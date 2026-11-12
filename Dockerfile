# Build the existing React frontend, then serve it and the Django API from one
# origin so session cookies and CSRF protections work without cross-site cookies.
FROM node:20-alpine AS frontend-build
WORKDIR /src/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt
COPY backend/ ./
COPY --from=frontend-build /src/frontend/dist ./frontend_dist
# The web process and the start-up commands need no write access to the image: run them as an unprivileged user.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app
EXPOSE 10000
# Fast wake-up: only migrate runs before the web server starts. The idempotent seed/cleanup
# commands run in the background right after gunicorn begins listening, so the port opens in
# seconds instead of minutes. A failed migrate still stops the container (as before).
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py createcachetable && { ( python manage.py seed_reference_data && python manage.py apply_army_structure --apply && python manage.py remove_legacy_structure --apply --purge && python manage.py rename_sample_data --apply && python manage.py seed_sample_data && python manage.py seed_test_personnel --from-env && python manage.py report_duplicate_identities || echo 'Background seeding stopped early - see messages above' ) & exec python -m gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 60 --access-logfile -; }"]
