FROM python:3.12-slim AS builder

WORKDIR /build
COPY pyproject.toml ./
COPY src ./src
COPY VERSION ./
RUN pip install --no-cache-dir --prefix=/install .


FROM node:20-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/ ./
# Tolerates an empty frontend/ (Release 1A phase A): produce an empty dist so
# the runtime COPY below always has something to take.
RUN if [ -f package.json ]; then \
        (if [ -f package-lock.json ]; then npm ci; else npm install; fi) && npm run build; \
    else \
        mkdir -p dist; \
    fi


FROM python:3.12-slim AS runtime

ARG APP_VERSION=dev
ARG BUILD_TIMESTAMP=unknown
ENV APP_VERSION=${APP_VERSION} \
    BUILD_TIMESTAMP=${BUILD_TIMESTAMP}

# Unraid runs containers as nobody:users (uid 99, gid 100). Used numerically to
# avoid colliding with the base image's existing gid-100 "users" group.
COPY --from=builder /install /usr/local
COPY --chown=99:100 src /app/src
COPY --chown=99:100 VERSION /app/VERSION
COPY --chown=99:100 migrations /app/migrations
COPY --chown=99:100 --from=frontend-builder /frontend/dist /app/frontend/dist

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

RUN mkdir -p /app/config /app/state && chown -R 99:100 /app

VOLUME ["/app/config", "/app/state"]

EXPOSE 8080

USER 99:100

ENTRYPOINT ["python", "-m", "ladelaug_avregning"]
