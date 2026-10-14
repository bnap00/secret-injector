#!/usr/bin/env python3
"""Run local Python file(s) on a remote host over ssh, passing this process's stdin through.

The code travels base64-encoded in the ssh command; secrets must only travel on stdin.
Files are concatenated in order, so library files (e.g. envfile.py) go first.

Usage:  remote_py.py [--ssh-opt=-p2222 ...] HOST lib1.py [lib2.py ...] main.py [-- main args...]
Args after -- are visible in `ps` on both ends: never put secrets there.
"""
import base64, shlex, subprocess, sys

argv = sys.argv[1:]
ssh_opts = [x.split("=", 1)[1] for x in argv if x.startswith("--ssh-opt=")]
argv = [x for x in argv if not x.startswith("--ssh-opt=")]
if "--" in argv:
    i = argv.index("--"); argv, extra = argv[:i], argv[i + 1:]
else:
    extra = []
if len(argv) < 2:
    sys.exit(__doc__)
host, files = argv[0], argv[1:]
code = "\n\n".join(open(f).read() for f in files)
b64 = base64.b64encode(code.encode()).decode()
remote = ("python3 -c " + shlex.quote(
    "import base64,sys;sys.argv=['remote']+sys.argv[1:];exec(compile(base64.b64decode('%s'),'remote','exec'))" % b64)
    + "".join(" " + shlex.quote(x) for x in extra))
sys.exit(subprocess.run(["ssh", "-o", "ConnectTimeout=15", "-o", "BatchMode=yes", *ssh_opts, host, remote]).returncode)
