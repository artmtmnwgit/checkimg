#!/bin/bash
set -euo pipefail
cd /opt/checkimg

python3 <<'PY'
from pathlib import Path

# Fix .env: single CORS line removed (set in compose instead)
p = Path(".env")
lines = [l for l in p.read_text().splitlines() if not l.startswith("CORS_ORIGINS=")]
p.write_text("\n".join(lines) + "\n")

# Inject CORS into docker-compose api + worker environment
compose = Path("docker-compose.yml").read_text()
needle = "      IMAGE_STORE_DIR: /app/data/images\n"
insert = needle + '      CORS_ORIGINS: \'["http://31.77.146.7:5173","http://checkimg.play2go.cloud:5173"]\'\n'
if "CORS_ORIGINS:" not in compose:
    compose = compose.replace(needle, insert, 2)
    Path("docker-compose.yml").write_text(compose)
PY

docker compose up -d api frontend worker
sleep 8
curl -sf http://127.0.0.1:8000/health && echo OK
curl -sI -X OPTIONS http://127.0.0.1:8000/api/scan \
  -H "Origin: http://31.77.146.7:5173" \
  -H "Access-Control-Request-Method: POST" | head -8
