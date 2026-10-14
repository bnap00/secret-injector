#!/usr/bin/env python3
"""secret-injector: one-shot web form that hands secrets to a "sink" command via stdin.

The form is served at an unguessable URL on exactly one of three reaches:
  local      http://127.0.0.1:PORT/...   only a browser on this machine
  lan        http://192.168.x.y:PORT/... a device on the same private network (home/office Wi-Fi)
  tailscale  http://100.x.y.z:PORT/...   a device on your tailnet, signed in as the SAME
                                         Tailscale account as this machine (checked per request)

On submit, the field values are sent as one JSON line on the sink's stdin. They are never
printed, logged, or put in argv. Sink output is shown on the page and printed here with every
submitted value redacted. The form closes after one success, N failures, or a timeout.

Usage:
  serve.py --reach tailscale --title "Shiprocket API user -> prod" \
           --fields '[{"name":"password","label":"API password","type":"password"},
                      {"name":"email","label":"Email (blank = keep)","type":"email","optional":true}]' \
           -- python3 /path/to/sink.py
"""
import argparse, html, http.server, ipaddress, json, re, secrets, socket, subprocess, sys, threading, urllib.parse

INPUT_TYPES = {"password", "text", "email", "url"}
NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
TS_NET = ipaddress.ip_network("100.64.0.0/10")

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--reach", choices=["local", "lan", "tailscale"], default="tailscale",
               help="who must be able to open the link (default: tailscale)")
p.add_argument("--title", default="Secret injector")
p.add_argument("--note", default="", help="plain-text hint shown under the form")
p.add_argument("--fields", required=True, help="JSON list of {name,label,type,optional}")
p.add_argument("--port", type=int, default=0, help="default: random free port")
p.add_argument("--timeout", type=int, default=30 * 60, help="seconds before the form closes unused")
p.add_argument("--sink-timeout", type=int, default=15 * 60)
p.add_argument("--max-attempts", type=int, default=5, help="failed submissions before closing")
p.add_argument("--allow-user", action="append", default=[],
               help="tailscale: extra login name allowed to submit (default: this node's own account)")
p.add_argument("sink", nargs=argparse.REMAINDER, help="-- command [args]; receives JSON on stdin")
a = p.parse_args()

sink = a.sink[1:] if a.sink[:1] == ["--"] else a.sink
if not sink:
    sys.exit("error: give the sink command after --")
try:
    fields = json.loads(a.fields)
    assert isinstance(fields, list) and fields
except Exception:
    sys.exit("error: --fields must be a non-empty JSON list")
for f in fields:
    if not isinstance(f, dict) or not NAME_RE.match(str(f.get("name", ""))):
        sys.exit(f"error: bad field name in {f!r}")
    if f.get("type", "password") not in INPUT_TYPES:
        sys.exit(f"error: field type must be one of {sorted(INPUT_TYPES)}")
if len({f["name"] for f in fields}) != len(fields):
    sys.exit("error: duplicate field names")


def tailscale(*args):
    """Run a tailscale CLI command; None if the CLI is missing or the command fails."""
    try:
        r = subprocess.run(["tailscale", *args], capture_output=True, text=True, timeout=10)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def lan_ip():
    """IP of the interface with the default route (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("192.0.2.1", 9))
            return s.getsockname()[0]
        except OSError:
            return None


def self_login():
    out = tailscale("status", "--json")
    if not out:
        return None
    j = json.loads(out)
    me = j.get("Self") or {}
    if me.get("Tags"):
        return None  # tagged node: no owning user
    u = (j.get("User") or {}).get(str(me.get("UserID")), {})
    return u.get("LoginName")


# --- pick the bind address and the admission rule for this reach -------------------------------
ALLOWED_LOGINS = set()
if a.reach == "local":
    bind = "127.0.0.1"
elif a.reach == "lan":
    bind = lan_ip()
    if not bind or not ipaddress.ip_address(bind).is_private or ipaddress.ip_address(bind) in TS_NET:
        sys.exit(f"error: LAN address {bind!r} is not a private network address; refusing to serve on it")
else:
    bind = (tailscale("ip", "-4") or "").split("\n")[0].strip()
    if not bind or ipaddress.ip_address(bind) not in TS_NET:
        sys.exit("error: no Tailscale IPv4 address (is tailscale up?). Use --reach local or lan instead.")
    ALLOWED_LOGINS = set(a.allow_user) or ({self_login()} - {None})
    if not ALLOWED_LOGINS:
        sys.exit("error: this node is tagged / has no owning user; pass --allow-user you@example.com")

port = a.port
if not port:
    with socket.socket() as s:
        s.bind((bind, 0)); port = s.getsockname()[1]
funnel = tailscale("funnel", "status") or ""
if re.search(rf"[:\s]{port}\b", funnel):
    sys.exit(f"error: port {port} appears in `tailscale funnel status` (public internet); pick another")

TOKEN = secrets.token_urlsafe(24)
HOST = f"{bind}:{port}"
ORIGIN = f"http://{HOST}"
PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<meta name=referrer content=no-referrer><title>{title}</title>
<style>body{{font:16px system-ui;max-width:440px;margin:60px auto;padding:0 16px}}
label{{display:block;margin:14px 0 4px}}input{{width:100%;padding:10px;font:inherit;box-sizing:border-box}}
button{{margin-top:18px;padding:10px 18px;font:inherit}}pre{{white-space:pre-wrap;background:#f4f4f4;padding:12px}}</style>
<h2>{title}</h2>{body}"""


def form():
    inputs = "".join(
        '<label>{l}{o}</label><input name="{n}" type="{t}" autocomplete="{ac}"{r}>'.format(
            l=html.escape(f.get("label", f["name"])), n=f["name"], t=f.get("type", "password"),
            o=" <small>(optional)</small>" if f.get("optional") else "",
            ac="new-password" if f.get("type", "password") == "password" else "off",
            r="" if f.get("optional") else " required")
        for f in fields)
    note = f"<p><small>{html.escape(a.note)}</small></p>" if a.note else ""
    return f'<form method=post autocomplete=off>{inputs}<button>Submit</button></form>{note}'


def redact(text, values):
    """Blank out every submitted value, in the forms it is most likely to be echoed in."""
    forms = set()
    for v in values:
        if len(v) >= 4:
            forms.update({v, json.dumps(v)[1:-1], urllib.parse.quote(v, safe=""), html.escape(v)})
    for v in sorted(forms, key=len, reverse=True):
        text = text.replace(v, "[REDACTED]")
    return text


_whois = {}
_whois_lock = threading.Lock()


def peer_login(ip):
    """Tailscale login name owning the peer at ip (user-owned nodes only); None if unknown."""
    with _whois_lock:
        if ip in _whois:
            return _whois[ip]
    out = tailscale("whois", "--json", ip)
    login = None
    if out:
        j = json.loads(out)
        if not (j.get("Node") or {}).get("Tags"):
            login = (j.get("UserProfile") or {}).get("LoginName")
    if login:
        with _whois_lock:
            _whois[ip] = login
    return login


def admit(ip):
    """Return a short identity string if this client may use the form, else None."""
    addr = ipaddress.ip_address(ip)
    if a.reach == "local":
        return "localhost" if addr.is_loopback else None
    if a.reach == "lan":
        return ip if addr.is_private and addr not in TS_NET else None
    login = peer_login(ip)
    return f"{login} via {ip}" if login in ALLOWED_LOGINS else None


done = threading.Event()
lock = threading.Lock()
failures = 0


class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # never log requests
        pass

    def _send(self, code, body):
        b = PAGE.format(title=html.escape(a.title), body=body).encode()
        self.send_response(code)
        for k, v in (("Content-Type", "text/html; charset=utf-8"), ("Cache-Control", "no-store"),
                     ("Referrer-Policy", "no-referrer"), ("X-Frame-Options", "DENY"),
                     ("Content-Length", str(len(b)))):
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def _gate(self):
        """Common checks for GET and POST. Returns identity or None (response already sent)."""
        if self.headers.get("Host") != HOST:
            self._send(400, "<p>Bad request</p>"); return None
        if self.path != "/" + TOKEN:
            self._send(404, "<p>Not found</p>"); return None
        who = admit(self.client_address[0])
        if not who:
            hint = {"local": "Open this link on the computer it was created on.",
                    "lan": "Open this link from a device on the same local network.",
                    "tailscale": "Open this link from a device signed in to Tailscale as "
                                 + html.escape(", ".join(sorted(ALLOWED_LOGINS))) + "."}[a.reach]
            self._send(403, f"<p>Not allowed. {hint}</p>"); return None
        if done.is_set():
            self._send(410, "<p>This form is closed.</p>"); return None
        return who

    def do_GET(self):
        if self._gate():
            self._send(200, form())

    def do_POST(self):
        global failures
        who = self._gate()
        if not who:
            return
        origin = self.headers.get("Origin")
        if (origin and origin != ORIGIN) or self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            return self._send(403, "<p>Cross-site request refused.</p>")
        try:
            n = int(self.headers.get("Content-Length", "0"))
            if not 0 <= n <= 64 * 1024:
                raise ValueError
            q = urllib.parse.parse_qs(self.rfile.read(n).decode("utf-8"), keep_blank_values=True)
        except (ValueError, UnicodeDecodeError):
            return self._send(400, "<p>Bad request</p>")
        if not lock.acquire(blocking=False):
            return self._send(409, "<p>A submission is already running.</p>")
        try:
            data = {f["name"]: q.get(f["name"], [""])[0] for f in fields}
            values = [v for v in data.values() if v]
            try:
                r = subprocess.run(sink, input=json.dumps(data) + "\n", capture_output=True, text=True,
                                   timeout=a.sink_timeout)
                out, rc = r.stdout.strip(), r.returncode
                if rc != 0 and r.stderr.strip():
                    out += "\n--- stderr (tail) ---\n" + "\n".join(r.stderr.strip().splitlines()[-15:])
            except subprocess.TimeoutExpired:
                out, rc = "sink timed out", 124
            out = redact(out or "(no output)", values)
            print(f"[submission from {who}]\n{out}\n[sink exit {rc}]", flush=True)
            if rc == 0:
                done.set()
                return self._send(200, f"<pre>{html.escape(out)}</pre><p><b>Done.</b> This form is now closed.</p>")
            failures += 1
            if failures >= a.max_attempts:
                done.set()
                return self._send(200, f"<pre>{html.escape(out)}</pre><p>Too many failed attempts; form closed.</p>")
            self._send(200, f"<pre>{html.escape(out)}</pre>" + form())
        finally:
            lock.release()


srv = http.server.ThreadingHTTPServer((bind, port), H)
threading.Thread(target=srv.serve_forever, daemon=True).start()
print(f"URL: {ORIGIN}/{TOKEN}", flush=True)
print(f"reach: {a.reach}" + (f" (accepting {', '.join(sorted(ALLOWED_LOGINS))})" if ALLOWED_LOGINS else "")
      + f"; closes in {max(1, round(a.timeout / 60))} min if unused", flush=True)
try:
    done.wait(a.timeout)
except KeyboardInterrupt:
    pass
srv.shutdown()
print("form closed" + ("" if done.is_set() else " (timed out or interrupted, nothing accepted)"), flush=True)
