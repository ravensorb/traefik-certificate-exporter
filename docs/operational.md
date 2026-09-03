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

None today — no metrics endpoint, no health check (PRD backlog item #15). The only signal
is the process's stdout/log-file output; monitor container/process liveness externally
(e.g. `docker inspect` health status is not configured either).

## Recover a failed release push

An atomic-push failure leaves the prepared local version commit and annotated exact tag intact for
inspection. It does not confirm that either remote ref changed, and the helper never retries with a
broad, forced, separate, or non-atomic push.

First inspect the local and remote identities without changing them (replace the example version
and branch with the values printed by the failed command):

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

Resume does not recalculate a version, create another commit, or replace the tag. It refetches,
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

Exactly one immutable tag per enabled destination is published, from one multi-platform Buildx
invocation shared with the development channel. Mutable aliases -- `latest`, `vX`, `vX.Y` -- and
the forge Release are not part of this workflow yet.

### The immutable identity is re-read before each upload

`vX.Y.Z` is immutable (ADR-0006), so both package publishers re-read the tag set immediately before
their credentialed step and refuse to upload if the tag no longer peels to the commit being
published. A moved release identity under a run about to publish it is the one case where refusing
is the only safe outcome -- a version accepted by PyPI can never be withdrawn.

## Rollback

Pin the previous image tag/PyPI version; there is no migration/state to roll back — the
tool is stateless aside from the files it writes to the output volume, which are safe to
leave in place across versions.
