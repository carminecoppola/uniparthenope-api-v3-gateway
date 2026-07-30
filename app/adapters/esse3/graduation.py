"""Tesi di laurea/dottorato assegnate al docente (relatore/tutor/correlatore).

Stessa area web di ESSE3 del Calendario Esami (stesso login SSO, stesso
cookie jar), ma sola lettura: nessuna scrittura, quindi nessun dry-run da
gestire qui.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from ...core.errors import SessionExpired, UpstreamContract, UpstreamTimeout, UpstreamUnavailable

LAUREANDI_PATH = "/auth/docente/Graduation/LaureandiAssegnati.do"


def _iso(value: str | None) -> str | None:
    m = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", (value or "").strip())
    return f"{m[3]}-{m[2]}-{m[1]}" if m else None


def _titolo_corso(grezzo: str) -> str:
    # L'intestazione di ogni tabella arriva con tutto il testo della pagina
    # accumulato prima di "[COD]" (footable/jqGrid non isolano il blocco):
    # si tiene solo la coda breve che assomiglia al nome di un corso.
    match = re.match(r".*?([A-Za-zÀ-ÿ'.]+(?:\s+[A-Za-zÀ-ÿ'.]+){0,4})\s*$",
                     grezzo.strip())
    return match.group(1).strip() if match else grezzo.strip()


# Trasforma la pagina "Laureandi assegnati" in un elenco di tesi. La pagina
# ha una tabella per ogni corso di studio/dottorato per cui il docente ha
# tesi assegnate; l'id di ogni tabella ("tableLaureandiAssegnati<COD>")
# contiene già il codice del corso, l'unico identificatore affidabile —
# l'intestazione testuale ("NOME [COD] - Corso di ...") che la precede è
# frammentata in modo incoerente dallo script della pagina (footable/jqGrid
# ci mescolano dentro codice JS), quindi si usa solo come etichetta
# "a titolo informativo" e si scarta se non sembra un nome di corso breve.
def parse_laureandi(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    full_text = re.sub(r"\s+", " ", soup.get_text(" "))
    intestazioni = {
        cod.strip(): (des_grezzo, tipo)
        for des_grezzo, cod, tipo in re.findall(
            r"(.*?)\[([A-Z0-9]+)\]\s*-\s*(.*?)(?=Matricola|var arrSelected)",
            full_text)
    }

    tabelle = soup.find_all(
        "table", id=lambda x: bool(x) and x.startswith("tableLaureandiAssegnati"))

    items = []
    for tabella in tabelle:
        cod = (tabella.get("id") or "").replace("tableLaureandiAssegnati", "")
        des_grezzo, tipo = intestazioni.get(cod, (None, None))
        des = _titolo_corso(des_grezzo) if des_grezzo else None
        if des is not None and len(des) > 60:
            des = None  # intestazione non isolata correttamente: meglio niente che spazzatura
        corso = {"cod": cod, "des": des, "tipo": tipo.strip() if tipo else None}

        for row in tabella.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 10:
                continue
            valori = [c.get_text(" ", strip=True) for c in cells]
            azioni = cells[-1]
            dettaglio = azioni.find("a", href=lambda h: h and "DettaglioTesi.do" in h)
            tesi_id = pers_id = dom_ct_id = None
            if dettaglio is not None:
                query = parse_qs(urlparse(dettaglio["href"]).query)
                tesi_id = query.get("tesi_id", [None])[0]
                pers_id = query.get("pers_id", [None])[0]
                dom_ct_id = query.get("dom_ct_id", [None])[0]
            items.append({
                "matricola": valori[0],
                "nominativo": valori[1],
                "ruoloDocente": valori[2],
                "dataApprovazioneTesi": _iso(valori[3]),
                "sessioneLaurea": valori[4] or None,
                "dataAppello": _iso(valori[5]),
                "appello": valori[6] or None,
                "statoTesi": valori[7] or None,
                "dataAssegnazioneTesi": _iso(valori[8]),
                "corso": corso,
                "tesiId": int(tesi_id) if tesi_id else None,
                "persId": int(pers_id) if pers_id else None,
                "domCtId": int(dom_ct_id) if dom_ct_id else None,
            })
    return items


class GraduationAdapter:
    """Legge le tesi assegnate al docente. Usa lo stesso httpx.Client
    autenticato (SSO Shibboleth) del Calendario Esami."""

    def __init__(self, client) -> None:
        self.client = client

    def _request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
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

    def theses(self) -> dict:
        response = self._request("GET", LAUREANDI_PATH)
        if "Laureandi assegnati" not in response.text:
            raise UpstreamContract("Pagina 'Laureandi assegnati' non riconosciuta.")
        items = parse_laureandi(response.text)
        return {"items": items, "count": len(items)}
