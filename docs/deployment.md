# Deploying Revision OS

This puts Revision OS on a small server of your own, at your own domain, with
HTTPS. That is what makes it usable from your phone, including push
reminders. Everything runs in Docker from one compose file
(`infra/docker-compose.prod.yml`):

| Service | What it does |
| --- | --- |
| `web` | Caddy: HTTPS (certificates are automatic), the app, and the Python and R runtimes, with strict security headers. The only service reachable from outside, on ports 80 and 443. |
| `api` | The FastAPI backend. Applies database migrations when it starts. |
| `worker` | Background jobs: processing uploads, Claude calls, exports and restores. |
| `scheduler` | Push reminders every few minutes; empties the trash and old exports daily. |
| `db`, `redis` | PostgreSQL with pgvector, and the job queue. Not reachable from outside. |
| `backup` | A database dump at start-up and then daily, in `./backups`. |

## What you need

- **A server.** Any Linux virtual server with Docker: 2 CPUs and **4 GB of
  memory** (the search model and document processing need it), 40 GB of disk.
  Small cloud servers cost a few pounds a month (for example Hetzner, OVH or
  DigitalOcean).
- **A domain name** (or a subdomain of one you have) whose DNS `A` record (and
  `AAAA`, for IPv6) points at the server.
- **Optionally, a storage bucket** for your files: Cloudflare R2 (free up to
  10 GB) or Backblaze B2. Without one, files are kept on the server's disk.

## 1. Prepare the server

On a fresh Ubuntu 24.04 server, signed in as a user who can use `sudo`:

```bash
# Docker Engine and the compose plugin (https://docs.docker.com/engine/install/ubuntu/)
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # then sign out and back in

# Only SSH and the web are reachable from outside.
sudo ufw allow OpenSSH
sudo ufw allow 80/tcp
sudo ufw allow 443
sudo ufw enable

sudo apt-get install -y make git
```

## 2. Get the code and configure it

```bash
git clone https://github.com/Ewancode/RevisionOS.git
cd RevisionOS
cp .env.example .env
nano .env
```

In `.env`, set:

| Setting | Value |
| --- | --- |
| `APP_ENV` | `production` |
| `POSTGRES_PASSWORD` | a long random password: `openssl rand -base64 24` |
| `DATABASE_URL` | the same password in this URL (only used outside Docker, but keep it consistent) |
| `DOMAIN` | your site's name, e.g. `revision.example.com` |
| `ANTHROPIC_API_KEY` | your Claude API key (optional) |
| `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUBJECT` | for push reminders: run `make vapid-keys` on your own computer and copy the three lines from its `.env` |

`.env` holds your secrets: keep it on the server only (`chmod 600 .env`), and
never commit it.

### Files in a bucket (optional)

To keep uploaded files in Cloudflare R2 rather than on the server's disk:

1. In the Cloudflare dashboard, create an R2 bucket (leave public access
   **off**: files are only ever served through the app, after it checks they
   are yours).
2. Create an R2 API token with **Object Read & Write** for that bucket only.
3. In `.env`:

   ```
   STORAGE_BACKEND=s3
   S3_BUCKET=revision-os
   S3_ENDPOINT_URL=https://<your account id>.r2.cloudflarestorage.com
   S3_REGION=auto
   S3_ACCESS_KEY_ID=...
   S3_SECRET_ACCESS_KEY=...
   ```

Backblaze B2 works the same way with its S3-compatible endpoint
(`https://s3.<region>.backblazeb2.com`). Turning on the bucket's object
versioning (or B2's "keep all versions") gives you a second copy of every file
if one is ever deleted by mistake.

## 3. Start it

```bash
make prod-up            # builds the images and starts everything
make prod-logs          # Ctrl+C to stop following
make prod-create-user   # your account (registration is closed)
```

The first build takes several minutes. Then open `https://<your domain>`.
Caddy fetches the HTTPS certificate on the first visit; if that fails, check
that ports 80 and 443 are open and that your domain's DNS points at the
server.

`GET https://<your domain>/api/v1/health/ready` answers `"status": "ready"`
when the API can reach the database and Redis.

## 4. Bring your data across

On your computer, in Revision OS: **Settings > Your data > Export my data**,
then download the ZIP. On the server's site, signed in to your new (empty)
account: **Settings > Your data > Restore from an export…** and choose the ZIP.
Everything comes across: modules, materials and their files, questions,
flashcards with their review history, attempts, plans, conversations and
settings.

## Backups

The `backup` service dumps the database when it starts and every 24 hours
after, into `backups/` in the repository folder, keeping
`BACKUP_KEEP_DAYS` (default 14) days of dumps. **Copy them off the server
too**: a backup on the same disk does not survive losing the server. For
example, with [rclone](https://rclone.org) set up for your R2 or B2 account,
a nightly cron job:

```bash
# crontab -e
30 4 * * * rclone copy ~/RevisionOS/backups r2:revision-os-backups
```

If your files are on the server's disk (`STORAGE_BACKEND=local`), back them up
too; they are in the `appdata` volume:

```bash
docker run --rm -v revision-os-prod_appdata:/data -v ~/RevisionOS/backups:/out alpine \
  tar czf /out/files-$(date -u +%Y%m%d).tgz -C /data storage
```

With a bucket, the bucket keeps them (turn on versioning, as above).

Your own **export** (Settings > Your data) is a third, portable copy that does
not depend on any of this.

### Restoring the database from a dump

```bash
docker compose -f infra/docker-compose.prod.yml --env-file .env stop api worker scheduler
docker compose -f infra/docker-compose.prod.yml --env-file .env exec -T db \
  sh -c 'pg_restore --clean --if-exists --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < backups/revision-os-YYYYMMDD-HHMM.dump
make prod-up
```

## Updating

```bash
git pull
make prod-up    # rebuilds what changed; the API applies new migrations on start
```

## Good to know

- **Security:** only Caddy is exposed. The API documentation is switched off
  in production, cookies are HTTPS-only, and every page is sent with a strict
  Content-Security-Policy ([security.md](security.md)).
- **The Python and R runtimes** are built into the web image, pinned and
  checked against their checksums (`frontend/scripts/fetch-runtimes.sh`), so
  no third party serves code to your browser. Python packages are verified
  against Pyodide's lock file; R packages come from the WebR repository.
- **Memory:** the worker is capped at 2 GB while processing documents. On a
  server with less than 4 GB, processing large PDFs may fail; upload smaller
  files or choose a bigger server.
- **Trying the production setup locally:** set `DOMAIN=localhost`,
  `HTTP_PORT=8080` and `HTTPS_PORT=8443` in a separate env file and run the
  compose file with `-p revision-os-try --env-file <that file>`. Caddy then
  uses its own local certificate, which your browser will warn about.
