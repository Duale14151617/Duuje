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
EXPOSE 10000
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py createcachetable && python manage.py seed_reference_data && python manage.py seed_demo_data && python -m gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-10000} --workers 2 --timeout 60 --access-logfile -"]
