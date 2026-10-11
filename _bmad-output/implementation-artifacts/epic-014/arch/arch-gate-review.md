# E014 architecture gate review: "0.3.0 release readiness"

- **Reviewer:** l3io-arch-review (Mode B, architectural review of an existing design)
- **Date:** 2026-10-11
- **Scope:** the 17 planned E014 stories, reviewed before implementation. Code lagging the spines is expected and is not a finding unless no story closes the gap.
- **Work type:** MIXED (code + CI config + docs)
- **Standards applied:** `standards-core.md` §1–10, plus the Python, GitHub Actions and Docker overlays, and the user's global rules 1–4 (`~/.claude/CLAUDE.md`).
- **Inputs:**
  - Stories: `epic-014/sprint-01/stories/E014-S01-001..010.md`, `epic-014/sprint-02/stories/E014-S02-001..007.md`
  - `epic-014/execution-notes.md`
  - `epic-014/plan-review/SUMMARY.md`, read only so that resolved items are not raised again
  - PRD `prd-traefik-certificate-exporter-2026-08-30/prd.md`
  - Product spine `architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md`
  - CI/CD spine `architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`
  - `spec/spec-index.md`
  - Spot checks of individual source files, to test specific claims the stories make: `libs/certificate_exporter.py`, `libs/docker.py`, `libs/settings.py`, `config_default.yaml`, `docker/Dockerfile`, the s6 init `run` script, `docker/root/defaults/config/config.yaml.sample`, `justfile` and `build.yaml`.

## Executive summary

The E014 story set is unusually well elaborated. Each story carries:
- explicit contracts;
- a Verification table that is a real definition of done;
- fail-first evidence;
- scope-attack probes;
- routing of spine and ADR text to S02-003.

Global rule 1 (maintained libraries over hand-rolled code) is honoured throughout: `deptry`, `pip-audit`, `dateutil`, `x509.load_pem_x509_certificates`, ShellCheck, and a retry action preferred over a loop.

**Totals: 1 BLOCKER, 2 MAJOR, 9 MINOR.**

**The most important action:** fix the E014-S01-006 `artifactMtime(domain)` contract (AG-1). It ignores the per-resolver output directory. That directory is the **default** layout: `resolverinpathname: true` in `config_default.yaml` and in both sample configs. As written, the restart rule would find no artifacts under the default configuration, and FR-8/FR-15 restarts would never fire.

The two MAJORs are:
- **AG-2:** the required 0.3.0 restart release evidence is inconsistent across S01-001, S01-006 and S02-005.
- **AG-3:** the `pip-audit` gate does not cover the new optional `publish` group, which is the one that runs beside live tokens.

## Findings table

| # | Severity | Principle | Story | Location | Finding (short) |
|---|---|---|---|---|---|
| AG-1 | BLOCKER | Core §3 Design by contract; PRD FR-8/FR-15 | E014-S01-006 | `E014-S01-006.md:249` | `artifactMtime(domain)` cannot locate artifacts under the default `resolverinpathname: true` layout |
| AG-2 | MAJOR | Core §4 Testability; cross-story consistency; NFR-5 | S01-001, S01-006, S02-005 | `E014-S01-001.md:76-92`, `E014-S01-006.md:240,354-367`, `E014-S02-005.md:78-79,257` | S01-006 breaks S01-001's required integration test and no story owns the repair; S02-005 names the wrong test as FR-15 evidence |
| AG-3 | MAJOR | Global rule 4 (guard reach); Core §7 | S01-007, S02-001 | `E014-S01-007.md:48,82-89`; `E014-S02-001.md:78-79` | `pip-audit` audits the installed dev venv; the optional `publish` group (twine, beside live tokens) is never installed there, so it is never audited |
| AG-4 | MINOR | Core §1 Separation of concerns; FR-16 "once" | S01-009 (with S01-005) | `E014-S01-009.md:81,153`; init `run:55-58` | Detection hooked into `SettingsManager` load also fires in the s6 init oneshot, so the WARNINGs appear twice per container start |
| AG-5 | MINOR | Global rule 4 | S01-009 | `E014-S01-009.md:149` | The runtime `valid_env_names()` literal set is hand-kept; no test ties it to the source scan |
| AG-6 | MINOR | Core §3; ADR-0025 / product AD-6 strict parse | S01-008 | `E014-S01-008.md:61-65` | `parse_known_args` path leaves undefined what happens with leftover tokens that have no dash; strict-parse regression possible |
| AG-7 | MINOR | Core §4 (Verification executability) | S02-005 | `E014-S02-005.md:258` (row 5) | The seed-check `docker run` uses the image's default watch mode and never exits |
| AG-8 | MINOR | Release hygiene; AD-7 version identity | S02-005 | `E014-S02-005.md:265,267` (rows 12, 14) | The Gitea re-verification publishes a dev version from a throwaway WIP commit to the real index and never cleans it up |
| AG-9 | MINOR | Cross-story consistency | S02-004 | `E014-S02-004.md:37,87` | Files review-product m4 as an open backlog item although S01-010 (a transitive dependency) fixes it |
| AG-10 | MINOR | ADR coverage; Global rule 3 | S02-003 | `E014-S02-003.md:52-57,250`; CI spine L405 | The minimum item list for the "E014 pipeline amendments" ADR omits decisions the CI spine says that ADR records; no row verifies them |
| AG-11 | MINOR | Core §7 (dependency justification in an ADR) | S01-006 | `E014-S01-006.md:57,76-82,343-347` | The new runtime dependency `python-dateutil` is not in the restart ADR's content list |
| AG-12 | MINOR | Core §4; Global rule 3 | S02-001 | `E014-S02-001.md:77,82,260` | The Dependabot `pip`/hash outcome can only be observed after merge; nobody owns recording it |

## Findings

### AG-1: BLOCKER, E014-S01-006

**Finding.** The interface contract is `AcmeCertificateExporter.artifactMtime(domain: str) -> float | None`. It returns the newest mtime "over the artifact paths the configured layout (`flat` or per-domain directory) writes for `domain`" (`E014-S01-006.md:249`).

The export path inserts a resolver directory when `resolverInPathName` is set:

```
outputPath / <resolverName> / <domain> / …
```

See `src/traefik_certificate_exporter/libs/certificate_exporter.py:433-439`. That setting is the **default**:
- `src/traefik_certificate_exporter/config_default.yaml:6` (`resolverinpathname: true`);
- `docker/root/defaults/config/config.yaml.sample:6`;
- `config.sample.yml:4`.

A domain-only signature cannot locate those files. Under the default configuration:
1. `artifactMtime` returns `None` for every domain;
2. so no labeled container is a candidate (`E014-S01-006.md:42`);
3. so no restart ever happens.

That breaks PRD FR-8/FR-15 and product AD-10. The one integration test that would expose this (`tests/test_container_restart.py`) is opt-in, so `just check` stays green. The unit cases 1–9 are not required to use the default `resolverinpathname: true`.

**Evidence.**
- `E014-S01-006.md:40` (rule: "artifact files … in the configured layout"), `:249` (contract), `:331` (the `artifactMtime` tests name "both layouts" only).
- `certificate_exporter.py:433-439`; `config_default.yaml:6`.

**Fix.** Amend S01-006 before dev:
1. `artifactMtime(domain)` returns the newest mtime across **every** artifact location the exporter can write for that domain. That is `<base>/<domain>/…` and `<base>/<name>.*` (flat), plus, when `resolverInPathName` is true and the layout is not flat, `<base>/<resolver>/<domain>/…` for every resolver directory. Enumerate the resolver directories either from the resolver names seen in the store this pass, or by listing `<base>/*/<domain>`, with `_is_contained_within` applied.
2. Derive the path set from the one path helper the export path uses, including the resolver dimension and the `outputPath`-or-`cwd` base.
3. Add `test_artifact_mtime_resolver_in_path_name` (default settings, two resolvers carrying the same domain).
4. Run restart cases 1 and 2 with the default `config_default.yaml` settings.
5. State in the ADR that the newest file across resolvers wins.

### AG-2: MAJOR, E014-S01-001, E014-S01-006, E014-S02-005

**Finding.**

1. S01-001 AC 6/10 makes `tests/libs/test_docker_engine.py` required 0.3.0 release evidence. That test calls `restartLabeledContainers(["it.example.test"])` and asserts that busybox `StartedAt` changed.
2. S01-006 then changes the signature to `restartLabeledContainers(artifactMtime: Callable)` and makes a restart conditional on exported files that are newer than the container's start (`E014-S01-006.md:240`).
3. After S01-006 the S01-001 test is wrong twice over:
   - it passes a list where a callable is expected;
   - even with a callable, it creates no artifacts and starts a fresh busybox, so the rule correctly declines to restart.
4. The test is opt-in, so `just check` stays green. S01-006's "Files in scope" (`:354-367`) does not list `tests/libs/test_docker_engine.py`, and its Verification runs only `tests/test_container_restart.py` (row 10).
5. S01-007 (row 9) runs every integration test, but it can land before S01-006. The breakage therefore surfaces first at S02-005 row 4, which is release time.
6. S02-005 AC 3 lists the evidence set as S01-001's restart test, S01-005's run-once test and S01-002's PFX test (`E014-S02-005.md:78`). It claims the S01-001 test shows "newer-file restart and unchanged-store no-restart" (`:79`, row 4 `:257`). Only S01-006's `tests/test_container_restart.py` exercises FR-15, and S02-005's "missing test → BLOCKED" guard does not name it. A missing or skipped FR-15 image test would therefore not block the release.

**Evidence.**
- `E014-S01-001.md:76-82,88-92`
- `E014-S01-006.md:162-165,174-187,240,354-367,382`
- `E014-S02-005.md:78-79,167,257`
- `E014-S01-007.md:121`
- PRD NFR-5

**Fix.**
- **S01-006.** Add `tests/libs/test_docker_engine.py` to "Files in scope". Rework its AC 6 test to pass an `artifactMtime` stub that returns `StartedAt + 3 s`, so the B1 "really reaches the Engine" proof survives. Add its command to S01-006's Verification.
- **S02-005.** Make AC 3 and row 4 name all four integration modules (`test_docker_engine.py`, `test_container_pkcs12.py`, `test_container_run_once.py`, `test_container_restart.py`). Attribute the FR-15 evidence to `test_container_restart.py`. Extend the BLOCKED guard to all four.

### AG-3: MAJOR, E014-S01-007, E014-S02-001

**Finding.**
- S01-007 defines the `pip-audit` gate scope as "the whole dev venv", meaning the venv that `just check` and `build.yaml` run in (`E014-S01-007.md:48`).
- S02-001 moves `twine` into a new **optional** Poetry group `publish` and removes it from the dev group (`E014-S02-001.md:78-79,124-129`).
- `just install` is `poetry install` (`justfile:13`) and `build.yaml:47` is `poetry install`. Neither installs optional groups.

So after S02-001 the gate never audits twine or its transitive set (for example `id`, `keyring`, `readme-renderer`, `rich`, `requests-toolbelt`, `pkginfo`). Those packages are installed only in the credentialed publish jobs, beside a live PyPI or Gitea token. That is the exact surface S02-001 exists to harden (AR-06).

The guard's scope is "whatever happens to be installed", not the source of truth (`poetry.lock`), which global rule 4 forbids. No story records this narrowing.

**Evidence.**
- `E014-S01-007.md:48,82-89,175`
- `E014-S02-001.md:34-35,78-79,182`
- CI spine AD-3 (L109) and AD-11 (L221)
- `justfile:13`; `.github/workflows/build.yaml:47`

**Fix.** In S02-001, make the audited environment include the `publish` group. Choose one of:
- `just install` and the `build.yaml` install step use `poetry install --with publish`. The build stays credential-free; twine installed there is harmless.
- The `pip-audit` hook audits a lock-derived requirement set covering every group. This needs a standard-tool way; do not use `poetry export` if AD-4 forbids it.

Then:
- add a Verification row showing `poetry run pip show twine` in the gate's venv;
- add a bite probe that pins a vulnerable version of a twine-only dependency;
- route the CI AD-3 wording "audits the dev **and publish** groups" to S02-003.

### AG-4: MINOR, E014-S01-009 (interacts with E014-S01-005)

**Finding.** S01-009 places legacy and unknown-name detection in `settings.py`: "calls `find_legacy_settings` / `warn_legacy_settings` once when settings are loaded" (`E014-S01-009.md:153`).

The s6 init oneshot also builds `SettingsManager()` and calls `loadFromFile` (`init-traefik-certificate-exporter-config/run:55-58`). S01-005 keeps that resolver as the single settings authority (AD-12). In the container, every start would therefore emit each legacy or unknown-name WARNING twice:
- once from init, through an unconfigured logger, so in a different format and possibly via `logging.lastResort`;
- once from the app.

This contradicts FR-16 ("warn once") and S01-009's "Detection runs once per process … exactly one WARNING per name". Those statements hold per process, but there are two processes per container start.

**Evidence.**
- `E014-S01-009.md:81,85,153`
- `docker/root/etc/s6-overlay/s6-rc.d/init-traefik-certificate-exporter-config/run:55-58`
- PRD FR-16

**Fix.** Call the detection from `app.main()` after logging setup, not from `SettingsManager.loadFromFile`. Alternatively, add an explicit `warn_legacy=False` parameter that the init heredoc passes. Add a test to `tests/test_s6_run_mode.py` or `tests/test_s6_privilege_drop.py`: the init heredoc emits no `Legacy setting` line.

### AG-5: MINOR, E014-S01-009

**Finding.** At runtime, `valid_env_names()` takes its literal env names (`LOGGING_*`, `EXPORTED_DOMAINS`, `CORRELATION_ID`) from "the module constants that hold those names, not a source scan" (`E014-S01-009.md:149`). The test side derives the same set by scanning `src/**/*.py`.

No test asserts that the two sets are equal. If a future `os.getenv("TRAEFIK_CERTIFICATE_EXPORTER_…")` is added without its constant, every operator who sets it gets a false "Unknown setting" WARNING, while the documentation test stays green. This is a hand-kept list beside a derived one (global rule 4).

`test_valid_env_names_match_confuse_envsource` checks only the confuse-mapped part.

**Evidence.** `E014-S01-009.md:110,149`; `E014-S01-004.md:87`.

**Fix.** Add `tests/test_settings_surface.py::test_runtime_valid_env_names_equal_source_scan`. It asserts that `legacy_settings.valid_env_names()` equals the `config_default.yaml`-derived names plus the `src` literal scan (marked files skipped). Record a scope-attack probe: add an `os.getenv` literal with no constant and show that the test fails.

### AG-6: MINOR, E014-S01-008

**Finding.** The new `parse_args_strict()` calls `parser.error` only "if any leftover token starts with `-`". Leftover tokens without a dash "are reported in the same message" (`E014-S01-008.md:61-65`). The case where **all** leftovers are positional tokens (for example `traefik-certificate-exporter foo`) is left unspecified.

Today, `parse_args()` exits 2 on that input (ADR-0025; product AD-6: "unknown flag → exit 2"). A literal implementation would accept it silently, a strict-parse regression that no Verification row covers.

**Evidence.** `E014-S01-008.md:61-68,131`; product spine AD-6 (L175-177).

**Fix.** State the contract as "any leftover token → `parser.error`; suggestions only for `-` tokens". Add a test: `test_stray_positional_argument_exits_2`.

### AG-7: MINOR, E014-S02-005

**Finding.** The NFR-7 seed check is row 5:

```
docker run --rm -v "$C":/config traefik-certificate-exporter:local
```

It sets no `…_SETTINGS_WATCHFORCHANGES=false`. The image defaults to watch mode (`docker/Dockerfile:128`: `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true`), so the container never exits and the row hangs. The expected "exit code as S01-005 defines" is never reached.

**Evidence.** `E014-S02-005.md:258`; `docker/Dockerfile:128`.

**Fix.** Add `-e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false` (S01-005 run-once mode) and a `timeout 60` wrapper. Alternatively, cite the run-once integration test id after adding a seed assertion to `tests/test_container_run_once.py`.

### AG-8: MINOR, E014-S02-005

**Finding.** Decision 2 says "The dry run publishes nothing real" and deletes the test container package (row 14).

The Gitea re-verification is different. Row 12 runs `dev.yaml` with `PUBLISH_GITEA_PYPI_URL` set to the **real** index and the real package name, from a throwaway clone whose WIP commit sits at commit distance N+1. The resulting `0.2.1.devN` wheel and sdist stay on the real Gitea index; no row deletes them.

When the real merge to `main` later reaches the same distance, `dev.yaml`'s AD-11 "upload only files Gitea lacks" step skips the upload. The real index then permanently serves the WIP build under that version, a silent conflict with AD-7's version identity.

**Evidence.** `E014-S02-005.md:44-49,265,267`; CI spine AD-7 (L146-149) and AD-11 (L219).

**Fix.** Choose one:
- In row 12, point `PUBLISH_GITEA_PYPI_URL` at a test package owner or namespace.
- Extend row 14 to delete the published PyPI dev version via `DELETE /api/v1/packages/{owner}/pypi/traefik-certificate-exporter/{version}`, and record the version.

### AG-9: MINOR, E014-S02-004

**Finding.** S02-004 files review-product m4 ("`postexportcommand` logged verbatim") as a new open backlog item with `append-issue` (`E014-S02-004.md:37,87`). S02-004 depends on S01-008, which depends on S01-010. S01-010 fixes m4: `argv[0]`-only hook logs and `postexportcommand` added to `SECRET_CONFIG_KEYS` (`E014-S01-010.md:62-71`).

When S02-004 runs, m4 is already fixed. Filing it as open leaves a false open item that nobody schedules, and contradicts S02-004's own goal of "a truthful state tree".

**Evidence.** `E014-S02-004.md:37,87,241` (row 10); `E014-S01-010.md:25,62-71`.

**Fix.** For m4: `append-issue`, then immediately `resolve-issue --resolution fixed --ref E014-S01-010`, after checking that S01-010 is `done`. Alternatively, record m4 → E014-S01-010 in the notes without filing. Before filing m1, m5, m10 and m11, apply the same check: has any E014 story already closed them?

### AG-10: MINOR, E014-S02-003

**Finding.** The CI spine states that "The E014 amendments (configuration gating, hash hand-off, Poetry bootstrap exception, one forge per release, zero-warning release rule, step order, 0.x major tag) … are recorded in the ADRs E014-S02-003 writes" (CI spine L405).

S02-003 decision 4 lists the "at least" content of the E014 pipeline ADR as: Poetry bootstrap, one release run per tag, NFR-4 zero-warning, step order, and the retry loop. The following items are not on that list:
- configuration gating (token plus variables, guard retired; AD-9/AD-10);
- the hash hand-off (AD-17);
- the 0.x major-tag gate (AD-8);
- SHA-frozen hooks with `precommit-revs-frozen` (AD-3/AD-5);
- the LLL `@vN` hook;
- the token-off-argv hook and its coverage limit (AD-5/AD-11);
- the `pip-audit`/`deptry` gates and their offline-failure choice (AD-3).

The only check, Verification row 3, counts header lines. The spine's claim that "these are recorded in an ADR" is therefore not verified (global rule 3).

**Evidence.** `E014-S02-003.md:52-57,80,250`; CI spine L405.

**Fix.** Make decision 4's list match CI spine L405 exactly, adding AD-3/AD-5 frozen hooks and the gates. Add a Verification row that greps the new ADR for one anchor per item (for example `AD-8`, `AD-17`, `precommit-revs-frozen`, `workflows-no-auth-header-argv`, `pip-audit`). Alternatively, reword CI spine L405 to the items the ADR actually carries.

### AG-11: MINOR, E014-S01-006

**Finding.** S01-006 adds `python-dateutil` as a runtime dependency for one call (`isoparse`), because Python 3.10 `fromisoformat` cannot parse Docker's nanosecond `Z` timestamps. The rationale and revisit condition ("floor reaches 3.11") are in the story's Existing-library check (`:343-347`). They are absent from the ADR content list (`:76-82`) and from the spine (Stack row only).

Core §7 asks for the dependency justification to be recorded in an ADR. Without it, the "drop at 3.11" revisit has no durable home once the story file is archived.

**Evidence.** `E014-S01-006.md:57,76-82,253,343-347`; product spine Stack L320.

**Fix.** Add a bullet to the S01-006 ADR's Decision. It records `python-dateutil` (maintained, BSD/Apache-2.0, one transitive `six`), why the stdlib is insufficient on 3.10, and the revisit trigger "remove when `requires-python` floor ≥ 3.11". File that revisit as a Low backlog item.

### AG-12: MINOR, E014-S02-001

**Finding.** AC 4 makes the Dependabot `pip` entry on `/.github/requirements` conditional on "the first Dependabot PR against the file keeps `--hash=` lines". The outcome is "recorded in the notes".

That PR can only exist after the story merges, and S02-001 closes on act evidence (AC 5). Verification row 6 checks only that the entry exists. So either the outcome is never recorded, or the story cannot close. Meanwhile an entry that might produce a hash-less PR stays live, and no later story (S02-003, S02-005, S02-007) owns the check.

**Evidence.** `E014-S02-001.md:36,77,82,260`.

**Fix.** Choose one:
- Add the item "first Dependabot PR against `.github/requirements/poetry.txt` keeps hashes, or the entry is removed" to E014-S02-007's maintainer checklist and S02-005's prepared checklist.
- File it as a Low backlog item at S02-001 closure, and drop "recorded in the notes" from S02-001's DoD.

## Per-principle walkthrough

| Principle | Result |
|---|---|
| Core §1 Separation of concerns | AG-4. Otherwise PASS: docker.py receives `artifactMtime` as a callable, so the adapter never imports the domain (AD-13); the destination rule lives only in job `env` (S02-002). |
| Core §2 Reuse | PASS. The shared `suggest.nearest_name` (S01-009/S01-008); one `_scan_pathspecs()`; the publish duplication is accepted by an explicit ADR (S02-003, CI AD-1). |
| Core §3 Design by contract | AG-1, AG-6. Otherwise PASS: return types are tightened (`list[str]`, never `None`), state-file contracts are explicit (S01-005), and the reporting contract has an ADR (S01-002). |
| Core §4 Testability | AG-2, AG-7, AG-12. Otherwise PASS: fail-first rows, fake `Timer`/client, scope-attack probes, throwaway-clone act runs. |
| Core §5 Brevity | PASS. |
| Core §6 Comments | PASS. S01-006 rewrites the stale cooldown comment; S01-010 rewrites the notify docstring. |
| Core §7 Dependency selection | AG-3, AG-11. Otherwise PASS: deptry and pip-audit gates; unused dependencies removed. |
| Core §8 GA over beta | PASS. S02-001 gates the Dependabot `pre-commit` ecosystem on GA status; `queue: max` is deferred. |
| Core §9 Logging and correlation | PASS. The correlation id is re-bound in deferred restart timers (S01-006); `postexportcommand` is redacted (S01-010); per-element list redaction (S01-008). See also AG-4 (duplicate init WARNINGs). |
| Core §10 Documentation | PASS. Upgrade notes are derived from story bullets with a cross-read table (S02-005); the ADR index is compared with the directory (S02-003). |
| Python overlay | PASS (Poetry plus lock, ruff, mypy, pytest). See also AG-3 and AG-11. |
| GitHub Actions overlay | PASS. Actions are SHA-pinned or LLL `@vN` with a hook; least-privilege `contents: read`; tokens off argv (S02-006); concurrency wording corrected. |
| Docker overlay | PASS within E014 scope. The base digest is refreshed (S01-007); SBOM, provenance and `.dockerignore` are explicitly deferred in the CI spine. |
| Global rule 1 (no hand-rolling) | PASS. The S01-003 shape helpers and the S02-002 reporting loop are justified in each story's Existing-library check; retry uses an action first (S02-006). |
| Global rule 3 (mechanical enforcement) | AG-10. Elsewhere, "not mechanically enforced" is stated explicitly (one forge per release, zero warnings, duplication). |
| Global rule 4 (guard reach) | AG-3, AG-5. Otherwise PASS: pathspecs plus the pre-commit `exclude:` regex are derived, the history scan uses `HEAD`, and the hooks have scope-attack plants. |
| ADR coverage | AG-10, AG-11. All new load-bearing decisions have a reserved ADR (S01-002, S01-005, S01-006, three in S02-003) or an explicit no-ADR decision (legacy names, C-16b). |
| Spec conflict / gap | No conflict between the stories and PRD FR-1..17, NFR-1..7, product AD-1..13 and CI AD-1..18, apart from AG-1 (FR-8/FR-15 not achievable under the default layout) and AG-6 (AD-6 strict parse). The spec index covers the same three authorities plus the superseded spine and `epics.md`, so no additional spec ranges were needed. |

## Gate

- **BLOCKER AG-1** and **MAJOR AG-2 and AG-3** must be fixed in the story files before S01-006, S01-007 and S02-001 enter dev. Fixing them in the stories is enough; none needs an ADR to justify keeping it.
- **MINOR AG-4..AG-12** auto-defer to the backlog unless the story owner folds them in during elaboration. Each is a small edit to its story.

## Recommended ADRs

No new ADR beyond those the stories already reserve. Content to add to reserved ADRs:
- **E014-S01-006 restart ADR:** the `python-dateutil` justification and its revisit trigger (AG-11), and the resolver-directory artifact lookup (AG-1).
- **E014 pipeline ADR (S02-003):** the full list of items from CI spine L405 (AG-10), and the `pip-audit` scope including the `publish` group (AG-3).

## Sections read

The bounded inputs were read in full rather than through the spec index:
- PRD `prd.md` L1–138
- product spine `ARCHITECTURE-SPINE.md` L1–423
- CI/CD spine `ARCHITECTURE-SPINE.md` L1–422

Opened through or from the spec index:
- `spec/spec-index.md` L1–40, and the `^## ` header lines (L4, L26, L53, L76, L85)

No other spec ranges were opened.

## Consolidated gate outcome (orchestrator, 2026-10-11)

Reviewers run: l3io-arch-review, then (escalated on BLOCKER/MAJOR) bmad-agent-architect
(`arch-gate-review-architect.md`). superpowers reviewer not installed as a project skill.

| ID | Consolidated severity | Sources | Disposition |
|---|---|---|---|
| AG-1 | BLOCKER | arch-review, architect | ADR-0040; S01-006 patched (AR-3 folded in) |
| AG-2 | MAJOR (single-source; architect rated MINOR) | arch-review | ADR-0041; S01-006, S02-005 patched |
| AG-3 | MAJOR confirmed | arch-review, architect | ADR-0042; S01-007, S02-001 patched (AR-1 folded in) |
| AG-4 | rejected | arch-review (architect disagreed: `run:50` sends init output to /dev/null) | none |
| AG-5 | MINOR confirmed | both | BL-E014-001 |
| AG-6 | MINOR confirmed | both | BL-E014-002 |
| AG-7 | MINOR confirmed | both | BL-E014-003 |
| AG-8 | MINOR confirmed | both | BL-E014-004 |
| AG-9 | MINOR confirmed | both | BL-E014-005 |
| AG-10 | MINOR confirmed | both | BL-E014-006 |
| AG-11 | MINOR confirmed | both | folded into the AG-1 patch of S01-006 |
| AG-12 | MINOR confirmed | both | folded into the AG-3 patch (moved to S02-007) |
| AR-1 | MINOR (single-source) | architect | folded into AG-3 |
| AR-2 | MINOR (single-source) | architect | BL-E014-007 |
| AR-3 | MINOR (single-source) | architect | folded into AG-1 |

## Re-validation (l3io-arch-review)

- **Date:** 2026-10-11
- **Read:**
  - `docs/adr/0040-exported-artifact-paths-from-one-shared-helper.md`
  - `docs/adr/0041-contract-change-owns-every-test-of-the-contract.md`
  - `docs/adr/0042-dependency-audit-scope-is-the-whole-lock.md`
  - `git diff -- _bmad-output/implementation-artifacts/epic-014/sprint-0*/stories/`, which changed E014-S01-003, S01-006, S01-007, S02-001, S02-003, S02-005 and S02-007
- **Not re-reviewed:** the rest of the epic.

| Finding | Verdict | Reason |
|---|---|---|
| AG-1 | **RESOLVED** | One pure `_artifact_paths` helper, keyed by the resolver name from `_iter_resolver_nodes`, is the only place the writer gets its paths. `artifactMtime` reads the paths each pass recorded, so all four layouts are found, including the default `<output>/<resolver>/<domain>/`, plus unwrapped stores and a domain under two resolvers. Unit tests and the image test exercise the default layout (S01-006 rows 10, 11 and 13). |
| AG-2 | **RESOLVED** | S01-006 now owns `tests/libs/test_docker_engine.py`: the test uses a `StartedAt` + 3 s stub, is in "Files in scope", and S01-006 row 13 runs it with `-rs`, expecting no skip. S02-005 AC 3, row 4 and its missing-test guard name all four integration modules and credit FR-15 to `tests/test_container_restart.py`. |
| AG-3 | **RESOLVED** | `poetry sync --all-groups` in `just install` and `build.yaml` makes the audited venv equal the whole lock without naming any group. `pip-audit-bootstrap` covers `.github/requirements/*.txt` by glob, and `workflows-pip-install-from-requirements` keeps every workflow `pip install` inside that directory. Scope-attack probes are S01-007 rows 13–14 and S02-001 row 19. S02-001 row 17 proves twine is in the gate's venv. |

Folded-in items (AG-11 in ADR-0040/S01-006; AG-12 moved to S02-007 checklist, AC 3 and row 21) also read as resolved.

### New defects introduced by the patches

- **AG-13 (MINOR), E014-S01-006 / ADR-0040 §4–5: the artifact index has no concurrency contract.**
  - What can happen:
    1. The `sourceFile → {name → set[Path]}` index is written by the drain thread.
    2. It is read by `artifactMtime`, including from the deferred-restart daemon `Timer` thread. The deferred entry keeps the `artifactMtime` lookup it was armed with.
    3. With more than one store file, a drain that adds or replaces an entry while a timer iterates the index can raise `RuntimeError: dictionary changed size during iteration` inside the timer thread. That loses the deferred restart until the next pass.
  - **Fix:** state in S01-006's Interface contracts (and in ADR-0040 §4) one of two options:
    - guard the index with a lock;
    - publish it copy-on-write, where the writer builds a new dict and swaps it with one assignment, and `artifactMtime` iterates a snapshot.
  - **Test:** add `test_artifact_mtime_concurrent_with_pass`.
- **AG-14 (MINOR), E014-S01-007 / S02-001 / S02-003, ADR-0042: other spine text left stale.**
  - The routing covers only the CI AD-3 and PRD NFR-3 wording.
  - The CI spine still says plain `poetry install` in two places that the patches make stale:
    - AD-2 step 2 ("then `poetry install`", L91);
    - the AD-16 recipe table (`just install` | `poetry install`, L265).
  - **Fix:** add replacement text for AD-2 step 2 and the AD-16 `just install` row (`poetry sync --all-groups`, ADR-0042) to the S01-007 notes routing. Extend S02-003 row 20 to grep both.
