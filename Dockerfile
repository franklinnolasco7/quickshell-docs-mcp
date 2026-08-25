# Slim image speaking MCP over stdio (the transport MCP clients expect).
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY quickshell_docs_mcp ./quickshell_docs_mcp

RUN uv pip install --system --no-cache .

ENTRYPOINT ["quickshell-docs-mcp"]
