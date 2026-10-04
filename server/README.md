# WristMind server v2

This directory is a clean backend. It does not import the legacy phone bridge,
legacy audio protocol, or any previous database/history.

## Local verification

```powershell
py -3.12 -m venv .venv-v2
.\.venv-v2\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv-v2\Scripts\python.exe -m pytest -q
```

Development defaults use an empty SQLite database and mock AI providers. The
container stack uses PostgreSQL 16 with pgvector, a separate worker, private
file storage, and nginx on host port `80` during the pre-TLS smoke stage.

## First deployment

1. Copy `.env.production.example` to `.env` and replace every generated value.
2. Keep provider mocks enabled until health and enrollment smoke tests pass.
3. Run `docker compose up -d --build`.
4. Verify `http://server/health` and enrollment before adding real keys.
5. Put HTTPS in front of the service before enrolling personal devices.

The bootstrap secret is only used to enroll the first administrative phone.
The phone creates short-lived pairing codes for watches. Device bearer tokens
are stored only as hashes.

## Updating the Orange Pi

The private repository is read through a dedicated read-only deploy key. On the
server, run `sh /home/ivan/wristmind-project/server/deploy/update-server.sh`.
The script performs a fast-forward-only Git pull, rebuilds the containers, and
prints their final state. The ignored `server/.env` and Docker volumes remain
outside Git.
