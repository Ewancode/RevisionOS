# The web server image: the built app, the pinned Python and R runtimes, and
# Caddy. Build context: frontend/ (the Caddyfile is mounted by
# docker-compose.prod.yml).
FROM node:22-alpine AS build
WORKDIR /app
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Downloaded and checksum-verified here, so the image never trusts a copy
# from your computer.
COPY scripts ./scripts
RUN sh scripts/fetch-runtimes.sh public/runtimes

COPY . .
RUN pnpm build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv
