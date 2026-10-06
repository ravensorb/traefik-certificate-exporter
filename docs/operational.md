# Operations Guide — traefik-certificate-exporter

## Deploy

**Docker (recommended):**

```bash
docker pull ravensorb/traefik-certificate-exporter:latest
```

See [docker/README.md](../docker/README.md) for `docker run` / `docker-compose` examples
(env-var-driven and config-file-driven variants).

**PyPI package:**

```bash
pip install traefik-certificate-exporter
```

`cryptography` is a declared dependency (PRD backlog item #3, fixed), so a bare `pip
install` pulls it in on any platform/resolver.

## Configuration

Three layers, in precedence order (highest wins): CLI flags > environment variables
(`TRAEFIK_CERTIFICATE_EXPORTER_*`) > `config.yaml` (via `-c`) > packaged
[config_default.yaml](../src/traefik_certificate_exporter/config_default.yaml). Env vars
deliberately outrank the config file — this is a Docker-first tool, and env vars are the
standard vehicle for per-deployment overrides of a static/mounted config file. See
[config.sample.yml](../config.sample.yml) for a starting file.

`..._DOMAINS_INCLUDE` and `..._DOMAINS_EXCLUDE` are mutually exclusive on every surface
(CLI, env var, config file) — setting both raises a clear error and exits (PRD backlog
item #6, fixed). You no longer need to set the other one to a dummy value to avoid a
crash.

## Runbook: certificate not exported

1. Check the container/process is actually seeing file events: run with `-ll DEBUG` and
   confirm `Watchdog received modified event` appears when Traefik renews.
2. Confirm `settings.dataPath` resolves to a real, mounted path — a misconfigured or
   unmounted data path now fails loudly with a non-zero exit (PRD backlog item #2 / review
   finding #2, fixed).
3. Confirm the domain isn't filtered out by an include/exclude list (`Skipping domain: ...`
   at INFO level).
4. Confirm the ACME JSON has a non-empty private key and cert for that domain (`Unable to
   find private key or full chain ...` at WARNING level is a Traefik-side/ACME-side symptom,
   not an exporter bug).
5. A domain whose name is not a plain DNS label is refused outright (`Refusing to export
   domain ...` at ERROR level). The name is joined into a filesystem path, so only
   `[A-Za-z0-9_-]` labels separated by dots are accepted.

### Exit code 2 at start-up

**Exit code 2 at start-up means an unrecognised flag; check your `command:`/`args:`
override.** Argument parsing is strict and happens *before* `setup_logging()`, so nothing
is written to the log file — under s6 the container simply crash-loops with no explanation
in `traefik-certificate-exporter.log`. Read the container's stderr (`docker logs`) for the
`unrecognized arguments:` line.

## Runbook: container not restarting after cert change

1. Confirm `restartContainers` / `--restart-container` is set.
2. Confirm the target container has label
   `com.github.ravensorb.traefik-certificate-exporter.domain-restart=<domain>` (comma-separated
   for multiple domains).
3. Confirm `/var/run/docker.sock` is mounted read-write into the exporter container (it is
   mounted read-only in the sample `docker-compose.yml` — read-only is sufficient for the
   `docker` SDK's list/restart calls over the socket, but verify against your Docker daemon's
   socket permission model if restarts silently fail).

## First-run config seeding (container)

**Known bug (PRD backlog item #6 / review finding #6):** the s6 init script that should seed
`/config/config.yaml` from `/defaults/config/config.yaml.sample` on first boot currently
writes to `/config/config.yaml.sample` instead — so no real config file is created
automatically. Until fixed, manually copy a config file into the mounted `/config` volume,
or rely entirely on environment variables.

## Monitoring / observability

No metrics endpoint and no health check (PRD backlog item #15). The only signal is the
process's stdout/log-file output; monitor container/process liveness externally (e.g.
`docker inspect` health status is not configured either).

### Tracing one export pass: `correlation_id`

Every export pass — the start-up sweep, and each debounced drain the file watcher runs —
mints a UUID4 and tags every log line it produces with it: the "certificates changed found
in file" event, the export itself, the post-export command, and the notification delivery.
One value joins all of them (ADR-0023).

- **Rotating log file** (`traefik-certificate-exporter.log`): already JSON, so
  `correlation_id` is a real field.
  ```bash
  jq -r 'select(.correlation_id == "<id>") | "\(.asctime) \(.levelname) \(.message)"' \
      traefik-certificate-exporter.log
  ```
- **Console** (what `docker logs` shows): human-readable and coloured by default, with the
  id in brackets after the level. Set
  `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CONSOLEJSON=true` to emit the console stream as
  JSON instead, so `correlation_id` is a parseable field there too. The default is
  unchanged colour output — this is opt-in, because an operator reading `docker logs` by
  eye usually wants the colour.
- `-` in place of an id means the line was emitted outside any export pass (start-up,
  configuration, shutdown before a pass ran).
- The post-export hook receives the same value as
  `TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID`, so a hook that logs elsewhere can be
  joined back. It is a UUID4 and carries nothing derived from a domain, path, or secret.

If a drain is interrupted part-way, the work left over is re-armed under a **new** id, and
an INFO line names both ("Re-arming export drain as X for work left by Y") so the two
halves can still be joined by hand.

### Shutdown

SIGTERM and SIGINT are both installed as explicit handlers at start-up. SIGTERM's default
disposition terminates the interpreter without running any Python, so `docker stop`,
`kubectl delete`, systemd and s6 would otherwise never reach the shutdown path at all —
only an interactive `Ctrl-C` did. Both signals now raise `KeyboardInterrupt` into the same
handler, so the behaviour described below is what you get from every one of them.

`Ctrl-C`/SIGTERM stops the watcher and cancels any armed-but-not-yet-fired debounce timer,
logging that cancellation at INFO — so a truncated run is distinguishable from a clean
exit ("no export drain was pending" is the clean case). Once shutdown has begun, a late
file-change event cannot start another pass.

If a drain is already *running*, shutdown waits a bounded 5s for it and then abandons it
and exits, rather than holding the process open past the container runtime's grace period
(`docker stop` allows 10s by default, while one drain can spend 30s in the post-export hook
alone). The drain threads are daemons, so the interpreter does not wait for them either;
abandoning one costs an export that did not happen — never a half-written file — and the
abandoned work is picked up the next time the acme file changes or the process restarts
with `runatstart`. The abandonment is logged at WARNING.

Certificate files (PEM and `.pfx` alike) are written to a temporary file in the target
directory and then `os.replace`d into place, so a process killed mid-pass leaves each file
either fully in its previous state or fully in its new state — never zero-length or
partial. Keep `outputpath` on a single filesystem (the normal bind-mount case): the rename
is only atomic within one.

### Trust boundary: `/config` and `settings.postexportcommand`

`/config` is a **trusted mount**. Treat it exactly as you would a binary on `PATH`: it must
be root-owned and must not be world-writable or group-writable by any account you would not
grant arbitrary code execution inside the container. Anyone who can write into `/config`
can set `settings.postexportcommand`, and that setting is executed by the exporter —
**`settings.postexportcommand` is remote-code-execution-equivalent configuration**, not a
convenience hook. The same applies to any file referenced from there.

The logging configuration is deliberately *not* auto-discovered from the working directory
for this reason: `logging.config.dictConfig` resolves and calls arbitrary dotted names for
its `class:`/`()` keys, so a planted `./logging.yaml` would have been code execution
regardless of `yaml.safe_load`. Only the packaged configuration, or one named explicitly
via `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE`, is ever loaded.

## Recover a failed release push

An atomic-push failure leaves the prepared local version commit and annotated exact tag intact for
inspection. It does not confirm that either remote ref changed, and the helper never retries with a
broad, forced, separate, or non-atomic push.

First inspect the local and remote identities without changing them (substitute the example
version and branch with the values printed by the failed command):

```bash
git status --short
git show --stat --decorate HEAD
git cat-file -t v1.2.4
git rev-parse HEAD 'HEAD^' 'v1.2.4^{}'
git ls-remote --symref origin HEAD
git ls-remote origin refs/heads/main refs/tags/v1.2.4 'refs/tags/v1.2.4^{}'
poetry version --short
```

If the working tree is clean, `HEAD` is the sole unpushed release commit, the exact matching tag is
annotated, its version equals Poetry's committed version, the remote branch still equals the local
commit's parent, and the remote tag is absent, resume through the guard:

```bash
just release-resume
```

Resume never recalculates a version, never creates another commit, and never replaces the tag. It refetches,
revalidates the recovery state, and repeats the same atomic two-ref push. Changed or ambiguous
state, multiple tags, a lightweight tag, or an already-present remote tag is refused without a
push.

Manual abandon is deliberately non-destructive. Valid choices include leaving the local commit and
tag in place while the incident is investigated, recording their object IDs in the incident notes,
or adding an archival branch such as `git branch archive/release-v1.2.4 HEAD`. This runbook does not
prescribe deleting tags, resetting a branch, or rewriting history; any later cleanup should be a
separate maintainer decision made after the refs are understood and preserved.

## Development publication (`dev.yaml`)

Every push to the protected default branch runs `.github/workflows/dev.yaml`. It resolves the
development identity, calls the governed verifier exactly once for the pushed SHA, and then
publishes an immutable `X.Y.(Z+1).devN` package and a `dev-<12sha>` image. Concurrency supersedes a
stale candidate: a newer push cancels an in-flight one.

### Destinations, and the two reasons one can be missing

| Destination | Development | Controlled by |
|---|---|---|
| image -> active forge registry | always | nothing; it is the channel |
| image -> Docker Hub | never | nothing. `PUBLISH_IMAGE_DOCKERHUB` is **inert** here |
| package -> forge Python index | when the host has one | host capability, not a toggle |
| package -> TestPyPI | when enabled | `PUBLISH_PACKAGE_TESTPYPI` |
| package -> PyPI | never | nothing; that is the stable channel |

"Disabled by toggle" and "absent by host capability" are reported as different words in the run
summary on purpose. GitHub has no forge Python index, and no toggle can create one; a destination
reported `unsupported` is not one somebody switched off.

`PUBLISH_PACKAGE_TESTPYPI` accepts only `true`, `false`, or absence. Any other value fails the plan
job rather than being coerced.

### Forge coordinates

There is no registry variable. Every coordinate -- the forge kind, the container registry, the
image repository, and whether the host offers a Python package index -- is a projection of
`github.server_url` and `github.repository`, derived in the plan job of each channel workflow. On
GitHub the registry is `ghcr.io`; on Gitea it is the forge's own host and port. `FORGE_REGISTRY`
was specified as an override for a Gitea deployment whose registry answers on a different port
from its web UI; no such deployment exists here, so the variable is retired and setting it does
nothing.

An unrecognised forge -- neither `github.com` nor a runner setting `GITEA_ACTIONS=true` -- fails
the plan job. No registry is guessed, because a guess publishes an immutable artifact somewhere
nobody chose.

### The accepted tag race

`just release` pushes the branch and the annotated tag atomically, so one operation fires a `push`
event on the default branch *and* a tag event, and the forge guarantees no ordering between them.
`dev.yaml` suppresses development publication when the pushed commit carries an exact annotated
`vX.Y.Z` tag, and **the two package publishers** re-read the tag set immediately before their
upload. The image publisher is reached through `uses:` and a called workflow takes no caller steps,
so it cannot re-read inline; it is protected at job granularity by the guard job's conclusion, and
its window remains "guard job start -> push". Either way the race is narrowed, not closed. **This
is a recorded decision, not a defect:** serialising the two events would mean giving up the atomic
two-ref push ADR-0006 exists to provide.

If the tag is still invisible when the checks run, an immutable, unretractable `X.Y.(Z+1).devN` is
published for the release commit. It cannot be withdrawn. The recovery is to publish a new
development version; the stable release itself is unaffected.

### What the published-image smoke test does and does not cover

After the push, `publish-image.yaml` pulls the published index **by digest**, resolves the
descriptor matching the runner's own architecture, and starts that container. Only the native
descriptor is executed. The other platform is covered by provenance rather than execution: the
wheel is `py3-none-any`, so the same file with the same SHA-256 is installed into both images, and
the base image is digest-pinned (ADR-0008). Platform coverage of the index itself is asserted from
the published manifest list, filtered on `vnd.docker.reference.type` -- never by counting
descriptors, since BuildKit emits SLSA provenance whether or not attestations were requested.

## Stable publication (`release.yaml`)

Pushing an annotated `vX.Y.Z` tag runs `.github/workflows/release.yaml`. It accepts the tag,
resolves the stable identity, calls the governed verifier exactly once for the tagged SHA, and
publishes the immutable `X.Y.Z` package and image. Unlike the development channel, a stable run is
never cancelled by a later one: two tag pushes are two distinct immutable identities and run
independently, and a re-push of the same ref queues rather than superseding. Cancelling a fan-out
half-way is the state the finalizer must never act on.

### What the tag guard accepts

Only an annotated tag spelled exactly `vX.Y.Z`, whose peeled commit is the event SHA, and whose
commit is reachable from the protected default branch. A lightweight tag, a floating alias (`v1`,
`v1.2`), a prerelease (`v1.2.3-rc1`), a malformed version (`1.2.3`, `v01.2.3`), a branch ref, a tag
pointing at some other commit, and a tag on history the default branch never took are each refused
**before any credential is used**. The decisions are git's -- `%(objecttype)` for the
annotated-object filter, `^{commit}` for the peel, `merge-base --is-ancestor` for reachability
and `--sort=v:refname` for version ordering -- composed in the workflow step itself. The one
thing git cannot answer is the *spelling*, which is a naming convention rather than a git fact,
and it is the only pattern anywhere in the relation.

The accepted tag then has to agree with the repository: the version the tag spells, the committed
Poetry version, and the checked-out commit are compared as a relation before any publisher starts,
and the verifier proves the lock, the built distribution metadata and the application version
against that same single value (CI-AR11). The workflow names no version anywhere.

### Destinations, and the two reasons one can be missing

| Destination | Stable | Controlled by |
|---|---|---|
| image -> active forge registry | always | nothing; it is the channel |
| image -> Docker Hub | when enabled | `PUBLISH_IMAGE_DOCKERHUB` (namespace via `DOCKERHUB_ORG`, derived by default) |
| package -> forge Python index | when the host has one | host capability, not a toggle |
| package -> TestPyPI | never | nothing; that is the development channel |
| package -> PyPI | when enabled, on GitHub | `PUBLISH_PACKAGE_PYPI`, plus host capability |

`PUBLISH_IMAGE_DOCKERHUB` and `PUBLISH_PACKAGE_PYPI` accept only `true`, `false`, or absence; any
other value fails the plan job rather than being coerced. Both are read exactly once, by the plan
job, which emits the enabled set as a job output -- no publisher re-reads a toggle (ADR-0011).

PyPI is reached by trusted publishing, which needs a GitHub OIDC identity. On a Gitea runner there
is none, so the destination is reported `unsupported` rather than failing a job nobody expected --
the same situation TestPyPI has in the development channel, for the same reason.

### The `pypi` environment — two settings this repository cannot make for you

`release.yaml`'s PyPI job declares `environment: pypi`. That declaration on its own changes
nothing: an environment with no protection rules runs exactly as it did before. It exists so the
two settings below have somewhere to attach, and **until both are made, neither protection is in
effect** — the contract suite can see the declaration and cannot see either setting.

1. **Required reviewers on the `pypi` environment** (repository → Settings → Environments → `pypi`).
   PyPI never lets a version be withdrawn or replaced, so without this a single tag push carries
   straight through to an irrevocable upload. Everything between is an identity re-check, and an
   identity re-check proves the tag still names the commit — never that anyone meant to release it.
2. **The PyPI trusted publisher constrained to that environment** (PyPI → the project → Publishing).
   Without an environment claim to match on, *any* workflow in this repository that can obtain
   `id-token: write` can mint a PyPI-scoped token, not only the reviewed one.

**Decided for this repository: (1) is declined, (2) is not.** This is a sole-developer project, so
required reviewers is a gate on yourself — it would either block every release or be self-approved,
and neither is worth the setting. That is recorded in `BL-E008-007`/`BL-E008-008` rather than left
looking like pending work.

(2) is a different thing wearing the same heading. It is not an approval gate, costs nothing
operationally, and adds no waiting: it narrows *which* workflow can mint a PyPI-scoped token from
"any workflow in this repository that can obtain `id-token: write`" to one. It is latent right now
because `PUBLISH_PACKAGE_PYPI` is unset and PyPI publication is off — **so the trigger is the first
time you enable PyPI, and it belongs in that same sitting.** The `environment: pypi` declaration is
already in `release.yaml` and is inert until the PyPI side is configured.

### `DOCKERHUB_ORG`

Two independent things, and only one of them needs you.

The image **name** is not configurable: it is whatever this repository builds, taken from the same
coordinate that composes the forge image repository. Docker Hub and the forge registry therefore
ship the same image name by construction, rather than by two settings that agree until one is
edited.

The **namespace** cannot be derived -- a Docker Hub org is unrelated to the forge owner -- so
`DOCKERHUB_ORG` is the one knob. It defaults to the lowercased forge owner, which is correct for
this project and fork-correct besides: a fork resolves its own namespace rather than pushing at
this one. Set it only if your Docker Hub org differs from the forge owner.

The default is not a fail-open. The composed `<namespace>/<name>` is still validated, so a
namespace that is not a legal Docker Hub reference **fails the plan job** rather than publishing an
immutable tag to a mangled guess -- the same posture an unrecognised forge takes. Credentials come
from the `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN` secrets, and reach only the image job.

**Changing this variable is a publication-authority change, and it is not a code review.**
`DOCKERHUB_ORG` is validated for *shape*, never against an expectation, because there is no
expectation to hold it to -- a fork must resolve its own namespace. It is also a repository
variable rather than a secret, so anyone who can set repository variables redirects every stable
image push to a different Docker Hub namespace, using this project's real (account-scoped)
`DOCKERHUB_TOKEN`, with no diff to review and no ADR. It is the one operator-supplied value in the
whole publication path.

Two things narrow it and neither closes it: the publisher refuses any tag whose repository the plan
job did not prove, so the redirect has to go through this variable rather than around it; and the
run summary records the repository every tag addressed, so a redirect is visible after the fact.
Treat a change here with the same review as a workflow edit, and check the run summary of the first
release that follows one.

Exactly one immutable tag per enabled destination is published, from one multi-platform Buildx
invocation shared with the development channel. The mutable aliases -- `latest`, `vX`, `vX.Y` --
and the forge Release are attached afterwards, by the two registered finalizers (`finalize` and
`finalize-image-aliases`), and only once every required job has succeeded.

### The immutable identity is re-read before each upload

`vX.Y.Z` is immutable (ADR-0006), so both package publishers re-read the tag set immediately before
their credentialed step and refuse to upload if the tag no longer peels to the commit being
published. A moved release identity under a run about to publish it is the one case where refusing
is the only safe outcome -- a version accepted by PyPI can never be withdrawn.

## Publication recovery

A channel run fans out to several destinations, and each one is immutable: an accepted PyPI
version, an accepted forge package version, and a pushed image tag can never be withdrawn or
replaced. So a run in which one destination failed after another succeeded is the normal case this
section exists for, and the recovery is always the same shape -- **rerun only the jobs that
failed**, against the verifier evidence the original run already produced.

The recovery is never a whole-workflow rerun, and it is never a force, a delete or an overwrite.
Those four are listed as prohibited below, with what to do instead.

### How a conflict is detected

The detector is **the destination's own rejection**. `pypa/gh-action-pypi-publish` fails when the
version already exists; a registry fails an immutable tag push; the forge index fails a duplicate
upload. Nothing in this repository asks a destination whether a version exists before uploading to
it, and nothing may: a pre-upload existence query is a decision taken from a remote read that can
be stale by the time the upload runs, and it is refused by
`test_no_publisher_queries_a_destination_before_uploading`.

Inspecting what a run has **just published** is a different thing and is required -- the image
publisher pulls the index by digest, resolves the native descriptor, runs it, and asserts the
index's platforms from its annotations. That read happens after the push and describes this run's
own output, so it cannot be stale in the way a pre-upload probe is.

### Rerun the failed jobs

Start from the run summary, whose `Run` row links the run that published (see the evidence table
below). Then:

**GitHub.** Open the run and use **Re-run failed jobs**. The rerun keeps the same run, reuses the
outputs of the jobs that already succeeded -- including the plan job's identity and the verifier's
`build-manifest-sha256` -- and re-executes only the failed jobs and the jobs that depend on them.
The verified distribution artifact uploaded by the original attempt is still the artifact the
rerun downloads, so nothing is rebuilt and no second identity is created.

**Gitea.** Open the run and use the per-job rerun control on each failed job in the run's job
list; Gitea reruns that job and the jobs blocked behind it, and leaves the successful ones with
their original conclusions and outputs. If the deployed Gitea version offers no per-job rerun --
only a rerun of the whole run -- then failed-jobs-only recovery is unsupported on that host, and
the run halts and escalates rather than being rerun whole. Certifying this procedure against the
target Gitea deployment is Epic 9's work; until then, treat a Gitea publication failure as an
escalation. The certification contract this recovery must satisfy before production ownership
migrates to Gitea -- the staging-only fault-injection mechanism, the pre/expected-partial-state
record, and the preservation/cleanup postconditions -- is documented in
`docs/ci/gitea-certification.md` and mechanically gated by
`assert_recovery_contract` (ADR-0020).

### When recovery halts and escalates

Recovery is abandoned, and the incident escalated to a maintainer, in each of these cases. None of
them has a retry that is safe to take unattended.

| Condition | How you see it | What happens |
|---|---|---|
| Failed-jobs-only rerun unsupported | the forge offers no per-job rerun | halt; escalate. A whole-workflow rerun is prohibited, so there is no rerun to take |
| Verifier evidence expired | the rerun job cannot download `verified-dist-v1` (30-day retention, `verify-build.yaml`) | halt; escalate. Rebuilding produces a new artifact, which is a new identity and not a rerun |
| Remote immutable identity conflicts | the destination rejects the upload because that version or tag already exists | halt; escalate. Never force, delete or overwrite the published one |
| Partially aliased registry | `finalize-image-aliases` failed and its run summary lists one or more **Unconfirmed** references beside the ones it Moved | re-run **that job only**. `docker buildx imagetools create` writes each `--tag` in turn rather than atomically, so a rate limit, a token expiry or a registry error part way leaves some aliases moved and the rest not. Pointing the same alias at the same digest again is idempotent, which is why this one is recoverable where the rows above are not. If the re-run also fails, escalate: do not move the names by hand |

In the **development** channel the escalation resolves by publishing a new version: push again and
a new `X.Y.(Z+1).devN` is built and published. The already-published development version is left
exactly where it is. In the **stable** channel the escalation resolves by deciding, with a
maintainer, whether a new `vX.Y.Z` is warranted through `just release`; the conflicting tag,
release and package are never moved, deleted or republished.

### Prohibited recovery actions

**These four are procedural, and three of them are unenforced.** Nothing in the pipeline can stop
an operator pressing "Re-run all jobs": `github.run_attempt` distinguishes a re-run from a first
attempt, not a *whole* re-run from the *failed-jobs* re-run this runbook prescribes, so a guard
built on it would refuse the legitimate recovery. Stating that here is the point -- a prohibition
that reads as enforced stops the next person checking.

What **is** enforced, and what you are actually relying on:

- the destination's own rejection. Neither PyPI upload sets `skip-existing`, deliberately, so a
  second attempt at a spent version fails loudly instead of passing silently;
- `test_no_publisher_queries_a_destination_before_uploading`, which forbids asking a registry
  whether something is already there -- the rejection is the detector;
- the finalizer gate, which refuses to create the Release or move any alias unless every enabled
  destination delivered, so a half-published re-run does not advance a mutable name;
- `test_no_workflow_writes_refs_or_releases_outside_a_finalizer` and its siblings, which make the
  last two rows below unexpressible in a workflow at all -- though a human holding the same
  authority can still perform them by hand, which is why they remain listed here.


| Action | Status | Why, and what to do instead |
|---|---|---|
| Re-run all jobs / whole-workflow rerun | prohibited | it re-executes destinations that already succeeded, so every immutable upload is attempted a second time. Re-run the failed jobs only |
| Force update of a tag, alias or release (`--force`, force-push, force-overwrite) | prohibited | it moves an identity that consumers have already resolved. Publish a new version instead |
| Delete a published tag, release, package version or image tag | prohibited | deletion is not a recovery: PyPI never re-accepts a deleted version, and a deleted image digest breaks whoever pinned it. Escalate instead |
| Overwrite a published artifact at the same identity | prohibited | the destination rejects it, and where it does not, two different artifacts have shared one name. Publish a new version instead |

### Aliases stay blocked until every required job succeeds

The finalizers -- `release.yaml`'s `finalize` and `finalize-image-aliases`, and `dev.yaml`'s
`finalize-dev-alias` -- run behind a gate that reads every required job's result and every enabled
destination's conclusion. A destination that failed, was cancelled, or was skipped while enabled
blocks finalization, so `latest`, `vX`, `vX.Y` and `dev` never advance to a half-published run.
Rerunning the failed publisher is what unblocks them: once its conclusion is `success`, the
finalizers run in the same rerun and the aliases advance to the digest that was published.

### From an image digest to the run that published it

A published index carries no run identity on purpose -- a run number is not a property of the
artifact. The join key is the source commit, recorded as an OCI label:

```bash
docker buildx imagetools inspect --format '{{json .Image}}' <registry>/<owner>/<name>@sha256:... \
  | jq -r 'to_entries[0].value.config.Labels."org.opencontainers.image.revision"'
```

The published artifact is a multi-platform index (CI-AR39), so that output is keyed by platform
and the `jq` step reads the labels of the first entry; every platform carries the same revision.
`org.opencontainers.image.revision` is the full source SHA the image was built from
(`docker-bake.hcl` sets it from the build manifest's `source_sha`). The run that
published that digest is the channel run whose summary `Source` row holds the same SHA -- one run
per source SHA per channel, so the lookup is exact. `org.opencontainers.image.version` gives the
package version for the same purpose when the digest is not to hand.

### What the run summary reports (CI-AR41)

Both channel workflows end in an evidence job that depends on every publisher and every finalizer,
and runs on `!cancelled()` so a failed destination is still reported. The table it writes carries
the run link, the forge, the source SHA, the release tag (stable), the package version, the
verifier's build manifest SHA-256, the enabled destination set, one conclusion row per
destination, the published image digest, its immutable reference and its platforms, the Release
URL (stable), and the alias outcomes. The development table adds the `Suppressed by stable tag`
row, which is how a run that deliberately published nothing is told apart from one that failed. That table is the input to every decision above -- read it before
rerunning anything.

### What a local `docker/act-build.sh` run reports (BL-E007-002)

The run summary above is the GitHub-side evidence. The local verifier is the other half, and its
status should be read as **safe, executes, not yet green end to end** rather than as a working
rehearsal of CI.

Attempted 2026-10-06 against source SHA `2213e429ed3eb83733b89744db835f267124f9c4`, package version
`0.2.0`, with `act` and a reachable Docker daemon (Engine 29.8.2, Buildx v0.37.1). The wrapper's
disposable-clone guard behaved as designed — the clone resolved elsewhere, the real tree was never
mounted — and `act` got as far as starting the `ubuntu-24.04` runner and executing
`actions/checkout@v7`. It then failed, definitively and reproducibly, at the first step of the first
job:

```
::error::Invalid repository '/home/.../traefik-certificate-exporter'. Expected format {owner}/{repo}.
```

`act` derives `github.repository` from the clone's `origin` remote, which `git clone --local` points
at a filesystem path — the very property that lets a local-only commit be fetched is the one
`actions/checkout` rejects. Pointing `origin` at the GitHub URL instead trades this failure for the
original one: the SHA is not on any remote, so the ref cannot be fetched. Closing that needs a
change to the wrapper's clone/mount strategy, not a rerun.

That wrapper change is tracked as backlog item **BL-E011-011**. Until it lands, BL-E007-002 is
closed only for its evidence-capture half: the local verifier is safe to run and its transcript is
retained, but it has never completed a green end-to-end run.

Two things follow for anyone running it. First, a failed local run is still useful output — read the
transcript rather than assuming the environment is broken. Second, if `act` stops on
`Provide value for '<SECRET>'` before any job starts, that is `~/.actrc` declaring `-s NAME` with no
value; `verify-build.yaml` is the secret-free verifier (ADR-0007) and needs none of them, so supply
placeholders in the invoking environment rather than real credentials.

The transcript is retained at
`_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/E011-S01-001-act-run-evidence.md`.
The wrapper `tee`s to `act-build-traefik-certificate-exporter.log` in the repository root, which
`.gitignore`'s `**/*.log` excludes — so archive the transcript deliberately; it is not kept for you.

## If a publication credential is compromised

The publication-recovery procedure above answers "a run failed part way". This one answers "someone
else may have used our credentials", which is a different question with a different first move: the
recovery runbook's instinct is to finish the release, and this one's is to stop being able to.

There are four long-lived-ish credentials, and they are not equally bad.

| Credential | Blast radius | Where it is used |
|---|---|---|
| `DOCKERHUB_TOKEN` (+ `DOCKERHUB_USERNAME`) | **account-scoped**: every repository that Docker Hub account can write, not only this one | the image publisher, and the stable alias job |
| `FORGE_PACKAGE_TOKEN` | the forge Python index for this owner | the forge package publisher |
| `GITHUB_TOKEN` | per-run, expires with the run, scoped by each job's `permissions:` | everywhere; never stored |
| PyPI | **no stored credential** — trusted publishing mints a short-lived OIDC token per run | the PyPI publisher |

PyPI being absent from the list of things that can leak is the point of CI-AR25, and it is the
posture the other two would ideally move to.

**First, in order.**

1. **Invalidate the credential at its source**, not here: Docker Hub → Account Settings → Personal
   access tokens; the forge → the owner's package-registry tokens. Clearing the repository secret
   only stops this pipeline from reaching for it, and has no effect on anyone else who holds a
   copy.
2. **Then** clear the repository secret, so a run cannot half-succeed with a credential that no
   longer works and leave a confusing state behind.
3. Turn the affected destination off — `PUBLISH_IMAGE_DOCKERHUB=false` — rather than letting runs
   fail against it. A disabled destination is a state the finalizer understands (ADR-0011); a
   failing one blocks the Release and the aliases.

**Then work out what was published.** Everything this pipeline ships is recorded, and that is what
the evidence is for:

- each run's summary names every destination, the image digest, the platforms, and the exact
  repositories the tags addressed;
- the Release carries `SHA256SUMS` and `build-manifest.json` for its version, and on GitHub the
  distributions are attested (ADR-0008), so an artifact that this pipeline did **not** build has no
  attestation — that is the check to run, rather than comparing checksums against the same Release
  an attacker with `contents: write` could have replaced;
- the image index carries SLSA provenance naming the workflow and run that built it.

Anything on a destination that no run summary accounts for was not published from here.

**What not to expect.** Rotating a credential does not unpublish anything, and nothing in the
prohibited-actions table above becomes available because a credential leaked: a version PyPI has
accepted is still spent, and an image digest someone pinned is still pinned. The remedy for a bad
artifact is the same as it always is — publish a new version and communicate the bad one.

**Afterwards**, record it: which credential, when it was invalidated, what the run summaries showed,
and whether anything was published that should not have been. A rotation nobody writes down teaches
nobody anything.

## Rollback

Pin the previous image tag/PyPI version; there is no migration/state to roll back — the
tool is stateless aside from the files it writes to the output volume, which are safe to
leave in place across versions.

## Gitea staging certification and production-owner migration

Production ownership moves from GitHub to the pinned Gitea tuple only after staging
certification -- proving PR verification, protected delivery, artifact round-trip, private-CA
boundaries, the multi-arch image flow, the forge package/Release channel, both reusable
workflows, aliases-last behavior, and failed-jobs-only recovery, with no required negative case
unsupported (CI-AR35). The requirements registry, the evidence-export and report-projection gate
(ADR-0017), the action-closure drift check (ADR-0016), and the fault-injection/cleanup contract
(ADR-0020) live in `tests/ci/test_certification.py`; the narrative runbook, case-by-case status,
and the production-owner cutover's named approver, stop conditions, rollback commands, and
retained-evidence-link requirements are in `docs/ci/gitea-certification.md`. As of this writing no
live Gitea instance exists to certify against, so migration has not occurred and this repository's
publication credentials remain GitHub's.
