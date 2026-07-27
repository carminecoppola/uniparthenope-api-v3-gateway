# Esposizione pubblica del gateway v3 — istruzioni

Il gateway v3 gira già, stabile, in un container Docker sul server
(`~/uniparthenope-api-v3-gateway`, utente `montella`), raggiungibile solo su
`127.0.0.1:8080` (localhost). Manca solo l'ultimo passo: renderlo
raggiungibile da internet con TLS vero.

## 1. DNS

Serve un sottodominio dedicato, **non** `api.uniparthenope.it` — il gateway
rispecchia anche i vecchi indirizzi legacy per compatibilità, quindi sullo
stesso dominio del sistema v1 andrebbe in conflitto con quello reale.

Proposta: `api-v3.uniparthenope.it` → stesso IP del server attuale.

## 2. Certificato TLS

```bash
certbot certonly --nginx -d api-v3.uniparthenope.it
```
(non riusare il certificato esistente di `api.uniparthenope.it`: è emesso
solo per quel nome esatto)

## 3. Configurazione nginx

Il file è già pronto nel repo:
`~/uniparthenope-api-v3-gateway/deploy/nginx-v3.conf.example`

Copiarlo in `/etc/nginx/vhosts.d/` (o dove sono gli altri vhost), verificare
i percorsi del certificato del punto 2, poi:

```bash
nginx -t && systemctl reload nginx
```

## 4. Verifica

```bash
curl https://api-v3.uniparthenope.it/v3/health
```
Deve rispondere `{"status":"ok",...}`.

## Cosa NON serve fare

- Non serve toccare `apiuniparthenope.service` (il sistema v1): resta
  invariato, il gateway v3 è un servizio completamente separato.
- Non serve dare accesso SSH a nessun altro: il gateway è già gestito
  dall'utente `montella` via Docker (`--restart unless-stopped`, sopravvive
  ai riavvii da solo).
