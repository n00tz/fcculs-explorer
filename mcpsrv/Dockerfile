# MCP server: exposes the app's read-only FCC data as MCP tools over
# streamable HTTP, so MCP-capable clients/agents can query it directly.
#
# Directory is `mcpsrv/`, not `mcp/`, deliberately: the app runs with its
# own directory on sys.path, so a top-level `mcp/` would shadow the `mcp`
# SDK package and break every import.
FROM docker.io/library/python:3.14-slim AS base

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN chmod -R a+rX /app

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 8080

CMD ["python", "-m", "app.server"]
