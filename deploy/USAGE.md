# Come usare il gateway v3 (Carmine, Nicola)

## Indirizzo base

- **Ora** (in sviluppo, prima della pubblicazione): tramite tunnel —
  `http://127.0.0.1:8080` sul Mac di chi ha il tunnel SSH/Cloudflare aperto.
- **Dopo la pubblicazione** (quando Antonello completa i suoi passi):
  `https://api-v3.uniparthenope.it`

Il codice dell'app dovrebbe leggere questo indirizzo da una variabile di
configurazione, non hardcoded, così il giorno del passaggio si cambia un
valore solo.

## 1. Ottenere una API key (una volta sola)

```bash
curl -X POST <BASE_URL>/v3/api-keys \
  -H 'Content-Type: application/json' \
  -d '{"owner": "il-tuo-nome"}'
```
Risposta: `{"apiKey": "upk_...", ...}`. **Conservala** (non è recuperabile
dopo — se persa, richiedine un'altra, quella vecchia resta valida finché non
la revochiamo).

Ogni chiamata successiva, di qualsiasi tipo, deve avere l'header:
```
X-API-Key: upk_...
```
Senza, tutte le rotte (tranne `/v3/docs`, `/v3/health`, `/v3/api-keys`
stesso) rispondono `401 api_key_required`.

## 2. Esplorare le API

Swagger interattivo: `<BASE_URL>/v3/docs` — bottone **Authorize** in alto a
destra, incolla la chiave lì una volta, poi puoi provare ogni endpoint
direttamente dal browser.

## 3. Login utente (per le rotte che richiedono un account)

Due strade, a seconda di cosa ti serve:

**Facciata nuova** (consigliata per l'app):
```
POST /v3/auth/sessions   {"username": "...", "password": "..."}
→ {"accessToken": "...", "refreshToken": "...", "profile": {...}, "careers":[...]}
```
Poi `Authorization: Bearer <accessToken>` sulle rotte protette.

✅ Corretto il 27/07/2026: il bug di mappatura carriera (la risposta reale di
Esse3 annida dati anagrafici e carriere dentro `user`, non alla radice) è
risolto. Verificato con account reale: login, profilo completo e carriere
multiple tutte corrette.

**Passthrough legacy** (identico al vecchio sistema, funziona già con
account reali):
```
GET /UniparthenopeApp/v1/login   con Basic Auth (utente:password)
```
E poi Basic Auth su ogni chiamata successiva, esattamente come il vecchio
sistema — più tutte le altre rotte legacy sotto lo stesso schema
(`/UniparthenopeApp/...`, `/GAUniparthenope/...`, ecc.), tutte già testate
con account reali.

## 4. Rotte pubbliche (nessun account, ma sempre serve la API key)

Sedi, news, avvisi, eventi, mense, corsi — vedi `/v3/docs` per l'elenco
completo, sezione "Pubblica" in `API_OVERVIEW.md`.

## Attenzione

- Le API key sono **solo in memoria**: se il gateway si riavvia (rebuild,
  `docker restart`, riavvio del server), tutte le chiavi emesse spariscono e
  vanno richieste di nuovo. Non è ancora persistente — da tenere a mente
  finché non lo sistemiamo.
