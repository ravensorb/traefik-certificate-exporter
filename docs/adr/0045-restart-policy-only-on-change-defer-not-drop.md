# ADR-0045: Container restart policy: only on change, with a per-container rate floor and one coalesced trailing restart

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** maintainer decision "restart only on change" (2026-10-11); E014 orchestrator
  decision on the architecture re-review MAJOR; implemented by E014-S01-006
- **Epic:** E014
- **Amends:** ADR-0014 §7 (decision 13, E014-S01-010): the post-export hook and notifications
  run only on change, so a notification means "a certificate changed", not "an export pass
  completed"
- **Departs from spec:** n/a. Binds product spine AD-10
  (`_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md#ad-10--container-restart-one-client-file-mtime-trigger-defer-not-drop-adopted`)
  and PRD FR-8 / FR-15. Resolves BL-E012-004, BL-E012-008 and review finding M6
  (`review-product.md`, "Restart cooldown (BL-E011-016)", drift-silent).
- **Principle(s) in tension:** Core §3 Design by contract (what triggers a restart must be
  stated, not inferred); security (a restart storm over a host-root-equivalent socket);
  availability (no rotation may leave a container serving a stale certificate)

## Context

0.3.0 makes container restarts work for the first time (E014-S01-001 fixed the Docker SDK,
B1). Before this decision:

- every pass restarted every labeled container whose domain was in the pass's list, changed
  or not. The image runs a pass at every start (`RUNATSTART=true`), so every exporter start
  and every ACME write would have restarted every labeled container, limited only by the
  cooldown (BL-E012-008);
- the cooldown (`RESTART_COOLDOWN_SECONDS = 300`) **dropped** a restart that landed inside the
  window. A second rotation within five minutes (two resolvers renewing minutes apart, a
  reissue after a revocation) left the container on the stale certificate until some later,
  unrelated ACME write (M6);
- no ADR stated the window, where it is defined, or whether it is configurable
  (BL-E012-004).

E014-S01-002 made the export compare built bytes with the files on disk and leave unchanged
files untouched (ADR-0043), so a file's mtime moves only on a real change. The architecture
re-review then found that a restart driven by "this pass reported the domain changed" is lost
for good when the exporter crashes between writing and restarting, or when a pending deferred
restart is cancelled at shutdown: the next pass finds unchanged files, reports nothing, and
the container keeps the stale certificate.

## Options considered

| Option | Pros | Cons | Standards fit |
|---|---|---|---|
| A. Restart on the pass's changed-domain list | Simple | A crash between write and restart, or a deferral cancelled at shutdown, loses the restart for good: the next pass sees unchanged files | Fails "no stale certificate" |
| B. Persist a per-container "restart owed" record | Survives a crash | New state file, its own atomicity and corruption handling, and a second source of truth beside the files | Adds persistence the files already make unnecessary |
| C. Compare the exported files' mtimes with the container's `State.StartedAt` on every pass | Both survive a crash; no new state; one rule covers crash, failure, cancelled deferral, upgrade and start-up | Trusts the output directory's mtimes; needs the two clocks to agree (slack) | Chosen |

For the cooldown: keep dropping (status quo, M6), make it configurable (rejected: a knob
nobody needs and a way to switch the protection off), or **defer** one trailing restart per
container (chosen).

## Decision

1. **Restart rule.** On every pass — the run-at-start pass in `app._run` and every drain in
   `AcmeCertificateFileHandler.__processPath`, including passes in which no domain changed —
   `DockerManager.restartLabeledContainers(artifactMtime)` restarts a candidate container
   when `newestArtifactMtime > startedAt + RESTART_MTIME_SLACK_SECONDS`:
   - `newestArtifactMtime` is the newest `st_mtime` among the exported artifacts (the PEMs
     and the `.pfx`) of every domain in the container's
     `com.github.ravensorb.traefik-certificate-exporter.domain-restart` label;
   - `startedAt` is the container's `attrs["State"]["StartedAt"]`, parsed as UTC.
   The changed-domain list does not reach the restart path.
2. **Candidate set.** The running labeled containers on the connected daemon
   (`containers.list(filters={"label": DOCKER_LABEL})`) whose label names at least one domain
   with an exported artifact present on disk when the rule is evaluated, after the pass's
   writes. A container with no artifact on disk for any labeled domain is not a candidate.
   Containers on any other daemon are out of scope.
3. **Artifact lookup.** `AcmeCertificateExporter.artifactMtime(domain)` follows ADR-0040: it
   reads only the paths the export pass recorded per domain through the shared
   `_artifact_paths` helper, the newest file across resolvers wins, and its reach is every
   store file this process has processed (ADR-0040 §6, AR-3). A file that cannot be stat'ed
   counts as missing. The index is published by single assignment so the deferred-restart
   thread can read it while a drain rebuilds it, and a certificate or resolver whose rebuild
   fails keeps its previous paths.
4. **Clock slack.** `RESTART_MTIME_SLACK_SECONDS = 2`, defined in
   `src/traefik_certificate_exporter/libs/docker.py`, not configurable. In the supported setup
   (local daemon, output on a local filesystem) mtime and `StartedAt` come from the same
   clock; the slack absorbs up to 2 s of drift where a network filesystem's server stamps the
   mtime, which would otherwise restart a container a second time on the pass after every
   rotation. Accepted cost: a container started less than 2 s before the write is not
   restarted. Larger skew is unsupported.
5. **Missing or zero `StartedAt`** (absent, empty, unparsable, or `0001-01-01T00:00:00Z` for a
   container that never started): no restart, with a DEBUG log. Not an error.
6. **No persisted state.** The exported files' mtimes and the container's `StartedAt` are the
   only restart state. This depends on E014-S01-002 not rewriting unchanged artifacts
   (ADR-0043). The cooldown map is process-local, so a fresh process's first pass is always
   eligible.
7. **Rate floor.** `RESTART_COOLDOWN_SECONDS = 300`, defined in
   `src/traefik_certificate_exporter/libs/docker.py`, fixed and **not configurable**. No
   container is restarted more than once per 300 s. Its purpose is BL-E011-016 / RT-009: the
   domain names come from an ACME store the operator does not fully control, and without a
   floor a noisy or hostile store could drive restarts over a host-root-equivalent socket.
   Restart-only-on-change narrows this further: a store rewrite that changes nothing never
   reaches the socket.
8. **Defer, don't drop.** A restart the rule calls for but the floor denies arms one daemon
   `threading.Timer(remaining + 1, …)` for that container unless one is pending; otherwise
   the request is coalesced and its domains are added to the pending set. At most one
   trailing restart per container per window, so memory is bounded by labeled containers.
   At fire time the callback builds a fresh client, does `containers.get(id)`, and restarts
   only if the container is **still running** (`status == "running"`; Docker's restart
   endpoint would start a stopped one, amended by SD-01-2), the label still names a
   requesting domain **and** the rule still holds against the
   fresh `StartedAt` and current mtimes, and only if no other restart has claimed the
   window since it was armed (the floor holds at fire time); the trailing restart records a
   new window start. A
   failed restart, immediate or trailing, is logged at ERROR, releases its reservation, and
   arms a retry through this same path one full window later, with the same re-checks, at
   most `RESTART_RETRY_LIMIT` (3) times; then it logs a WARNING and stops (amended by
   ADV-1, E014 sprint 01 closure). The callback carries the arming pass's correlation id.
9. **Shutdown and recovery.** `DockerManager.cancel()` cancels every pending timer and is
   called on every exit path of `app._run`. A cancelled deferral, a restart whose retries are
   spent, and a
   crash between write and restart are all recovered on the next pass by rule 1, because the
   files are still newer than the container: the next start-up pass, or the next ACME write
   (with `runatstart: false`, only once that store file is next written, ADR-0040 §6).
10. **Dry run.** Nothing is written, so mtimes do not move. Containers that already satisfy
    the rule are logged (`[DRYRUN] would restart <id>`, or `would schedule deferred restart
    of <id> in <n>s`); nothing is restarted, armed or recorded.
11. **Client target** (recorded from E014-S01-001, A-15). The Docker client is built only by
    `DockerManager._create_client()` as `docker.from_env(use_context=False)`. docker-py 7.2
    made `from_env()` fall back to the active Docker CLI context when `DOCKER_HOST` is unset;
    ignoring the context keeps the 0.2.x target — `DOCKER_HOST` if set, otherwise
    `unix:///var/run/docker.sock` — so a `~/.docker` planted in the service's `HOME` cannot
    redirect restarts over the host-root-equivalent socket to a different daemon.
12. **`python-dateutil` runtime dependency (AG-11).** Added for one call,
    `dateutil.parser.isoparse`, to parse `State.StartedAt`: Docker emits RFC 3339 with
    nanoseconds and a `Z` suffix, which `datetime.fromisoformat` on Python 3.10 (the project
    floor) accepts neither of. It is maintained, dual-licensed BSD/Apache-2.0, and pulls in one
    transitive dependency (`six`). No hand-written timestamp trimming.
13. **Post-export hook and notifications: only on change (E014-S01-010; amends ADR-0014 §7).**
    The restart rule above reads the files, so it runs on every pass. The post-export hook
    (`run_post_export_command`) and the Apprise notifications (`send_export_notifications`)
    do not: at both call sites they run only when the pass's changed-domain list (ADR-0043)
    is non-empty, and they receive exactly that list, so
    `TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS` and the notification body name only the
    changed domains. When nothing changed, neither runs, and one INFO line,
    `No certificate changed; no hook or notification`, keeps the quiet pass visible (on the
    watch path, once per store file processed, the scope the hook and notifications already
    have there). This holds for every pass: the run-at-start pass with `runatstart: true`,
    a run-once container, and a pass that only recovers a lost restart (rule 9), which
    restarts the container and sends nothing. In a dry run the list is the domains that
    *would* change; the hook and notifications log their existing dry-run skip lines for them
    and run nothing. ADR-0014 §7 ("an export pass completed") was written when nothing
    detected change; with ADR-0043 in place, a notification means "a certificate changed",
    and an operator can keep the channel unmuted. Not added: a hook or notification on
    restart.
14. **`postexportcommand` is a declared secret (E014-S01-010; review-product m4).** A hook
    command often carries a credential (`curl -H "Authorization: …"`, a webhook token).
    `("settings", "postexportcommand")` is in `SECRET_CONFIG_KEYS`, so the DEBUG settings and
    config dumps redact it when set and show `null` when unset (value-aware redaction,
    unchanged). Every hook log line names only the program, `argv[0]` from the existing
    `shlex.split`, never the arguments or the command string; a command `shlex` cannot parse
    is reported without the command and without the parser's message, which can echo a
    fragment of it. The hook's own stderr is still logged on failure as its diagnostic
    output; redacting it is out of scope.

## Consequences

- Positive: a labeled container restarts when, and only when, an exported file for one of its
  domains is newer than its start. Restarting the exporter over an unchanged store restarts
  nothing; the first export into an empty output directory, and the first pass after
  upgrading from 0.2.x (every `.pfx` gains its intermediates), restart each container once.
- Positive: no rotation is lost. Within one process the restart follows at most one window
  after the change; a crash, a failure or a shutdown is recovered on the next pass.
- Trade-off accepted: the rule trusts the output directory's mtimes. Anyone who can write
  there can already replace the certificates the containers serve, so this grants nothing
  new; `docs/operational.md` states the directory must be writable only by the exporter.
- Trade-off accepted: until the next pass after a crash or a cancelled deferral, the container
  keeps the previous certificate.
- Trade-off accepted: a container started less than 2 s before the write is not restarted;
  skew beyond 2 s is unsupported.
- Positive (decisions 13-14): the hook and notifications report real changes only, so an
  exporter restart over an unchanged store, or a pass that only recovers a lost restart,
  runs no operator command and sends nothing; a `postexportcommand` carrying a credential
  never puts it in a log line or a DEBUG dump.
- Trade-off accepted (decision 13): an operator who relied on a notification per exporter
  start as a liveness signal loses it; the quiet-pass INFO line is the replacement. Stated
  as a 0.3.0 release note.
- Tests: `tests/libs/test_docker.py` (rule, slack, `StartedAt` cases, deferral, coalescing,
  fire-time re-check, floor, cancel, correlation, a real-`Timer` case, and the real-exporter
  cases), `tests/libs/test_certificate_exporter.py` (lookup), and the opt-in image test
  `tests/test_container_restart.py` (first run restarts, unchanged run does not, touched files
  restart on the next run). Decisions 13-14: `tests/test_app.py` and
  `tests/libs/test_certificate_exporter_watch.py` (hook and notification guards at both call
  sites, quiet-pass line, dry run, the restart-recovery pass), `tests/libs/test_post_export.py`
  and `tests/libs/test_settings.py` (redaction).

## Revisit when

- the exporter persists state between processes (then the `runatstart: false` caveat can go);
- a supported deployment needs a remote daemon or a network-filesystem output with skew
  beyond 2 s;
- the `requires-python` floor reaches 3.11 and `datetime.fromisoformat` parses Docker's
  timestamps: drop `python-dateutil` (filed as a Low backlog item at closure).
