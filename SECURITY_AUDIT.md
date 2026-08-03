# Audit di sicurezza pre-deploy (27/07/2026)

Revisione indipendente del gateway prima dell'esposizione sul cluster, in
seguito all'incidente del 2022 (credenziali compromesse via il DB del vecchio
sistema). Metodo: lettura completa del codice + verifica empirica delle
ipotesi (non solo lettura a occhio).

## Punti di forza confermati

- Nessun database: il vettore usato nel 2022 (dump DB via SQL injection) non
  esiste in questa architettura.
- Credenziali upstream tenute solo in memoria di processo, mai su disco.
- Token di sessione opachi (`secrets.token_urlsafe`), salvati solo come hash
  SHA-256; refresh rotante con revoca totale in caso di riuso rilevato.
- Nessuno stack trace esposto al client (verificato: handler generico in
  `app/main.py` logga e restituisce solo `requestId`).

## Corretto in questo audit

1. **Login legacy senza rate limit** (`app/api/v3/upstream/upstream.py`) — il
   pass-through di `/UniparthenopeApp/v1/login` e `/v2/login` bypassava il
   limitatore usato da `/v3/auth/sessions`, riaprendo lo stesso vettore di
   brute-force del sistema originale. Fix: stesso `TokenBucket`, chiave
   `username|ip` (username estratto dall'header Basic in arrivo). Verificato:
   6° tentativo in un minuto → `429`.
2. **Cache senza limite di dimensione** (`app/core/cache.py`) — le chiavi di
   cache delle rotte pubbliche includono la query string, quindi un
   chiamante esterno poteva far crescere `_entries`/`_locks` senza limite
   (esaurimento memoria). Fix: evizione LRU con `max_entries` (default 2000).
   Verificato: 500 chiavi distinte → la cache resta a `max_entries` voci.

## Verificato e scartato (non sfruttabile)

- **Path traversal via parametri di path** (es. `{sede}` sostituito con
  `../../...`): ipotesi testata con un upstream fittizio — il routing di
  FastAPI/Starlette rifiuta a monte qualunque `/` o `%2f` nel segmento,
  risponde 404 prima di raggiungere il codice del gateway. Nessuna azione
  necessaria.

## Da sistemare in fase di deploy (non nel codice)

- Il processo parla solo HTTP in chiaro: va messo dietro nginx con TLS
  (i certificati per `api.uniparthenope.it` sono già presenti sul server),
  mai esposto direttamente su una porta pubblica senza cifratura.
- Va avviato con `uvicorn --proxy-headers`, altrimenti il rate limiter per
  IP vede sempre l'IP di nginx invece di quello reale del chiamante.

## Nota minore, non bloccante

- `/v3/upstream-catalog` espone la mappa completa delle 91 operazioni senza
  autenticazione (utile per il debug, ma non necessario che sia pubblico).
