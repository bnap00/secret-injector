# Secret Injector

An agent skill for handing a secret (API key, password, token) to a server or service
**without the secret ever going through the agent, the chat, logs, argv or shell history.**

You type the value into a one-shot web form on your own machine or network. A small script
checks it with the real provider, writes it to the env file, restarts the service, verifies the
running service uses it, and rolls back if anything fails. The agent only ever sees status lines.

## Install

Copy this directory to `~/.claude/skills/secret-injector` (all projects) or
`.claude/skills/secret-injector` inside a project. Requirements: Python 3.8+, `ssh` for remote
targets, and the Tailscale CLI if you use the `tailscale` reach.

## Use

Tell your agent something like "rotate the Stripe key on the prod server". It will ask where
you want to open the link:

| Reach | Link works from | Who can submit |
|---|---|---|
| `local` | a browser on the agent's machine | only that machine |
| `lan` | a device on the same home/office network | any device on that private network that has the link |
| `tailscale` | a device on your tailnet | only devices signed in to your Tailscale account (checked per request) |

Then open the link, type the value, submit. The link dies after one success, five failures or
30 minutes.

## What protects the secret

- Form bound to one address only; random port; 192-bit random URL; no request logging.
- Per-request admission: loopback, private LAN address, or Tailscale identity via `tailscale whois`.
- Host, Origin and Sec-Fetch-Site checks against DNS rebinding and cross-site posts.
- Values go to the sink on stdin as one JSON line, never argv or environment.
- Anything the sink prints is redacted against the submitted values before anyone sees it.
- Sink template fails closed: unwritten steps raise; a failed restart or verify rolls back.
- Env file written atomically, mode and owner preserved; backup is 0600.

Not covered: a compromised agent machine or target host, someone reading your screen, and
plain-HTTP sniffing on an untrusted LAN (use `tailscale` or `local` there).

## Layout

```
SKILL.md                     what the agent reads
scripts/serve.py             the form server
scripts/remote_py.py         run the sink on a remote host over ssh
scripts/envfile.py           set_vars / get_var / restore / perm_warning
templates/sink.py            validate → write → restart → verify → rollback
reference/                   styles, recipes, worked example
```

## License

MIT
