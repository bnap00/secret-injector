# Security policy

This tool handles secrets, so security reports are very welcome.

## Reporting a vulnerability

Please **do not open a public issue**. Report privately through GitHub's
[private vulnerability reporting](https://github.com/bnap00/secret-injector/security/advisories/new)
(Security tab → "Report a vulnerability").

Include what you found, how to reproduce it, and the impact you expect. You should get a reply
within a few days. Fixes are released on `main`; there are no maintained older versions.

## Scope

In scope: anything that lets a submitted value leak (to the agent, logs, argv, environment, other
processes or the network), bypasses the per-request admission checks, or lets an unintended
client submit. Known non-goals are listed under "Not covered" in the [README](README.md).
