# Esposizione del gateway v3 (ambiente di test) — istruzioni per l'admin

Il gateway v3 gira già, stabile, in un container Docker sul server
(`/home/montella/uniparthenope-api-v3-gateway`, utente `montella`),
raggiungibile solo su `127.0.0.1:8080` (localhost). Mancano 3 passi, tutti
da root, per renderlo raggiungibile da internet con TLS vero.

Dominio richiesto dal prof per i test: **`api-dev.uniparthenope.it`**.

## 1. DNS — record A

Serve un sottodominio dedicato, **non** `api.uniparthenope.it` — il gateway
rispecchia anche i vecchi indirizzi legacy per compatibilità, quindi sullo
stesso dominio del sistema v1 andrebbe in conflitto con quello reale.

```
api-dev.uniparthenope.it.   A   192.167.9.47
```

(stesso IP di `api.uniparthenope.it` — nessun nuovo server, solo un nuovo
nome che punta a quello esistente)

## 2. Certificato TLS

Da lanciare **solo dopo** che il DNS del punto 1 è propagato:

```bash
certbot certonly --nginx -d api-dev.uniparthenope.it
```
(non riusare il certificato esistente di `api.uniparthenope.it`: è emesso
solo per quel nome esatto — va richiesto ex novo)

Il certificato viene salvato in:
```
/etc/letsencrypt/live/api-dev.uniparthenope.it/fullchain.pem
/etc/letsencrypt/live/api-dev.uniparthenope.it/privkey.pem
```
(sono già questi i percorsi usati nel file nginx del punto 3)

## 3. Configurazione nginx

Il file è già pronto nel repo, cartella:
`/home/montella/uniparthenope-api-v3-gateway/deploy/nginx-api-dev.conf.example`

Va copiato nella cartella dei vhost, inclusa da `/etc/nginx/nginx.conf`:
`/etc/nginx/vhosts.d/`

```bash
cp /home/montella/uniparthenope-api-v3-gateway/deploy/nginx-api-dev.conf.example /etc/nginx/vhosts.d/api-dev.uniparthenope.it.conf
nginx -t && systemctl reload nginx
```

## 4. Verifica

```bash
curl -sS https://api-dev.uniparthenope.it/v3/health
```
Deve rispondere `{"status":"ok",...}`.

## Cosa NON serve fare

- Non serve toccare `apiuniparthenope.service` (il sistema v1): resta
  invariato, il gateway v3 è un servizio completamente separato.
- Non serve dare accesso SSH a nessun altro: il gateway è già gestito
  dall'utente `montella` via Docker (`--restart unless-stopped`, sopravvive
  ai riavvii da solo).
