# Note di deploy sul cluster (montella@192.167.9.47)

## Incidente 27/07/2026: aggiornamento del sistema operativo

Durante l'aggiornamento del SO del cluster (openSUSE Leap 15.2 → 15.4), il
Python 3.9 di sistema (`/usr/local/bin/python3.9`) ha perso la compatibilità
SSL (`libssl.so.45: version 'LIBRESSL' not found`). Il venv del gateway era
costruito su quel Python 3.9 ed è quindi diventato inutilizzabile (uvicorn
non parte, serve `ssl` per httpx).

**Fix applicato**: venv ricostruito con `/usr/bin/python3.11` (SSL
funzionante, OpenSSL 1.1.1l), stesso `requirements.txt`, nessuna modifica al
codice del gateway. Il vecchio venv rotto è stato rinominato
`.venv_old_py39_broken` invece di essere cancellato.

**Comando di avvio corretto su questo server**:

```bash
cd ~/uniparthenope-api-v3-gateway
/usr/bin/python3.11 -m venv .venv   # se il venv non esiste già
source .venv/bin/activate
pip install -r requirements.txt

export MOCK_ESSE3=0
export UPSTREAM_BASE='https://api.uniparthenope.it'
export UPSTREAM_TIMEOUT_S=25
nohup uvicorn app.main:app --host 127.0.0.1 --port 8080 --proxy-headers \
  > gateway.log 2>&1 &
disown
```

Nota: il processo non è gestito da systemd (nessun accesso root disponibile
su questo server per l'utente `montella`) — sopravvive alla disconnessione
SSH (`KillUserProcesses=no` sul sistema), ma **non sopravvive a un riavvio
del server**. Va rilanciato manualmente dopo ogni reboot finché non si ha
un modo per registrarlo come servizio (systemd user unit con linger, o unità
root-level).
