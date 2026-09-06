# FastAPI service: search/browse/detail/identity/watch/channel/auth endpoints.
FROM docker.io/library/python:3.12-slim AS base

WORKDIR /app

# System deps for psycopg[binary] wheels are already bundled; no compiler needed.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# COPY preserves host file-mode bits, which may be restrictive (e.g. 700 on
# directories from the build context); ensure the app directory is readable
# by the non-root runtime user regardless of how the context was assembled.
RUN chmod -R a+rX /app

# Run as a non-root, unprivileged user regardless of host UID mapping --
# rootless Podman already avoids host-root privileges, this is defense in
# depth inside the container's own user namespace.
RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin appuser
USER appuser

EXPOSE 8000

# --proxy-headers with forwarded-allow-ips="*" is safe here: this container
# publishes no host port and is only reachable from other containers on the
# internal Podman network (in practice, only the `web` Caddy container),
# so trusting X-Forwarded-* from any peer that can reach us is equivalent
# to trusting Caddy specifically. This makes request.url.scheme correct
# app-wide (e.g. cookie Secure flags) behind Caddy + Cloudflare Tunnel.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
