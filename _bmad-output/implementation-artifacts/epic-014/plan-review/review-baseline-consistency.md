# Baseline consistency review — consolidated 0.3.0 PRD + spines vs E014 stories

Date: 2026-10-11. Read-only cross-check of the baseline consolidated on 2026-10-11.

## Verdict

**CONSISTENT WITH FIXES: 1 High, 5 Medium, 13 Low; no blocker.** Every FR and NFR traces to at least one AD, and the memlog decisions all appear in rule text or Deferred with the same meaning. Both spines lint clean. One rule competes across the two spines (ShellCheck / s6 hook, C-01). The product spine also does not record the Poetry bootstrap exception (C-02). The PRD's FR-17 forge wording is looser than CI AD-9 (C-03). The product spine's `binds:` and Capability map stop at FR-11 (C-04). One story still describes the old restart input (C-05). E014-S02-003 is now largely redundant for the PRD and spines, but it is still needed for ADRs, docs, AGENTS.md and the closure note.

Lint: `uv run .claude/skills/bmad-architecture/scripts/lint_spine.py --workspace <folder>` returned `"ok": true, "total_findings": 0` for both spine folders.

Header check:

| Document | "Target: 0.3.0" | Frontmatter `target` | Sources listed |
|---|---|---|---|
| PRD | yes, banner line 11 | `target: '0.3.0'` | yes, changelog lines 24–35 |
| Product spine | yes, body line 25 | **missing** (C-13) | yes, `sources:` and changelog |
| CI/CD spine | yes, line 39 | `target: '0.3.0 (pipeline after epic E014)'` | yes, `sources:` and changelog |

## FR/NFR → AD trace

P- = product spine AD, CI- = CI/CD spine AD. "Map row" means a product Capability map row that names the ID. "Story match" compares the PRD's status attribution with the stories and ADRs the AD cites.

| ID | PRD status (0.3.0) | Governing AD(s) | Map row | Story match | Note |
|---|---|---|---|---|---|
| FR-1 | Met by S01-003 | P-AD-7 | yes | yes (AD-7 cites S01-003) | |
| FR-2 | Met by S01-002 | P-AD-8 | yes | yes | |
| FR-3 | Met | P-AD-8, Conventions (artifacts) | yes | n/a | |
| FR-4 | Met | P-AD-6 (map only) | yes | n/a | AD-6 rule text has no include/exclude exclusivity clause (C-10) |
| FR-5 | Met by S01-003 | P-AD-7 (`traefikresolverid`) | yes | yes | |
| FR-6 | Met by S01-005 | P-AD-11, P-AD-12 | yes | yes (AD-12 cites S01-005) | "nothing to do" WARNING not in any AD (C-10) |
| FR-7 | Met | P-AD-11 | yes | n/a | |
| FR-8 | Met by S01-001, S01-006 | P-AD-10, P-AD-9 | yes | yes | Engine API ≥ 1.24 floor not in AD (C-10) |
| FR-9 | Met by S01-002 | P-AD-8, P-AD-10 | yes | yes | hook/notify dry-run skip not stated in AD-9 (C-10) |
| FR-10 | Met by S01-004 | P-AD-6, P-AD-3 (log level) | yes | yes | |
| FR-11 | Met by S02-005 (privilege: E012-S01-001, E013-S02-004) | P-AD-1, P-AD-2, P-AD-4, P-AD-5 → CI-AD-10 (multi-arch) | yes | yes (AD-2 cites ADR-0030) | |
| FR-12 | Met by S01-006 | P-AD-9, P-AD-3 | **no ID** (unnamed "Post-export hook, notifications" row) | yes | C-04 |
| FR-13 | Met by S01-006 | P-AD-9, P-AD-3 | **no ID** | yes | C-04 |
| FR-14 | Met by S01-002 | P-AD-8 (`BestAvailableEncryption`, PFX compare incl. encryption state) | **no** | yes | C-04 |
| FR-15 | Met by S01-006 | P-AD-10 (mtime > StartedAt + 2 s) | **no** | yes | C-04 |
| FR-16 | Met by S01-004 | P-AD-6 (`LEGACY_SETTING_NAMES`, warn and ignore) | **no** | yes | C-04, C-14 |
| FR-17 | Met by S02-002 (+S02-001, S02-005; ADR-0038/0039) | CI-AD-8, CI-AD-9, CI-AD-12, CI-AD-13 (via P-AD-5) | **no** | yes (CI sources list S02-001/002/005) | wording conflict C-03 |
| NFR-1 | Met by S01-006 (+S01-008) | P-AD-3 | yes | yes | |
| NFR-2 | Met by S01-004 (+S01-001, S01-005) | P-AD-6, P-AD-10 (ping), Conventions (errors) | yes | yes | "nothing to do" not in AD (C-10) |
| NFR-3 | Met by S01-007 (range ends: S02-005) | P-AD-1, P-AD-4; CI-AD-3 (deptry, pip-audit) | yes | partial: AD-1 cites only ADR-0001 (spine sources list S01-007) | |
| NFR-4 | Met by S02-005 (+S02-001, S02-002) | P-AD-5 → CI-AD-2, CI-AD-9, CI-AD-10, CI-AD-12 | yes (AD-5) | yes | |
| NFR-5 | Met by S02-005 (+S01-001/002/005/006) | Conventions (testing), P-AD-5 → CI-AD-3 | yes | yes | |
| NFR-6 | Met by S01-006 (+S01-008); BL-E011-017 open | P-AD-3 | yes | yes | open BL not in Deferred (C-11) |
| NFR-7 | Met | P-AD-2, P-AD-12 (map only) | yes | n/a | neither AD states the `/config/config.yaml` seed (C-10) |

Result: no ID is orphaned. Six FRs (FR-12 to FR-17) have no Capability map row by ID, and the product spine's `binds:` stops at FR-11.

## Memlog decision → spine check (2026-10-10 / 2026-10-11 entries)

| Decision | Spine location | Same meaning? |
|---|---|---|
| Restart trigger = newest artifact mtime > `StartedAt` + 2 s; bytes/content decide rewrite and reporting | P-AD-10, P-AD-8, Deferred (clock skew); PRD FR-15 | yes. The product memlog line 9 still says "byte comparison"; line 11 clarifies it, and the spine follows the clarification. |
| Hook and notifications only for changed domains | P-AD-9; PRD FR-12/13 | yes |
| Destination gating: unconfigured silent, partial one warning, enabled needs token + every variable | CI-AD-9, CI-AD-10 (no fail-fast guard), Retired list | yes. The 2026-10-10 (3) "visible warning" wording is correctly narrowed by 2026-10-11 (1). |
| One release run per tag; secrets on one forge only | CI-AD-9, CI-AD-13, Deferred (checklist) | yes in the CI spine. **PRD FR-17 is looser (C-03).** CI-AD-13 wording is ambiguous (C-18). |
| 0.x until stable, then v1 | CI-AD-7 | yes |
| No bare `:0`; existing `:0` frozen | CI-AD-8 (enable= gate, `workflows-major-tag-gated`) | yes |
| Third-party hooks SHA-pinned (`--freeze`) | CI-AD-3, CI-AD-5 | yes. The memlog says "Dependabot pre-commit ecosystem on GitHub" unconditionally; AD-5 makes it conditional on GA + `# frozen:` support, per S02-001 AC7 (C-12). |
| deptry / pip-audit gates | CI-AD-3; P-AD-1 (restated) | yes (overlap: C-09) |
| No ACME store size cap | P-AD-7 ("No store size cap"); PRD §5 | yes |
| Legacy and misspelled names warn and are ignored; upgrade notes | P-AD-6; PRD FR-16; CI-AD-12 (`docs/upgrading.md`) | yes (C-14 for the CLI source) |
| `runatstart` stays default-on (product memlog line 9) | not stated in either spine | not recorded. Low; folded into C-10. |

## Contradictions and gaps

| ID | SEVERITY | where | finding | fix |
|---|---|---|---|---|
| C-01 | High | Product AD-12 ("shell scripts pass ShellCheck"; pygrep hook `s6-no-raw-settings-env`); E014-S01-005 AC10/AC11; CI spine AD-3 required-hooks list and Deferred last bullet | The two spines compete. The product spine binds ShellCheck and the s6 pygrep hook, and S01-005 adds both "under AD-3's single hook list" and routes them into CI AD-3. The CI spine owns the hook list (product AD-5), but its AD-3 list names neither hook, and its Deferred says "ShellCheck hook … undecided". CI spine `sources` omit S01-005. A dev who follows the CI spine can drop the gate. | CI AD-3: add `shellcheck` (shellcheck-py, SHA-frozen, `files: ^docker/root/`, `types_or: [shell, executable]`) and `s6-no-raw-settings-env` (pygrep, `^docker/root/`) to the required hooks. Remove ShellCheck from that Deferred bullet (keep `.dockerignore`). Add S01-005 to CI `sources`. |
| C-02 | Medium | Product AD-1 vs CI AD-11 (and Structural Seed `.github/requirements/`); S02-001 AC9; S02-003 AC5 | Product AD-1 says `pyproject.toml` + `poetry.lock` are "the only declaration of runtime and dev dependencies; no other file hand-lists a package set". CI AD-11 introduces `.github/requirements/poetry.in`/`poetry.txt` as "the one bootstrap-only exception to ADR-0001". The product rule does not mention the exception, and S02-001 and S02-003 both expect product AD-1 to record it. | Append to product AD-1: "Exception: `.github/requirements/poetry.in`/`poetry.txt` (hash-locked, generated) installs Poetry only in CI, per CI AD-11; nothing else." |
| C-03 | Medium | PRD FR-17 vs CI AD-9 ("One release run per tag"), AD-13, ADR-0039 | FR-17 says releases can be cut from GitHub or Gitea and publish to every configured destination, with "each destination's credentials … on one forge only". CI AD-9 is stricter: every `PUBLISH_*` secret is on the one publishing forge, and an all-Gitea release can reach only Gitea destinations (Gitea never holds PyPI/TestPyPI/GHCR/Docker Hub tokens). So the full 0.3.0 destination set requires a GitHub release (S02-005 AC7 does this). | Reword FR-17: "All destinations of a release publish from one forge's run; every publish credential lives on that forge only. A release from Gitea can reach only the Gitea destinations; the full set (PyPI, GHCR, Docker Hub) is released from GitHub." |
| C-04 | Medium | Product spine frontmatter `binds:`; Capability map | `binds:` lists FR-1..FR-11 only. The Capability map has no row by ID for FR-12..FR-17: FR-12/13 sit under an unnamed row, FR-14, FR-15 and FR-16 have no row, and FR-17 is not routed to the CI spine. Check 1 therefore fails for six IDs at the map level, although each is governed in rule text. | Add FR-12..FR-17 to `binds:` (FR-17 via AD-5). Add rows: FR-12/13 → AD-9, AD-3; FR-14 → AD-8; FR-15 → AD-10; FR-16 → AD-6; FR-17 → AD-5 → CI AD-8/9/12/13. |
| C-05 | Medium | E014-S01-001 Context, "Which domains reach the restart path" (line 41) | It says `restartLabeledContainers` "receives only the domains whose exported artifacts changed". That contradicts P-AD-10, FR-15 and S01-006's interface `restartLabeledContainers(artifactMtime)`, which is called on every pass, including passes with no change. | Reword: "S01-006 changes the call to `restartLabeledContainers(exporter.artifactMtime)` on every pass (FR-15, AD-10); this story only makes the call reach the Engine." |
| C-06 | Medium | E014-S02-003 AC10, decision 10, Context row "PRD staleness", Files in scope (prd.md), AC11 "full PRD refresh" item | The planned PRD banner and "Status as of 0.3.0" column already exist. The banner text AC10 prescribes ("requirements text predates E011–E014") is now false. AC10 also says "§6 #19 and #23 stay open", but the consolidated §6 records #19 as a checklist item and #23 as a backlog item filed by S01-005. Executing AC10 as written would make the PRD wrong. | See the triage below. Replace AC10 with a post-merge update of the existing Status column. Drop the "full PRD refresh" backlog item. |
| C-07 | Low | Routing targets in S01-001 (FR8 row), S01-002 and S01-003 (Conventions "Data & formats"), S01-004 (Conventions "Naming"), S01-005 AC11 ("product spine AD-2: container service model"), S01-006 (Capability map FR8 "restart contract"), S02-003 decision 8 | These targets use the pre-consolidation spine layout. The content now lives in P-AD-10 (restart contract), P-AD-12 (service model), P-AD-6 (legacy policy) and P-AD-7/P-AD-8 (parsing, artifacts). Following the notes literally would duplicate rules into the map and Conventions. | In each routing AC, retarget to the consolidated AD, or say "verify AD-x matches; route only deltas and the ADR citation". |
| C-08 | Low | S02-003 decision 7; S02-005 Context line 93 | "Restarted only when a certificate it serves actually changed" is imprecise. Under FR-15 a container also restarts with no change in that pass (crash or lost-deferral recovery). S02-005 AC4 (line 128) is already exact. | Use FR-15 wording: "restarted when its domains' newest exported file is > 2 s newer than its start". |
| C-09 | Low | Product AD-1 (deptry DEP001–004, `per_rule_ignores`, pip-audit scope and `--ignore-vuln`) vs CI AD-3 | The product spine restates hook mechanics that product AD-5 says the CI spine owns. The wording agrees today, so the risk is drift only. | Keep the dependency rule in AD-1 and replace the hook mechanics with "enforced by the `deptry` and `pip-audit` hooks (CI AD-3)". |
| C-10 | Low | Product spine AD-6, AD-9, AD-10, AD-11/12, AD-2 | These PRD clauses have no AD rule text, only a map row: FR-4 include/exclude mutual exclusivity across surfaces; FR-6/NFR-2 one WARNING when run-at-start and watch are both off, and `runatstart` default-on (memlog); FR-8 Engine API ≥ 1.24; FR-9 hook/notify dry-run skip; NFR-7 first-boot `/config/config.yaml` seed. | Add one clause each: AD-6 (exclusivity), AD-12 (nothing-to-do WARNING, `runatstart` default), AD-10 (API floor), AD-9 (dry-run skip), AD-12 (config seed). |
| C-11 | Low | PRD NFR-6 (BL-E011-017 open); product spine Deferred | The open notification-delivery-failure visibility gap is not in Deferred. | Add a Deferred bullet citing BL-E011-017. |
| C-12 | Low | CI memlog 2026-10-10 (1) vs CI AD-5 | The memlog states a Dependabot `pre-commit` ecosystem on GitHub unconditionally. AD-5 conditions it on GA + `# frozen:` support (from S02-001 AC7). The spine is correct. | Add a memlog line recording the GA condition. |
| C-13 | Low | Product spine frontmatter | No `target:` key, unlike the PRD and the CI spine. | Add `target: '0.3.0 (product after epic E014)'`. |
| C-14 | Low | S01-004 AC (legacy WARNING source includes `command line`) vs FR-16 / P-AD-6 ("environment and config file") | The story is wider than the PRD and the spine. | Either add the CLI source to FR-16 and AD-6, or drop it from S01-004. Strict parse already rejects unknown flags. |
| C-15 | Low | PRD §6 #19 vs CI spine Deferred "Forge settings" list | The PRD makes GitHub secret scanning and push protection an S02-005 checklist item. The CI spine's forge-settings list omits it. | Add it to the Deferred forge-settings list (and the walkthrough checklist). |
| C-16 | Low | `docs/architecture.md:94` (link `prd.md#6-fix--upgrade--enhancement-backlog`); `AGENTS.md` "Where things are" (PRD §6 as backlog) | After consolidation, PRD §6 is "Backlog", a pointer plus a closed table. The anchor is broken and the AGENTS.md pointer is stale. | Name both explicitly in S02-003 AC3 (§5 pointer) and AC8. |
| C-17 | Low | S02-002 Context line 12 | It quotes retired AD-9 wording ("enabled exactly when its token secret is set"). It is marked "Today", but read alone it is a token-only enablement claim. | Prefix it with "pre-consolidation spine said:". |
| C-18 | Low | CI AD-13 "only when Gitea is the publishing forge for its destinations" | This reads as a per-destination forge choice, against AD-9's all-on-one-forge rule. | Reword: "only when Gitea is the publishing forge (AD-9)". |
| C-19 | Low | S02-003 decision 4 / S02-005 decision 1, "decision 2026-10-11 (3)" | In the CI memlog's 2026-10-11 list, (3) is 0.x→v1 and the forge rule is (2). The number apparently refers to the plan-review decision list. | Cite as "plan-review decision 3" or "memlog 2026-10-11 (2)". |

## E014-S02-003 AC triage

| AC / item | Disposition | Reason |
|---|---|---|
| AC1 ADR statuses (0030 Accepted + title, 0002 amended-by, 0003/0023/0024/0026/0027 Accepted, 0016/0017 superseded, 0028 note, 0035/0036/0039/0001 amended-by) | **Still needed** | Verified: 0003, 0023, 0024, 0026, 0027 and 0030 still read `Proposed`; 0016/0017 read "Superseded by scope". Not touched by the consolidation. |
| AC2 three new ADRs (E014 pipeline amendments, duplication, module layering) | **Still needed** | The CI spine (line 404) and product Deferred/AD-13 defer the record to "the ADRs E014-S02-003 writes". Rewording: the decision-4 content now exists as CI spine rule text, so the ADR records it and cites the AD rather than re-deriving it. Fix the C-19 citation. |
| AC3 `docs/architecture.md` §4/§5/§6/SDK mentions | **Still needed** | Verified: §4 still says `3.19` and PUID/PGID. Add the broken PRD §6 anchor at line 94 (C-16). |
| AC4 environment wording (README, operational, architecture §7; BL-E013-038) | **Still needed** | Docs not touched. |
| AC5 product spine | **Mostly redundant; 3 sub-items still needed; rest needs rewording** | Redundant (already in the consolidated spine): AD-2 base 3.24 + digest + ADR-0030; AD-3 `LOGGING_LEVEL`; AD-4 implemented; AD-5 handed to the CI spine; Stack; Structural Seed; Design Paradigm/AD-13 layering; Conventions (SANs, artifacts, naming, signals); `updated:` bump. Still needed: (a) AD-1 Poetry bootstrap exception (C-02); (b) citations of the new ADRs (module layering, export-reporting, restart/cooldown, run-once) once written; (c) Capability map rows FR-12..FR-17 and `binds:` (C-04). Needs rewording: "AD-2 states the container service model" → already in AD-12; "Capability map rows FR1/FR6/FR8" → verify against AD-7/AD-12/AD-10 and add ADR cites only; "Conventions record each E014-S01 decision" → verify only; "correlation-id Deferred bullet is deleted" → the old bullet is gone and a "Cross-process correlation id" bullet remains, so confirm it does not contradict AD-3 and resolve BL-E011-041. |
| AC6 CI spine | **Mostly redundant; 4 items still needed** | Redundant: AD-3 pip-audit/deptry, AD-4 product-surface clarification, AD-5, AD-8, AD-9 (token + vars, `ANY_*`, one release run per tag), AD-10, AD-11, AD-12, AD-13, AD-14, AD-17/AD-18 step order, Conventions, Stack incl. pip-tools, Seed, F-08 ambient-token wording, F-13 live-certification bullet, SBOM/provenance reason, `updated:`. Still needed: (a) F-06: check the AD-2 step order against the post-E014 `build.yaml`; (b) F-12: add the new E014 ADRs to `companions`; (c) add `shellcheck` + `s6-no-raw-settings-env` to AD-3 and remove the Deferred contradiction (C-01); (d) the global-rule-3 enforcement-naming sweep, as a verification pass. Needs rewording: "one `.memlog.md` line per change" → the consolidation is one memlog event; write lines only for post-merge deltas. |
| AC6a routing table from notes files | **Still needed, reworded** | The notes files do not exist yet (stories in backlog) and may carry implementation deltas. Reword: each notes item is either "already in consolidated spine at AD-x" (cite the line) or applied as a delta. The "known items" list becomes a verification list, not an edit list. Retarget the old-structure targets (C-07). |
| AC7 `docs/guidelines.md` §10 hook table | **Still needed** | Verified: lines 169/175 still list `detect-private-key` and "mypy not yet added". |
| AC8 AGENTS.md refresh | **Still needed** | Verified: stamp "Verified 2026-08-30 against 6bdb516"; PRD §6 backlog pointer now stale (C-16). |
| AC9 E009 closure note | **Still needed** | Untouched by the consolidation. |
| AC10 PRD banner + "Status as of 0.3.0" column | **Redundant, and harmful as written** | The PRD already has the dated Target banner and the Status column. The prescribed banner text is false, and "#19/#23 stay open" contradicts §6. Replace it with: "after E014 merges, change 'Met by E014-…' to delivered (or 'open' with key), fill the #23 backlog key, bump `updated:`". |
| AC11 backlog via pm-status | **Still needed, minus one item** | Scheduling BL-E013-035/-040/-025 and BL-E011-041 and filing module-extraction, SBOM and register-repair items: still needed. The "full PRD refresh via `bmad-prd`" item is redundant. |
| AC12 `just check` + link check | **Still needed** | |
| Decision 7 (restart wording) | **Needs rewording** | Use the FR-15 mtime rule (C-08). The target is P-AD-10, not Conventions or the FR8 map row. |
| Decision 8 (legacy policy in Conventions "Naming") | **Redundant / needs rewording** | It already lives in P-AD-6; the Conventions row cross-references AD-6. |
| Decision 10 (PRD status, not rewrite) | **Redundant** | Done by the consolidation. |
| Context rows CO-05/M8 and "PRD staleness" | **Stale** | Mark them as resolved by the 2026-10-11 consolidation. |

Summary: still needed are AC1, AC2, AC3, AC4, AC7, AC8, AC9 and AC12, AC6a reworded, AC11 minus one item, and four CI-spine and three product-spine sub-items. Redundant are AC10, decision 10, most of AC5/AC6, and the PRD file in scope.

## Sections read

- `prds/prd-traefik-certificate-exporter-2026-08-30/prd.md`: all (front matter, banner/changelog, §1–§6).
- Product spine `ARCHITECTURE-SPINE.md`: all (front matter, Paradigm, AD-1..AD-13, Conventions, Stack, Seed, Capability map, Deferred, Changelog). `.memlog.md`: all 5 entries.
- CI/CD spine `ARCHITECTURE-SPINE.md`: all (front matter, Paradigm, AD-1..AD-18, Conventions, Stack, Seed, Retired/Superseded, Deferred, Changelog). `.memlog.md`: all, focused on lines 50–52.
- E014-S02-003: all. E014-S02-002: Context and AC 1–10, Business AC, Non-goals. E014-S02-001: AC 1–10. E014-S01-007: AC 1–10. E014-S01-006: Context lines 28–60, Plan review, AC excerpts (lines 116–162, 196–207), interface contracts, edge cases. E014-S01-002: Context lines 30–66, AC 5. E014-S01-001: Context lines 36–52, AC 1–3. E014-S01-003: AC lines 74–106, size-cap lines. E014-S01-005: AC 8–12. E014-S01-004: grep for legacy, unknown-name and precedence lines. E014-S01-008: grep for redaction lines. E014-S02-005: AC headings, decisions 1–5, AC 7–11. E014-S02-004: AC headings and the `uv.lock` row.
- Spot-verified in the repo: ADR status lines (0001–0003, 0016, 0017, 0023, 0024, 0026–0028, 0030, 0035, 0036, 0039); `docs/architecture.md:86,94`; `AGENTS.md:2`; `docs/guidelines.md:169,175`; `.gitignore` (no `uv.lock`, which S01-007 AC6 plans); `.pre-commit-config.yaml` (no shellcheck yet, which S01-005 AC10 plans).
- Lint: `lint_spine.py --workspace` on both spine folders returned ok, with 0 findings.
