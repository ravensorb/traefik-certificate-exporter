# Whole-solution review — lens 3 of 3: cross-epic coherence

- Date: 2026-10-10
- HEAD: 2139ad8
- Scope: E001–E013, three architecture spines, PRD, `docs/adr/` (38 files), `adr-register.yaml`, state tree, narrative docs
- Mode: read-only. The only file written is this report.

## Verdict

**COHERENT AT THE CODE AND CI LAYER, INCOHERENT IN THE RECORD.** The shipped repository tells one
story: four trigger-selected workflows (ADR-0035/0036), environment-held publish credentials
(ADR-0039), release only from protected tags on `main` (ADR-0038), no path exemption from secret
scanning (ADR-0033 → ADR-0037), and a container that keeps root unless it can prove the
unprivileged account can do the job (ADR-0030 as amended 2026-10-10). `docs/ci/pipeline-walkthrough.md`,
`docs/operational.md` §"Container privileges" and `docker/README.md` describe that story accurately.

The record around it does not. Five things are out of date: the ADR that governs the container
privilege model (ADR-0030: Status `Proposed`, title states the pre-amendment rule); the product
spine (AD-2, AD-5 and the Deferred list were never updated after 2026-08-30); the PRD, which
AGENTS.md still names as the backlog (status `final`, every NFR still "Violated");
the state tree (E012 is `in-progress`, with a superseded story and nine issues still scheduled
into retired work); and three operator-facing docs that omit the ADR-0039 environment requirement.
I found no BLOCKER: none of these defects changes what CI or the image does. Several would lead a
new maintainer to act on a superseded rule.

Counts: **BLOCKER 0 · MAJOR 7 · MINOR 14**

## 1. Decision lineage

| # | Date | Epic | Decision | Later fate | Coherence of the trail |
|---|---|---|---|---|---|
| 1 | 2026-08-30 | review | ADR-0001 Poetry | Live, carried forward | OK. A stray untracked `uv.lock` sits at the root (BL-E013-032). It comes from BMAD tooling run with `uv`, not from a migration. |
| 2 | 2026-08-30 | review | ADR-0002 linuxserver base + PUID/PGID privilege drop | **Amended by ADR-0030** (E012), and ADR-0030 itself was amended 2026-10-10 (E013-S02-004) | **Broken.** ADR-0002 has no back-reference to ADR-0030. The `docs/architecture.md:119` row omits "amended by 0030". `docs/architecture.md:86-87` and product-spine AD-2 (`ARCHITECTURE-SPINE.md:69-71`) still say "PUID/PGID privilege drop" and cite base `3.19`. The Dockerfile uses `3.24@sha256`. |
| 3 | 2026-08-30 | review | ADR-0003 logging + redaction | Implemented E004/E010; AD-3 amended by ADR-0023 | Status still **Proposed**. |
| 4 | 2026-08-30 → 09-01 | E002/E007 | ADR-0004 locked deps → ADR-0008 exact-wheel → amended by ADR-0035 (build-push-action, not bake) | Live | OK. Chain recorded at both ends. |
| 5 | 2026-08-30 | E002 | ADR-0005 reusable-workflow wiring → superseded by 0007 → 0007 superseded by 0035 | Retired | ADR OK. Product-spine AD-5 (`:101-112`) still binds `.github/workflows/*` and says "not yet implemented — docs/adr/0005". It has no supersession marker. |
| 6 | 2026-09-01 | E007 | ADR-0006 release-version transaction, ADR-0007 PR topology | Superseded by 0035 | OK. |
| 7 | 2026-09-02 | E008 | **Pinning:** ADR-0009 floating major by default, reviewed SHA for credential handlers | → ADR-0031 (E012-S01-002, every action SHA-pinned) → ADR-0035 (third-party SHA, `LiquidLogicLabs/*@vN` major tags, Dependabot renews) | Statuses are correct (0009 and 0031 both "Superseded by ADR-0035"). Residue: `docs/guidelines.md:72` still says ADR-0009's "accepted-risk entries rest on" LLL ownership, as if ADR-0009 were live. The risk that LLL major refs reach credentials is open as BL-E013-022/029, Medium/Low, but no live ADR records it as accepted. ADR-0035's acceptance is the only cover, and BL-E013-022 says it is exceeded. |
| 8 | 2026-09-02 | E008 | ADR-0010 forge release via one multi-platform action; ADR-0012 metadata action | Accepted, amended by 0035 | OK. |
| 9 | 2026-09-02 | E008 | ADR-0011 publication matrix/finalizer | Superseded by 0035 | OK. |
| 10 | 2026-09-06 | E010 | ADR-0013 event bus → superseded by ADR-0014 (Apprise on post-export) | Live | OK. |
| 11 | 2026-10-06 | E009 | ADR-0015..0022 Gitea runner trust class, tuple evidence, credential matrix, fault injection, classifier, action governance | 0015/0019/0020/0021/0022 superseded by 0035. 0016/0017 "**Superseded by scope**". 0018 still live. | **Delivered then undone.** E009 is archived `done` with no epic or sprint closure report and no retrospective (`epic-009/` has only `arch/` and two story reviews). "Superseded by scope" is not a supersession: no ADR records the E009 rescope. epics.md:987 calls Epic 9 "Practical Gitea Certification"; state calls it "Gitea Classifier and Credential-Logic Correctness". |
| 12 | 2026-10-06 | E011 | ADR-0023 correlation id + atomic writes, 0024 PKCS12 atomic, 0025 strict parse, 0026 None-safe cancel, 0027 vendored framing in CODEOWNERS | All implemented (`_atomic_write`, `cancel()`, `correlation_id` in src) | 0025 is Accepted. **0023, 0024, 0026, 0027 remain Proposed.** Product-spine AD-3 was amended for the correlation id, but its Deferred list (`:187-189`) still says the cross-process correlation id is "deliberately deferred" (BL-E011-041). |
| 13 | 2026-10-06 | E011 | E011-S01-002 tracked-file coverage gate + vendored-tree integrity (BL-E000-001, BL-E008-009) | Retired by ADR-0035 (scripts and `vendored-trees.lock` removed) | **Delivered then undone.** Recorded in ADR-0035 §Consequences and `docs/developer.md:82`. BL-E011-006, about the retired coverage check, is still open. |
| 14 | 2026-10-08 | E012 | **ADR-0028 ref-free checkout** | Carried forward by ADR-0035 and CI spine AD (`:105`, `:341`). Enforced by the `workflows-ref-free-checkout` hook. | Status Accepted is correct. Its body still binds to CI-AR2/CI-AR33/CI-AR42–46 of the **superseded** 2026-08-31 spine, with no amendment note re-anchoring it. ADR-0028 is not in `adr-register.yaml`. |
| 15 | 2026-10-08 | E012 | ADR-0029 gate placement | Superseded by 0035 | OK. |
| 16 | 2026-10-08 | E012 | **ADR-0030 conditional root** (drop unless Docker-socket restart enabled) → **amended 2026-10-10**: drop only when the ACME store is proven readable | Implemented E012-S01-001, amended and implemented E013-S02-004 (HEAD) | **Wrong status.** ADR-0030 still says `Status: Proposed` (`0030…md:2`). Its title is the pre-amendment rule, and `docs/architecture.md:142` repeats that title. A reader of §6 learns the opposite of the shipped default: the stock Traefik case now keeps root. |
| 17 | 2026-10-08 | E012 | **ADR-0032 vendored-tree integrity record** | Superseded by 0035, retired same week | Status correct. Residue: BL-E011-013/-021 are still `scheduled` into E012-S01-002 (see §3). |
| 18 | 2026-10-08 | E012 | **ADR-0033 secret scanning exempts no path + two-severity untracked gate** | Amended by 0035 (untracked gate and near-miss probe retired) and by 0037 (inherit gitleaks default allowlist). No-`paths` rule re-enforced by the `gitleaks-no-paths-allowlist` hook. | Amendment chain recorded in ADR-0033:140-146 and the architecture.md row. BL-E011-015 and BL-E011-020 are still `scheduled` although 0037/0035 settle them. |
| 19 | 2026-10-08 | E012→E013 | **ADR-0035 standard pipeline** (supersedes the 2026-08-31 spine and 12 ADRs) | Accepted — "live forge verification pending (E013-S02-001)" | Header consistent with state. `docs/architecture.md:148` row says "amended by 0036" and omits 0037, which ADR-0035:17 lists. |
| 20 | 2026-10-09 | E013 | ADR-0036 arch-gate amendments; ADR-0037 gitleaks default allowlist | Accepted | OK. |
| 21 | 2026-10-09 | E013 | ADR-0038 release only from protected `v*` tags on main | Accepted, implemented S02-003 | OK in ADR, spine and walkthrough. BL-E013-037 ("validate-tag checks form only") is still backlog although its own description says to resolve it with RT-E013-02, and that item is resolved (BL-E013-019). |
| 22 | 2026-10-09 | E013 | ADR-0039 publish credentials in forge environments | Accepted, implemented S02-002 | **Missing from `docs/architecture.md` §6** (BL-E013-040 open). `README.md:147-150`, `docs/operational.md:317-318` and `docs/architecture.md:180` describe enablement by `PUBLISH_*` secret and never mention the `dev`/`release` environments. |
| — | — | — | **ADR-0034** | Never existed | `docs/architecture.md:107` asserts the gap, but no reservation, event or commit explains it. |

### ADR register integrity (`state/adr-register.yaml`)

- Reserved `number: 1` has slug `action-pin-policy` (E008), and `number: 2` has slug `post-export-notifications` (E010). The files with those numbers are Poetry (0001) and base image (0002). Those decisions landed as 0009 and 0014, so the reservations are mis-numbered.
- 0003–0014, 0028 and 0034 have no register entry. 0015–0022 and 0024–0027 all carry slug `arch-gate`, which gives no traceability to the file.
- `next: 40` is consistent with the files.

## 2. PRD coverage (PRD §6, `prd.md:73-123`)

| PRD item | Delivered by | Status now |
|---|---|---|
| 1 Stop logging passphrase/config dumps | E001-S01-001, extended E010-S01-001, E011-S01-003 | Delivered |
| 2 dataPath None guard | E001-S01-002 | Delivered |
| 3 Declare `cryptography` | E002-S01-001 | Delivered (`cryptography = "^50.0.1"`) |
| 4 Fix `build.yaml` wiring | E002-S01-004 → rebuilt E007/E008 → replaced E013 | Delivered, rebuilt three times; current form is ADR-0035 |
| 5 pytest suite | E001-S01-003 | Delivered |
| 6 s6 first-run config seed | E004-S01-001 | Delivered |
| 7 Poetry out of runtime deps | No dedicated story (folded into E002-S01-002) | Delivered (`poetry` absent from `[tool.poetry.dependencies]`), **without a story** |
| 8 Image from locked deps | E002-S01-002 (ADR-0004/0008) | Delivered |
| 9 Structured JSON file logging | E004-S01-002 | Delivered |
| 10 Include/exclude across config surfaces | E003-S01-001 | Delivered |
| 11 Remove `if: env.ACT` in `build-container.yaml` | E002-S01-005; enforced by the `workflows-no-act-env` hook | Delivered. The PRD links a file that no longer exists. |
| 12 Dead code removal | E006-S01-003 | Delivered |
| 13 Digest-pin base + privilege ADR | E002-S01-003 (ADR-0002) | Delivered. The privilege model was then **reversed** by ADR-0030, and the PRD/FR-11 still say "PUID/PGID". |
| 14 Action versions + Dependabot | E006-S01-002 | Delivered, then policy changed twice (row 7 above) |
| 15 `/docs` skeleton | pre-epic | Delivered |
| 16 LiquidLogicLabs adoption | E006 Story 6.2 / E008 / E013 | Delivered (5 LLL actions in workflows) |
| 17–18 SECURITY/CONTRIBUTING/CoC/templates | E006-S01-001 | Delivered |
| 19 GitHub secret scanning/push protection | None (forge setting) | **Never delivered, never tracked.** No story, no issue, and absent from the walkthrough's forge-settings checklist. |
| 20 Synthetic fixtures | E001-S01-003 | Delivered |
| 21 Metrics/health surface (candidate) | None | Not delivered. Correctly listed as a gap in `docs/architecture.md:97`. |
| 22 SANs export decision (candidate) | E006-S01-003 removed the commented loop | Decided by deletion, with no recorded decision |
| 23 `--once`/exit-code contract (candidate) | None | Not delivered, not tracked |
| — PKCS12 passphrase setting | E003-S01-002 | **Delivered without a PRD item** |
| — Post-export hook | E005-S01-001 | **Delivered without a PRD item.** It is in epics.md and the product spine, but not in the PRD FR table. |
| — Apprise notifications | E010-S01-002 (ADR-0014) | **Delivered without a PRD item/FR** |
| — Release/publication pipeline, Gitea certification, residual hardening | E007, E008, E009, E011, E012, E013 | **Delivered without a PRD item.** These came from review/backlog. E011–E013 also have no epics.md entry (epics.md ends at Epic 10). |
| — Conditional root / ACME-readability privilege decision | E012-S01-001, E013-S02-004 | Delivered without a PRD item. Contradicts PRD FR-11 and NFR wording. |

The PRD front-matter says `status: final, updated: 2026-08-30`. NFR-1 through NFR-7 still read "Violated"/"Unmet" (`prd.md:58-64`), although every one has been delivered.

## 3. State integrity

| Node | Recorded | Reality | Severity |
|---|---|---|---|
| E012 (epic) | `in-progress`, `_lock` claimed 2026-10-08T12:41:41Z, ttl 30m | Stale lock (pm-status anomaly). The E012 code landed inside E013 commit fb75fc6 ("+ E012 hardening"). Epic `goal: ''`. No closure, retro or epic definition (BL-E012-005). | MAJOR |
| E012-S01 (sprint) | `backlog` | 2 done, 1 in-progress, 1 ready-for-dev | MINOR |
| E012-S01-002 | `in-progress` (stuck; open `l3io-pm-story` and `bmad-code-review` dispatch brackets since 2026-10-08) | Its deliverables (ADR-0031/0032/0033, `vendored_trees.py`, `verify-build.yaml` gates) were all superseded and removed by ADR-0035/E013. It should be closed as superseded. | MAJOR |
| BL-E011-013/-014/-015/-020/-021 (Medium) | `scheduled` → E012-S01-002 | 013/021: the integrity gates were retired by ADR-0035, which accepts the loss (`0035:74`). 014: replaced by ADR-0035 pin policy, with residue tracked as BL-E013-022/029. 015: settled by ADR-0037 plus the no-paths hook. 020: the untracked gate was retired. All five need disposition, not scheduling. | MAJOR (with the row above) |
| E012-S01-004 | `ready-for-dev`, schedules BL-E011-033..036 | Real, still-valid CLI hygiene work, stranded in a dormant epic | MINOR |
| E013-S01 (sprint) | `done` | Contains E013-S01-004 `blocked`. The closure report counts it as carry-over, but the tree carries a done sprint with a non-terminal child. | MINOR |
| E013-S01-004 | `blocked` "moved to E013-S02-001" | Duplicate of E013-S02-001 (identical title). Should be closed or superseded now, not when S02-001 finishes. | MINOR |
| E013-S02-001 | `in-progress` (⚠ stuck) | Evidence file `notes-E013-S02-001.md` shows act + GitHub dev.yaml done and Gitea partial. Consistent with the ADR-0035 status "verification pending". | — (consistent) |
| E013-S02 (sprint) | `backlog` | 3/4 done, 1 in-progress | MINOR |
| E008 dispatch brackets | 4 open since 2026-09-03 (retro, adversarial, redteam, arch-review) | The artifacts exist in `epic-008/epic-closure/`. The brackets were never closed. | MINOR |
| E009 | `done` | No closure report or retrospective. Most of its output was superseded within 3 days. | MINOR |
| E007, E010 | `done` | Epic closure report present, no retrospective | MINOR (noted) |
| Already fixed, still `backlog` | BL-E012-003 (s6 privilege conditional has no automated test): `tests/test_s6_privilege_drop.py` added at 2139ad8 executes the decision. BL-E012-013 (CI-AR44 / `verify-build.yaml`): file and spine retired. BL-E011-006 (coverage-check): gate retired. BL-E013-037: resolved with RT-E013-02 / BL-E013-019. BL-E012-006 (ADR-0028 gate-pass desync): about a retired gate process. | | MINOR |
| Duplicates / severity mislabel | BL-E013-001 (Low) and BL-E013-020 (Medium) are the same finding (pre-commit hook revs on mutable tags). BL-E013-020 says "related to BL-E013-001". BL-E013-032 says `uv.lock` is "staged", but `git status` shows it untracked (`??`). | | MINOR |
| Locks | `state/*.lock` and `*.yaml.lock` are empty flock files (normal). The only live claim is E012's `_lock`. | | (in E012 row) |

## 4. Narrative contradictions (README → architecture → operational → walkthrough → AGENTS)

| # | Location | Says | Reality / conflicting source |
|---|---|---|---|
| N1 | `docs/architecture.md:86-87` | Image built on `baseimage-alpine:3.19`, "PUID/PGID privilege drop — see ADR-0002" | `docker/Dockerfile:6` uses `3.24@sha256:…`. `docs/operational.md:223-248`: the container keeps **root** by default (stock Traefik `acme.json` 0600), per ADR-0030 amended |
| N2 | `docs/architecture.md:142` (§6 row 0030) | "Conditional root — privilege drop unless the Docker-socket restart path is enabled" | ADR-0030 amendment (`0030…md:114`): drop only when the ACME store is proven readable. ADR-0030 `Status: Proposed`. |
| N3 | `docs/architecture.md:113-151` | §6 index, "one row per file" | No row for ADR-0039. Row 0002 lacks "amended by 0030". Row 0035 lacks "amended by 0037". |
| N4 | `README.md:147-150`, `docs/operational.md:317-318`, `docs/architecture.md:180` | Each destination is enabled by its own `PUBLISH_*` secret, "set separately on each forge" | `docs/ci/pipeline-walkthrough.md:102-104,238-258` and ADR-0039: on GitHub every `PUBLISH_*` secret must live in the `dev`/`release` environment, never at repository level. A maintainer following README/operational would put repo-level secrets in place and bypass the environment gate. |
| N5 | `AGENTS.md:21` | Backlog is PRD §6 | PRD §6 items are all closed. The live backlog is `state/issues.yaml` (57 backlog + 9 scheduled). |
| N6 | `AGENTS.md:20` | Decisions: `docs/adr/` + the product spine | Omits the governing CI/CD spine `architecture-ci-cd-pipeline-2026-10-08`. The named product spine is stale (N7). |
| N7 | Product spine `ARCHITECTURE-SPINE.md:69-71` (AD-2), `:101-112` (AD-5), `:187-189` (Deferred) | PUID/PGID drop, `3.19`. AD-5 "not yet implemented — ADR-0005". Cross-process correlation id deferred. | ADR-0030. ADR-0035 / CI spine. AD-3 `:80-85` in the same file already mandates `correlation_id`. |
| N8 | `AGENTS.md:2` | "Verified 2026-08-30 against 6bdb516" | Body has since been edited (line 26 describes the ADR-0035 pipeline), so the verification stamp is false |
| N9 | PRD `prd.md:3-4,58-64,84-85,95` | `status: final`. NFRs "Violated". Item 4/11 cite `build-container.yaml`. | All delivered. The file was removed. |
| N10 | `docs/guidelines.md:72` | "what ADR-0009's accepted-risk entries rest on" | ADR-0009 is superseded by ADR-0035 |
| N11 | `docker/docker-compose.yml:13`, `docker/README.md:144` | `…_RESTART_CONTAINERS`, `…_SETTINGS_RESTARTCONTAINER` | Convention `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS` (AGENTS.md:31). Tracked as BL-E013-042 (Medium). |
| N12 | `README.md` (no section) | Silent on the container privilege model | A reader who stops at the README never learns the image runs as root by default. `docker/README.md:60-65` and `docs/operational.md:223` do say it. `README.md:154` "Credits" sits before `:158` "Export notifications". |
| N13 | `_bmad-output/planning-artifacts/epics.md:987` | Epic 9 "Practical Gitea Certification"; no Epic 11–13 | State title differs. E011–E013 are not in epics.md. |

## Findings

| ID | SEVERITY | Finding | Evidence | Remediation |
|---|---|---|---|---|
| CO-01 | MAJOR | ADR-0030 status is wrong and its recorded title states the superseded rule; ADR-0002 does not point to it. | `docs/adr/0030-conditional-privilege-drop.md:1-2` (Proposed, "unless the Docker-socket restart path"); amendment at `:114`; implemented E012-S01-001 + E013-S02-004 (2139ad8); `docs/adr/0002…md` has no "Amended by" line | Set `Status: Accepted; amended 2026-10-10`. Retitle, or add the amended rule to the title. Add `Amended by: ADR-0030` to ADR-0002. Update architecture.md rows 0002/0030. |
| CO-02 | MAJOR | Operator docs omit the ADR-0039 environment requirement for publish secrets. | `README.md:147-150`, `docs/operational.md:317-318`, `docs/architecture.md:180` vs `docs/ci/pipeline-walkthrough.md:102-104,238-258`, ADR-0039, CI spine `:199` | Say "in the `dev`/`release` environment (GitHub; ADR-0039)" at all three sites and link the walkthrough checklist. |
| CO-03 | MAJOR | E012 is a dormant `in-progress` epic: stale lock, a superseded story stuck `in-progress` with open dispatch brackets, sprint `backlog`. | `pm-status report` (stale-lock anomaly, E012-S01-002 stuck, 2 stalled brackets); `active/epic-012/epic.yaml:1-4`; review-E012-S01-002.md reviews files that ADR-0035 deleted | Clear the lock. Close E012-S01-002 as superseded by ADR-0035/E013-S01-002. Close the stalled brackets. Decide E012-S01-004: run it, or reparent it to a new epic. Then close or archive E012 with a closure note that its code shipped in fb75fc6. |
| CO-04 | MAJOR | Nine Medium backlog items are `scheduled` into retired or dormant work. Five of them (BL-E011-013/-014/-015/-020/-021) are already settled by ADR-0035/0037. | `list-issues --status scheduled`; ADR-0035:72-74; ADR-0037; `.pre-commit-config.yaml:32-35` | Resolve 013/021 as `wontfix — accepted by ADR-0035`, 015 as `fixed by ADR-0037 + no-paths hook`, 020 as `obsolete — gate retired`, 014 as `superseded → BL-E013-022/029`. Reschedule 033–036. |
| CO-05 | MAJOR | The product architecture spine was never updated after 2026-08-30. AD-2, AD-5 and the Deferred list contradict live ADRs and its own AD-3, yet AGENTS.md names it as the decision record. | `architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md:69-71,101-112,187-189` (front-matter `updated: '2026-08-30'`) | Amend AD-2 (→ ADR-0030 amended). Mark AD-5 superseded by the CI/CD spine (ADR-0035). Delete the correlation-id Deferred bullet (BL-E011-041). Bump `updated`. |
| CO-06 | MAJOR | AGENTS.md routes new maintainers and agents to stale sources: the PRD §6 backlog, the product spine only, and a false verification stamp. | `AGENTS.md:2,20,21` | Point the backlog at `state/issues.yaml` (via `pm-status list-issues`). Add the 2026-10-08 CI/CD spine. Refresh the stamp via `bmad-project-context`. |
| CO-07 | MAJOR | E009's delivered decisions were reversed within days, and the record of that is non-standard: "Superseded by scope", no ADR for the rescope, no E009 closure or retro. | `docs/adr/0016…md:3-4`, `0017…md:3`; `implementation-artifacts/epic-009/` (no closure); epics.md:987 title differs from state | Supersede 0016/0017 "by ADR-0035". Add a one-paragraph E009 closure note recording what remains live (ADR-0018) and what was retired. |
| CO-08 | MINOR | Implemented ADRs left at `Proposed`. | ADR-0003, 0023, 0024, 0026, 0027 status lines; code at `certificate_exporter.py:154,818`, `logging_utils.py`, CODEOWNERS `/.agents/` | Set each to Accepted, citing the implementing story (E004/E010, E011-S01-004, E011). |
| CO-09 | MINOR | `docs/architecture.md` §6 index is incomplete and §4 is stale. | `docs/architecture.md:86` (3.19), rows at `:119,:142,:148`; ADR-0039 row absent (BL-E013-040) | Add the 0039 row. Add "amended by 0030" to the 0002 row and "amended by 0037" to the 0035 row. Fix the base image in §4. Consider a pre-commit check comparing §6 with `docs/adr/`, since the doc states that no check exists. |
| CO-10 | MINOR | `adr-register.yaml` mis-numbers reservations 1 and 2, lacks 0003–0014, 0028 and 0034, and uses slug `arch-gate` for twelve unrelated ADRs. | `state/adr-register.yaml:3-10` vs `docs/adr/0001`, `0002`, `0009`, `0014` | Repair via `l3io-doctor`. Record 0034 as `void` with a reason. Back-fill slugs. |
| CO-11 | MINOR | PRD is frozen at baseline. NFR "Violated" claims are false, and it cites a removed file. Notifications, passphrase, post-export hook, privilege model and CI/CD epics have no PRD item. | `prd.md:3-4,58-64,84-85,95`; §2 table above | Add an "as of 2026-10-10" status column, or mark the PRD historical and point to state for current scope. Add FR rows for notifications and the post-export hook. |
| CO-12 | MINOR | PRD item 19 (GitHub secret scanning / push protection) was never delivered or tracked. | `prd.md:113-114`; absent from `pipeline-walkthrough.md` §"Forge settings" | Add to the walkthrough's required forge-settings checklist, or file a backlog item. |
| CO-13 | MINOR | E013 sprint and story statuses contradict each other: sprint S01 is `done` with a `blocked` child, and S01-004 duplicates S02-001. | `pm-status show --epic E013`; `active/epic-013/sprint-01/E013-S01-004.yaml` | Close E013-S01-004 now as `superseded → E013-S02-001`. |
| CO-14 | MINOR | Backlog items already fixed or obsolete are still open. | BL-E012-003 (`tests/test_s6_privilege_drop.py`, 2139ad8), BL-E012-013, BL-E011-006, BL-E013-037, BL-E012-006 | Resolve with evidence pointers (`l3io-doctor` triage). |
| CO-15 | MINOR | A duplicate backlog pair carries two severities, and one description is factually wrong. | BL-E013-001 (Low) and BL-E013-020 (Medium); BL-E013-032 says "staged" but `uv.lock` is untracked | Merge 001 into 020 at Medium. Correct 032. |
| CO-16 | MINOR | E008 left four dispatch brackets open for 54k minutes. | `pm-status report --stall-minutes 60` | Close the brackets. The artifacts exist. |
| CO-17 | MINOR | ADR-0028 binds to rule ids of the superseded 2026-08-31 spine and is absent from the register. | `docs/adr/0028…md:6-10`; CI spine `:105,:341` carries it forward | Add an amendment note re-anchoring it to the CI/CD spine AD. Register 0028. |
| CO-18 | MINOR | `docs/guidelines.md` cites superseded ADR-0009 as live. | `docs/guidelines.md:72` | Re-point the sentence to ADR-0035 (LLL major-tag policy). |
| CO-19 | MINOR | E011–E013 have no epics.md entry, and the Epic 9 title diverges. | `epics.md:102-1068` | Append the epic definitions or a pointer to the state tree. |
| CO-20 | MINOR | README does not state the container privilege default, and the section order is odd. | `README.md` headings `:138,:154,:158` | Add a two-line container-privileges pointer to `docs/operational.md#container-privileges…`. Move Credits last. |
| CO-21 | MINOR | The sample compose and docker README env var names do not follow the settings convention (already tracked). | `docker/docker-compose.yml:13`, `docker/README.md:144`; BL-E013-042 | Fix under BL-E013-042. |

Assumptions:
- A "Proposed" ADR whose decision is implemented in code is treated as a wrong status, not as a pending decision.
- A sprint `done` with a blocked child is treated as a state contradiction, even though the closure report explains it as carry-over.
- No finding is graded BLOCKER, because none changes CI, release, or runtime behaviour. CO-02 is the nearest: following README/operational would place secrets outside the ADR-0039 gate.

## Sections read

- `docs/adr/*`: Status/header block of all 38 files. Amendment headings of 0002, 0004, 0008, 0009, 0010, 0012, 0016, 0028, 0030 (`:1-12`, `:114`), 0031, 0032, 0033 (`:140-146`), 0035 (`:1-28`, `:60-79`), 0036–0039. Grep across ADR files for references to ADR-0034.
- `docs/architecture.md:60-183`. `docs/operational.md:223-332` plus targeted greps. `docs/ci/pipeline-walkthrough.md`: greps for environments, tag protection, ADR refs (`:52-61,:102-104,:179-194,:224-320`). `README.md:135-157` plus headings and greps. `AGENTS.md:1-35`. `docs/guidelines.md:66-74` plus greps. `docs/developer.md`: greps. `docker/README.md` and `docker/docker-compose.yml`: greps. `docker/Dockerfile:6-9`. `pyproject.toml` deps. `.pre-commit-config.yaml` hook ids. `.github/workflows/*` `uses:` lines. `tests/test_s6_privilege_drop.py:1-12`.
- Product spine 2026-08-30: `:12`, `:56-112`, `:183-192`. CI/CD spine 2026-10-08: front-matter and greps (`:18,:97,:105,:109,:143,:199,:268,:341,:348`). CI/CD spine 2026-08-31: front-matter only.
- PRD `prd.md:1-14,38-123`. `epics.md` headings. `plan-output-meta.yaml`.
- State: `pm-status show` (E012, E013), `list-epics`, `list-stories`, `report --stall-minutes 60`, `list-issues --status backlog|scheduled`. `adr-register.yaml` (full). Lock files. `active/epic-012/{epic.yaml,sprint-01/E012-S01-002.yaml,E012-S01-004.yaml}` headers. Archived epic/sprint/story status fields. Selected `issues.yaml`/`issues-resolved.yaml` entries.
- Epic artifacts: closure/retro file inventory for all 13 epics. `epic-013/sprint-01/closure/closure-report.md:1-40`. `epic-013/sprint-02/closure/notes-E013-S02-001.md:1-30`. `epic-012/sprint-01/closure/review-E012-S01-002.md:1-15`. Grep of `epic-013/sprint-01/closure/retrospective.md`.
- Git: tags, `git log` for E012/privilege commits, ancestry of E012 work vs `v0.2.0`, history of ADR-0034.
- Not read: closure-report and retrospective bodies of E001–E011 (inventory only), the 2026-08-31 spine body, `review-report*.md`, `events.jsonl` beyond the pm-status reader.
