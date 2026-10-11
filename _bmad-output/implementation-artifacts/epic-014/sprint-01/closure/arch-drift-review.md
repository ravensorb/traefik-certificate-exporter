# Architectural drift review — E014 sprint 01

- **Mode:** l3io-arch-review Mode B (architectural review), headless
- **Date:** 2026-10-11
- **Subject:** the uncommitted sprint diff `/tmp/e014-s01-review/sprint-diff.patch` (52 files; `poetry.lock` is excluded from the patch and was checked separately, it is consistent with `pyproject.toml`) and the stories `E014-S01-001` … `E014-S01-010`
- **Standards loaded:** `standards-core.md`, plus the Python, Docker, Shell and GitHub Actions overlays
- **Out of scope (known):** BL-E014-017 (the image's environment default `WATCHFORCHANGES=true` outranks the config file)

## Executive summary

The sprint fits the recorded architecture closely. ADR-0040 to ADR-0045 are implemented as written, with three exceptions:

- One shared path helper (`_artifact_paths`) and a published-by-assignment artifact index: ADR-0040.
- Build, compare, then write, with the files on disk as the only state: ADR-0043.
- An s6 run mode resolved by the installed package: ADR-0044.
- Restart only on change, using the artifact mtime against `StartedAt`, with deferred rather than dropped restarts: ADR-0045.
- An audit scope derived from the lock and from the bootstrap directory: ADR-0042.

The review found **0 BLOCKER, 2 MAJOR and 7 MINOR** findings:

- **SD-01-1 (MAJOR):** the new settings-name check adds import cycles, which the spine's AD-13 forbids. They are hidden behind two function-local imports.
- **SD-01-2 (MAJOR):** the deferred-restart path never checks that the container is still running. A labeled container that an operator stops inside the 300 s window is started again by the trailing `restart()`. This contradicts ADR-0045 §2 and `docs/operational.md`.

**Most important action:** add a running-state check to `DockerManager._deferredRestart` (SD-01-2).

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| SD-01-1 | MAJOR | Core §1 Separation of concerns (circular dependencies); spine AD-13 "Module layering as built" (Prevents: import cycles); Global rule 3 | `src/traefik_certificate_exporter/libs/settings.py:367`, `libs/legacy_settings.py:25,314`, `app.py:16` | The diff introduces two import cycles. **Cycle 1:** `settings → legacy_settings → cli_args → docker → settings`. The comment at `settings.py:364-366` admits it. **Cycle 2:** `legacy_settings → certificate_exporter → settings → legacy_settings`. Both cycles are broken only by function-local imports. In addition, `app.py` and `legacy_settings.py` both import the private helper `certificate_exporter._sanitize_for_log`. A settings-layer module therefore reaches into the domain module for a logging utility, and `legacy_settings` imports `cli_args` (and through it the Docker SDK) only to get the constant `LOG_LEVEL_ENV`. AD-13 is not enforced mechanically, so nothing caught any of this. No ADR covers it. | (1) Move `_sanitize_for_log` into `logging_utils.py` as public `sanitize_for_log`. That module is a leaf under AD-13. Re-export the old name from `certificate_exporter` if tests need it. (2) Move `LOG_LEVEL_ENV`, `LOG_LEVEL_CHOICES` and `DEFAULT_LOG_LEVEL` to `logging_utils.py`, next to the other `LOGGING_*_ENV` constants, and have `cli_args` import them. (3) Make `from .legacy_settings import check_setting_names` a top-level import in `settings.py`, and delete both lazy imports. (4) Add the mechanical AD-13 guard in the same change, using a maintained tool: an `import-linter` contract (layers plus `independence`, with no cycles) as a `repo: local` pre-commit hook. Then plant a cycle to show that the guard fails. |
| SD-01-2 | MAJOR | Core §3 Design by contract; ADR-0045 §2 (candidate set = *running* labeled containers) and §8 (fire-time re-check); `docs/operational.md:122` ("Stopped containers are not restarted") | `src/traefik_certificate_exporter/libs/docker.py:427-476` (`_deferredRestart`) | `restartLabeledContainers` lists running containers only. `_deferredRestart`, by contrast, re-fetches with `client.containers.get(id)` and re-checks the label, the mtime rule and the floor, but never the container's state. `StartedAt` keeps its old value after a stop, so the rule still holds. Docker's restart endpoint starts a stopped container, so the following happens. A container is restarted, a second rotation lands within 300 s, a trailing restart is armed, and the operator stops the container for maintenance. When the timer fires, the exporter starts that container over the host-root-equivalent socket. The candidate-set contract from ADR-0045 §2 is applied at arming time but dropped at fire time. No test covers a container that stops between arming and firing. | Before the rule re-check in `_deferredRestart`, skip with INFO `Skipping deferred restart of container <id>: not running` unless `container.status == "running"` (or `attrs["State"]["Running"]` is true). The trailing restart then fires only for a container that is still running. A stopped container loads the current files when it next starts, which is the documented behaviour. Add a `tests/libs/test_docker.py` case where the fake container's status is `exited` at fire time and assert that `restart()` is not called. Add "running at fire time" to the fire-time conditions in ADR-0045 §8 (route it through S02-003). |
| SD-01-3 | MINOR | Core §10 Docs that contradict the code | `docs/adr/0040-exported-artifact-paths-from-one-shared-helper.md` Decision §2, §4 | **§2** names the writer `__exportCertificate`. The code's method is `__exportDomain` (`certificate_exporter.py:914`), and spine AD-8's "Binds" line uses the same stale name. **§4** says domains "failing to build are not recorded". The code instead carries a failed certificate's or failed resolver's previous paths forward (`__recordArtifacts` `keepNames`/`keepResolvers`, `certificate_exporter.py:722-745`), as ADR-0045 §3 (RV-1) later decided. ADR-0040 carries no "Amended by ADR-0045" marker. | Add `Amended by: ADR-0045 (§3: a certificate or resolver whose rebuild fails keeps its previous recorded paths)` to ADR-0040, and correct the method name there and in the spine AD-8 Binds line (S02-003 routing). |
| SD-01-4 | MINOR | Core §5 Brevity (dead code) | `src/traefik_certificate_exporter/libs/certificate_exporter.py:1208-1244` (`PemToPfxConverter.export_to_pkcs12`), `:261` (`_atomic_write_text`); `:1165` | After the build-first rewrite, `export_to_pkcs12` has no caller in `src/` or `tests/`. It was rewritten anyway (37 lines, "kept for external callers") although the package declares no library API. `_atomic_write_text` is only reached from tests. `build_pkcs12` also loads the private key from PEM a second time, after `__exportDomain` has already loaded it. | Delete `export_to_pkcs12`. Point the tests at `_atomic_write` directly, or keep `_atomic_write_text` only if it is part of a test seam. Pass the already-loaded key into `build_pkcs12`. |
| SD-01-5 | MINOR | Core §2 Reuse / Global rule 4 (single source) | `src/traefik_certificate_exporter/app.py:128` | `setup_logging(env_key="TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE")` repeats the literal, although this diff adds `logging_utils.LOGGING_CFGFILE_ENV` as the one definition. The env-name scan in `tests/test_settings_surface.py` reads literals, so the duplicate passes, but it can drift from the constant. | Use `LOGGING_CFGFILE_ENV`, or drop the argument because the default already equals it. |
| SD-01-6 | MINOR | Core §3 Design by contract (types as contracts); Python overlay (type-checked) | `src/traefik_certificate_exporter/libs/docker.py:169,194,302,314,324` | `_reserveRestart` and `_releaseRestart` declare no return type. The `(allowed, reason, previousAt)` tuple is untyped, and three call sites carry a bare `# type: ignore` with no error code. That hides whatever mypy objects to in the cooldown bookkeeping, which is the code the restart floor depends on. | Annotate `_reserveRestart -> tuple[bool, str \| None, float \| None]` and `_releaseRestart -> None`. Remove the ignores, or narrow each one to its error code with a reason. |
| SD-01-7 | MINOR | Shell overlay (strict mode) | `docker/root/etc/s6-overlay/s6-rc.d/svc-traefik-certificate-exporter/run:1-51` | The run script was largely rewritten in this diff, but it still has no strict-mode line. Its sibling `finish` sets `set -uo pipefail` and records why `-e` is left out. `run` only reads state files and `exec`s, so the risk is low. | Add `set -uo pipefail` after the shebang, matching `finish`. Leave out `-e`, for the same reason `finish` gives. |
| SD-01-8 | MINOR | Core §10 Diagrams where a flow is non-trivial | `docs/adr/0045-restart-policy-only-on-change-defer-not-drop.md`, `docs/operational.md` §restart runbook | The restart path now spans the export pass, the artifact index, the mtime/`StartedAt` rule, the cooldown reservation, a coalesced daemon timer, the fire-time re-checks and shutdown cancellation, across three threads. No document has a sequence diagram for it. | Add a Mermaid sequence diagram (pass → `artifactMtime` → rule → reserve or defer → timer fire → re-check → restart or release) to ADR-0045 or to `docs/architecture.md` (S02-003). |
| SD-01-9 | MINOR | `docs/guidelines.md` §5 (same validation on every input mode); Core decision hook (record departures as ADRs) | `src/traefik_certificate_exporter/app.py:79-102`; `libs/legacy_settings.py:275-309`; `libs/cli_args.py:221-229` | The same mistake is handled differently depending on where it is made. An invalid `-ll` value or an unknown flag exits 2. An invalid `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL` falls back to INFO with a WARNING, and an unknown `TRAEFIK_CERTIFICATE_EXPORTER_*` env name gets a WARNING only. The reason is sound (exiting would put a watch-mode container into an s6 respawn loop), and spine AD-3 and AD-6 state the behaviour. However, the departure from guidelines §5 is not recorded as an ADR. | Record a short ADR, "Environment-sourced misconfiguration warns; the CLI fails", naming guidelines §5 as the principle in tension and the s6 respawn loop as the reason. Cite it from AD-3 and AD-6 (S02-003). |

## Per-principle walkthrough

**Core**
- §1 Separation of concerns: **SD-01-1**. Otherwise PASS. The adapters (`docker`, `notify`, `post_export`) do not import `certificate_exporter`. Path layout lives in one pure helper (`_artifact_paths`), as ADR-0040 requires.
- §2 Reuse over copy-paste: **SD-01-5**. Otherwise PASS:
  - One path rule (ADR-0040).
  - One suggestion helper (`suggest.nearest_name`, shared by the CLI and env paths).
  - One atomic writer for PEM and PFX.
  - The `write_atomically` helper in the init heredoc is coincidental similarity (a tmpfs state file), not duplication.
- §3 Design by contract: **SD-01-2** and **SD-01-6**. Otherwise PASS:
  - `exportCertificatesForFile -> list[str]`, never `None`.
  - Strict base64.
  - The change test is explicit and stated in ADR-0043.
  - `StartedAt` parsing is total (`None` on any failure).
- §4 Testability: PASS.
  - `_create_client` is the single client seam.
  - `artifactMtime` is injected as a callable.
  - The legacy check takes `environ` and the logger as parameters.
  - The debounce timing is named.
  - Opt-in integration tests are owned by the contract-changing story (ADR-0041). For example, `tests/libs/test_docker_engine.py:103` uses the new `restartLabeledContainers(artifactMtime)` signature.
- §5 Brevity and readability: **SD-01-4**.
- §6 Comments: PASS. Provenance comments follow the recorded deviation in `docs/guidelines.md` §11: the invariant comes first, then the defect or ADR. No new history-only comments were found in the diff.
- §7 Dependency selection: PASS.
  - `python-dateutil` is added for one call and justified in ADR-0045 §12 (BSD/Apache-2.0, one transitive dependency).
  - The unused `requests`, `docker-pycreds` and `expandvars` are removed.
  - `pyyaml` moves to main because `src/` imports it. The `deptry` hook now enforces declared-against-imported dependencies.
- §8 GA over alpha/beta: PASS. Every dependency, hook and the base image is a GA release.
- §9 Logging and correlation: PASS.
  - The correlation id is handed explicitly to deferred-restart timers.
  - `postexportcommand` is a declared secret, and hook lines name only `argv[0]`.
  - Declared-secret lists are redacted per element.
  - Untrusted names pass through `_sanitize_for_log`.
  - The hook's stderr is still logged on failure, a limit ADR-0045 §14 states.
- §10 Documentation: **SD-01-3**, **SD-01-8** and **SD-01-9**. Otherwise PASS. `docs/operational.md` has run-once, restart and hook runbooks, and `docker/README.md` has a Run once section. The ADRs carry Amended-by markers (0014, 0023, 0024, 0030).

**Python overlay**
- Packaging is Poetry (ADR-0001), and `uv.lock` is git-ignored. The lock is committed, `poetry check --lock` is consistent, and CI uses `poetry sync --all-groups`: PASS.
- `requires-python` is bounded at `>=3.10,<3.15`: PASS.
- Type-checked: **SD-01-6**.
- Structured logging with a correlation id, and no `print`: PASS.
- Dependencies are GA and checked: PASS. `pip-audit` covers every lock group and every bootstrap file (ADR-0042), and `deptry` covers declared against imported.

**Docker overlay**
- The base image is pinned with both a tag and a digest (`3.24@sha256:d2deff…`): PASS.
- Secrets, multi-stage build, SBOM/provenance and `.dockerignore` are not touched by this diff.
- Non-root runtime follows ADR-0030's conditional privilege drop. This sprint does not change it.
- Signals and exec form: PASS. The s6 `run` script `exec`s the exporter, and `finish` `exec`s `halt`.

**Shell overlay**
- Strict mode: **SD-01-7**. `finish` documents why it leaves out `-e`.
- Quoting: PASS. Every expansion in `run` and `finish` is quoted, and `[[ ]]` is used.
- ShellCheck in CI: PASS. A SHA-frozen hook scoped by directory (`^docker/root/`) lints these scripts, and the one suppression carries its reason.
- No secret appears in argv: PASS.

**GitHub Actions overlay**
- `build.yaml` changes only its install command. The unhashed `pip install "poetry==2.4.2"` is ADR-0042's stated E014-S02-001 work, not this sprint's.
- The `pip-audit-bootstrap` `bash -c` loop is justified in ADR-0042 (hook configuration, no script file).
- PASS for this sprint.

**Spine and ADR alignment** (AD-3, AD-6 to AD-13; ADR-0040 to ADR-0045)
- AD-3, AD-6, AD-7, AD-8, AD-9, AD-10, AD-11 and AD-12: implemented as stated, apart from the findings above (AD-10/ADR-0045 §2: SD-01-2).
- AD-13: **SD-01-1**.
- ADR-0040: SD-01-3 (stale text).
- ADR-0041: honoured.
- ADR-0042: honoured. The hooks, `poetry sync --all-groups` and the comments state the covered and uncovered scope.
- ADR-0043: honoured, including decision 6 (per-resolver isolation, the expiry-based owner).
- ADR-0044: honoured. The `s6-no-raw-settings-env` pygrep guard ships with the rule.
- ADR-0045: SD-01-2. Every other decision is honoured: the rule, the slack, `StartedAt` handling, coalescing, the generation-guarded cancel, dry run, `use_context=False`, only-on-change hooks and notifications, and redaction.

**Spec alignment:** every hunk is covered by an epic ADR, an older ADR or a spine section, so no section of `spec-index.md` was opened. `spec-align sections` resolved no pointers for these stories.

## Gate

- **BLOCKER:** none.
- **MAJOR (resolve or record an accepted ADR before sign-off):**
  - SD-01-1: no existing ADR justifies it. AD-13 forbids cycles.
  - SD-01-2: no existing ADR justifies it. ADR-0045 §2 requires running containers only.
- **MINOR:** SD-01-3 to SD-01-9 defer to the backlog.

## Recommended ADRs

- **"Environment-sourced misconfiguration warns; the CLI fails"** (SD-01-9). It records the departure from guidelines §5 for `LOGGING_LEVEL` and for unknown `TRAEFIK_CERTIFICATE_EXPORTER_*` names.
- **ADR-0045 amendment** (SD-01-2, S02-003 routing). Add "the container is still running" to the fire-time conditions in §8.
- **AD-13 enforcement** (SD-01-1). If `import-linter` is adopted, record it as a dependency decision under Core §7 (maintained, BSD-2), or include it in the S02-003 spine amendment.

Blocker: 0, Major: 2, Minor: 7

Sections read:
- `.claude/skills/l3io-arch-review/SKILL.md` (as loaded by the skill), `references/review-report.md` 1-41, `references/standards-core.md` 1-169, `references/standards-python.md` 1-43, `references/standards-docker.md` 1-66, `references/standards-shell.md` 1-87, `references/standards-github-actions.md` 1-49
- `/tmp/e014-s01-review/sprint-diff.patch`: all per-file hunks, split by file. Read in full: source (`app.py`, `config_default.yaml`, `libs/settings.py`, `libs/cli_args.py`, `libs/suggest.py`, `libs/post_export.py`, `libs/notify.py`, `libs/logging_utils.py`), s6 scripts, `Dockerfile`, `pyproject.toml`, `justfile`, `build.yaml`, `.gitignore`, `.pre-commit-config.yaml`, ADR 0014/0023/0024/0030 hunks, `docs/ci/pipeline-walkthrough.md`, `docs/developer.md`, `docker-compose.yml`, `config.yaml.sample`. Added lines only: `docs/operational.md`, `README.md`, `docker/README.md`. Test files: line counts plus a targeted grep only.
- `/tmp/e014-s01-review/adrs.txt`, `spec-sections.txt`, `poetry-lock-stat.txt` (whole)
- `src/traefik_certificate_exporter/libs/certificate_exporter.py` 1-1625 (working tree)
- `src/traefik_certificate_exporter/libs/docker.py` 1-513 (working tree)
- `src/traefik_certificate_exporter/libs/legacy_settings.py` 1-372 (working tree)
- `docs/adr/0040-…md` 1-130, `0041-…md` 1-67, `0042-…md` 1-159, `0043-…md` 1-145, `0044-…md` 1-99, `0045-…md` 1-191
- `ARCHITECTURE-SPINE.md` (product, 2026-08-30): heading index; 114-135 (AD-3); 157-307 (AD-6 to AD-13, Consistency Conventions); 328-366 (Structural Seed)
- `docs/guidelines.md`: heading index; 26-59 (§3 Logging, §4, §5 Configuration); 163-200 (§10, §11)
- Stories: the `## Acceptance Criteria` sections of `E014-S01-001` to `E014-S01-010`, plus a heading index of `E014-S01-001`. `E014-S01-006.md`: grep hit at line 291 only.
- Targeted greps: `tests/libs/test_docker_engine.py`, `tests/libs/test_docker.py`, `docs/operational.md`, the in-package import graph of `src/`, `app.py:128`, `.pre-commit-config.yaml`/`pyproject.toml` (searched for an import-linter), the s6 `run` script heads, `poetry.lock` (dependency presence)
