FROM node:22.15.0-bookworm-slim AS web-build
WORKDIR /workspace
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY web/package.json web/package.json
RUN pnpm --dir web install --frozen-lockfile
COPY web web
RUN pnpm --dir web build

FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

FROM python:3.12.11-slim-bookworm AS python-build
COPY --from=uv /uv /uvx /bin/
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        build-essential \
        libpoppler-cpp-dev \
        pkg-config \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY migrations migrations
COPY src src
RUN uv sync --frozen --no-dev

FROM python:3.12.11-slim-bookworm AS runtime
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        ca-certificates \
        libpoppler-cpp0v5 \
        tini \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 billzebub \
    && useradd --uid 10001 --gid 10001 --create-home --home-dir /home/billzebub billzebub
WORKDIR /app
COPY --from=python-build /opt/venv /opt/venv
COPY --from=python-build /app/alembic.ini ./
COPY --from=python-build /app/migrations migrations
COPY --from=python-build /app/src src
COPY --from=web-build /workspace/web/dist web-dist
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BILLZEBUB_WEB_ROOT=/app/web-dist
USER billzebub:billzebub
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["billzebub-api"]
