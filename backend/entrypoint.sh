#!/bin/sh
set -eu
if [ "${1:-}" = "gunicorn" ]; then
  python manage.py migrate --noinput
  python manage.py createcachetable
fi
exec "$@"
