# Worked example: Shiprocket credentials in a docker compose env file on a remote host

Situation: `server/.env` on `root@77.42.38.22` is loaded by `env_file:` for service
`orcaslicer-slicer`, container `orcaslicer-container`. The app exposes `GET /health` on port 7777
with an `activeJobs` count.

## Recon (no secrets)

```
ssh root@77.42.38.22 "grep -n '^SHIPROCKET_' /srv/app/server/.env | cut -d= -f1"
ssh root@77.42.38.22 "grep -n env_file -A1 /srv/app/compose.yaml"
```

## Sink (`/tmp/x/sink.py`, filled-in template)

```python
ENV_FILE = "/srv/app/server/.env"
STYLE = "compose"
KEYS = {"SHIPROCKET_EMAIL": "email", "SHIPROCKET_PASSWORD": "password"}

def validate(new):
    email = new["SHIPROCKET_EMAIL"] or get_var(ENV_FILE, "SHIPROCKET_EMAIL")
    body = json.dumps({"email": email, "password": new["SHIPROCKET_PASSWORD"]}).encode()
    req = urllib.request.Request("https://apiv2.shiprocket.in/v1/external/auth/login", body,
                                 {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return None if json.load(r).get("token") else "login returned no token"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code} from Shiprocket"

def restart():
    deadline = time.time() + 120
    while time.time() < deadline:
        with urllib.request.urlopen("http://127.0.0.1:7777/health", timeout=5) as r:
            if json.load(r).get("activeJobs", 0) == 0:
                break
        time.sleep(5)
    else:
        raise RuntimeError("service still busy after 120 s; not restarting")
    subprocess.run(["docker", "compose", "-f", "/srv/app/compose.yaml", "up", "-d", "orcaslicer-slicer"],
                   check=True, capture_output=True, text=True)
    deadline = time.time() + 90
    while time.time() < deadline:
        r = subprocess.run(["docker", "inspect", "-f", "{{.State.Health.Status}}", "orcaslicer-container"],
                           capture_output=True, text=True)  # prints status only, never env
        if r.stdout.strip() == "healthy":
            return
        time.sleep(3)
    raise RuntimeError("container not healthy after 90 s")

def verify():
    js = ("const r=await fetch('https://apiv2.shiprocket.in/v1/external/auth/login',{method:'POST',"
          "headers:{'content-type':'application/json'},body:JSON.stringify({email:process.env.SHIPROCKET_EMAIL,"
          "password:process.env.SHIPROCKET_PASSWORD})});console.log(r.status);process.exit(r.status===200?0:1)")
    r = subprocess.run(["docker", "exec", "orcaslicer-container", "node", "-e", js], capture_output=True, text=True)
    return None if r.returncode == 0 else f"login from inside container returned {r.stdout.strip() or 'error'}"
```

## Serve

```
python3 -I <skill>/scripts/serve.py --reach tailscale \
  --title "Shiprocket API user -> prod" \
  --note "Checked with Shiprocket first; prod changes only if the login works." \
  --fields '[{"name":"password","label":"API password","type":"password"},
             {"name":"email","label":"Email (blank = keep current)","type":"email","optional":true}]' \
  -- python3 <skill>/scripts/remote_py.py root@77.42.38.22 <skill>/scripts/envfile.py /tmp/x/sink.py
```

Expected output on success:

```
[submission from you@example.com via 100.x.y.z]
1/4 New secret validated with the provider
2/4 /srv/app/server/.env updated (backup: /srv/app/server/.env.bak-20261014-101500)
3/4 Service restarted
4/4 Verified: the running service uses the new secret
[sink exit 0]
form closed
```
