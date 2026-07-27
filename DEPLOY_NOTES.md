# Note di deploy sul cluster (montella@192.167.9.47)

## Deploy attuale: Docker (dal 27/07/2026)

Il gateway gira in un container Docker invece che in un venv diretto —
`montella` è nel gruppo `docker` (aggiunto durante l'aggiornamento del SO),
quindi nessun bisogno di root/systemd.

```bash
cd ~/uniparthenope-api-v3-gateway
docker build -t uniparthenope-v3-gateway .
docker rm -f uniparthenope-v3-gateway 2>/dev/null
docker run -d --name uniparthenope-v3-gateway \
  --restart unless-stopped \
  --user $(id -u):$(id -g) \
  --log-opt max-size=10m --log-opt max-file=3 \
  -p 127.0.0.1:8080:8080 \
  -e MOCK_ESSE3=0 \
  -e UPSTREAM_BASE=https://api.uniparthenope.it \
  -e UPSTREAM_TIMEOUT_S=25 \
  -v $(pwd)/logs:/app/logs \
  uniparthenope-v3-gateway
```

`docker compose` non è installato su questo server (né il plugin né il
binario standalone) — si usano `docker build`/`docker run` diretti.

**Perché Docker**: risolve due problemi visti nell'incidente del 27/07 (vedi
sotto) — l'immagine si porta dietro il proprio Python/OpenSSL, isolata
dall'aggiornamento del sistema operativo host; e con `--restart
unless-stopped` (Docker è abilitato all'avvio: `systemctl is-enabled docker`
→ enabled) il gateway **si rialza da solo dopo un riavvio del server**, senza
bisogno di root/systemd per il nostro processo.

## Dove sono i log

- `logs/app.log` (montato dall'host, rotazione automatica 10MB×5): log
  applicativi — chiamate upstream, errori, tracciati non gestiti.
- `docker logs uniparthenope-v3-gateway`: richieste HTTP e avvio/arresto del
  processo uvicorn (rotazione via `--log-opt max-size=10m --log-opt
  max-file=3`, impostata all'avvio del container).

Le API key emesse sono **solo in memoria**: si perdono ad ogni riavvio del
container (rebuild, `docker restart`, riavvio del server) e vanno riemesse
con `POST /v3/api-keys`.

## Incidente 27/07/2026: aggiornamento del sistema operativo (storico)

Durante l'aggiornamento del SO del cluster (openSUSE Leap 15.2 → 15.4), il
Python 3.9 di sistema (`/usr/local/bin/python3.9`) ha perso la compatibilità
SSL (`libssl.so.45: version 'LIBRESSL' not found`). Il venv del gateway era
costruito su quel Python 3.9 ed è quindi diventato inutilizzabile (uvicorn
non parte, serve `ssl` per httpx). Fix temporaneo (venv su Python 3.11) poi
superato passando a Docker, che rende il problema strutturalmente impossibile
da ripetere.
