FROM python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641 AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app/backend

FROM base AS build
# Keep the deployment image small enough for the required disk reserve.
ENV UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.13.4@sha256:9f130421e930bfbdc563c00740466603f8723158e90297d07957c2294640262b /uv /usr/local/bin/uv
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
ENV PATH="/app/backend/.venv/bin:$PATH"
COPY backend/ ./
COPY frontend/templates/ /app/frontend/templates/
COPY frontend/static/ /app/frontend/static/
RUN APP_BUILD=1 python manage.py collectstatic --noinput --verbosity 0 --ignore js/questionnaires.js && chmod +x entrypoint.sh

FROM base AS runtime
ENV PATH="/app/backend/.venv/bin:$PATH"
RUN groupadd --gid 10001 compass && useradd --uid 10001 --gid compass --no-create-home compass
COPY --from=build --chown=10001:10001 /app/ /app/
USER 10001:10001
EXPOSE 8000
ENTRYPOINT ["/app/backend/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind=0.0.0.0:8000", "--workers=2", "--timeout=30", "--access-logfile=-", "--access-logformat=%(m)s %(s)s %(D)s", "--error-logfile=-"]
