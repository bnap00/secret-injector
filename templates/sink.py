# secret-injector sink. Runs ON THE MACHINE THAT HOLDS THE ENV FILE.
#   remote: python3 <skill>/scripts/remote_py.py user@HOST <skill>/scripts/envfile.py sink.py
#           (envfile.py is prepended, so set_vars/get_var/restore/perm_warning are already defined)
#   local : uncomment the IMPORT line below.
#
# Contract: one JSON line of form fields on stdin -> status lines on stdout -> exit 0 only when the
# new secret is verified working. Every TODO raises until you write it: an unfinished sink fails
# closed. Never print, log or write a value anywhere; serve.py redacts, but don't rely on it.
import json, subprocess, sys, time, urllib.error, urllib.request

# IMPORT (local only): sys.path.insert(0, "/path/to/secret-injector/scripts"); from envfile import *

ENV_FILE = "/path/to/.env"      # TODO
STYLE = "compose"               # TODO compose | dotenv | shell  (reference/env-files.md)
KEYS = {"API_KEY": "api_key"}   # TODO  env var name -> form field name


def say(msg):
    print(msg, flush=True)


def validate(new):
    """Test the NEW values against the real provider BEFORE anything changes.
    Return None if accepted, else a short reason (the provider's status/message, never the value).
    For blank optional fields, fall back to get_var(ENV_FILE, KEY)."""
    raise NotImplementedError("validate(): TODO")  # e.g. POST to the provider's auth endpoint


def restart():
    """Make the consumer reload the file. Wait for it to be idle first if it processes jobs,
    then wait until it reports healthy. Raise on failure."""
    raise NotImplementedError("restart(): TODO")  # e.g. docker compose up -d <svc> / systemctl restart <unit>


def verify():
    """Prove the RUNNING service now uses the new value (e.g. docker exec ... auth call using its env).
    Return None if it works, else a short reason."""
    raise NotImplementedError("verify(): TODO")


def main():
    fields = json.loads(sys.stdin.readline())
    new = {env: fields.get(field, "") for env, field in KEYS.items()}
    if not any(new.values()):
        say("REJECTED: nothing entered. Nothing changed."); return 1
    reason = validate(new)
    if reason:
        say(f"REJECTED: {reason}. Nothing changed."); return 1
    say("1/4 New secret validated with the provider")
    warn = perm_warning(ENV_FILE)
    if warn:
        say("note: " + warn)
    bak = set_vars(ENV_FILE, new, STYLE)
    say(f"2/4 {ENV_FILE} updated" + (f" (backup: {bak})" if bak else ""))
    try:
        restart()
        say("3/4 Service restarted")
        reason = verify()
        if reason:
            raise RuntimeError(reason)
    except Exception as e:
        say(f"ERROR: {type(e).__name__}: {str(e)[:300]}")
        if bak:
            restore(ENV_FILE, bak); say("Rolled back to the previous file")
            try:
                restart(); say("Service restarted with the previous secret")
            except Exception as e2:
                say(f"ERROR: restart after rollback failed: {str(e2)[:300]}. Needs a human.")
        return 3
    say("4/4 Verified: the running service uses the new secret")
    return 0


if __name__ == "__main__":
    sys.exit(main())
