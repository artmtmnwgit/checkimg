#!/bin/bash
set -euo pipefail
cd /opt/checkimg

git pull origin main

if ! grep -q '^AUTH_SECRET=' .env 2>/dev/null; then
  echo "AUTH_SECRET=$(openssl rand -hex 32)" >> .env
elif grep -q '^AUTH_SECRET=change-me-in-production' .env; then
  sed -i "s/^AUTH_SECRET=.*/AUTH_SECRET=$(openssl rand -hex 32)/" .env
fi

docker compose up -d --build api worker frontend

sleep 10
curl -sf http://127.0.0.1:8000/health
echo
curl -sf http://127.0.0.1:8000/api/auth/me -H "Authorization: Bearer bad" -o /dev/null -w "auth route: %{http_code}\n" || true
docker compose ps --format "table {{.Name}}\t{{.Status}}"
