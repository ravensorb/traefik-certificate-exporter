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
3. Confirm `/var/run/docker.sock` is mounted (the sample `docker-compose.yml` mounts it
   `ro`). **The `ro` mount flag does not narrow what this container can do over the
   socket** — it only blocks replacing/unlinking the socket file itself. Any client
   connected to `docker.sock`, `ro` or `rw`, has the same full Docker Engine API available
   to it as the host's Docker daemon user, which is host-root-equivalent (CIS Docker
   Benchmark; Docker's own security docs). There is no code in this project that narrows
   this to "list/restart" — `restartLabeledContainers` uses the general `docker-py`
   client with no endpoint allowlist. If you need a narrower grant, put an
   endpoint-restricted proxy (e.g. Tecnativa/docker-socket-proxy, allowlisting only
   `GET /containers/json` and `POST /containers/{id}/restart`) between this container and
   the real socket rather than mounting the socket directly.
4. Confirm the restart is not being suppressed by the cooldown. A given labeled container is
   restarted **at most once per 5-minute window**; a pass that lands inside that window logs
   `Skipping restart of container <id>: restart cooldown active, Ns remaining` at INFO and
   moves on. The window is per container, not global.

   This floor exists because the domain strings come from Traefik's ACME store, and anyone
   who can get a certificate issued into that store can influence them — without it, a noisy
   or hostile store turns every drain pass into a restart of every labeled container over a
   host-root-equivalent socket.

   The cooldown is the *only* suppression. Restarts are deliberately **not** filtered on "the
   domain names did not change": a renewal keeps the domain name and replaces only the key
   material, so name-based filtering would restart each container once per exporter process
   lifetime and then never again — the opposite of the feature. A per-domain certificate
   fingerprint would allow precise filtering and is tracked as a follow-up.

   The state is in-process only: restarting the exporter clears it, so the first pass after a
   start is always eligible. A failed restart and a `dryrun` restart both leave the container
   eligible — neither starts a cooldown.

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

### A symlink at an export path is replaced, not followed

If an export target is a symlink, the exporter replaces **the link itself** with a regular
file and refuses to carry the linked-to file's owner and mode forward. It does not write
through the link, and this is deliberate — not a bug to be fixed (BL-E011-009).

Writing through the link would make anyone who can create a file in `outputpath` able to
aim a privileged write anywhere on the filesystem, and the obvious guard ("check whether
it is a symlink, then open it") cannot close that: the link can be swapped in between the
check and the open. Replacing the link is the control, because `os.replace` acts on the
name rather than on whatever the name currently points at, so there is no window to win.
The first time a given path is seen to be a symlink the exporter logs a WARNING naming it.

If you were using symlinks in `outputpath` to publish certificates under a second name,
use a copy step in `settings.postexportcommand`, or point the consumer at the real path.

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

#### The hook inherits the exporter's entire environment

`settings.postexportcommand` is run with a **copy of the exporter process's full
environment**, plus `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS` and
`TRAEFIK_CERTIFICATE_EXPORTER_CORRELATION_ID`. Nothing is stripped or filtered
(BL-E011-019).

Everything you pass to the container is therefore readable by the hook and by every process
it starts: `TRAEFIK_CERTIFICATE_EXPORTER_NOTIFY_*` Apprise URLs (which commonly embed an
API token or a bot credential), registry or cloud credentials injected for unrelated
reasons, and anything else in the container's env. A hook that pipes output to a remote
endpoint, or that runs a third-party script, exports those values with it.

Two practical consequences:

- Keep secrets out of the environment where the configuration file will do. Credentials
  read from a mounted file are not handed to the hook by this mechanism.
- Treat the hook as having the same privilege as the exporter: it is not a sandbox, and it
  runs as whatever account the service runs as (see "Container privileges" below).

The argument vector is **not** run through a shell (`shlex.split` plus `shell=False`), so a
domain name cannot inject a second command into a hook that references it. That protects
the command line, not the environment.

### Container privileges: when the image keeps root, and when it drops

The container decides at start-up whether to keep root, and it decides from
`settings.restartcontainers` alone (ADR-0030):

| `settings.restartcontainers` | Service runs as | Why |
|---|---|---|
| `false` / unset (default) | `abc` (the `PUID`/`PGID` account) | Nothing in the export path needs root |
| `true` | `root` | `/var/run/docker.sock` access cannot be guaranteed for an unprivileged account |

There is no separate switch and nothing to opt into. When root is retained the service logs
a WARNING at start-up naming the condition and the remedy, so `docker logs` answers "why is
this running as root?" directly.

The fallback is one-directional: if `/config/config.yaml` is missing or malformed, or the
decision cannot be made for any other reason, the container **drops** privileges and logs a
WARNING. A failure never leaves it as root.

The decision is made by the **installed exporter**, not by a second parser in the init
script: the container asks `SettingsManager` for the resolved `settings.restartcontainers`,
so every source the application honours (packaged default, `.env` files, config file,
environment) and its exact truthiness apply. A container that dropped privileges while the
application believed the Docker-socket path was on would fail every restart with a bare
permission error, so the two must not be able to disagree.

**Upgrading into the dropped configuration.** Three things change on first boot without
`restartcontainers`, and all three are worth checking before you upgrade:

- **The output path is chowned to the `PUID`/`PGID` account.** The *resolved*
  `settings.outputpath` is used, not the `/certs` default, so a custom mount is covered too.
  Symlinks inside it are skipped and never followed, and the walk does not cross into a
  nested mount — a link planted in the output volume must not be able to redirect a
  root-owned `chown`. If your host tooling depends on a particular owner for that directory,
  set `PUID`/`PGID` to match it.
- **Traefik's ACME store must be readable by that account.** Traefik writes `acme.json` mode
  `0600` owned by the account Traefik runs as — commonly root — and refuses to start if it
  is more permissive, so the dropped account may simply not be able to read it. The exporter
  would otherwise report only a generic `Error processing file` per pass, so the init step
  probes every file matching `settings.filespec` under `settings.datapath` and logs a
  WARNING naming the unreadable files and the two remedies: set `PUID`/`PGID` to an account
  that can read them, or relax their group permissions. **Check your start-up log for this
  warning after upgrading** — it is the difference between "exporting nothing" and "working".
- **The service gets its own `HOME`** (`/run/traefik-certificate-exporter/home`, on tmpfs).
  `s6-setuidgid` changes the uid and nothing else, and the configuration library creates an
  application directory under `$HOME` on every start; the image's `HOME` is a root-owned
  `0700` `/root`, which the dropped account cannot write.

`/data` is not chowned — the exporter only reads it — and `/config` deliberately stays
root-owned, because `settings.postexportcommand` makes it execution-equivalent configuration
and the account that runs the hook must not be able to rewrite it.

**Known limitation:** file logging (`logging.consoleonly: false`) writes a relative path
resolved against the root-owned `/config`, so the dropped account cannot open it; the
exporter reports the failure and continues on console logging only. Use console logging and
your container runtime's log driver, or keep `restartcontainers` enabled, until a writable
log location is configured.

**If you need `restartcontainers` but not root:** put an endpoint-restricted proxy (e.g.
`Tecnativa/docker-socket-proxy`) between this container and the real socket, allowlisting
only `GET /containers/json` and `POST /containers/{id}/restart`, and point
`DOCKER_HOST` at the proxy instead of mounting `docker.sock`. The container still runs as
root in that configuration, but a compromise of it reaches two Docker endpoints rather than
the whole Engine API.

## Publishing

Packages and images are published by `dev.yaml` (every push to `main`) and `release.yaml`
(every `vX.Y.Z` tag); `ci.yaml` only builds and tests (ADR-0035). Each destination — the
Gitea package index, TestPyPI, PyPI, GHCR, the Gitea container registry, Docker Hub, and
the forge release — is enabled only by its own `PUBLISH_*_TOKEN` secret, set separately on
each forge (AD-9). With none set, a run succeeds and publishes nothing.

The destination table, the `PUBLISH_*` variables that go with each secret, and the image
tags each workflow writes are in
[ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md#where-things-are-published).

The Gitea package index and the Gitea container registry share one secret,
`PUBLISH_GITEA_TOKEN` (AD-9 table), so neither can be enabled without the other: setting
it turns on both, and the image side then also needs `PUBLISH_GITEA_IMAGE` and
`PUBLISH_GITEA_REGISTRY`. A registry whose token is set but whose image (or, for Gitea,
registry) variable is empty fails `publish-image` at its `Registry configuration guard`
step, before any login or push.

The `PUBLISH_*` **variables** are part of the publication authority, not just the
secrets. `PUBLISH_GITEA_PYPI_URL` is the upload URL that receives `PUBLISH_GITEA_TOKEN`,
`PUBLISH_GITEA_REGISTRY` is the registry that token logs in to, and the `PUBLISH_*_IMAGE`
variables set where images are pushed. Anyone who can edit repository or organisation
variables can redirect a live credential or a push to another host, with no diff and no
review: CODEOWNERS covers files only, so who may set these is a forge-permission decision
outside it. Treat a change to any of them like a workflow edit, and check the next run's
log for where it uploaded and pushed.

## CI recovery runbook

The jobs are `build` (all three workflows), `publish-package` and `publish-image`
(`dev.yaml`, `release.yaml`), and `validate-tag` and `release` (`release.yaml` only).

**A job failed part way (network, registry, runner).** Re-run the failed jobs — but only
on the **latest** run of that workflow. Package uploads skip files already published (`twine upload --skip-existing` for PyPI/TestPyPI; for Gitea, which twine refuses that flag for, the step uploads only the files Gitea does not already hold)
and the forge release is created with `allow-updates: true`, so those steps tolerate a
re-run. Image tags do not: a re-run re-points every tag that run writes (`dev` and `sha-*`
for `dev.yaml`; `latest`, `X` and `X.Y` for `release.yaml`) to the one digest it built. A
re-run does not reproduce an earlier digest, it replaces it. AD-14's `concurrency` only
cancels or queues runs still in progress; nothing stops a manual re-run of a finished,
superseded run. So if a newer `dev.yaml` run, or a newer release, has already completed,
do not re-run the older one — that would move `dev`, or `latest`/`X`/`X.Y`, back to the
older build. Push again, or cut a new release, instead.

**A `dev.yaml` re-run fails at `Version guard` after the commit was tagged.** That is by
design (AD-15): once `vX.Y.Z` points at the commit, the build's version is `X.Y.Z`, not a
`.dev` version, and dev refuses to publish it. Nothing needs recovering — `release.yaml`
owns that version.

**`release.yaml` fails at `validate-tag` (`Reject tag`).** The tag is not exactly
`vX.Y.Z` (AD-12), so nothing was built or published. Delete the tag on the remote and
locally, then tag the commit correctly — preferably with `just release`:

```bash
git push origin :refs/tags/<bad-tag>
git tag -d <bad-tag>
just release <major|minor|patch>
```

**`just release` failed to push the tag.** The local tag exists; nothing reached the
forge, so no workflow ran. Re-push it, or abandon it — the recipe prints both commands:

```bash
git push origin refs/tags/vX.Y.Z   # retry
git tag -d vX.Y.Z                  # abandon
```

**`publish-package`, `publish-image` or `release` fails at `download-artifact`.** First re-run the
failed jobs. If it fails again on the same runner, the forge's artifact server does not
accept the pinned artifact pair (upload-artifact v5.0.0 / download-artifact v6.0.0, the
newest pair that works under `act` 0.2.89). That is the open item recorded in the spine's
Deferred section ("Live certification on Gitea 1.27", "Artifact action majors" —
`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`).
Do not bump either action to a newer major to work around it; Dependabot ignores those
majors deliberately until `act` supports them.

**Bad release (a published `vX.Y.Z` is broken).** Published versions are not replaced.

1. Fix the defect on `main` and cut a patch release: `just release patch`.
2. Yank the broken version where the index supports it — PyPI and TestPyPI do (yanking
   hides it from resolvers without deleting it). Where an index offers no yank, leave
   the version in place or delete it deliberately, and say which in the fixed release's
   notes.
3. Never move `latest`, `X.Y`, `X` or any other tag by hand. Each tag has exactly one
   writing workflow (AD-8); the next `release.yaml` run moves them to the fixed version.

## If a publication credential is compromised

1. **Invalidate the credential at its source** — PyPI, TestPyPI, Docker Hub, GitHub or
   Gitea — not only in the repository. Clearing a repository secret stops this pipeline
   from using it and has no effect on anyone else holding a copy.
2. **Rotate the `PUBLISH_*` secret on each forge separately.** GitHub and Gitea hold their
   own secret stores (AD-9); a secret rotated on one forge is still the old value on the
   other. On GitHub the secret lives in an environment, not at repository level
   (ADR-0039): update it in every environment that holds it, which for a shared token
   (`PUBLISH_GITEA_TOKEN`, `PUBLISH_GHCR_TOKEN`, `PUBLISH_DOCKERHUB_TOKEN`,
   `PUBLISH_CA_CERTIFICATE`) is both `dev` and `release`
   (`gh secret set <NAME> --env dev`, then `--env release`). On Gitea update it in the
   repository (or organisation) secret store. To stop publishing to that destination
   instead, delete the secret: the destination switches off and runs keep succeeding.
3. **Scope the replacement as narrowly as the destination allows.** Create
   `PUBLISH_PYPI_TOKEN` and `PUBLISH_TESTPYPI_TOKEN` as project-scoped tokens for this
   project, never account-wide ones (an account-scoped token is only needed once, for the
   very first upload that creates the project). A Docker Hub personal access token cannot
   be limited to one repository: Docker documents that "a PAT uses one permission level
   for every repository the account can access", so `PUBLISH_DOCKERHUB_TOKEN` reaches
   every repository that account can push to. Use a dedicated account, or an organisation
   access token limited to this repository, to contain it.
4. **Check what was published** with the old credential: compare each destination's
   versions and image digests against the `dev.yaml` and `release.yaml` run logs. Anything
   no run accounts for was not published from here; yank or delete it, as for a bad release.

## Rollback

Pin the previous image tag/PyPI version; there is no migration/state to roll back — the
tool is stateless aside from the files it writes to the output volume, which are safe to
leave in place across versions.
