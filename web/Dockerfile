# Multi-stage build: compile the SvelteKit static SPA with Node, then serve
# the built assets (plus reverse-proxy to the API) with Caddy -- no Node
# runtime needed in the final image, and Caddy handles TLS automatically if
# a public hostname is configured.
FROM docker.io/library/node:22-slim AS build

WORKDIR /app
COPY package.json .
RUN npm install --no-audit --no-fund

COPY . .
RUN npm run build

FROM docker.io/library/caddy:2-alpine

COPY --from=build /app/build /srv
COPY Caddyfile /etc/caddy/Caddyfile

# Explicit non-root user (defense-in-depth: the official caddy:2-alpine
# image runs as root by default). Rootless Podman's user namespace already
# prevents root-in-container from mapping to a privileged host UID, but
# running as an unprivileged UID here also limits what a future Caddy
# vulnerability could do to sibling containers/files even inside the
# container's own mount namespace, and matches the other three services
# (api/ingestor/notifier), which already run non-root.
RUN adduser -D -u 10001 caddy-app \
    && mkdir -p /data /config \
    && chown -R caddy-app:caddy-app /data /config /srv /etc/caddy
USER caddy-app

# Caddy's official image already runs fine under rootless Podman (the
# container's UID 0 is mapped to an unprivileged host UID by the user
# namespace); listening on :8080 here (see Caddyfile) additionally avoids
# needing CAP_NET_BIND_SERVICE for a low port inside the container itself.
EXPOSE 8080
