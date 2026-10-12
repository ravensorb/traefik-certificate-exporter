# E015 / 0.3.1 planning baseline — independent validation (2026-10-12)

- **Baseline validated:** HEAD `fd383ef` (PRD, product spine, CI spine, maintainer-decisions, ADR-0001–0048 and the
  `docs/architecture.md` §6 index, the eight E015 stories, execution-notes, `plan-2026-10-12-v1.yaml`, E015 state,
  research brief 2026-10-12). The 0.3.0 code and config (`src/`, `docker/`, `.github/workflows/`,
  `.pre-commit-config.yaml`, `justfile`, `pyproject.toml`) were used as the starting point.
- **Method:** read every document end to end and spot-checked the cited line references against the tree. Also ran:
  - `pm-status show` and `verify --scope epic --epic E015`;
  - read-only `gh variable list` against the forge;
  - an `imagetools inspect` probe of the digest-equality command;
  - an inspection of installed confuse 2.3.0 (`.venv/.../confuse/core.py`).
- **Write scope:** no file other than this report was changed.

## Summary verdict: **READY WITH FIXES**

The baseline is coherent where it matters most:
- The root-mode trust rule is consistent across the PRD, both spines, MD-19…MD-22 and E015-S01-001. It covers the same two keys and the same file sources (`.env` included), and it logs an ERROR and keeps exporting rather than exiting.
- `validatekeys`, the `.pfx` sidecar contract, the rename handling, the eleven legacy names, `buildkitd-config` and the locked-hook rule all agree.
- The LinuxServer conventions are untouched.
- Every ADR placeholder has an owner, and the dependency waves match `depends_on`.
- `verify` passes, and the code references are accurate.

No finding stops execution or makes it build the wrong product. Six MAJOR findings should be fixed in the stories (and in the two places in the spine and the PRD that carry the same defect) before the affected story starts:
- two are false-green or unrecordable verification commands, one of them a variant of E014's digest false-green;
- one is a contradiction inside E015-S01-001's interface contract;
- one is a variable-placement rule that contradicts the zero-warning release gate;
- one is a PRD NFR with no story AC;
- one is an unrecorded consequence of production jumping from 0.2.0 straight to 0.3.1.

| Severity | Count |
|---|---|
| BLOCKER | 0 |
| MAJOR | 6 |
| MINOR | 10 |

## Findings

| ID | Severity | Check | Document:line | Finding | Recommended fix |
|---|---|---|---|---|---|
| V-01 | MAJOR | 7, 2 | CI spine `ARCHITECTURE-SPINE.md:250-251`; E015-S02-002.md:250, :265; E015-S02-004.md:292-293, :315; PRD prd.md:95 | **The digest-equality command can still pass when it should fail.** Adding `echo` fixes the newline collapse. But a lookup that fails (tag missing, registry not published, auth error) prints nothing on stdout, so `echo` emits an empty line, and `grep -c .` does not count empty lines. Probe run here: `dig docker.io/library/alpine:3.20 docker.io/ravensorb/this-image-does-not-exist-e015:0.3.1 \| sort -u \| grep -c .` printed `1` (rc 0). The same happens when a `PUBLISH_*_IMAGE` variable is unset: `for r in $(IMGS)` / `for r in $GHCR_IMAGE …` drops the registry silently. 0.3.1 is GHCR's first release publish (S02-004:29 context), so a failed or skipped GHCR push passes row 14. S02-002:123 even states the contract "pass iff … every lookup succeeded", but the command does not check it. PRD NFR-4 claims the newline "so that differing digests cannot collapse into one line", which holds only for present tags. | Make a failed lookup visible: `dig() { for t; do d=$(docker buildx imagetools inspect "$t" --format '{{json .Manifest.Digest}}') \|\| d="MISSING $t"; printf '%s\n' "$d"; done; }`. Then pass only on `out=$(…) && ! grep -q MISSING <<<"$out" && test "$(sort -u <<<"$out" \| wc -l)" = 1`. Also assert the input set: `test "$(IMGS \| grep -c .)" = 3`. Apply the same text in CI AD-12, S02-002 (row 9 and the walkthrough checklist it writes) and S02-004 row 14, and plant a missing tag once in the notes. |
| V-02 | MAJOR | 2, 6 | E015-S01-001.md:61, :66, :139; product spine `ARCHITECTURE-SPINE.md:215`; installed `confuse/core.py:117, :424-425` (`set` → `sources.insert(0, ConfigSource.of(value))`) and `set_args` → `self.set(...)` | **`sourceOf` cannot tell the command line from the fallback that withholding installs.**<br>• AC 2 (:61): the fallback is "applied with `view.set(...)`".<br>• Interface contract (:139): "confuse adds the command-line source with `set_args`; it is a `ConfigSource` with no filename that is not an `EnvSource`."<br>Both produce the same source type at the front of `resolve()`. After a file value is withheld, the start-up line therefore reads `source: command line`, which is the operator-visible signal FR-18 and the S02-004 post-check (:130, :318) rely on. Separately, AC 4's and AD-3's source enumeration `<environment\|command line\|configuration file '<path>'>` omits `default`, which `sourceOf` returns (:139) for an unset hook. | Specify that `_withholdFileSourcedRootSettings` records the effective source of each withheld key (for example a `dict` on the manager, read first by `sourceOf`), or that it neutralises the file pair without `set()`. Add a unit test: root, file-only hook → `sourceOf == "default"`; root, file + env → `"environment"`. Add `default` to the AC 4 and AD-3 line format. |
| V-03 | MAJOR | 2 | E015-S02-002.md:121 ("variables (environment or repository level)"); CI spine `:196` ("variables stay at repository level or in the environment"); `.github/workflows/dev.yaml:236, :246-250`; E015-S02-004.md:88; E015-S02-002.md:112 | **Repository-level variables would make every `dev.yaml` run warn.** `dev.yaml` `publish-image`/`publish-package` run in the `dev` environment and compute `ANY_GHCR`, `ANY_GITEA`, `ANY_DOCKERHUB` and `ANY_GITEA_SHARED` from `vars.*`. If the maintainer sets the new `PUBLISH_GHCR_*`/`PUBLISH_GITEA_*` variables at repository level as S02-002 allows, every dev run gets partial-configuration warnings (the tokens are in `release` only). That contradicts S02-004 AC 1 ("zero `partially configured`") and S02-002's own non-goal "Does not enable GHCR or Gitea for `dev.yaml`". Today all variables are environment-level (`gh variable list -R …` lists none; `--env release` lists the two Docker Hub variables). | State in S02-002 (Interface contracts, maintainer checklist :222) and CI AD-9/AD-13: release variables live **only** in the `release` environment. Make S02-002 row 8 and S02-004 row 6 assert that `gh variable list -R $GH` returns no `PUBLISH_*` name. |
| V-04 | MAJOR | 1 | PRD prd.md:96 (NFR-5 "Changed in 0.3.1 — … E015-S02-004 (release record)"); E015-S02-004.md:82-145, :300-322 | **NFR-5 is orphaned in the release story.** NFR-5 requires that "each release records a passing run of the opt-in integration tests (real container restart, container run-once, passphrase PFX, root-mode settings trust including the RT-1 replay) against the release-commit image". E015-S02-004 has no AC and no Verification row that runs `-m integration` against the released image. The only integration runs are on `:local` during dev (S01-001 row 11, S01-002 row 13). | Add an S02-004 AC and row after row 15: pull the released digest, then `TCE_DOCKER_INTEGRATION=1 TCE_IMAGE=<registry>/…@<digest> poetry run pytest -q -m integration -rs tests/test_container_*.py`, expecting all passed and none skipped. Record it in the evidence file. |
| V-05 | MAJOR | 2, 6 | E015-S02-004.md:52, :59-63, :123-134; `docs/upgrading.md:27-30`; PRD prd.md:69 (FR-2 upgrade sentence applies to 0.3.0 output); maintainer-decisions.md:59-63 (MD-06) | **Production jumps from 0.2.0 straight to 0.3.1, and the story does not plan for 0.3.0's one-time effects.**<br>• `docs/upgrading.md:27-30`: "The first pass after upgrading from 0.2.x rewrites every `.pfx` … every labeled container restarts once, and the post-export hook and notifications fire once."<br>• The MD-06 "verify once, rewrite nothing" upgrade covers 0.3.0 output only.<br>• S02-004's "0.3.1 changes what the operator sees" list (:59-63) and its post-checks do not anticipate that the first production pass rewrites every `.pfx` (with key validation, ~74 RSA-4096 builds). That pass reports all ~74 domains and fires any configured hook or Apprise once.<br>• `cert-distributor` may react to the rewrite.<br>• The "export-pass duration beside 0.2.0 baseline" row compares a one-off first pass with steady state.<br>This is an operational consequence with no recorded decision on the production host. | In S02-004:<br>• extend the row 8 pre-check to record whether a hook or Apprise URLs are configured (names or counts only) and what triggers `cert-distributor`;<br>• add a maintainer acknowledgement of the one-time mass report;<br>• state the expected first-pass behaviour (every `.pfx` rewritten, every domain reported once, `cert.pem` unchanged);<br>• measure steady-state duration on the second pass.<br>Mention 0.2.0 → 0.3.1 in the S02-002 `### Where releases come from` note. |
| V-06 | MAJOR | 7 | E015-S02-001.md:198-201; E015-S02-002.md:258-262, :268; E015-S02-003.md:219-223; E015-S02-004.md:303, :312, :321; rule at execution-notes.md:177-183 | **Verification wrappers that cannot exit 0 on correct code, or cannot fail.**<br>(a) The expected count is `0`, but `grep -c` exits 1 when it counts zero: S02-001 row 7, S02-002 rows 3 and 5, S02-004 row 11.<br>(b) The act exit status is discarded, because `actrun …; grep` or `… \| tee` takes the last command's status: S02-001 rows 7 and 8, S02-002 rows 3 and 5.<br>(c) `! (cd … && just act dev.yaml) 2>&1 \| tee …` negates `tee`'s status, so it is always 1 (S02-002 row 4).<br>(d) `;`-chained rows record only the last status, so their earlier positive greps can never fail the row: S02-001 rows 5 and 6, S02-002 rows 2, 6 and 12, S02-003 rows 4, 7 and 8, S02-004 row 2.<br>(e) Rows ending in clean-up always exit 0: S02-003 row 5 (`; rm -rf "$H"`) and S02-004 row 20 (`; rm -rf "$T"`).<br>Recorded with `pm-status add-test-run`, these give false greens or false reds, which is the E014 failure class the execution notes forbid. | Rewrite each as one `&&` chain:<br>• counts as `test "$(grep -c … \|\| true)" = N`;<br>• act status as `actrun …; rc=$?; test $rc = 0 && …`, or `set -o pipefail` inside a subshell;<br>• the refusal as `( cd … && just act dev.yaml ) >"$D/actrc.log" 2>&1; test $? = 1 && grep -q 'refusing …' "$D/actrc.log"`;<br>• clean-up moved to its own row.<br>Plant each wrapper once against a violation and note it, as execution-notes.md:178-179 already requires. |
| V-07 | MINOR | 5 | `docs/architecture.md:127-131`; Files in scope of E015-S01-001.md:252-267, E015-S01-002.md:347-361, E015-S02-002.md:203-212, E015-S02-003.md:185-194 | The ADR index is consistent today (every row checked against each ADR's Status, Amended-by and Amendment markers). Its own rule is "a new or re-statused ADR must update its row in the same change", but no E015 story has `docs/architecture.md` §6 in scope. That covers three new ADRs, plus the new "amended by" markers on 0030, 0039, 0042 and 0043. | Add `docs/architecture.md` §6 (the new row, or the amended-by marker) to the Files in scope of S01-001, S01-002, S02-002 and S02-003, with a grep row each. |
| V-08 | MINOR | 5 | CI spine `ARCHITECTURE-SPINE.md:436`; E015-S02-002.md:79, :200, :208 | The third "ADR to be written by E015-S02-002" occurrence, in the "ADRs carried forward" block, is outside S02-002's stated replacement scope ("in AD-9/AD-10"). | Widen S02-002's routing to "every occurrence in the CI spine", and grep `! grep -n 'to be written by E015' <both spines>` at epic close. |
| V-09 | MINOR | 4, 2 | `docs/adr/0030-conditional-privilege-drop.md:110-111`; `docs/operational.md:423`; E015-S01-001.md:86, :126, :262-263 | Two passages that call `/config` root-owned survive S01-001: "the root-owned `/config`" at ADR-0030:110-111 and `operational.md:423`. S01-001 amends only ADR-0030:89-91 and leaves `operational.md:422-426` as a non-goal (BL-E015-001). That conflicts with AC 9's "Docs state what ships". Nothing in the baseline changes the convention; this is stale text only. | Include ADR-0030:110-111 in the S01-001 amendment and reword "root-owned" in `operational.md:423`. The rest of the paragraph can stay with BL-E015-001. |
| V-10 | MINOR | 1 | E015-S01-002.md:57, :71-76, :351; maintainer-decisions.md:106 | MD-21 says E015-S01-002 "classifies `validatekeys`", and FR-19 says it "may come from any source, root mode included". In the story this appears only in the Sequencing paragraph, not as an AC or in Files in scope (`settings.py` lists only the `Settings` field and `loadFromFile`). Row 8 forces it implicitly. | Add an AC: `ROOT_SETTING_TRUST[("settings","validatekeys")] == ROOT_TRUST_ANY_SOURCE`, and list it in Files in scope. |
| V-11 | MINOR | 2 | PRD prd.md:69 vs product spine `:353-358` | PRD FR-2: "A missing, unusable or **mismatching** fingerprint file falls back once to a content comparison." AD-8: "A usable fingerprint file with an input mismatch gives `rebuild` (no PKCS12 load)", and only a `pfx_sha256` mismatch gives `verify`. | Reword FR-2: "…or one whose recorded `.pfx` hash does not match the file falls back once to a content comparison; one whose inputs (key, certificates, passphrase) differ rebuilds the `.pfx`." |
| V-12 | MINOR | 2 | PRD prd.md:100 vs CI spine `:120`; E015-S02-003.md:60 | PRD NFR-9: "every local hook runs as `system` or `pygrep`". CI AD-3 and the guard also admit `unsupported` (pre-commit ≥ 4.4's alias). | Add "(or `unsupported`, its pre-commit ≥ 4.4 alias)" to NFR-9. |
| V-13 | MINOR | 3 | `plan-2026-10-12-v1.yaml:41`; E015-S02-002.md:46; E015-S02-004.md:74; E015-S01-002.md:35, :41 | Every MD is accepted and MD-01…05 are withdrawn with no surviving target text, but some "open"/"assumed" wording remains:<br>• "18 maintainer decisions open … stories proceed on the recommendations";<br>• table headers "Recommended (story assumes)" and "Recommended (assumed)";<br>• "recorded, overturn at review" and "Recommended and assumed". | Replace with "Accepted 2026-10-12 (MD-nn)", and regenerate the plan snapshot (V-14). |
| V-14 | MINOR | 8 | `plan-2026-10-12-v1.yaml:1, :14-19, :31-33`; state `planned/epic-015/*.yaml` (`updated_at` 22:14Z); commits `bacc1f2` 18:40-04:00 and `fd383ef` 19:09-04:00 | The snapshot (22:16Z = 18:16-04:00, commit `e8308ba`) predates the S01-001 redesign and the consolidation, and its readiness text is stale. The HITL estimates also understate what the stories plan:<br>• epic `hitl_hours` is 1.98–2.3, and S02-002 and S02-004 each carry 0.16 h;<br>• the stories plan 1.5–2 h (S02-002) and 3–4.5 h (S02-004) of maintainer time.<br>The understatement is acknowledged as a caveat, not corrected. The waves still match `depends_on`, and `verify` passes. | Re-run `/l3io-plan estimate E015` (or regenerate the snapshot) after the fixes, carrying HITL hours for S02-002 and S02-004. |
| V-15 | MINOR | 8, 6 | E015-S01-002.md:57, :357, :386; E015-S02-002.md:80, :211; E015-S02-003.md:193; E015-S01-001.md:252-267 | **Wave-2 stories run in parallel and edit the same files.**<br>• S01-002 (row 9 needs `## 0.3.0 → 0.3.1`) and S02-002 ("created if absent") can both create the same `docs/upgrading.md` section.<br>• S02-002 and S02-003 both edit `docs/ci/pipeline-walkthrough.md`.<br>• S01-002:57 assumes S01-001 opens the upgrading section, but S01-001's Files in scope do not include `docs/upgrading.md`. | Make S01-001 own opening `## 0.3.0 → 0.3.1` (add the file to its scope), or make S02-002 `depends_on` S01-002. Note the shared walkthrough edits in both stories so the second rebases. |
| V-16 | MINOR | 7 | E015-S02-004.md:253, :313; execution-notes.md:23 | Row 12 installs the released package with `uv venv`/`uv pip`. execution-notes says uv "runs `_bmad/scripts/pm-status.py` only; the project is Poetry". This is not a project dependency-tool change, but it contradicts the recorded tool boundary. | Use `python3.10 -m venv` / `python3.14 -m venv` and that venv's `pip install`. |

## Per-check verdicts

1. **Traceability, both directions — PASS WITH GAPS.**
   - **PRD → story.** Every "New/Changed in 0.3.1" requirement maps to a story AC and a Verification row:
     - FR-2/FR-14/FR-15/FR-19/NFR-8 → S01-002 AC 2-12, rows 2-7;
     - FR-6 → S01-003 AC 1-6, rows 2-4;
     - FR-10/FR-18/NFR-1/NFR-2 → S01-001 AC 1-7, rows 1-11 (plus S01-002 AC 5, `test_sidecar_holds_no_secret`; S01-004 AC 2-3);
     - FR-16 → S01-004 AC 1-7;
     - FR-17/NFR-4 → S02-002 AC 1-7 and S02-004 AC 4-9;
     - NFR-9 → S02-003;
     - NFR-10 → S02-001 and S02-004 AC 6;
     - NFR-3 range ends → S02-004 AC 7.

     The exceptions:
     - **NFR-5 has no S02-004 AC (V-04).**
     - The `validatekeys` trust class is not an AC (V-10).
   - **Story → PRD/spine.** Every story AC traces to a PRD requirement or a spine AD (S02-001 → CI AD-18/AD-3; S02-003 → CI AD-3; S01-003 → AD-11; and so on). The only story ACs without a PRD or spine anchor are S02-004 AC 5 and AC 10-11 (production freeze, upgrade and rollback). They trace only to MD-16, which by explicit decision lives in S02-004 alone (maintainer-decisions.md:160-164; CI `.memlog.md:83`). That is accepted, not an orphan defect.
2. **Consistency — PASS WITH FIXES.** All the named behaviours agree across the PRD, both spines, the decision record and the stories:
   - **Root-mode trust:**
     - settings: `postexportcommand` and `outputpath` only;
     - sources: the config file, the confuse user config, and a `.env` file, as a file only for a value newly added by `.env`;
     - outcome: one ERROR per setting naming setting, file and env var, never the value; exporting continues, no exit.
     - Sources: prd.md:77, :85; product AD-2 :138-152; MD-19/20/21; S01-001 AC 1-3, Observability.
   - **`validatekeys`:** `settings.validatekeys`, env `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_VALIDATEKEYS`, `--no-validate-keys` as `store_const False`/`default None`, default `true` (prd.md:86; AD-6 :260-262; AD-8 :336-342; S01-002 AC 2).
   - **Sidecar:**
     - name `<pfx>.fingerprint.json`;
     - contents: `pfx_sha256`, `key_sha256`, ordered `certificates_sha256`, `passphrase` null or scrypt n=16384 r=8 p=1 with a 16-byte salt and 32-byte digest, plus format/version;
     - mode 0600; write order PEMs → `.pfx` → sidecar;
     - upgrade from 0.3.0: verify once, write the sidecar only, report nothing.
     - Sources: prd.md:69; AD-8 :362-384; MD-06/07; S01-002 D2-D5.
   - **Rename handling** (prd.md:73; AD-11 :461-469; S01-003 AC 1-6).
   - **Legacy names:** the same eleven in every place (prd.md:83; MD-08 :79; AD-6 :267; S01-004 table).
   - **Releases:** one build per release, GitHub as the sole publishing forge, classic `write:packages` GHCR PAT, fine-grained release PAT, `write:package`-only Gitea token (prd.md:84, :95; CI AD-9/AD-10/AD-13; MD-10…MD-15; S02-002 D1-D8).
   - **Locked hook dependencies** (prd.md:100; CI AD-3 :120; MD-17; S02-003).
   - **`buildkitd-config`** (prd.md:101; CI AD-18 :324-325; S02-001).

   Contradictions found, quoted in the table:
   - V-02 (S01-001 `view.set` versus the `sourceOf` source rule);
   - V-03 (variables "environment or repository level" versus zero dev-run warnings);
   - V-11 (PRD FR-2 "mismatching … falls back" versus AD-8 "input mismatch gives rebuild");
   - V-12 (`system`/`pygrep` versus `unsupported`).
3. **Decisions — PASS (minor wording).**
   - Each accepted MD (MD-06…MD-23) is present in every "Lives in" location I checked: the PRD FR/NFR rows, the product and CI ADs, the story D-items and ACs, `.memlog.md` lines 22-26 and 77-83, and `issues.yaml` BL-E015-001…003.
   - The withdrawn MD-01…05 survive nowhere as target text. The searches for "root-owned", "lsiown", "back to root" and "refuse" in the baseline find them only as withdrawn or rejected.
   - Residual "open"/"assumed" wording: V-13. MD-21's "E015-S01-002 classifies `validatekeys`" is only implicit (V-10).
4. **LSIO constraint — PASS.**
   - No story changes `/config` ownership, disables `lsiown` or patches the LSIO init. No story's Files in scope include `docker/Dockerfile` or any s6 script. S01-001 non-goal :119 and AC 8 enforce this with row 5 (`! grep -q init-adduser docker/Dockerfile && ls … init-adduser = branding`), and product AD-12 :513 says "No s6 script changes in E015".
   - S01-001 AC 7(iv) and S02-004 row 18 prove that `/config` stays owned by `PUID`.
   - BL-E015-002/003 are deferred, not acted on.
   - Only stale documentary text remains (V-09).
5. **ADRs — PASS WITH GAPS.**
   - Each placeholder has an owning story with an AC to write the ADR:
     - product AD-2 :188 → S01-001 AC 10;
     - product AD-8 :391 → S01-002 AC 16;
     - CI AD-9 :195 and AD-10 :224 → S02-002 AC 1/5;
     - MD-13 → S02-002.
   - Each existing ADR the baseline contradicts is named as amended by a story:
     - ADR-0030 (S01-001 AC 9);
     - ADR-0043 (S01-002 AC 16);
     - ADR-0039 (S02-002 AC 1);
     - ADR-0042 (S02-003 AC 8);
     - ADR-0048 :37-38 (S02-003 AC 7).
   - ADR-0045 is explicitly unchanged.
   - The §6 index is consistent today, but no story owns updating it (V-07). One placeholder at CI :436 is unowned (V-08).
6. **Implementability against 0.3.0 — PASS.** I checked the cited code, config and doc locations against the tree, and they exist as described:
   - **`certificate_exporter.py`:** `:66`, `:271-276`, `:370`, `:397`, `:420`, `:976`, `:981`, `:1020`, `:1031`, `:1046-1063`, `:1201`, `:1304`, `:1341-1356`, `:1381`; plus `__exportDomain`, `_pfx_differs`, `_log_pkcs12_details`, `_breaks_write_policy`, `_artifact_paths`, `__arm`/`__rearm`/`__processPath`;
   - **`settings.py`:** `:313-346`, the two `load_dotenv` calls, `set_env`/`set_args`/`check_setting_names`/`_mark_present_secrets` order;
   - **`app.py`:** `:41-48`, `:140`, `:175-177`, `:240-255`;
   - **`post_export.py`:** `:88` `_run`;
   - **`docker.py`:** `:157-158`, `:300-301`, `:365`, `:479`;
   - **`config_default.yaml`:** keys and defaults; `watchforchanges`/`runatstart` false, so S01-004 rows 6-7 terminate;
   - **`legacy_settings.py`:** `ENV_PREFIX`, `_canonical`, `_legacy_entry`, `find_legacy_settings`, `_NO_CONFIG_FILE_ENV`;
   - **tests:** the helpers `_git`, `_history_names`, `_undocumented_history_names`, `_DIFF_HEADER`, `CONFIG_DEFAULT`, `_DEFAULT_ARTIFACTS`, `_snapshot`, `_make_settings`, `_run`/`_warnings`/`_env_rows`, `_handler`, `_drain_with_changed`;
   - **Docker and s6:** `Dockerfile:6`, `:123-131`; `init-adduser/` (holds only `branding`); `init-…-config/run:23`, `:146-153`;
   - **workflows:** `dev.yaml:409-412`, `release.yaml:477-480`, `build.yaml:45`, `:154`;
   - **`justfile`:** `:52`; `image` depends on `build` and tags `:local`;
   - **`.pre-commit-config.yaml`:** `:59-67`, `:115`, `:268-275`;
   - **`pyproject.toml`:** `:24`, `:36-38`, `:57-63`;
   - **docs:** ADR-0030:89-91, ADR-0048:37-38, `operational.md:39-42`, `:294-301`, `:417-420`, `:422-426`, `docker/README.md:90-99`, `:184`, `architecture.md:50`, `:72`, `gitea-runners.md:40`, `:47-48`.

   I found no stale references. The one implementability defect is a design conflict, not a stale reference (V-02).
7. **Verification quality — NEEDS FIXES.**
   - Every story's Verification table ends with `just check`:
     - S01-001 row 12, S01-002 row 15, S01-003 row 7, S01-004 row 8;
     - S02-001 row 11, S02-002 row 14, S02-003 row 12, S02-004 row 21.
   - No command puts a secret on a command line:
     - Gitea tokens go through `curl -H @-` on stdin (S02-002 rows 7-8; S02-004 row 7);
     - act secrets go through the process environment with `-s NAME` (S02-001 row 8);
     - the SSH password comes from Infisical through the environment;
     - `--var` values on argv are non-secret.
   - The product stories' fail-first claims are credible and evidenced.
   - Defects:
     - the digest check still passes on missing lookups (V-01);
     - several wrappers cannot exit 0 or cannot fail (V-06);
     - row 12 uses a tool outside the recorded boundary (V-16).
8. **Plan/state — PASS (minor).**
   - The waves in `plan-2026-10-12-v1.yaml:27-30` match every state `depends_on`:
     - S01-002 ← S01-001;
     - S01-003 and S01-004 ← S01-002;
     - S02-002 and S02-003 ← S02-001;
     - S02-004 ← all seven others.
   - Every story and sprint has an estimate block, and `pm-status verify --scope epic --epic E015` prints `PASS epic E015`.
   - The snapshot predates the last two planning commits and understates HITL time (V-14). Parallel same-file edits exist in wave 2 (V-15).

## Re-validation

Re-checked against the uncommitted working tree (`git diff fd383ef -- _bmad-output/`, 12 files). V-14 (the plan snapshot) is being regenerated separately and is not assessed here.

Rows run locally:
- **V-01 digest probe.** `dig`/`onedigest` exactly as written in the stories and the CI spine. Four cases, expected and actual exit codes:
  - one real image looked up twice: `0`;
  - a real image plus a nonexistent one: `1`;
  - three refs expected, two given: `1`;
  - two different digests: `1`.
- **V-02 confuse probe.** Installed confuse 2.3.0, a root-mode file holding both keys, env `OUTPUTPATH=/certs`. After the `postexportcommand`/`outputpath` keys were popped from the file source's `settings` dict:
  - `postexportcommand`: `resolve()` yields the packaged default first, so `sourceOf` reports `default`;
  - `outputpath`: `resolve()` yields `EnvSource` first, `.get()` returns `/certs`, so `sourceOf` reports `environment`.
- **E015-S01-004 rows 6 and 7** on the pre-story tree. Both exit `1`, which is the expected fail-first. Both terminate: `runatstart` and `watchforchanges` default to false, so the exporter logs "nothing to do" and exits.
- **E015-S02-004 row 1.** Its regex matches the real `pm-status show --sprint` output format (`␠␠E015-S01-001␠…␠backlog`).

| ID | Result | Evidence |
|---|---|---|
| V-01 | RESOLVED | CI AD-12 and E015-S02-002/-004 use `dig` (`MISSING <ref>` on a failed or empty lookup) and `onedigest N` (passes only if the ref count matches, nothing is `MISSING` and one digest remains). E015-S02-004 row 14 also asserts `IMGS` yields 3 and that the digest equals `RUN_DIGEST`. PRD NFR-4 and execution-notes are restated. The probe above shows it can now fail. |
| V-02 | RESOLVED | E015-S01-001 AC 2 withholds by removing the key from the file sources, never by `set()`. `sourceOf` classes are explicit, and `default` is added to the AC 4 and product AD-3 line format. A new test `test_source_of_after_withholding_reports_the_real_fallback_source` was added. The product AD-2 text matches. The probe above confirms the mechanism. |
| V-03 | RESOLVED | CI AD-9 and AD-13 and the E015-S02-002 Interface contracts and checklist require release variables in the `release` environment only. E015-S02-002 row 8 and E015-S02-004 row 6 assert no repository-level `PUBLISH_*` variable. |
| V-04 | RESOLVED | E015-S02-004 AC 13 and row 15a run `tests/test_container_*.py` against `<GHCR image>@$RUN_DIGEST` from the release commit, with `-rs` and no `SKIPPED`. |
| V-05 | RESOLVED | E015-S02-004 Context describes the 0.2.0 → 0.3.1 one-time effect. The pre-check (row 8) records hook/Apprise counts, labelled containers and `cert-distributor`. There is a maintainer acknowledgement (row 8a), first-pass checks (row 18a) and a steady-state second pass (row 19a). E015-S02-002 and E015-S01-002 upgrade notes carry it too. |
| V-06 | RESOLVED | Every rewritten row in E015-S02-001/-002/-003/-004 is one `&&` chain:<br>• `! grep -q` replaces `grep -c` expecting 0;<br>• `actrun` keeps act's exit status, and recipe runs are redirected to a file;<br>• the `.actrc` refusal is `{ …; test $? = 1; }`;<br>• listings are written to files before they are checked;<br>• clean-up is its own row (S02-003 row 11, S02-004 row 20a).<br>The rule is generalised in execution-notes. The only remaining `;` is in clean-up rows, which is acceptable. |
| V-07 | RESOLVED | S01-001, S01-002, S02-002 and S02-003 put `docs/architecture.md` §6 in Files in scope with a grep each (S01-001 row 8, S01-002 row 10, S02-002 row 12, S02-003 row 8). The rule is also in execution-notes. |
| V-08 | RESOLVED | E015-S02-002 AC 5 and routing replace every occurrence. Row 12 and S02-004 row 20 assert that no `to be written by E015` remains in either spine. |
| V-09 | RESOLVED | E015-S01-001 AC 9 covers ADR-0030:110-111 and `operational.md:423`. Row 6 adds `! grep -qE 'under the root-owned$\|against the root-owned'`, and both phrases currently match, so the row fails before the story. |
| V-10 | RESOLVED | E015-S01-002 AC 16a, Files in scope and row 6 (grep plus `test_every_default_setting_has_a_root_trust_class`). MD-21 "Lives in" is updated. |
| V-11 | RESOLVED | PRD FR-2 now distinguishes a hash mismatch (verify) from an input mismatch (rebuild), matching AD-8. |
| V-12 | RESOLVED | PRD NFR-9 now names `unsupported`. |
| V-13 | RESOLVED (stories) | S01-002, S02-002 and S02-004 wording now reads "accepted 2026-10-12". The plan-snapshot line (`plan-2026-10-12-v1.yaml:41`) belongs to V-14. |
| V-15 | RESOLVED | E015-S01-001 owns the `## 0.3.0 → 0.3.1` heading. S01-002 and S02-002 add `###` subsections, and the second to merge rebases. The `pipeline-walkthrough.md` section split is stated in S02-001/-002/-003 and execution-notes. |
| V-16 | RESOLVED | E015-S02-004 row 12 uses `python3.10 -m venv` / `python3.14 -m venv` and that venv's `pip`. |

New findings introduced by the edits:

| ID | Severity | Document:line | Finding | Recommended fix |
|---|---|---|---|---|
| R-01 | MINOR | E015-S02-004.md row 18a (`:340`) | The row asserts that every `.pfx` under `/mnt/certificates` was rewritten after the upgrade and that the fingerprint-file count equals the pre-check `.pfx` count. The exporter never deletes artifacts (AD-8; PRD §5), and only the owner of a shared file set writes. So any `.pfx` left by a domain no longer in the store is neither rewritten nor given a fingerprint file, and the row fails although the release is correct. | Compare against the domains the first pass reported, or limit `find` to the paths of the current store's domains. Alternatively, record stale `.pfx` files in the pre-check and exclude them. |
| R-02 | MINOR | E015-S02-004.md Context (0.2.0 → 0.3.1 paragraph) | "`cert.pem` and the other PEM files are unchanged" is not established for 0.2.0 output: 0.3.0 changed `chain.pem`/`cert.pem` for single-certificate chains (`docs/upgrading.md`, PKCS12 section). Row 19 checks `cert.pem` only, so the claim is not verified. | Say "`cert.pem` unchanged; `chain.pem` may change for single-certificate chains (0.3.0 fix)". Optionally record a `chain.pem` diff beside row 19. |

No new contradiction was found between the PRD, the spines, the decision record and the stories.

**Verdict: READY.** Every V-01 to V-13, V-15 and V-16 finding is resolved. Two new MINOR findings are confined to E015-S02-004's production rows and can be fixed before that story starts (it runs last). V-14 is pending its separate regeneration.
