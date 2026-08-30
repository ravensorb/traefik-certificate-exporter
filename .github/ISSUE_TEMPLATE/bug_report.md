---
name: Bug report
about: Report something that isn't working as expected
title: "[Bug]: "
labels: bug
---

**Describe the bug**
A clear description of what's wrong.

**Steps to reproduce**
1. Config used (redact secrets like `pkcs12passphrase`) — CLI flags / env vars / `config.yaml`
2. Traefik ACME storage version (v1 or v2) if relevant
3. What you expected vs. what happened

**Logs**
Run with `-ll DEBUG` (or `TRAEFIK_CERTIFICATE_EXPORTER_LOGGINGLEVEL=DEBUG`) and paste the
relevant output. Please double-check no secrets (passphrases, private keys) are included —
debug logs redact known secret-shaped fields, but always double-check before pasting.

**Environment**
- traefik-certificate-exporter version:
- Deployment: Docker / pip install
- Traefik version:
