# Le API di UniParthenope, spiegate per sezione

Panoramica in linguaggio semplice delle 8 aree funzionali del sistema, utile
per presentare cosa fa ciascuna sezione e perché serve — sia per chi deve
decidere sul progetto, sia come base per modernizzare l'app in futuro.

## Access — controllo accessi alle strutture

Gestisce chi può entrare fisicamente nelle sedi (aule, biblioteche) e con
quale modalità (in presenza o a distanza), più l'autocertificazione sanitaria
introdotta durante il Covid. Include anche l'esportazione dati per chi
amministra gli accessi.

## Badges — QR code e controllo ingressi

Genera il QR code personale mostrato all'ingresso, verifica che sia valido
quando viene scansionato ai varchi, tiene lo storico delle scansioni e
gestisce i tablet/lettori installati nelle sedi. Include anche (ormai
superata) la parte di Green Pass del periodo Covid.

## Bus — trasporti pubblici

Mostra gli orari e le posizioni in tempo reale dei bus ANM verso la sede
Centro Direzionale, prendendo i dati direttamente dal sito dell'azienda di
trasporti. **Attualmente non funzionante**: ANM ha smesso di rispondere alle
richieste automatiche (blocco 403), un problema esterno non risolvibile lato
nostro se non trovando una fonte dati alternativa.

## Eating — mense e ristorazione convenzionata

Mostra il menu del giorno dei ristoranti convenzionati con l'ateneo e
permette ai gestori di aggiornarlo. Pensato per chi vuole sapere cosa
mangiare in pausa senza uscire dal campus.

## GAUniparthenope — prenotazione aule e servizi

La parte più complessa: prenotazione di aule/laboratori per lezioni,
segnalazione di chi è effettivamente presente a lezione, prenotazione di
servizi generali (es. sale studio), ed eventi dell'ateneo. Usata sia dagli
studenti (per prenotarsi) che dai docenti (per gestire le proprie lezioni).

## Notifications — notifiche push

Permette all'app di ricevere avvisi push sul telefono: registrazione del
dispositivo, invio di notifiche a un intero corso di laurea o a persone
specifiche (es. "esame rinviato").

## Reports — reportistica per il personale

Genera report degli accessi per sede/periodo, ad uso di chi amministra gli
edifici — non usato dagli studenti.

## UniparthenopeApp — il cuore dell'app: carriera dello studente

La sezione più grande e più usata: login, libretto/piano di studi, media
voti, appelli d'esame (verifica, prenotazione, cancellazione), tasse
universitarie, informazioni su corsi/docenti, anagrafica personale, foto
profilo, news e sedi dell'ateneo. È quello che uno studente apre ogni giorno.

---

## Cosa cambia con il gateway v3

Stessa sostanza, stessa interfaccia esterna (nessuna app deve essere
riscritta) — ma dietro le quinte: sessioni con token invece di inviare la
password ad ogni richiesta, errori chiari invece di stack trace tecnici,
cache per i dati pubblici (più veloce), un limite ai tentativi di login
(protezione da attacchi di forza bruta) e nessun salvataggio di password in
chiaro da nessuna parte — a differenza del sistema attuale.
