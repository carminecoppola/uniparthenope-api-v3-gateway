from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date

import httpx
from fastapi import APIRouter, Body, HTTPException, Path, Request

from .appelli import (ESSE3, TIMEOUT, WORKERS, _carriere, _chiama,
                      _credenziali, _formatta, _giorno, _intero, _libretto,
                      _scarica, svuota_cache)

SERVIZIO_PRENOTAZIONI = "libretto-service-v2/libretti/{mat}/prenotazioni"
SERVIZIO_APPELLO = "calesa-service-v1/appelli/{cds}/{ad}/{app}"
SERVIZIO_ISCRITTI = "calesa-service-v1/appelli/{cds}/{ad}/{app}/iscritti"
SERVIZIO_ISCRITTO = "calesa-service-v1/appelli/{cds}/{ad}/{app}/iscritti/{stu}"
PERCORSO_PRENOTAZIONI = "/students/prenotazioni"
PERCORSO_PRENOTAZIONE = "/students/prenotazioni/{appId}"
PREFISSO_LEGACY = "/UniparthenopeApp/v3"
GIORNI_STORICO = 400
TIPI_PROVA = {"O": "Orale", "S": "Scritto", "SO": "Scritto e orale",
              "P": "Pratico", "C": "Compitino", "G": "Giudizio",
              "F": "Prova finale", "A": "Altro"}
TIPI_APPELLO = {"PF": "Prova finale", "PP": "Prova parziale",
                "PI": "Prova intermedia", "SP": "Prova scritta parziale"}
ESITI_CREAZIONE = (200, 201, 204)
ESITI_ANNULLAMENTO = (200, 202, 204)


def _intestazioni(token: str) -> dict:
    return {"Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": "Basic " + token}


def _corpo(risposta):
    try:
        return risposta.json()
    except Exception:
        return None


def _invia(token: str, indirizzo: str, dati: dict):
    with httpx.Client(timeout=TIMEOUT) as client:
        risposta = client.post(indirizzo, headers=_intestazioni(token), json=dati)
    return risposta.status_code, _corpo(risposta)


def _elimina(token: str, indirizzo: str):
    with httpx.Client(timeout=TIMEOUT) as client:
        risposta = client.delete(indirizzo, headers=_intestazioni(token))
    return risposta.status_code, _corpo(risposta)


def _messaggio(corpo, ripiego: str) -> str:
    if isinstance(corpo, dict):
        dettagli = corpo.get("errDetails")
        if isinstance(dettagli, list):
            for voce in dettagli:
                if isinstance(voce, dict) and voce.get("errorType"):
                    return str(voce["errorType"])
        for chiave in ("retErrMsg", "detail", "message"):
            if corpo.get(chiave):
                return str(corpo[chiave])
    return ripiego


def _carriera(token: str, cds_id=None) -> dict:
    carriere = _carriere(token)
    scelta = _intero(cds_id) if cds_id is not None else None
    if scelta is not None:
        for carriera in carriere:
            if carriera["cdsId"] == scelta:
                return carriera
        raise HTTPException(status_code=404,
                            detail="Nessuna carriera con cdsId {}.".format(scelta))
    attive = [carriera for carriera in carriere if carriera["attiva"]]
    return (attive or carriere)[0]


def _storico(token: str, mat_id) -> list:
    stato, corpo = _chiama(token, ESSE3 + SERVIZIO_PRENOTAZIONI.format(mat=mat_id))
    if stato != 200 or not isinstance(corpo, list):
        raise HTTPException(status_code=stato if 400 <= stato < 500 else 502,
                            detail=_messaggio(corpo, "Prenotazioni ESSE3 non leggibili."))
    voci = []
    for grezza in corpo:
        if not isinstance(grezza, dict):
            continue
        app_id = _intero(grezza.get("appId"))
        ad_id = _intero(grezza.get("adId"))
        if app_id is None or ad_id is None:
            continue
        voci.append({
            "appId": app_id,
            "adId": ad_id,
            "cdsId": _intero(grezza.get("cdsId")),
            "adsceId": _intero(grezza.get("adsceId")),
            "applistaId": _intero(grezza.get("applistaId")),
            "appLogId": _intero(grezza.get("appLogId")),
            "stuId": _intero(grezza.get("stuId")),
            "matricola": grezza.get("matricola"),
            "dataPrenotazione": grezza.get("dataIns"),
            "giorno": _giorno(grezza.get("dataIns")),
        })
    return voci


def _recenti(voci: list, oggi: date) -> list:
    limite = oggi.toordinal() - GIORNI_STORICO
    return [voce for voce in voci
            if voce["giorno"] is not None and voce["giorno"].toordinal() >= limite]


def _schede(token: str, cds_id, ad_ids: list) -> dict:
    trovate = {}
    if not ad_ids:
        return trovate
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(ad_ids))) as pool:
        lavori = {pool.submit(_scarica, token, cds_id, ad_id): ad_id for ad_id in ad_ids}
        for lavoro in as_completed(lavori):
            ad_id = lavori[lavoro]
            try:
                appelli, stato, _ignorato = lavoro.result()
            except httpx.HTTPError:
                continue
            if stato != 200:
                continue
            for appello in appelli:
                app_id = _intero(appello.get("appId"))
                if app_id is not None:
                    trovate[(ad_id, app_id)] = appello
    return trovate


def _scheda_singola(token: str, cds_id, ad_id, app_id):
    indirizzo = ESSE3 + SERVIZIO_APPELLO.format(cds=cds_id, ad=ad_id, app=app_id)
    stato, corpo = _chiama(token, indirizzo)
    if stato != 200:
        return None
    if isinstance(corpo, list):
        corpo = corpo[0] if corpo else None
    return corpo if isinstance(corpo, dict) else None


def _dettagli(token: str, chiavi: list) -> dict:
    trovati = {}
    if not chiavi:
        return trovati
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(chiavi))) as pool:
        lavori = {pool.submit(_scheda_singola, token, cds, ad, app): (ad, app)
                  for cds, ad, app in chiavi}
        for lavoro in as_completed(lavori):
            try:
                scheda = lavoro.result()
            except httpx.HTTPError:
                continue
            if scheda is not None:
                trovati[lavori[lavoro]] = scheda
    return trovati


def _turno(scheda, app_log_id):
    if not isinstance(scheda, dict):
        return None
    turni = scheda.get("turni")
    if not isinstance(turni, list) or not turni:
        return None
    for turno in turni:
        if isinstance(turno, dict) and _intero(turno.get("appLogId")) == app_log_id:
            return turno
    primo = turni[0]
    return primo if isinstance(primo, dict) else None


def _sessione(scheda):
    if not isinstance(scheda, dict):
        return None
    sessioni = scheda.get("sessioni")
    if not isinstance(sessioni, list) or not sessioni:
        return None
    prima = sessioni[0]
    return _codice(prima.get("sesDes")) if isinstance(prima, dict) else None


def _commissione(turno):
    if not isinstance(turno, dict):
        return []
    membri = turno.get("commissione")
    if not isinstance(membri, list):
        return []
    elenco = []
    for membro in membri:
        if not isinstance(membro, dict):
            continue
        cognome = _codice(membro.get("docenteCognome")) or ""
        nome = _codice(membro.get("docenteNome")) or ""
        completo = (cognome.title() + " " + nome.title()).strip()
        if completo:
            elenco.append({"docente": completo,
                           "ruolo": _codice(membro.get("ruoloDes"))})
    return elenco


def _codice(valore):
    if isinstance(valore, dict):
        valore = valore.get("value")
    if valore is None:
        return None
    testo = str(valore).strip()
    return testo or None


def _ora(valore):
    testo = _codice(valore)
    if not testo or ":" not in testo:
        return None
    parti = testo.split(" ")[-1].split(":")
    if len(parti) < 2:
        return None
    return parti[0].zfill(2) + ":" + parti[1].zfill(2)


def _dettaglio(voce: dict, appello: dict, scheda=None) -> dict:
    unito = dict(voce)
    unito.pop("giorno", None)
    unito.update(_formatta(appello))
    unito["appId"] = voce["appId"]
    unito["adId"] = voce["adId"]
    unito["insegnamento"] = appello.get("adDes")
    unito["appelloId"] = _intero(appello.get("appelloId"))
    turno = _turno(scheda, voce.get("appLogId"))
    origine = turno if isinstance(turno, dict) else appello
    unito["aula"] = _codice(origine.get("aulaDes"))
    unito["aulaCod"] = _codice(origine.get("aulaCod"))
    unito["edificio"] = _codice(origine.get("edificioDes"))
    unito["sessione"] = _sessione(scheda)
    unito["commissione"] = _commissione(turno)
    tipo = _codice(appello.get("tipoEsaCod"))
    unito["tipoProvaCod"] = tipo
    unito["tipoProva"] = TIPI_PROVA.get(tipo, tipo)
    codice_app = _codice(appello.get("tipoAppCod"))
    unito["tipoAppello"] = TIPI_APPELLO.get(codice_app, codice_app)
    unito["modalita"] = _codice(appello.get("tipoGestAppDes"))
    unito["oraEsame"] = (_ora(origine.get("dataOraEsa"))
                         or _ora(appello.get("oraEsa")))
    return unito


def _attive(token: str, cds_id, voci: list, oggi: date) -> list:
    candidate = _recenti(voci, oggi)
    schede = _schede(token, cds_id, sorted({voce["adId"] for voce in candidate}))
    ordinate = []
    for voce in candidate:
        appello = schede.get((voce["adId"], voce["appId"]))
        if appello is None:
            continue
        esame = _giorno(appello.get("dataInizioApp"))
        if esame is None or esame < oggi:
            continue
        ordinate.append((esame, voce, appello))
    ordinate.sort(key=lambda gruppo: gruppo[0])
    chiavi = [(voce.get("cdsId") or cds_id, voce["adId"], voce["appId"])
              for _esame, voce, _appello in ordinate]
    schede = _dettagli(token, chiavi)
    return [_dettaglio(voce, appello, schede.get((voce["adId"], voce["appId"])))
            for _esame, voce, appello in ordinate]


def _quadro(token: str, cds_id=None):
    oggi = date.today()
    carriera = _carriera(token, cds_id)
    voci = _storico(token, carriera["matId"])
    return oggi, carriera, voci


def _riga_libretto(token: str, mat_id, ad_id):
    righe, stato = _libretto(token, mat_id)
    if stato != 200:
        raise HTTPException(status_code=502, detail="Libretto ESSE3 non leggibile.")
    for riga in righe:
        if ad_id in riga["candidati"]:
            return riga
    raise HTTPException(status_code=404,
                        detail="Insegnamento {} non presente nel libretto.".format(ad_id))


def elenco_prenotazioni(request: Request, cdsId: str = None, storico: bool = False):
    token = _credenziali(request)
    oggi, carriera, voci = _quadro(token, cdsId)
    if storico:
        elenco = [dict(voce, giorno=None) for voce in voci]
        for voce in elenco:
            voce.pop("giorno", None)
        return {"carriera": carriera, "totale": len(elenco),
                "storico": True, "prenotazioni": elenco}
    attive = _attive(token, carriera["cdsId"], voci, oggi)
    return {"carriera": carriera, "totale": len(attive),
            "storico": False, "prenotazioni": attive}


def crea_prenotazione(request: Request, corpo: dict = Body(...)):
    token = _credenziali(request)
    ad_id = _intero(corpo.get("adId"))
    app_id = _intero(corpo.get("appId"))
    if ad_id is None or app_id is None:
        raise HTTPException(status_code=422,
                            detail="Servono adId e appId, entrambi numerici e maggiori di zero.")
    forza = bool(corpo.get("forza"))
    oggi, carriera, voci = _quadro(token, corpo.get("cdsId"))
    riga = _riga_libretto(token, carriera["matId"], ad_id)
    if riga["adsceId"] is None:
        raise HTTPException(status_code=409,
                            detail="Riga di libretto priva di adsceId: prenotazione impossibile.")
    cds_id = riga["cdsId"] or carriera["cdsId"]
    attive = _attive(token, cds_id, voci, oggi)
    for altra in attive:
        if altra["appId"] == app_id:
            raise HTTPException(status_code=409,
                                detail="Prenotazione già attiva per l'appello {}.".format(app_id))
        if altra["adId"] == ad_id and not forza:
            raise HTTPException(status_code=409,
                                detail="Sei già prenotato all'appello {} di questo insegnamento. Usa forza=true per prenotarti comunque.".format(altra["appId"]))
    indirizzo = ESSE3 + SERVIZIO_ISCRITTI.format(cds=cds_id, ad=ad_id, app=app_id)
    try:
        stato, risposta = _invia(token, indirizzo, {"adsceId": riga["adsceId"]})
    except httpx.HTTPError as guasto:
        raise HTTPException(status_code=503, detail=str(guasto))
    if stato not in ESITI_CREAZIONE:
        raise HTTPException(status_code=stato if 400 <= stato < 500 else 502,
                            detail=_messaggio(risposta, "ESSE3 ha rifiutato la prenotazione (HTTP {}).".format(stato)))
    svuota_cache()
    aggiornate = _attive(token, cds_id, _storico(token, carriera["matId"]), oggi)
    creata = None
    for voce in aggiornate:
        if voce["appId"] == app_id and voce["adId"] == ad_id:
            creata = voce
            break
    if creata is None:
        raise HTTPException(status_code=502,
                            detail="ESSE3 ha accettato la richiesta ma la prenotazione non risulta attiva.")
    return {"prenotato": True, "prenotazione": creata,
            "prenotazioniAttive": len(aggiornate)}


def annulla_prenotazione(request: Request, appId: int = Path(...),
                         adId: int = None, cdsId: str = None):
    token = _credenziali(request)
    oggi, carriera, voci = _quadro(token, cdsId)
    attive = _attive(token, carriera["cdsId"], voci, oggi)
    voce = None
    for candidata in attive:
        if candidata["appId"] == appId and (adId is None or candidata["adId"] == adId):
            voce = candidata
            break
    if voce is None:
        raise HTTPException(status_code=404,
                            detail="Nessuna prenotazione attiva per l'appello {}.".format(appId))
    stu_id = voce.get("stuId") or carriera.get("stuId")
    if stu_id is None:
        raise HTTPException(status_code=502,
                            detail="Identificativo studente non disponibile.")
    cds_reale = voce.get("cdsId") or carriera["cdsId"]
    indirizzo = ESSE3 + SERVIZIO_ISCRITTO.format(cds=cds_reale, ad=voce["adId"],
                                                 app=appId, stu=stu_id)
    try:
        stato, risposta = _elimina(token, indirizzo)
    except httpx.HTTPError as guasto:
        raise HTTPException(status_code=503, detail=str(guasto))
    if stato not in ESITI_ANNULLAMENTO:
        raise HTTPException(status_code=stato if 400 <= stato < 500 else 502,
                            detail=_messaggio(risposta, "ESSE3 non ha annullato la prenotazione (HTTP {}).".format(stato)))
    svuota_cache()
    rimaste = _attive(token, carriera["cdsId"], _storico(token, carriera["matId"]), oggi)
    for altra in rimaste:
        if altra["appId"] == appId:
            raise HTTPException(status_code=409,
                                detail="La prenotazione risulta ancora attiva.")
    return {"annullato": True,
            "appId": appId,
            "adId": voce["adId"],
            "adsceId": voce.get("adsceId"),
            "applistaId": voce.get("applistaId"),
            "insegnamento": voce.get("insegnamento"),
            "dataEsame": voce.get("dataEsame"),
            "prenotazioniAttive": len(rimaste)}


router = APIRouter()
router.add_api_route(PERCORSO_PRENOTAZIONI, elenco_prenotazioni, methods=["GET"],
                     tags=["students"],
                     operation_id="v3_elenco_prenotazioni",
                     summary="Prenotazioni attive")
router.add_api_route(PERCORSO_PRENOTAZIONI, crea_prenotazione, methods=["POST"],
                     tags=["students"], status_code=201,
                     operation_id="v3_crea_prenotazione",
                     summary="Prenotazione appello")
router.add_api_route(PERCORSO_PRENOTAZIONE, annulla_prenotazione, methods=["DELETE"],
                     tags=["students"],
                     operation_id="v3_annulla_prenotazione",
                     summary="Annullamento prenotazione")


def mount(app, prefisso: str = PREFISSO_LEGACY) -> None:
    app.add_api_route(prefisso + PERCORSO_PRENOTAZIONI, elenco_prenotazioni, methods=["GET"],
                      tags=["uniparthenope-v3:students"],
                      operation_id="uapp_v3_elenco_prenotazioni",
                      summary="Prenotazioni attive")
    app.add_api_route(prefisso + PERCORSO_PRENOTAZIONI, crea_prenotazione, methods=["POST"],
                      tags=["uniparthenope-v3:students"], status_code=201,
                      operation_id="uapp_v3_crea_prenotazione",
                      summary="Prenotazione appello")
    app.add_api_route(prefisso + PERCORSO_PRENOTAZIONE, annulla_prenotazione, methods=["DELETE"],
                      tags=["uniparthenope-v3:students"],
                      operation_id="uapp_v3_annulla_prenotazione",
                      summary="Annullamento prenotazione")
