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

Four layers, in precedence order (highest wins), for every setting —
`CLI > env > config file > defaults`: CLI flags > environment variables
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

1. Check the container/process is actually seeing file events: raise the log level to DEBUG
   (`-e TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL=DEBUG` for the container, `-ll DEBUG` on
   the CLI) and confirm `Watchdog received modified event` appears when Traefik renews
   (`Watchdog received created event` or `Watchdog received moved event` when the store is
   replaced by a new file or a rename). A rename onto the store (a restore, or a tool that
   writes a temporary file and renames it) is detected and exported; a rename away from it
   is logged at INFO (`Store file ... was renamed to ...`) and exports nothing. inotify sees
   only local changes: a store on NFS/SMB that another host changes is not detected.
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

### Run-once container (`watchforchanges: false`)

**A run-once container exits after one pass, and its exit code reflects start-up failures
only: 0, or 1 when the data path is missing. Export failures are logged at ERROR and do not
change the exit code** — check `docker logs` for `ERROR` lines after each scheduled run
(ADR-0044). Run it with `restart: "no"` or from cron, a systemd timer or a Kubernetes Job;
`restart: always`/`unless-stopped` turns it into a container-level loop. A start that logs
`WARNING: run mode unresolved; defaulting to watch mode` means the start-up settings
resolution failed (usually a malformed `/config/config.yaml`): the service falls back to the
image's watch mode and the exporter's own error follows in the same log, once per restart
(s6 respawns the failing exporter until the config is fixed). In the image, select run-once
with `-e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false`: the image's environment
default for it outranks `watchforchanges` in `/config/config.yaml`. See
[docker/README.md](../docker/README.md#run-once).

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
   `GET /_ping`, `GET /version`, `GET /containers/json`, `GET /containers/{id}/json` and
   `POST /containers/{id}/restart`)
   between this container and the real socket rather than mounting the socket directly.
4. Check the start-up log. With restarts enabled the exporter checks the Docker Engine once
   at start-up: INFO `Docker Engine reachable (API <version>)` on success, or one ERROR
   naming the endpoint (`DOCKER_HOST`, else `unix:///var/run/docker.sock`) and the error on
   failure. Exporting continues either way; restarts do not happen until the Engine is
   reachable, and each pass that tries one logs the same single ERROR line, without a
   traceback.
   - The client targets `DOCKER_HOST` if it is set, otherwise the default socket. The
     Docker CLI context (`docker context use …`, `~/.docker/config.json`) is deliberately
     **ignored**, so a `~/.docker` in the service's `HOME` cannot redirect restarts to
     another daemon. On a workstation with a non-default context, set `DOCKER_HOST`.
   - Docker Engine API **1.24 or newer** is required (the docker-py 7.x floor). An older
     Engine shows up as the same start-up ERROR.
5. Check whether a restart was called for. Restarts happen **only on change**
   ([ADR-0045](adr/0045-restart-policy-only-on-change-defer-not-drop.md)):
   - **Trigger.** On every pass — the start-up pass and every drain, whether or not a
     domain changed — a running labeled container is restarted when the newest mtime among
     the exported files (PEMs and `.pfx`) of its labeled domains is more than **2 s** later
     than the container's own start (`State.StartedAt`, UTC). Change detection happens at
     export time: an unchanged certificate is not rewritten, so its files keep their mtime
     and restart nothing — restarting the exporter over an unchanged store restarts no
     container. A restart follows the first export into an empty output directory, a
     renewal or reissue, an output file deleted or edited by hand, and the first pass after
     upgrading from 0.2.x (every `.pfx` is rewritten with its intermediates).
   - The log line is INFO `Restarting container <id>: exported files for <domain> (<mtime>)
     are newer than its start (<StartedAt>)`. At DEBUG each evaluated container logs why it
     was not restarted; a container whose `StartedAt` is missing or the zero value is never
     restarted. A container none of whose labeled domains has an exported file is not
     considered at all. Stopped containers are not restarted; they load the current files
     when they next start.
   - **Clock slack.** The 2 s slack (`RESTART_MTIME_SLACK_SECONDS` in
     `src/traefik_certificate_exporter/libs/docker.py`, not configurable) absorbs small
     drift between the clock that stamps the output files and the Docker daemon's clock.
     Run the exporter against the local daemon with the output directory on a local
     filesystem: clock skew beyond 2 s (a remote daemon, a network filesystem whose server
     stamps mtimes) is unsupported, and a container that started less than 2 s before the
     write is not restarted. Containers on any daemon other than the one the exporter is
     connected to are never listed or restarted.
   - **Who can write the output directory.** The rule trusts the output files' mtimes. Keep
     the output directory writable by the exporter only — anyone who can write there can
     already replace the certificates the containers serve.

6. Check the cooldown. A given labeled container is restarted **at most once per 300 s
   (5-minute) window**: `RESTART_COOLDOWN_SECONDS = 300` in
   `src/traefik_certificate_exporter/libs/docker.py`, fixed and **not configurable**. The
   window is per container, not global. A restart that the rule calls for inside the window
   is **deferred, not dropped**: INFO `Deferring restart of container <id>: cooldown active,
   <n>s remaining; one restart scheduled`, and one trailing restart runs when the window
   ends (INFO `Restarting container: <id> (deferred)`). Further requests inside the window
   coalesce into that one. Before it restarts, the trailing restart re-checks that the
   container still exists and is still running, that its label still names a domain that asked for it, that its
   files are still newer than its start, and that no other restart has claimed the window
   since; otherwise it logs the reason at INFO and skips.

   This floor exists because the domain strings come from Traefik's ACME store, and anyone
   who can get a certificate issued into that store can influence them — without it, a noisy
   or hostile store could drive restarts of every labeled container over a
   host-root-equivalent socket. The trailing restart starts a new window, so the floor holds
   however noisy the store is.

7. A failed restart (logged at ERROR) is retried one 300 s window later through the
   trailing-restart path, with the same re-checks: INFO `Retrying restart of container <id>
   in <n>s (retry <k> of 3)`. After three failed retries it logs WARNING `Giving up
   retrying restart of container <id> ...` and waits for the next pass.

   A restart that did not happen is recovered on the **next pass**. Nothing is persisted:
   the exported files' mtimes and the container's `StartedAt` are the only restart state,
   and both survive a crash. So a restart lost to an exporter crash between writing and
   restarting, a failed restart whose retries are spent, or a deferred
   restart cancelled at shutdown (INFO `Cancelled <n> pending deferred restart(s); the next
   pass restarts them`) happens on the next pass, because the files are still newer than
   the container. The next pass is the next exporter start's start-up pass
   (`runatstart`, on in the image) or the next ACME write. With `runatstart: false`, a store
   file not written since the process started is not covered until its next write
   ([ADR-0040](adr/0040-exported-artifact-paths-from-one-shared-helper.md) §6). Until that
   next pass, the container keeps serving the previous certificate. In a dry run nothing is
   written, so mtimes do not move; containers that already satisfy the rule are logged as
   `[DRYRUN] would restart <id>` (or `would schedule deferred restart`) and nothing is
   restarted or scheduled.

8. To opt out of restarts: set `restartcontainers: false` (it is off unless enabled), or
   remove the `com.github.ravensorb.traefik-certificate-exporter.domain-restart` label from
   the container.

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

### When the post-export hook and notifications run: only on change

The post-export hook (`settings.postexportcommand`) and the Apprise notifications
(`settings.appriseurls`) run **only on change**: after a pass in which at least one domain's
exported files changed on disk, and only for those domains
([ADR-0045](adr/0045-restart-policy-only-on-change-defer-not-drop.md), amending ADR-0014 §7).
`TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS` and the notification body list only the
changed domains.

- A pass that changed nothing runs neither and logs one INFO line:
  `No certificate changed; no hook or notification`. That covers an exporter or container
  restart over an unchanged store (the start-up pass with `runatstart: true`), a run-once
  container over an unchanged store, and a pass that only recovers a lost container restart
  (see the restart runbook above): the container is restarted, but no hook runs and nothing
  is notified.
- A permission-only difference is not a change. An exported file whose mode is wider than
  its policy (`0600` for `privkey.pem` and the PKCS12 file) is tightened back in place
  (its mtime is kept) with a WARNING `Tightened mode of <path> from <old> to <new>`, and
  causes no rewrite, hook, notification or restart. A hook that loosens a key (for example
  `chmod 0640 privkey.pem`) is therefore reverted on every pass; have the hook give a
  non-root consumer its own copy instead.
- The start-up pass runs the hook and notifies once, for the union of every store file; the
  watcher runs them once per changed store file in a drain, so the quiet-pass line is also
  per store file there.
- Dry run: the domains that *would* change are reported, and the hook and notifications log
  their existing `Dry run: skipping …` lines for them and run nothing.
- In 0.2.x both ran after every pass, including every exporter start. If a notification
  channel was muted for that reason, it can be unmuted.

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

### The `.pfx` fingerprint file and `settings.validatekeys`

Beside every `.pfx` the exporter writes a small JSON file: `cert.pfx.fingerprint.json` in the
per-domain layout, `<name>.pfx.fingerprint.json` in the flat layout. It is written after the
`.pfx`, atomically, at mode `0600`
([ADR-0051](adr/0051-pfx-fingerprint-sidecar.md)).

- **What it holds:** the SHA-256 of the `.pfx` file, of the store's private-key PEM and of
  each certificate, and the passphrase only as a salted scrypt hash. No passphrase and no key
  bytes.
- **What it is for:** a `.pfx` cannot be compared byte for byte (each build draws a fresh
  salt), and opening it costs a private-key and a PKCS#12 load. With the fingerprint file the
  exporter tells that the `.pfx` is current without opening it, so a pass over unchanged
  certificates loads no key at all.
- **It is never trusted alone.** The `.pfx` counts as current only when the hash in the file
  equals the `.pfx` on disk. A missing, damaged or edited `.pfx` is rebuilt and its domain
  reported. A missing, unreadable or malformed fingerprint file, or one whose recorded `.pfx`
  hash no longer matches the `.pfx` on disk, makes the next pass verify the `.pfx` by content
  once and write a new fingerprint file; when the content is current that rewrites no
  certificate file and reports nothing. A well-formed fingerprint file whose `.pfx` hash still
  matches but which was edited to record different inputs (key hash, certificate hashes or
  passphrase hash) counts as an input change: the next pass rebuilds the `.pfx` and reports
  the domain, so the restart, hook and notification follow. Deleting the fingerprint files is
  therefore safe; editing them is not.
- **It is not an exported artifact.** Its modification time never triggers a container
  restart, the hook or a notification, and it is not removed when a domain leaves the store
  (nor is any other exported file).
- **Dry run:** a dry run writes no fingerprint file. Over output from 0.3.0 (no fingerprint
  files yet) every dry run therefore verifies every `.pfx` by content — slow on RSA-4096
  stores — until one real pass has written them.

`settings.validatekeys` (env `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_VALIDATEKEYS`, CLI
`--no-validate-keys`), default `true`, controls RSA private-key validation when the exporter
builds or verifies a `.pfx`. Validation costs ~0.5 s per RSA-4096 key (Traefik's default key
type). Set it to `false` **only when the ACME store is written by your own Traefik**: the keys
are then trusted, not checked, and cryptography warns that an invalid key loaded that way may
make OpenSSL misbehave. The check that a key matches its certificate always runs, in both
modes. The start-up line `RSA key validation: on` / `RSA key validation: off (…)` shows the
setting. It affects only passes that build a `.pfx`: an unchanged pass loads no key either
way.

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

`/config` is owned by `PUID`/`PGID`: LinuxServer's `init-adduser` (base image) gives it to
`abc` on every start, as in every LinuxServer image, and that account — on the host, your
`PUID` user — edits `/config/config.yaml`. **`settings.postexportcommand` is
remote-code-execution-equivalent configuration**, not a convenience hook, so what the
exporter takes from `/config` depends on the uid it runs as (ADR-0049). The image reads no
`.env` file, `/config/.env` included: it sets
`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV=false`, and a leftover `/config/.env` gives
one WARNING at start-up (ADR-0049, amendment E015-S02-005).

- **When the exporter runs as root**, `postexportcommand`, `outputpath` and `datapath` are
  taken only from `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_*` environment variables or the
  command-line flags. A value from `config.yaml` (or the confuse user config, or a `.env`
  file) is ignored with one ERROR at start naming the setting, the file and the variable to
  use. Set a root hook in the container's `environment:`.
- **When the exporter runs as root**, a `.env` file (a CLI run as root; the image reads no
  `.env`) may set only `any-source` settings. Every other variable it would add —
  `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_*`, `LD_PRELOAD`, `DOCKER_HOST`, `PATH`, anything —
  is dropped before the hook or the Docker client can inherit it, with one ERROR per file
  listing the dropped names (never their values). A variable the container's environment
  already sets is untouched. Set such variables in the container's `environment:`
  (ADR-0049, amendment 2026-10-12).
- **In both modes**, `filespec` is a file-name glob inside the data path. A value with a
  directory part, `..` or an absolute path is ignored with an ERROR and `*.json` is used.
- **In both modes**, root and unprivileged, the ACME store and its directory must not be
  writable by `PUID`: mount `/data:ro`. A `PUID`-writable store lets that account forge what
  a root exporter writes into `/certs` (residual risk AR-1, ADR-0049); in root mode the
  start-up log does not yet say so (BL-E015-004).
- **In dropped mode** (the exporter runs as `abc`) a `config.yaml` hook keeps working and
  runs as `PUID`; that account already owns `/config`, so it gains nothing.
- A root hook must not run a program or script stored in `/config`, and
  `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE` must not point into `/config`: `abc` can
  rewrite both. This is documented, not enforced.

The start-up line `Post-export command: <set|not set> (source: …), runs as uid …` shows
where the hook came from and which uid runs it.

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
it starts: `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_<n>` Apprise URLs (which commonly embed an
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

#### The hook command is a secret in the logs

A hook command often carries a credential (`curl -H "Authorization: Bearer …"`, a webhook
token). `settings.postexportcommand` is a declared secret: the DEBUG settings and config
dumps show it as `***REDACTED***` when it is set (and `null` when it is not), and every hook
log line names only the program, `argv[0]` — `Post-export command curl exited 7: …`,
`… timed out …`, `… failed to start: …` — never its arguments. A command that cannot be
parsed is reported without the command or the parser's message, which can echo a fragment of
it. On failure only the last non-empty line of the hook's stderr is logged, as its diagnostic
output: every argument of 4 or more characters is masked as `***`, CR/LF/ESC are stripped,
and the line is cut to 200 characters. It is not redacted beyond that: a hook that prints
its credential in another form than the argument it was given leaks it there.

### Container privileges: when the image keeps root, and when it drops

The container decides **once, at start-up**, whether the exporter runs as root or as `abc`
(the `PUID`/`PGID` account). It drops to `abc` only when it can **prove** that account can do
the job; anything it cannot prove keeps root (ADR-0030, amended 2026-10-10). Read the table
top to bottom — the first row that matches your deployment is the answer:

| # | Condition at container start | Service runs as | Start-up log |
|---|---|---|---|
| 1 | The settings cannot be resolved (malformed `/config/config.yaml`, invalid environment), or `settings.datapath`/`settings.outputpath` is a relative path | `root` | WARNING `could not resolve settings` — a malformed configuration is then reported by the exporter itself |
| 2 | `settings.restartcontainers` is enabled | `root` | WARNING naming `settings.restartcontainers` — `/var/run/docker.sock` access cannot be guaranteed for an unprivileged account |
| 3 | `settings.datapath` does not exist, or `abc` cannot list it | `root` | WARNING `cannot list settings.datapath` |
| 4 | No file matches `settings.filespec` under `settings.datapath` yet | `root` | WARNING `no file matches` — restart the container once Traefik has written its store |
| 5 | Any matching ACME store file is not readable by `abc` — **the stock Traefik case**: Traefik runs as root and writes `acme.json` `root:root 0600` | `root` | WARNING naming the files (`not readable by abc`) and the remedy below |
| 6 | `abc` cannot write `settings.outputpath` even after the container took ownership of it (read-only mount, root-squashed share) | `root` | WARNING `cannot write settings.outputpath` |
| 7 | Otherwise | `abc` | No WARNING |

Exactly one privilege WARNING is logged per container start when root is retained, so
`docker logs` answers "why is this running as root?" directly. There is no separate switch
and nothing to opt into.

**How to get the unprivileged mode.** Traefik refuses to start if `acme.json` has any group
or other permission bit set, and writes it `0600` owned by the user Traefik runs as — so
the only way for another account to read it is to *be* that user. Run Traefik as a non-root
user, and set this container's `PUID`/`PGID` to that user's uid/gid. `settings.restartcontainers`
still forces root whatever the store permissions are.

**Unprivileged mode requires `/data` mounted read-only (`:ro`), and so does root mode — mount
it read-only in both modes.** With `PUID`/`PGID` set to Traefik's uid, `abc` owns the store;
if `/data` is writable, a compromised exporter could chmod, delete or plant an unreadable
`*.json` there and make the **next** start keep root (rows 3–5), and a root exporter would
export whatever that account forged into the store (ADR-0049, AR-1). Mount `/data:ro`. When the store is writable by `abc`, the start-up log says so
in one line (an `INFO:` line when dropping, appended to the WARNING otherwise) — the
container still starts, but treat that line as a deployment defect.

**The decision is not re-checked while the container runs.** If Traefik first writes its
store after the exporter started (row 4), or the store's owner or mode changes later, the
start-up decision stands until the container is restarted. A store that becomes unreadable
after a drop surfaces as the exporter's per-file `Error processing file` errors; restart the
container to re-decide.

The decision is made by the **installed exporter**, not by a second parser in the init
script: the container asks `SettingsManager` for the resolved settings and uses the
exporter's own `glob` of `settings.datapath`/`settings.filespec` as the set of store files,
so every source the application honours (packaged default, config file, environment; the
image reads no `.env`) and its exact truthiness apply. The probes run *as* `abc` (`s6-setuidgid`), not
as root, which would read every file and prove nothing.

**What the unprivileged mode changes.** When the container drops to `abc`:

- **The output path is chowned to the `PUID`/`PGID` account** on start-up. The *resolved*
  `settings.outputpath` is used, not the `/certs` default, so a custom mount is covered too.
  Symlinks inside it are skipped and never followed, and the walk does not cross into a
  nested mount — a link planted in the output volume must not be able to redirect a
  root-owned `chown`. If your host tooling depends on a particular owner for that directory,
  set `PUID`/`PGID` to match it.
- **The service gets its own `HOME`** (`/run/traefik-certificate-exporter/home`, on tmpfs).
  `s6-setuidgid` changes the uid and nothing else, and the configuration library creates an
  application directory under `$HOME` on every start; the image's `HOME` is a root-owned
  `0700` `/root`, which the dropped account cannot write.

**Upgrading to 0.3.0 (from v0.2.0).** v0.2.0 always ran the exporter as root.

- Stock Traefik (root, `acme.json` `0600`) with `restartcontainers` off: no functional
  change — still root, still exporting. New: one start-up WARNING saying why it runs as root,
  which files forced it, and how to get the unprivileged mode.
- A store already readable by `PUID`/`PGID` (Traefik run as that uid/gid) with
  `restartcontainers` off: the exporter now runs as `abc`, with no privilege WARNING. New on
  first start: the output path is chowned to `PUID`/`PGID`, and file logging degrades to
  console-only (see the known limitation below). Mount `/data:ro` for this mode.
- `restartcontainers` on: unchanged — root, now with a start-up WARNING.

`/data` is never chowned or chmodded — the exporter only reads it, and Traefik requires
`0600`. `/config` is owned by `PUID`/`PGID`, as LinuxServer's `init-adduser` makes it on every
start; because that account can rewrite it, a root exporter does not take
`postexportcommand`, `outputpath` or `datapath` from it (see "Trust boundary" above,
ADR-0049).

**Known limitation:** file logging (`logging.consoleonly: false`) writes a relative path
resolved against `/config`, so the dropped account cannot open it; the
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
the forge release — is enabled only when its own `PUBLISH_*_TOKEN` secret **and** every
`PUBLISH_*` variable it needs are set and non-empty, separately on each forge (AD-9). With
nothing set, a run succeeds and publishes nothing, silently. A partly configured
destination is skipped with exactly one `::warning::` per run naming what is missing and
where to set it; the run stays green.

**Where the secrets live.** One forge's run publishes all destinations of a release
(CI spine AD-9); the other forge holds no `PUBLISH_*` secret or variable (a variable left
there alone warns on every run).

- **GitHub:** every `PUBLISH_*` secret lives in the `dev` or `release` environment of the
  jobs that use it, never at repository level, where any same-repository branch workflow
  could read it ([ADR-0039](adr/0039-publish-credentials-in-forge-environments.md)). A
  token both workflows use is set in both environments.
- **Gitea:** Gitea ignores `environment:`, so `PUBLISH_*` secrets are repository-level and
  are present only when Gitea is the publishing forge. A Gitea-run release may hold the
  PyPI, TestPyPI, GHCR and Docker Hub tokens too, and then requires the AD-13 mitigations:
  protected `main` and `v*` tags with push and tag creation limited to trusted accounts,
  project-scoped tokens, and rotation of every token after any untrusted push (ADR-0039 as
  amended 2026-10-11, [ADR-0046](adr/0046-e014-pipeline-amendments.md)).

The settings to apply on each forge are the checklist in
[ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md#forge-settings-the-maintainer-applies).

The destination table, the `PUBLISH_*` variables that go with each secret, and the image
tags each workflow writes are in
[ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md#where-things-are-published).

The Gitea package index and the Gitea container registry share `PUBLISH_GITEA_TOKEN` and
`PUBLISH_GITEA_USERNAME` (AD-9 table) but are enabled independently: the index also needs
`PUBLISH_GITEA_PYPI_URL`, the registry `PUBLISH_GITEA_REGISTRY` and `PUBLISH_GITEA_IMAGE`.
A registry whose token is set but whose image (or, for Gitea, registry) variable is empty
is skipped with a warning before any login or push; the other destinations still publish.
Because a skipped destination does not fail the run, check each release run for zero
destination warnings (the per-release checklist in
[ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md#releasing)). On GitHub, a
destination only one workflow publishes to keeps its variables in that workflow's
environment, or the other workflow reports it as partially configured on every run. Legacy secrets that
nothing reads any more (for example `DOCKERHUB_TOKEN`) are reported once per run with
their `PUBLISH_*` replacement.

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
   instead, delete the secret from **every environment that holds it** (`dev` and `release`
   for a shared token; on Gitea, the repository or organisation store), or clear one of
   the destination's required `PUBLISH_*` variables: the destination switches off and runs
   keep succeeding. A secret left in one environment keeps that workflow publishing.
   Clearing a variable while the secret remains reports the destination as partially
   configured on every run, which blocks a release under the zero-warning rule: delete the
   secret too, or clear every variable it needs, before the next release.
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
