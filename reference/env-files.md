# Env files: styles, quoting, restart and verify recipes

## Pick `STYLE` from the consumer

| Consumer | How to recognise it | `STYLE` | Reload |
|---|---|---|---|
| docker compose `env_file:` / `.env` | `env_file:` or `${VAR}` in `compose.yaml` | `compose` | `docker compose up -d <svc>` recreates the container when the file changed |
| node `dotenv` / `dotenv-expand` | `require('dotenv')`, `import 'dotenv/config'` | `dotenv` | restart the process (`pm2 restart <app>`, `systemctl restart`, container restart) |
| python-dotenv | `load_dotenv()` | `dotenv` (avoid backticks: values with `'` are rejected, ask for a value without `'`) | restart the process |
| systemd `EnvironmentFile=` | the unit file | `shell` | `systemctl restart <unit>` |
| sourced by a shell script | `. ./.env` or `source .env` | `shell` | re-run the script or restart the service that runs it |

Compose and shell both honour `export KEY=...`; `set_vars` keeps an existing `export ` prefix.

## Quoting rules `envfile.quote_env` applies

- All styles: newline or NUL in a value is rejected.
- Default is single quotes, which are literal everywhere.
- Value contains `'`:
  - `compose` → double quotes with `\\`, `\"` and `$$` (compose interpolates `$` inside double quotes).
  - `dotenv` → backticks (node dotenv ≥ 15). A value with both `'` and `` ` `` is rejected.
  - `shell` → `'...'` with `'` written as `'\''`.

## Verify from inside the running service

The point is to prove the *running* process sees the new value, not just the file.

- Container: `docker exec <ctr> node -e '<auth call using process.env.KEY; print status only>'`
  or `docker exec <ctr> python3 -c '...'`.
- systemd service: `systemd-run --wait -p EnvironmentFile=<file> <command>` or call the
  service's own health/whoami endpoint that uses the credential.
- Prefer an endpoint that fails fast with a clear status code (login, whoami, list with limit 1).

## Waiting for idle and healthy

- Health: poll the service's health endpoint until 200, with a deadline (60 to 120 s).
- Idle: if the service processes jobs, poll its queue/status endpoint until no job is active
  before restarting. Put a deadline on it and report `ERROR: still busy after N s` instead of
  restarting mid-job.

## Permissions

`set_vars` keeps the file's existing mode and owner so a service running as another user does
not lose access. `perm_warning(path)` returns a message when the file is group/world readable;
the template prints it as a `note:` line so the user can decide. Backups are always 0600.
