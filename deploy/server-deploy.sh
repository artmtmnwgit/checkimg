#!/bin/bash
set -euo pipefail
cd /opt/checkimg

git pull origin main

if ! grep -q '^AUTH_SECRET=' .env 2>/dev/null; then
  echo "AUTH_SECRET=$(openssl rand -hex 32)" >> .env
elif grep -q '^AUTH_SECRET=change-me-in-production' .env; then
  sed -i "s/^AUTH_SECRET=.*/AUTH_SECRET=$(openssl rand -hex 32)/" .env
fi

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build api worker frontend nginx

sleep 12
curl -sf http://127.0.0.1/health || { echo "WARN: :80 health failed, retry..."; sleep 5; curl -sf http://127.0.0.1/health || true; }
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart nginx 2>/dev/null || true
echo
curl -sf http://127.0.0.1:8000/health || true
echo
curl -sf http://127.0.0.1/api/auth/me -H "Authorization: Bearer bad" -o /dev/null -w "auth via :80: %{http_code}\n" || true
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
