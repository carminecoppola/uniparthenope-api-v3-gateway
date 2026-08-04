from __future__ import annotations

import base64
import hashlib
import threading
import time
from datetime import date

import httpx
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import APIRouter, HTTPException, Request

ESSE3 = "https://uniparthenope.esse3.cineca.it/e3rest/api/"
SERVIZIO = "calesa-service-v1/appelli"
PAGE_SIZE = 100
PAGE_SIZE_LIBRETTO = 200
MAX_PAGES = 25
PAGINE_PARALLELE = 10
TIMEOUT = 20
STATI_ESCLUSI = ("C",)


def _credenziali(request: Request) -> str:
    valore = request.headers.get("Authorization", "")
    if valore.lower().startswith("basic "):
        grezzo = valore.split(None, 1)[1].strip()
        try:
            base64.b64decode(grezzo, validate=True)
        except Exception:
            raise HTTPException(status_code=401, detail="Header Basic non valido.")
        return grezzo
    if valore.lower().startswith("bearer "):
        sessioni = getattr(request.app.state, "sessions", None)
        if sessioni is None:
            raise HTTPException(status_code=503, detail="Sessioni non disponibili.")
        sessione = sessioni.resolve_access(valore[7:].strip())
        adapter = sessione.data.get("adapter")
        credenziali = getattr(adapter, "upstream_auth", None)
        if not credenziali:
            raise HTTPException(status_code=503, detail="Credenziali ESSE3 non disponibili in questa sessione.")
        coppia = credenziali[0] + ":" + credenziali[1]
        return base64.b64encode(coppia.encode("utf-8")).decode("ascii")
    raise HTTPException(status_code=401, detail="Autenticazione richiesta: Basic oppure Bearer.")


def _pagina(client, indirizzo, intestazioni, inizio):
    risposta = client.get(indirizzo, headers=intestazioni,
                          params={"start": inizio, "limit": PAGE_SIZE})
    if risposta.status_code != 200:
        try:
            return risposta.status_code, risposta.json()
        except ValueError:
            return risposta.status_code, risposta.text
    try:
        return 200, risposta.json()
    except ValueError:
        return 502, None


def _scarica(token: str, cds_id, ad_id):
    indirizzo = ESSE3 + SERVIZIO + "/{}/{}".format(cds_id, ad_id)
    intestazioni = {"Authorization": "Basic " + token, "Accept": "application/json"}
    raccolti = []
    with httpx.Client(timeout=TIMEOUT) as client:
        stato, corpo = _pagina(client, indirizzo, intestazioni, 0)
        if stato != 200:
            return [], stato, corpo
        if not isinstance(corpo, list):
            return [], 502, corpo
        raccolti.extend(corpo)
        if len(corpo) < PAGE_SIZE:
            return raccolti, 200, None
        blocco = 1
        while blocco < MAX_PAGES:
            partenze = [(blocco + passo) * PAGE_SIZE
                        for passo in range(PAGINE_PARALLELE)
                        if blocco + passo < MAX_PAGES]
            if not partenze:
                break
            risultati = {}
            with ThreadPoolExecutor(max_workers=len(partenze)) as pool:
                lavori = {pool.submit(_pagina, client, indirizzo, intestazioni, partenza): partenza
                          for partenza in partenze}
                for lavoro in as_completed(lavori):
                    partenza = lavori[lavoro]
                    try:
                        risultati[partenza] = lavoro.result()
                    except httpx.HTTPError:
                        risultati[partenza] = (503, None)
            ultima = False
            for partenza in partenze:
                esito, dati = risultati.get(partenza, (502, None))
                if esito != 200 or not isinstance(dati, list):
                    ultima = True
                    break
                raccolti.extend(dati)
                if len(dati) < PAGE_SIZE:
                    ultima = True
                    break
            if ultima:
                break
            blocco += PAGINE_PARALLELE
    return raccolti, 200, None


def _testo(valore) -> str:
    return valore if isinstance(valore, str) else ""


def _nome(valore) -> str:
    return _testo(valore).capitalize()


def _data(valore):
    testo = _testo(valore).strip()
    return testo.split()[0] if testo else None


def _giorno(valore):
    testo = _testo(valore).strip().split()[0] if _testo(valore).strip() else ""
    parti = testo.split("/")
    if len(parti) == 3 and all(pezzo.isdigit() for pezzo in parti):
        try:
            return date(int(parti[2]), int(parti[1]), int(parti[0]))
        except ValueError:
            return None
    return None


def _aperto(appello: dict, oggi: date):
    inizio = _giorno(appello.get("dataInizioIscr"))
    fine = _giorno(appello.get("dataFineIscr"))
    esame = _giorno(appello.get("dataInizioApp"))
    if esame is not None and esame < oggi:
        return False, False, "esame passato"
    if fine is not None and fine < oggi:
        return False, False, "iscrizioni chiuse"
    if esame is None and inizio is None and fine is None:
        return False, False, "nessuna data disponibile"
    if inizio is not None and inizio > oggi:
        return False, False, "iscrizioni aperte dal " + _testo(appello.get("dataInizioIscr"))
    return True, True, None


def _ordina(valore):
    testo = _testo(valore).strip()
    parti = testo.split("/")
    if len(parti) == 3 and all(p.isdigit() for p in parti):
        return parti[2] + parti[1] + parti[0]
    return testo or "99999999"


def _formatta(appello: dict) -> dict:
    cognome = _nome(appello.get("presidenteCognome"))
    nome = _nome(appello.get("presidenteNome"))
    return {
        "esame": appello.get("adDes"),
        "appId": appello.get("appId"),
        "stato": appello.get("stato"),
        "statoDes": appello.get("statoDes"),
        "docente": cognome,
        "docente_completo": (cognome + " " + nome).strip(),
        "numIscritti": appello.get("numIscritti"),
        "note": appello.get("note"),
        "descrizione": appello.get("desApp"),
        "dataFine": _data(appello.get("dataFineIscr")),
        "dataInizio": _data(appello.get("dataInizioIscr")),
        "dataEsame": _data(appello.get("dataInizioApp")),
    }


def check_appello(request: Request, cdsId: str, adId: str):
    token = _credenziali(request)
    try:
        appelli, stato, errore = _scarica(token, cdsId, adId)
    except httpx.HTTPError as guasto:
        raise HTTPException(status_code=503, detail=str(guasto))
    if stato != 200:
        messaggio = errore.get("retErrMsg") if isinstance(errore, dict) else None
        raise HTTPException(status_code=stato, detail=messaggio or "Errore ESSE3.")
    return [_formatta(a) for a in appelli if a.get("stato") not in STATI_ESCLUSI]



PERCORSO_LIBRETTO = "libretto-service-v2/libretti/{mat}/righe"
PERCORSO_LOGIN = "login"
WORKERS = 5
CACHE_TTL = 300
CACHE_MAX = 64
_cache = {}
_cache_lock = threading.Lock()


def _chiave_cache(token, parti):
    grezzo = token + "|" + "|".join(str(pezzo) for pezzo in parti)
    return hashlib.sha256(grezzo.encode("utf-8")).hexdigest()


def _cache_leggi(chiave):
    adesso = time.time()
    with _cache_lock:
        voce = _cache.get(chiave)
        if voce is None:
            return None
        scadenza, dati = voce
        if scadenza < adesso:
            _cache.pop(chiave, None)
            return None
        return dati


def svuota_cache():
    with _cache_lock:
        _cache.clear()


def _cache_scrivi(chiave, dati):
    with _cache_lock:
        if len(_cache) >= CACHE_MAX:
            piu_vecchia = min(_cache, key=lambda k: _cache[k][0])
            _cache.pop(piu_vecchia, None)
        _cache[chiave] = (time.time() + CACHE_TTL, dati)


def _chiama(token: str, indirizzo: str, parametri=None):
    intestazioni = {"Content-Type": "application/json", "Authorization": "Basic " + token}
    with httpx.Client(timeout=TIMEOUT) as client:
        risposta = client.get(indirizzo, headers=intestazioni, params=parametri)
    try:
        corpo = risposta.json()
    except Exception:
        corpo = None
    return risposta.status_code, corpo


def _intero(valore):
    try:
        numero = int(str(valore).strip())
    except Exception:
        return None
    return numero if numero > 0 else None


def _cerca(nodo, chiave):
    if isinstance(nodo, dict):
        for nome, valore in nodo.items():
            if nome == chiave:
                return valore
            trovato = _cerca(valore, chiave)
            if trovato is not None:
                return trovato
    elif isinstance(nodo, list):
        for elemento in nodo:
            trovato = _cerca(elemento, chiave)
            if trovato is not None:
                return trovato
    return None


def _carriere(token: str):
    stato, corpo = _chiama(token, ESSE3 + PERCORSO_LOGIN)
    if stato != 200:
        messaggio = corpo.get("retErrMsg") if isinstance(corpo, dict) else None
        raise HTTPException(status_code=stato if stato in (401, 403) else 502,
                            detail=messaggio or "Login ESSE3 non riuscito.")
    tratti = _cerca(corpo, "trattiCarriera")
    if not isinstance(tratti, list):
        raise HTTPException(status_code=502, detail="Nessuna carriera trovata per queste credenziali.")
    elenco = []
    for tratto in tratti:
        if not isinstance(tratto, dict):
            continue
        mat = _intero(tratto.get("matId"))
        cds = _intero(tratto.get("cdsId"))
        if mat is None or cds is None:
            continue
        stato_cod = tratto.get("stuStatoCod")
        if isinstance(stato_cod, dict):
            stato_cod = stato_cod.get("value")
        elenco.append({
            "matId": mat,
            "cdsId": cds,
            "stuId": _intero(tratto.get("stuId")),
            "cdsDes": tratto.get("cdsDes"),
            "stato": stato_cod,
            "attiva": str(stato_cod or "").upper() == "A",
        })
    if not elenco:
        raise HTTPException(status_code=502, detail="Nessuna carriera utilizzabile per queste credenziali.")
    return elenco


def _libretto(token: str, mat_id):
    stato, corpo = _chiama(token, ESSE3 + PERCORSO_LIBRETTO.format(mat=mat_id),
                           {"start": 0, "limit": PAGE_SIZE_LIBRETTO})
    if stato != 200 or not isinstance(corpo, list):
        return [], stato
    righe = []
    for riga in corpo:
        if not isinstance(riga, dict):
            continue
        chiave = riga.get("chiaveADContestualizzata")
        chiave = chiave if isinstance(chiave, dict) else {}
        candidati = []
        for valore in (chiave.get("adId"), riga.get("adDefAppId"),
                       chiave.get("adDefAppId"), riga.get("attDidEsaId"),
                       riga.get("adId")):
            numero = _intero(valore)
            if numero is not None and numero not in candidati:
                candidati.append(numero)
        if not candidati:
            continue
        stato_riga = riga.get("stato")
        if isinstance(stato_riga, dict):
            stato_riga = stato_riga.get("value")
        righe.append({
            "nome": riga.get("adDes") or chiave.get("adDes"),
            "adsceId": _intero(riga.get("adsceId")),
            "cdsId": _intero(chiave.get("cdsId")),
            "candidati": candidati,
            "prenotabili": _intero(riga.get("numAppelliPrenotabili")) or 0,
            "prenotazioni": _intero(riga.get("numPrenotazioni")) or 0,
            "stato": stato_riga,
            "statoDes": riga.get("statoDes"),
            "superato": str(stato_riga or "").upper() == "S",
        })
    return righe, 200


def _appelli_riga(token: str, cds_id, riga):
    ultimo = None
    dettaglio = None
    for candidato in riga["candidati"]:
        try:
            appelli, stato, errore = _scarica(token, cds_id, candidato)
        except httpx.HTTPError as guasto:
            ultimo, dettaglio = 503, str(guasto)
            continue
        if stato == 200:
            return candidato, appelli, 200, None
        ultimo = stato
        if isinstance(errore, dict):
            dettaglio = errore.get("retErrMsg") or errore.get("retErrObj") or dettaglio
    return None, [], ultimo or 502, dettaglio


def elenco_appelli(request: Request, cdsId: str = None, soloPrenotabili: bool = True,
                   soloAttive: bool = True, includiSuperati: bool = False,
                   soloAperti: bool = True, aggiorna: bool = False):
    oggi = date.today()
    token = _credenziali(request)
    chiave_cache = _chiave_cache(token, (cdsId, soloPrenotabili, soloAttive,
                                         includiSuperati, soloAperti, oggi.isoformat()))
    if not aggiorna:
        salvato = _cache_leggi(chiave_cache)
        if salvato is not None:
            return dict(salvato, dallaCache=True)
    carriere = _carriere(token)
    if cdsId:
        scelto = _intero(cdsId)
        carriere = [c for c in carriere if c["cdsId"] == scelto]
    elif soloAttive and any(c["attiva"] for c in carriere):
        carriere = [c for c in carriere if c["attiva"]]
    if not carriere:
        raise HTTPException(status_code=404, detail="Nessuna carriera corrispondente.")

    appelli = []
    visti = set()
    diagnostica = []
    saltate = 0

    for carriera in carriere:
        righe, stato_libretto = _libretto(token, carriera["matId"])
        if stato_libretto != 200:
            diagnostica.append({"cdsId": carriera["cdsId"], "matId": carriera["matId"],
                                "errore": "libretto", "stato": stato_libretto})
            continue

        selezionate = []
        for riga in righe:
            if soloPrenotabili and riga["prenotabili"] <= 0 and riga["prenotazioni"] <= 0:
                saltate += 1
                continue
            if not includiSuperati and riga["superato"] and riga["prenotabili"] <= 0:
                saltate += 1
                continue
            selezionate.append(riga)

        if not selezionate:
            continue

        with ThreadPoolExecutor(max_workers=min(WORKERS, len(selezionate))) as pool:
            lavori = {pool.submit(_appelli_riga, token,
                                  riga["cdsId"] or carriera["cdsId"], riga): riga
                      for riga in selezionate}
            for lavoro in as_completed(lavori):
                riga = lavori[lavoro]
                adId, grezzi, stato, dettaglio = lavoro.result()
                trovati = 0
                scartati = 0
                for appello in grezzi:
                    if appello.get("stato") in STATI_ESCLUSI:
                        continue
                    futuro, apribile, motivo = _aperto(appello, oggi)
                    if soloAperti and not futuro:
                        scartati += 1
                        continue
                    chiave = (carriera["cdsId"], appello.get("appId"), appello.get("adDes"))
                    if chiave in visti:
                        continue
                    visti.add(chiave)
                    formattato = _formatta(appello)
                    formattato["bookable"] = apribile
                    if motivo:
                        formattato["motivoNonPrenotabile"] = motivo
                    formattato["adId"] = adId
                    formattato["adsceId"] = riga["adsceId"]
                    formattato["cdsId"] = riga["cdsId"] or carriera["cdsId"]
                    formattato["matId"] = carriera["matId"]
                    formattato["stuId"] = carriera["stuId"]
                    if not formattato.get("esame"):
                        formattato["esame"] = riga["nome"]
                    appelli.append(formattato)
                    trovati += 1
                voce = {"cdsId": riga["cdsId"] or carriera["cdsId"],
                        "insegnamento": riga["nome"], "adId": adId,
                        "adsceId": riga["adsceId"], "stato": stato,
                        "prenotabiliDaLibretto": riga["prenotabili"],
                        "scaduti": scartati, "appelli": trovati}
                if dettaglio:
                    voce["errore"] = dettaglio
                diagnostica.append(voce)

    appelli.sort(key=lambda a: (_ordina(a.get("dataEsame")), a.get("esame") or ""))
    risposta = {
        "carriere": carriere,
        "totale": len(appelli),
        "righeSaltate": saltate,
        "insegnamenti": sorted(diagnostica, key=lambda d: str(d.get("insegnamento"))),
        "appelli": appelli,
        "dallaCache": False,
    }
    _cache_scrivi(chiave_cache, risposta)
    return risposta


PERCORSO_ELENCO = "/students/appelli"
PERCORSO = "/students/checkAppello/{cdsId}/{adId}"
PREFISSO_LEGACY = "/UniparthenopeApp/v3"

router = APIRouter()
router.add_api_route(PERCORSO_ELENCO, elenco_appelli, methods=["GET"], tags=["students"],
                     operation_id="v3_elenco_appelli", summary="Elenco appelli studente")
router.add_api_route(PERCORSO, check_appello, methods=["GET"], tags=["students"],
                     operation_id="v3_check_appello", summary="Check Appello")


def mount(app, prefisso: str = PREFISSO_LEGACY) -> None:
    app.add_api_route(prefisso + PERCORSO_ELENCO, elenco_appelli, methods=["GET"],
                      tags=["uniparthenope-v3:students"],
                      operation_id="uapp_v3_elenco_appelli", summary="Elenco appelli studente")
    app.add_api_route(prefisso + PERCORSO, check_appello, methods=["GET"],
                      tags=["uniparthenope-v3:students"],
                      operation_id="uapp_v3_check_appello", summary="Check Appello")
