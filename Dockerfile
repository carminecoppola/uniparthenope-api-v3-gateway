FROM python:3.11-slim

# Immagine ufficiale con il proprio Python/OpenSSL: isola il gateway
# dall'aggiornamento del sistema operativo host (causa dell'incidente del
# 27/07/2026, in cui il Python di sistema ha perso la compatibilità SSL).

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV LOG_DIR=/app/logs
RUN mkdir -p /app/logs

# Mai come root: altrimenti i file scritti in logs/ (montato dall'host)
# risultano di proprietà di root e illeggibili/non sovrascrivibili
# dall'utente che gestisce il server (visto nell'incidente del 27/07/2026).
# Se l'host monta logs/ con un proprietario diverso da 1000, sovrascrivi con
# `docker run --user $(id -u):$(id -g) ...`.
RUN useradd --uid 1000 --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8080

# Nota sui log: uvicorn scrive richieste/avvio sul proprio logger (visibile
# con `docker logs`, non nel file qui sotto). Il container va avviato con
# `--log-opt max-size=10m --log-opt max-file=3` per farlo ruotare anch'esso
# senza crescere all'infinito (vedi README/DEPLOY_NOTES). I log applicativi
# (errori, chiamate upstream) finiscono invece in logs/app.log, con
# rotazione propria, montato come volume sull'host.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
