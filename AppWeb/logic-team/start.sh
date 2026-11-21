#!/usr/bin/env sh
# Arranque en producción (Render): aplica las migraciones y levanta gunicorn.
set -e
python manage.py migrate --noinput
exec gunicorn config.wsgi:application --bind "0.0.0.0:${PORT:-8000}" --workers "${WEB_CONCURRENCY:-2}" --timeout 60 --access-logfile -
