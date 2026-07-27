# Griglia di confronto v1/v2 ↔ v3

Stessi casi di prova, tre versioni, evidenze complete. Regola dell'audit:
un 200 OK non è un successo finché il payload non è verificato.

Per ogni cella registrare: **codice HTTP / tempo (ms) / payload verificato sì-no / note**.

| # | Caso di prova | v1/v2 (endpoint) | v3 (endpoint) | Esito atteso v3 |
|---|---|---|---|---|
| 1 | Login credenziali valide | `GET /UniparthenopeApp/v1/login` (Basic) | `POST /v3/auth/sessions` | 201 + accessToken/refreshToken, niente password sul device |
| 2 | Login credenziali errate | idem | idem | 401 `invalid_credentials` problem+json (mai 500) |
| 3 | 6º login in 60 s | — (nessun limite) | idem | 429 `rate_limited` + Retry-After |
| 4 | Elenco appelli | `students/checkAppello/{cdsId}/{adId}` | `GET /v3/exam-sessions` | `bookable` + `reason` + `inPlan` calcolati server-side |
| 5 | Prenotazione con insegnamento IN piano | `students/bookExam/...` | `POST /v3/exam-sessions/{appId}/reservations` | 201, `adsceId` risolto dal libretto (mai None) |
| 6 | Prenotazione con insegnamento FUORI piano | idem (oggi: `adsceId: None` → errore upstream) | idem | **422 `plan_entry_not_found`**, zero chiamate upstream |
| 7 | Prova prenotazione senza effetti | — (non esiste) | idem + `?dryRun=true` | 200, nessuna mutazione |
| 8 | Cancellazione esistente | `students/deleteExam/...` | `DELETE /v3/reservations/{id}` | 204 |
| 9 | Cancellazione ripetuta (idempotenza) | comportamento da verificare | idem | 204 + `X-Already-Gone: true` |
| 10 | Foto presente | endpoint foto v1/v2 (da confermare su spec) | `GET /v3/students/me/photo?size=128` | 200 image/webp o png, ETag |
| 11 | Foto — richiesta ripetuta | — | idem + `If-None-Match` | **304** (risparmio banda) |
| 12 | Foto assente | ? | idem | 404 problem+json = stato di dominio (avatar iniziali) |
| 13 | Registrazione device | `Notifications/registerDevice` | `PUT /v3/devices/{token}` | 204, idempotente |
| 14 | Autobus | percorso da confermare | `GET /v3/transport/bus/routes` | 200 + cache; se path reale non configurato: 503 tipizzato |
| 15 | Mense | percorso da confermare | `GET /v3/dining/menus` | come sopra |
| 16 | Token scaduto (>15 min) | — (Basic sempre valido) | qualunque rotta autenticata | 401 `session_expired`, refresh rotante funziona |
| 17 | Upstream 500 ripetuto | 500 nudo al client | qualunque rotta proxy | 503 `upstream_unavailable` dopo apertura circuito, requestId in ogni risposta |

Criterio di superiorità (§13.10 dell'audit): la v3 è «migliore» solo se vince
su correttezza, contratto errori, sicurezza credenziali, resilienza e latenza
percepita — non se ha semplicemente più endpoint.
