#!/usr/bin/env bash
# Scarica la spec ufficiale v1/v2 per riconfermare i percorsi upstream.
# Da eseguire su una macchina CON rete (la sandbox di build non ne aveva).
set -euo pipefail
OUT="${1:-swagger.json}"
curl -fsSL 'https://api.uniparthenope.it/swagger.json' -o "$OUT"
echo "Spec salvata in $OUT"
python3 - "$OUT" <<'PY'
import json, sys
spec = json.load(open(sys.argv[1]))
paths = sorted(spec.get("paths", {}))
print(f"{len(paths)} percorsi. Cerca qui foto/bus/mense:")
for p in paths:
    low = p.lower()
    if any(k in low for k in ("foto", "photo", "bus", "eating", "mensa", "dining")):
        print("  ", p)
PY
