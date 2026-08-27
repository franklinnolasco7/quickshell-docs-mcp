# Slim image speaking MCP over stdio (the transport MCP clients expect).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY quickshell_mcp ./quickshell_mcp

RUN uv pip install --system --no-cache .

ENTRYPOINT ["quickshell-mcp"]
