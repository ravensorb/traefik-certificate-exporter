# Release 0.3.1 evidence (E015-S02-004)

Started 2026-10-14 (sitting 1, Part A and the production pre-check). Agent-run rows are
read-only. No tag, push, forge write or production write has been made. No secret value,
prefix or length appears in this file.

## AC 1 — Pre-tag preconditions

- Row 1 (stories): **pass**, 2026-10-14T14:33Z. Nine story lines (E015-S02-005 joined
  sprint 02 on 2026-10-14; the row's count was corrected from 8 to 9). All but E015-S02-004
  are `done`.
- Row 2: **pass**, 2026-10-14T16:27Z. The maintainer approved a direct push of `main`
  (16:16Z; the `main` ruleset's pull-request and status-check rules were bypassed as
  admin). `main` = `origin/main` = `2c1a1b7`. `just check` green on that tree (629 passed,
  16 skipped; pre-commit re-run over the commit's files). `dev.yaml` run
  [38596838383](https://github.com/ravensorb/traefik-certificate-exporter/actions/runs/38596838383)
  at `2c1a1b7`: `success` (build, publish-package, publish-image). One `enabled` line,
  `TestPyPI enabled`; 0 emitted `partially configured` warnings; 0 `Unexpected input`.
  Published `0.3.1.dev13` to TestPyPI only (wheel
  `50069439b964b71446edbbdc3462f974af4d110012ee64dc2fdf72040d26ac30`, sdist
  `14b5f37b634fdab8a8f3bc2d67ef11d497fda01d8fbaa377e9937908f49cdfa7`); no image pushed.
  The row's original `grep` matched the destination step's echoed script text; corrected
  to count only `##[warning]` lines.
- **GHCR job-token push proven before the tag** (maintainer-approved 16:44Z). Set
  `PUBLISH_GHCR_IMAGE=ghcr.io/ravensorb/traefik-certificate-exporter` and
  `PUBLISH_GHCR_USERNAME=ravensorb` in the GitHub `dev` environment, then re-ran only
  `publish-image` of run 38596838383 (attempt 2): `success`, `GHCR enabled`, 0 emitted
  warnings, 0 `Unexpected input`, no 403. GHCR now has `0.3.1-dev.13`, `dev` and
  `sha-2c1a1b7` on one index digest
  `sha256:83eb5961e3edec7440cbe790c6d8c7e6b7976d8d5b917e697d1591380c56c34a`
  (`linux/amd64` + `linux/arm64`, label `0.3.1-dev.13`). `latest` is unchanged at the 0.2.0
  digest `sha256:2e2cf7f7…536f` (dev tags set `latest=false`), so production and Watchtower
  are unaffected. The release's GHCR 403 contingency (Manage Actions access) is not
  expected to be needed.
- Run annotations (not gating): Node.js 20 deprecation for the pinned
  `actions/upload-artifact` / `actions/download-artifact` pair (kept for act
  compatibility), and `ubuntu-latest` moving to Ubuntu 26 from 2026-10-19.

## AC 2 — Upgrade notes

- Row 3: **pass** after an edit, 2026-10-14. The `## 0.3.0 → 0.3.1` section lacked two AC 2
  topics. Added from the stories' "0.3.1 release notes" bullets:
  - `### Watch mode detects stores replaced by rename` (E015-S01-003);
  - a private-CA publishing bullet for forks under `### Where releases come from`
    (E015-S02-001).
- Maintainer review of the section: **approved** 2026-10-14T21:29Z, including the later
  additions (CIFS summary WARNING, BL-E015-068; `cert.pem`/`chain.pem` rewritten once,
  BL-E015-069).

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

See `## Production pre-check`.

- Row 8a: **acknowledged** 2026-10-14T21:29Z. The maintainer wants production on 0.3.1 and
  accepts the one-time first pass (every `.pfx` rebuilt with the intermediates, `cert.pem`
  and `chain.pem` rewritten once, every domain reported once; 0 restart-labelled containers
  at the pre-check).
- Row 9 (freeze): **declined by the maintainer** 2026-10-14T21:29Z. The compose service
  stays on `ghcr.io/ravensorb/traefik-certificate-exporter:latest`, so Watchtower (12 h
  poll, enable label set) may upgrade it on its own once the release moves `latest`. To
  keep the post-check timed, the agent runs the deliberate upgrade (row 17, with approval)
  as soon as the release is verified; if Watchtower gets there first, the upgrade time is
  taken from the container's `State.StartedAt` and its log. The PEM baseline is re-taken
  with `pemsums` (blank lines ignored) before the tag.

## AC 6 — The release

Pre-tag, at `1a91666` (after the code review of the BL-E015-068 fix,
`closure/review-E015-S02-004.md`):

- Row 2 re-run: `main` = `origin/main` = `1a91666`; `just check` 632 passed, 16 skipped;
  dev run [38641788670](https://github.com/ravensorb/traefik-certificate-exporter/actions/runs/38641788670)
  `success` at HEAD; 0 emitted partial-configuration or `Unexpected input` warnings.
- Row 8 PEM baseline re-taken with `pemsums` at 2026-10-14T21:38:30Z: 261 hashes (87
  domain directories × `cert`/`chain`/`fullchain.pem`), 87 `.pfx`; production still
  0.2.0 (`sha256:feedded1…`, started 2026-10-09T14:33:06Z).

Row 10: **pass**. `just release patch` (maintainer-approved 21:56Z, run by the agent from
21:56:12Z): clean tree, on `main`, HEAD = `origin/main`, `just check` 632 passed, 16
skipped; base `v0.3.0`, bump `patch`, tag `v0.3.1` at
`1a916660500ca4ffc18a18dfe63e352b2761987d`, pushed.

Row 11: **pass**. release run
[38644809861](https://github.com/ravensorb/traefik-certificate-exporter/actions/runs/38644809861),
22:02:36Z → 22:10:15Z, `success` at `1a91666` (validate-tag, build, publish-image,
publish-package, release). Six `enabled` lines: PyPI, Gitea package index, GHCR, Docker
Hub, Gitea container registry, Forge release. 0 emitted partial-configuration or
`Unexpected input` warnings. Other `##[warning]` lines: four Node.js 20 deprecation
notices, and validate-tag's `Tag 'v0.3.1' not found in repository; parsing tag string
only` (the step runs without a checkout; the 0.3.0 run logged the same line).
Copied from the log: `WHL_SHA=918d8762f3821dc203799e4d80c60e376bf581a402d7ca5e4f0d5fbb09c0c210`,
`SDIST_SHA=8d671a806322f13fb1efb5a97eb4d28d284419305368951429a312cd68f88d6f`,
`RUN_DIGEST=sha256:29e23a8d18a3b0b746b31548d71189336db3cbcaa045a144a918e7143d99cf91`.

## AC 7 — Python packages

- Row 12: **pass**. `traefik-certificate-exporter==0.3.1` from PyPI installs and runs
  `--help` on Python 3.10.20 and 3.14.4. The workstation has no `python3.10` and no
  `python3.14-venv`, so the venvs were made with `uv venv -p 3.10|3.14` and
  `uv pip install --index-url https://pypi.org/simple` (same check, uv-managed interpreters).
- Row 13: **pass**. PyPI holds exactly the run's wheel and sdist by sha256; the Gitea
  index wheel (`https://git.ravenwolf.org/api/packages/ravensorb/pypi/simple`) has the
  run's wheel sha256.

## AC 8 — Images

- Row 14: **pass**. Three configured images (GHCR, Docker Hub, Gitea); nine anonymous
  lookups (`0.3.1`, `0.3`, `latest` on each), none `MISSING`, one digest, equal to
  `RUN_DIGEST`. (`logout_all` logged the workstation out of ghcr.io, Docker Hub and
  git.ravenwolf.org for the anonymous lookups.)
- Row 15: **pass**. Each `0.3.1` index lists `linux/amd64` and `linux/arm64`; each
  anonymous pull is labelled `0.3.1`; GHCR `:0` is still the 0.2.0 digest
  `sha256:2e2cf7f7…536f`.

## AC 9 — Forge release

Row 16: **pass**. GitHub release `v0.3.1` has a non-empty body and exactly the wheel and
the sdist, with the run's (and PyPI's) sha256.

## AC 10 — Production upgrade

Maintainer-approved 21:55Z: the agent upgrades production right after the release is
verified, keeping the compose service on `:latest` (no edit to `image:`; line 144 stays
`ghcr.io/ravensorb/traefik-certificate-exporter:latest`).

- Pre-upgrade capture: `/config` = `/opt/docker-data/volumes/372835ec…/_data`,
  `1000:1000 755`; compose project `traefik-v3`, service `traefik-certificate-exporter`,
  file `/usr/local/docker-apps/network/traefik-v3/docker-compose.yml`; 0 containers with
  the restart label; `traefik`, `watchtower`, `cert-distributor` up. Watchtower had not
  pulled the new `latest`.
- Row 17: **pass**. Host time 2026-10-14T22:12:09Z; `docker compose pull
  traefik-certificate-exporter && docker compose up -d --no-deps
  traefik-certificate-exporter` in the project directory: only the exporter was
  recreated; it runs `…@sha256:29e23a8d…` (`RUN_DIGEST`).
- Details under `## Production post-check`.

## AC 11 — Rollback

Not needed: every post-check passed. Rollback reference kept:
`ghcr.io/ravensorb/traefik-certificate-exporter@sha256:2e2cf7f769e51639d91ded4df1f04df1c45b2d304f46d5edeab26000fbbb536f`.

## AC 12 — Close-out

- P1 (image reference): production stays on `:latest` by maintainer decision; the
  recommended `:0.3` was not adopted. P2 (freeze): declined by the maintainer, upgrade done
  deliberately before Watchtower's 12 h poll. P3 (Watchtower): nickfedor/watchtower 1.23.1,
  up and healthy, enable label honoured; no backlog item needed.
- ADR-0035's Status line untouched (the Gitea `act_runner` path was not exercised).
- Row 20: **pass**. Neither spine contains an unreplaced "to be written by E015"
  placeholder. As written, the row's grep also matched two spine changelog lines that
  quote the placeholder they replaced (`ADR-0049 replaces "ADR to be written by
  E015-S01-001"`, ADR-0051 likewise); the row now skips those quotes.
- Defects found during the release were filed, not fixed in place, except BL-E015-068 and
  BL-E015-069, which the maintainer asked to fix before the tag: BL-E015-068 to 070 (070
  open, operational), BL-E015-071 (Low findings of the sprint review).
- Two story rows were wrong on production and are corrected in the story (see
  `## Production post-check`): row 18a compared bare domain names across resolvers, and
  row 19's exclusion filter emptied both lists when no single-certificate chain exists.
- Row 21: `just check` at the released commit ran inside `just release` (632 passed, 16
  skipped).

## AC 13 — Released-image integration run

Row 15a: **pass**. From the release commit (`HEAD` = `v0.3.1^{commit}` = `1a91666`),
`TCE_DOCKER_INTEGRATION=1 TCE_IMAGE=ghcr.io/ravensorb/traefik-certificate-exporter@sha256:29e23a8d18a3b0b746b31548d71189336db3cbcaa045a144a918e7143d99cf91 poetry run pytest -q -m integration -rs tests/test_container_*.py`:

```text
...............                                                          [100%]
15 passed in 244.02s (0:04:04)
```

0 `SKIPPED`; no test container left running.

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

## Dev-image rehearsal on rwusdckrls6

Maintainer-approved 2026-10-14T19:08Z. Image
`ghcr.io/ravensorb/traefik-certificate-exporter@sha256:83eb5961e3edec7440cbe790c6d8c7e6b7976d8d5b917e697d1591380c56c34a`
(`0.3.1-dev.13`, commit `2c1a1b7`). Scratch
`/mnt/docker-appdata/network/traefik-v3/traefik/_certexport-test-031` (`0700 root`, local
disk): copies of both ACME stores (`0600 root`, mounted read-only), of the 0.2.0 output
(`/mnt/certificates/traefik/resolver-*`, 435 files, 87 `.pfx`) and of production's
`config.yaml`. Containers `tce-test-031-first` / `-second`: `--network none`,
`--restart no`, Watchtower opt-out, production's environment except
`WATCHFORCHANGES=false` (run once).

| Check | First pass (the 0.2.0 → 0.3.1 upgrade) | Second pass (steady state) |
| --- | --- | --- |
| Exit code / container time | 0 / 82.9 s | 0 / 6.4 s |
| ERROR, Traceback, `Ignoring settings.` | 0, 0, 0 | 0, 0, 0 |
| Privilege line | `WARNING: running as root because abc cannot list settings.datapath` (the scratch `data` dir is `0700`; production's is `0755` with `0600` stores, so its reason will name the unreadable store files) | same |
| Legacy warning | `Legacy setting TRAEFIK_RESOLVERID_INOUTPUTPATHNAME in environment is ignored; use …RESOLVERINPATHNAME` | same |
| `Post-export command:` | `not set (source: default), runs as uid 0` | same |
| Exported | 67 `Extracted certificate for:` of 74 store entries; 7 `Not exporting '*.aussierescue.<tld>'` (wildcard and apex map to one folder; documented in 0.2.0 → 0.3.0) | `No certificate changed; no hook or notification` |
| Files written | 268 (67 domains × `.pfx`, fingerprint file, `cert.pem`, `chain.pem`); 67 fingerprint files `0600 root` | 0 |
| Untouched | 20 domain folders not in the store (stale, `0755 30102:30103`) | — |
| PEM vs production | 134 files differ (67 `cert.pem`, 67 `chain.pem`), all content-identical ignoring blank lines: 0.2.0 ended them with `\n\n`, 0.3.x with `\n`; every `fullchain.pem` identical (BL-E015-069) | — |
| `/config` | `1000:1000 755` before and after | same |

**Production storage is a CIFS share.** `/mnt/certificates` is `//10.0.1.8/Certificates`,
`cifs vers=3.0, nounix, forceuid uid=30102, forcegid gid=30103, file_mode=0755,
dir_mode=0755`. Every exported file, private keys included, is `0755 30102:30103` there.
Probe (one empty file in `/mnt/certificates/_certexport-probe-031`, removed with its
recycle-bin copy): `fchmod 0600` and `chown 0:0` return success and change nothing; an
atomic replace works. So on production 0.3.1 will not loop on rewrites, but every pass logs
one false `Tightened mode … to 0600` WARNING per file (335 on the first pass here, ~400 per
pass on the share, sidecars included) and `refusing to inherit ownership (uid 30102)` on each
rewrite (**BL-E015-068, Medium**). The local-disk rehearsal could not show this; it was
derived from the probe and `_breaks_write_policy`.

Cleanup: both containers, the scratch directory and the pulled image removed; the probe and
its `.recycle` copy removed. Production exporter unchanged (`sha256:feedded1…`, running since
2026-10-09T14:33:06Z); `traefik`, `watchtower`, `cert-distributor` up.

### Fixes from the rehearsal (before the tag)

- **BL-E015-068, fixed.** `_breaks_write_policy` re-reads the mode after `fchmod`. When the
  filesystem kept the old mode, it logs no `Tightened mode` line and the path is collected;
  `exportCertificatesForFile` logs one WARNING per store file per pass (`N exported file(s)
  from '<store>' keep a mode wider than the export policy …`, with the `file_mode=0600`
  advice). Nothing is rewritten because of it. Tests:
  `test_a_filesystem_that_ignores_chmod_gets_one_summary_per_pass` (fails on the old code)
  and `test_a_filesystem_that_keeps_modes_is_tightened_without_a_summary`. Documented in
  `docs/upgrading.md` (0.3.1, "Output on a filesystem that ignores chmod") and
  `docs/operational.md`. The `refusing to inherit ownership (uid 30102)` line on a rewrite
  is unchanged: it is correct (the share forces that owner) and only logged on a rewrite.
- **BL-E015-069, fixed (docs).** `docs/upgrading.md` 0.2.0 → 0.3.0 now says `cert.pem` and
  `chain.pem` are rewritten once per domain with the same certificates (blank line dropped)
  and `fullchain.pem` is unchanged; the GHCR one-time-effect bullet says the same. S02-004's
  Context, the AC 10 PEM bullet and rows 8/19 compare certificates with blank lines removed
  (`pemsums`), and the production `find`s are scoped to `/mnt/certificates/traefik/resolver-*`
  so `.archive` and `.recycle` copies are not counted.
- `just check`: exit 0, 631 passed, 16 skipped.
- Pushed as `981c1d3`. dev run
  [38629832499](https://github.com/ravensorb/traefik-certificate-exporter/actions/runs/38629832499):
  `success`; 0 `partially configured` warnings, 0 `Unexpected input` (the only `##[warning]`
  lines are GitHub's Node.js 20 deprecation notices for `actions/upload-artifact` and
  `actions/download-artifact`). TestPyPI has `0.3.1.dev14` (wheel and sdist). GHCR
  `0.3.1-dev.14`, `dev` and `sha-981c1d3` all resolve to
  `sha256:8876edf384f34b55ca16450bc5155ccd7ab13dd26b4ef7afb08029f8a3b7dbed`; `latest` is
  still 0.2.0 (`sha256:2e2cf7f7…536f`).

## Production post-check

rwusdckrls6, 2026-10-14, after the 22:12:09Z upgrade (read-only except the approved
restart in row 19a).

| Check | Result |
| --- | --- |
| Row 18 | **pass**. Running digest `RUN_DIGEST`, label `0.3.1`; privilege line `running as root because these ACME store files are not readable by abc: '/data/acme-dns-cloudflare.json' '/data/acme-http.json' …`; the S01-004 legacy warning for `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME`; `Post-export command: not set (source: default), runs as uid 0`; no `Ignoring settings.`, `Traceback`, `ERROR` or `Tightened mode`; `/config` still `1000:1000 755`; `traefik` and `cert-distributor` `Up` |
| First pass | 22:12:20 → 22:13:42, **82 s** (0.2.0 baseline 47 s; this pass rebuilt every `.pfx` with RSA key validation). 60 domains reported (`Extracted certificate for:`). 0 restarts (0 labelled containers); hook not set, and no hook or notification line in the log. `cert-distributor` logged nothing since the upgrade |
| CIFS summary (BL-E015-068) | One WARNING per store file: `110 exported file(s) from '/data/acme-http.json' …` and `225 … '/data/acme-dns-cloudflare.json' …`; 0 `Tightened mode` lines (0.3.0 would have logged one per file) |
| Other first-pass WARNINGs | 201 `refusing to inherit ownership (uid 30102)` (one per rewritten file on the share, documented as expected); 7 `Not exporting '*.aussierescue.*' … does not cover 'aussierescue.*'` (wildcard and apex share an output directory; the apex keeps it; the dev rehearsal logged the same 7) |
| Row 18a | **pass** with resolver-qualified paths. The 60 reported domains equal the 60 domains with a fingerprint file (`diff` empty). As written, the row's final `comm` failed on `invisionware.com` and `triptracks.net`: each was rebuilt under `resolver-dns-cloudflare` and also has a stale directory under `resolver-http`, and the row compared bare names. Compared as `resolver/domain` directories, no fingerprinted directory has a `.pfx` older than the upgrade. 20 stale `.pfx` (19 `resolver-http`, 1 `resolver-dns-cloudflare`) belong to domains no longer in the store and are untouched (AD-8: no pruning). Row corrected in the story |
| Row 19 | **pass**. `pemsums` after the pass: 261 hashes, identical to the 21:38Z baseline (blank lines ignored); 0 single-certificate chains. Files rewritten since the upgrade: 67 `cert.pem` and 67 `chain.pem` (the 0.2.x trailing blank line, BL-E015-069); no `fullchain.pem` or `privkey.pem`. As written, the row's `keep` filter (`NR==FNR` with an empty exclusion file) emptied both lists and passed vacuously; the direct comparison above is the gate, and the filter is corrected in the story |
| Row 19a | **pass**. Approved restart of the exporter only at 22:14:32Z. Second pass 22:14:37 → 22:14:39, **2 s** steady state (0.2.0 baseline 47 s); `No certificate changed; no hook or notification`; 0 files written; 0 `Tightened mode`; 2 CIFS summaries (132 and 270 files, `STORES=2`); 0 `ERROR` |
| Neighbours | `traefik` (healthy), `watchtower` (healthy), `cert-distributor` up and not recreated |

## Maintainer approvals

| Time (UTC) | Approval | By |
| --- | --- | --- |
| 2026-10-14T14:34Z | Start S02-004 release prep (read-only Part A and production pre-check); hold the push to `main` until 0.3.x is ready | maintainer (session) |
| 2026-10-14T16:09Z | Enable secret scanning and push protection on the GitHub repository | maintainer (session) |
| 2026-10-14T16:09Z | Do not pin production yet; run dev builds first (dev builds publish no image, so GHCR `latest` does not move; the "no image" part is superseded at 16:44Z/18:00Z: dev builds now publish `dev`/`sha-*`/dev-version tags to GHCR, never `latest`) | maintainer (session) |
| 2026-10-14T16:16Z | Commit and push `main` directly (ruleset bypass as admin) to start the dev build | maintainer (session) |
| 2026-10-14T16:44Z | Set `PUBLISH_GHCR_IMAGE` / `PUBLISH_GHCR_USERNAME` in the GitHub `dev` environment and re-run `publish-image` to prove the GHCR job-token push | maintainer (session) |
| 2026-10-14T18:00Z | Keep the GHCR `dev` variables: every push to `main` publishes `dev`, `sha-<short>` and the dev version to GHCR (never `latest`) | maintainer (session) |
| 2026-10-14T20:09Z | Fix BL-E015-068 and BL-E015-069, push `main`, run a new dev build | maintainer (session) |
| 2026-10-14T21:29Z | 0.3.1 upgrade notes reviewed and approved | maintainer (session) |
| 2026-10-14T21:29Z | No production pin: production is to upgrade to 0.3.1 (row 9 declined; row 8a acknowledged) | maintainer (session) |
| 2026-10-14T21:29Z | Run a fresh code review of `2c1a1b7..981c1d3` before the tag; push `main` | maintainer (session) |
| 2026-10-14T21:55Z | The agent upgrades production (exporter only, `docker compose pull && up -d`, stays on `:latest`) right after the release is verified, and restarts the exporter once for the steady-state pass (rows 17, 19a) | maintainer (session) |
| 2026-10-14T21:56Z | The agent runs `just release patch` (row 10) | maintainer (session) |
