# UniParthenope — refactoring legacy compatibile

Questa release segue il requisito del professore: **l'app esistente non deve
accorgersi del refactoring**.

## Autori

- Nicola Salvati — progettazione e implementazione del gateway v3.
- Carmine Coppola — audit di sicurezza pre-deploy, hardening, deploy sul cluster.

## Contratto esterno invariato

Le 91 operazioni della spec ufficiale sono esposte direttamente agli stessi
indirizzi originali, con gli stessi metodi HTTP, parametri, query string, body,
status, media type e payload upstream.

Esempi:

```text
GET    /UniparthenopeApp/v1/login
GET    /UniparthenopeApp/v1/general/image/{personId}
POST   /UniparthenopeApp/v1/students/bookExam/{cdsId}/{adId}/{appId}
DELETE /UniparthenopeApp/v1/students/deleteExam/{cdsId}/{adId}/{appId}/{stuId}
POST   /Badges/v3/checkQrCode
GET    /Bus/v1/bus/{sede}
GET    /Eating/v1/getAllToday
POST   /Notifications/v1/registerDevice
```

Quindi il client attuale può continuare a usare i vecchi URL. Il namespace
`/v3/...` rimane disponibile come interfaccia opzionale, ma non è necessario
per mantenere l'app esistente.

## Copertura

Fonte: `swagger.json` incluso.

- 88 percorsi;
- 91 operazioni HTTP;
- 8 namespace;
- 91/91 operazioni registrate all'indirizzo originale;
- 91/91 disponibili anche nel namespace diagnostico `/v3/upstream`.

Verifica:

```bash
python tools/verify_coverage.py
python -m unittest discover -s tests -t . -v
```

`tests/test_api.py` contiene anche un controllo OpenAPI che verifica che ogni
metodo/percorso legacy sia registrato alla radice.

## Avvio reale

Python 3.12 è consigliato. Python 3.9 è supportato tramite
`eval-type-backport`.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MOCK_ESSE3=0
export UPSTREAM_BASE='https://api.uniparthenope.it'
export UPSTREAM_TIMEOUT_S=25
uvicorn app.main:app --port 8080
```

Swagger locale:

```text
http://localhost:8080/v3/docs
```

Le sezioni `legacy:*` mostrano gli indirizzi originali. Le sezioni normali
`auth`, `students`, `exams`, `photos`, `devices` e `services` rappresentano la
nuova interfaccia opzionale.

## Autenticazione compatibile

Le rotte legacy protette accettano ancora Basic Auth, come il server attuale.
Questo e' necessario per non modificare subito l'app. Il gateway non registra
la password e non la salva su file.

E' disponibile anche Bearer v3 per una migrazione successiva. Non viene
presentato come compatibilita' trasparente: per usare Bearer il client deve
essere aggiornato.

## Refactoring interno riutilizzato

Dietro le interfacce legacy sono disponibili:

- client HTTP centralizzato;
- timeout espliciti;
- circuit breaker;
- cache per GET pubbliche;
- session store per la nuova interfaccia opzionale;
- rate limit del nuovo login;
- mapper e validazione;
- errori correlati con request ID;
- ETag e ridimensionamento foto nelle facciate v3;
- risoluzione di `adsceId` dal piano di studi.

Sulle rotte legacy un errore HTTP 500 dell'upstream viene conservato con status
e payload originali, perché il contratto deve rimanere osservabile. Sul
namespace v3 lo stesso guasto viene normalizzato come errore upstream.

## Limite della compatibilità ricostruita

Questo pacchetto deriva dallo Swagger e dalle prove HTTP disponibili, non dal
sorgente Flask effettivamente installato sul server. Garantisce metodo e
percorso 1:1 e inoltro trasparente, ma non può dimostrare eventuali comportamenti
non documentati nel vecchio sorgente.

Quando sarà disponibile il repository Flask sanificato, i test dovranno essere
estesi a query, payload reali, effetti sul database e comportamenti non presenti
nello Swagger.

## Sicurezza

Non inserire nel repository:

- password studenti;
- password database;
- token;
- file di credenziali;
- dump o log reali.

Le vulnerabilità del vecchio sorgente — SQL concatenato, segreti nel codice,
credenziali scritte su file e badge privo di autorizzazione — richiedono il
sorgente reale per essere corrette nel punto in cui nascono. Questo gateway non
finge che tali correzioni siano già dimostrate.

Le operazioni che modificano prenotazioni, badge, dispositivi, menu, notifiche
o aule non vengono lanciate automaticamente contro l'ambiente reale.
