FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app

RUN uv sync --frozen --no-dev

ENV UV_NO_SYNC=1

RUN git remote set-url origin https://github.com/kdan-mobile-software-ltd/security_info_bot.git \
    && git config --global --add safe.directory /app \
    && git config --global credential.helper \
       '!f() { echo username=x-access-token; echo "password=${GITHUB_PAT}"; }; f' \
    && chmod +x /app/docker-entrypoint.sh

ENTRYPOINT ["/app/docker-entrypoint.sh"]
