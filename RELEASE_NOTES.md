# Release 3.2.0 — legacy drop-in compatibility

## Requisito applicato

L'app esistente mantiene indirizzi, metodi, parametri, body e risposte
upstream. Tutte le 91 operazioni sono registrate direttamente sui percorsi
originali; `/v3` resta opzionale.

## Evidenze

- 88 percorsi e 91 operazioni estratti dallo Swagger incluso.
- Copertura statica metodo/percorso: 91/91.
- Test OpenAPI incluso per verificare a runtime tutti gli indirizzi legacy.
- 52 test totali: quelli HTTP richiedono FastAPI installato.

## Compatibilità e sicurezza

- Basic Auth resta accettato sulle vecchie rotte per non rompere l'app.
- Le credenziali non vengono scritte su file o nei log.
- Bearer v3 e nuove facciate restano disponibili per una migrazione futura.
- Status, payload e media type upstream vengono inoltrati sulle rotte legacy.
- I 500 upstream non vengono trasformati in successi falsi.

## Limite verificabile

La compatibilità è ricostruita dallo Swagger e dalle prove HTTP, non dal
sorgente Flask in produzione. Query SQL, accesso al database e comportamenti
non documentati potranno essere rifattorizzati e certificati solo sul
repository Flask sanificato.
