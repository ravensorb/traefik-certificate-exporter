# E015 "0.3.1": epic architecture-gate review

- **Skill / mode:** `l3io-arch-review`, Mode B (architectural review of an existing design), applied to the E015 story set before implementation.
- **Date:** 2026-10-12.
- **Work type:** MIXED.
  - S01 (product): E015-S01-001 … S01-004.
  - S02 (pipeline): E015-S02-001 … S02-003, plus S02-004 (maintainer-run HITL release).
- **Standards applied:**
  - `references/standards-core.md` §1–10;
  - overlays: Python, GitHub Actions, Docker, Shell.
- **Binding maintainer rules honoured as constraints, not re-litigated:**
  - LinuxServer conventions untouched;
  - CLI > env > file > defaults, with the root-mode rule treated as a trust rule;
  - strict import-linter layering;
  - Poetry, not uv;
  - LiquidLogicLabs actions at major tags;
  - no `env.ACT`;
  - the global rules in `~/.claude/CLAUDE.md`.
- **Already resolved, not re-raised:** V-01 … V-16, R-01 and R-02 of `plan-review/validation-2026-10-12.md`. Also not re-raised: the deferred BL-E015-002 (venv under the `abc`-owned `/app`), which the maintainer explicitly scoped out.
- **Write scope:** this file only.

## Executive summary

The design is sound where it matters most:
- The root-mode trust rule keeps confuse doing the precedence and removes only an inadmissible source.
- The `.pfx` fingerprint file is never authoritative on its own.
- The rename handling reuses watchdog's own matcher.
- The release token model removes the workstation and forge-admin credentials.
- Every guard derives its scope from the source of truth and plants a violation against that scope.

There are two MAJOR findings, both in E015-S01-001:
- **AG-1:** the trust classification calls `filespec`/`datapath` "read only". But `filespec` is joined to `datapath` without a containment check, so the `PUID` account can point a root exporter at a store it forged. Root then writes that store's keys and certificates into the root-owned output tree, and restarts labelled containers. The image's `DATAPATH` `ENV` does not cover `filespec`.
- **AG-2:** the spawn-site guard is a hand-written AST scanner. Its existing-library check never evaluates ruff's flake8-bandit `S6xx` rules, which ruff, a tool AD-4 already allows and runs, provides.

There are four MINOR findings. No BLOCKER.

**Single most important action:** close AG-1 before E015-S01-001 starts. It needs a maintainer re-decision of MD-21's `filespec`/`datapath` rationale, and the PRD FR-18, spine AD-2 and ADR text must follow.

| Severity | Count |
|---|---|
| BLOCKER | 0 |
| MAJOR | 2 |
| MINOR | 4 |

## Findings

### AG-1 — MAJOR — E015-S01-001 (also product spine AD-2, PRD FR-18, MD-21)

- **Principle:** Core §3 Design by Contract (unchecked input at the system edge); security of the root-mode design; spec-gap.
- **Finding:** The trust-class rule is "a setting whose value root executes or writes **to** is environment-only when root". It covers *where* root writes, but not *what* root writes.
  - `datapath` and `filespec` are classed `any-source` because they are "read and JSON-parsed only".
  - `exportCertificates` globs `os.path.join(dataPath, fileSpec)` with no containment check, so an absolute or `..` `filespec` escapes `datapath`. `filespec` is read with a bare `.as_str()`.
  - The image pins `DATAPATH` (and `OUTPUTPATH`) by `ENV`, but not `FILESPEC`.

  So uid 1000 can write two files and get a root exporter to plant forged content:
  1. a forged ACME store `/config/forged.json`;
  2. a `config.yaml` with `filespec: /config/forged.json` and `restartcontainers: true`. The second setting forces root mode, which MD-21 allows from a file.

  After a restart, the root exporter writes that store's attacker-chosen private keys and certificates as root into `/certs/<real domain>/`, over the genuine files, and then restarts every labelled container.
  - The `PUID` account cannot write `/certs` in root mode (root writes keys `0600 root`), so this is a privilege-boundary crossing on the integrity of root-owned output. Consumers include `cert-distributor` and anything that mounts `/certs`.
  - It is not code execution, so this is not a BLOCKER.
  - An environment-set root hook also receives the forged domain list (`TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS`).
  - A PyPI root run has no `ENV`, so `datapath` from a file is exposed there in the same way.
  - The S01-001 replay (AC 7) and the scope guards cover only `postexportcommand`/`outputpath`, so nothing would catch this.
- **Evidence:**
  - `_bmad-output/implementation-artifacts/epic-015/sprint-01/stories/E015-S01-001.md:56` (classification);
  - `E015-S01-001.md:189` ("`datapath`/`filespec` (read and JSON-parsed only …)");
  - `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md:164`, `:170`;
  - `src/traefik_certificate_exporter/libs/certificate_exporter.py:1176-1178`;
  - `src/traefik_certificate_exporter/libs/settings.py:401`;
  - `docker/Dockerfile:126-127`;
  - `maintainer-decisions.md:104` (MD-21);
  - `research-2026-10-12-release-0.3.1.md:50`.
- **Recommended fix:** The maintainer re-decides MD-21 for these two keys. Recommended:
  - (a) Validate `filespec` at the edge in every mode, since it is a contract, not a trust rule. It must be a file-name glob with no path separator, no `..` and no absolute path. Otherwise log one ERROR and fall back to the next source or the default (as with an invalid log level). Watchdog already treats it as a name pattern on a non-recursive watch, so legitimate use is unaffected.
  - (b) Class `datapath` `environment-only-when-root`, with the same cost as `outputpath` for PyPI root runs. The image is unaffected because `DATAPATH` comes from `ENV`.

  Then add the following to S01-001:
  - an AC and unit tests: root plus a file `filespec` of `/config/x.json` or `../x.json` exports nothing from outside `datapath`; root plus a file `datapath` is withheld with the AC 2 ERROR;
  - an image case AC 7 (v) that replays the forged-store variant;
  - an ADR section on content integrity.

  Update the spine AD-2 table and the PRD FR-18 key list in the same change. The privilege-decision script reads the same resolved values through `loadFromFile` (spine `:129-130`), so it stays consistent. If the maintainer instead accepts the risk, the S01-001 ADR must record it as a residual with this scenario. "Read only" must not stay as the rationale.

### AG-2 — MAJOR — E015-S01-001

- **Principle:** global rule 1 (maintained tool over hand-rolled code; departing is a recorded decision); Core §7; CI AD-4 (allowed mechanisms).
- **Finding:**
  - AC 5 builds a bespoke `ast` scanner over the package. It looks for calls to `subprocess.*`, `os.system`, `os.popen`, `os.exec*`, `os.spawn*`, `os.posix_spawn*`, `os.fork*`, `pty.spawn` and `asyncio.create_subprocess_*`, plus `from subprocess import`, and comes with its own planted-call test.
  - The Existing-library check justifies it only as "stdlib `ast` … a test helper inside pytest, not a runner". It does not evaluate ruff's flake8-bandit rules:
    - S602/S604: shell=True;
    - S603: any `subprocess` call, with aliases resolved by ruff's semantic model;
    - S605: `os.system`/`os.popen`;
    - S606: `os.exec*`/`os.spawn*`/`os.startfile`.
  - ruff already runs as a required hook (AD-3) and is on AD-4's allowed list. With `per-file-ignores` for `libs/post_export.py`, it enforces "the hook is the only spawn site" over every file ruff discovers.
  - `pyproject.toml` has no `[tool.ruff]` section, so this is a configuration-only change. The scanner is small, but the rule requires the evaluation to be recorded either way.
- **Evidence:**
  - `E015-S01-001.md:67` (AC 5);
  - `E015-S01-001.md:240` (Existing-library check);
  - `E015-S01-001.md:223-224` (tests);
  - `pyproject.toml` (no `[tool.ruff]`);
  - CI spine `ARCHITECTURE-SPINE.md` AD-4.
- **Recommended fix:**
  - Preferred: enable `S602,S603,S604,S605,S606` in `[tool.ruff.lint]`, with a per-file ignore for `src/traefik_certificate_exporter/libs/post_export.py` only, and replace AC 5 with a ruff check.
    - Prove the scope by planting `os.system("id")` in a throwaway clone and showing that `ruff check` fails. Record it as a Verification row; per AD-4 it is not a pytest test.
    - State the coverage limit where the rule lives: `pty.spawn`, `os.fork` and `asyncio.create_subprocess_*` are not in ruff's set.
    - If that limit is unacceptable, keep only a minimal test for those three calls.
  - Otherwise: record in the new S01-001 ADR the evaluation of ruff `S6xx`, why it was rejected, the cost accepted, and the revisit condition (global rule 1).

### AG-3 — MINOR — E015-S01-002

- **Principle:** Core §3 Design by Contract (an interface contract that cannot be implemented as written).
- **Finding:**
  - The Interface contract gives `_passphrase_matches(passphrase: bytes, record: dict) -> bool` "behind `functools.lru_cache(maxsize=4096)`".
  - `lru_cache` hashes its arguments, and a `dict` is unhashable, so the first call raises `TypeError`.
  - D4 states the intended cache key as `(passphrase, salt, n, r, p)`, which contradicts the signature. Implementing it literally either fails or tempts a cache keyed on something else, such as `id(record)`.
- **Evidence:** `E015-S01-002.md:51` (D4 cache key); `E015-S01-002.md:161` (contract row).
- **Recommended fix:** Split the function:
  - an uncached `_passphrase_matches(passphrase, record)` that validates `kdf`/`n`/`r`/`p`/`salt`/`digest` types (unknown or bad gives `False`);
  - `@lru_cache _scrypt_verifies(passphrase: bytes, salt: bytes, n: int, r: int, p: int, digest: bytes) -> bool`, built only from hashable primitives.

  Amend the contract row and D4 to match.

### AG-4 — MINOR — E015-S01-002

- **Principle:** Core §4 Testability (non-deterministic assertions in the gating suite).
- **Finding:** AC 11 and AC 12 make hard wall-clock bounds (`< 2.0 s`) test assertions:
  - `test_unchanged_rsa4096_pass_loads_no_key_and_no_pfx`;
  - `test_first_rsa4096_pass_loads_each_key_once[False]`.

  They run in the default pytest suite, so in `just check` and in `build.yaml` on GitHub (Python 3.14), on Gitea runners and under act. The 4.5× margin was measured on this workstation only. The call-count spies are already the stated "mechanical proof of the bound"; the timing is called "secondary". A shared or QEMU-loaded runner turns the secondary assertion into an intermittent red gate that has nothing to do with the code.
- **Evidence:** `E015-S01-002.md:100-106` (AC 11–12); `E015-S01-002.md:275` ("wall-clock is the secondary assertion, with a 4.5× margin on this host"); `E015-S01-002.md:281-282`.
- **Recommended fix:**
  - Keep the 0/0 and exactly-5 load counts as the gating assertions.
  - Turn the absolute times into one of these:
    - a relative bound (for example, the unchanged pass takes less than ¼ of a validating first pass in the same process);
    - a recorded measurement in the notes (rows 2 and 14).
  - State the choice in AC 11 and AC 12.

### AG-5 — MINOR — E015-S02-002 (release token model; CI spine AD-10/AD-13)

- **Principle:** GitHub Actions overlay (secrets never exposed beyond need; least privilege); Core §7; ADR coverage.
- **Finding:**
  - From 0.3.1, `publish-image` logs in to Docker Hub, GHCR and Gitea, and writes all three credentials to the job's Docker config. These include the classic `write:packages` PAT, which can write **every** package of the account, and a per-user Gitea `write:package` token.
  - After the logins, the job runs `LiquidLogicLabs/git-action-docker-metadata@v6` and `git-action-docker-test@v2` at mutable major tags. That is a binding rule, and not challenged here.
  - S02-002's ADR scope (D2 residual) records the PAT's account-wide reach. It does not record that the token sits beside mutable-ref steps that can read it. RT-2 raised exactly that pattern ("ref-pinned `LiquidLogicLabs/*` actions after login") for the workstation run, and it now applies to the CI job with a wider credential.
  - Every new token has an expiry (D2/D3), but nothing records the expiry dates or a rotation step. The first sign of an expired token is a 403 during a release.
- **Evidence:**
  - `.github/workflows/release.yaml:432-446` (three `docker/login-action` steps);
  - `release.yaml:459` (`git-action-docker-metadata@v6` after them);
  - `release.yaml:505` (`git-action-docker-test@v2`);
  - CI spine `ARCHITECTURE-SPINE.md:219-222`, `:262`;
  - `E015-S02-002.md:34` (RT-2 context);
  - `E015-S02-002.md:49`, `:163-166`.
- **Recommended fix:**
  - In the S02-002 ADR, record the co-residence as an accepted residual tied to the LiquidLogicLabs major-tag rule, with a revisit condition (for example, `docker logout` of all registries before `git-action-docker-test`, since every image is publicly pullable, as a later workflow story).
  - Add to the walkthrough's per-release checklist (AD-12): each `PUBLISH_*` token's expiry date (dates only, never values) and the rotation procedure.
  - File the logout change as a Low backlog item rather than widening S02-002's non-goal "no workflow change".

### AG-6 — MINOR — E015-S01-001 / E015-S01-002 (cross-story: settings trust and the image-level proof)

- **Principle:** global rule 4 (a guard proves its rule; check its reach); Core §4.
- **Finding:**
  - S01-002 adds `validatekeys` as `any-source` (AC 16a). The classification guard proves only that a class exists for every key; the image-level boundary test (S01-001 AC 7) exercises only the two `environment-only-when-root` keys.
  - Nothing at image level checks that a setting classed `any-source` cannot change what root executes or where root writes. AG-1 is the concrete case: no test failed for the `filespec` path.
  - The `any-source` justifications ("no privilege effect", "read only") are prose, and the AD-2 table restates them without a check (global rule 3).
- **Evidence:**
  - `E015-S01-001.md:58`, `:68-70` (guards);
  - `E015-S01-001.md:71-75` (image test, two keys only);
  - `E015-S01-002.md:117` (AC 16a);
  - product spine `ARCHITECTURE-SPINE.md:164-168`.
- **Recommended fix:**
  - State in AD-2 and in the S01-001 ADR, where the rule lives, that the `any-source` rationales are reviewed claims, not mechanically checked. Name the review trigger: a new key, or a change to how an existing key is used in `certificate_exporter.py`/`docker.py`/`notify.py`.
  - Add the AG-1 image case so that at least the path-shaped `any-source` keys (`filespec`, `datapath`) have an executable proof.

## Per-principle walkthrough

| Principle | Result |
|---|---|
| Core §1 Separation of concerns | PASS. New logic stays inside its owning module: trust classes in `settings.py`, the change test in `certificate_exporter.py`, the handler in `AcmeCertificateFileHandler`, the legacy table in `legacy_settings.py`. No new cross-layer import: `settings` → `legacy_settings` and `app` → `settings.sourceOf` both respect the `libs-layers`/`entrypoint-on-top` contracts in `pyproject.toml:101-121`. |
| Core §2 Reuse over copy-paste | PASS. Shared pieces are reused rather than copied: `_history_names` is generalised, `__queuePath` is extracted, `_serialize_pkcs12` is shared by `build_pkcs12`, and `_require_full_history` is factored out. The copied `clone`/`actrun`/`dig` shell shorthands across the S02 stories are verification text, and AD-4 bars them from being repository code. Accepted. |
| Core §3 Design by contract | AG-1, AG-3. Elsewhere contracts are explicit: `_pfx_state` never raises, `sourceOf` classes are pinned by a test, and `on_moved` re-tests `dest_path`. |
| Core §4 Testability | AG-4, AG-6. Fail-first and planted scope attacks are present in every story. `geteuid` is monkeypatched, so the root tests run under any uid. |
| Core §5 Brevity/readability | PASS. |
| Core §6 Comments | PASS. Stale comments are corrected in scope: `certificate_exporter.py:271-276`, the three `.pre-commit-config.yaml` comments, and the `[tool.mypy]` comment. The residual-race comment in S01-003 explains why. |
| Core §7 Dependency selection | AG-2, AG-5. No new runtime dependency. S02-003 moves import-linter, mypy and the stubs into the hashed, audited lock. |
| Core §8 GA over preview | PASS. cryptography 50.0.2, watchdog `^6` (7.x excluded on purpose, with the risk recorded), pre-commit 3.8.0, base image digest-pinned. |
| Core §9 Logging | PASS. One logger (`globalLogger`). Pass-scoped lines keep `correlation_id`, and start-up lines are documented as outside a pass. New lines carry no values: the hook, the withheld values and the passphrase are never logged; paths go through `sanitize_for_log`. |
| Core §10 Documentation | PASS. Each story updates the operational, developer and upgrade docs and the §6 ADR index. The product spine diagram (`:610`) reflects `/config` as `PUID`-owned. |
| Python overlay | PASS (Poetry and lock; mypy and ruff gate). AG-2 concerns how ruff is used, not the toolchain choice. |
| GitHub Actions overlay | AG-5. Pinning follows AD-5 (third-party actions SHA-pinned, LiquidLogicLabs at major tags by binding rule). Permissions are `contents: read`. The release environment is restricted to `v*` tags (`docs/ci/pipeline-walkthrough.md:442-459`; S02-004 row 5). |
| Docker overlay | PASS. No Dockerfile or s6 change in E015. LinuxServer init untouched (S01-001 AC 8, row 5). |
| Shell overlay | PASS for the scope reviewed. The story rows use `&&` chains, `pipefail` where they pipe, and `mktemp`. The V-06 fixes hold. |
| ADR coverage | PASS with AG-2/AG-5 additions. There is a new ADR for each of S01-001, S01-002 and S02-002; ADR-0030, ADR-0039, ADR-0042 and ADR-0043 are amended; no ADR is needed for S01-003, S01-004 or S02-001 (spine AD-11/AD-6/AD-18 carry them). |
| Cross-story consistency | Mostly PASS:<br>• S01-001 → S01-002 → S01-003/S01-004 are serialised on `settings.py` and `certificate_exporter.py`.<br>• The start-up line order matches spine AD-3 (`:218-221`).<br>• S02-001 → S02-002/S02-003 are serialised on `.pre-commit-config.yaml`, with the walkthrough sections split.<br>• S02-003's `language:` guard admits S02-001's pygrep hook.<br>• The S02-004 post-checks (18, 18a, 19a) match the S01-001/S01-002 contracts (`cert.pfx.fingerprint.json`, `Post-export command:` line).<br>The one gap is AG-6. |
| PRD / spine conformance | AG-1 is a spec-gap shared by PRD FR-18, spine AD-2 and MD-21. Otherwise the stories match FR-2, FR-6, FR-10, FR-12, FR-16 … FR-19, NFR-2, NFR-4, NFR-5, NFR-9, NFR-10 and CI AD-3, AD-9 … AD-13, AD-16 and AD-18. |
| Root-mode security | AG-1, AG-6. The hook/output-path closure itself is sound: removing the file pair rather than calling `set()` keeps the precedence native to confuse, `.env` smuggling is handled, and the RT-1 replay runs on the real image. |
| Release token model | AG-5. Otherwise sound: forge-only tokens, a scoped Gitea token proven non-admin (S02-002 row 7), no repository-level `PUBLISH_*`, the `v*`-only release environment, `just act` hardened with planted sources, and a digest check that can fail. |

## Gate

- **BLOCKER:** none.
- **MAJOR (AG-1, AG-2):** resolve them in E015-S01-001 before it starts, or record them as accepted in the S01-001 ADR. AG-1 needs a maintainer re-decision of MD-21 for `filespec`/`datapath`.
- **MINOR (AG-3 … AG-6):** defer to the backlog, or fold them into the owning story at dev time. AG-3 and AG-4 are cheapest to fix in S01-002 itself.

## Recommended ADR content

- **S01-001 ADR** (`root-takes-hook-and-output-path-from-environment-only`):
  - the `filespec`/`datapath` decision (AG-1);
  - the evaluation of ruff `S6xx` against the AST scan (AG-2);
  - the statement that the `any-source` rationales are reviewed, not checked (AG-6).
- **S02-002 ADR** (`release-publication-one-forge-run`):
  - the co-residence of registry credentials with mutable-ref steps, and the token-expiry tracking (AG-5).

Sections read:
- `.claude/skills/l3io-arch-review/SKILL.md`, `references/standards-core.md` (all), `references/review-report.md` (all), `references/standards-python.md`, `standards-github-actions.md`, `standards-docker.md`, `standards-shell.md` (all).
- `_bmad-output/implementation-artifacts/epic-015/maintainer-decisions.md:1-185`; `execution-notes.md:1-217`; `plan-review/validation-2026-10-12.md:1-204`.
- Stories (complete): `sprint-01/stories/E015-S01-001.md:1-296`, `E015-S01-002.md:1-397`, `E015-S01-003.md:1-219`, `E015-S01-004.md:1-223`; `sprint-02/stories/E015-S02-001.md:1-207`, `E015-S02-002.md:1-278`, `E015-S02-003.md:1-231`, `E015-S02-004.md:1-348`.
- Product spine `architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md:129-130, 155-175, 214-224, 653-694` (grep for trust classes, start-up lines, Deferred).
- CI spine `architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md:110-140, 183-330` (AD-3 … AD-6, AD-9 … AD-18).
- PRD `prd.md:41-42, 77, 79, 85-86, 93, 96, 101` (FR-10, FR-12, FR-18, FR-19, NFR-2, NFR-5, NFR-10).
- Research brief `research-2026-10-12-release-0.3.1.md` headings, `:23-69` (§1, venv/lsiown facts), `:50`.
- Spec index `spec-index.md` (E015 grep only).
- Source spot-checks:
  - `src/traefik_certificate_exporter/libs/certificate_exporter.py:1165-1195`;
  - `libs/post_export.py:60-120`;
  - `libs/settings.py` (`fileSpec` grep, `:401`);
  - `pyproject.toml:16-24, 92-121` (dependencies, import-linter; no `[tool.ruff]`);
  - `docker/Dockerfile:123-127`;
  - `.github/workflows/*.yaml` (`environment:` grep), `release.yaml:432-505`;
  - `.pre-commit-config.yaml:1-17, 196-209`;
  - `docs/ci/pipeline-walkthrough.md:430-470`;
  - `docs/adr/0039-publish-credentials-in-forge-environments.md:60-80`.

## Re-validation

- **Date:** 2026-10-12.
- **Scope, as instructed:**
  - `docs/adr/0049-root-mode-trust-covers-hook-output-and-store-location.md`;
  - `docs/adr/0050-spawn-site-guard-uses-ruff-banned-api.md`;
  - `git diff -- _bmad-output/ docs/architecture.md`: `maintainer-decisions.md`, E015-S01-001, E015-S01-002, E015-S02-002, `state/issues.yaml`, the §6 rows;
  - for the AR-1 and AR-2 definitions only, `arch-gate-review-architect.md:178-205`.
- **Maintainer approval of the AG-1 fix (2026-10-12):**
  - `filespec` is a file-name glob in every mode;
  - `datapath` comes from environment or CLI only when running as root;
  - `/data:ro` is required in both modes.
- **Local checks run (throwaway directories outside the repository):**
  - **TID251 probe.** ruff 0.16.5 (the pre-commit `ruff-pre-commit` environment, `ruff --version` = 0.16.5) with `extend-select = ["TID251"]` and a banned-api table naming `subprocess`, `pty`, `os.posix_spawn`, `os.system` and `asyncio.create_subprocess_exec`.
    - It reported `TID251 os.posix_spawn is banned` at the call, and `TID251 subprocess is banned` at `import subprocess` in a file whose only spawn is the literal-argument `subprocess.run(["/bin/sh", "-c", "id"], check=False)`.
    - It also reported `from subprocess import run as r`, the attribute reference `f = os.system`, and `asyncio.create_subprocess_exec`. Exit code 1.
    - A file with `import subprocess  # noqa: TID251` followed by `subprocess.run(argv)` passed (exit code 0).
    - The output format matches the greps in S01-001 Verification row 14.
  - **Glob probe.** `glob` cannot synthesise `..`: `[.][.]/…`, `.[.]/…` and `??/…` matched nothing. `../config/*.json` and an absolute path both escaped `datapath`. This confirms that a lexical check of the pattern text (ADR-0049 Decision 5) is sufficient, and that every escaping form contains `/`, which the check rejects.

| ID | Result | Evidence |
|---|---|---|
| AG-1 | RESOLVED | **ADR-0049:**<br>• Decision 2 classes `datapath` `environment-only-when-root`.<br>• Decision 5 validates `filespec` at load in every mode and from every source. It rejects an empty value, `/` or `\`, `.` or `..`, an absolute path and a drive, and falls back to the packaged `*.json`. The value is validated in one place, so the export pass, the watcher and the init resolver all read the checked value.<br>• Decision 7 requires `/data:ro` in both modes.<br>**S01-001:**<br>• AC 1 and AC 1a carry this.<br>• AC 7 (v) adds the forged-store image replay.<br>• Init-resolver test (row 13).<br>• Release-note, help-text and README rows (15).<br>**Records:** MD-21 is re-decided and recorded, and the spine is cited as updated. The class rule now covers "trusts as the source of what it writes". |
| AG-2 | RESOLVED | **ADR-0050** chooses ruff `TID251` banned-api, records the rejected `S602`–`S606` and the rejected `ast` scan, and states its coverage limit.<br>The hand-kept `os` list is checked against `dir(os)`/`dir(asyncio)`, with a planted gap. S01-001 AC 5 and row 14 prove it against the tool, and the probe above confirms the two planted forms fail. |
| AG-3 | RESOLVED | S01-002 D4 and the contract table split `_passphrase_matches` (uncached, validates the record) from `@lru_cache _scrypt_verifies(passphrase, salt, n, r, p, digest)`, which takes only hashable arguments. A new test checks it: `test_passphrase_check_is_cached_on_hashable_values_only`. |
| AG-4 | RESOLVED | S01-002 AC 11 and AC 12 gate on load counts. Wall time is checked only as a same-process relative bound (< ¼ and < ½), and absolute times are recorded in the notes (rows 2 and 14). |
| AG-5 | RESOLVED | The S02-002 ADR (AC 1, row 1) records the co-residence of registry credentials with LiquidLogicLabs steps at major tags as an accepted residual, with a revisit condition, and records token-expiry tracking. The walkthrough checklist gains expiry dates and a rotation procedure (AC 4, row 6). BL-E015-005 (Low) is filed for a `docker logout` before `git-action-docker-test`. |
| AG-6 | RESOLVED | ADR-0049 "What is and is not mechanically checked" states that the `any-source` rationales are reviewed claims and names the review trigger. S01-001 AC 1 adds the same block comment above `ROOT_SETTING_TRUST`, and S01-002 AC 16a uses the "availability only" wording. The forged-store replay gives the path-shaped `any-source` key an executable proof. |
| AR-1 | RESOLVED | ADR-0049 lists AR-1 as a residual risk. S01-001 AC 9 documents `/data:ro` for both modes in `operational.md` and `docker/README.md`, with a grep in row 15. BL-E015-004 (Low) is filed for the root-mode writable-store note, an s6 change. |
| AR-2 | RESOLVED | The contract stays in `settings.py`, with no `certificate_exporter.py` change (S01-001 Interface contracts). An every-mode release note and an `upgrading.md` bullet were added. The `--file-spec` help text and `README.md` are updated. The `filespec` class comment reads "validated as a file-name glob at load". Rejected-form unit tests, the root plus file-`datapath` test and AC 7 (v) are all present. |

**New defect:**

- **N-1 — MINOR — ADR-0050 (Decision 2, Coverage limit), E015-S01-001 (AC 5).**
  - **Finding:** For a module ban (`subprocess`, `pty`, `multiprocessing`), ruff 0.16.5 reports only the import. It does not report each use. The probe confirmed this: `subprocess.run(...)` after the import produced no finding of its own. So the `# noqa: TID251` on `post_export.py`'s `import subprocess` line exempts **every** `subprocess.*` call in that file, not only `_run`.
  - **What overstates coverage:**
    - ADR-0050's "Any other banned name in that file is still reported" is true only for the banned `os.*`/`asyncio.*` names.
    - The guard is file-level, where the first plan was site-level (`_run`).
  - **Recommended fix:** add one coverage-limit line to ADR-0050 and the `pyproject.toml` comment: "the allowed file may make further `subprocess` calls unreported; `libs/post_export.py` is reviewed as a whole". Alternatively, keep `post_export.py` limited to `_run` by review. No code change is needed.

## Consolidated gate outcome (orchestrator, 2026-10-12)

Reviewers run: l3io-arch-review, then (escalated) bmad-agent-architect.

| ID | Consolidated | Disposition |
|---|---|---|
| AG-1 | MAJOR confirmed (both) | Maintainer approved the fix; ADR-0049 (root-mode trust incl. store location); PRD/spine/S01-001 updated |
| AG-2 | MAJOR single-source (architect: MINOR) | ADR-0050 (ruff TID251 banned-api) |
| AG-3..AG-6 | MINOR confirmed | Folded into S01-001/S01-002/S02-002; BL-E015-005 |
| AR-1, AR-2 | MINOR single-source | Folded into ADR-0049 and S01-001; BL-E015-004 |
| N-1 | MINOR (re-validation) | ADR-0050 and S01-001 coverage-limit wording corrected by the orchestrator |

Re-validation: 8/8 resolved, no blocking findings. Gate passed.
