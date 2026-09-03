# E008-S01 sprint closure review — `clean-release` + `adversarial`

**Dispatched by:** `l3io-pm-execute` sprint-closure §2–3 · `epic_key: E008` · `sprint: S01` · `work_type: MIXED`
**Lenses:** `clean-release`, `adversarial` (one pass, one diff, two stances)
**Reviewed at:** `df6e5ed` · **Date:** 2026-09-02

---

## What was examined, and what was widened

**Scope as dispatched.** `/tmp/e008-closure/sprint-diff.txt` (3,267 lines, +2,752) is the sprint diff
restricted to *production* files: the two composite actions, `dev.yaml`, `release.yaml`,
`publish-image.yaml`, ADRs 0006/0010/0011, `docs/operational.md`, `docs/ci/codex-assesment.md`,
`pyproject.toml`, and the two deleted shell scripts.

**Widened, with reason.** The dispatched diff does **not** contain the guards, which the brief names in
scope and whose reach is one of the two things the adversarial lens was asked to attack. The real sprint
range is `921e5b9..HEAD` = **8,888 insertions / 566 deletions across 43 files** — the figure the brief
quotes. The dispatched file omits `tests/ci/test_workflow_contracts.py` (**+3,947**), `tests/support.py`
(+51), `tests/ci/test_publication_contract.py` (+54), `tests/test_release_version.py` (+39), the two new
workflow fixtures, `build.sh` (−150) and the `_bmad-output` artifacts. I regenerated the full production
diff (`git diff 921e5b9..HEAD -- . ':(exclude)_bmad-output' ':(exclude)poetry.lock'`, 7,650 lines) and
reviewed the guards, the fixtures and `build.sh`'s deletion alongside it. I also read the five workflows
and three composite actions **as they stand on disk**, not only as diff hunks, because a workflow's
correctness is a property of the whole file.

**Method.** Two independent passes over the same material: a workflow-semantics pass (what breaks under
re-run, cancellation, partial failure and racing) and a dedicated guard-reach pass over the full
5,024-line contract suite. Every guard-reach finding below was **verified by planting the violation in a
throwaway copy of the repository and running the entire suite** — not by reading. Where a candidate was
ruled out, the ruling is recorded with its counter-evidence, including one of my own draft findings that
the planting exercise disproved (LOW-5).

**Guard count.** 124 test *functions* (AST count of `def test_*`), expanding to **215 collected cases**
after `@pytest.mark.parametrize`. The brief's "124 guards" is correct as a function count.

**Suite status on HEAD.** `python -m pytest tests/ci/test_workflow_contracts.py` → **1 failed, 214
passed**. See CRITICAL-1. That single pre-existing failure is the baseline against which every planted
violation below was measured, so "214 passed" in a finding means *the planted violation fired nothing*.

**Not duplicated.** The credential surface is a parallel red-team pass. This report touches credentials
only where a *correctness* property — a guard's reach — happens to be expressed through them, which is
squarely this lens (HIGH-2).

**This review is not clean.** Seventeen findings follow: a currently-red CI job, and **four separate
instances** of the epic's recurring guard-reach defect, one of which is the literal artefact of the first
instance left half-fixed.

---

## Findings — `clean-release`

### CRITICAL-1 · the sprint's own closure artifact breaks CI

**Where:** `_bmad-output/implementation-artifacts/epic-008/sprint-01/closure/review-E008-S01-004.md:197,198,205,215`
against `tests/ci/test_workflow_contracts.py:4886-4926`.

**The concrete failure.** `test_the_retired_local_build_paths_are_gone_and_nothing_invokes_them` scans
**every file git tracks** for `RETIRED_INVOCATION`, with exactly one exemption (the guard module itself,
asserted by identity). Story 004's closure review — committed in this sprint at `df6e5ed` — analyses the
guard's own pattern in a markdown table, and that table contains the strings the guard is built to
reject. Reproduced:

```
FAILED tests/ci/test_workflow_contracts.py::test_the_retired_local_build_paths_are_gone_and_nothing_invokes_them
AssertionError: _bmad-output/.../closure/review-E008-S01-004.md invokes the retired 'docker/build.sh'
```

The pattern's "naming versus invoking" heuristic is a lookbehind on a single backtick
(`(?<![\w./$`-])`), which exempts `` `build.sh` `` but not `` `bash docker/build.sh` `` — where the
backtick precedes the *command*, not the path. Prose that quotes an invocation in order to document the
guard is therefore indistinguishable from an invocation.

**Consequence.** The sprint cannot close green. Every subsequent run on `main` is red until this is
fixed, and the first thing an operator will reach for is `INVOCATION_SCAN_EXEMPTIONS` — growing the
hand-kept list this epic exists to eliminate.

**Remediation.** Do **not** grow the exemption set file by file. Either narrow the scan's *derived* scope
to files that can actually invoke a script (tracked files outside `_bmad-output/`) and replace the
now-false docstring claim "every file git tracks"; or extend the naming rule to any backtick-delimited
inline span (`re.sub(r"`[^`\n]*`", "", text)` before searching), which is the honest form of the rule
already intended. Either way, plant a violation that attacks the *new* scope: an invocation in a justfile
recipe and one in a fenced block must still fail.

### HIGH-1 · a guard's proof-of-reach names a module that no longer exists

**Where:** `tests/ci/test_workflow_contracts.py:2335-2336`.

```
Planted to prove it: dropping the `object_type == "tag"` filter from
`stable_tags.annotated_tags` makes the lightweight case pass, and this test fails.
```

`scripts/stable_tags.py` was deleted this sprint; the guard now executes the workflow's real `run:` body
instead. The docstring's planting instruction cannot be carried out by anyone. Per global rule 3, a
recorded plant is the *evidence* that a guard has reach — an unfollowable one is a claim with nothing
behind it, and it stops the next reader from checking.

**Remediation.** Restate the plant against what the guard now runs: "deleting the
`[[ "$(git for-each-ref --format='%(objecttype)' ...)" == tag ]]` line from the `tag` step's body makes
the lightweight case pass." One line, and it is checkable.

### LOW-1 · stale forward-looking comment in `publish-image.yaml`

**Where:** `.github/workflows/publish-image.yaml:3-5` — *"…becomes the fifth workflow file **once
release.yaml lands**; story E008-S01-004's topology assertion expects those five."*

`release.yaml` landed at `a15e4f1`, and the topology guard was rewritten this sprint into a *partition*
property precisely because an exactly-four count was the epic's fourth guard-reach defect. The comment
describes neither the present nor the guard. **Remediation:** drop the tense and the count — "reusable
only, like `verify-build.yaml`; a trigger here would make it an event owner and fail the topology
partition."

### LOW-2 · deleted-script references, triaged

| Reference | Verdict |
|---|---|
| `docs/adr/0011:107-108` names `finalizer_gate.py`/`stable_tags.py` | **correct** — the ADR *recording their deletion* |
| `docs/adr/0006:12` names `git-increment-version.sh` | **correct** — "the previous …" |
| `closure/review-E008-S01-003.md` quotes `finalizer_gate.py` | **known, exempt** — historical closure record, per the brief |
| `test_workflow_contracts.py:1444` names `forge_coordinates.py` | **correct** — rationale for why the module went |
| `test_workflow_contracts.py:2336` | **HIGH-1 above** |
| `stories/E008-S01-00{1,2,3}.md` describe the modules as "new surface" | **defer** — historical like closure records, but nothing marks them superseded. One line each ("retired in 003; the derivation is now a workflow step") would stop a reader treating them as current |
| `scripts/release_version.py` `stable_tags` field; `dev.yaml:265` `stable_tags=` | **not references** — a dict field and a shell variable sharing a name |
| `tests/test_release_version.py:633` | **correct** — the guard keeping `git-increment-version.sh` deleted |

**No TODO/FIXME/HACK/XXX/WIP markers, no debug artifacts, no commented-out code, and no secret- or
credential-shaped literals** in any changed file. Three `TODO|placeholder|DEBUG` grep hits are legitimate
prose (`x-access-token` is a documented fixed userinfo placeholder; `-ll DEBUG` is a runbook log-level
flag). `build.sh` and `docker/build.sh` are gone; `scripts/` holds only `committed_versions.py`,
`dump-pkcs12.py`, `release_version.py`; the retired `publication-plan`/`release-receipt` schemas leave
behind only their own retirement guards. **`markdown-it-py ^3.0.0`** was added to read
`docs/operational.md` as blocks, with a comment naming global rule 1 and the hand-written block splitter
it avoided — correct call, correctly recorded.

---

## Findings — `adversarial`

### The recurring defect, found four more times

The brief asked whether there is a fifth instance of "a guard that proves its rule but examines the wrong
set". There are four. Ordered by what they leave uncovered.

---

### HIGH-2 · the first instance was fixed on one line and left intact on the next

**Where:** `tests/ci/test_workflow_contracts.py:66`, consumed at `:354`, `:360`, `:368`.

```python
def _governed_definitions() -> tuple[Path, ...]:
    """Tier 1 scope, derived from the filesystem rather than enumerated by hand.

    The previous hand-kept 2-tuple examined ci.yaml and verify-build.yaml only, so the
    four credential-bearing workflows and every composite action were governed by
    nothing. ..."""
    return tuple(sorted(WORKFLOWS.glob("*.yaml")) + sorted(ACTIONS.rglob("action.yml")))

GOVERNED_DEFINITIONS = _governed_definitions()

# Tier 2 scope. ...
SECRET_FREE_WORKFLOWS = (CI_WORKFLOW, VERIFY_WORKFLOW)      # <-- eight lines below
```

**This is the artefact of defect #1, still in place.** Tier 1's hand-kept 2-tuple was replaced by a
filesystem derivation. The **identical 2-tuple** was left eight lines down to carry the *tier-2* rules —
the ones that matter most: `SECRET_FREE_PROHIBITIONS` covers `secrets:`, `id-token: write`,
`packages: write`, `docker/login-action@`, `actions/cache@`, `runs-on: self-hosted`, `secrets: inherit`.
Its two siblings, `test_fork_verification_has_no_publisher_capability_or_persistent_runner` and
`test_pull_request_adapter_is_minimal_and_fork_safe`, are hardcoded to the single constants
`VERIFY_WORKFLOW` and `CI_WORKFLOW`.

**Intended coverage:** every workflow that executes fork-authored code must never hold a publishing
capability (ADR-0007 invariant 2).

**Mutation, planted and verified.** Add `.github/workflows/pr-preview.yaml` with
`on: pull_request: branches: [release/**]`. The branch filter is disjoint from `ci.yaml`'s `main`, so the
topology guard accepts it — that exact shape is *asserted lawful* by
`test_the_topology_accepts_a_workflow_that_races_nothing[disjoint-branch-literal-space]`. The planted
file runs fork PR code on `runs-on: self-hosted` with `permissions: packages: write`, `actions/cache@v4`,
`docker/login-action@v3` and `password: ${{ secrets.PREVIEW_REGISTRY_TOKEN }}` — **every entry in
`SECRET_FREE_PROHIBITIONS`**. Result: **`214 passed`**. Not one guard fired. (One incidental red,
`test_the_runbook_names_every_channel_...`, clears with one sentence in `docs/operational.md`.)

**Second mutation, cheaper, no new file.** The prohibitions are matched as raw substrings against the
file text, and the list contains `"secrets:"` but not `"secrets."`. Adding to `ci.yaml`'s `plan` job:

```yaml
      - name: Leak
        env:
          NPM_TOKEN: ${{ secrets.NPM_TOKEN }}
        run: echo "$NPM_TOKEN" > /tmp/t
```

leaves the suite at **`214 passed`**. A named secret is materialised in a job that checks out and runs a
fork's PR head. `test_no_workflow_exposes_a_secret_at_workflow_scope` reads workflow-level `env:`/
`defaults:` only; `test_pull_request_adapter_is_minimal_and_fork_safe` never looks at step `env:`.

**Remediation.** Derive the fork-facing set the way the topology guard already closes over local calls:

```python
def _fork_facing_definitions() -> tuple[Path, ...]:
    """Workflows that can execute fork-authored code: any `pull_request*` owner, plus
    every local workflow/action reachable from one."""
    # seed from _declared_events(...) & {"pull_request", "pull_request_target"},
    # then close over `uses: ./...` as _topology_findings' `called` set does.
```

and add `"secrets."` to `SECRET_FREE_PROHIBITIONS` — or, better, assert per job over `json.dumps(job)`
using `_is_credential_bearing()`, which already exists at `:222`. Plant the scope attack: a second
`pull_request`-triggered workflow with `packages: write` must fail.

---

### HIGH-3 · `dev.yaml` moves an alias and the alias-ordering guard cannot see it

**Where:** `tests/ci/test_workflow_contracts.py:657-687`, against `.github/workflows/dev.yaml:666-691`,
and the claim at `.github/workflows/dev.yaml:497-500`.

The rule is right; the *set* is keyed on an action name:

```python
moves_aliases = any(
    str(step.get("uses", "")).startswith(APPROVED_ALIAS_ACTION)   # git-action-tag-floating-version
    for candidate in _jobs(_load_workflow(path)).values()
    for step in (candidate.get("steps", []) or [])
)
if not moves_aliases:
    continue
```

`dev.yaml` moves the `dev` image alias with `docker buildx imagetools create` (`dev.yaml:684`) and
contains no `git-action-tag-floating-version` step. Executed against the real files:

```
ci.yaml             moves_aliases(guard scope)=False   moves_registry_alias(real)=False
dev.yaml            moves_aliases(guard scope)=False   moves_registry_alias(real)=True   <-- excluded
publish-image.yaml  moves_aliases(guard scope)=False   moves_registry_alias(real)=False
release.yaml        moves_aliases(guard scope)=True    moves_registry_alias(real)=True
verify-build.yaml   moves_aliases(guard scope)=False   moves_registry_alias(real)=False
```

`release.yaml` is covered only *incidentally*, because it also moves a Git alias with the approved
action. Remove that one step and it leaves the checked set too, while still moving three image aliases.

**Concrete failure.** A `skopeo inspect` or `buildx imagetools inspect` in any job of `dev.yaml` —
deciding whether to advance `dev` from what the registry currently holds — passes this guard. That is the
retired-CI-AR26 revival the guard exists to prevent, in the file the sprint just taught to move an alias.

**It is also asserted false in the workflow.** `dev.yaml:497-500`: *"Story 003 adds an alias finalizer
here, and from that moment a registry read in any job of this file would fail
`test_alias_ordering_is_decided_from_git_never_from_a_registry`."* Story 003 added the finalizer. The
claim is untrue, and it is exactly the prose global rule 3 warns about — it stops the next reader looking.

**The correct derivation exists 2,270 lines down the same file.** `_alias_moving_jobs()` (`:2926-2942`)
covers both spellings and its docstring says *"Derived rather than enumerated, so an alias step added to
a publisher shows up here without anyone editing a list."* This guard does not use it.

```python
alias_files = {workflow for workflow, _ in _alias_moving_jobs()}
assert alias_files, "no workflow moves an alias; this guard examined nothing"
for path in sorted(WORKFLOWS.glob("*.yaml")):
    if path.name not in alias_files:
        continue
```

Plant the scope attack, not the rule attack: `buildx imagetools inspect` in **`dev.yaml`'s plan job** must
fail. And correct the `dev.yaml:497-500` comment.

---

### HIGH-4 · `_channel_workflows()` keys the scope of ten guards on one literal path

**Where:** `tests/ci/test_workflow_contracts.py:1259` (constant at `:1187`).

```python
PUBLISH_IMAGE_REFERENCE = "./.github/workflows/publish-image.yaml"
def _channel_workflows() -> list[Path]:
    return [path for path in sorted(WORKFLOWS.glob("*.yaml"))
            if any(job.get("uses") == PUBLISH_IMAGE_REFERENCE
                   for job in _jobs(_load_workflow(path)).values())]
```

The docstring claims derivation, and it is derived — from *whether the workflow publishes a container
image*, not from whether it publishes anything. Ten guards take their entire scope from it, including
`test_publisher_credentials_stay_disjoint_between_destinations` (`:1799`),
`test_step_based_publishers_re_read_the_tag_set_before_they_upload` (`:1981`),
`test_optional_destination_credentials_are_gated_on_the_enabled_set` (`:2805`) and
`test_every_finalizer_waits_for_every_publisher_and_reads_every_result` (`:3120`).

**Mutation, planted and verified.** Add `nightly.yaml`, `on: push: branches: [nightly]` (disjoint from
`main`, so the topology guard accepts it), with a `plan` job, a `verify` job calling the governed
verifier, and one `publish-package-pypi` job holding `id-token: write` that uploads via
`pypa/gh-action-pypi-publish`. Give it `fetch-depth: 1` on every checkout, no tag re-read before the
upload, no aggregator job, no finalizer, and ungated optional credentials. **`214 passed`.** It ships no
image, so it is not a "channel workflow", so none of the ten guards looked at it.

Note the circularity: `test_the_image_fan_out_is_one_buildx_invocation_carrying_every_tag` forbids a
channel workflow from running `buildx build` — but a workflow that builds and pushes an image inline is,
by this derivation, not a channel workflow.

**Remediation.** The correct derivation already exists in this file at `:4877`:

```python
return [p for p in sorted(WORKFLOWS.glob("*.yaml"))
        if _trigger_surface(_load_workflow(p)) and _publishers(_load_workflow(p))]
```

Use it for the ten; keep the image-specific subset as a separate helper for the image-only guards.

---

### HIGH-5 · hand-kept trigger-event tuple in the ship-without-verifying guard

**Where:** `tests/ci/test_workflow_contracts.py:498`, inside
`test_any_push_triggered_workflow_verifies_before_it_ships`.

```python
        if not (events & {"push", "release", "workflow_dispatch", "schedule"}):
            continue
```

The comment records that the previous filter (`push` alone) let an `on: release:` publisher through — and
the fix widened the literal set by one entry rather than deriving it.

**Mutation, planted and verified.** The same `nightly.yaml`, retriggered as
`on: repository_dispatch: types: [nightly]`, with the `verify` job **deleted entirely**. A job with
`id-token: write` uploads to PyPI having run no tests. **`214 passed`** — `repository_dispatch` is not in
the tuple, so the guard `continue`d past the file. `workflow_run`, `merge_group`, `pull_request_target`
and `create` have the same hole.

**Remediation.** The complement is already defined at `:4360`. Invert it rather than enumerating:

```python
        if not (events - NON_AUTOMATIC_EVENTS):   # {"workflow_call", "workflow_dispatch"}
            continue
```

or drop the event filter entirely and gate on `_publishers(document)`, which the next lines already
compute.

---

### HIGH-6 · two stable releases race, and `v1`/`latest` can be dragged backwards

**Where:** `release.yaml:41-43` (concurrency), `:698-739` (the ordering decision), `:866-875` and
`:929-1006` (the alias moves).

The concurrency group is `${{ github.workflow }}-${{ github.ref }}`. Two *different* tags are two
different refs, so `v1.2.3` and `v1.3.0` run **fully in parallel** — deliberately: *"Two tag pushes are
two distinct immutable identities and run independently."* The ordering decision (`advance-major`, from
`git for-each-ref --merged --sort=v:refname`) is taken once in `finalize` and consumed later by
`finalize-image-aliases`. Nothing re-reads it, and nothing serializes the two runs' alias writes.

1. `T0` — `v1.2.3` pushed. Run A's `finalize`: `v1.2.3` is greatest → `advance-major=true`.
2. `T1` — `v1.3.0` pushed. Run B starts.
3. `T2` — Run B's `finalize`: `v1.3.0` is greatest → `advance-major=true`. B moves `v1`, `latest` and the
   image aliases to `1.3.0`.
4. `T3` — Run A, slower (a Docker Hub leg, a retried QEMU build), executes
   `imagetools create --tag repo:latest --tag repo:1 repo@<v1.2.3 digest>`.

`latest` and `v1` now point at **v1.2.3**, and both runs are green. This is precisely the failure F4
exists to prevent — the guard prevents it *within* a run and is silent *across* runs. The Git aliases go
the same way: `git-action-tag-floating-version` moves unconditionally, and A's decision was correct when
taken and stale when applied. The decision is also stale *within* a single run: `finalize` decides,
`finalize-image-aliases` applies, and a `v1.3.0` landing between the two jobs inverts the aliases with no
second run involved.

**Remediation (either, or both).**
- **Serialize the alias writers.** Give `finalize` and `finalize-image-aliases` a job-level
  `concurrency: { group: ${{ github.workflow }}-aliases, cancel-in-progress: false }` — ref-free, so every
  stable run queues behind every other for the alias stage only. The fan-out stays parallel.
- **Re-prove greatness at the point of the write.** `finalize-image-aliases` already re-checks the tag
  peel (`:892-906`); have it re-run the `--sort=v:refname` comparison from the same authority and refuse
  if the released tag is no longer greatest. This closes the within-run window that concurrency alone
  does not.

Guard it by property: assert that every job in `_alias_moving_jobs()` either carries a ref-free
`concurrency.group` or re-evaluates `ALIAS_ORDER_MARKER` at a step index below its first
`_writing_steps()` index.

---

### HIGH-7 · an enabled destination can receive no tag at all, and every gate reports success

**Where:** `publish-image.yaml:159-215` (the tag-permission check), `release.yaml:619-680` (the finalizer
gate), `:329-337` (the rendered tag set).

The "Compose the single Buildx tag list" step enforces one direction only: *a tag must not address a
destination this run did not log into*. The symmetric direction — *an enabled destination must receive at
least one tag* — is enforced nowhere. The finalizer gate cannot fill the hole and says so: *"a job result
carries no evidence of WHICH destinations it addressed, and one job ships several."*

**Concrete failure.** `PUBLISH_IMAGE_DOCKERHUB=true`. `plan` composes and validates
`dockerhub-repository`, sets `image-dockerhub: enabled`, and hands the docker.io line to
`LiquidLogicLabs/git-action-docker-metadata@v6` through a `format()` on a possibly-empty second `images:`
entry (`release.yaml:331-334`). If that third-party action renders only the first repository — an
empty-line edge case, a fork's behaviour change, a `flavor`/`tags` interaction — then Buildx pushes only
to the forge; the permission check passes (no forbidden authority appears); `publish-image` succeeds; the
gate joins `{"image-dockerhub":"enabled"}` with `"success"` → **ok**; the Release is created and the Git
aliases advance; and `finalize-image-aliases` then runs
`imagetools create docker.io/ns/name:latest docker.io/ns/name@sha256:…` against a digest never pushed to
Docker Hub, failing *after* the irreversible Release and with `latest` already advanced on the forge.

**Remediation.** One `elif` in the loop that already computes `authority` per tag:

```bash
if [[ "$DOCKERHUB_ENABLED" == "true" && " $seen_authorities " != *" docker.io "* ]]; then
  echo "dockerhub is enabled but no tag addresses docker.io: the enabled set and the" >&2
  echo "rendered tag list have drifted" >&2
  exit 2
fi
```

Guard it by **executing** the step — the file already does this for the forbidden direction
(`test_every_published_tag_addresses_a_destination_the_run_logged_into`) — with a planted input of
`dockerhub: true` and a forge-only tag list.

---

### MEDIUM-1 · `imagetools create` with several `--tag`s is not atomic, and the evidence assumes it is

**Where:** `release.yaml:992-1006`. The comment asserts an invariant the tool does not provide:

> "`latest` and `MAJOR` mean the same thing, so they must not be two writes that can disagree — and a
> single `imagetools create` is the only spelling in which they cannot."

`docker buildx imagetools create -t a -t b <src>` pushes the manifest to each tag **sequentially**. A
registry error, a rate limit or a token expiry between the two leaves `MAJOR` moved and `latest` not.
Worse, `moved+=(...)` is appended only *after* the whole call returns (`:1004-1006`), so the
`trap report EXIT` summary reports **"Moved: none"** for a repository where one alias did move — the
reconciliation record CI-AR41 exists to provide, reporting the opposite of the truth. The runbook's
escalation table has no row for this state.

**Remediation.** Move the bookkeeping inside the failure domain — record each reference as *attempted*
before the call and *moved* after, and report both lists — drop the atomicity claim, and add a "partially
aliased registry" row to the escalation table naming `imagetools create` as its cause and re-running that
one job as its resolution (idempotent for the same digest).

### MEDIUM-2 · `gates` derived from one exact `needs:` shape, backed only by a hand-kept job-name set

**Where:** `tests/ci/test_workflow_contracts.py:1166-1171`, in `test_every_gate_job_blocks_the_distribution_job`.

```python
    gates = {name for name, job in jobs.items()
             if job.get("needs") == "source-integrity" or job.get("needs") == ["source-integrity"]}
```

**Intended coverage:** "a gate that does not block the build is decorative" — every job in
`verify-build.yaml` that can fail must be in `distribution.needs`.

**Mutation, planted and verified, in two steps.** Add a `pip-audit` job with
`needs: [source-integrity, poetry-lock]` and a body of `run: exit 1`, not in `distribution.needs`. The
*only* guard that fires is `test_verifier_supports_call_and_direct_dispatch_with_the_same_graph`
(`:959`), which asserts an exact hardcoded 10-element job-name set — a red that names the job-name
literal and nothing else, so the natural fix is to add `"pip-audit"` to it. Having done so:
**`214 passed`**, with a permanently-failing gate job in the verifier that `distribution` does not depend
on. The two-element `needs:` shape put it outside `gates`, and `assert gates` stayed non-empty on the
other eight.

**Remediation.** Derive from the graph, not from the shape of one `needs:` value:

```python
    blocking = _transitive_needs(jobs, "distribution")
    assert set(jobs) - {"distribution"} <= blocking, sorted(set(jobs) - {"distribution"} - blocking)
```

### MEDIUM-3 · the default branch is spelled three ways, and one of them fails open by going silent

**Where:** `release.yaml:129` (`DEFAULT_BRANCH_REF: origin/main`), `dev.yaml:15-16`
(`on: push: branches: [main]`), `dev.yaml:559` (`ref: ${{ github.event.repository.default_branch }}`).

One fact, three spellings, and the two channels chose **opposite** answers — `release.yaml` a literal,
`dev.yaml` the event field. `BL-E008-005` records this for `release.yaml` alone and correctly notes both
spellings fail closed *there*. What is not recorded: `dev.yaml:15` is the third spelling and it fails
**silently** — rename the default branch and `dev.yaml` simply stops triggering. No run, no red, no alert:
"green run, aliases unmoved, nothing reported", one level up. And `dev.yaml:559`'s
`github.event.repository.default_branch`, if empty on Gitea's `act_runner` (recorded as unverified),
makes `actions/checkout` fall back to the default branch and *appear* correct while proving nothing.

**Remediation.** Pick one authority, derive the other two, and guard the derivation: assert no workflow
contains a literal default-branch name outside the `on:` trigger, and that `dev.yaml`'s just-in-time head
checkout refuses an empty ref rather than defaulting. Fold into `BL-E008-005`; do not open a fourth issue.

### MEDIUM-4 · the "single producer" guard still identifies the producer by an output-name substring

**Where:** `tests/ci/test_workflow_contracts.py:1341-1349`.

```python
produces = "enabled-destinations" in outputs or any("version" in name for name in outputs)
if produces and not _is_credential_bearing(job):
    continue
```

The docstring records that a previous form escaped "by naming the output, which is the guard reading a
label instead of a role" — and the fix retained a *second* label test. This is the epic's second defect
(`package-version`) in a milder form: a job declaring any output whose name contains `version` and holding
no secret is exempted from the toggle scan and may read `PUBLISH_*` directly, reintroducing the
two-readers drift F7 exists to prevent.

**Remediation.** Define the producer by **role**, from the file: the job every finalizer's gate reads
`needs.<job>.outputs.enabled-destinations` from — derivable from `_gate_steps()`, already asserted
non-empty there. Drop the `"version" in name` clause. Plant: a publisher declaring an output named
`image-version` and reading `PUBLISH_IMAGE_DOCKERHUB` must fail.

### MEDIUM-5 · textual assertions where semantic parsing was available

Three raw-text guards whose brittleness or blindness is load-bearing rather than cosmetic:

- **`:354`** `assert forbidden not in source` over raw YAML — simultaneously over-broad (a *comment*
  saying `secrets:` fails it) and blind (no `secrets.` entry). This is HIGH-2's second half.
- **`:698`** `re.findall(r"uses:\s*(\./[^\s#]+)", text)` in
  `test_no_workflow_calls_a_local_workflow_or_action_that_does_not_exist` — a quoted reference
  (`uses: "./.github/workflows/x.yaml"`) does not match, so a dangling local `uses:` written that way is
  unchecked. `_action_references(path)` exists three hundred lines above, written precisely because
  "reading these with a line regex silently misses" forms. Use it.
- **`:884`** `"release-please" not in text` — a raw substring over the whole file; a comment explaining
  why release-please is *not* used would fail it, and any other release bot passes.

Ruled acceptable: `:938`'s whitespace-sensitive `POETRY_VERSION` regex (returns `[]` and fails loudly),
and `test_publication_contract.py:388`'s `assert "secrets:" not in raw`, which is documented as
deliberately textual for one file.

### LOW-3 · "re-run all jobs is prohibited" is a rule with no mechanical enforcement

**Where:** `docs/operational.md` ("Prohibited recovery actions"), against `release.yaml:420-425`,
`:508-511`, `dev.yaml:364-369`, `:464-468`.

Neither `pypa/gh-action-pypi-publish` invocation sets `skip-existing` — correct, since the runbook depends
on the destination's own rejection as the conflict detector and
`test_no_publisher_queries_a_destination_before_uploading` forbids probing first. But it means a
whole-workflow re-run re-attempts every immutable upload, which is why the runbook prohibits it. That
prohibition lives **only in prose**, and per global rule 3 a rule that lives only in prose will be
violated invisibly.

**Decision taken, since I have no inbox:** I am *not* proposing a `github.run_attempt` guard.
`run_attempt` distinguishes a re-run from a first attempt, not a *whole* re-run from a *failed-jobs*
re-run, so such a guard would refuse the legitimate recovery the runbook prescribes. **Remediation:**
state explicitly in `docs/operational.md` that this prohibition is procedural and unenforced, and name
what *is* enforced (the destination's rejection, and the finalizer gate blocking aliases).

### LOW-4 · nothing keeps the three deleted Python modules deleted

**Where:** `tests/ci/test_workflow_contracts.py:4886` — `RETIRED_LOCAL_PATHS = ("build.sh", "docker/build.sh")`.

`scripts/git-increment-version.sh` is covered by `tests/test_release_version.py:633-640`, but
`scripts/forge_coordinates.py`, `scripts/stable_tags.py` and `scripts/finalizer_gate.py` — all deleted
this sprint, all replaced by workflow steps, all with ADRs recording why the module form was wrong — have
**no** guard keeping them gone.

**Remediation.** This one is genuinely an allowlist (a deleted path cannot be derived from a source of
truth that no longer mentions it), so the honest form is one list, in one place, with a comment saying it
is hand-kept and why. Add the three modules to `RETIRED_LOCAL_PATHS` (renaming it) and extend the
existence assertion. Do **not** extend `RETIRED_INVOCATION` to Python module names before fixing
CRITICAL-1 — the same prose-versus-invocation collision would recur immediately and more often, because
ADR-0011 and three story files name all three modules.

### LOW-5 · the recheck-count assertions are brittle, not vacuous — a draft finding, disproved

**Where:** `tests/ci/test_workflow_contracts.py:4004-4032` (`assert len(refusers) == 4`, `== 3`).

I drafted this as a MEDIUM: an "exactly N" standing in for a derivable property, so adding a new
irreversible act without a re-check would leave the count at 4 and the guard silent. **Planting
disproved it.** The one silent mutation available — deleting the re-check in `finalize-image-aliases`
(`release.yaml:903`) and duplicating one into `publish-package-pypi` to hold the count at 4 — is caught
by `test_every_refusal_a_finalizer_makes_precedes_everything_it_writes` (`:3790`), because that re-check
is `finalize-image-aliases`'s **only** `REFUSAL_MARKERS` match. And a *new* publisher or finalizer is
covered by the placement guard at `:2015`, whose scope is `_publishers()` and which asserts a re-check
below the first publishing step. Recorded as LOW for the residual brittleness only: the counts will need
editing whenever a destination is added, and the docstring should say the *placement* guard is what
proves the property.

---

## What I checked and found sound

A clean verdict is worth nothing without saying where it was earned. Ruled-out candidates are recorded
with their counter-evidence, not merely omitted.

- **The finalizer gate `jq` program** (`release.yaml:645-680`, `dev.yaml:604-655`) is a genuine join of
  two maps, not a reading of either. Every branch traced: `--argjson` rejects malformed or absent JSON
  *before* the program runs (so a failed `plan` job, whose output is the empty string, fails the gate
  rather than yielding an empty set); an empty enabled set refuses; a key in one map and not the other
  refuses in **both** directions; unknown result and unknown state values refuse rather than defaulting.
  `disabled` + `success` correctly passes; `enabled` + `skipped` correctly blocks. The two copies are
  byte-identical.
- **`!cancelled()` versus `always()`** at both job and step level, with `RELEASE_FINALIZER_JOBS` requiring
  the condition to be *present* rather than merely constrained (`:592-615`) — closing the "no `if:` at
  all" failure that forbidding `always()` alone leaves open.
- **The four stable tag re-checks and three suppression re-checks** are byte-identical once uncommented,
  and each is executed against real git with a real annotated-tag fixture. Lightweight-tag,
  floating-alias, prerelease, zero-padded, four-component and wrong-commit cases are all parametrised and
  executed, not read.
- **Fail-closed derivation.** An unrecognised forge exits 2 in both plan jobs rather than guessing a
  registry. A `PUBLISH_*` toggle that is not `true`/`false`/absent fails the plan job rather than being
  coerced. A Docker Hub repository that is not a legal lowercase `<namespace>/<name>` fails the plan job.
  An absent or malformed digest halts the alias step rather than composing `repo@`.
- **`_alias_moving_jobs()` == `RELEASE_FINALIZER_JOBS`** is asserted as **equality in both directions** —
  a registered-but-unused grant and an unregistered alias mover both fail. This is why HIGH-3 is one
  guard's oversight rather than a systemic gap.
- **Exact-equality assertions ruled acceptable:** the verifier's 10-job set (`:967`), the composite
  action's input set (`:894`), the three Dependabot ecosystems (`:1136`), `producers == {"plan"}`
  (`:2521`), `DESTINATION_CLASSES` with `assert len(addressed) == 1` (`:2001`), and `_render()`'s
  `KeyError`-on-unbound-expression (`:3011`). Each fails *loudly* on drift rather than silently
  under-covering. (MEDIUM-2 is the exception that proves the rule: `:967` firing *alone* is what makes
  that hole reachable.)
- **`WORKFLOWS.glob("*.yaml")`** everywhere is safe: `test_governance_scope_is_derived_from_disk` (`:254`)
  compares the globs against `WORKFLOWS.iterdir()` and `ACTIONS.rglob("*")`, so a `.yml` workflow or an
  `action.yaml` fails there rather than slipping past.
- **`tests/support.py:tracked_text_files`** is correctly derived from `git ls-files`, with a landmark
  assertion rather than a file-count floor.
- **Non-emptiness preconditions** are present on the guards that need them —
  `test_ref_writing_and_registry_alias_privileges_never_meet`, `test_no_finalizer_builds_anything`,
  `test_every_finalizer_waits_for_every_publisher_and_reads_every_result`, the placement guard, and the
  verifier-caller guard all end in `assert examined` / `assert destinations` / `assert verifier_callers`.
- **The topology guard** was rewritten this sprint from an exactly-four count into a partition property
  over parsed `on:` blocks, with planted violations for a second owner, a triggered reusable workflow and
  an orphan. The epic's fourth defect is genuinely fixed, not renamed.
- **Runbook claims verified against code, not accepted:** the 30-day retention (`verify-build.yaml:663`),
  the `Suppressed by stable tag` evidence row (`dev.yaml:747`), and all five cited guard names exist. No
  phantom flags, no phantom guards — the failure mode that cost this project weeks previously.
- **The accepted races are recorded, not hidden.** The F16 tag window in `dev.yaml` is documented in the
  workflow, the runbook and the story, with its recovery stated and its cost accepted explicitly. HIGH-6
  is reported precisely *because* it is the one race **not** in that record.

---

## Triage

| ID | Lens | Severity | Disposition |
|---|---|---|---|
| CRITICAL-1 | clean-release | CRITICAL | **must fix** — CI is red on HEAD |
| HIGH-1 | clean-release | HIGH | **must fix** |
| HIGH-2 | adversarial | HIGH | **blocks closure** — fork-facing tier-2 scope |
| HIGH-3 | adversarial | HIGH | **blocks closure** — alias-ordering scope |
| HIGH-4 | adversarial | HIGH | **blocks closure** — ten guards' scope |
| HIGH-5 | adversarial | HIGH | **blocks closure** — ship-without-verifying scope |
| HIGH-6 | adversarial | HIGH | **blocks closure** — alias inversion across runs |
| HIGH-7 | adversarial | HIGH | **blocks closure** — silent under-publication |
| MEDIUM-1 … MEDIUM-5 | adversarial | MEDIUM | fix in place (MEDIUM-3 folds into `BL-E008-005`) |
| LOW-1, LOW-2 | clean-release | LOW | defer to issues |
| LOW-3, LOW-4, LOW-5 | adversarial | LOW | defer to issues |

**Ordering note for the fixer.** HIGH-2, HIGH-4 and HIGH-5 share one root cause and one remedy shape:
three scope helpers that should be derived from `_publishers()`, `_trigger_surface()` and the local-`uses:`
closure the topology guard already computes. Fix them together, and plant one workflow that attacks all
three scopes at once — the `nightly.yaml` and `pr-preview.yaml` shapes above are ready-made regression
fixtures.

**Assumption recorded, no decision awaited:** I treated story files
(`stories/E008-S01-00{1,2,3}.md`) as historical records under the same exemption the brief grants the
closure record, and reported their stale "new surface" references as LOW-2 rather than as defects. If
sprint closure treats stories as living documents, LOW-2 becomes a must-fix.
