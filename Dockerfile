FROM python:3.14-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=oven/bun:latest /usr/local/bin/bun /usr/local/bin/bun

RUN ln -s /usr/local/bin/bun /usr/local/bin/node

RUN bun install -g @anthropic-ai/claude-code

ENV PATH="/root/.bun/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY tldr/ ./tldr/

ENTRYPOINT ["uv", "run", "python", "-m", "tldr"]
