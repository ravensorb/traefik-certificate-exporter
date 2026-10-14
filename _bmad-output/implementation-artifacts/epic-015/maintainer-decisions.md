# E015 "0.3.1" — maintainer decision record

Written by the l3io-plan run of 2026-10-12 as a list of open questions with recommendations;
converted to a decision record on 2026-10-12 after the maintainer answered. **Every MD-06 …
MD-23 is accepted as recommended (2026-10-12). MD-01 … MD-05 are withdrawn. MD-24 and MD-25
were added on 2026-10-14 from the maintainer's decisions D1/D2 of 2026-10-13/14.** Facts behind each
decision: `_bmad-output/planning-artifacts/research/research-2026-10-12-release-0.3.1.md`
(§ cited per item).

Each entry says where the decision now lives. The consolidated 0.3.1 baseline is:
- PRD: `_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md` (Target 0.3.1);
- product spine: `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md` (Target 0.3.1);
- CI/CD spine: `_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md` (Target 0.3.1);
- one `.memlog.md` decision line per decision in each spine folder.

Binding constraints for this release:
- **LinuxServer conventions (2026-10-12), verbatim:** "for the root fix -- do NOT break lsio and the way they do things".
- **Earlier maintainer rules, still binding:** settings precedence CLI > env > config file > defaults for every setting (the root-mode rule of MD-19 … MD-22 is a trust rule over admissible sources, not a precedence change; PRD FR-10, product spine AD-2/AD-6); strict import-linter layering (product AD-13); restart only on change, defer not drop (product AD-10); 0.x until stable (CI AD-7); Poetry, not uv (ADR-0001); LiquidLogicLabs actions at major tags (CI AD-5); no `env.ACT` (CI AD-6).
- **Scope (2026-10-12):** BL-E015-002 (move the venv from `/app` to `/lsiopy`) is **not** in 0.3.1. It is a known open risk (PRD §6, product spine Deferred).

Already decided before this run (not re-opened): BL-E014-106 scope, maintainer decision
2026-10-12 (`state/events.jsonl` BL-E014-106 note): `settings.validatekeys` default true,
`--no-validate-keys`, no toggle for the .pfx compare, fingerprint sidecar, ADR-0043 amendment,
tests first.

## Summary

| MD | Decision | Status | Lives in |
|---|---|---|---|
| MD-01 … MD-05 | Take `/config`, `/app`, `/defaults` back to root; neutralise `lsiown`; refuse non-root-owned config | Withdrawn 2026-10-12 | — (replaced by MD-19 … MD-23) |
| MD-06 | Upgrade from 0.3.0: verify each `.pfx` once, write only the sidecar | Accepted 2026-10-12 | PRD FR-2; product AD-8; E015-S01-002 (D2, AC 9) |
| MD-07 | Sidecar and key-load defaults D1, D3–D6; new ADR + ADR-0043 amendment | Accepted 2026-10-12 | PRD FR-2, FR-14, FR-15, FR-19, NFR-1, NFR-8; product AD-3, AD-8, AD-10, Conventions (artifacts); E015-S01-002 |
| MD-08 | Warn about all eleven pre-confuse names | Accepted 2026-10-12 | PRD FR-16, NFR-2; product AD-6; E015-S01-004 (D-1) |
| MD-09 | Warn and ignore; no aliases | Accepted 2026-10-12 | PRD FR-16, §5; product AD-6; E015-S01-004 (D-2) |
| MD-10 | GHCR: classic PAT, `write:packages` only | Overturned 2026-10-14 (MD-26) | PRD FR-17; CI AD-9, AD-13; E015-S02-002 (D2) |
| MD-11 | Forge release: fine-grained PAT; backfill `v0.3.0` | Overturned 2026-10-14 (MD-26) | PRD FR-17, NFR-4; CI AD-9, AD-13; E015-S02-002 (D3, D7) |
| MD-12 | Revoke the Gitea admin token; `write:package`-only token in GitHub `release` | Amended 2026-10-14 (MD-26): token also kept in Infisical | PRD FR-17; CI AD-9, AD-13, Deferred (namespace); E015-S02-002 (D4) |
| MD-13 | Retag Gitea 0.3.0 to the Docker Hub digest; record the exception | Overturned 2026-10-14 (MD-26) | PRD NFR-4; CI AD-10; E015-S02-002 (D6) |
| MD-14 | No workstation publishing of release versions | Overturned 2026-10-14 (MD-26) | PRD FR-17; CI AD-9, AD-16, Deferred; E015-S02-002 (D5) |
| MD-15 | Digest equality as a per-release checklist command | Overturned 2026-10-14 (MD-26) | PRD NFR-4; CI AD-10, AD-12, Deferred; E015-S02-002 (D8), E015-S02-004 |
| MD-16 | Production: freeze on 0.2.0, hand upgrade, then track `:0.3` | Accepted 2026-10-12 | E015-S02-004 (P1–P3) only; not a spine invariant (CI `.memlog.md`); PRD §6 (Watchtower) |
| MD-17 | Hook dependencies into the Poetry dev group (option A) + guard | Accepted 2026-10-12 | PRD NFR-9, §6; CI AD-3, Stack, Deferred; product AD-1, AD-13, Stack; E015-S02-003 |
| MD-18 | Version 0.3.1 via `just release patch` | Accepted 2026-10-12 | PRD header; CI AD-7, AD-16; E015-S02-004 |
| MD-19 | Close RT-1 by environment/CLI-only root-sensitive settings (option b) | Accepted 2026-10-12 | PRD FR-10, FR-18; product AD-2, AD-6, AD-12, Conventions; E015-S01-001 |
| MD-20 | File-sourced root-sensitive value: ignore with one ERROR, keep exporting | Accepted 2026-10-12 | PRD FR-18, NFR-2; product AD-2, Conventions (errors); E015-S01-001 |
| MD-21 | Environment-only when root: `postexportcommand`, `outputpath`, `datapath`; `filespec` a validated file-name glob in every mode; `/data:ro` in both modes | Accepted 2026-10-12; extended 2026-10-12 (arch gate AG-1) | PRD FR-10, FR-11, FR-18, FR-19; product AD-2 (trust-class table), AD-6; [ADR-0049](../../../docs/adr/0049-root-mode-trust-covers-hook-output-and-store-location.md); E015-S01-001, E015-S01-002 |
| MD-22 | Root hook opt-in is setting it in the environment/CLI; no new flag | Accepted 2026-10-12 | PRD FR-12, FR-18, §5; product AD-2, AD-9; E015-S01-001 |
| MD-23 | Venv under `/app` and seeded config owner are separate backlog items | Accepted 2026-10-12 | PRD §6; product AD-4, AD-12, Deferred; BL-E015-002, BL-E015-003; E015-S01-001 non-goals |
| MD-24 | `.env` only for the standalone CLI: `settings.loaddotenv` (env/CLI only), `false` in the image; no module-folder `.env` | Accepted 2026-10-14 (maintainer D1, 2026-10-13/14) | PRD FR-10, FR-18; product AD-2, AD-6; ADR-0049 amendment at dev time; E015-S02-005; supersedes BL-E015-052 |
| MD-25 | `appriseurls` stays `any-source` for now; arbitrary-request reach recorded as an accepted residual risk | Accepted 2026-10-14 (maintainer D2, 2026-10-13/14) | PRD FR-18, §6; product AD-2 (trust table, residual risks), Deferred; ADR-0049 amendment at dev time; E015-S02-005 AC 9; BL-E015-032 (wontfix) |

## Product (sprint S01)

### MD-01 … MD-05 — WITHDRAWN (2026-10-12)

- **Withdrawn by:** the maintainer constraint for E015-S01-001, 2026-10-12, verbatim: **"for the root fix -- do NOT break lsio and the way they do things"**.
- **What was withdrawn:** refuse a non-root-owned config in root mode (MD-01); take `/app` and `/defaults` back to root (MD-02); take `/config` and `config.yaml` back to root, ending PUID editing (MD-03); neutralise the base image's `lsiown` lines at build (MD-04); extend the ownership refusal to confuse's default/user config (MD-05).
- **Reason:** each changes LinuxServer's ownership convention or its init. `/config` stays owned by `abc` (PUID/PGID), the LinuxServer init is untouched, and host operators keep editing `config.yaml` as their PUID user.
- **Replaced by:** MD-19 … MD-23 (research §1).
- **Lives in:** PRD §5 (out of scope: changing LinuxServer conventions), FR-18; product spine AD-2 ("Base and LinuxServer conventions").

### MD-06 — Upgrade from 0.3.0: how the first fingerprint sidecar is created (E015-S01-002)

- **Decision:** (a) verify each existing `.pfx` once by content (~0.6 s per RSA-4096 `.pfx`) and write only the sidecar. Rejected: (b) rebuild every `.pfx`, which restarts every labelled container once and fires the hook for every domain.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-2 (upgrade sentence); product spine AD-8 ("Upgrade from 0.3.0"); E015-S01-002 D2 and AC 9.

### MD-07 — Sidecar and key-load design defaults (E015-S01-002 D1, D3–D6)

- **Decision:**
  - D1: an unchanged pass loads no key; keys load only when a `.pfx` must be built or verified, once per domain per pass.
  - D3: sidecar `<pfx>.fingerprint.json`, derived by a pure helper next to `_artifact_paths`, not a recorded artifact, so it never moves the ADR-0045 restart mtime.
  - D4: passphrase hash with cryptography `Scrypt` (n=2^14, r=8, p=1, 16-byte random salt per sidecar) behind an `lru_cache`.
  - D5: write order PEMs → `.pfx` → sidecar; a stale sidecar leads to the verify path, never to a false "unchanged".
  - D6: one INFO start-up line `RSA key validation: on/off` (no per-start WARNING when off).
  - ADR form: a new ADR (slug `pfx-fingerprint-sidecar`, written by E015-S01-002) plus a dated `## Amendment` in ADR-0043.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-2, FR-14, FR-15, FR-19, NFR-1, NFR-8; product spine AD-3 (start-up line), AD-8 (key loading, change test, fingerprint file contract, writes), AD-10 (not an artifact), Conventions (artifacts); E015-S01-002.

### MD-08 — Pre-confuse names without the `TRAEFIK_` prefix (E015-S01-004 D-1)

- **Decision:** (a) warn about all eleven historical names, the eight unprefixed ones (`DRYRUN`, `FLAT`, `RESTART_CONTAINERS`, `DOMAINS_INCLUDE`, `DOMAINS_EXCLUDE`, `RUN_AT_START`, `CONFIG_FILE`, `TEST_VERSION`) included, by exact case-sensitive match. Accepted cost: a CLI user whose shell exports e.g. `FLAT=1` gets one advisory warning.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-16, NFR-2; product spine AD-6; E015-S01-004 (recorded there as D-1).

### MD-09 — Warn only, or honour old names as aliases (E015-S01-004 D-2)

- **Decision:** warn and ignore (the existing legacy policy). An alias would be a compatibility contract and would need an ADR. Production is unaffected: `resolverinpathname` already defaults to true.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-16, §5 (no aliases); product spine AD-6 (C-16b, no ADR); E015-S01-004 (D-2).

### MD-19 — How RT-1 is closed without breaking LinuxServer conventions (E015-S01-001)

- **Decision:** (b) when running as root, take the root-sensitive settings from the environment/CLI only and ignore their values from `config.yaml`, the confuse user config and `.env` files, with a declared trust class for every setting in `config_default.yaml` (`ROOT_SETTING_TRUST`), tests that every key is classified, that every file the loader opens is covered and that the hook is the package's only process-spawn site, and an image test that replays RT-1. Rejected: (a) run the hook as `abc` (breaks root hooks that read `0600 root` keys or the socket; a root opt-in would still come from the environment); (c) split a root reader from an `abc` worker (no LinuxServer precedent; new IPC).
- **Status:** accepted 2026-10-12.
- **Precedence:** this is a trust rule, not a precedence change. CLI > env > config file > defaults holds for every setting; in root mode a file is simply not an admissible source for the two environment-only keys, and the key resolves by the same order over the remaining sources.
- **Lives in:** PRD FR-10 (reconciliation), FR-18; product spine AD-2 ("Root-mode settings trust", "Trust classes"), AD-6, AD-12 (init resolver), Conventions (state); E015-S01-001; [ADR-0049](../../../docs/adr/0049-root-mode-trust-covers-hook-output-and-store-location.md) (written at the arch gate 2026-10-12; E015-S01-001 implements it). The spawn-site guard is [ADR-0050](../../../docs/adr/0050-spawn-site-guard-uses-ruff-banned-api.md) (ruff `TID251` banned-api replaces the planned `ast` scan; arch gate AG-2).

### MD-20 — What happens to a file-sourced root-sensitive value in root mode (E015-S01-001)

- **Decision:** (a) ignore it, fall back to the next non-file source, log one ERROR naming setting and file (never the value), keep exporting. Rejected: (b) exit 1 (crash-loop on upgrade).
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-18, NFR-2; product spine AD-2, AD-12 (logged, not signalled), Conventions (errors); E015-S01-001.

### MD-21 — Which settings are environment-only when running as root (E015-S01-001)

- **Decision as first accepted (2026-10-12):** (a) `postexportcommand` and `outputpath` only. `restartcontainers`, `appriseurls` and `datapath` stay any-source (bounded Docker API use, egress only, read only). E015-S01-002's `validatekeys` is any-source.
- **Extended 2026-10-12 by the maintainer ("Yes" to the AG-1 fix of the epic architecture gate, `arch/arch-gate-review.md` and `arch/arch-gate-review-architect.md`).** "Read only" was false as a rationale: a `filespec` from a `PUID`-writable file was joined to `datapath` with no containment check, so an absolute or `..` value pointed a file-forced root exporter at a store the `PUID` account forged, and root wrote its keys and certificates over `/certs` and restarted the labelled containers. The decision now is:
  1. **`filespec` is a plain file-name glob in every mode.** It is validated once at settings load by checking the pattern text, not resolved paths. Empty values, `/` or `\`, exactly `.` or `..`, and absolute values (or a drive) are rejected with one ERROR naming the setting and its source, and the packaged default `*.json` is used. The export pass, the watcher and the init resolver (`init-…-config/run:85-88`) all read this one validated value. It needs a release-note bullet and updated `--file-spec` help text and `README.md`. `filespec` stays any-source.
  2. **`datapath` is environment/CLI-only in root mode**, exactly like `postexportcommand` and `outputpath`. A file-sourced value is ignored with one ERROR. The image is unaffected (`DATAPATH` comes from `ENV`); PyPI root runs bear the same cost as for `outputpath`.
  3. **`/data:ro` is required in both modes.** Residual risk recorded: a `PUID`-writable store directory still gives the same reach (AR-1). Low backlog item BL-E015-004: `privilege-decision.sh` emits its "store is writable" note in root mode too.
  4. The class rule becomes "a setting whose value root executes, writes to, or trusts as the source of what it writes is environment-only when root, unless it is validated at load so that it cannot leave an environment-only path". The remaining `any-source` rationales are reviewed claims, not checked; the last row reads "availability only, no read/write/execute reach" (AG-6).
  - The binding LinuxServer rule holds: no Dockerfile, s6 or `/config` ownership change.
  - `restartcontainers`, `appriseurls` and `validatekeys` stay any-source, as first decided.
- **Status:** accepted 2026-10-12; extended 2026-10-12 (AG-1).
- **Lives in:** PRD FR-10, FR-11, FR-18, FR-19, §6 (AR-1); product spine AD-2 (trust-class table, class rule, `/data:ro`, residual risks), AD-6, Conventions (state, errors), Deferred; [ADR-0049](../../../docs/adr/0049-root-mode-trust-covers-hook-output-and-store-location.md); E015-S01-001 (AC 1, AC 1a, AC 7 (v)), E015-S01-002 (AC 16a classifies `validatekeys` as any-source).

### MD-22 — Opt-in for a hook that must run as root (E015-S01-001)

- **Decision:** (a) setting the hook in the environment (or CLI) is itself the opt-in; it runs with the exporter's uid. No new flag; the hook is not defaulted to `abc`. Upgrade note: root-mode users with the hook in `config.yaml` move it to the container `environment:`.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-12, FR-18, §5; product spine AD-2 ("Hook opt-in"), AD-9; E015-S01-001 (release notes), E015-S02-004 (production pre-check).

### MD-23 — Adjacent gaps: venv under `abc`-owned `/app`; root-owned seeded `config.yaml`

- **Decision:** (b) separate backlog items, both non-goals of E015-S01-001: BL-E015-002 (Medium: move the venv to `/lsiopy` as LinuxServer Python images do) and BL-E015-003 (Low: seed `config.yaml` as `abc:abc`). The maintainer confirmed on 2026-10-12 that **BL-E015-002 is not scheduled into 0.3.1**; it is a known open risk.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD §6 (open risks); product spine AD-4 (venv stays at `/app/.venv`), AD-12 (seeded file owner), Deferred; `state/issues.yaml` BL-E015-002, BL-E015-003; E015-S01-001 non-goals and residual risks.

### MD-24 — `.env` loading: standalone CLI only (E015-S02-005)

- **Decision (maintainer D1, 2026-10-13/14):** keep `.env` support for the standalone CLI, because the tool may be packaged and installed outside containers, and switch it off in the container:
  1. New setting `settings.loaddotenv`, default `true`. Env `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV`, CLI `--no-dotenv` (the `store_const` opt-out convention of `--no-validate-keys`). It is taken only from the environment or the CLI, never from `.env`, `config.yaml` or the confuse user config, because it decides whether `.env` is read. It gets a third `ROOT_SETTING_TRUST` class, `environment-only-in-every-mode`, enforced in every mode by the existing derived checks. `config_default.yaml` stays the single key list.
  2. The Dockerfile sets `ENV TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV=false`, like the pinned `DATAPATH`/`OUTPUTPATH`. LinuxServer init, `/config` ownership and s6 stay untouched.
  3. In the container `/config/.env` is never read. If a `.env` is present, one WARNING at start says it is not read and points to the container's `environment:`/`env_file:` or `config.yaml`. Values are never logged.
  4. CLI: a `.env` in the current working directory loads as today. Run as root (e.g. `sudo`), S01-001's root-mode filtering stays: `any-source` settings only, no `${VAR}` expansion. This ratifies the ADR-0049 amendment of 2026-10-12 for CLI root runs.
  5. The `.env` in the installed package's own folder (`self.modulePath`) is no longer read. Only the working-directory `.env` remains.
  6. Docs: README (CLI), `docker/README.md` and `docs/upgrading.md` `## 0.3.0 → 0.3.1` (container), ADR-0049 amendment, PRD FR-10/FR-18, product spine AD-2/AD-6.
  7. BL-E015-052 (ratify the root-mode `.env` narrowing) is superseded.
- **Planning finding recorded with the decision (2026-10-14).** Probed on `traefik-certificate-exporter:local`: the s6 service's working directory is its s6 service directory (`/run/s6-rc:s6-rc-init:<id>/servicedirs/svc-traefik-certificate-exporter`), not the image `WORKDIR` `/config`. A planted `/config/.env` therefore did not reach the service in 0.3.0. It did reach `docker exec <c> traefik-certificate-exporter …`, which runs in `/config` (`dryRun: true` from the file). Two consequences for item 3:
  - the switch closes the `docker exec`/one-off path, and also the service path should s6's cwd ever change;
  - the WARNING checks the `.env` in the cwd **and** the one beside the configuration file (`/config/.env` for `-c /config/config.yaml`), because a cwd-only check would never see `/config/.env` from the service.

  Recorded as a planning refinement of item 3's wording, not a change of intent. Also, ADR-0049's 2026-10-12 amendment ("The exporter's working directory in the image is `/config`") and two operator docs are inaccurate for the service; E015-S02-005 corrects them.
- **Status:** accepted 2026-10-14.
- **Lives in:** PRD FR-10, FR-18 (Target 0.3.1, delivered by E015-S02-005); product spine AD-2 (`.env` rule, trust-class table), AD-6 (the switch and the class), Changelog; `.memlog.md` (2026-10-14); E015-S02-005 (AC 1-8, 10-12); ADR-0049 dated amendment written by E015-S02-005 at dev time; `state/issues.yaml` BL-E015-052 (resolved `obsolete`, ref E015-S02-005).

### MD-25 — `appriseurls` stays `any-source`: accepted residual risk (BL-E015-032, RT-4)

- **Decision (maintainer D2, 2026-10-13/14):** keep `appriseurls` `any-source` "for now". Do not restrict file-sourced Apprise URLs in root mode, and do not refuse schemes.
- **Residual risk accepted, stated plainly:** Apprise `json://`, `xml://` and `form://` (and `jsons://`, `xmls://`, `forms://`) can send a request with a chosen method, path, query and headers to any host the container can reach. The `PUID` account, which can write `config.yaml`, can therefore make the exporter send such requests whenever a pass reports a changed domain. **Example: a POST to a docker-socket-proxy's container endpoints, such as `/containers/<id>/stop`, needs no body.** So `appriseurls: ["json://docker-socket-proxy:2375/containers/traefik/stop?method=POST"]` stops a container through a proxy that allows `CONTAINERS` and `POST`. `docs/operational.md` recommends that proxy topology for `restartcontainers` without the socket. The same applies to any unauthenticated internal admin API on the container's networks. The setting gives no local file read, no local write and no process spawn (ADR-0049 review; ADR-0050).
- **What changes now:** only the stated rationale. "Network egress only" in `ROOT_SETTING_TRUST`, ADR-0049 Decision 2 and spine AD-2 becomes "outbound requests to any reachable host, accepted residual risk (MD-25)". The code comment and the ADR amendment are written by E015-S02-005 (AC 9) at dev time; the spine and PRD were updated on 2026-10-14.
- **Revisit when** any of these happens: the project documents or recommends a deployment where the exporter shares a network with a docker-socket-proxy or another unauthenticated control API; a user report or red-team finding shows the path used; or a release after 0.3.1 adds root-mode restrictions for another `any-source` key. In that release, decide between environment-only-when-root for `appriseurls` and refusing the free-form schemes (`json`, `xml`, `form` and their TLS forms) from files in root mode (RT-4 remediation options).
- **Status:** accepted 2026-10-14.
- **Lives in:** PRD FR-18 (residual sentence), §6 (open-risk row); product spine AD-2 (trust table, residual risks), Deferred; `.memlog.md` (2026-10-14); E015-S02-005 AC 9 and its ADR-0049 amendment; `state/issues.yaml` BL-E015-032 (resolved `wontfix`, ref MD-25).

## Release pipeline (sprint S02)

E015-S02-002's story decisions D1–D8 follow from these: D1 (all-GitHub publishing forge from 0.3.1) is implied by MD-10 … MD-12, which store every publish token in the GitHub `release` environment; D2 = MD-10; D3 and D7 = MD-11; D4 = MD-12; D5 = MD-14; D6 = MD-13; D8 = MD-15. E015-S02-004's P1–P3 are MD-16.

### MD-10 — GHCR credential (E015-S02-002)

- **Decision:** (a) classic PAT with only `write:packages`, with an expiry, as `PUBLISH_GHCR_TOKEN` in the GitHub `release` environment, plus `PUBLISH_GHCR_USERNAME`/`PUBLISH_GHCR_IMAGE`. Rejected: (b) the workflow `GITHUB_TOKEN` with `packages: write` (widens job permissions, hands the ambient token to a publish step; CI AD-9/AD-13). Accepted risk: a classic `write:packages` PAT can write every package the account owns. The package already exists, is public and is linked to the repository (research §7).
- **Status:** accepted 2026-10-12. Configuring it is a maintainer-only forge action in E015-S02-002.
- **Lives in:** PRD FR-17; CI spine AD-9, AD-13; E015-S02-002 (D2), E015-S02-004 (configured before the tag).

### MD-11 — GitHub forge release (`PUBLISH_RELEASE_TOKEN`) (E015-S02-002)

- **Decision:** (a) fine-grained PAT on this repository only (Contents read/write, Pull requests read) in the `release` environment, enabled before the 0.3.1 tag, so 0.3.1 gets a forge release with wheel and sdist. Backfill the missing `v0.3.0` GitHub release (re-run the old `release` job, else `gh release create` from the PyPI-identical dists). Rejected: (b) `GITHUB_TOKEN` with `contents: write`.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-17, NFR-4; CI spine AD-9, AD-13; E015-S02-002 (D3, D7), E015-S02-004.

### MD-12 — Gitea admin token used from a workstation (RT-2 / BL-E014-120) (E015-S02-002)

- **Decision:** (a) revoke the admin token now and issue a `write:package`-only token, stored only in the GitHub `release` environment. (b) moving packages to a bot/org namespace is not in 0.3.1 (it changes image names).
- **Status:** accepted 2026-10-12. A maintainer-only forge action in E015-S02-002.
- **Lives in:** PRD FR-17 (Gitea holds no publish credential), §6; CI spine AD-9, AD-13, Deferred (namespace); E015-S02-002 (D4).

### MD-13 — The split 0.3.0 (Gitea digest ≠ Docker Hub digest) (E015-S02-002, spec proposal AD-1)

- **Decision:** (a) retag Gitea `0.3.0`, `0.3`, `latest` to the Docker Hub digest with `docker buildx imagetools create` (copy, no rebuild), plus an ADR record of the one-off exception; no `0.3.0` is pushed to GHCR (GHCR goes 0.2.0 → 0.3.1).
- **Status:** accepted 2026-10-12. A maintainer-only action with a verification row in E015-S02-002.
- **Lives in:** PRD NFR-4; CI spine AD-10 (exception on record); E015-S02-002 (D6); ADR to be written by E015-S02-002.

### MD-14 — Workstation publishing of release versions (E015-S02-002)

- **Decision:** (a) disallow: tokens live only in forge stores; `just act` is hardened against ambient secrets (`~/.actrc`, `.secrets`, `.vars`). Stated limit: a raw `act -s …` run cannot be prevented by the repository. A forge-tag check in `validate-tag` was rejected (the Gitea repository is not anonymously readable; the check would need the ambient token).
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD FR-17, §6; CI spine AD-9 ("No workstation publishing"), AD-16 (`just act`), Deferred; E015-S02-002 (D5, AC 2–4).

### MD-15 — Where the cross-registry digest-equality check lives (E015-S02-002/-004)

- **Decision:** (a) a per-release checklist command, each lookup followed by `echo` (fixing E014's false-green row). (c) a post-publish CI job is revisited once GHCR and Gitea publish from one run routinely. Rejected: (b) a `just` recipe.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD NFR-4; CI spine AD-10, AD-12 (the command), Deferred; E015-S02-002 (D8, walkthrough), E015-S02-004 (row 14).

### MD-26 — CI/CD simplified to the maintainer's stated goals (2026-10-14; overturns MD-10, MD-11, MD-13, MD-14, MD-15; amends MD-12)

The maintainer's goals, 2026-10-14: run under `act`, self-hosted Gitea and GitHub; use
LiquidLogicLabs actions pinned to `@vN`; publish the package to a custom registry or PyPI
(release) / TestPyPI (dev), and the image to a custom registry, GHCR or Docker Hub; publish
only when a destination's variables are defined; keep the tokens for GitHub in Infisical.
"we are massively over complicating things".

- **Decision:** GHCR and the forge release use the workflow's own token (`packages: write` on
  `publish-image`, `contents: write` on `release`); `PUBLISH_GHCR_TOKEN` and
  `PUBLISH_RELEASE_TOKEN` become optional overrides. The Gitea token stays `write:package`
  only and may live in Infisical. Dropped: the one-forge check, the workstation-publishing
  rule, the Gitea `0.3.0` retag, the `v0.3.0` release backfill as a requirement, the digest
  checklist and the token-expiry table. The `PUBLISH_GITEA_*` names stay.
- **Lives in:** ADR-0052 (rewritten); CI spine AD-9, AD-10, AD-12, AD-13; walkthrough;
  E015-S02-002 notes "Maintainer checklist" and Verification rows 1, 6, 8, 9, 11.

### MD-16 — How production (rwusdckrls6) upgrades (E015-S02-004)

- **Decision:** freeze production on the 0.2.0 digest before the tag, upgrade by hand to 0.3.1 with the post-checks in the story, then track `:0.3`. If the pre-check shows Watchtower (archived upstream) failing against Docker 29's API floor, file a backlog item to replace it; not in 0.3.1. Every production step is maintainer-approved HITL.
- **Status:** accepted 2026-10-12.
- **Lives in:** E015-S02-004 (P1–P3, AC 5, AC 10–11) only. It is an operational procedure, not a pipeline invariant, so the CI spine does not carry it (CI `.memlog.md`, 2026-10-12). PRD §6 lists the Watchtower risk.

### MD-17 — Hook dependency pinning approach (E015-S02-003, spec proposal AD-2)

- **Decision:** (A) move import-linter, mypy and the two type stubs into the Poetry dev group, run as `language: system`, delete the mirrors-mypy entry, add the guard `precommit-hook-deps-locked`; amend ADR-0042 "Not covered" with the remaining remote hooks; file one Low backlog item for pre-commit-hooks' `ruamel.yaml>=0.15` range. Not chosen: (B) every Python hook into the lock (Deferred); (C) document the gap only.
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD NFR-9, §6; CI spine AD-3, Stack, Deferred; product spine AD-1, AD-13, Stack; E015-S02-003.

### MD-18 — Version number for a release that adds a setting

- **Decision:** (a) 0.3.1 via `just release patch`. The new setting `settings.validatekeys` defaults to current behaviour, and the security change is a fix; the upgrade note carries the operator-visible changes. Rejected: (b) 0.4.0.
- **Correction recorded at acceptance:** the original recommendation also cited "tightens `/config` ownership". That change was withdrawn with MD-01 … MD-05; `/config` ownership does not change in 0.3.1. The security fix is the root-mode settings trust rule (MD-19 … MD-22).
- **Status:** accepted 2026-10-12.
- **Lives in:** PRD header (patch release); CI spine AD-7 (0.x until stable), AD-16 (`just release`); E015-S02-004 (AC 6).

## Planning decisions taken by the planning run (recorded for traceability)

- E015-S01-004 reclassified simple → standard (scope grew: unprefixed names need a runtime change, history-derived tests, docs regeneration).
- E015-S02-001 reclassified simple → standard (guard, spine edits, act TLS-registry proof).
- E015 has no docs/spine story. Since the 2026-10-12 consolidation the spines already state the 0.3.1 target; each story verifies the spine text against what it ships at dev time, records any deviation under `## Spine/ADR amendments` in its notes, and replaces "ADR to be written by E015-S0x-00y" with the number it reserves.
- `docs/operational.md:422-426` ("Known limitation": relative file-log path resolves against `/config`) is inaccurate — the service cwd is its s6 service directory (research §1). Filed as BL-E015-001 (Low), not fixed in E015-S01-001.
- Story `depends_on` set: S01-002 ← S01-001 (`settings.py`); S01-003 ← S01-002 and S01-004 ← S01-002 (`certificate_exporter.py`, `config_default.yaml` / settings-surface tests); S02-002 ← S02-001 and S02-003 ← S02-001 (workflows, `.pre-commit-config.yaml`, walkthrough checklist); S02-004 ← all seven other stories. Unchanged by the consolidation.
