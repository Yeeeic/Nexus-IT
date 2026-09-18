FROM python:3.13.14-slim-bookworm@sha256:67a1e1f215ccda113cfc024e8639049257e88f273898f595b61476d128d387e8

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN groupadd --system --gid 10001 nexus \
    && useradd --system --uid 10001 --gid nexus --no-create-home nexus

WORKDIR /app

COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/requirements.lock /app/backend/requirements.lock
RUN python -m pip install --no-cache-dir --only-binary=:all: \
    -r /app/backend/requirements.lock

COPY --chown=nexus:nexus backend /app/backend

USER nexus

EXPOSE 8000

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-server-header"]
