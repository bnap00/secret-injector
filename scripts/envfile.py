"""Env-file helpers for secret-injector sinks. Import locally, or prepend via remote_py.py.

set_vars(path, {"KEY": "value"}, style) -> backup path or None  (atomic replace, keeps mode/owner)
get_var(path, "KEY")                    -> current value or None
restore(path, backup)                   -> put the backup back (rollback)
perm_warning(path)                      -> message if the file is readable by other users, else None

Styles (how the file is consumed):
  compose : docker compose env_file   ('...' literal; "..." with \\ \" and $$ if value has ')
  dotenv  : node dotenv               ('...' literal; `...` if value has '; rejects both)
  shell   : sourced by sh/bash        ('...' with ' -> '\\'')
Values must not contain newlines. Never print values.
"""
import os, re, stat, tempfile, time

KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def quote_env(v, style):
    if "\n" in v or "\r" in v or "\0" in v:
        raise ValueError("value contains a newline/NUL")
    if style == "shell":
        return "'" + v.replace("'", "'\\''") + "'"
    if "'" not in v:
        return "'" + v + "'"
    if style == "compose":
        return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$") + '"'
    if style == "dotenv":
        if "`" not in v:
            return "`" + v + "`"
        raise ValueError("dotenv cannot safely hold a value with both ' and `")
    raise ValueError(f"unknown style {style!r}")


def _key(line):
    s = line.lstrip()
    if s.startswith("export "):
        s = s[7:].lstrip()
    return s.split("=", 1)[0].strip() if "=" in s and not s.startswith("#") else None


def get_var(path, key):
    for line in open(path).read().split("\n"):
        if _key(line) == key:
            v = line.split("=", 1)[1].strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"`":
                v = v[1:-1]
            return v
    return None


def perm_warning(path):
    if not os.path.exists(path):
        return None
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        return f"{path} is mode {mode:03o} (readable by other users on this machine); consider chmod 600"
    return None


def _write_private(path, text, like=None):
    """Write text to path atomically with mode 600 (or the mode/owner of `like`)."""
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)))  # mkstemp => 0600
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        if like is not None:
            os.chmod(tmp, stat.S_IMODE(like.st_mode))
            try:
                os.chown(tmp, like.st_uid, like.st_gid)
            except PermissionError:
                pass
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def set_vars(path, mapping, style, backup=True):
    """Replace or append KEY=value lines. Empty values are skipped (keep current)."""
    mapping = {k: v for k, v in mapping.items() if v}
    if not mapping:
        raise ValueError("nothing to set")
    for k in mapping:
        if not KEY_RE.match(k):
            raise ValueError(f"bad env var name {k!r}")
    exists = os.path.exists(path)
    lines = open(path).read().split("\n") if exists else []
    out, seen = [], set()
    for line in lines:
        k = _key(line)
        if k in mapping:
            prefix = "export " if line.lstrip().startswith("export ") else ""
            out.append(f"{prefix}{k}={quote_env(mapping[k], style)}"); seen.add(k)
        else:
            out.append(line)
    if out and out[-1] == "":
        out.pop()
    out += [f"{k}={quote_env(v, style)}" for k, v in mapping.items() if k not in seen]
    bak = None
    if backup and exists:
        bak = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
        _write_private(bak, "\n".join(lines))  # backup is always 0600, whatever the original was
    _write_private(path, "\n".join(out) + "\n", like=os.stat(path) if exists else None)
    return bak


def restore(path, backup):
    """Roll back: copy the backup over path (keeps path's mode/owner). Backup is left in place."""
    _write_private(path, open(backup).read(), like=os.stat(path) if os.path.exists(path) else None)
