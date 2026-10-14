---
name: secret-injector
description: Hand over or rotate a secret (API key, password, token) on a server or local service without the value ever passing through the agent, chat, logs, argv or shell history. The user types it into a one-shot web form; a sink validates, writes, restarts and verifies, and reports status only. Use whenever a credential must be entered, updated or rotated somewhere, or the user offers to paste one.
---

# Secret injector

The user types the secret into a short-lived web form. Your sink moves it to where it belongs
and prints **status lines only**. You never see the value, and neither does the transcript.

## Hard rules

- **Never ask for the secret in chat** and never read it back. If the user pastes it anyway,
  tell them it is now in the transcript and must be rotated, then use this skill to rotate it.
- **Secrets travel only on stdin.** Never in argv (`ps`), env vars of commands you print, files
  you `cat`, URLs or query strings.
- **Print statuses, not values.** No `cat .env`, `docker compose config`, `env`, `printenv`,
  `set -x`, `docker inspect`. Never open the backup file. Never write debug files from the sink.
- **Only `serve.py` serves the form.** Do not write your own server, tunnel (ngrok, cloudflared,
  ssh -R), port-forward, or edit the reach checks. If it refuses to start, fix the cause.
- **Validate before writing, verify after restart, roll back on failure.** The template does
  this; keep that shape.
- **Scope production changes.** Restart only the affected service, after it is idle.

## Files (paths relative to this skill directory)

| File | Role |
|---|---|
| `scripts/serve.py` | One-shot form. `--reach local|lan|tailscale` picks who can open it and binds only there. Random port, random URL, checks who connects, no request logging, redacts submitted values from sink output, closes on success / timeout / max attempts. |
| `scripts/remote_py.py` | Runs local `.py` file(s) on `HOST` over ssh. Code travels base64 in argv; stdin passes through. Libraries first. |
| `scripts/envfile.py` | `set_vars`, `get_var`, `restore`, `perm_warning`. Atomic write, 0600 backup, keeps the file's mode and owner. Styles: `compose`, `dotenv`, `shell`. |
| `templates/sink.py` | Validate → write → restart → verify → roll back on failure. Every TODO raises until written. |
| `reference/env-files.md` | Which style for which consumer, quoting rules, restart and verify recipes. |
| `reference/example-shiprocket.md` | Complete worked example (docker compose env file on a remote host). |

## Procedure

1. **Recon, no secrets involved.** Find where the secret lives and how it is consumed: the env
   file, the consumer (compose `env_file`, dotenv, systemd `EnvironmentFile`, shell-sourced), how
   to restart it, how to tell it is idle and healthy, and a call that proves the credential works.
   Look at key *names* only: `grep -n '^KEY=' .env | cut -d= -f1`. Pick `STYLE` from
   `reference/env-files.md`.
2. **Pick the reach with the user.** Ask in plain words where they will open the link:
   - on this computer → `--reach local`
   - on a phone or laptop on the same home/office Wi-Fi → `--reach lan` (unencrypted on that
     network, so only for networks they trust)
   - on a device signed in to the same Tailscale account → `--reach tailscale` (preferred when
     available; the form admits only that account). If `tailscale status` says the device is
     not online, fall back to `local` or `lan`. If this node is tagged, pass `--allow-user`.
3. **Write the sink** in a fresh scratch directory (`mktemp -d`) from `templates/sink.py`. Fill in
   every TODO, then `python3 -I -m py_compile sink.py`. For a remote target the sink command is
   `python3 <skill>/scripts/remote_py.py user@HOST <skill>/scripts/envfile.py /tmp/x/sink.py`.
   For a local target, uncomment the IMPORT line in the template and run `python3 -I /tmp/x/sink.py`.
   Ssh to the host once before (`ssh -o BatchMode=yes HOST true`) so keys and known_hosts work.
4. **Start the form in the background** and read the URL from its output:
   ```
   python3 -I <skill>/scripts/serve.py --reach tailscale \
     --title "Shiprocket API user -> prod" \
     --note "Checked with Shiprocket first; nothing changes unless the login works." \
     --fields '[{"name":"password","label":"API password","type":"password"},
                {"name":"email","label":"Email (blank = keep current)","type":"email","optional":true}]' \
     -- python3 <skill>/scripts/remote_py.py root@HOST <skill>/scripts/envfile.py /tmp/x/sink.py
   ```
   Smoke-test: `curl` of the URL returns 200 (local) or 200/403 (tailscale, depending on whois
   of this machine), and a wrong path returns 404.
5. **Give the user the URL** with a plain-words explanation. See "What to tell the user".
6. **When the background task finishes**, read its output (redacted status lines, who submitted,
   sink exit code) and report the outcome. Never retry by asking for the value in chat.
7. **Cleanup.** Delete the scratch sink. The backup holds the *old* secret: offer to delete it
   once the user is happy, and recommend rotating anything that leaked earlier.

## What to tell the user

Keep it to four short sentences: open this link on the device we agreed on; type the new
value and press Submit; it is checked with the provider first and nothing changes if it is
wrong; the link stops working after one success or 30 minutes. Mention the backup and any
`note:` line the sink printed (for example a world-readable env file).

## Sink contract

- stdin: exactly one JSON line `{"<field name>": "<value>", ...}`. Blank optional fields are `""`.
- stdout: short status lines; shown to the user and to you, after redaction.
- Exit `0` only when the new secret is verified working. Anything else re-shows the form, up
  to `--max-attempts`. Exit `1` for "rejected by provider, nothing changed", `3` for "rolled back".
