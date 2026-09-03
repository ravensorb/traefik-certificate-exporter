# RED TEAM FINDINGS REPORT

**Scope:** Epic 8, Sprint 01 (E008-S01) — the publication surface: `dev.yaml`, `release.yaml`,
`publish-image.yaml`, `verify-build.yaml`, `ci.yaml`, three composite actions, `docker-bake.hcl`,
the contract guard suite, and the pre-commit gate configuration those workflows execute.
**Work type:** MIXED
**Date:** 2026-09-02
**Analyst:** Red Team Agent (`l3io-sec-redteam`), dispatched by `l3io-pm-execute` sprint-closure §4
**Tree state analysed:** `df6e5ed` (working tree; note this is *ahead* of the supplied
`/tmp/e008-closure/sprint-diff.txt`, which predates `ef3a532` and `df6e5ed` — findings are against
the shipped files, not the stale diff)

---

## SEVERITY SUMMARY

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 3 |
| MEDIUM | 6 |
| LOW | 3 |
| OBSERVATION | 4 |

**On the absence of a CRITICAL.** It is not a clean bill. Two of the three HIGHs are *certain*
defects rather than probabilistic ones — H2 is a security gate proven to scan zero bytes, and H1 is
a documented policy (ADR-0009) that four shipped `uses:` lines violate while the guard written to
prevent exactly that reports green. Neither is scored CRITICAL only because neither is reachable by
an adversary who does not already hold either repository write or control of a third-party org.
The vocabulary's CRITICAL bar — "exploitable today" — is not met; the risk is real.

---

## SCOPE MAP — WHAT I WIDENED TO, AND WHY

Seeds given: the sprint diff, five workflows, three composite actions, four stories, four ADRs,
`tests/ci/test_workflow_contracts.py`.

Widened to, with reason:

| Widened to | Why |
|---|---|
| `.pre-commit-config.yaml`, upstream `gitleaks@v8.30.1` hook definition | `verify-build.yaml` delegates six of its eight gates to pre-commit hooks. The gate's *behaviour* lives there, not in the workflow. This is where H2 was found. |
| `docker-bake.hcl` | `publish-image.yaml`'s only push command is `buildx bake`; the tag list reaches the registry through this file's `TAGS` variable, not through the workflow. |
| `scripts/committed_versions.py` | Sole producer of `package-version` / `poetry-version`, both written straight to `$GITHUB_OUTPUT`. Needed to rule out output injection. Ruled out — both are regex-validated (`:42`, `:54`, `:70`). |
| `.github/dependabot.yml`, absence of `.github/CODEOWNERS` | The whole governance model is hand-kept registries in a test file. Who can edit them, and with what review, is the control. → M4. |
| `docs/guidelines.md` §6, `docs/adr/0010` | To establish whether `LiquidLogicLabs` is maintainer-owned or third-party. It is third-party, identified by GitHub search on 2026-08-30, not security-reviewed. Load-bearing for H1. |
| `docs/operational.md` | Recovery capability (DAR lens). Publication recovery is well covered; credential compromise is not. → O1. |
| `.agents/`, `.claude/`, `AGENTS.md` (1,229 tracked files each tree) | AI-poisoning cross-cut. This repository's development model is agent-driven and the instructions those agents follow are versioned in-tree. → M6. |
| Gitea Actions token-permission documentation (live) | `release.yaml`'s authority split is expressed in `permissions:` and the project explicitly targets Gitea (CI-AR6, E009). → H3. |
| PyPA trusted-publishing security model (live) | The OIDC job is new this sprint. → M3. |

**Entry points.** `ci.yaml` (`pull_request` → fork-controlled), `dev.yaml` (`push: main`),
`release.yaml` (`push: tags v*`), `verify-build.yaml` (`workflow_dispatch`, write-access only).
No `pull_request_target`, `workflow_run`, `issue_comment`, `schedule`, or `repository_dispatch`
anywhere — verified mechanically.

**Trust boundaries.** fork source → verifier (no secrets); verifier artifact → publisher
(`verified-bundle`, revalidated before every login); plan job outputs → publishers; third-party
action → job credential set. The last one is where the findings concentrate.

**Credentials introduced this sprint.** `secrets.GITHUB_TOKEN` at `contents: write` (one job) and
as a registry password (three jobs), `secrets.FORGE_PACKAGE_TOKEN`, `secrets.DOCKERHUB_USERNAME`,
`secrets.DOCKERHUB_TOKEN`, and a PyPI/TestPyPI OIDC identity (`id-token: write`, two jobs).

---

## FINDINGS

### HIGH

---

#### H1 — Four credential-handling actions ride moving refs; ADR-0009's "reach" guard cannot see them because it matches on action *names*

**Lens:** EXT, DAR
**Severity:** HIGH

**Evidence.**

ADR-0009 states the rule plainly: *"For an action handed a publication credential it inverts:
whoever can move the branch can exfiltrate the token on the next run, with no diff in this
repository to review."* It then claims the reach is covered:

> `tests/ci/test_workflow_contracts.py:300` — `test_credential_handling_publishers_are_registered_as_sha_pinned`
> — *"any action whose name contains `pypi` or `publish` must be either registered or explicitly recorded as not credential-handling."*

The candidate set is derived from the action's **name**:

```python
# tests/ci/test_workflow_contracts.py:305-311
publisher_verb = re.compile(r"(?:\A|[-/])(?:pypi|publish)(?:[-/]|\Z)")
...
if not publisher_verb.search(action.split("/", 1)[-1]):
    continue
```

Four references shipped this sprint are handed a credential and match neither word, so the guard
skips them and `test_tier_one_actions_use_approved_owners_and_floating_major_aliases`
(`:277`) takes its floating-major branch and passes:

| Reference | File:line | Credential it receives |
|---|---|---|
| `LiquidLogicLabs/git-action-release@v2` | `.github/workflows/release.yaml:756-758` | `token: ${{ secrets.GITHUB_TOKEN }}` in the repository's **only** `contents: write` job |
| `LiquidLogicLabs/git-action-tag-floating-version@v2` | `.github/workflows/release.yaml:810-822` | `secrets.GITHUB_TOKEN` embedded in `GIT_CONFIG_VALUE_0` on the step's own `env:` |
| `docker/login-action@v3` | `release.yaml:915-919`, `:921-927`; `publish-image.yaml:228-240`; `dev.yaml:659-664` | `secrets.DOCKERHUB_USERNAME`, `secrets.DOCKERHUB_TOKEN`, `secrets.GITHUB_TOKEN` |
| `LiquidLogicLabs/git-action-docker-test@v2` | `.github/workflows/publish-image.yaml:333-337` | none *passed*, but it runs **after** both logins at `:228` and `:235`, so `~/.docker/config.json` on the runner holds the forge and Docker Hub credentials for it to read |

`LiquidLogicLabs` is not maintainer-owned. `docs/guidelines.md:66` records it as a *"Confirmed org
(checked 2026-08-30 via GitHub search — the earlier … search had simply used the wrong handle)."*
That is identification, not review. `git-action-docker-metadata@v6` is additionally described at
`docs/guidelines.md:83` as *"a drop-in fork of `docker/metadata-action`"* — a fork inherits the
upstream's interface, not its security posture, and it produces the tag list every push consumes
(`release.yaml:330`, `dev.yaml:200`).

**Attack path.** An adversary who obtains push access to the `LiquidLogicLabs` org (or to any one
of those four repositories) force-moves the `v2` tag to a commit that appends four lines to the
action's entrypoint. No commit lands in *this* repository, so no review here fires and every
contract guard stays green. On the next `v*` tag push:

1. `release.yaml/finalize` invokes `git-action-release@v2`, handing it a `contents: write`
   `GITHUB_TOKEN` as `INPUT_TOKEN`. The action can push to `main`, rewrite `refs/tags/*`, replace
   Release assets, or simply POST the token out.
2. In the same job, `git-action-tag-floating-version@v2` runs with `GIT_CONFIG_VALUE_0` in its
   process environment — the same token, in a form usable by any subprocess it spawns.
3. In `publish-image.yaml`, `git-action-docker-test@v2` runs at `:333`, after the logins at `:228`
   and `:235`, and reads the Docker Hub token straight out of the runner's docker config.

**Impact.** Full compromise of the publication surface: arbitrary code published to Docker Hub and
to the forge registry under this project's names, arbitrary commits and tags on `main`, and
replacement of Release assets. The `contents: write` grant then re-enters the *next* release
through the source, which the verifier cannot detect because the verifier verifies the source it is
given.

**Why the existing controls do not cover it.** ADR-0009's second guard was written specifically to
supply "reach", and it does — over a set defined by two English words in an action's repository
name. That is a hand-enumerated scope wearing a derivation's clothes. The credential-handling
property is *mechanically derivable* from the workflow: a step is credential-handling iff its
`with:`, `env:`, or enclosing job's `secrets:` block references `secrets.*`, **or** it is ordered
after a `docker/login-action` step in the same job.

**Remediation.**

1. Replace the name heuristic in `test_credential_handling_publishers_are_registered_as_sha_pinned`
   with a derivation over the parsed step: any external `uses:` whose `with`/`env` JSON matches
   `secrets\.`, plus any external `uses:` appearing after a `docker/login-action` step in the same
   job, must be in `SHA_PINNED_ACTIONS` or in an explicit, ADR-backed
   `not_credential_handling` set. Prove the new scope by planting `docker/login-action@v3` as the
   violation and confirming the guard fails.
2. SHA-pin, with a recorded review date beside each `uses:` line (the existing
   `test_every_sha_pinned_publisher_records_the_date_it_was_reviewed` at `:1888` then covers them
   for free): `LiquidLogicLabs/git-action-release`, `git-action-tag-floating-version`,
   `git-action-docker-test`, `git-action-docker-metadata`, `docker/login-action`.
3. Amend ADR-0009 to say the classification is derived from credential *reachability*, not from the
   action's name.

Cited guidance: pinning to a full-length commit SHA is *"currently the only way to use an action as
an immutable release,"* and *"a compromise of a single action within a workflow … would have access
to all secrets configured on your repository, and may be able to use the GITHUB_TOKEN to write to
the repository"* — [Secure use reference, GitHub Docs](https://docs.github.com/en/actions/reference/security/secure-use).

---

#### H2 — The `gitleaks` gate scans zero bytes in CI. Proven: `0 commits scanned … scanned ~0 bytes`, exit 0, on a repository containing a committed credential

**Lens:** DAR, INS
**Severity:** HIGH

**Evidence.**

`verify-build.yaml:162-178` runs the secret scan as one of the eight gates that block the
`distribution` job — and therefore block every publisher:

```yaml
  gitleaks:
    name: Gitleaks
    ...
      - name: Scan tracked content for credentials
        run: poetry run pre-commit run gitleaks --all-files
```

The hook it invokes (`.pre-commit-config.yaml:74-77`) is upstream `gitleaks/gitleaks` at
`rev: v8.30.1`, whose `.pre-commit-hooks.yaml` defines:

```yaml
- id: gitleaks
  entry: gitleaks git --pre-commit --redact --staged --verbose
  pass_filenames: false
```

`--staged` scans the git **index**. `pass_filenames: false` means `--all-files` changes nothing.
A CI runner does a fresh `actions/checkout`; the index is empty — a fact this very workflow
asserts two jobs later at `verify-build.yaml:293` and `:317` (`git diff --cached --exit-code`).

**Reproduction (executed, not reasoned).** Using the exact binary from this machine's pre-commit
cache and the exact hook entry, against a scratch repository whose HEAD commit contains a
detectable credential and whose index is empty — i.e. the CI state:

```
$ gitleaks git --pre-commit --redact --staged --verbose
INF 0 commits scanned.
INF scanned ~0 bytes (0) in 86.6ms
INF no leaks found
exit=0

$ gitleaks dir --redact .          # a scan that actually looks at the tree
INF scanned ~61 bytes (61 bytes) in 3.65ms
WRN leaks found: 1
exit=1
```

Running the hook against this repository as it stands reproduces the green:
`poetry run pre-commit run gitleaks --all-files` → `Detect hardcoded secrets ... Passed`.

**Attack path / impact.** This is a detective control that is entirely absent while reporting
present — the false-green failure mode. In the sprint that introduces `FORGE_PACKAGE_TOKEN`,
`DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` and a PyPI OIDC identity, a token pasted into any tracked
file — a `.env` sample, a runbook, an agent session log, a debugging commit — reaches `main`, the
published sdist, the forge package index, PyPI and the Release assets with every gate green. The
sdist and the Release are *immutable and public*, so the exposure is permanent and unretractable
even after the token is rotated.

**Compounding scope defect.** Even if the invocation is fixed, `.pre-commit-config.yaml:16` sets
`exclude: '^(\.agents|\.claude|_bmad)/'` at file scope. The comment justifying it argues entirely
about *mutating linters* (`ruff-check` runs with `--fix`, the BL-E002-002 incident). Nothing in that
reasoning applies to a read-only credential scanner, yet the exclusion silently takes 1,229 tracked
files per tree — plus `_bmad/memory/`, where agent session logs live — out of its reach.
(`_bmad-output/` is correctly *in* scope: the pattern requires a `/` immediately after `_bmad`.)

**Remediation.**

1. Change the invocation so it scans content rather than the index. Either add
   `args: ["dir", "--redact", "--verbose", "."]` (overriding the upstream entry's default
   subcommand) or, cleaner, define a local hook running `gitleaks dir` with `pass_filenames: false`.
   Whichever is chosen, **verify by planting a credential and confirming the job goes red** — this
   finding exists because nobody did.
2. Move the `exclude:` off the file scope and onto the mutating hooks (`ruff-check`, `ruff-format`,
   `check-toml`, `mypy`) individually, so `gitleaks` sees the whole tree.
3. Add a contract guard that is not satisfiable by the hook's presence: run the configured gitleaks
   invocation against a fixture repository holding a known-detectable secret and assert non-zero
   exit. A guard that asserts "the gitleaks hook is configured" is the guard this repository already
   has, and it passed throughout.

---

#### H3 — The finalizer authority split is enforced by a GitHub-specific `permissions:` semantic that Gitea does not document, and Gitea's default mode is permissive

**Lens:** DAR, PBR
**Severity:** HIGH

**Evidence.**

ADR-0006's split is the sprint's central security claim, restated at
`tests/ci/test_workflow_contracts.py:98-104` and in `release.yaml:564-571`:

```yaml
  finalize:                       # release.yaml:591-595
    permissions:
      contents: write             # and no `packages:` key at all

  finalize-image-aliases:         # release.yaml:877-879
    permissions:
      contents: read
      packages: write
```

On GitHub this is airtight: declaring any `permissions:` block sets every unlisted scope to `none`,
so `finalize`'s token genuinely cannot write packages. `test_ref_writing_and_registry_alias_privileges_never_meet`
(`:3064`) asserts the YAML shape, and correctly so *for GitHub*.

The property is **not** a property of the YAML. It is a property of the runner reading it. This
project targets Gitea as a first-class forge — `release.yaml:83-116` derives Gitea coordinates,
`ADR-0010` exists so *"E009 inherits the Gitea path unchanged"*, and every `runs-on: ubuntu-24.04`
resolves on Gitea to a self-hosted `act_runner`.

Gitea's own documentation confirms job-level `permissions:` are honoured and that the hierarchy is
job → workflow → default, and it enumerates a *different scope vocabulary* — `code` and `releases`
are separate from `contents`, and *"if you specify both `contents` and a more granular scope
(like `code` or `releases`), the granular scope wins."* Two gaps follow:

1. **Partial declarations are undocumented.** The design document specifies fallback only for a
   *missing or unparseable* block: *"If an invalid or unparseable `permissions:` block is
   specified, or no explicit permissions are defined at all, Gitea falls back to using the
   repository's default `TokenPermissionMode`."* Nothing states that scopes omitted from an
   otherwise-valid block become `none`. If they instead retain the repository default, and that
   default is the shipped one — **Permissive**, *"read and write permissions for most units in the
   job's repository (backwards-compatible default)"* — then `finalize`'s token holds `packages:
   write` and the split collapses to nothing on the Gitea side.
2. **A version floor is unrecorded.** Job-level permission enforcement was a proposal
   (go-gitea#24635) before it was a feature. Neither ADR-0006 nor `docs/operational.md` names a
   minimum Gitea version, so an operator running an older instance gets a permissive token in both
   finalizers with every guard green.

**Attack path.** On a Gitea deployment in the default Permissive mode (or below the version floor),
a compromise of *either* finalizer — most plausibly through H1's floating `git-action-release@v2`
or `git-action-docker-test@v2` — yields one token that can both rewrite `main` and push container
images. That is precisely the *"single over-privileged finalizer the split exists to avoid — one
compromised step that can both rewrite history and publish an image"*
(`tests/ci/test_workflow_contracts.py:3068-3070`).

**Impact.** The sprint's headline security property is platform-conditional and the condition is
neither stated nor checked. E009 ("Certified Gitea Portability") will inherit it as an assumption
already blessed by a green suite.

**Remediation.**

1. Add to ADR-0006 an explicit **platform precondition**: the split requires job-level
   `permissions:` with deny-by-default for unlisted scopes. Name the minimum Gitea version and
   require `TokenPermissionMode = restricted` at repository or organization level.
2. Make it fail closed rather than documented: declare every scope **explicitly** in both finalizer
   jobs (`contents: write, packages: none, ...` and `contents: read, packages: write, ...`), and
   add Gitea's granular `code:` / `releases:` spellings alongside `contents:`. An explicit `none`
   needs no inference from any runner.
3. Add a contract guard asserting that a job in `RELEASE_FINALIZER_JOBS` enumerates every scope it
   relies on being denied, rather than relying on omission. Plant the violation by deleting one
   explicit `none`.

Sources: [Actions job token permissions, Gitea Docs](https://docs.gitea.com/usage/actions/token-permissions/);
[gitea/services/actions/token_permission_design.md](https://github.com/go-gitea/gitea/blob/main/services/actions/token_permission_design.md);
[Support configuring permissions of automatic tokens, go-gitea#24635](https://github.com/go-gitea/gitea/issues/24635).

---

### MEDIUM

---

#### M1 — The permitted-destination check validates the registry *authority* and never the repository, so a tag may address any repository at a host the run logged into

**Lens:** EXT, DAR
**Severity:** MEDIUM

`publish-image.yaml:182-208` builds `permitted` from `$REGISTRY` (plus `docker.io index.docker.io`
when Docker Hub is enabled) and tests only the authority segment:

```bash
authority="${tag%%/*}"
if [[ "$authority" != *.* && "$authority" != *:* ]]; then authority="docker.io"; fi
if [[ " $permitted " != *" $authority "* ]]; then
  echo "image tag addresses $authority, which this run did not log in to: $tag" >&2; exit 2
fi
```

The plan job proved two repositories — `steps.forge.outputs.image-repository` and
`steps.destinations.outputs.dockerhub-repository`, the latter regex-checked at `release.yaml:247`.
Neither is compared against the tags actually pushed. The tag list arrives from
`LiquidLogicLabs/git-action-docker-metadata@v6` (`release.yaml:330`), a floating-ref fork (H1).
`test_every_published_tag_addresses_a_destination_the_run_logged_into` (`:2047`) executes the step
but only ever asserts the *authority* rule.

**Attack path.** A compromised or merely misbehaving metadata action emits
`docker.io/<attacker-namespace>/x:1.2.3` alongside the legitimate tags. The authority is
`docker.io`, permitted. `buildx bake` pushes every tag in one invocation with the real
`DOCKERHUB_TOKEN`. A Docker Hub PAT is account-scoped, so the push succeeds anywhere that account
can write, and `primary` (`:210`) — which becomes the digest reference and thus the alias target —
is whichever tag came first.

**Impact.** Publication of this project's verified image under an unintended name, and an
unintended repository becoming the run's `image-reference` in the evidence record.

**Remediation.** Pass the plan's two proven repositories into `publish-image.yaml` as an input and
assert each tag's `repository` is exactly one of them, not merely its authority. Extend the
executed guard with a violation planted at the repository level
(`docker.io/other/name:1.2.3` with Docker Hub enabled) — it passes today.

---

#### M2 — A `http://` forge server URL sends the push credential in cleartext; the endpoint step validates that a scheme exists, not which one

**Lens:** EXT, CHA
**Severity:** MEDIUM

`release.yaml:786-799`:

```bash
if [[ "$FORGE_SERVER_URL" != *://* ]]; then
  echo "forge server URL has no scheme: '$FORGE_SERVER_URL'" >&2; exit 2
fi
{ echo "scheme=${FORGE_SERVER_URL%%://*}"; echo "authority=${FORGE_SERVER_URL#*://}"; }
```

That scheme is then reassembled into the credential URL at `release.yaml:820-822`:
`${scheme}://x-access-token:${{ secrets.GITHUB_TOKEN }}@${authority}/…`.

An internal Gitea instance served over plain HTTP — the deployment shape CI-AR6 exists to support
— makes `git push` transmit a `contents: write` token as HTTP Basic auth over the wire. On GitHub
`github.server_url` is always `https://`, so this is latent today and live the moment E009 lands on
a self-hosted instance. The same value also composes `package_index_url` (`release.yaml:106`),
which carries `FORGE_PACKAGE_TOKEN` to the Gitea package index.

**Remediation.** Refuse any scheme but `https` in the endpoint step, with an explicit,
ADR-recorded escape hatch if an operator genuinely needs plaintext on a trusted network. Add the
same assertion to the forge-coordinate derivation so the package index URL is covered by one rule.
`test_forge_coordinates_are_derived_from_action_context_and_fail_closed` (`:1437`) already executes
that step and is the natural home for the case.

---

#### M3 — No `environment:` protection anywhere: a single tag push carries straight through to an irrevocable PyPI upload with no approval gate

**Lens:** INS, DAR, PBR
**Severity:** MEDIUM

`release.yaml:446-459` declares `id-token: write` for `publish-package-pypi` and no
`environment:`. No publisher job in the repository declares one.

PyPI's own guidance: *"Configuring an environment is optional, but strongly recommended: with a
GitHub environment, you can apply additional restrictions to your trusted GitHub Actions workflow,
such as requiring manual approval on each run by a trusted subset of repository maintainers."*
Without an environment claim, the trusted publisher on PyPI cannot be constrained to one — so **any**
workflow in this repository that can obtain `id-token: write` can mint a PyPI-scoped OIDC token,
not only the reviewed one.

The workflow's own comments acknowledge the stakes: *"PyPI is the one destination from which
nothing can ever be withdrawn: a version number is spent the moment it is accepted"*
(`release.yaml:474-475`). The mitigations built are all *identity* re-checks (`:468-487`) — they
prove the tag still names the commit. None of them introduces a human.

**Remediation.** Create a `pypi` environment with required reviewers, set `environment: pypi` on
`publish-package-pypi`, and re-configure the PyPI trusted publisher to require that environment
claim. Do the same for `publish-package-forge` and the Docker Hub half of `publish-image`. Note the
credit due: *"try to separate building from publishing"* is already satisfied — the verifier builds,
the publishers only upload.

Sources: [Security Model and Considerations, PyPI Docs](https://docs.pypi.org/trusted-publishers/security-model/);
[Publishing with a Trusted Publisher, PyPI Docs](https://docs.pypi.org/trusted-publishers/using-a-publisher/).

---

#### M4 — Every privilege grant in this system is a hand-kept list inside a test file, and nothing requires a separate reviewer for it

**Lens:** INS, DAR
**Severity:** MEDIUM

`RELEASE_FINALIZER_JOBS` (`:98`), `SHA_PINNED_ACTIONS` (`:144`), `APPROVED_ACTION_OWNERS` (`:121`)
and `APPROVED_RELEASE_ACTION` (`:149`) are the authority model. The file says so:
*"adding a name here IS the grant, and each needs an ADR."*

There is no `.github/CODEOWNERS` in this repository. So the grant and the thing being granted are
one commit, reviewable by one person — and in this project's operating model, frequently authored
by an agent. A pull request that adds `("dev.yaml", "publish-image")` to `RELEASE_FINALIZER_JOBS`
and `contents: write` to that job passes every guard in the suite, by construction: the registry
*is* the rule.

The "each needs an ADR" half is prose with no mechanical check — the failure mode
`CLAUDE.md` §3 records verbatim.

**Remediation.**
1. Add `.github/CODEOWNERS` covering `/.github/`, `/tests/ci/test_workflow_contracts.py`,
   `/docs/adr/`, and `/.pre-commit-config.yaml`, with branch protection requiring code-owner review.
2. Add a guard that ties each registry entry to an ADR mechanically: for every
   `(workflow, job)` in `RELEASE_FINALIZER_JOBS` and every entry in `SHA_PINNED_ACTIONS`, assert
   some file under `docs/adr/` names it. Derive the scope from the registries, so a fourth entry is
   covered without an edit.

---

#### M5 — The Release evidence is unsigned and replaceable: `allow-updates: true` plus `contents: write` makes `SHA256SUMS` and `build-manifest.json` attest to nothing an attacker with the same authority cannot forge

**Lens:** DAR, INS
**Severity:** MEDIUM

`release.yaml:764-775` attaches the wheel, sdist, `SHA256SUMS` and `build-manifest.json`, with
`allow-updates: "true"`. The justification given is sound for its own purpose — a stranded run must
be resumable, and `refs/tags/vX.Y.Z` is immutable so a re-run is the same identity.

The security consequence is separate and unaddressed: the four assets are the *only* thing a
downstream consumer can check the wheel against, they are unsigned, and they sit behind a mutable
API call available to anyone holding `contents: write` — including a compromised
`git-action-release@v2` (H1). Nothing in the pipeline produces a signature, an attestation, or a
transparency-log entry: `docker-bake.hcl:36-39` sets `ATTESTATIONS` to `[]` and nothing calls
`cosign`, `actions/attest-build-provenance`, or an equivalent.

The chain therefore proves integrity *within a run* very thoroughly — three independent hashes of
the wheel in `verified-bundle/action.yml:75-121` — and proves nothing at all *after* the run.

**Remediation.** Sign or attest the published artifacts so the evidence has an authority independent
of whoever can write to the Release: `actions/attest-build-provenance` for the wheel and sdist (in
the job that already holds `id-token: write`), and BuildKit provenance/SBOM attestations on the
image index (`ATTESTATIONS` in `docker-bake.hcl`). Record the decision either way in ADR-0008 —
"the evidence is unsigned and this is accepted because X" is an acceptable outcome; silence is not.

---

#### M6 — 1,229 tracked agent-instruction files that any pull request can edit, excluded from every gate, in a repository whose agents hold write access

**Lens:** AIP, INS
**Severity:** MEDIUM

`.agents/skills/**` and `.claude/**` each hold 1,229 tracked files; `AGENTS.md` sits at the root;
`.github/agents/*.agent.md` instruct tooling to *"LOAD the FULL {project-root}/.agents/skills/
<name>/SKILL.md, READ its entire contents and follow its directions exactly!"*

Every one of those paths is excluded from every pre-commit gate by
`.pre-commit-config.yaml:16` (`exclude: '^(\.agents|\.claude|_bmad)/'`), and `pyproject.toml:100`
sets `testpaths = ["tests"]`, so the `.agents/skills/**/scripts/` trees are never executed by the
suite either. The exclusion's stated rationale is entirely about linter noise and `--fix` mutation.

**Attack path.** A fork opens a pull request that edits one line of a `SKILL.md` — inserting an
instruction to add an entry to `RELEASE_FINALIZER_JOBS`, to widen `APPROVED_ACTION_OWNERS`, or to
"helpfully" relax a guard. No gate reads the file. A maintainer reviewing the PR with an agent
session — which is this project's documented working method — has that text loaded as authority by
an agent that holds repository write. The instruction executes as a normal-looking follow-up commit.

This is indirect prompt injection against the governance layer specifically, and this repository's
governance layer is the security control.

**Impact.** Bounded by the maintainer noticing the resulting diff, which is the same protection the
project already judged insufficient for workflows (hence the guard suite). The asymmetry is the
finding: workflows get 124 executable guards, the files that instruct the agent editing them get
none.

**Remediation.**
1. Treat `.agents/`, `.claude/`, `.github/agents/` and `AGENTS.md` as governed surface: add them to
   `CODEOWNERS` (M4) and require code-owner review.
2. Remove them from the `gitleaks` scope exclusion (H2 remediation 2) at minimum.
3. Consider a guard asserting these trees are byte-identical to the installed BMad release they
   claim to vendor — `docs/guidelines.md` calls them *"vendored BMad skills … this project neither
   authors nor maintains them"*, which is a checkable claim and is currently unchecked.

---

### LOW

---

#### L1 — The pre-upload identity re-check drops the default-branch reachability leg the plan job proved, and the sameness guard now freezes that subset

**Lens:** CHA, INS
**Severity:** LOW

`release.yaml:126-173` proves four things about a stable tag: exact `vX.Y.Z` spelling, annotated
object type, peel-to-the-event-commit, **and** `git merge-base --is-ancestor "$source_commit"
"$DEFAULT_BRANCH_REF"` — *"publication is limited to the protected default branch"* (`:162-163`).

The three re-checks immediately before each credentialed step (`:389-394`, `:482-487`, `:691-696`,
`:901-906`) carry the first three legs and not the fourth.
`test_every_stable_tag_recheck_is_the_same_body` (`:4004`) then asserts every copy is byte-identical
once comments are stripped — which is a good guard that has, as a side effect, made the weaker body
canonical.

**Impact.** Narrow: the plan job's proof holds unless `origin/main` moves during the run
(a force-push removing the released commit). In that window a publisher would still upload. Tag
immutability and the plan-time proof make this thin, which is why it is LOW rather than MEDIUM.

**Remediation.** Add the `merge-base --is-ancestor` line to the shared re-check body and pass
`default-branch-ref` (already a plan output, `release.yaml:60`) into each job. The sameness guard
propagates the fix to all four copies for free.

---

#### L2 — `DOCKERHUB_ORG` redirects the stable image push and is validated for shape only, never against an expectation

**Lens:** INS
**Severity:** LOW

`release.yaml:189` reads `vars.DOCKERHUB_ORG`; `:241-256` composes `<org>/<image-name>` and checks
it against `^[a-z0-9][a-z0-9._-]*/[a-z0-9][a-z0-9._-]*$`. A repository variable is not a secret and
its changes are not part of the code review that governs everything else here. Anyone who can set
repository variables redirects every stable image push to a different Docker Hub namespace, using
the project's real `DOCKERHUB_TOKEN` (account-scoped), with no diff and no ADR.

The design reasoning at `:224-239` is sound about *why* the namespace cannot be derived. What is
missing is that the one operator-supplied value in the whole publication path is checked for
shape and nothing else, while `release.yaml:86-89` argues elsewhere that *"there is no
operator-supplied input to validate."*

**Remediation.** Either fold the namespace into the same fail-closed treatment as the registry
(compare against an expected value committed to the repository, so a change is a reviewable diff),
or record in `docs/operational.md` §`DOCKERHUB_ORG` that changing this variable is a
publication-authority change requiring the same review as a workflow edit.

---

#### L3 — An absent `dist-artifact-name` overrides the composite default and makes `download-artifact` fetch everything

**Lens:** CHA
**Severity:** LOW

Every publisher passes `artifact-name: ${{ needs.verify.outputs.dist-artifact-name }}`
(e.g. `release.yaml:400`). `verified-bundle/action.yml:18-20` declares a default of
`verified-dist-v1`, but an explicitly-passed empty string overrides a default rather than falling
back to it, and `actions/download-artifact@v4` with an empty `name` downloads **every** artifact in
the run into `path`.

The bundle revalidation then fails (the contract validator requires exactly one wheel and one sdist
at the directory root), and in `finalize` the enabled-set gate refuses before this step is reached.
So the outcome today is a confusing failure, not an unsafe one.

**Remediation.** Assert the input is non-empty at the top of `verified-bundle/action.yml`, so the
failure names its cause.

---

### OBSERVATIONS

---

#### O1 — There is a publication-recovery runbook and no credential-compromise runbook

`docs/operational.md` covers "Recover a failed release push" (§75), "Publication recovery" (§262),
"When recovery halts and escalates" (§296), "Prohibited recovery actions" (§313) and "Rollback"
(§360) — genuinely good operational work. Searching that file for `revoke`, `rotate`, `compromise`
or `leak` returns only two incidental hits, neither about credentials.

This sprint introduced five publication credentials. Nothing states which to revoke first, that
PyPI uploads cannot be withdrawn so a compromise means yanking a version rather than deleting it,
or that a Docker Hub PAT and a forge package token have different blast radii. Add a short
"Credential compromise" section listing every credential, its scope, where it is configured, and
the revocation order. This is cheap now and expensive during an incident.

---

#### O2 — Fork and untrusted-input paths: checked, and genuinely narrow

Reported as a positive because the task asked for the check, and because it is the strongest part
of the design.

- **No dangerous triggers.** No `pull_request_target`, `workflow_run`, `issue_comment`, `schedule`,
  or `repository_dispatch` in any workflow (verified mechanically across all five files).
  `ci.yaml` is `pull_request` only, `permissions: contents: read`, and passes no `secrets:` to the
  verifier — enforced from the *caller* side by `test_no_caller_hands_the_verifier_any_secret`
  (`:321`), which is the right place for that guard.
- **No script injection anywhere.** I parsed all five workflows and all three composite actions and
  searched every `run:` block for `${{ … }}`: **zero matches**. Every value reaches a shell through
  `env:`, and every one I traced is quoted at use. The class named in the task — tag names, branch
  names, `github.actor`, commit messages reaching a shell — does not exist in our own steps.
  `BL-E008-005`'s upstream defect has no local analogue.
- **No `$GITHUB_OUTPUT` injection.** Every value written to `$GITHUB_OUTPUT` is either a shell
  literal, a git object id, a regex-validated tag name, or output from
  `scripts/committed_versions.py`, which validates `package-version` against
  `\A[0-9]+(?:\.[0-9]+)*\Z` (`:42`, `:54`) and the Poetry pin against an exact caret form (`:38`,
  `:70`). A newline cannot reach an output.
- **Artifacts are same-run only.** `actions/download-artifact@v4` is called without `run-id` or
  `github-token` (`verified-bundle/action.yml:63-67`), so it can only see artifacts from the run
  that produced them. A fork PR's `verified-dist-v1` cannot be consumed by `release.yaml`.
- **The enabled-destination set cannot be forged.** Its three variable values
  (`release.yaml:262-266`) are shell literals assigned on branches within one step; the fourth
  (`dockerhub-repository`) is regex-validated at `:247`. The single-producer rule is enforced by
  `test_the_enabled_destination_set_has_one_producer` (`:618`), and a publisher acting on a
  destination the plan did not enable is blocked twice — no credentials (`release.yaml:561-562`)
  and no requests (`publish-image.yaml:182-208`).

The one qualification: on a Gitea `act_runner` every job is by definition self-hosted, so the
runner-isolation assumption that makes fork code execution safe on `ubuntu-24.04` is a GitHub
property. That is the same platform-conditionality as H3 and belongs with it.

---

#### O3 — The `GIT_CONFIG_COUNT` credential injection: examined closely, and the mechanism itself is right

Reported because the task asked specifically and because the answer is "no leak from the mechanism,
two leaks from its surroundings" — which is worth stating precisely.

`release.yaml:811-822` sets `GIT_CONFIG_COUNT=1`, `GIT_CONFIG_KEY_0=remote.origin.pushurl`,
`GIT_CONFIG_VALUE_0=<scheme>://x-access-token:<token>@<authority>/<repo>.git` on one step's `env:`.

- **`.git/config`:** not written. git's `GIT_CONFIG_*` protocol is process-environment only.
  `test_a_finalizer_never_leaves_a_credential_in_the_workspace` (`:3828`) forbids the alternatives
  (`git remote set-url` with a token, `http.*.extraheader`, `credential.helper store`).
- **Reused `act_runner` workspace:** nothing persists, for the same reason. This was designed for,
  not stumbled into — the comment at `:812-817` says so, and the guard backs it.
- **Logs:** `secrets.GITHUB_TOKEN` is a registered mask, and masking is substring-based, so the
  token is redacted even inside the composed URL.
- **`x-access-token` as userinfo:** correct — both forges authenticate on the token, and
  `github.actor` would be an illegal URI userinfo for `github-actions[bot]`.

What remains is **not** the mechanism: it is that the credential sits in the process environment of
a *moving-ref third-party action* (H1), and that the scheme is unvalidated (M2). Fix those two and
this construction is sound as written.

---

#### O4 — What the guard suite gets right, said explicitly

A red team report that lists only holes misrepresents this surface. The following were probed and
held:

- **Refusals precede writes.** `test_every_refusal_a_finalizer_makes_precedes_everything_it_writes`
  (`:3790`) derives both sets and asserts `max(refusals) < min(writes)`. This is the guard most
  repositories do not have, and it is the one that makes the others meaningful.
- **The finalizer gate is a `jq` program executed by the suite** with real `needs.*.result` values
  substituted (`:3177-4340`), not an `if:` expression readable only by eye — including malformed
  input, unknown states, unknown results, empty sets, and every blocking destination reported rather
  than only the first.
- **Alias ordering is decided from git, never from a registry** (`:657`), and the alias action is
  gated on that decision (`:3591`) including its `@v2` input *and output* spellings — a class of
  silent failure most projects discover in production.
- **Vacuity assertions throughout** (`assert examined`, `assert used`, "this guard examined
  nothing"). The suite consistently checks its own reach. H1 and H2 are both failures of *how* a
  scope was derived, not of whether anyone thought about scope.

---

## EXECUTIVE SUMMARY

**What was reviewed.** The complete publication surface introduced by Epic 8 Sprint 01: five GitHub
Actions workflows (~2,900 lines), three composite actions, `docker-bake.hcl`, the pre-commit gate
configuration those workflows execute, `scripts/committed_versions.py`, and the 124-guard contract
suite that encodes the intended invariants. Stack: GitHub Actions and Gitea `act_runner`, Poetry,
Buildx/BuildKit, PyPI trusted publishing (OIDC), Docker Hub, a forge container registry and a Gitea
package index. Five credentials and one OIDC identity are introduced here and exist nowhere else in
the repository.

**Overall risk posture: MEDIUM–HIGH, and the design is better than the score suggests.** The
identity chain is the best-engineered part of this repository — one version authority, four
independent re-proofs of the tag/commit binding before any credentialed step, three hashes of the
wheel before any login, refusals ordered before writes and *mechanically proven* to be so, and a
guard suite that repeatedly checks its own reach. Zero shell-injection sites exist across ~2,900
lines of workflow, which is genuinely unusual. The risk is concentrated at the two edges the design
does not own: **third-party action code**, and **the platform semantics the `permissions:` split
depends on**.

**Single most dangerous finding: H1.** Four actions that receive a publication credential — one of
them the repository's only `contents: write` token, one of them the Docker Hub token, one of them
simply running after `docker/login-action` with the credential store populated — ride floating major
tags. ADR-0009 states exactly why that is wrong and commissioned a guard to supply "reach"; that
guard derives its candidate set from whether the words `pypi` or `publish` appear in an action's
name, so it examines one action and misses four. The result is that the ADR's rule is documented,
believed, tested, green, and false. An adversary who moves a tag in the `LiquidLogicLabs` or
`docker` namespace — with no diff in this repository for anyone to review — reaches every credential
this epic introduces.

**Single most important recommendation.** Replace both of the name-derived scopes with derivations
over the source of truth, and prove each by planting a violation that attacks the *scope* rather
than the rule:

- **H1** — derive "credential-handling" from the parsed step (`secrets.` in `with:`/`env:`, or
  ordered after a `docker/login-action` in the same job), not from the action's name; SHA-pin the
  five references that derivation returns.
- **H2** — make the `gitleaks` gate scan content instead of an empty index, and add a guard that
  runs the configured invocation against a fixture holding a real secret and asserts it fails.

Both defects are the same mistake in two places: a control whose rule is correct and whose reach was
enumerated by hand. This repository already knows that lesson — `CLAUDE.md` §4 states it, and the
contract suite applies it more rigorously than most codebases ever do. These two are where it was
not applied, and they are the two that guard everything else.

---

## Notes on this run

- **Sanctum.** `_bmad/memory/l3io-sec-redteam/` did not exist and was created by the skill's
  activation path (`scripts/init-sanctum.py`), as case 1 of the skill contract requires.
- **Research cache not written back.** `references/platform-research.md` instructs writing
  `research-cache/{topic}.md` and updating `INDEX.md`. The dispatch instruction — *"Do not modify
  any file other than your report"* — is binding and takes precedence, so the two topics researched
  live (`identity` — Gitea/GitHub Actions token permissions; `secrets` — PyPI trusted publishing and
  action pinning) are cited inline above rather than cached. A future run will re-fetch them.
- **Nothing under `_bmad-output/implementation-artifacts/state/` was read or written.** No `git
  commit` was run. No project file was modified. The only commands executed against a repository
  were read-only, plus one `gitleaks` reproduction inside the session scratchpad
  (`.../scratchpad/glproof2`), on a throwaway git repository created for that purpose.
