# E014 architecture gate: second review (architect)

- **Reviewer:** Winston (bmad-agent-architect persona), second reviewer
- **Date:** 2026-10-11
- **Scope:** the 17 planned E014 stories, `execution-notes.md`, the PRD, the product and CI/CD spines. Spot checks of source files were made only to test specific story claims.
- **Method:** I reviewed the stories independently first, then read `arch-gate-review.md` (AG-1..AG-12) and gave each finding a verdict. I independently reproduced AG-1, AG-3, AG-5, AG-7 and AG-9 before reading that file.
- **Severity scale:**
  - BLOCKER: the story cannot deliver its contract as written.
  - MAJOR: fix in the story before it enters dev.
  - MINOR: fold in during elaboration, or defer.

## Verdict summary

Totals after this review:
- **1 BLOCKER:** AG-1.
- **1 MAJOR:** AG-3, which now also covers AR-1.
- **12 MINOR:** AG-2 (downgraded), AG-5..AG-12, AR-1..AR-3.
- **AG-4 is rejected.**

| AG | First reviewer | My verdict | My severity | Basis (evidence) |
|---|---|---|---|---|
| AG-1 | BLOCKER | **Agree**, and the gap is wider than stated | BLOCKER | The export path joins `outputPath / <resolver> / <name>` when `resolverInPathName` is set and a resolver name exists. The non-flat layout then adds `/<name>/`; the flat layout writes `<name>.*` inside the resolver directory (`certificate_exporter.py:428-445`, `:461-512`). The default is `resolverinpathname: true` (`config_default.yaml:6`, `docker/root/defaults/config/config.yaml.sample:6`, `config.sample.yml:4`). The S01-006 contract covers only "`flat` or per-domain directory" (`E014-S01-006.md:249`), and its tests cover "both layouts" (`:331`). Under the default image config, `artifactMtime` returns `None` for every domain, so the container is never a candidate and no restart happens: the B1 silent-no-op class returns. Three things widen the gap (see "AG-1 extension" below). |
| AG-2 | MAJOR | **Agree with the facts; disagree with the severity** | MINOR | Ownership exists in words. S01-006 says "any test that passes a domain list to `restartLabeledContainers` passes an `artifactMtime` lookup instead" (`E014-S01-006.md:165`). What is missing is the file (`tests/libs/test_docker_engine.py`) in Files in scope (`:354-367`) and a Verification row. The breakage cannot ship silently: S02-005 row 4 runs `pytest -m integration -v -rs`, which collects every integration module and requires "PASSED … no skip" (`E014-S02-005.md:257`). So it surfaces as a loud failure before tagging. The cost is late rework plus a misattribution (FR-15 credited to S01-001's test, `:79`), not a wrong release. AG-2's fix is right as written. |
| AG-3 | MAJOR | **Agree** | MAJOR | `pip-audit` runs as `poetry run pip-audit` over the installed venv (`E014-S01-007.md:85`, scope "whole dev venv" `:48`). `just install` and `build.yaml` run plain `poetry install` (`justfile:13`, `build.yaml:47`), which skips optional groups. S02-001 makes `publish` optional and moves `twine` there (`E014-S02-001.md:78`, `:124-129`). After S02-001, the only packages installed beside live tokens are never audited. PRD NFR-3 (`prd.md:86`) also claims "no locked dependency carries a known advisory (pip-audit gate)", but the gate audits the installed set, not the lock. That overstates coverage (global rule 3). Prefer AG-3 fix option 1 (`--with publish` in `just install` and `build.yaml`). Option 2's `poetry export` needs `poetry-plugin-export`, which Poetry 2.x does not bundle: a new plugin for no gain. Also route the NFR-3 / CI AD-3 wording. See AR-1 for the second unaudited set. |
| AG-4 | MINOR | **Disagree** | — (not a finding) | The init heredoc runs with `> /dev/null 2>&1` (`init-traefik-certificate-exporter-config/run:50`). Any WARNING emitted by a `SettingsManager` load there, including through `logging.lastResort`, goes to `/dev/null`, so the operator sees each WARNING once, from the app. The image sets `LOGGING_CONSOLEONLY=true`, so no file handler catches it either. The only residual is invisible duplicate work. Optional hardening, not a defect: S01-005, which edits the same heredoc, keeps that redirect. |
| AG-5 | MINOR | **Agree** (found independently) | MINOR | `E014-S01-009.md:149`: the runtime literal set is hand-kept, and `test_valid_env_names_match_confuse_envsource` covers only the confuse-mapped part (`:110`). A missing constant produces a false "Unknown setting" WARNING while every test stays green. That is global rule 4. AG-5's fix is correct. |
| AG-6 | MINOR | **Agree** | MINOR | `E014-S01-008.md:61-65` makes `parser.error` conditional on a `-`-prefixed leftover. A positional-only leftover is unspecified, and today's `parse_args()` exits 2 on it (ADR-0025, product AD-6). The parser declares no positional arguments (every `add_argument` in `cli_args.py` is a flag), so any leftover is an error. |
| AG-7 | MINOR | **Agree** (found independently) | MINOR | `E014-S02-005.md:258` (row 5) runs the image in its default watch mode, which never exits. Add `-e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false` and a `timeout`. |
| AG-8 | MINOR | **Agree** | MINOR | Row 12 (`E014-S02-005.md:265`) uploads a dev version built from a throwaway WIP commit to the real Gitea index. Row 14 cleans up only the container package (`:267`). AD-11's "upload only files Gitea lacks" then shadows the real build of the same version for good. |
| AG-9 | MINOR | **Agree** (found independently) | MINOR | `E014-S02-004.md:306` and AC 5 (`:356`) file m4. S01-010 fixes m4 (`E014-S01-010.md` ACs "`postexportcommand` is not logged"). S02-004 reaches it through S01-008, which reaches S01-010. Filing it would create a false open item. |
| AG-10 | MINOR | **Agree** (narrower list) | MINOR | CI spine L405 claims the E014 ADR records "configuration gating, hash hand-off, … 0.x major tag". S02-003 decision 4 (`E014-S02-003.md:52-57`) does not name configuration gating, hash hand-off or the 0.x major tag, and row 3 counts headers only. The extra items AG-10 lists (frozen hooks, LLL hook, argv hook, pip-audit/deptry) are not claimed by L405. Add them only if the spine is reworded to claim them. The required minimum is the L405 list. |
| AG-11 | MINOR | **Agree** | MINOR | The `python-dateutil` rationale and its "floor ≥ 3.11" revisit appear only in the story's Existing-library check (`E014-S01-006.md:343-347`), not in the ADR content list (`:76-82`). |
| AG-12 | MINOR | **Agree** | MINOR | The Dependabot `pip`-with-hashes outcome is observable only after merge, while S02-001 closes on act evidence (`E014-S02-001.md:77,82`). Hand the check to S02-007's checklist. |

### AG-1 extension: what the S01-006 fix must also cover

The first reviewer's fix (item 1) adds `<base>/<resolver>/<domain>/…` only "when the layout is not flat". Three cases remain open:

1. **Flat layout with a resolver directory.** With `resolverinpathname: true` and `flat: true`, the exporter writes `<base>/<resolver>/<name>.key|.crt|.chain.pem|.fullchain.pem|.pfx` (`certificate_exporter.py:433-439`, `:460-488`). That is a fourth location, and the fix's enumeration misses it.
2. **The layout depends on the store shape as well as on settings.** An unwrapped store gets no resolver directory even under the default settings: the Traefik v1.7 single `StoredData` (S01-003's `acme_v17_single_store`), or `acme_v2_uppercase_fixture` ("NOT resolver-wrapped", `tests/fixtures/acme_fixtures.py:64-65`). A settings-only path rule therefore cannot be right. The path set must come from the store, through S01-003's `_iter_resolver_nodes`, honouring `traefikresolverid`, the `*.` strip and `_is_safe_path_component`.
3. **The release backstop can miss the defect.** S01-006's image test writes "a `real_chain()` ACME v2 store" (`E014-S01-006.md:176`) without fixing its shape. If it reuses an unwrapped builder, the opt-in test passes under the default config, and the defect reaches users.

**Fix, in addition to AG-1's fix:**
- Define one helper, `_artifact_paths(base, resolverName | None, name, flat) -> list[Path]`, in `certificate_exporter.py`. Both the write path and `artifactMtime` call it.
- `artifactMtime(domain)` takes the maximum over `_artifact_paths` for every resolver node the most recent parse of the store files yielded for that domain. Do not glob `<base>/*/<domain>`: a glob also matches files the exporter did not write, and it cannot express the flat-with-resolver layout.
- Add unit cases for all four layout combinations, a two-resolver same-domain case and an unwrapped-store case.
- Require the S01-006 image test store to be resolver-wrapped, the stock Traefik v2/v3 shape.
- Route the resolver dimension to PRD FR-3 (`prd.md:64`) and to the product spine Conventions "Data & formats — artifacts" row (`ARCHITECTURE-SPINE.md:301`). Both omit it today. Route through S01-006's notes file to S02-003.

## New findings

| # | Severity | Story | Finding | Evidence | Fix |
|---|---|---|---|---|---|
| AR-1 | MINOR (I would merge it into AG-3 as one MAJOR fix) | E014-S02-001 (with S01-007) | **The Poetry bootstrap set is a second package set outside the `pip-audit` gate.** S02-001 installs Poetry in every credentialed publish job from `.github/requirements/poetry.txt`. pip-compile resolves that file independently of `poetry.lock`. The gate runs `poetry run pip-audit` inside the project venv, so it never sees the bootstrap set: Poetry's own transitive closure (requests, urllib3, keyring, dulwich, …) at the bootstrap file's pins. `poetry` is also in the dev group (`pyproject.toml:34`), but at lock-resolved versions, which can differ from `poetry.txt`. Dependabot's `pip` entry on that directory, if kept, proposes updates; it is not a gate. | `E014-S02-001.md:75-77` (AC 4), `:132-135`; `E014-S01-007.md:85` (hook entry), `:87` (`files:` limited to `pyproject.toml`/`poetry.lock`); `.github/workflows/build.yaml:46`, `dev.yaml:77`, `release.yaml:123` | Add a second invocation to S01-007's `pip-audit` local hook, done in S02-001 when the file appears: `pip-audit --require-hashes --disable-pip -r .github/requirements/poetry.txt`, and add `.github/requirements/poetry\.txt` to its `files:`. Prove it bites the same way S01-007 AC 4 does, using a vulnerable pin in a scratch copy. Route "the gate audits the venv (dev + publish groups) and the Poetry bootstrap file" to CI AD-3 and NFR-3 through S02-003. |
| AR-2 | MINOR | E014-S01-009 (with S01-004) | **The history scan does not inherit the vendored-tree exclusion, despite "one helper, no second list".** S01-004 drops vendored files by applying the pre-commit `exclude:` regex (`^(\.agents\|\.claude\|_bmad)/`) to the current-tree file list. A git pathspec cannot express that regex. S01-009 says the history test "passes the same pathspecs to `git log`", and its re-derivation command has no vendored exclusion. So `git log -p HEAD -- '*.md' …` scans the full history of about 690 vendored `*.md` files. Any `TRAEFIK_CERTIFICATE_EXPORTER_*` string ever committed there would force a `LEGACY_SETTING_NAMES` row for a name no operator was ever told to use, and the two scans would quietly disagree on scope. | `E014-S01-004.md:83-84`; `E014-S01-009.md:30,94,154,219` (row 1) | In S01-009, state that the history test splits `git log -p` output on `diff --git a/<path>` headers and drops hunks whose path matches the same `exclude:` regex, read through `_scan_pathspecs()`'s companion. Add a probe: a legacy name committed under `.claude/` in a throwaway clone is ignored, and one under `docs/` is reported. Apply the same filter to row 1. |
| AR-3 | MINOR | E014-S01-006 | **The candidate set and `artifactMtime` are underspecified for a watch pass that processes one store file.** `__processPath` handles one file, but the rule is evaluated over "labeled containers whose label names at least one domain with an exported artifact present". If `artifactMtime` is scoped to the domains parsed in this pass (the natural fix for AG-1), then a watch drain for file A never re-evaluates containers that serve only file B's domains. Crash recovery for those containers then waits for file B's next write or the next start-up pass. That is acceptable, but the story's "on every pass … recovered on the next pass" (`E014-S01-006.md:39,251`) does not say so. | `E014-S01-006.md:39-42,116,252`; `certificate_exporter.py:1044-1065` (per-file call site) | When fixing AG-1, state which store files' domains `artifactMtime` covers: all files under `datapath` (re-parsed or cached), or only this pass's file. If "only this pass's file", record in the ADR and the operational doc that "next pass" means the next pass over that store file. Add a test either way. |

### Independently checked and found clean

These need no action:
- **S01-002 build-first and no-rewrite.** These are compatible with S01-006's mtime rule. `_atomic_write` replaces through a temp file and copies only mode and owner, never times (`certificate_exporter.py:154-232`), so a rewritten file's mtime always moves, and an unchanged file is not touched.
- **The S01-005 / S01-006 / S01-010 `app._run` restructuring order.** It is consistent: S01-005 adds the WARNING branch, S01-006 adds the `try/finally`, and S01-010 adds the hook and notification guard, with matching `depends_on` chains.
- **S02-002's flag and `ANY_*` table.** It is internally consistent, including the Gitea shared-input single-warning rule.

## Gate

- **AG-1 (BLOCKER)** must be fixed in E014-S01-006 before that story enters dev, including the AG-1 extension above. Without the fix, the release's headline restart fix does not work in the default deployment.
- **AG-3 (MAJOR, with AR-1 folded in)** must be fixed in E014-S02-001 before dev (and in the S01-007 hook definition, if S01-007 has not started).
- **All MINORs** (AG-2, AG-5..AG-12, AR-1..AR-3) may be folded in during elaboration, or deferred with backlog keys. AR-3 should be decided together with the AG-1 fix, because it is the same contract.
- **AG-4 is rejected.** No action is needed.

## Assumptions recorded

- The CLI parser declares no positional arguments (AG-6). I inferred this from the `add_argument` calls in `cli_args.py`; I did not open each one in full.
- I did not inspect the vendored trees for `TRAEFIK_CERTIFICATE_EXPORTER_` strings (AR-2). The finding is about scope parity, so it stands whether or not a match exists today.

## Re-validation (bmad-agent-architect)

- **Date:** 2026-10-11
- **Inputs read:**
  - `docs/adr/0040-exported-artifact-paths-from-one-shared-helper.md`
  - `docs/adr/0041-contract-change-owns-every-test-of-the-contract.md`
  - `docs/adr/0042-dependency-audit-scope-is-the-whole-lock.md`
  - `git diff` of the story files (S01-003, S01-006, S01-007, S02-001, S02-003, S02-005, S02-007)

| Item | Verdict | Reason |
|---|---|---|
| AG-1 | RESOLVED | ADR-0040 and the S01-006 patch replace the settings-only lookup with three things: one pure `_artifact_paths` helper that the writer also uses; resolver names taken from S01-003's `_iter_resolver_nodes` (`None` for unwrapped stores); and a per-store-file index that `artifactMtime` reads. The patch adds unit cases for all four `resolverinpathname` × `flat` layouts, unwrapped stores, two resolvers sharing a domain, and planted foreign files; it switches the image test to a resolver-wrapped store under the default layout (Verification rows 10–11) and routes FR-3 and the spine "artifacts" row. That covers the original finding and every item of my AG-1 extension. |
| AR-3 (folded into AG-1) | RESOLVED | ADR-0040 §6 defines the scope: every store file this process has processed. The `runatstart: false` caveat is stated in the story Context and in `docs/operational.md`, and `test_artifact_mtime_covers_previously_processed_store_files` tests the scope. |
| AG-2 | RESOLVED | Following ADR-0041, S01-006 lists `tests/libs/test_docker_engine.py` in scope. The test now passes a `StartedAt + 3 s` stub, which satisfies the 2 s slack rule. S01-006 Verification row 13 runs it with `-rs` (none skipped). S02-005 AC 3, row 4 and the BLOCKED guard name all four integration modules and credit FR-15 to `tests/test_container_restart.py`. |
| AG-3 | RESOLVED | ADR-0042 option E: `just install` and `build.yaml` run `poetry sync --all-groups`, so the audited venv is the whole lock, the optional `publish` group included, and no group is named anywhere. S02-001 row 17 guards that twine stays in the gate's venv. The S01-007 lock-scope probe shows the old scope missing an advisory in an optional group and the new scope failing on it. The NFR-3 and CI AD-3 wording is routed through S02-003 (row 20). |
| AR-1 (folded into AG-3) | RESOLVED | The `pip-audit-bootstrap` hook audits `.github/requirements/*.txt` through its `files:` glob, with `--require-hashes --disable-pip`. The `workflows-pip-install-from-requirements` reach guard keeps every workflow `pip install` inside that directory. Both have scope-attack probes (S01-007 row 14, S02-001 row 19). The parts the guard cannot see are stated as not covered in ADR-0042 Consequences: the Dockerfile builder Poetry, the Poetry plugin environment, and multi-line or variable-built `pip install` lines. |

### New defects introduced by the patches

| # | Severity | Story / ADR | Defect | Fix |
|---|---|---|---|---|
| RV-1 | MINOR | E014-S01-006 / ADR-0040 §4 | **A partial failure in a store file can drop a domain from the restart index for the rest of the process.** Processing a store file replaces that file's whole index entry with the paths of the certificates that reached the write step. A domain is therefore dropped from the index whenever a store file is processed and the domain does not reach the write step. That happens when the resolver it belongs to fails under S01-003's per-resolver isolation (for example `Certificates: null` mid-rewrite), or when its own build fails (S01-002 keeps its old files). The domain is dropped even though its files are still on disk. Only a *file-level* failure keeps the previous entry. A crash-lost restart for that domain is then not recovered until the domain next exports cleanly. Today the recovery claim holds only for the file-level case. | In ADR-0040 §4 and the S01-006 interface contract, choose one: a resolver that fails, or a domain whose build fails, keeps its previous paths in the entry (merge rather than replace for those); or the "recovered on the next pass" caveat in ADR-0040 §6 and `docs/operational.md` names this case. Add one test: a two-resolver store whose second resolver fails on re-processing still yields `artifactMtime` for that resolver's domain. |

No other new defect found. The `poetry sync --all-groups` side effects (twine installed in the credential-free build job and in dev venvs; a stale local venv is audited as it stands) are accepted explicitly in ADR-0042. They are not defects.

**Gate after re-validation:**
- The BLOCKER (AG-1) is cleared, and so is the remaining MAJOR (AG-3, with AR-1).
- AG-2 and AR-3 are resolved.
- RV-1 is MINOR. It can be folded into E014-S01-006 during dev, or deferred with a backlog key.
