# FCC ULS Explorer & Alerting Service

Self-hostable service for browsing FCC ULS Amateur Radio Service and Antenna
Structure Registration (Tower) data, with watch-based alerting (email,
email-to-SMS, or webhook) on changes to a specific callsign or ULS ID.

## Status

Early scaffolding — see `docs/plan.md` for the full implementation plan and
`docs/todo-status.md` for current progress.

## Stack

- **API**: Python 3.12 + FastAPI
- **Database**: PostgreSQL 16
- **Cache/Queue**: Redis 7 + RQ
- **Frontend**: SvelteKit (static build)
- **Reverse proxy**: Caddy
- **Deployment**: rootless Podman via `podman-compose`/`podman compose`

## Repository Layout

```
api/        FastAPI backend (search, browse, watches, notification config)
ingestor/   FCC data downloader/parser/diff/upsert job
notifier/   RQ worker: SMTP, email-to-SMS, webhook delivery
web/        SvelteKit frontend
db/         SQL migrations / schema
deploy/     Dockerfiles, compose.yaml, .env.example
docs/       Plan and reference docs
```

## Data Sources

- FCC ULS Amateur Radio Service complete + daily transaction files.
- FCC ULS Antenna Structure Registration (ASR) complete + daily transaction
  files.

All data is free, public, and unauthenticated per FCC's public access
program. See `docs/fcc-data-reference.md` for verified current URLs and file
format details.

## License / Attribution

FCC ULS data is public domain U.S. government data. This project itself will
be licensed separately (TBD).
