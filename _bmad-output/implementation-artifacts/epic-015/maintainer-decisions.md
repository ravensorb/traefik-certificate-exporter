# E015 "0.3.1" — maintainer decisions

Written by the l3io-plan run of 2026-10-12. The planning run has no inbox, so every decision
below has a recommended default, and **each story is written to proceed on that recommendation**
until the maintainer answers. To overturn one, edit the "Answer" line and the named story before
it is dispatched. Facts behind each recommendation: `_bmad-output/planning-artifacts/research/research-2026-10-12-release-0.3.1.md` (§ cited per item).

Already decided (not re-opened here): BL-E014-106 scope, maintainer decision 2026-10-12
(`state/events.jsonl` BL-E014-106 note): `settings.validatekeys` default true, `--no-validate-keys`,
no toggle for the .pfx compare, fingerprint sidecar, ADR-0043 amendment, tests first.

Status legend: **open** = needs an answer; the story proceeds on the recommendation.

## Product (sprint S01)

### MD-01 … MD-05 — WITHDRAWN (2026-10-12)

Withdrawn by the maintainer constraint for E015-S01-001, 2026-10-12, verbatim: **"for the root fix -- do NOT break lsio and the way they do things"**. The withdrawn recommendations were: refuse a non-root-owned config in root mode (MD-01); take `/app` and `/defaults` back to root (MD-02); take `/config` and `config.yaml` back to root, ending PUID editing (MD-03); neutralise the base image's `lsiown` lines at build (MD-04); extend the ownership refusal to confuse's default/user config (MD-05). `/config` stays owned by `abc` (PUID/PGID), the LinuxServer init is untouched, and host operators keep editing `config.yaml` as their PUID user. Replaced by MD-19 … MD-23 (research §1).

### MD-06 — Upgrade from 0.3.0: how is the first fingerprint sidecar created? (E015-S01-002)
- **Options:** (a) verify each existing `.pfx` once by content (slow path, ~0.6 s per RSA-4096 `.pfx`) and write only the sidecar; (b) rebuild every `.pfx` (every labelled container restarts once and the hook fires for every domain).
- **Recommendation:** (a). An upgrade should not look like a mass renewal.
- **Story assumes:** (a).
- **Status:** open. **Answer:**

### MD-07 — Sidecar and key-load design defaults (E015-S01-002 D1, D3–D6)
- **Defaults the story assumes** (all recommended; overturn individually):
  - D1: an unchanged pass loads no key at all; keys load only when a `.pfx` must be built or verified (an "always load once" design still costs ~41 s per unchanged pass over 74 domains with validation on).
  - D3: sidecar `<pfx>.fingerprint.json`, derived by a pure helper next to `_artifact_paths`, deliberately **not** a recorded artifact, so it never moves the ADR-0045 restart mtime.
  - D4: passphrase hash with cryptography `Scrypt` (n=2^14, r=8, p=1, 16-byte random salt per sidecar) behind an `lru_cache`.
  - D5: write order PEMs → `.pfx` → sidecar; a stale sidecar leads to the verify path, never to a false "unchanged".
  - D6: one INFO start-up line `RSA key validation: on/off` (no per-start WARNING when off).
  - ADR form: a new ADR (slug `pfx-fingerprint-sidecar`) plus a dated `## Amendment` in ADR-0043.
- **Status:** open. **Answer:**

### MD-08 — Pre-confuse names without the `TRAEFIK_` prefix (E015-S01-004 D-1)
- **Question:** 8 of the 11 historical names (`DRYRUN`, `FLAT`, `RESTART_CONTAINERS`, `DOMAINS_INCLUDE`, `DOMAINS_EXCLUDE`, `RUN_AT_START`, `CONFIG_FILE`, `TEST_VERSION`) have no prefix (research §4). Warn about them too?
- **Options:** (a) warn about all eleven; (b) only the three `TRAEFIK_*` names.
- **Recommendation:** (a). The old README told operators to set them in compose files. Cost: a CLI user whose shell exports e.g. `FLAT=1` gets one advisory warning (exact, case-sensitive match only).
- **Story assumes:** (a).
- **Status:** open. **Answer:**

### MD-09 — Warn only, or honour old names as aliases? (E015-S01-004 D-2)
- **Recommendation:** warn and ignore (the existing legacy policy). An alias is a compatibility contract and would need an ADR. Production is unaffected: `resolverinpathname` already defaults to true.
- **Story assumes:** warn and ignore.
- **Status:** open. **Answer:**

### MD-19 — How RT-1 is closed without breaking LinuxServer conventions (E015-S01-001)
- **Options:** (a) run the post-export hook as `abc` even when the exporter is root (`subprocess.run(user=)`, `s6-setuidgid` or `setpriv`, all available); (b) when running as root, take the root-sensitive settings from the environment/CLI only and ignore their values from `config.yaml`, the confuse user config and `.env` files; (c) split a root-only reader from an `abc` worker.
- **Recommendation:** (b). It closes the reproduced attack (the RT-1 payload's hook comes from `config.yaml`, so root ignores it) without touching LSIO init or ownership. (a) breaks root hooks that must read the `0600 root` keys or the Docker socket, and a root opt-in would still have to come from the environment; (c) has no LSIO precedent for a single app (swag runs fail2ban as root from `/config`-seeded config) and needs new IPC plumbing.
- **Story assumes:** (b), with a declared trust class for every setting in `config_default.yaml` (`ROOT_SETTING_TRUST`), plus tests that every key is classified, every file the loader opens is covered, and the hook is the package's only process-spawn site; an image test replays RT-1.
- **Status:** open. **Answer:**

### MD-20 — What happens to a file-sourced root-sensitive value in root mode? (E015-S01-001)
- **Options:** (a) ignore it, fall back to the next non-file source, log one ERROR naming setting and file (never the value), keep exporting; (b) exit 1.
- **Recommendation:** (a): certificates keep flowing, the ERROR repeats every start, and an upgrade does not crash-loop.
- **Story assumes:** (a).
- **Status:** open. **Answer:**

### MD-21 — Which settings are environment-only when running as root? (E015-S01-001)
- **Options:** (a) `postexportcommand` and `outputpath` only; (b) also `restartcontainers`, `appriseurls`, `datapath`.
- **Recommendation:** (a). Root + the Docker socket is host-root, but `docker.py` only pings, lists by label, gets and restarts labelled containers, with the endpoint from `DOCKER_HOST` only; so a file-set `restartcontainers: true` gains at most restarts of containers carrying the restart label. Apprise loads no plugins (`plugin_paths` empty) and reads no local attachment; `datapath`/`filespec` are only read. The image `ENV` already pins `outputpath=/certs`.
- **Story assumes:** (a); E015-S01-002's new `validatekeys` is classified any-source (the classification test will fail S01-002 until it is added — intended).
- **Status:** open. **Answer:**

### MD-22 — Opt-in for a hook that must run as root (E015-S01-001)
- **Options:** (a) setting the hook in the environment (or CLI) is itself the opt-in; it runs with the exporter's uid; (b) a new `…POSTEXPORTRUNASROOT` flag; (c) default the hook to `abc`.
- **Recommendation:** (a), no new flag. Upgrade note: root-mode users with the hook in `config.yaml` must move it to the container `environment:`.
- **Story assumes:** (a).
- **Status:** open. **Answer:**

### MD-23 — Adjacent gaps found during the redesign: venv under `abc`-owned `/app`; root-owned seeded `config.yaml`
- **Options:** (a) fix in E015-S01-001; (b) separate backlog items.
- **Recommendation:** (b), both outside RT-1's reproduced path and both touching image layout: BL-E015-002 (Medium: move the venv to `/lsiopy` as LSIO Python images do; renaming `/app/.venv` as `abc` is blocked today only by overlay2 `EXDEV`) and BL-E015-003 (Low: seed `config.yaml` as `abc:abc` per LSIO convention so PUID in-place editors work). Consider scheduling BL-E015-002 into 0.3.1 if the maintainer wants the `/app` path closed before release.
- **Story assumes:** (b); both are non-goals of E015-S01-001.
- **Status:** open. **Answer:**

## Release pipeline (sprint S02)

### MD-10 — GHCR credential (E015-S02-002)
- **Options:** (a) classic PAT with only `write:packages`, with an expiry, as `PUBLISH_GHCR_TOKEN` in the GitHub `release` (and `dev`, if wanted) environment plus `vars.PUBLISH_GHCR_USERNAME`/`PUBLISH_GHCR_IMAGE`; (b) the workflow `GITHUB_TOKEN` with `packages: write` (amends CI spine AD-9/AD-13; GitHub-only; widens job permissions).
- **Recommendation:** (a). The package already exists, is public and is linked to the repository, so no first-push visibility fix-up is needed (research §7). Risk accepted: a classic `write:packages` PAT can write every package the account owns.
- **Story assumes:** (a); configuring it is a maintainer-only forge action listed in the story.
- **Status:** open. **Answer:**

### MD-11 — GitHub forge release (`PUBLISH_RELEASE_TOKEN`) (E015-S02-002)
- **Options:** (a) fine-grained PAT on this repository only (Contents read/write, Pull requests read) in the `release` environment; (b) `GITHUB_TOKEN` with `contents: write` (amends AD-13).
- **Recommendation:** (a), enabled before the 0.3.1 tag, so 0.3.1 gets a forge release with wheel and sdist. Also backfill the missing `v0.3.0` GitHub release (manual `gh release create` from the PyPI-identical dists if re-running the old job cannot fetch its artifact).
- **Story assumes:** (a).
- **Status:** open. **Answer:**

### MD-12 — Gitea admin token used from a workstation (RT-2 / BL-E014-120) (E015-S02-002)
- **Options:** (a) revoke the admin token now and issue a `write:package`-only token for this purpose, stored only in the GitHub `release` environment; (b) additionally move packages to a bot/org namespace (changes image names — separate decision).
- **Recommendation:** (a) now; (b) not in 0.3.1.
- **Story assumes:** (a) as a maintainer-only forge action.
- **Status:** open. **Answer:**

### MD-13 — The split 0.3.0 (Gitea digest ≠ Docker Hub digest) (E015-S02-002, spec proposal AD-1)
- **Options:** (a) retag Gitea `0.3.0`, `0.3`, `latest` to the Docker Hub digest with `docker buildx imagetools create` (copy, no rebuild; dry run produced the Docker Hub digest); (b) annotate the Gitea package only.
- **Recommendation:** (a), plus an ADR record of the one-off exception; no `0.3.0` is pushed to GHCR (GHCR goes 0.2.0 → 0.3.1).
- **Story assumes:** (a) as a maintainer-only action with a verification row.
- **Status:** open. **Answer:**

### MD-14 — Workstation publishing of release versions (E015-S02-002)
- **Options:** (a) disallow: tokens live only in forge stores; `just act` is hardened against ambient secrets (`~/.actrc`, `.secrets`, `.vars`); (b) allow as an emergency path with mitigations (pinned runner digest, scoped token, tag already on the forge).
- **Recommendation:** (a). Stated limit: a raw `act -s …` run cannot be prevented by the repository. A forge-tag check in `validate-tag` was rejected: the Gitea repository is not anonymously readable and the check would need the ambient token.
- **Story assumes:** (a).
- **Status:** open. **Answer:**

### MD-15 — Where the cross-registry digest-equality check lives (E015-S02-002/-004)
- **Options:** (a) a per-release checklist command (each lookup followed by `echo`, fixing E014's false-green row); (b) a `just` recipe (amends CI spine AD-4/AD-16); (c) a post-publish CI job.
- **Recommendation:** (a) for 0.3.1; revisit (c) once GHCR and Gitea publish from one run routinely.
- **Story assumes:** (a).
- **Status:** open. **Answer:**

### MD-16 — How production (rwusdckrls6) upgrades (E015-S02-004)
- **Options:** (a) keep `:latest` + Watchtower; (b) track `:0.3`; (c) pin a digest and upgrade by hand.
- **Recommendation:** freeze production on the 0.2.0 digest before the tag, upgrade by hand to 0.3.1 with the post-checks in the story, then track `:0.3`. `containrrr/watchtower` is archived and may fail against Docker 29's API floor; if the pre-check shows it failing, file a backlog item to replace it (e.g. the maintained fork) — not in 0.3.1.
- **Story assumes:** this sequence; every production step is maintainer-approved HITL.
- **Status:** open. **Answer:**

### MD-17 — Hook dependency pinning approach (E015-S02-003, spec proposal AD-2)
- **Options:** (A) move import-linter, mypy and the two type stubs into the Poetry dev group, run as `language: system`, delete the mirrors-mypy entry, add guard `precommit-hook-deps-locked`; (B) every Python hook into the lock; (C) document the gap only.
- **Recommendation:** (A), plus ADR-0042 "Not covered" listing the remaining remote hooks honestly and one Low backlog item for pre-commit-hooks' `ruamel.yaml>=0.15` range.
- **Story assumes:** (A).
- **Status:** open. **Answer:**

### MD-18 — Version number for a release that adds a setting
- **Question:** 0.3.1 adds `settings.validatekeys` / `--no-validate-keys` (opt-out, default unchanged) and tightens `/config` ownership. Semver for 0.x allows either a patch or a minor.
- **Options:** (a) 0.3.1 via `just release patch` as planned; (b) 0.4.0.
- **Recommendation:** (a). The new setting defaults to current behaviour and the ownership change is a security fix; the upgrade note carries the operator-visible changes.
- **Story assumes:** (a) (E015-S02-004).
- **Status:** open. **Answer:**

## Planning decisions taken by this run (no answer needed; recorded for traceability)

- E015-S01-004 reclassified simple → standard (scope grew: unprefixed names need a runtime change, history-derived tests, docs regeneration).
- E015-S02-001 reclassified simple → standard (guard, spine edits, act TLS-registry proof).
- E015 has no docs/spine story: each story applies its own spine/ADR edits at dev time, text first drafted in its notes under `## Spine/ADR amendments`.
- `docs/operational.md:422-426` ("Known limitation": relative file-log path resolves against `/config`) is inaccurate — the service cwd is its s6 service directory (research §1). Filed as BL-E015-001 (Low), not fixed in E015-S01-001.
- Story `depends_on` set: S01-002 ← S01-001 (`settings.py`); S01-003 ← S01-002 and S01-004 ← S01-002 (`certificate_exporter.py`, `config_default.yaml` / settings-surface tests); S02-002 ← S02-001 and S02-003 ← S02-001 (workflows, `.pre-commit-config.yaml`, walkthrough checklist); S02-004 ← all seven other stories.
