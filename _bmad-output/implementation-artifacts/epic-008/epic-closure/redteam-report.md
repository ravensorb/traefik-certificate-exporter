# RED TEAM FINDINGS REPORT

**Scope:** Epic E008 — Action-Based Multi-Channel Delivery (epic-level)
**Base:** `dbc991c..HEAD` (cumulative), with concentrated attention on `df6e5ed..HEAD` — the 20 remediation commits no security review had seen
**Date:** 2026-09-03
**Analyst:** Red Team Agent
**Prior work not re-reported:** sprint closure report `epic-008/sprint-01/closure/redteam-report.md` (H1–H3, M1–M6, L1–L3, O1–O4, all remediated); BL-E008-007 (`CODEOWNERS` inert without branch protection)

---

## SEVERITY SUMMARY

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 4 |
| LOW | 2 |
| OBSERVATION | 2 |

---

## SCOPE MAP — WHAT I WIDENED TO, AND WHY

The seed set was the cumulative diff, four stories, ADRs 0006–0012 and the sprint report. Epic-level means the *surface*, not the diff, so I widened to the following and read them as they stand at `HEAD` rather than as deltas.

| Widened to | Why |
|---|---|
| All five workflows at `HEAD` (`ci`, `dev`, `release`, `publish-image`, `verify-build` — 3,342 lines) | The epic's product is a workflow topology. A diff shows what changed; only the whole file shows what the surface now *is*. Findings E1, E2, E6 are properties of the assembled file, invisible in any single hunk. |
| All three composite actions (`verified-bundle`, `setup-poetry-python`, `publication-contract`) | A composite action's steps run *inside* the calling job and hold its authority. The contract suite knows this (`_governed_step_groups`); the credential-reach derivation does not. Load-bearing for E3. |
| `tests/ci/test_workflow_contracts.py` (6,153 lines added this epic) — specifically the registries `RELEASE_FINALIZER_JOBS`, `SHA_PINNED_ACTIONS`, `CREDENTIAL_ACTIONS_ON_MOVING_REFS`, and the derivations `_credential_handling_actions`, `_ordering_steps`, `_alias_moving_jobs` | The governance model *is* this file. Every finding below is a **scope** question — what set does a guard examine — rather than a rule question. E1, E3, E6, E7 are all reach gaps in guards whose rules are correct. |
| `.gitleaks.toml` + `.pre-commit-config.yaml` gitleaks hook + `verify-build.yaml`'s self-test | The gate's behaviour lives in the hook definition, not the workflow. E4, E5. |
| `docs/adr/0009` (accepted-risk register), `docs/operational.md` §"If a publication credential is compromised" | To judge whether the `CREDENTIAL_ACTIONS_ON_MOVING_REFS` acceptance is sound. **It is** — see the note below. |
| **Live platform research**: GitHub Actions concurrency semantics (docs.github.com, fetched 2026-09-03) | The alias transaction's correctness rests entirely on a claimed queueing behaviour. It had to be checked against the platform, not against the comment. This turned E2 from speculative to verified. |
| **Execution** — I extracted `publish-image.yaml`'s tag-composition step body and ran it against 25 adversarial tag lists | The task asked me to get a tag past the new validation. Executing the shipped body is the only way to answer that honestly. Two hypotheses I formed by reading were **wrong** and are recorded as such below. |

### Surface model (internal scaffolding, abridged)

- **Entry points.** Three event owners: `pull_request` → `ci.yaml` (fork-facing, no credentials); `push: branches: [main]` → `dev.yaml`; `push: tags: v*` → `release.yaml`. Two reusable callees (`verify-build.yaml`, `publish-image.yaml`) own no event.
- **Trust boundaries.** (a) verifier ↔ publisher — the verified bundle, revalidated at every crossing; (b) workflow ↔ third-party action — six external owners, four of them credential-adjacent; (c) plan job ↔ publisher — the enabled-destination set and the permitted-repository list; (d) publisher ↔ finalizer — alias ownership (CI-AR29); (e) GitHub ↔ Gitea — `permissions:` semantics differ.
- **Credential sinks.** `GITHUB_TOKEN` (contents:write in `finalize` only; packages:write in three jobs), `FORGE_PACKAGE_TOKEN`, `DOCKERHUB_USERNAME`/`_TOKEN`, and — new this epic — an **ambient OIDC identity** in `publish-package-pypi`.
- **Irrevocable writes, in order.** PyPI upload → forge Release → Git aliases `vN`/`vN.M` → registry aliases `N.M`/`N`/`latest` (stable) or `dev` (development).

---

## FINDINGS

| Severity | ID | Title | Lens |
|---|---|---|---|
| HIGH | E1 | The publisher's alias refusal enumerates only the *stable* channel's alias shapes; the development channel's `dev` alias passes it | EXT, DAR |
| HIGH | E2 | The new ref-free alias concurrency group **cancels** pending finalizers rather than queueing them, stranding or inverting the alias transaction — with no run summary | CHA, ABU, PBR |
| HIGH | E3 | The credential-reach derivation has no notion of an *ambient* credential, so every action in the one irrevocable-destination job — including the newly added `actions/attest-build-provenance@v3` — rides a moving ref unexamined | DAR, PBR |
| MEDIUM | E4 | `gitleaks dir` reads the working tree; the repository's **history is now scanned by nothing**, though the job fetches all of it | EXT, INS |
| MEDIUM | E5 | The gitleaks self-test proves the scanner reads bytes, not that it reads *this repository*: the allowlist is never exercised, and any non-zero exit satisfies it | DAR |
| MEDIUM | E6 | The explicit-`none` scope declaration is scoped to the three registered finalizers; the credential-bearing publisher jobs still rely on "omission denies" on the platform where it grants | PBR, DAR |
| MEDIUM | E7 | `finalize-dev-alias` moves an alias with no job-level concurrency group — the serialisation guard's scope is "decides ordering", not "moves an alias" | CHA |
| LOW | E8 | Tag normalisation is byte/ASCII-only: `latest ` and `1 ` pass the alias refusal, and `"` passes the CSV-metacharacter defence | ABU |
| LOW | E9 | `primary` — the reference that is pulled, smoke-tested and reported as the published image — is positional on the metadata action's output order | CHA |
| OBSERVATION | E10 | The "runs after a registry login" reach test is ordered one way only; `docker/setup-buildx-action@v4` and `docker/setup-qemu-action@v3` run *before* the login and persist the state the credential later flows through | DAR |
| OBSERVATION | E11 | ADR-0009's accepted-risk register is well-formed and its reasoning is sound — recorded explicitly so the reach gap in E3 is not misread as an indictment of the acceptance | DAR |

---

### HIGH

#### E1 — The publisher's alias refusal enumerates only the *stable* channel's alias shapes; the development channel's `dev` alias passes it

**Lens:** External attacker / Design and architecture. **Status: VERIFIED by execution.**

`publish-image.yaml` (step `plan`, "Compose the single Buildx tag list") carries the CI-AR29 boundary — "an alias is the finalizer's sole property" — enforced against the *rendered* tag list because the renderer (`LiquidLogicLabs/git-action-docker-metadata@v6`, a fork on its own floating major) is explicitly not trusted. The step's own comment states the threat model precisely:

> the contract suite asserts `latest=false` is *passed*, which is not the same as *obeyed* … If it ever emitted `latest`, or a bare major or major.minor, the publisher would move an alias from outside the grant while every alias-ownership guard still passed.

The refusal implementing that is:

```bash
reference="${tag##*:}"
if [[ "$reference" == latest || "$reference" =~ ^[0-9]+(\.[0-9]+)?$ ]]; then
```

That covers `latest`, `1`, `1.2` — the stable channel's three aliases. **`publish-image.yaml` is also the development channel's publisher**, and `dev.yaml:736` shows the development alias is the bare name `dev`:

```bash
--tag "${IMAGE_REPOSITORY}:dev" "${IMAGE_REPOSITORY}@${IMAGE_DIGEST}"
```

`dev` matches neither branch of the refusal. The governing test is parametrised with the same hand-written three:

```python
@pytest.mark.parametrize("alias", ["ghcr.io/owner/name:latest", "ghcr.io/owner/name:1", "ghcr.io/owner/name:1.2"])
def test_a_publisher_refuses_to_push_an_alias_however_the_tag_list_was_rendered(alias):
```

and its sibling `test_the_exact_version_a_publisher_does_push_is_still_accepted` asserts `dev-0123456789ab` **must** be accepted — the near-miss that makes the omission look deliberate.

**Attack path.** The threat model is the renderer, exactly as the step's comment states. `git-action-docker-metadata@v6` is a fork of `docker/metadata-action` on a floating major; whoever can move `v6` chooses the rendered list. Emit `<forge-registry>/<owner>/<name>:dev` alongside the legitimate `dev-<sha>` tag. Executed against the shipped step body:

```
refused   :latest
refused   :1
refused   :1.2
ACCEPTED  :dev        <-- the development channel's alias, from the publisher
ACCEPTED  :v1
ACCEPTED  :v1.2
ACCEPTED  :stable
ACCEPTED  :edge
```

`docker buildx bake` then pushes `:dev` from the `publish-image` job.

**Impact.** The `dev` name is moved from outside the finalizer grant, which means it bypasses every check `finalize-dev-alias` performs *before* it moves that same name:
- the just-in-time proof that the candidate is still the head of the protected default branch (`dev.yaml` "Halt unless the candidate is still that head");
- the stable-tag suppression re-check — a commit carrying an exact `vX.Y.Z` must publish *nothing* to the development channel, and the publisher runs before that re-check;
- the finalization gate that requires every enabled destination to have delivered.

So a superseded candidate, or a release commit that the development channel is required to ignore, takes the `dev` name that operators and `:dev`-pinned deployments pull. `finalize-dev-alias` would then correctly refuse — and the name has already moved. The run summary reports the finalizer's refusal, not the publisher's write.

**Recommendation.** Derive the refused set from the source of truth rather than enumerating it. The finalizers are the authority on what an alias is: `release.yaml`'s `finalize-image-aliases` composes `${MINOR_ALIAS#v}`, `${MAJOR_ALIAS#v}`, `latest`; `dev.yaml`'s `finalize-dev-alias` composes `dev`. Invert the rule — a publisher pushes **only** a reference that matches the exact-version shape the identity step proved (`^[0-9]+\.[0-9]+\.[0-9]+$` for stable, `^dev-[0-9a-f]{12}$` for development, passed in as an input from the caller's plan job) and refuses everything else. An allow-list of one shape cannot be out-grown by a new alias the way a deny-list of three was. Extend `test_a_publisher_refuses_to_push_an_alias_however_the_tag_list_was_rendered` to derive its parameters from the alias names the registered finalizers actually write, so a fourth alias reaches the guard without a second edit.

---

#### E2 — The new ref-free alias concurrency group **cancels** pending finalizers rather than queueing them

**Lens:** Chaos engineer / Abusive legitimate user / Platform best practices. **Status: VERIFIED against GitHub's published concurrency semantics (fetched 2026-09-03).**

The alias-inversion remediation has two halves: re-derive ordering at the point of write (sound — see the note at the end of this finding), and serialise the alias stage across runs. The second half is a job-level group on both stable finalizers:

```yaml
concurrency:
  group: ${{ github.workflow }}-aliases
  cancel-in-progress: false
```

ADR-0011:165–168 states the property this is supposed to buy:

> Ref-free, so **every stable run queues behind every other** for the alias stage while the fan-out stays parallel.

**That is not what GitHub does.** Per GitHub's concurrency documentation: there can be **at most one running and one pending** job in a concurrency group at any time, and *"any existing pending job or workflow in the same concurrency group, if it exists, will be canceled and the new queued job or workflow will take its place."* `cancel-in-progress: false` governs the **running** job only; it does not make additional runs queue. Multiple waiting runs require `queue: max` (up to 100), which is a separate option this repository does not set.

Both `finalize` and `finalize-image-aliases` share one group, so a single stable run contributes *two* claims on it.

**Attack path (deterministic, three tags).** A back-port batch or a `git push --tags` after several local releases — the workflow explicitly designs for this ("Two tag pushes are two distinct immutable identities and run independently"):

1. Run A (`v1.2.4`) `finalize` starts, holds the group.
2. Run B (`v1.3.0`) `finalize` queues → pending.
3. Run C (`v2.0.0`) `finalize` queues → **run B's `finalize` is cancelled.**

Run B has already uploaded to PyPI and pushed its image — both irreversible — and now creates no Release, moves no Git alias and moves no image alias. Worse, `release-evidence` is gated `if: ${{ !cancelled() }}`, so **the run summary is not written either**. The release simply is not there, and nothing says so.

**Attack path (two tags, race).** The same cancellation occurs whenever run A's `finalize-image-aliases` queues while run B's `finalize` is still pending — the window between the group being released and FIFO admitting the next claimant. If `finalize-image-aliases` is the job cancelled, run A has **created its Release and moved the Git aliases `v1` and `v1.2`, and not moved the image aliases** — `git rev-parse v1` and `docker pull …:1` disagree permanently, with no summary. That is a partially applied alias transaction, which is precisely the state CI-AR41's evidence and the `attempted`/`moved` bookkeeping exist to make visible; the bookkeeping never runs, because the job never starts.

**Deliberate abuse.** Anyone who can push a tag can push a third throwaway `v*` tag to cancel a pending finalizer, freezing `latest`/`vMAJOR` on an older release or stranding a competitor release half-finalized. The evidence is a *cancelled* run with no step summary — the least-alerting outcome available.

**Impact.** The alias transaction can be inverted or left partially applied by ordinary release operations, and the failure is silent in both directions. The property ADR-0011 records as established is not established.

**Recommendation.**
1. Add `queue: max` alongside `cancel-in-progress: false` on both alias concurrency blocks, so waiting runs queue instead of cancelling each other. That is the option that delivers what the ADR describes.
2. Use **one group claim per run**, not two — either merge the two finalizers' waiting into a single claim or key the group so a run's second job does not re-queue against a sibling run's first.
3. Change `release-evidence` from `!cancelled()` to `always()`. A cancelled finalization is exactly the run whose summary matters most; today it is the only run that produces none.
4. Correct ADR-0011:165–168, and add a contract guard that asserts every alias concurrency block carries `queue: max` — the rule is currently carried by prose that states the opposite of the platform's behaviour.

*Recorded in fairness:* the other half of the remediation is correct and I tried to break it. `test_no_alias_move_consumes_an_ordering_decision_taken_in_another_job` derives its scope from each job's own `outputs:` mapping rather than a filename list, and `finalize-image-aliases` genuinely re-reads the Git tag set at the point of the write. Within a run, the inversion is closed. E2 is a defect in the serialisation half only.

---

#### E3 — The credential-reach derivation has no notion of an *ambient* credential

**Lens:** Design and architecture / Platform best practices.

Sprint finding H1 replaced a name-matching reach guard (`pypi|publish` against the action's repository name) with a derivation. That was the right move and it is a real improvement. The derivation, `_credential_handling_actions`, recognises exactly two ways an action receives a credential:

```python
if "secrets." in handed:          # its own with:/env:
    reasons.add("a secret is passed to it")
if after_login:                    # it runs after docker/login-action in the same job
    reasons.add("it runs after a registry login")
```

Both are *passing* mechanisms. **There is a third, and this epic introduced the job that uses it.** `publish-package-pypi` holds:

```yaml
permissions:
  contents: read
  id-token: write
  attestations: write
environment: pypi
```

An OIDC identity is not passed to a step — it is ambient in the job, as `ACTIONS_ID_TOKEN_REQUEST_URL` / `ACTIONS_ID_TOKEN_REQUEST_TOKEN` in every step's environment. **Every action in that job can mint it**, and the file's own comment states what that is worth:

> Until the second is set, ANY workflow here that can obtain `id-token: write` can mint a PyPI-scoped token, not only this one.

The derivation flags none of them. Concretely, the job's step sequence is:

```
checkout@v7  →  recheck (run)  →  ./verified-bundle  →  stage upload-set/ (run)
             →  actions/attest-build-provenance@v3   →  pypa/gh-action-pypi-publish@dc37677…
```

- `pypa/gh-action-pypi-publish` is SHA-pinned here — but note it receives **no** `secrets.*` in this job (trusted publishing). It appears in `SHA_PINNED_ACTIONS` only because the *forge* job hands it `password: ${{ secrets.FORGE_PACKAGE_TOKEN }}`. Its coverage in the irrevocable job is coincidence, not derivation.
- `actions/attest-build-provenance@v3` — **new this epic** (commit `e50f250`) — is on a floating major, appears in neither `SHA_PINNED_ACTIONS` nor `CREDENTIAL_ACTIONS_ON_MOVING_REFS`, and is placed *between* the final bundle revalidation and the irrevocable upload.
- `actions/checkout@v7` is likewise floating and likewise in that job.

**Attack path.** Whoever can move `actions/attest-build-provenance@v3` (or `actions/checkout@v7`) gets code execution in the one job in this repository that publishes to the one destination from which nothing can ever be withdrawn, and can:
1. **Overwrite `upload-set/`** after every hash check has passed and before `pypa/gh-action-pypi-publish` reads it. Every revalidation in this pipeline — the bundle action, `SHA256SUMS`, `build-manifest.json` — happens *upstream* of that directory sitting on disk. A malicious wheel is published under this project's name at a version number that can never be reused.
2. **Mint the PyPI-audience OIDC token** and upload out-of-band, per the file's own comment, since the trusted-publisher-to-environment binding is a PyPI-side setting the repository cannot make.

Even the attestation is not a check on this: `subject-checksums` reads `SHA256SUMS` and the attest step runs before the swap it would need to detect.

**Impact.** The blast radius CI-AR38 exists to bound — "whoever can move the ref can exfiltrate the credential, with no diff in this repository to review" — applies in full to an action the guard reports as examined. `test_every_credential_handling_action_is_pinned_or_its_risk_is_recorded` asserts `candidates`, is non-empty and passes green over a job it never inspected.

**Honest calibration.** `actions/attest-build-provenance` and `actions/checkout` are GitHub-first-party, and compromising them is a very high bar — higher than the four entries the project *did* record. The finding is not "GitHub is untrustworthy". It is that the repository's own policy says an action that receives a publication credential must be pinned **or** its acceptance written down, and here the policy's reach silently stops at the boundary of "passed in a `with:`", in the newest and most consequential job. Silence is the one outcome the register does not allow — and the register is currently silent because the derivation cannot see the job.

**Recommendation.**
1. Add a third reason to `_credential_handling_actions`: any external action in a job (or in a composite invoked from a job) whose effective `permissions:` include `id-token: write`, `attestations: write`, `packages: write` or `contents: write` is handed a credential ambiently. Derive it from the job's `permissions` mapping, which is already parsed for `test_every_finalizer_states_the_scopes_it_relies_on_being_denied`.
2. Add a fourth: any external action that runs in the same job **before** a step that consumes a credential or a staged artifact — E10 is the registry-login instance of the same blind spot.
3. Then either SHA-pin `actions/attest-build-provenance` and `actions/checkout` in `publish-package-pypi`, or record the acceptance in `CREDENTIAL_ACTIONS_ON_MOVING_REFS` with the ADR-0009 reasoning (first-party owner, revisit condition). Either is defensible; silence is not.
4. Independently: re-verify `upload-set/` immediately before the upload step, or attest and upload from a step that no third-party action precedes. The staging directory currently has an unguarded window in front of an irreversible write.

---

### MEDIUM

#### E4 — `gitleaks dir` reads the working tree; the repository's history is now scanned by nothing

**Lens:** External attacker / Malicious insider.

Sprint H2 found the gate reading zero bytes (`gitleaks git --pre-commit --staged` under `--all-files`). The remediation overrides `entry:` to:

```
gitleaks dir --redact --no-banner --config .gitleaks.toml .
```

This fixes "reads nothing" and simultaneously changes the *domain*: `gitleaks git` walks commit objects; `gitleaks dir` walks the checked-out tree. A credential committed in any commit and removed in a later one is present in the repository's history — retrievable by anyone who can clone, which for a public repository is everyone — and is now examined by **no gate at all**, local or CI.

The gap is stark because the material is right there: the `gitleaks` job checks out with `fetch-depth: 0, fetch-tags: true`. The full history is fetched and only the tip is read.

The prose makes this harder to notice rather than easier. `.gitleaks.toml` says "The gate had been passing over every commit of this project without reading any of it" — which reads as though the fix now reads every commit. It reads one.

**Attack path.** Commit a credential (an accident, or an insider's deliberate staging), push, then remove it in a follow-up commit within the same PR. Every gate is green: `gitleaks dir` sees the cleaned tree; the CI self-test passes; review sees a diff that removes a secret. The credential is live in `refs/pull/*` and in the branch's history indefinitely.

**Recommendation.** Run both forms — keep `gitleaks dir` for the tree and add `gitleaks git --redact --no-banner --config .gitleaks.toml .` as a second hook, or a second CI step in the same job that already fetches the history. Extend `test_the_secret_scanner_reads_content_rather_than_the_index` to assert both domains are covered, since it currently asserts only that the invocation is not the index form. If history scanning is deliberately out of scope, say so in `.gitleaks.toml` and correct the sentence that implies otherwise — per the project's own rule, prose that overstates its coverage stops the next reader looking.

---

#### E5 — The gitleaks self-test proves the scanner reads bytes, not that it reads *this repository*

**Lens:** Design and architecture.

`verify-build.yaml`'s "Prove the scanner reads content" is a genuinely good idea, well built in one respect — it reads the invocation from `.pre-commit-config.yaml` rather than restating it. Its **scope** has two gaps.

**(a) The allowlist is never exercised.** The fixture is written to `$(mktemp -d)/planted.py` and the last argv element is swapped for that directory. `.gitleaks.toml`'s three path allowlists (`^\.agents/`, `^\.claude/`, `^_bmad/`) are anchored patterns that cannot match a file at the root of a temp directory. So the self-test's verdict is identical whether the allowlist is the current three entries or a fourth entry reading `^src/` or `^\.github/`. A widened allowlist — the single most likely way this gate silently stops covering the repository — is invisible to the check that exists to catch exactly that. Only a *universal* allowlist would be caught, because it would also swallow the fixture.

`test_the_secret_scanner_and_pre_commit_exclude_the_same_vendored_trees` asserts the two lists stay *identical to each other*; neither list is checked against what must be scanned. Two lists agreeing is not the same as either being right.

**(b) Any non-zero exit satisfies it.**

```bash
if "$scanner" "${argv[@]}"; then
  echo "the configured gitleaks invocation passed over a planted credential:" >&2
  exit 2
fi
echo "the scanner read the planted credential and failed, as required"
```

gitleaks exits non-zero for a finding **and** for a usage error, an unparsable config, an unreadable path, an unknown subcommand. The check never confirms the failure was a *finding*. Compounding this, the binary is located by `find "$HOME/.cache/pre-commit" -type f -perm -u+x -name gitleaks | head -1` — with more than one cached revision present (a `rev:` bump leaves both), `head -1` selects by directory order, so the self-test may exercise a different binary from the one the real hook runs.

**Attack path.** A change to the entry's flag order — e.g. moving the scan path off the end — makes `argv[last]` the wrong token; the swapped invocation errors out non-zero; the self-test reports success while exercising nothing. The real scan continues with whatever the edited entry now means.

**Recommendation.** Assert the *outcome*, not the sign of the exit code: require exit status `1` **and** require the planted secret's rule id or redacted fingerprint in the output. Plant the fixture **inside the repository working tree** at a path the allowlist does not cover, and plant a second fixture inside an allowlisted tree asserting it is correctly ignored — that turns the check into a test of the allowlist's shape rather than of the binary's existence. Resolve the scanner path from pre-commit's own resolved hook environment rather than `find | head -1`.

---

#### E6 — The explicit-`none` scope declaration is scoped to the three registered finalizers

**Lens:** Platform best practices / Design and architecture.

Sprint H3 established the platform fact: GitHub treats an unlisted `permissions:` scope as `none`; Gitea does not document that semantic and ships `TokenPermissionMode` permissive by default, so on the forge E009 targets, **omission grants where GitHub denies**. The remediation adds explicit `contents`/`packages`/`id-token`/`attestations` to three jobs, and a guard:

```python
for workflow, job_name in sorted(RELEASE_FINALIZER_JOBS):
    ...
    for scope in AUTHORITY_SCOPES:
        assert scope in declared
```

The scope of the fix is `RELEASE_FINALIZER_JOBS` — a hand-kept registry of three `(workflow, job)` pairs. But the platform fact is not about finalizers; it is about **every job on that runner**. The jobs that hold real publication credentials and do *not* state their denials:

| Job | Declares | Silently granted on permissive Gitea |
|---|---|---|
| `release.yaml: publish-package-forge` | `contents: read` | `packages`, `id-token`, `attestations` — and this is *the Gitea path*, the only package publisher that runs there |
| `release.yaml: publish-package-pypi` | `contents: read`, `id-token: write`, `attestations: write` | `packages` |
| `release.yaml: publish-image` (and `publish-image.yaml`'s own block) | `contents: read`, `packages: write` | `id-token`, `attestations` |
| `release.yaml: plan`, `verify`, `release-evidence`; `dev.yaml` equivalents | `contents: read` | `packages`, `id-token`, `attestations` |

**Impact.** The disjointness property CI-AR24/CI-AR40 assert — "this job holds an OIDC identity and no registry credential; that job holds registry credentials and no OIDC identity … disjoint by construction" — is constructed from omission in every job except the three finalizers, on the platform where omission does not deny. On Gitea the two credential sets are not disjoint, and no guard says so. The guard's own docstring names the correct principle ("Denial is stated, never inferred") and then derives its scope from a registry of three.

This is the same shape as the finding it remediates, one level up: H3 was "the split rests on an inferred semantic"; E6 is "the fix for that rests on a hand-enumerated set of jobs."

**Recommendation.** Derive the scope from capability, not from `RELEASE_FINALIZER_JOBS`: **every job in a governed workflow that declares any `permissions:` block, or that receives any secret, must state all four `AUTHORITY_SCOPES` explicitly.** That set comes from the parsed documents and grows on its own. Then add the declarations. When testing the guard, plant the violation against the *scope* — add a new credential-bearing job with a partial `permissions:` block and confirm the guard fails.

---

#### E7 — `finalize-dev-alias` moves an alias with no job-level concurrency group

**Lens:** Chaos engineer.

`test_a_job_that_decides_alias_order_serialises_against_every_other_run` states the property it wants — *"so the alias stage of one run cannot interleave with another's"* — and then derives its scope as jobs where `_ordering_steps(job)` is non-empty, i.e. jobs that take a **version-ordering decision**. `dev.yaml`'s `finalize-dev-alias` moves the `dev` image alias and takes no ordering decision (there is nothing to order — `dev` is a single moving name), so it is outside the guard's scope and carries no job-level `concurrency`. Confirmed: no `concurrency:` key on that job.

The residual race is the one the job's own comment describes and then only partly closes:

> Concurrency already cancels a superseded run, but cancellation is not instantaneous and the two events are unordered, so the head is re-read here.

The re-read is a TOCTOU check: `git rev-parse HEAD` → *(window)* → `docker buildx imagetools create … :dev`. Run A (commit 1) passes the head check, is cancelled by run B but has not yet died; run B (commit 2) completes its alias move; run A's in-flight `imagetools create` lands afterwards and `dev` points at the **older** commit. The workflow-level group (`${{ github.workflow }}-${{ github.ref }}`, `cancel-in-progress: true`) narrows this a great deal — every `main` push shares one group — but narrowing is what the stable channel judged insufficient and answered with a job-level group.

The asymmetry is the finding: the same class of race gets a ref-free serialising group in `release.yaml` and nothing in `dev.yaml`, and the guard's derived scope is what permits the difference. Note that a *sibling* guard, `test_the_alias_ordering_scope_covers_registry_aliases_not_just_git_ones`, gets this right — it derives from `_alias_moving_jobs` and explicitly plants a violation in `dev.yaml`. The serialisation guard uses the narrower derivation.

**Recommendation.** Widen the scope from `_ordering_steps` to `_alias_moving_jobs()` — every job that moves an alias serialises, whether or not it ordered anything — and give `finalize-dev-alias` a ref-free group. Apply E2's `queue: max` at the same time. Plant the scope attack: a job that moves an alias and takes no ordering decision must fail the guard.

---

### LOW

#### E8 — Tag normalisation is byte/ASCII-only, and the CSV defence is comma-only

**Lens:** Abusive legitimate user. **Status: VERIFIED by execution.**

Two gaps in `publish-image.yaml`'s composition step, both reachable only under the untrusted-renderer threat model that motivates the step:

**(a) `tr -d '[:space:]'` strips ASCII whitespace only.** U+00A0 and U+2028 survive normalisation. Executed:

```
ACCEPTED  :latest       (the alias refusal is a string equality, and this is not `latest`)
ACCEPTED  :1            (and this does not match ^[0-9]+(\.[0-9]+)?$)
ACCEPTED  1.2.3 
```

An OCI tag is `[A-Za-z0-9_][A-Za-z0-9._-]{0,127}`, so the registry rejects these — the practical impact is a failed push after the build, not a moved alias. It is recorded because the alias refusal is a **string test on unnormalised input**, and the step's comment presents the normalisation as complete.

**(b) The CSV-metacharacter defence is comma-only.** The step rejects commas because buildx parses the `TAGS` env override of a `list(string)` as CSV. `"` is CSV's other metacharacter and passes: `…/name:1.2.3"` is ACCEPTED and reaches `docker buildx bake`. Because a new comma cannot be introduced, no new field can be smuggled, so this is a parse hazard rather than a bypass. The comment's rationale — "an image reference has no business carrying one" — applies verbatim to `"` and to embedded whitespace.

**Recommendation.** Replace both ad-hoc tests with one positive assertion on the whole reference after normalisation: `^[a-z0-9._:/-]+:[A-Za-z0-9_][A-Za-z0-9._-]{0,127}$`. An allow-list of the OCI grammar refuses every case above by construction, and does not need extending each time a new metacharacter is thought of. Use `LC_ALL=C tr` or a byte-class strip explicitly, so the ASCII-only behaviour is chosen rather than inherited from the runner's locale.

#### E9 — `primary` is positional on the metadata action's output order

**Lens:** Chaos engineer.

`primary="${primary:-$repository}"` takes the repository of the **first** tag in the rendered list. That value becomes `image-reference`, and therefore the reference that is resolved to a digest, pulled, smoke-tested, and reported as the published image. The list comes from the same untrusted renderer everything else in this step guards against; if it ever ordered `images:` output the other way, the published-index assertion and the smoke test would run against **Docker Hub** rather than the forge registry, and the run summary would report a Docker Hub reference as the published image. Both destinations carry the same digest from one Buildx invocation, so this is an evidence-correctness issue rather than a publication one.

**Recommendation.** Take `primary` from `inputs.registry` joined to the caller's proven forge repository — a value the plan job proved — rather than from the position of a tag in a rendered list.

---

### OBSERVATIONS

#### E10 — The "runs after a registry login" reach test is ordered one way only

`_credential_handling_actions` sets `after_login = True` when it passes `docker/login-action`, and flags subsequent steps. The reasoning is right: an action that can read `~/.docker/config.json` is handed a credential without being passed one. The same reasoning applies **before** the login to any action that persists runner state the credential later flows through. In `publish-image.yaml`, `docker/setup-qemu-action@v3` (which runs a privileged container to install binfmt handlers) and `docker/setup-buildx-action@v4` (which creates the builder instance that subsequently receives and uses the registry credentials) both run before both logins and are therefore unflagged. Both are approved-owner floating majors under CI-AR4, which is a defensible position — but it is currently an *unexamined* position rather than a recorded one, which is the distinction `CREDENTIAL_ACTIONS_ON_MOVING_REFS` exists to enforce. Folded into E3's recommendation 2.

#### E11 — ADR-0009's accepted-risk register is sound; recorded explicitly

I went looking for an unsound acceptance, because the task asked whether the `CREDENTIAL_ACTIONS_ON_MOVING_REFS` entries are defensible, and because the sprint report had identified `LiquidLogicLabs` as third-party and not security-reviewed. The register holds up:

- Each of the four entries names the action, the specific credential it receives, and the reason it is an entry rather than a pin (ADR-0009:93–124).
- The maintainer-ownership claim is recorded with its provenance (confirmed at sprint closure) rather than asserted.
- A **revisit condition** is stated (ADR-0009:127): "the maintainer stops controlling `LiquidLogicLabs`, any of those actions gains a …".
- The `pypa` split is reasoned rather than owner-wide — `pypa` stays an approved owner and only the one credential-bearing action is pinned harder.
- The guard enforces both directions: an action cannot be in both registries, and a **stale** entry (one no longer derived as a candidate) fails the suite, so the register cannot outlive what it accepts.

The reasoning behind the maintainer-owned entries is also substantively correct in a way the entries understate: if one account controls both the action repository and this repository, compromising that account already compromises this repository, so the floating ref adds little marginal blast radius. Worth writing into the ADR, since a future reader without that step may read "maintainer-owned" as a trust assertion rather than a blast-radius argument.

The register is not the problem. **Its reach is** — see E3.

---

## EXECUTIVE SUMMARY

**What was reviewed.** Epic E008's complete delivery surface as it stands at `HEAD`: five GitHub Actions workflows (3,342 lines), three composite actions, the 6,153-line contract suite that constitutes this project's governance model, the secret-scanning gate in both its hook and CI-self-test forms, and ADRs 0006–0012. Attention was weighted toward the 20 remediation commits `df6e5ed..HEAD`, which closed every sprint-level finding and which no security review had seen. I widened past the seeds to the assembled workflows, the guard **derivations** rather than the guard rules, and one live platform-documentation check on GitHub's concurrency semantics. Two findings are verified by executing the shipped code — I extracted `publish-image.yaml`'s tag-composition step and ran it against 25 adversarial tag lists — and two hypotheses I formed by reading (glob injection through the unquoted repository comparison; a normalisation gap between the three Docker Hub spellings) were **disproved by that execution** and are not reported.

**Overall risk posture: MEDIUM-HIGH.** This is an unusually well-defended pipeline, and the remediation was real: the credential-reach guard now derives from what an action receives instead of matching its name; the secret scanner reads content and proves it in CI; alias ordering is re-derived at the point of write; the permitted-destination check validates the repository and not just the authority — I attacked that last one hard and could not get a tag past it. Every finding below is of one shape, and it is the shape this project has already named as its own recurring failure mode: **the rules are right and the guards' derived scopes fall short of them.** Four of the eleven findings (E1, E3, E6, E7) are a correct rule enforced over a hand-enumerated or too-narrow set, in each case with the guard reporting green over the part it never examined.

**The single most dangerous finding is E2** — the ref-free alias concurrency group cancels pending finalizers instead of queueing them. It is the most serious for four reasons: it is triggered by *ordinary release operations*, not by an adversary (pushing three tags in a batch is deterministic; two tags is a race); it produces exactly the alias inversion and partial application that F4 and the whole finalizer split exist to prevent, after the irreversible half of the transaction has committed; it is **silent** — a cancelled job leaves `release-evidence` skipped under `if: !cancelled()`, so the one run whose summary matters most produces none; and ADR-0011 records the opposite of the platform's actual behaviour as an established property, so the next reader has no reason to look. It is also weaponisable: anyone who can push a tag can cancel a pending finalizer with a throwaway `v*` tag and freeze `latest` on an older release, with a cancelled run and no summary as the only trace. **E1 is a close second** and is the most cleanly exploitable — the shared publisher's alias refusal covers `latest`, `1` and `1.2` and lets `dev` through, so the development channel's alias can be moved from outside the finalizer grant, bypassing the just-in-time default-branch-head proof and the stable-tag suppression re-check that are the only things standing between a superseded or release-tagged commit and the `dev` name operators pull.

**The single most important recommendation:** apply this project's own rule 4 to the four reach gaps — *derive the scope from the source of truth, never enumerate it by hand* — and, when testing each guard, plant a violation that attacks the **scope** rather than the rule. Concretely: derive the publisher's refused-alias set from the alias names the registered finalizers actually write (E1); derive credential reach from a job's `permissions:` mapping as well as from what a step is passed (E3); require explicit `AUTHORITY_SCOPES` on every credential-bearing job rather than on three registered finalizers (E6); and scope the alias-serialisation guard to `_alias_moving_jobs()` rather than to jobs that decide ordering (E7). Alongside that, one platform correction stands on its own and should ship first because it is a one-line change protecting an irreversible transaction: add `queue: max` to both alias concurrency blocks and change `release-evidence` to `always()` (E2).

---

## Notes on this run

- Sanctum was at birth state (`BOND.md` and `MEMORY.md` unpopulated), so no prior owner context, accepted risks or analysis preferences informed this pass. Everything above is derived from the artifacts.
- **Verified by execution:** E1, E8 (the tag-composition step body extracted from `publish-image.yaml` and run against crafted inputs). **Verified against authoritative platform documentation:** E2 (GitHub Actions concurrency — at most one running and one pending job per group; a new queued job cancels the existing pending one; `queue: max` is the option that queues). **Verified by reading the shipped definitions and the guards that govern them:** E3, E4, E5, E6, E7, E9, E10, E11.
- **Nothing here is marked speculative.** Two read-derived hypotheses that execution disproved were dropped rather than hedged: (i) glob-metacharacter injection through the repository-membership comparison — the command substitution *is* quoted and the pattern is literal; (ii) a normalisation gap between `docker.io`, `index.docker.io` and bare `owner/name` — `normalize_repository` handles all three symmetrically and I could not separate them.
- Not re-reported, per scope: sprint H1–H3, M1–M6, L1–L3, O1–O4; BL-E008-007 (`CODEOWNERS` inert without branch protection — factored into the trust model for E6 and E11, since every governance registry named above is a hand-kept list in a test file that no separate reviewer is required to approve).

Sources consulted live: [Control the concurrency of workflows and jobs — GitHub Docs](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency), [Workflow syntax for GitHub Actions — `concurrency`](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#concurrency).
