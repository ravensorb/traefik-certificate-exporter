# Release 0.3.1 evidence (E015-S02-004)

Started 2026-10-14 (sitting 1, Part A and the production pre-check). Agent-run rows are
read-only. No tag, push, forge write or production write has been made. No secret value,
prefix or length appears in this file.

## AC 1 — Pre-tag preconditions

- Row 1 (stories): **pass**, 2026-10-14T14:33Z. Nine story lines (E015-S02-005 joined
  sprint 02 on 2026-10-14; the row's count was corrected from 8 to 9). All but E015-S02-004
  are `done`.
- Row 2 (`main` = `origin/main`, `just check`, live `dev.yaml` run on `main`): **not run**.
  `main` is 12 commits ahead of `origin/main` (head `d27613b`). The maintainer chose
  2026-10-14 to hold the push until 0.3.x is ready; row 2 runs after that push.

## AC 2 — Upgrade notes

- Row 3: **pass** after an edit, 2026-10-14. The `## 0.3.0 → 0.3.1` section lacked two AC 2
  topics. Added from the stories' "0.3.1 release notes" bullets:
  - `### Watch mode detects stores replaced by rename` (E015-S01-003);
  - a private-CA publishing bullet for forks under `### Where releases come from`
    (E015-S02-001).
- Maintainer review of the section: **pending**.

## AC 3 — Forge hygiene

- Row 4: `default_workflow_permissions` / `can_approve_pull_request_reviews` = `read false`
  (**pass**). `security_and_analysis`: secret scanning `disabled`, push protection
  `disabled`, non-provider patterns `disabled`, validity checks `disabled`, Dependabot
  security updates `disabled`. The repository is `public`, so secret scanning and push
  protection are available at no cost. **Closed 2026-10-14T16:10Z:** on the maintainer's
  approval, secret scanning and push protection were enabled
  (`gh api -X PATCH repos/ravensorb/traefik-certificate-exporter`); the API now returns
  both `enabled`.
- Row 5: **pass**. Environments `dev` (policy `main branch`) and `release` (policy
  `v* tag`); rulesets `main` and `release-tags` `active`.

## AC 4 — Configuration check

- Row 6: **pass**, 2026-10-14. `release` secrets: `PUBLISH_DOCKERHUB_TOKEN
  PUBLISH_GITEA_TOKEN PUBLISH_PYPI_TOKEN`. `release` variables: `PUBLISH_DOCKERHUB_IMAGE
  PUBLISH_DOCKERHUB_USERNAME PUBLISH_GHCR_IMAGE PUBLISH_GHCR_USERNAME PUBLISH_GITEA_IMAGE
  PUBLISH_GITEA_PYPI_URL PUBLISH_GITEA_REGISTRY PUBLISH_GITEA_USERNAME`. Repository level:
  no variable, no secret.

## AC 5 — Production pre-check and freeze

See `## Production pre-check`. Freeze (row 9) and the first-pass acknowledgement (row 8a):
**pending maintainer approval**.

## AC 6 — The release

Not started.

## AC 7 — Python packages

Not started.

## AC 8 — Images

Not started.

## AC 9 — Forge release

Not started.

## AC 10 — Production upgrade

Not started.

## AC 11 — Rollback

Not needed so far. Rollback reference:
`ghcr.io/ravensorb/traefik-certificate-exporter@sha256:2e2cf7f769e51639d91ded4df1f04df1c45b2d304f46d5edeab26000fbbb536f`.

## AC 12 — Close-out

Not started.

## AC 13 — Released-image integration run

Not started.

## Production pre-check

Read-only, 2026-10-14T14:36Z, over one SSH ControlMaster session as `svc.claude` (password
from Infisical through `SSH_ASKPASS`; session closed afterwards).

| Item | Value |
| --- | --- |
| Container | `traefik-certificate-exporter`, running since 2026-10-09T14:33:06Z |
| Image | `ghcr.io/ravensorb/traefik-certificate-exporter:latest`, label `0.2.0` |
| Running digest | `sha256:2e2cf7f769e51639d91ded4df1f04df1c45b2d304f46d5edeab26000fbbb536f` (matches the rollback reference) |
| Compose (`C`, `CF`) | `/usr/local/docker-apps/network/traefik-v3`, `docker-compose.yml` line 144 `image: ghcr.io/ravensorb/traefik-certificate-exporter:latest`; service `traefik-certificate-exporter` |
| Mounts | `/mnt/certificates/traefik` → `/certs` rw; volume `372835ec…/_data` → `/config` rw; `/mnt/docker-appdata/network/traefik-v3/traefik/letsencrypt` → `/data` ro; `/etc/localtime` ro |
| `/config` (`CFG`) | `/opt/docker-data/volumes/372835eccb9f26df7f3e4a815beaf54f86121dbfd8f51141bef97efc57d8d95a/_data`, `1000:1000 755`; holds only `config.yaml` (`root:root 644`); no `.env` |
| PUID / PGID | `1000` / `1000`; container user empty (s6 starts as root) |
| Environment names | `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEONLY`, `_LOGGING_LEVEL`, `_SETTINGS_DATAPATH`, `_SETTINGS_OUTPUTPATH`, `_SETTINGS_RUNATSTART`, `_SETTINGS_WATCHFORCHANGES`, `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME` (=`1`), plus LinuxServer/s6 names (`PUID`, `PGID`, `TZ`, `UMASK`, `S6_*`, `LLL_EX_*`, …) |
| Hook / Apprise | No `…_POSTEXPORTCOMMAND` or `…_APPRISEURLS_*` variable; `config.yaml` has 0 `postexportcommand:` and 0 `appriseurls` lines. The first pass fires no hook and no notification |
| `config.yaml` root-mode keys | `datapath: "/data"`, `outputpath: "/certs"`, `filespec: "*.json"`. The environment sets `DATAPATH=/data` and `OUTPUTPATH=/certs`, which win over the file, so the S01-001 rule withholds nothing (it acts only when a file is the winning source; `settings.py` `_withholdFileSourcedRootSettings`) and no `Ignoring settings.` ERROR is expected. `*.json` is a valid `filespec` |
| Restart-labelled containers | 0 |
| `cert-distributor` | `ravensorb/cert-distributor:latest`, entrypoint `/usr/local/bin/reconcile`; mounts `/mnt/certificates/traefik/resolver-dns-cloudflare` → `/certs` **read-only**. It may react to the first pass's rewritten `.pfx` files under `resolver-dns-cloudflare` |
| Certificates | Live output (`/mnt/certificates/traefik/resolver-*`): 87 domain directories, 261 PEM files, 87 `.pfx`, 0 fingerprint files, 0 empty `chain.pem`. Also under `/mnt/certificates`: `traefik/.archive` (426 PEM) and `.recycle/RAVENWOLF` (228 PEM), not exporter output |
| Last export pass (0.2.0 baseline) | Start-up pass 2026-10-09 14:33:10 → 14:33:57, **47 s**, 74 `Extracted certificate for:` lines (60 distinct names across the two resolvers). No export since (no renewal in five days). 0 `ERROR`, 0 `Traceback` in the full log (105 lines) |
| Watchtower | `watchtower`, image `nickfedor/watchtower:latest` (**1.23.1, the maintained fork**, Docker API v1.56), running and healthy; `WATCHTOWER_LABEL_ENABLE=true`, `WATCHTOWER_POLL_INTERVAL=43200` (12 h), `CLEANUP=true`, `MONITOR_ONLY=false`, HTTP API update enabled; next scheduled run 2026-10-14 18:14:53 EDT. The exporter carries `com.centurylinklabs.watchtower.enable=true`. **Watchtower works and will upgrade the exporter on its first poll after GHCR `latest` moves.** P3 (archived upstream) does not apply: no backlog item needed |
| Docker | Server 29.9.0, API 1.56, minimum API 1.24 |
| Neighbours | `traefik` (`gcr.ravenwolf.org/l3io/traefik:latest`) Up 4 h healthy; `cert-distributor` Up 2 weeks; `traefik-whoami-auth` Up 5 days |

Baseline files (kept on the workstation under `/tmp/e015-s02-004`, not committed):
`pems-before.txt` (all 915 PEM SHA-256s), `pems-before-live.txt` (the 261 live ones),
`pfx-before`, `log-before.txt`, `precheck.out`.

**Row-scope note for sitting 3.** Rows 8, 18a, 19 and 19a search `/mnt/certificates`, which
also holds `.archive` and `.recycle` copies. Rows 18a and 19 still pass with it (the archives
are static and are not "owned" domains), but row 19a's `find -newermt` would fail on any
write by another process under `.recycle`. Scope those finds to
`/mnt/certificates/traefik/resolver-*` when they are run. Re-take `pems-before` on the day of
the upgrade: a renewal between now and then shows up as an expected difference.

## Production post-check

Not started.

## Maintainer approvals

| Time (UTC) | Approval | By |
| --- | --- | --- |
| 2026-10-14T14:34Z | Start S02-004 release prep (read-only Part A and production pre-check); hold the push to `main` until 0.3.x is ready | maintainer (session) |
| 2026-10-14T16:09Z | Enable secret scanning and push protection on the GitHub repository | maintainer (session) |
| 2026-10-14T16:09Z | Do not pin production yet; run dev builds first (dev builds publish no image, so GHCR `latest` does not move) | maintainer (session) |
