# Architectural Drift Review — E015 sprint 01

- **Mode:** l3io-arch-review Mode B (architectural review), headless
- **Date:** 2026-10-12
- **Scope:** `git diff HEAD -- src tests docker pyproject.toml config.sample.yml` plus untracked
  `tests/test_container_root_trust.py`; stories E015-S01-001..004 (ACs); ADR-0049, ADR-0050,
  ADR-0051, ADR-0030 (amended paragraph); product spine AD-2, AD-3, AD-6, AD-8, AD-10, AD-11,
  AD-13; spec index (alignment on).
- **Standards loaded:** `standards-core.md`; overlays `standards-python.md` (Poetry project) and
  `standards-docker.md` (image ships; only `docker/README.md` changed). `standards-shell.md` not
  applied: no shell or s6 script is in the diff.
- **Binding constraint:** nothing that breaks LinuxServer.io conventions.
- **Out of scope here:** `docs/` (operational.md, upgrading.md, architecture.md §6, ADR-0043),
  `README.md`, `poetry.lock`, and the PRD. Story doc items in those files (S01-001 AC 9,
  S01-002 AC 15-16) were not checked. Known closure facts were taken as given: the root-mode
  `.env` narrowing beyond S01-001 AC 3 (ADR-0049 amendment, spine changelog, PRD FR-18 not
  updated); ruff==0.16.5 in the Poetry dev group; the `view: confuse.ConfigView` mypy fix.

## Executive summary

The sprint's code matches its ADRs and the spine sections it binds. The settings trust table,
withholding, `filespec` validation, `sourceOf`, the ruff `TID251` guard, the `.pfx` fingerprint
sidecar, the moved-event watch trigger and the pre-confuse legacy rows all follow ADR-0049,
ADR-0050, ADR-0051 and AD-2/3/6/8/10/11/13 as written. The diff does not change LinuxServer's
init, `docker/Dockerfile` or any s6 script. `/config` stays `PUID`-owned, and the image test
asserts this (`tests/test_container_root_trust.py`, `test_config_stays_puid_owned_and_editable_by_the_puid_account`).
Count: 0 BLOCKER, 1 MAJOR, 6 MINOR. Most important action: bring PRD FR-18 in line with the
shipped root-mode `.env` rule (SD-01-1). The ADR amendment and spine already record that rule;
only the requirement text is stale.

## Findings table

| # | Severity | Principle | Location | Finding | Remediation |
|---|----------|-----------|----------|---------|-------------|
| SD-01-1 | MAJOR | Spec alignment; Core §10 (docs that contradict the code) | `src/traefik_certificate_exporter/libs/settings.py:600` (`_loadDotenvAsRoot`), `:632` (`_isAnySourceEnvName`); story E015-S01-001 AC 3; PRD FR-18 | In root mode the shipped loader lets a `.env` file add only the variable names of `any-source` settings. It removes every other name that file adds (`LOGGING_*`, `LD_PRELOAD`, `DOCKER_HOST`, `PATH`, …). S01-001 AC 3 says "Other `.env` keys load as today", and PRD FR-18 covers only the environment-only keys. The decision is recorded in the ADR-0049 amendment (2026-10-12, Decision 4 replaced) and in spine AD-2, but the requirement that downstream planning reads still describes the narrower rule. | Update PRD FR-18 so that a root-mode `.env` file contributes only `any-source` setting names, derived from `ROOT_SETTING_TRUST`, and cite the ADR-0049 amendment. Add a pointer to the amendment in the S01-001 change log. No code change. |
| SD-01-2 | MINOR | Core §2 Reuse over copy-paste | `src/traefik_certificate_exporter/libs/settings.py:103` (`_ENV_PREFIX`), `:106` (`_env_name`), `:632-660` (`_isAnySourceEnvName`, `_packagedDefault`) vs `libs/legacy_settings.py:44` (`ENV_PREFIX`), `:259` (`_env_name`), `_is_valid_env_name` / `_config_leaves` | The env-name ↔ key-path rule now exists twice. The prefix literal and `_env_name` are duplicated, and the "trailing all-digit segment is admissible only under a list default" rule is implemented again with a different lookup. The two copies also treat the prefix differently: `_env_key_path` matches it case-insensitively, while `legacy_settings._canonical` and confuse's `EnvSource` match it case-sensitively. Two occurrences, so MINOR, but the copies have already diverged. | Import `ENV_PREFIX` and a public `env_name` from `legacy_settings` (AD-13 lets `settings` import from `legacy_settings`). Share one helper for "env name → key path, list index admissible", and match the prefix case-sensitively as confuse does. |
| SD-01-3 | MINOR | Core §2 / §5 | `src/traefik_certificate_exporter/libs/settings.py:576` (`sourceOf`), `:662` (`_withholdFileSourcedRootSettings`), `:733` (`_mark_present_secrets`); `:651` vs `:716` (`_validatedFileSpec`) | The `view = self._config; for segment in keyPath: view = view[segment]` walk appears three times, and the raw-dict walk `node.get(segment) if isinstance(node, dict) else None` twice. `_validatedFileSpec` reads the packaged default inline (`next(s for s in self._config.sources if s.default)[...]`) although `_packagedDefault` does the same thing. | Add one `_view(keyPath)` helper and one dict-walk helper. Use `self._packagedDefault(("settings", "filespec"))` in `_validatedFileSpec`. |
| SD-01-4 | MINOR | Spec alignment (spine AD-6); Core §10 | Spine AD-6 Rule ("the root-mode trust rule (AD-2) removes file sources from the admissible set for three keys … and does not reorder the rest") vs `settings.py:600` | After the ADR-0049 amendment, a root-mode `.env` is also not an admissible source for any name outside the `any-source` settings. AD-2 says so, but AD-6's summary sentence still describes only the three keys. | Rewrite the AD-6 sentence to defer to AD-2 ("…for three keys, and a root-mode `.env` contributes only `any-source` names (AD-2)"), with a changelog line. |
| SD-01-5 | MINOR | Core §7 dependency selection; Core §10; Python overlay (one pinned toolchain) | `pyproject.toml:41-44` (`ruff = "==0.16.5"`, comment "F10 of review…"); ADR-0050 Decision 4 and Consequences | ruff is now pinned twice, by the pre-commit hook's frozen `rev` and by the Poetry dev group, and a test keeps the two equal. The comment directly above (`pyproject.toml:37-38`) states the project convention for gate tools: `repo: local` hooks versioned by `poetry.lock` (C-10). ADR-0050 Decision 4 still says "ruff is a pre-commit hook, not a dev dependency", and its Consequences say "nothing else changes", although PGH004 is now selected. The amendment mentions both changes but does not replace that text. | Add a dated line to the ADR-0050 amendment that replaces Decision 4's parenthetical and the Consequences bullet. Consider moving the ruff hook to `repo: local` / `poetry run ruff` under C-10, so there is one pin and the equality test can go. |
| SD-01-6 | MINOR | Core §6 Comments explain current state, not history | `src/traefik_certificate_exporter/libs/certificate_exporter.py:1683` (`on_moved` docstring "Without this override every rename went to the base class's no-op…"); `settings.py:634` ("(F9, review E015-S01-001)"); `pyproject.toml:42` ("F10 of review E015-S01-001") | These comments narrate change history or cite review-finding IDs instead of the deciding ADR. | Say what the code does now and why, and link ADR-0049, ADR-0050 or AD-11. Leave review-finding IDs to the ADR amendment and git. |
| SD-01-7 | MINOR | Core §5 Brevity / efficiency | `src/traefik_certificate_exporter/libs/certificate_exporter.py:1324-1329` (`__exportDomain` verify path), `:388` (`_pfx_differs`) | On the `verify` path the same `.pfx` is read three times: `_pfx_state` hashes it, `__exportDomain` reads `existing`, and `_pfx_differs` reads the file again before its PKCS#12 load. The bytes that get compared are not necessarily the bytes later recorded as `verifiedPfx`. That gap is benign, because the next pass's `pfx_sha256` check catches any change, but it is avoidable. | Pass `existing` into the content compare (a bytes-taking variant of `_pfx_differs`), so the bytes compared are the bytes fingerprinted. |

## Per-principle walkthrough

**Core**

- §1 Separation of Concerns: PASS. Trust policy and `.env` sanitising live in `libs/settings.py` beside `SECRET_CONFIG_KEYS`, as AD-2 binds. The sidecar helpers are module-level pure functions next to `_artifact_paths` (AD-8). The watch handler change stays inside `AcmeCertificateFileHandler` (AD-11). No new module (AD-13: "E015 adds no module"). The new imports respect `libs-layers`: `settings` → `legacy_settings` goes downward, and `certificate_exporter` → `watchdog.utils.patterns` is a third-party import.
- §2 Reuse over copy-paste: SD-01-2, SD-01-3. Positive: `_serialize_pkcs12` was extracted so `build_pkcs12` and the export path share it; `__queuePath` was extracted from `handleEvent`; `_is_legacy_env_name` reuses `find_legacy_settings`; `_env_key_path` reuses confuse's `build_dict` rather than re-splitting.
- §3 Design by Contract: PASS. `filespec` is validated once at the load edge (ADR-0049 D5). Sidecar records are type- and size-checked, and the scrypt cost parameters are bounded before any derive (`_scrypt_params`). `_pfx_state` is total and never raises. `_load_private_key` is the single loader.
- §4 Testability: PASS. Root mode is switched by `os.geteuid` behind `_is_root()` and monkeypatched in tests. `_pfx_state`, `_is_file_name_glob`, `_pfx_fingerprint_path` and `_preconfuse_entry` are pure. The scope guards are derived: the leaf set comes from `config_default.yaml`, spawn names from `dir(os)`/`dir(posix)`, and translator files from `git log -G appParams`. Each guard has a planted-violation test. All tests are pytest; there is no bespoke harness.
- §5 Brevity: SD-01-3, SD-01-7.
- §6 Comments: SD-01-6. Otherwise the comments carry the why and cite ADRs, including the coverage-limit block beside the banned-api table, as global rule 3 requires.
- §7 Dependency selection: SD-01-5. No new runtime dependency. `watchdog.utils.patterns.match_any_paths` and cryptography's `Scrypt` are maintained, already-locked libraries.
- §8 GA over preview: PASS. No pre-release dependency or feature added.
- §9 Logging: PASS. The new lines follow AD-3: the hook-source and RSA-validation INFO lines come after `Output Path`, and the withholding, `.env` and `filespec` ERRORs carry names and sources but never values. The moved-event INFO uses the open window's correlation id. The sidecar WARNING carries the path and error only. No `print`.
- §10 Documentation: SD-01-1, SD-01-4, SD-01-5. `docker/README.md` and `config.sample.yml` state the new operator rules (hook in `environment:` for root mode, `/data:ro` in both modes, `validatekeys`). `docs/` is outside this review's scope.

**Python overlay**

- Poetry and lockfile: PASS on the diff. ruff was added to the dev group (SD-01-5 covers the dual pin). `poetry.lock` was not in scope.
- Typed and ruff-clean: PASS on the diff. The new functions are typed, and the closure mypy fix (`view: confuse.ConfigView`) is applied at `settings.py:576/662/733`. Remaining `# type: ignore` comments follow the existing confuse pattern.
- Structured logging, no `print`: PASS (core §9).

**Docker overlay**

- Base pinning, multi-stage, SBOM, non-root, signals: unchanged by this diff (no `Dockerfile` change). Not re-reviewed.
- Runtime posture and the LinuxServer constraint: PASS. `init-adduser` and `/config` ownership are untouched (S01-001 AC 8). The image test proves `/config` stays `1000:1000` and editable. The `.env` narrowing affects only a root process reading `/config/.env`, which is not a LinuxServer mechanism.

**Spine sections**

- AD-2: PASS. Trust table, withholding by source removal (no `set()`), `.env` rule as amended, `filespec` glob and hook opt-in all match. Wording drift elsewhere is SD-01-4.
- AD-3: PASS. Both start-up INFO lines; the command is never logged.
- AD-6: SD-01-4. The pre-confuse rows are exact and case-sensitive, never unknown, with `test_legacy_map_covers_preconfuse_env_names` plus the scope-attack and rule-attack tests. `--no-validate-keys` uses `store_const`/`default=None`.
- AD-8: PASS. Lazy key load, `_load_private_key` everywhere, current/rebuild/verify, sidecar contract and write order, the AG-3 cache split, and dry run writes nothing.
- AD-10: PASS. The sidecar is never in `_artifact_paths`, so `artifactMtime` is unchanged.
- AD-11: PASS. `on_moved` re-matches `dest_path` with `match_any_paths` over the handler's own properties, discards the source under the lock, logs rename-away at INFO, and ignores directory events.
- AD-13: PASS. No new module, and the imports respect the layer order.

**ADRs**

- ADR-0049 (with its amendment): PASS in code. The spec-side drift is SD-01-1.
- ADR-0050 (with its amendment): PASS in `pyproject.toml` and `post_export.py`. The text drift is SD-01-5.
- ADR-0051: PASS.
- ADR-0030 amended paragraph: consistent with the shipped behaviour and with the LinuxServer convention.

## Gate

- SD-01-1 (MAJOR) must be resolved before sign-off. Suggested disposition: **spec-updated** (PRD FR-18). The decision itself is already ADR-justified by the ADR-0049 amendment.
- SD-01-2 … SD-01-7 (MINOR) defer to the backlog.

## Recommended ADRs

None new. SD-01-5 needs only a dated line in the existing ADR-0050 amendment. If ruff moves to a
`repo: local` hook, that falls under the existing C-10 convention and needs no new ADR.

## Sections read

- `_bmad-output/implementation-artifacts/epic-015/sprint-01/stories/E015-S01-001.md` L56-120, L155-243, L292-323, L350-357
- `_bmad-output/implementation-artifacts/epic-015/sprint-01/stories/E015-S01-002.md` L62-123, L153-256, L335-352
- `_bmad-output/implementation-artifacts/epic-015/sprint-01/stories/E015-S01-003.md` L53-68, L96-143, L187-192
- `_bmad-output/implementation-artifacts/epic-015/sprint-01/stories/E015-S01-004.md` L56-80, L106-153, L192-197
- `docs/adr/0049-root-mode-trust-covers-hook-output-and-store-location.md` L1-27, L117-256, L272-313
- `docs/adr/0050-spawn-site-guard-uses-ruff-banned-api.md` L1-18, L65-181
- `docs/adr/0051-pfx-fingerprint-sidecar.md` L1-16, L43-144
- `docs/adr/0030-conditional-privilege-drop.md` L85-126
- `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md` L107-257 (AD-2, AD-3), L280-334 (AD-6), L356-435 (AD-8), L457-521 (AD-10, AD-11), L556-578 (AD-13)
- `_bmad-output/implementation-artifacts/spec/spec-index.md` (whole index). No spec section opened: every diff hunk was covered by the ADR and spine sections above.
- Diff support (to confirm duplication findings): `src/traefik_certificate_exporter/libs/legacy_settings.py` L252-300; `pyproject.toml` L30-40; `tests/test_container_root_trust.py` L1-40.

Blocker: 0, Major: 1, Minor: 6
