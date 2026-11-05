#!/usr/bin/env sh
# Invoke with: sh deploy-server.sh
set -eu
umask 077
cd "$(dirname "$0")"
compose() { docker compose -f docker-compose.server.yml "$@"; }
test -f .env || { echo 'Missing server .env; see docs/服务器部署.md.' >&2; exit 1; }
chmod 600 .env
RELEASE_TAG=${RELEASE_TAG:-$(date -u +%Y%m%dT%H%M%SZ)}
export RELEASE_TAG
compose config --quiet
# Build before stopping a running release. Keep previous image tags for rollback.
compose build
api_id=$(compose ps -a -q api)
if [ -n "$api_id" ]; then
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  backup_dir="$(pwd)/backups/$stamp"
  mkdir -p "$backup_dir"
  docker inspect --format '{{.Config.Image}}' "$api_id" > "$backup_dir/api-image.txt"
  web_id=$(compose ps -a -q web)
  if [ -n "$web_id" ]; then
    docker inspect --format '{{.Config.Image}}' "$web_id" > "$backup_dir/web-image.txt"
  fi
  # Both SQLite databases and private uploads need one consistent snapshot.
  compose stop web api
  trap 'compose start api web >&2 || true' 0
  # Only the short-lived backup helper needs to read private UID-10001 files
  # and write the operator-owned backup directory; runtime services keep ALL dropped.
  compose run --rm --no-deps -T --user 0 --cap-add DAC_OVERRIDE --entrypoint python \
    -v "$backup_dir:/backup" api -c \
    'import tarfile; a=tarfile.open("/backup/data.tar.gz","w:gz"); a.add("/srv/data",arcname="data"); a.close()'
  echo "Data backup: $backup_dir/data.tar.gz"
  trap - 0
fi
if ! compose up -d --wait --wait-timeout 300; then
  echo 'Startup failed; data volumes were preserved. Inspect: docker compose -f docker-compose.server.yml logs --tail=100' >&2
  exit 1
fi
compose exec -T api python -c \
  'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8000/health",timeout=5).read().decode())'
compose ps
printf '%s\n' "$RELEASE_TAG" > .release-tag
echo 'Containers are ready. Verify login over the configured protocol and the public URL before announcing deployment.'
