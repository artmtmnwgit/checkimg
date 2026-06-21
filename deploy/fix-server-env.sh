#!/bin/bash
set -euo pipefail
cd /opt/checkimg

python3 <<'PY'
from pathlib import Path
p = Path(".env")
lines = [l for l in p.read_text().splitlines() if not l.startswith("CORS_ORIGINS=")]
lines.append('CORS_ORIGINS=["http://31.77.146.7:5173","http://checkimg.play2go.cloud:5173"]')
p.write_text("\n".join(lines) + "\n")
PY

grep CORS_ORIGINS .env
docker compose restart api frontend
sleep 6
curl -sf http://127.0.0.1:8000/health
echo
curl -sI -X OPTIONS http://127.0.0.1:8000/api/scan \
  -H "Origin: http://31.77.146.7:5173" \
  -H "Access-Control-Request-Method: POST" | grep -iE 'HTTP|access-control'
