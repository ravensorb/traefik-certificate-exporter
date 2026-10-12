# Live-host test of 0.3.0 on rwusdckrls6 (docker 6) — 2026-10-12

Maintainer-approved parallel test against the production Traefik's ACME data. The production
exporter (`traefik-certificate-exporter`, 0.2.0), Traefik and `/mnt/certificates` were never
written to. Access: SSH as `svc.claude` (password from Infisical `CLAUDE_AD_*`; Kerberos login
is refused for this account), passwordless sudo for Docker.

## Setup

- Scratch `/mnt/docker-appdata/network/traefik-v3/traefik/_certexport-test-030/` (mode 0700):
  `data/` = `sudo cp -p` of `acme-http.json` and `acme-dns-cloudflare.json` (both `0600 root`),
  `certs/`, `certs-b/`, `hook/`.
- Image `git.ravenwolf.org/ravensorb/traefik-certificate-exporter:0.3.0` (label 0.3.0, amd64).
- Test containers `tce-test-030-*`: `--network none`, Watchtower disabled, `restart` none.
- Pre-check: 0 of 103 running containers carry `com.github.ravensorb.traefik-certificate-exporter.domain-restart`.

## Results

| # | Test | Result |
|---|---|---|
| A | Run-once with production's env (incl. `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME=1`) | exit 0; 67 certificates from 2 resolvers (22 + 52 entries); **all 67 `cert.pem` SHA-256 fingerprints identical to production 0.2.0 output**; same `resolver-*/<domain>/` layout. Production-only folders are domains no longer in the store (never pruned by either version). 7 `*.domain` wildcard entries skipped because the apex certificate owns the folder and the wildcard does not cover the apex — production holds the same apex certificate. Privilege decision logged "running as root because these ACME store files are not readable by abc". No legacy warning for `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME` (filed). |
| B | `pkcs12passphrase` set | exit 0; 67 `.pfx`; pfx opens with the passphrase, rejects a wrong one, holds 3 certificates (leaf + 2 intermediates, same as `fullchain.pem`), key matches `privkey.pem`; passphrase never in the log; no `TypeError` (B2 fixed). |
| C | Second run-once pass | exit 0; no file mtime changed; "No certificate changed; no hook or notification". |
| D | Watch mode, one domain renewed in the copied store | Start-up pass: nothing changed, no hook, labelled container not restarted. In-place write of a new `glkvm.ravenwolf.org` certificate: only that domain extracted, only `acme-http.json` re-processed, hook ran once with `domains=[glkvm.ravenwolf.org]`. An atomic-rename replacement of the file was **not detected** (filed, Medium). |
| E | Restart on change (Docker socket; throwaway `whoami` labelled for `glkvm.ravenwolf.org`) | "Docker Engine reachable (API 1.56)"; container restarted 8 s after the export (B1 fixed). Second renewal 60 s later: "Deferring restart … cooldown active, 240s remaining; one restart scheduled"; deferred restart ran at 16:32:16Z, 5 min after the first; hook ran once per change. |
| F | Privilege | root because the store is unreadable by `abc` (A) and because `restartcontainers` needs the socket (E); both logged with the reason. |

Timing: ~1–1.5 s per certificate per pass (filed, Low).

## Cleanup

Test containers removed, scratch folder (private-key copies) deleted, host temp logs deleted,
pulled image removed, SSH control session closed, local Kerberos ticket destroyed. Production
`traefik`, `traefik-certificate-exporter` and `cert-distributor` still up, unchanged.

## Note for the release

The production exporter runs `ghcr.io/ravensorb/traefik-certificate-exporter:latest` and
Watchtower is active on this host: once a release publishes `latest` to GHCR, production
upgrades itself automatically. GHCR is not configured as a destination today.
