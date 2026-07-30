"""Interpreta le pagine del Calendario Esami e comunica con ESSE3.

Il modulo trasforma le pagine HTML in dati strutturati, controlla i
valori ricevuti e prepara le richieste HTTP. Il cookie di sessione
resta nella sessione del server e non viene mai restituito.
"""
from __future__ import annotations

import re
from datetime import date
from urllib.parse import parse_qs, urlencode, urlparse

try:  # dipendenza di produzione; il parser resta testabile anche offline
    import httpx
except ImportError:  
    httpx = None
from bs4 import BeautifulSoup

from ...core.errors import (Conflict, InvalidCredentials, SessionExpired,
                            UpstreamContract, UpstreamTimeout,
                            UpstreamUnavailable, ValidationFailed)

# Indirizzi delle pagine usate per leggere e salvare i dati.
BASE_PATH = "/auth/docente/CalendarioEsami"
TEACHINGS_PATH = f"{BASE_PATH}/ListaAttivitaCalEsa.do"
LIST_PATH = f"{BASE_PATH}/ElencoAppelliCalEsa.do"
FORM_PATH = f"{BASE_PATH}/InserisciAggiornaAppelloCalEsa.do"
SUBMIT_PATH = f"{BASE_PATH}/InserisciAggiornaAppelloCalEsaSubmit.do"
ROOMS_PATH = f"{BASE_PATH}/LookupAule.do"
# Punto d'ingresso usato solo per innescare il login SSO (Shibboleth):
# qualunque pagina protetta andrebbe bene, questa è quella verificata.
LOGIN_ENTRY_PATH = "/auth/docente/AreaDocente.do"


# ----------------------------------------------------------------- login SSO


def _parse_form(html: str, predicate) -> tuple[str, list[tuple[str, str]]] | None:
    """Trova il primo <form> che soddisfa predicate e ne estrae action e campi.

    I campi sono una lista di coppie (nome, valore), non un dict: alcuni
    moduli Shibboleth ripetono lo stesso nome più volte (es. un
    `_shib_idp_consentIds` per ogni attributo da rilasciare) e un dict li
    collasserebbe in uno solo, invalidando il consenso. Le checkbox non
    spuntate e i radio non selezionati non vengono inclusi, esattamente come
    farebbe un browser che sottomette il modulo così com'è.
    """
    soup = BeautifulSoup(html, "html.parser")
    for form in soup.find_all("form"):
        fields: list[tuple[str, str]] = []
        for node in form.find_all(["input", "button"]):
            name = node.get("name")
            if not name:
                continue
            kind = (node.get("type") or "text").lower()
            if kind in ("checkbox", "radio") and not node.has_attr("checked"):
                continue
            # Un browser vero sottomette solo il pulsante su cui si clicca:
            # qui si sceglie sempre "procedi/accetta", mai varianti come
            # "_eventId_AttributeReleaseRejected" (altrimenti Shibboleth
            # riceve entrambi gli _eventId_* insieme e rifiuta il modulo).
            if kind == "submit" and name.startswith("_eventId_") and name != "_eventId_proceed":
                continue
            fields.append((name, node.get("value", "")))
        if predicate(fields):
            return form.get("action") or "", fields
    return None


def _has_field(fields: list[tuple[str, str]], name: str) -> bool:
    return any(n == name for n, _ in fields)


def _set_field(fields: list[tuple[str, str]], name: str, value: str) -> list[tuple[str, str]]:
    return [(n, v) for n, v in fields if n != name] + [(name, value)]


def _absolute(response, action: str) -> str:
    """Risolve un URL relativo (action di un form, href di un link).

    Le pagine di ESSE3 dichiarano `<base href=".../">`: gli URL relativi
    vanno risolti contro quello (la radice del sito), non contro il path
    della pagina corrente, altrimenti si finisce su percorsi annidati
    inesistenti (es. .../auth/docente/auth/UserProfileSubmit.do invece di
    .../auth/UserProfileSubmit.do). Le pagine dell'IdP non hanno un <base>:
    lì si risolve come sempre contro l'URL della risposta corrente.
    """
    if not action:
        return str(response.url)
    match = re.search(r'<base\s+href=["\']([^"\']+)["\']', response.text, re.I)
    root = match.group(1) if match else str(response.url)
    return str(httpx.URL(root).join(action))


def _post_form(client, url: str, fields: list[tuple[str, str]]):
    # httpx non incoraggia chiavi ripetute con un semplice dict; qui serve
    # (vedi `_shib_idp_consentIds`), quindi si codifica a mano preservandole.
    body = urlencode(fields, doseq=False)
    return client.post(url, content=body,
                       headers={"Content-Type": "application/x-www-form-urlencoded"})


def perform_shibboleth_login(client, base_url: str, username: str, password: str,
                             max_steps: int = 8) -> None:
    """Esegue il login SSO (Shibboleth) e sceglie il profilo Docente.

    L'area web di ESSE3 non accetta più Basic Auth diretta su Logon.do:
    l'ateneo protegge l'accesso con SSO federato (verificato il 30/07/2026).
    Il flusso reale, tutto lato IdP prima di tornare sul dominio ESSE3:
    una o più pagine "ponte" auto-inviate da JavaScript nel browser (probing
    del supporto al localStorage, poi eventuale consenso agli attributi, poi
    la risposta SAML da ripostare al Service Provider) e in mezzo il vero
    modulo di login (username/password + csrf_token). Qui si va avanti
    sottomettendo ogni modulo incontrato così com'è finché non si atterra
    di nuovo sul dominio di ESSE3 — è la stessa cosa che farebbe il
    JavaScript del browser, solo esplicita. Infine, per gli account con più
    profili (es. un docente con anche una vecchia carriera studente), sceglie
    esplicitamente "Docente".

    Il cookie jar del client (passato già autenticato dal chiamante) viene
    popolato con tutte le sessioni valide (SP Shibboleth e app server): non
    serve più gestire un JSESSIONID a mano.
    """
    sp_host = httpx.URL(base_url).host
    response = client.get(base_url.rstrip("/") + LOGIN_ENTRY_PATH)
    credentials_sent = False

    for _ in range(max_steps):
        if response.url.host == sp_host:
            break
        found = _parse_form(response.text, lambda f: _has_field(f, "j_username"))
        if found is not None:
            if credentials_sent:
                raise InvalidCredentials("Codice fiscale o password non validi (login SSO).")
            action, fields = found
            fields = _set_field(fields, "j_username", username)
            fields = _set_field(fields, "j_password", password)
            response = _post_form(client, _absolute(response, action), fields)
            credentials_sent = True
            continue
        # Pagina "ponte" (probing localStorage, consenso attributi, risposta
        # SAML auto-inviata): si sottomette così com'è, come farebbe il JS.
        found = _parse_form(response.text, lambda f: bool(f))
        if found is None:
            raise UpstreamContract("Login SSO: pagina intermedia non riconosciuta.")
        action, fields = found
        response = _post_form(client, _absolute(response, action), fields)
    else:
        raise UpstreamContract("Login SSO: troppi passaggi, flusso non riconosciuto.")

    if not credentials_sent:
        raise UpstreamContract("Login SSO: modulo di accesso non incontrato.")

    # Account con più profili (es. docente con anche una vecchia carriera
    # studente): sceglie esplicitamente "Docente", altrimenti si resta sulla
    # pagina di scelta invece che nell'area riservata.
    soup = BeautifulSoup(response.text, "html.parser")
    docente_link = next(
        (a for a in soup.find_all("a", href=True)
         if "UserProfileSubmit.do" in a["href"]
         and "docente" in a.get_text(" ", strip=True).lower()),
        None)
    if docente_link is not None:
        client.get(_absolute(response, docente_link["href"]))

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
    form_tag = soup.find("form")
    return {"modalita": "nuovo" if hidden.get("NEW_APP") == "1" else "modifica",
            "campi": fields, "hidden": hidden,
            "_action": form_tag.get("action") if form_tag else None}


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
    def __init__(self, client: httpx.Client, dry_run: bool = True):
        # `client` arriva già autenticato (perform_shibboleth_login):
        # il suo cookie jar porta sia la sessione SP (Shibboleth) sia
        # quella dell'app server (JSESSIONID), niente da gestire a mano.
        self.client, self.dry_run = client, dry_run
        self._list_page = None  # ultima risposta di "Lista Appelli" caricata

    def _request(self, method, url, **kwargs):
        try: response = self.client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc: raise UpstreamTimeout("Timeout verso calendario ESSE3.") from exc
        except httpx.HTTPError as exc: raise UpstreamUnavailable("Errore di rete verso calendario ESSE3.") from exc
        # follow_redirects=True: se la sessione e' scaduta si finisce di
        # nuovo sul modulo di login SSO, mai su un redirect da inseguire.
        if response.status_code in (401, 403) or "j_username" in response.text[:4000]:
            raise SessionExpired("Sessione web ESSE3 scaduta: eseguire di nuovo il login.")
        if response.status_code >= 400: raise UpstreamUnavailable(f"ESSE3 ha risposto {response.status_code}.")
        return response

    def teachings(self):
        response = self._request("GET", TEACHINGS_PATH,
                                 params={"menu_opened_cod": "menu_link-navbox_docenti_Didattica"})
        items = parse_teaching_list(response.text)
        if not items:
            raise UpstreamContract("Lista insegnamenti non riconosciuta o vuota.")
        return {"items": items, "count": len(items)}

    def _teaching_row(self, cds_id, ad_id, aa_id):
        """Trova, nella pagina "Lista Attività", il modulo (già con la
        sessione corretta al suo interno) che apre gli appelli
        dell'insegnamento indicato: ESSE3 non accetta un accesso diretto a
        ElencoAppelliCalEsa.do senza prima essere passati da qui
        (verificato il 30/07/2026 — risposta 500 altrimenti)."""
        response = self._request("GET", TEACHINGS_PATH,
                                 params={"menu_opened_cod": "menu_link-navbox_docenti_Didattica"})
        soup = BeautifulSoup(response.text, "html.parser")
        wanted = (str(cds_id), str(ad_id), str(aa_id))
        for row in soup.select("tr.detail_table"):
            cells = row.find_all("td", recursive=False)
            if len(cells) < 3:
                continue
            form = cells[2].find("form")
            if form is None:
                continue
            hidden = {n.get("name"): n.get("value", "") for n in form.find_all("input") if n.get("name")}
            if (hidden.get("CDS_ID"), hidden.get("AD_ID"), hidden.get("AA_ID")) == wanted:
                fields = [(n.get("name"), n.get("value", ""))
                         for n in form.find_all(["input", "select"]) if n.get("name")]
                return response, _absolute(response, form.get("action")), fields
        raise UpstreamContract(
            "Insegnamento non trovato nella Lista Attività (cdsId/adId/aaId non corrispondenti).")

    def list(self, cds_id, ad_id, aa_id, visibility="all"):
        _, action, fields = self._teaching_row(cds_id, ad_id, aa_id)
        response = _post_form(self.client, action, fields)
        if response.status_code in (401, 403) or "j_username" in response.text[:4000]:
            raise SessionExpired("Sessione web ESSE3 scaduta: eseguire di nuovo il login.")
        if response.status_code >= 400:
            raise UpstreamUnavailable(f"ESSE3 ha risposto {response.status_code}.")
        self._list_page = response
        result = parse_exam_list(response.text)
        # Il filtro passato/futuro/tutti richiede un secondo giro (il menu
        # "Visualizza" della pagina): più semplice e altrettanto corretto
        # filtrare qui sulla data già disponibile in ogni appello.
        if visibility in ("future", "past"):
            oggi = date.today().isoformat()
            tieni = (lambda d: d is not None and d >= oggi) if visibility == "future" \
                else (lambda d: d is not None and d < oggi)
            result["items"] = [i for i in result["items"] if tieni(i["data"])]
            result["count"] = len(result["items"])
        return result

    def new_form(self, cds_id, ad_id, aa_id, exam_type="PF"):
        self.list(cds_id, ad_id, aa_id)  # assicura il contesto "Lista Appelli" giusto
        submit_name = "new_pp" if exam_type == "PP" else "new_pf"
        soup = BeautifulSoup(self._list_page.text, "html.parser")
        form = next((f for f in soup.find_all("form")
                    if f.find(attrs={"name": submit_name})), None)
        if form is None:
            raise UpstreamContract("Modulo nuovo appello non trovato nella Lista Appelli.")
        fields = []
        for node in form.find_all(["input", "select"]):
            name = node.get("name")
            if not name:
                continue
            kind = (node.get("type") or "text").lower()
            if kind in ("image", "submit"):
                continue
            if kind in ("checkbox", "radio") and not node.has_attr("checked"):
                continue
            fields.append((name, node.get("value", "")))
        submit_node = form.find(attrs={"name": submit_name})
        fields.append((submit_name, submit_node.get("value", "")))
        response = self._request("POST", _absolute(self._list_page, form.get("action")),
                                 content=urlencode(fields),
                                 headers={"Content-Type": "application/x-www-form-urlencoded"})
        form_data = parse_exam_form(response.text)
        if not form_data["campi"]:
            raise UpstreamContract("Form nuovo appello non riconosciuto.")
        if form_data["_action"]:
            form_data["_action"] = _absolute(response, form_data["_action"])
        return form_data

    def edit_form(self, app_id, cds_id, ad_id, aa_id, exam_type="PF"):
        self.list(cds_id, ad_id, aa_id)  # assicura il contesto "Lista Appelli" giusto
        soup = BeautifulSoup(self._list_page.text, "html.parser")
        target_href = None
        for a in soup.find_all("a", href=True):
            if "InserisciAggiornaAppelloCalEsa.do" not in a["href"]:
                continue
            query = parse_qs(urlparse(a["href"]).query)
            if query.get("APP_ID", [None])[0] == str(app_id):
                target_href = a["href"]
                break
        if target_href is None:
            raise UpstreamContract(f"Appello {app_id} non trovato nella Lista Appelli.")
        response = self._request("GET", _absolute(self._list_page, target_href))
        form_data = parse_exam_form(response.text)
        if not form_data["campi"]:
            raise UpstreamContract("Form modifica appello non riconosciuto.")
        if form_data["_action"]:
            form_data["_action"] = _absolute(response, form_data["_action"])
        return form_data

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
        action = form.get("_action") or SUBMIT_PATH
        response = self._request("POST", action, data=payload)
        parsed = parse_exam_form(response.text)
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        if re.search(r"\berror[ei]?\b|operazione non riuscita", text, re.I):
            raise Conflict("ESSE3 ha rifiutato il salvataggio.")
        return {"dryRun": False, "applied": True, "appello": model,
                "form": parsed if parsed["campi"] else None}
