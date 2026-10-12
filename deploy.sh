#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
test -f .env || cp .env.example .env
chmod 600 .env
docker compose config --quiet
if docker volume inspect talent-discovery_talent_data >/dev/null 2>&1; then
  mkdir -p backups
  docker compose stop api web
  stamp=$(date +%Y%m%d_%H%M%S)
  docker run --rm -v talent-discovery_talent_data:/data:ro -v "$(pwd)/backups:/backup" alpine tar czf "/backup/data_$stamp.tar.gz" -C /data .
fi
docker compose up --build -d --wait --wait-timeout 300
echo 'Frontend on localhost:8501. Use an SSH tunnel for remote demo access.'
