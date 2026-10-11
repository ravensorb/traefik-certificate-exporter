# E014 plan review — lens 2 of 3: PRD / requirements traceability

- **Scope:** the 13 E014 stories (`sprint-01/stories/E014-S01-001..008.md`, `sprint-02/stories/E014-S02-001..005.md`), traced against the PRD (`_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md`, FR-1..11, NFR-1..7, §5, §6 items 1–23) and the maintainer decisions in `architecture-ci-cd-pipeline-2026-10-08/.memlog.md` (2026-10-10, 2026-10-11).
- **Context:** `review-all-epics-2026-10-10/review-product.md` (PRD capability trace, B1/B2/M1–M8/m1–m11) and `review-coherence.md` §2 (PRD coverage, CO-11/CO-12).
- **Date:** 2026-10-11. Stories are at `status: backlog`; this is a plan review. No code was changed.

## Verdict

**TRACEABLE WITH GAPS: 0 BLOCKER, 3 MAJOR, 9 MINOR.**

Every PRD functional requirement that `review-product.md` marked broken or partial (FR-1, FR-2, FR-6, FR-8, FR-10) has an E014 story with fail-first ACs. No story contradicts a PRD requirement. Each recorded maintainer decision (2026-10-10 items 1–3; 2026-10-11 items 1–4 plus the dropped ACME size cap) is carried by a named story. Backward trace: 11 of 13 stories rest on a PRD FR/NFR or a maintainer decision. The other two (S01-008, S02-004) are hygiene work with backlog provenance, which is acceptable.

The gaps are at the release boundary:

1. **F-01.** E014 never requires the positive end-to-end proof of its headline fixes (a real container restart, container run-once, a passphrase PFX) on any artifact. The only real-daemon or real-container tests are opt-in, and S02-005 does not run them.
2. **F-02.** The upgrade notes do not warn that restarts start happening in 0.3.0, including at every exporter start.
3. **F-03.** The upgrade-notes topic list is hand-enumerated. It drops several operator-visible changes that the stories themselves list as "0.3.0 release notes".

The PRD itself stays stale. S02-003 excludes it explicitly, and no backlog key tracks that deferral (F-04).

## 1. Forward trace: PRD → stories (state after E014)

Legend: **satisfied-before** = delivered by E001–E013 and unchanged or only reinforced by E014; **fixed-by-E014** = broken or partial before, repaired by the named story; **still-gap** = not delivered after E014; **contradicted** = E014 or an earlier ADR departs from the PRD text; **weakened** = still met, with a recorded trade-off.

### §3 Functional requirements

| PRD | Requirement | State before E014 (review-product) | After E014 | Story / evidence | Notes |
|---|---|---|---|---|---|
| FR-1 | Parse v1 and v2 ACME JSON | Partial: non-LE CA → `KeyError`; `Certificates: null` aborts the file | **fixed-by-E014** | S01-003 ACs "CA-agnostic detection", "Null-safety", "Per-resolver isolation", strict base64 | Goes beyond the PRD wording ("v1/v2"): detection is now by shape, with any RFC 8555 CA. The PRD text is stale (§5). |
| FR-2 | Key, leaf, chain, fullchain, PKCS12 | Broken with a passphrase (B2) | **fixed-by-E014** | S01-002 AC1–8 (passphrase, intermediates, `load_pem_x509_certificates`, build-before-replace) | PKCS12 now carries intermediates. The flat `<name>.crt` content is unchanged (non-goal), so it stays compatible. |
| FR-3 | Flat and per-domain layouts | Yes | satisfied-before | S01-002 keeps names and modes (Interface contracts) | — |
| FR-4 | Include/exclude, mutually exclusive | Yes | satisfied-before | S01-004 corrects the documented env names (`…_SETTINGS_DOMAINS_INCLUDE/EXCLUDE`) | — |
| FR-5 | Resolver scoping / auto-detect | Yes, with the M3 caveat | **fixed-by-E014** (auto-detect) | S01-003 "`traefikresolverid` scoping is unchanged"; `_iter_resolver_nodes` replaces the first-key heuristic | — |
| FR-6 | Run once and/or watch | Yes for PyPI; not in container (M5) | **fixed-by-E014** | S01-005 AC1–8 (init-resolved mode, `finish`/`halt`, warning on nothing to do) | Positive container proof is opt-in only (F-01). The run-once exit code is not an export-failure signal (F-07). |
| FR-7 | Debounce | Yes | satisfied-before | S01-007 AC8 re-runs the watch tests on watchdog 6 | — |
| FR-8 | Restart labeled containers | No (B1, M1, M6) | **fixed-by-E014** (design) | S01-001 (SDK 7.2, `use_context=False`, start-up check), S01-004 (`--restart-container` dest), S01-006 (defer, don't drop) | No mandatory live proof (F-01). There is still no change detection (BL-E012-008, open Medium), so every ACME write restarts every labeled container. The upgrade notes do not say so (F-02). |
| FR-9 | Dry run | Yes | satisfied-before, extended | S01-002 AC7, S01-006 dry-run AC, S01-001 "Dry run: unchanged" | — |
| FR-10 | CLI > env > file > default | Partial (M1, M2, log level) | **fixed-by-E014** | S01-004 (dest fix, derived dest/env checks, `LOGGING_LEVEL`, legacy/unknown-name WARNINGs) | `LOGGING_LEVEL` is env-only with no file key. This follows the existing `LOGGING_*` pre-settings family and is consistent with the precedence rule. |
| FR-11 | PyPI package + Docker image (linuxserver, s6, PUID/PGID) | Yes | satisfied-before; first live release by S02-005 | S02-001/002/005 | **contradicted (pre-E014, recorded):** "PUID/PGID" was replaced by ADR-0030 (root unless the store is proven readable). E014 keeps this, and S02-005 AC2 documents it for upgraders. |

### §4 Non-functional requirements

| PRD | Requirement | After E014 | Story / evidence | Notes |
|---|---|---|---|---|
| NFR-1 | No key or passphrase in logs | satisfied-before; reinforced | S01-002 security notes (passphrase never logged), S01-004 (legacy/unknown WARNINGs never echo values, tested), S01-008 (per-element list redaction, tested) | review-product m4 (`postexportcommand` logged verbatim) has no story and no backlog key (F-11). |
| NFR-2 | Loud misconfiguration | satisfied-before; reinforced | S01-001 AC7 (start-up ERROR when the Engine is unreachable, continues by design), S01-004 (legacy/unknown names, invalid `LOGGING_LEVEL` WARNING), S01-005 AC5 (WARNING on nothing to do) | Continuing after the ERROR/WARNING is a recorded choice in each story. |
| NFR-3 | `pip install` with no missing imports | **fixed-by-E014** (undeclared `pyyaml`) | S01-007 AC1 and AC5 (derived declared-vs-imported test) | S01-001 AC8 vs S01-007 AC1 can reintroduce an undeclared `requests` import (F-10). Only one interpreter of the declared `>=3.10,<3.15` range is verified at release (F-08). |
| NFR-4 | CI builds and publishes on every tagged release | satisfied-before (E013); first live run S02-005 | S02-001, S02-002, S02-005 AC3–8 | **weakened (maintainer decision 2026-10-10 (3) / 2026-10-11 (1)):** a partially configured destination is skipped with a warning and the run stays green (F-05). |
| NFR-5 | Regressions caught before release | satisfied-before; blind spots fixed | S01-001 AC3–5 (unmocked SDK tests), S01-002 AC8 (real chain fixtures), S01-003 fixtures (a)–(d), S01-005 AC2–3 (script tests) | The real-daemon test (S01-001 AC6) and the container smoke test (S01-005 AC7) are opt-in, and no story requires a recorded run of them (F-01). |
| NFR-6 | Traceable/structured logs | satisfied-before | S01-001/002/006 keep `correlation_id`; S01-006 rebinds it on deferred restarts; S01-008 makes the settings dump multi-line | **still-gap (minor):** review-product m7 (Apprise/urllib3 loggers disabled, so notification failures are invisible) is only partly tracked by BL-E011-017 (F-11). |
| NFR-7 | First boot yields a usable config | satisfied-before | S01-004 adds a logging note to the seed `config.yaml.sample` | review-product m1 (`docs/operational.md:100-104` still calls the seed a known bug) is not in any story or the backlog (F-11). |

### §5 Out of scope (checked for contradiction)

| Item | E014 effect |
|---|---|
| No metrics/health endpoint | Unchanged. S01-005 non-goal "No `HEALTHCHECK`". Consistent. |
| Only Traefik ACME JSON | Unchanged. S01-003 widens the CA support, not the store types. Consistent. |
| No Kubernetes-native mode | S01-005's outcome mentions running the image as a Kubernetes Job. That is a generic container use, not a K8s-native mode. Consistent. |
| Single instance per data path | S01-006 deferral timers are process-local (non-goal: no persistence). Consistent. |

### §6 backlog items and capabilities without a PRD row

| Item | After E014 | Story |
|---|---|---|
| 1–12, 15–18, 20 | satisfied-before (review-coherence §2) | Reinforced by: #3 S01-007 (cryptography 50.0.2), #4 S02-001/002, #5 S01-001/002/003, #6 S01-004 (seed note), #10 S01-004 (env names), #12 S01-008 (`-c` help text), #15 S02-003, #20 S01-002 (generated chain, no captured material) |
| 13 Digest pin + privilege ADR | satisfied-before; the privilege model was reversed by ADR-0030 (pre-E014) | S01-007 AC7 moves the digest; S02-005 AC2 documents the privilege model |
| 14 Current action versions + Dependabot | satisfied-before; extended | S02-001 AC6–7 (SHA-frozen hooks, Dependabot `pre-commit`), S01-007 (watchdog 6, docker 7.2) |
| 19 GitHub secret scanning / push protection | **still-gap, untracked** | None. S02-005's forge checklist omits it (F-06). |
| 21 Metrics/health | still-gap (candidate; out of scope) | None |
| 22 SANs export decision | **still-gap (undecided)** | S01-003 non-goal calls it "undecided". review-coherence says it was decided by deletion in E006, with no record (F-12). |
| 23 `--once` / exit-code contract | **partial** | S01-005 makes the container exit with the pass's exit code, but keeps export failures at exit 0 (non-goal) (F-07). |
| — PKCS12 passphrase (no PRD row) | fixed-by-E014 | S01-002 |
| — Post-export hook / Apprise notifications (no PRD row) | satisfied-before; **contract changed** | S01-002 AC5 and S01-003 change what "exported domains" means (reported iff an artifact was replaced; union across resolvers; ADR-0014 amended). The upgrade notes do not require this to be stated (F-03). |
| — Docker operator experience | fixed-by-E014 | S01-004 (compose/README names, `LOGGING_LEVEL`), S01-005 (run-once, `restart: "no"` docs), S01-001 (`docs/operational.md` restart runbook) |
| — Config precedence | satisfied-before; unchanged | S01-004 non-goal "Does not change precedence" |
| — Release pipeline / destinations | fixed-by-E014 | S02-001, S02-002, S02-005 |

**Contradictions introduced by E014: none.** FR-11's "PUID/PGID" contradiction predates E014 (ADR-0030). NFR-4 is weakened by an explicit maintainer decision.

## 2. Backward trace: stories → PRD / decisions

| Story | PRD requirement(s) | Maintainer decision / other provenance | Scope creep? |
|---|---|---|---|
| S01-001 Docker SDK 7.2 | FR-8, NFR-5, NFR-3 (runtime-compatible deps) | review B1 | No |
| S01-002 PKCS12 | FR-2, FR-9, NFR-1, NFR-5, §6 #20 | review B2, M4; amends ADR-0014/0023/0024 | No |
| S01-003 ACME parsing | FR-1, FR-5, NFR-5 | review M3/M4; BL-E011-018; **decision 2026-10-11 (ACME size cap dropped)** | Partly: CA-agnostic support goes beyond "v1/v2". Acceptable as a correctness fix, because the PRD purpose is "ACME certificates". |
| S01-004 Settings | FR-10, FR-8 (flag), NFR-2, NFR-7 (seed note) | review M1/M2; BL-E013-042, BL-E011-032; **decision 2026-10-11 (4)** (legacy-name detection) | `LOGGING_LEVEL` and the unknown-name suggestions are new surface. Acceptable: operator UX for FR-10, and maintainer-requested. |
| S01-005 Run-once | FR-6, FR-11, §6 #23 (partial) | review M5 | No |
| S01-006 Cooldown defer | FR-8 | review M6; BL-E012-004; BL-E011-016/RT-009 | The cooldown has no PRD row. It is security-driven (rate floor), so this is acceptable. |
| S01-007 Deps + pip-audit | NFR-3, §6 #13 (digest), #14 (current versions) | review m8; research §8 advisories | The pip-audit gate has no PRD row. Acceptable as security/supply-chain hygiene. |
| S01-008 CLI hygiene | NFR-1 (list redaction keeps masking), §6 #12 (stale help text) | BL-E011-033..036 (moved from E012-S01-004) | **Yes, mild:** operator-UX polish with no FR. Acceptable: small, tested, and already backlogged at Medium. |
| S02-001 CI hardening | NFR-4, §6 #14 | **decisions 2026-10-10 (1), (2); 2026-10-11 (3)** | Supply-chain items (hash-checked Poetry, wheel hash hand-off) go beyond NFR-4. Acceptable: security. |
| S02-002 Destination gating | NFR-4 | **decisions 2026-10-10 (3), 2026-10-11 (1)** | No (it weakens NFR-4 by decision, F-05) |
| S02-003 Record repair | §6 #15 (docs) | review-coherence CO-01..10, M7, M8; F-04/05/06/08/12/13 | No PRD requirement. Acceptable: record hygiene. It excludes the PRD itself (F-04). |
| S02-004 Close E012 / triage | none | review-coherence CO-03/04/14/15/16 | **Yes:** pure state and process hygiene, no product requirement. Acceptable: it gates a truthful state before release. It should also file the untracked review MINORs (F-11). |
| S02-005 Release 0.3.0 | FR-11, NFR-4 | **decisions 2026-10-10 (2); 2026-10-11 (2), (3), (4)** | No |

Decision coverage check (memlog): 2026-10-10 (1) → S02-001 AC6–7. (2) → S02-001 AC4 and S02-005 AC3/7. (3) → S02-002. 2026-10-11 (1) → S02-002 AC4. (2) → S02-005 (topologies, double-publish rule). (3) → S02-001 AC4 and S02-005 AC2. (4) → S01-004 (detection) and S02-005 AC2 (table plus test). ACME cap dropped → S01-003. **All covered.**

## 3. Acceptance-criteria quality against PRD thresholds

The PRD states no numeric performance thresholds, supported-Python list, platform list or CA list. Its measurable expectations are the NFRs, the FR formats and `pyproject.toml`'s declared range (`python = ">=3.10,<3.15"`). Results:

| Expectation | Reflected in story ACs? | Gap |
|---|---|---|
| File formats (FR-2/FR-3): PEM set + PKCS12, both layouts | Yes. S01-002 AC1–6 with byte-level and round-trip assertions | PKCS12 encryption is now AES-256/SHA-256. The consumer floor (Windows 10 1709+/Server 2019+) appears only in S01-002's release-note text and README, not in the upgrade-notes AC (F-03). |
| CA support (FR-1) | Yes. S01-003 fixture (a) is ZeroSSL; shape detection is URI-independent | Only one non-LE fixture. That is adequate, because detection no longer reads the URI. |
| Supported Python versions (`>=3.10,<3.15`, NFR-3) | **No.** S01-007 relies on one gate interpreter (`tomllib`/`tomli` note); S02-005 AC6 installs in "a fresh venv" with no version | After major dependency bumps (watchdog 6, cryptography 50, docker 7.2), the declared range is not verified at either end (F-08). |
| Platforms (FR-11 image) | Partly. S02-005 AC7 checks that the manifest lists `linux/amd64`/`linux/arm64` | arm64 is never run. The pipeline `docker-test` runs only the pushed digest on the runner's architecture (F-08). |
| Restart works (FR-8, the headline 0.3.0 fix) | Only negatively (missing-socket tests, S01-001 AC3–5). The positive test (S01-001 AC6) is opt-in, and no AC requires a recorded run | **F-01** |
| Container run-once (FR-6) | Script-level tests (S01-005 AC2–3). The image smoke test (AC7) is opt-in; S01-007 AC7 runs it only if s6-overlay changed | **F-01** |
| NFR-1 at release | Unit-tested in S01-002/004/008 | S02-005 does not check a DEBUG run of the released image. Acceptable, given the unit coverage. |
| NFR-3 at release | S02-005 AC6 `pip install` + `--help` from PyPI and Gitea | One interpreter only (F-08). |
| NFR-4 | S02-005 AC5 (each destination enabled exactly once, zero warnings) | For 0.3.0 only. Later releases rely on prose (F-05). |
| NFR-7 first boot | Not in S02-005 | The pipeline `docker-test` starts the image but does not assert `/config/config.yaml` was seeded. Minor, folded into F-01's remediation. |
| Operator UX (docs/env names) | Strong. S01-004 derived env-name and dest checks, the legacy-map coverage test, and S02-005's `test_upgrading_lists_every_legacy_name` | — |

**PRD NFRs that S02-005 should verify but does not:** FR-8 positive restart and FR-6 run-once on the release-candidate image (F-01); NFR-3 across the declared Python range (F-08); NFR-7 seed on the released image (F-01 remediation); PRD #19 forge setting (F-06).

## 4. 0.3.0 user-facing change list vs the upgrade-notes story (S02-005 AC2)

| # | Change (source story) | Breaking / behaviour change? | Required by S02-005 AC2? |
|---|---|---|---|
| 1 | Privilege model: root unless the ACME store is proven readable (ADR-0030, pre-E014) | Yes (vs v0.2.0 PUID/PGID drop) | **Yes** ("Privilege model") |
| 2 | Env names corrected to `…_SETTINGS_<KEY>`; compose sample fixed; `version:` removed (S01-004) | Yes, for anyone who copied the samples | **Yes** |
| 3 | Legacy/misspelled names produce a start-up WARNING and are ignored; unknown names get a suggestion (S01-004) | New log output | **Yes** (table plus test) |
| 4 | `--restart-container` now takes effect (S01-004) | Yes: restarts start happening | **Yes** (as a fix) |
| 5 | `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL`; `-ll` default resolution; INFO line naming the level source (S01-004) | Additive | **Yes** ("the log-level setting") |
| 6 | Restarts actually happen (SDK 7.2). With RUNATSTART=true (image default), **every exporter start restarts every labeled container**. **Every ACME write restarts every labeled container** whose domain is in the store, because there is no change detection (BL-E012-008) (S01-001) | **Yes:** a 0.2.x deployment with labels and `restartcontainers: true`, previously a silent no-op, starts restarting containers on upgrade | **Mentioned only as "the Docker SDK 7.2 restart path"; the consequence is not required (F-02)** |
| 7 | Docker client ignores the Docker CLI context; Engine API ≥ 1.24 floor; one start-up ERROR when unreachable (S01-001) | Behaviour change for PyPI installs on workstations with contexts | **No (F-03)** |
| 8 | Cooldown defers instead of dropping: a second write inside 5 minutes now yields a trailing restart (S01-006) | Yes (more restarts) | **Yes** ("Restart cooldown") |
| 9 | Passphrase works; PFX is AES-256/SHA-256 when encrypted (consumer floor); PFX includes intermediates; single-cert `cert.pem`/`chain.pem` fixed; empty passphrase = unencrypted (S01-002) | Yes (PFX content and encryption) | **Partly:** passphrase and intermediates are required; the AES-256 consumer floor and the `chain.pem` change are not (F-03) |
| 10 | Exported-domain contract: a domain is reported iff an artifact was replaced, including partial writes; one resolver's failure no longer drops another's domains; malformed domains keep their old files (S01-002/003) | Yes, for hook (`EXPORTED_DOMAINS`) and notification consumers | **No (F-03)** |
| 11 | Non-LE CAs exported; `Certificates: null` tolerated; invalid base64 fails per certificate (S01-003) | Additive/fix | **Yes** ("CA-agnostic ACME parsing") |
| 12 | Container run-once: the container now **exits** after one pass with the pass code; `restart: always` turns it into a container loop; use `restart: "no"` (S01-005) | **Yes** for anyone running `WATCHFORCHANGES=false` | **Mentioned only as "the container run-once behaviour"; the restart-policy guidance is not required (F-03)** |
| 13 | Dependencies: `requests`, `docker-pycreds`, `expandvars` no longer installed; `pyyaml` declared; watchdog 6, urllib3 ≥ 2.8 (S01-007) | Possible break for anyone importing those transitively from the same venv | **No (F-03)** |
| 14 | CLI: typo suggestions, `--help` pointer, metavars, `-c` help text; settings dump now multi-line JSON; list redaction keeps scheme and count (S01-008) | Cosmetic; log scrapers of the one-line dump change | **No** (acceptable to omit; list it for completeness) |
| 15 | Image tags: `0.3.0`, `0.3`, `latest`; no `:0` for 0.x; `:0` frozen; `:1` automatic at 1.0 (S02-001) | Yes for anyone pinned to `:0` | **Yes** ("Versioning and image tag naming") |
| 16 | Publication: PyPI, Gitea index, GHCR, Docker Hub, Gitea registry; releases from either forge; double-publish rule (S02-001/002/005) | Maintainer-facing | **Yes** ("Where releases come from") |
| 17 | Base image digest refreshed (S01-007) | No | No (acceptable) |

**Every breaking change covered? No.** Rows 6, 7, 10, 12 (guidance) and 13 are operator-visible behaviour changes that AC2 does not require. Row 9 is only partly required. Root cause: AC2 is a hand-written topic list. Each story already carries a "0.3.0 release notes" block, and S02-005 decision 4 rules out the forge release body as their home, so those bullets currently have **no destination**. That is F-02 and F-03.

## 5. PRD staleness (after E014)

| PRD location | Stale statement | Correct state (source) |
|---|---|---|
| Front matter / intro | `status: final`, `updated: 2026-08-30`; "reverse-engineered from v0.1.3"; points at `epics.md` (ends at Epic 10) and the product spine only | Released line is 0.3.0; CI/CD spine 2026-10-08; backlog in `state/issues.yaml` |
| FR-1 | "legacy (v1) and current (v2)" shapes, evidence `__exportCertificate` | Shape-based, CA-agnostic, null-safe, per-resolver isolation (S01-003) |
| FR-2 | No passphrase or intermediates semantics | PKCS12 with intermediates, AES-256 when a passphrase is set, build-before-replace, reporting contract (S01-002, new ADR) |
| FR-6 | Evidence `app.py` only | Container run-once via the s6 `finish`/`halt` contract (S01-005, new ADR) |
| FR-8 | No cooldown; SDK unspecified | 300 s per-container rate floor with deferred trailing restart (S01-006 ADR); `use_context=False`; start-up reachability check (S01-001) |
| FR-10 | No log-level env; evidence `loadFromFile` | `LOGGING_LEVEL` env; legacy/unknown-name WARNINGs (S01-004) |
| FR-11 | "PUID/PGID" | ADR-0030 as amended (root unless proven readable); destinations PyPI/Gitea/GHCR/Docker Hub; 0.x tag scheme |
| Missing FR rows | — | PKCS12 passphrase; post-export hook; Apprise notifications; exported-domain reporting contract; atomic writes; legacy-setting detection (review-coherence §2, CO-11) |
| §4 NFR "Current state" | NFR-1..7 all "Violated"/"Unmet"; NFR-5 "zero automated tests" | All delivered (review-coherence §2). New implied NFRs: no known-vulnerable locked dependency (pip-audit, S01-007); declared deps = imports (S01-007) |
| §5 | — | Add "no ACME store size cap: trusted input, `/data:ro`" (decision 2026-10-11) |
| §6 | Only #16 and #19 struck; #11 cites removed `build-container.yaml`; #19 says "still open"; #22/#23 undecided | #1–18 and #20 delivered (review-coherence §2); #19 still open (F-06); #22 decided by deletion without a record (F-12); #23 partial (F-07) |

**Should S02-003 update it?** S02-003 lists "Does not rewrite the PRD (CO-11)" as a non-goal and files no backlog item for it. A full rewrite through `bmad-prd` (update intent) can reasonably wait until after 0.3.0. But S02-003's purpose is that any reader "reaches the rule that the shipped code and pipeline actually follow". After E014 the PRD is the one planning document that still asserts false current state (all NFRs "Violated", FR-11 "PUID/PGID"). Recommendation (F-04): S02-003 adds a dated banner and a "status as of 0.3.0" column to §3/§4/§6 with story/ADR refs, a cheap documentation-only edit. Failing that, it files a Low backlog item with `pm-status append-issue` so the deferral is tracked.

## Findings

| ID | SEVERITY | Story | Finding | Evidence | Remediation |
|---|---|---|---|---|---|
| F-01 | MAJOR | S02-005 (also S01-001, S01-005, S01-007) | No E014 story requires recorded positive end-to-end evidence for the 0.3.0 headline fixes: a real labeled container restarted (FR-8), the container run-once exit (FR-6) and a passphrase PFX from the built image (FR-2). The real-daemon test (S01-001 AC6) and the container smoke test (S01-005 AC7) are opt-in (`TCE_DOCKER_INTEGRATION=1`) and skipped in CI. Only S01-007 AC7 may run the smoke test, and only if s6-overlay changed. S02-005 verifies install, `--help`, digests and the generic `git-action-docker-test`. B1 shipped exactly because the gate was green while the feature could not work. | S01-001 AC6 / Testability ("Run it with …", no evidence AC); S01-005 AC7; S01-007 AC7 "If it is no longer 3.2.1.0"; S02-005 AC6–7; `.github/workflows/release.yaml:324-329` (generic docker-test) | Add an S02-005 precondition AC: before tagging, run `TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration` against `just image` built from the release commit (restart + run-once), and add a passphrase PFX export through the image. Paste the output into the evidence file. Optionally require a recorded integration run in S01-001 and S01-005 DoD. |
| F-02 | MAJOR | S02-005 (from S01-001/S01-006) | The upgrade notes do not warn that container restarts start happening in 0.3.0. In 0.2.x `restartcontainers` was a silent no-op (B1, M1). After upgrade, with the image default RUNATSTART=true, every exporter start restarts every labeled container. Every ACME write (any domain's renewal) restarts every labeled container in the store, because no change detection exists (BL-E012-008 open). S01-006 adds a trailing restart for a second write inside 5 minutes. Operators who set labels long ago get unannounced restarts. | S02-005 AC2 "Also: the Docker SDK 7.2 restart path"; `libs/docker.py:18-23` ("a drain pass reports every domain it exported, changed or not"); S01-006 non-goal "No per-domain change detection"; S01-002 AC5 contract (reported iff replaced, and files are always replaced) | Add a required "Restarts now take effect" upgrade-notes item: what triggers a restart (start-up pass, any store write), the 5-minute floor with a trailing restart, and how to opt out (`restartcontainers: false`, remove labels, `RUNATSTART=false`). Cite BL-E012-008 as the open limitation. |
| F-03 | MAJOR | S02-005 | The upgrade-notes AC is a hand-enumerated topic list, not derived from the stories. Each S01 story carries a "0.3.0 release notes" block, and S02-005 decision 4 rules out the forge release body, so those bullets have no destination. Omitted operator-visible changes: the exported-domain/hook/notification contract change (S01-002/003, ADR-0014 amended); run-once exits plus the `restart: "no"` guidance (S01-005); PKCS12 AES-256 consumer floor and the `chain.pem` change (S01-002); Docker CLI context ignored and Engine API ≥ 1.24 (S01-001); removed `requests`/`docker-pycreds`/`expandvars` (S01-007). | S02-005 AC2 bullets vs the "0.3.0 release notes" blocks in S01-001..008; S02-005 enricher decision 4 | Change AC2 to: every "0.3.0 release notes" bullet in E014-S01-001..008 and S02-001 appears in `docs/upgrading.md` or is listed in the evidence as internal-only, with a reason. Record the cross-read in the evidence file. Global rule 4 favours deriving the list from the stories over a hand-kept list. |
| F-04 | MINOR | S02-003 | The PRD stays stale (status `final`, NFRs "Violated", FR-11 "PUID/PGID", no FR rows for hook, notifications, passphrase or reporting contract). S02-003 excludes it (CO-11) and files no backlog item, so the deferral is untracked. | S02-003 Non-goals "Does not rewrite the PRD (CO-11)"; S02-003 AC10 lists only three new Low items; §5 above | Either add a banner plus a "status as of 0.3.0" column (doc-only) in S02-003, or add a fourth `append-issue` (Low, "PRD refresh via bmad-prd update") to S02-003 AC10. |
| F-05 | MINOR | S02-002 | NFR-4 ("must publish on every tagged release") is weakened by decision. A partially configured destination is skipped with a warning and the release run is green. S02-005 AC5 requires zero warnings for 0.3.0 only. For later releases the safeguard is the prose instruction "read the run's warnings before announcing", which is not mechanical (global rule 3). | S02-002 AC8 ("The walkthrough tells the maintainer to read the run's warnings"), Non-goals "Does not make a skipped destination fail the run"; memlog 2026-10-10 (3) | Record the NFR-4 trade-off and the release-checklist step ("zero destination warnings, each target enabled once") in the E014 pipeline ADR (S02-003), stating that it is not mechanically enforced. Keep it in the walkthrough's per-release checklist, not only in S02-005. |
| F-06 | MINOR | S02-005 | PRD §6 #19 (enable GitHub secret scanning / push protection) was never delivered or tracked (CO-12). S02-005's maintainer forge checklist, which already verifies rulesets and Actions permissions, omits it. | `prd.md` §6 #19; review-coherence CO-12; S02-005 Files in scope checklist | Add a checklist item: `gh api repos/{owner}/{repo} --jq .security_and_analysis` shows `secret_scanning` and `secret_scanning_push_protection` enabled. Or file it with `append-issue`. |
| F-07 | MINOR | S01-005 | The outcome and release note claim the run-once image is "usable from cron, a systemd timer or a Kubernetes Job", but a non-goal keeps export failures at exit 0 (only a missing data path gives 1). PRD #23's scriptable exit-code contract remains undelivered, and the claim overstates it. | S01-005 Business outcome vs Non-goals "Does not make export failures produce a non-zero exit code"; PRD §6 #23 | Qualify the outcome and release note ("exit code reflects start-up failures only; export failures are logged"). File PRD #23 as a backlog item. |
| F-08 | MINOR | S02-005 (S01-007) | The declared Python range (`>=3.10,<3.15`) and arm64 runtime are not verified after major dependency bumps (watchdog 6, cryptography 50, docker 7.2). S02-005 AC6 installs in one unspecified venv. AC7 checks only that arm64 is listed in the manifest. | `pyproject.toml:15`; S01-007 AC5 (gate interpreter only); S02-005 AC6–7 | In S02-005 AC6, install and run `--help` on 3.10 and 3.14 (the range ends). In AC7, run the image once with `--platform linux/arm64` (qemu acceptable), or record that only amd64 is exercised. |
| F-09 | MINOR | S01-008 (vs S01-004) | S01-004 requires S01-008 to call the shared `suggest.nearest_name` so env and flag suggestions behave identically (maintainer decision 2026-10-11, "consistent with S01-008"). S01-008's ACs specify `difflib.get_close_matches` directly, and its Files in scope omit `libs/suggest.py`. | S01-004 Context "Interaction with E014-S01-008"; S01-008 AC BL-E011-034, Files in scope | Amend the S01-008 AC to call `suggest.nearest_name` and add `libs/suggest.py` to its file list. |
| F-10 | MINOR | S01-001 (vs S01-007) | S01-001 AC8 classifies "`requests` connection errors" as expected failures. If that is implemented with `import requests`, S01-007 AC1 (remove `requests`) and AC5 (every import declared) conflict, which reintroduces NFR-3's undeclared-direct-import class. The derived test would catch it, but the stories do not say which way to resolve it. | S01-001 AC8; S01-007 AC1, AC5 | State in S01-001 that the handler catches `docker.errors.DockerException` and `OSError` (`requests.RequestException` subclasses `IOError`) without importing `requests`. Otherwise S01-007 keeps `requests` declared. |
| F-11 | MINOR | S02-004 | Review-product MINORs that touch PRD requirements have no E014 story and no backlog key: m1 (`docs/operational.md:100-104` calls the fixed NFR-7 seed a known bug), m4 (`postexportcommand` logged verbatim, NFR-1 spirit; S01-008 calls it "a separate item"), m5 (symlink parent), m10 (no health-deferral ADR), m11. m7 (Apprise loggers disabled, NFR-6) is only partly covered by BL-E011-017. | review-product.md m1, m4, m5, m7, m10, m11; open backlog titles in `state/issues.yaml`; S01-008 Non-goals | Add to S02-004 AC5: `append-issue` for m1, m4, m5, m10 and m11, and link m7 to BL-E011-017, so every review finding has a key before release. |
| F-12 | MINOR | S01-003 / S02-003 | PRD #22 (SANs export) is treated as "undecided" (S01-003 non-goal), while review-coherence says E006 decided it by deletion with no record. The decision is in neither the spine Conventions list in S02-003 AC5 nor any ADR. | S01-003 Non-goals "PRD #22 is undecided"; review-coherence §2 row 22 | S02-003 records the decision (SANs are logged, not exported) in the product spine Conventions, or files it for the PRD refresh (F-04). |

**Counts:** BLOCKER 0 · MAJOR 3 · MINOR 9.

## Assumptions

- The PRD sets no numeric performance, platform or CA thresholds. "Supported Python" is taken from `pyproject.toml:15`, and "platforms" from the multi-arch decision (AD-10).
- F-02's claim that every pass reports every domain rests on `libs/docker.py:18-23` (code comment) and S01-002 AC5 (reported iff an artifact was replaced, with `_atomic_write*` always replacing). No skip-if-unchanged write was found by grep in `certificate_exporter.py`.
- "Untracked" in F-04/F-06/F-11 means no open key in `state/issues.yaml` matched by title (listing of non-resolved items, 2026-10-11).
- The 0.3.0 release-notes bullets in each story were treated as the authoritative statement of user-facing change.

Sections read: prd.md (full); E014-S01-001 (full), S01-002 (full), S01-003 (Context through Interface contracts), S01-004 (full), S01-005 (Context through Error handling), S01-006 (Context through Interface contracts), S01-007 (Context through Error handling), S01-008 (Context through Interface contracts, Files in scope), S02-001 (Context through Interface contracts), S02-002 (Context through Interface contracts), S02-003 (full), S02-004 (Context through Interface contracts), S02-005 (full); review-product.md (full); review-coherence.md §2 PRD coverage and CO-11/CO-12 rows; `.memlog.md` 2026-10-09..2026-10-11 entries; `state/issues.yaml` (open items: key, severity, status, title); `libs/docker.py:12-40`; `pyproject.toml` Python constraint; `release.yaml:322-334`, `build.yaml:126-132`; env-name grep over `docker/` and `src/`.
