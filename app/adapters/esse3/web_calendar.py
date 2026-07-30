"""Interpreta le pagine del Calendario Esami e comunica con ESSE3.

Il modulo trasforma le pagine HTML in dati strutturati, controlla i
valori ricevuti e prepara le richieste HTTP. Il cookie di sessione
resta nella sessione del server e non viene mai restituito.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qs, urlparse

try:  # dipendenza di produzione; il parser resta testabile anche offline
    import httpx
except ImportError:  
    httpx = None
from bs4 import BeautifulSoup

from ...core.errors import (Conflict, SessionExpired, UpstreamContract,
                            UpstreamTimeout, UpstreamUnavailable,
                            ValidationFailed)

# Indirizzi delle pagine usate per leggere e salvare i dati.
BASE_PATH = "/auth/docente/CalendarioEsami"
TEACHINGS_PATH = f"{BASE_PATH}/ListaAttivitaCalEsa.do"
LIST_PATH = f"{BASE_PATH}/ElencoAppelliCalEsa.do"
FORM_PATH = f"{BASE_PATH}/InserisciAggiornaAppelloCalEsa.do"
SUBMIT_PATH = f"{BASE_PATH}/InserisciAggiornaAppelloCalEsaSubmit.do"
ROOMS_PATH = f"{BASE_PATH}/LookupAule.do"

APP = "/WS/DataSet[@LocalEntityName='APP_CAL_ESA_WEB']/Row/"
LOG = "/WS/DataSet[@LocalEntityName='APP_LOG_DATI_WEB']/Row[@Num='1']/"
# Collega i nomi usati dall’API ai campi del modulo HTML.
FIELD_MAP = {
    "verbalizzazione": APP + "tipo_gest_app_cod",
    "dataAppello": APP + "data_inizio_app",
    "tipoEsame": APP + "tipo_iscr_cod_prev",
    "iscrizioniDal": APP + "data_inizio_iscr",
    "iscrizioniAl": APP + "data_fine_iscr",
    "descrizione": APP + "des",
    "note": APP + "note",
    "prenotabileDa": APP + "cond_id",
    "riservatoDocente": APP + "riservato_flg",
    "edificioId": LOG + "edificio_id",
    "aulaId": LOG + "aula_id",
    "postiMax": LOG + "numero_max",
    "partizionamento": LOG + "dom_part_cod",
    "appLogId": LOG + "app_log_id",
    "ora": "hh_esa", "minuti": "mm_esa", "sessione": "SES_ID_AA_SES_ID",
}
REVERSE_FIELDS = {v: k for k, v in FIELD_MAP.items()}
# Campi che non possono essere modificati.
READ_ONLY = {"verbalizzazione", "appLogId"}
EDITABLE = set(FIELD_MAP) - READ_ONLY
# Campi obbligatori per salvare i dati.
REQUIRED = {"dataAppello", "ora", "minuti", "iscrizioniDal", "iscrizioniAl", "descrizione"}
# Valori ammessi per ora e minuti.
HOURS = [f"{h:02d}" for h in range(8, 24)]
MINUTES = ["00", "15", "30", "45"]
# Traduce le icone della pagina in stati leggibili.
STATE_ICONS = {
    "defAppInCorso.gif": "in_corso", "defAppChiuso.gif": "chiuso",
    "defAppNoAperto.gif": "non_aperto", "defAppNonPrevisto.gif": "non_previsto",
}
# Traduce le icone delle azioni disponibili.
ACTION_ICONS = {
    "defAppOpen.jpg": "modifica", "defAppStudent.gif": "lista_iscritti",
    "defAppAttenzione.gif": "nessun_iscritto", "defAppDel.gif": "cancella",
}
# Traduce le icone informative mostrate accanto alla riga.
BADGE_ICONS = {
    "app_provap.jpg": "prova_parziale", "app_online.gif": "verbalizzazione_online",
    "app_firma_digitale.gif": "firma_digitale",
}


def _iso(value: str | None) -> str | None:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (value or "").strip())
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


def _italian(value: str | None) -> str:
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", (value or "").strip())
    return f"{m[3]}/{m[2]}/{m[1]}" if m else ""


def _icon(tag) -> str:
    return (tag.get("src") or "").rsplit("/", 1)[-1]


def _state(cell) -> dict:
    for image in cell.find_all("img"):
        icon = _icon(image)
        if icon in STATE_ICONS:
            return {"code": STATE_ICONS[icon], "label": image.get("title") or None}
    return {"code": "sconosciuto", "label": cell.get_text(" ", strip=True) or None}


# Trasforma la tabella HTML in un elenco di elementi.
def parse_exam_list(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for row in soup.select("tr.detail_table"):
        edit = row.find("a", href=lambda h: h and "InserisciAggiornaAppelloCalEsa.do" in h)
        if not edit:
            continue
        query = parse_qs(urlparse(edit["href"]).query)
        def one(key, default=None): return query.get(key, [default])[0]
        cells = row.find_all("td", recursive=False)
        if len(cells) < 10:
            continue
        raw_when = cells[2].get_text(" ", strip=True)
        match = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2})(.*)", raw_when)
        actions = []
        for image in row.find_all(["img", "input"]):
            icon = _icon(image)
            if icon in ACTION_ICONS:
                actions.append({"kind": ACTION_ICONS[icon], "label": image.get("title") or image.get("alt") or None})
        badges = []
        for image in row.find_all("img"):
            icon = _icon(image)
            if icon in BADGE_ICONS:
                badges.append({"code": BADGE_ICONS[icon], "label": image.get("title") or None})
        def number(index):
            raw = cells[index].get_text(" ", strip=True) if len(cells) > index else ""
            return int(raw) if raw.isdigit() else 0
        enrolled = number(4)
        items.append({
            "appId": int(one("APP_ID")), "tipoProva": one("TIPO_PROVA"),
            "descrizione": cells[0].get_text(" ", strip=True),
            "data": _iso(match.group(1)) if match else None,
            "ora": match.group(2) if match else None,
            "luogo": match.group(3).strip() or None if match else None,
            "badges": badges,
            "iscrizioni": {"stato": _state(cells[3]), "iscritti": enrolled},
            "esiti": {"stato": _state(cells[5]), "inseriti": number(6)},
            "verbali": {"stato": _state(cells[7]), "caricati": number(8)},
            "azioni": actions,
            "permessi": {"modificabile": any(a["kind"] == "modifica" for a in actions),
                         "cancellabile": any(a["kind"] == "cancella" for a in actions),
                         "haIscritti": enrolled > 0},
            "contesto": {"cdsId": one("CDS_ID"), "adId": one("AD_ID"), "aaId": one("AA_ID")},
        })
    page_text = soup.get_text(" ", strip=True)
    teaching = re.search(r"Appelli di:\s*(.+?\[[^]]+\])", page_text, re.I)
    course = re.search(r"Corso di [Ss]tudio:?\s*(.+?\[[^]]+\](?:\s*\([^)]+\))?)", page_text)
    return {"contesto": {"insegnamento": teaching.group(1) if teaching else None,
                          "corsoDiStudio": course.group(1) if course else None},
            "items": items, "count": len(items)}


def _field_value(node):
    if node.name == "select":
        selected = node.find("option", selected=True) or node.find("option")
        return selected.get("value", "") if selected else ""
    if node.name == "textarea":
        return node.get_text()
    if (node.get("type") or "text").lower() == "checkbox":
        return node.has_attr("checked")
    return node.get("value", "")


# Trasforma la pagina "Lista Attività" in un elenco di insegnamenti, con
# cdsId/adId/aaId gia' pronti per /professors/me/exam-sessions: a differenza
# della vecchia API v1 professor/getCourses/{aaId} (che va interrogata con
# l'anno "giusto", non sempre quello restituito da getSession — a inizio
# anno accademico la nuova didattica non e' ancora pubblicata li'), questa
# pagina elenca TUTTI gli insegnamenti del docente su TUTTI gli anni, ognuno
# gia' abbinato al proprio aaId corretto: nessun anno da indovinare.
def parse_teaching_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for row in soup.select("tr.detail_table"):
        cells = row.find_all("td", recursive=False)
        if len(cells) < 3:
            continue
        form = cells[2].find("form")
        if form is None:
            continue
        hidden = {node.get("name"): node.get("value", "")
                 for node in form.find_all("input") if node.get("name")}
        ad_id, cds_id, aa_id = hidden.get("AD_ID"), hidden.get("CDS_ID"), hidden.get("AA_ID")
        if not (ad_id and cds_id and aa_id):
            continue
        raw_ad = cells[0].get_text(" ", strip=True)
        match = re.match(r"(.+?)\s*\[([^\]]+)\]\s*$", raw_ad)
        ad_des, ad_code = (match.group(1), match.group(2)) if match else (raw_ad, None)
        items.append({
            "adId": int(ad_id), "cdsId": int(cds_id), "aaId": int(aa_id),
            "adDes": ad_des, "adCode": ad_code,
            "cdsDes": cells[1].get_text(" ", strip=True),
        })
    return items


# Trasforma il modulo HTML in campi, valori e opzioni.
def parse_exam_form(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    fields, hidden = {}, {}
    by_name = {}
    for node in soup.find_all(["input", "select", "textarea"]):
        name = node.get("name")
        if name: by_name.setdefault(name, []).append(node)
    for clean, original in FIELD_MAP.items():
        nodes = by_name.get(original, [])
        if not nodes: continue
        node = nodes[0]
        kind = (node.get("type") or node.name).lower()
        options = []
        if node.name == "select":
            options = [{"value": o.get("value", ""), "label": o.get_text(" ", strip=True)} for o in node.find_all("option")]
        elif kind == "radio":
            options = [{"value": n.get("value", ""), "label": None} for n in nodes]
            node = next((n for n in nodes if n.has_attr("checked")), nodes[0])
        value = _field_value(node)
        if clean in {"dataAppello", "iscrizioniDal", "iscrizioniAl"} and value:
            value = _iso(str(value))
        fields[clean] = {"value": value, "type": kind, "editable": clean not in READ_ONLY and not node.has_attr("disabled")}
        if options: fields[clean]["options"] = options
        if clean == "verbalizzazione": fields[clean]["readOnlyReason"] = "Valore imposto dall'ateneo."
    for name, nodes in by_name.items():
        node = nodes[0]
        if name not in REVERSE_FIELDS and (node.get("type") or "").lower() == "hidden":
            hidden[name] = node.get("value", "")
    return {"modalita": "nuovo" if hidden.get("NEW_APP") == "1" else "modifica",
            "campi": fields, "hidden": hidden}


# Estrae i valori attuali da un modulo gia analizzato.
def model_from_form(form: dict) -> dict:
    return {name: field.get("value") for name, field in form["campi"].items()}


# Controlla date, orari, campi obbligatori e opzioni valide.
def validate(model: dict, form: dict) -> None:
    errors = []
    for key in REQUIRED:
        if model.get(key) in (None, ""): errors.append({"field": key, "code": "required"})
    for key in (set(model) - EDITABLE - READ_ONLY):
        errors.append({"field": key, "code": "unknown_field"})
    if str(model.get("ora", "")).zfill(2) not in HOURS: errors.append({"field": "ora", "code": "invalid_hour"})
    if str(model.get("minuti", "")).zfill(2) not in MINUTES: errors.append({"field": "minuti", "code": "invalid_minutes"})
    for key in ("dataAppello", "iscrizioniDal", "iscrizioniAl"):
        try: date.fromisoformat(str(model.get(key, "")))
        except ValueError: errors.append({"field": key, "code": "invalid_date"})
    if model.get("iscrizioniDal") and model.get("iscrizioniAl") and model["iscrizioniDal"] > model["iscrizioniAl"]:
        errors.append({"field": "iscrizioniAl", "code": "invalid_interval"})
    if model.get("iscrizioniAl") and model.get("dataAppello") and model["iscrizioniAl"] > model["dataAppello"]:
        errors.append({"field": "iscrizioniAl", "code": "after_exam"})
    if model.get("aulaId") and not model.get("edificioId"):
        errors.append({"field": "edificioId", "code": "building_required"})
    for key, field in form["campi"].items():
        options = [str(o["value"]) for o in field.get("options", []) if str(o["value"]) != ""]
        if options and model.get(key) not in (None, "") and str(model[key]) not in options:
            errors.append({"field": key, "code": "option_not_available"})
    if errors: raise ValidationFailed("Campi non validi: " + ", ".join(f"{e['field']} ({e['code']})" for e in errors))


# Costruisce i dati nel formato accettato dal server remoto.
def build_payload(model: dict, hidden: dict, submit: str = "save", notifications: dict | None = None) -> dict:
    payload = dict(hidden)
    for clean, original in FIELD_MAP.items():
        value = model.get(clean, "")
        if clean in {"dataAppello", "iscrizioniDal", "iscrizioniAl"}: value = _italian(value)
        if clean == "riservatoDocente":
            if value: payload[original] = "1"
            else: payload.pop(original, None)
        else: payload[original] = "" if value is None else str(value)
    payload[FIELD_MAP["verbalizzazione"]] = model.get("verbalizzazione") or "FWP"
    payload[FIELD_MAP["partizionamento"]] = model.get("partizionamento") or "N0__N0"
    names = {"cambioData": "NOTIFICA_CAMBIO_DATA", "cambioLuogo": "NOTIFICA_CAMBIO_LUOGO",
             "cambioDataLuogo": "NOTIFICA_CAMBIO_DATA_LUOGO"}
    for key, original in names.items():
        if notifications and key in notifications: payload[original] = "1" if notifications[key] else "0"
    payload["sbmNewApp" if submit == "saveAndAdd" else "sbmDef"] = "Salva e aggiungi nuovo" if submit == "saveAndAdd" else "Salva"
    return payload


# Esegue le richieste HTTP e usa le funzioni di lettura del modulo.
class WebCalendarAdapter:
    def __init__(self, base_url: str, jsessionid: str, timeout_s: float = 25.0,
                 dry_run: bool = True, client: httpx.Client | None = None):
        if not re.fullmatch(r"[A-Fa-f0-9]{32}(?:\.[A-Za-z0-9_-]{1,120})?", jsessionid):
            raise ValidationFailed("JSESSIONID ESSE3 non plausibile.")
        self.base_url, self.jsessionid, self.dry_run = base_url.rstrip("/"), jsessionid, dry_run
        if client is None and httpx is None:
            raise RuntimeError("Installare le dipendenze da requirements.txt (httpx).")
        self.client = client or httpx.Client(base_url=self.base_url, timeout=timeout_s,
            follow_redirects=False, headers={"User-Agent": "uniparthenope-v3-gateway/3.1",
                                            "Cookie": f"JSESSIONID={jsessionid}"})

    def _url(self, path):
        stem, sep, query = path.partition("?")
        return f"{stem};jsessionid={self.jsessionid}{sep}{query}"

    def _request(self, method, path, **kwargs):
        try: response = self.client.request(method, self._url(path), **kwargs)
        except httpx.TimeoutException as exc: raise UpstreamTimeout("Timeout verso calendario ESSE3.") from exc
        except httpx.HTTPError as exc: raise UpstreamUnavailable("Errore di rete verso calendario ESSE3.") from exc
        location = response.headers.get("location", "")
        body = response.text
        if response.status_code in (401, 403) or "Logon.do" in location or "idp.uniparthenope.it" in location or ("Logon.do" in body and "j_username" in body):
            raise SessionExpired("Sessione web ESSE3 scaduta: acquisire un nuovo JSESSIONID.")
        if response.status_code >= 400: raise UpstreamUnavailable(f"ESSE3 ha risposto {response.status_code}.")
        return response

    def teachings(self):
        items = parse_teaching_list(self._request("GET", TEACHINGS_PATH).text)
        if not items:
            raise UpstreamContract("Lista insegnamenti non riconosciuta o vuota.")
        return {"items": items, "count": len(items)}

    def list(self, cds_id, ad_id, aa_id, visibility="all"):
        params = {"CDS_ID": cds_id, "AD_ID": ad_id, "AA_ID": aa_id, "MIN_AA_CAL_ID": "0",
                  "MAX_AA_CAL_ID": "", "VIS_APP": "1", "VIS_DETT": "-100", "VIEW_DETT_ESACOM": "1",
                  "FILTRO_DATE": "0", "FILTRO_DES_EDIFICIO": "0",
                  "MOD_VIS": {"future": "1", "all": "2", "past": "3"}.get(visibility, "2")}
        return parse_exam_list(self._request("GET", LIST_PATH, params=params).text)

    def new_form(self, cds_id, ad_id, aa_id, exam_type="PF"):
        data = {"CDS_ID": cds_id, "AD_ID": ad_id, "AA_ID": aa_id,
                "new_pp" if exam_type == "PP" else "new_pf": "Nuovo appello d'esame"}
        form = parse_exam_form(self._request("POST", LIST_PATH, data=data).text)
        if not form["campi"]: raise UpstreamContract("Form nuovo appello non riconosciuto.")
        return form

    def edit_form(self, app_id, cds_id, ad_id, aa_id, exam_type="PF"):
        params = {"APP_ID": app_id, "CDS_ID": cds_id, "AD_ID": ad_id, "AA_ID": aa_id,
                  "TIPO_PROVA": exam_type, "TYPE": "APP", "CHECK_MODIFICA": "1",
                  "VIS_PERIODI_ISCR": "1", "AULE_OBBL": "0", "MOD_SES": "1"}
        form = parse_exam_form(self._request("GET", FORM_PATH, params=params).text)
        if not form["campi"]: raise UpstreamContract("Form modifica appello non riconosciuto.")
        return form

    def rooms(self, building_id):
        response = self._request("GET", ROOMS_PATH, params={"edificioId": building_id})
        try: raw = response.json()
        except ValueError as exc: raise UpstreamContract("Elenco aule non JSON.") from exc
        if isinstance(raw, dict): raw = raw.get("rows") or raw.get("aule") or []
        return [{"id": str(x.get("id") or x.get("aulaId") or x.get("value") or ""),
                 "nome": str(x.get("des") or x.get("nome") or x.get("label") or ""),
                 "edificioId": str(building_id)} for x in raw]

    def save(self, form: dict, patch: dict, submit="save", notifications=None):
        unknown = set(patch) - EDITABLE
        if unknown: raise ValidationFailed("Campi non modificabili o sconosciuti: " + ", ".join(sorted(unknown)))
        current = model_from_form(form)
        model = {**current, **patch}
        if "edificioId" in patch and str(patch["edificioId"]) != str(current.get("edificioId", "")) and "aulaId" not in patch:
            model["aulaId"] = ""
        validate(model, form)
        payload = build_payload(model, form["hidden"], submit, notifications)
        if self.dry_run:
            return {"dryRun": True, "applied": False, "appello": model,
                    "warning": "Payload validato ma non inviato: manca un HAR di salvataggio riuscito."}
        response = self._request("POST", SUBMIT_PATH, data=payload)
        parsed = parse_exam_form(response.text)
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        if re.search(r"\berror[ei]?\b|operazione non riuscita", text, re.I):
            raise Conflict("ESSE3 ha rifiutato il salvataggio.")
        return {"dryRun": False, "applied": True, "appello": model,
                "form": parsed if parsed["campi"] else None}
