"""Registro lezioni (diario delle lezioni svolte) — area web ESSE3.

Sola lettura: elenco dei registri per anno accademico offerta e, per
ciascuno, le singole lezioni inserite (data/ore/titolo/tipo attività) con
il riepilogo ore previste/inserite/mancanti. Nessuna scrittura (inserimento
nuova lezione) in questa prima versione: la form "Inserisci nuova attività"
non è stata ancora verificata con un salvataggio reale.

Verificato il 31/07/2026 navigando l'area docente reale (Raffaele Montella):
- lista: auth/docente/RegistroDocente/Home.do?AA_OFF_ID=<anno>
- dettaglio: auth/docente/RegistroDocente/EnterRegistro.do?AA_OFF_ID=...&
  AD_LOG_ID=...&PART_COD=...&FAT_PART_COD=N0&DOM_PART_COD=N0&TIPO_SPEC_COD=
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup

from ...core.errors import SessionExpired, UpstreamTimeout, UpstreamUnavailable

_DATE_DMY = re.compile(r"^(\d{2})/(\d{2})/(\d{4})")


def _normalize_date(value: str) -> str:
    match = _DATE_DMY.match(value.strip())
    if not match:
        return value
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}"

BASE_PATH = "/auth/docente/RegistroDocente/"
LIST_PATH = BASE_PATH + "Home.do"
DETAIL_PATH = BASE_PATH + "EnterRegistro.do"

_ROW_HEADING = re.compile(
    r"(.+?)\s*-\s*\[([A-Z0-9]+)\]", re.S)
_ACTIVITY_HEADING = re.compile(
    r"Attività:\s*(.+?)\s*\[([A-Z0-9]+)\]", re.S)


def _text(node) -> str:
    if not node:
        return ""
    return node.get_text(" ", strip=True).replace("\xa0", " ")


def parse_year_options(html: str) -> list[dict]:
    """Anni accademici offerta disponibili nel selettore della lista."""
    soup = BeautifulSoup(html, "html.parser")
    select = soup.find("select", attrs={"name": "AA_OFF_ID"})
    if select is None:
        return []
    years = []
    for option in select.find_all("option"):
        label = _text(option)
        if not label:
            continue
        value = option.get("value", "").strip()
        years.append({"aaOffId": int(value) if value.isdigit() else None,
                     "label": label,
                     "selected": option.has_attr("selected")})
    return years


def parse_register_list(html: str) -> list[dict]:
    """Elenco dei registri (uno per insegnamento/partizione) per l'anno
    accademico correntemente selezionato nella pagina."""
    if "j_username" in html[:4000]:
        raise SessionExpired("Sessione ESSE3 scaduta durante la lettura del registro.")

    soup = BeautifulSoup(html, "html.parser")
    table = None
    for candidate in soup.find_all("table", class_="detail_table"):
        headers = [_text(th) for th in candidate.find_all("th")]
        if any("Attività" in h or "Periodo" in h for h in headers):
            table = candidate
            break
    if table is None:
        return []

    rows = []
    for tr in table.find_all("tr"):
        cells = tr.find_all("td")
        if len(cells) < 5:
            continue
        link = cells[0].find("a", href=True)
        if link is None:
            continue
        match = re.search(r"AD_LOG_ID=(\d+).*?PART_COD=([^&]*)", link["href"])
        if not match:
            continue
        ad_log_id = int(match.group(1))
        part_cod = match.group(2)
        aa_off_match = re.search(r"AA_OFF_ID=(\d+)", link["href"])
        aa_off_id = int(aa_off_match.group(1)) if aa_off_match else None

        heading = _ROW_HEADING.match(_text(cells[1]))
        ad_des = heading.group(1).strip() if heading else _text(cells[1])
        ad_cod = heading.group(2).strip() if heading else ""

        ore_text = _text(cells[3])
        stato_img = cells[5].find("img") if len(cells) > 5 else None
        stato = stato_img.get("title") or stato_img.get("alt") if stato_img else ""

        rows.append({
            "adLogId": ad_log_id,
            "partCod": part_cod,
            "aaOffId": aa_off_id,
            "adDes": ad_des,
            "adCod": ad_cod,
            "partizione": _text(cells[2]),
            "orePreviste": int(ore_text) if ore_text.isdigit() else None,
            "periodo": _text(cells[4]),
            "stato": stato or "",
        })
    return rows


def _labelled_value(soup: BeautifulSoup, label: str) -> str:
    """Trova un <th>/<label> con questo testo e ritorna il valore nella
    cella successiva — schema ricorrente in tutte le pagine tplForm ESSE3."""
    for th in soup.find_all(["th", "td"]):
        testo = _text(th)
        if testo.startswith(label):
            sib = th.find_next_sibling("td")
            if sib is not None:
                return _text(sib)
    return ""


def parse_register_detail(html: str) -> dict:
    """Dettaglio di un registro: intestazione, riepilogo ore, righe lezione."""
    if "j_username" in html[:4000]:
        raise SessionExpired("Sessione ESSE3 scaduta durante la lettura del registro.")

    soup = BeautifulSoup(html, "html.parser")
    full_text = soup.get_text(" ", strip=True)

    heading = _ACTIVITY_HEADING.search(full_text)
    ad_des = heading.group(1).strip() if heading else ""
    ad_cod = heading.group(2).strip() if heading else ""

    stato_registro = _labelled_value(soup, "Stato Registro:")
    docente = _labelled_value(soup, "Docente:")
    anno_accademico = _labelled_value(soup, "Anno Accademico:")

    def _ore(label: str) -> int | None:
        for td in soup.find_all("td", class_="tplForm"):
            if _text(td) == label:
                sib = td.find_next_sibling("td")
                if sib is not None:
                    bold = sib.find("b")
                    valore = _text(bold) if bold else _text(sib)
                    return int(valore) if valore.isdigit() else None
        return None

    righe = []
    for table in soup.find_all("table", class_="detail_table"):
        headers = [_text(th) for th in table.find_all("th")]
        if "Data" not in headers or "Titolo" not in headers:
            continue
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            form = cells[0].find("form")
            dett_id = None
            if form is not None and form.get("action"):
                match = re.search(r"DETT_REG_ID=(\d+)", form["action"])
                dett_id = int(match.group(1)) if match else None
            ore_testo = _text(cells[2])
            righe.append({
                "dettRegId": dett_id,
                "data": _normalize_date(_text(cells[1])),
                "ore": float(ore_testo.replace(",", ".")) if ore_testo else None,
                "titolo": _text(cells[3]),
                "tipoAttivita": _text(cells[4]),
            })
        break

    return {
        "adDes": ad_des,
        "adCod": ad_cod,
        "annoAccademico": anno_accademico,
        "docente": docente,
        "statoRegistro": stato_registro,
        "orePreviste": _ore("ore previste"),
        "oreInserite": _ore("ore inserite"),
        "oreMancanti": _ore("ore mancanti"),
        "lezioni": righe,
    }


class RegisterAdapter:
    """Registro lezioni per la sessione autenticata (client web già loggato)."""

    def __init__(self, client) -> None:
        self._client = client

    def _request(self, method: str, path: str, **kwargs):
        try:
            response = self._client.request(method, path, **kwargs)
        except Exception as exc:  # httpx.TimeoutException / HTTPError
            import httpx
            if isinstance(exc, httpx.TimeoutException):
                raise UpstreamTimeout("Timeout verso ESSE3.") from exc
            if isinstance(exc, httpx.HTTPError):
                raise UpstreamUnavailable("Errore di rete verso ESSE3.") from exc
            raise
        if response.status_code in (401, 403) or "j_username" in response.text[:4000]:
            raise SessionExpired("Sessione web ESSE3 scaduta: eseguire di nuovo il login.")
        if response.status_code >= 400:
            raise UpstreamUnavailable(f"ESSE3 ha risposto {response.status_code}.")
        return response

    def years(self, aa_off_id: int | None = None) -> dict:
        params = {"AA_OFF_ID": aa_off_id} if aa_off_id is not None else {}
        response = self._request("GET", LIST_PATH, params=params)
        items = parse_year_options(response.text)
        return {"items": items, "count": len(items)}

    def list(self, aa_off_id: int | None = None) -> dict:
        params = {"AA_OFF_ID": aa_off_id} if aa_off_id is not None else {}
        response = self._request("GET", LIST_PATH, params=params)
        items = parse_register_list(response.text)
        return {"items": items, "count": len(items)}

    def detail(self, ad_log_id: int, aa_off_id: int, part_cod: str = "S1") -> dict:
        params = {"AA_OFF_ID": aa_off_id, "FAT_PART_COD": "N0",
                  "DOM_PART_COD": "N0", "AD_LOG_ID": ad_log_id,
                  "PART_COD": part_cod, "TIPO_SPEC_COD": ""}
        response = self._request("GET", DETAIL_PATH, params=params)
        return parse_register_detail(response.text)
