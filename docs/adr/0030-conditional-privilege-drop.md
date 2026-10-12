# ADR-0030: Conditional root — keep root unless the ACME store is proven readable

- **Status:** Accepted (implemented by E012-S01-001 and E013-S02-004; status corrected
  2026-10-11 by E014-S02-003)
- **Amended:** 2026-10-10 (BL-E013-041, E013-S02-004)
- **Amended by:** ADR-0044 (2026-10-11, E014-S01-005) -- the init resolver also emits the
  run mode (`watch-for-changes`), which the service consumes like the privilege state
- **Date:** 2026-10-08
- **Deciders:** Maintainer (ravensorb), via Epic E012 Sprint S01 (Story E012-S01-001)
- **Epic:** E012
- **Title note:** retitled 2026-10-11 (E014-S02-003) to state the amended rule; the original
  title was "privilege drop unless the Docker-socket restart path is enabled"
- **Amends:** ADR-0002 (linuxserver.io base image and PUID/PGID privilege model). ADR-0002
  accepted "root-owned entrypoint before privilege drop" as the linuxserver.io convention,
  but the shipped service script never dropped: it ran `s6-setuidgid root`, so the
  long-lived exporter process — the one that reads an attacker-influenceable ACME store,
  executes `settings.postexportcommand`, and writes into `/certs` — held root for the whole
  container lifetime. This ADR keeps ADR-0002's base image and PUID/PGID model and narrows
  where root survives; it does not revisit the base-image choice.
- **Principle(s) in tension:** Docker overlay (non-root runtime) vs. Core §7 (operator
  ergonomics — a working default that needs no manual step)

## Context

Red-team finding RT-004 (backlog BL-E011-012) observed that `svc-traefik-certificate-exporter`
runs `s6-setuidgid root` unconditionally while `/config` is an operator-writable volume
feeding `settings.postexportcommand`, which is execution-equivalent configuration. Any
path to code execution inside the container therefore lands as root, which also widens
RT-001, RT-003 and RT-009.

Exactly one feature needs root: `settings.restartcontainers`, which talks to the mounted
`/var/run/docker.sock`. The socket's group ownership is host-dependent, so an unprivileged
in-container account cannot be relied on to reach it. Every other configuration — the
common one — needs nothing above the `abc` (PUID/PGID) account the base image already
creates.

## Options considered

| Option | Pros | Cons | Standards fit |
|--------|------|------|---------------|
| A. Conditional drop keyed on `settings.restartcontainers` (chosen) | The common configuration runs unprivileged with no operator action; root survives only where it is load-bearing, and says so at start-up | Two start-up paths to reason about; `/certs` ownership must be taken at init for the dropped case | Satisfies the overlay for the default configuration and makes the exception explicit |
| B. Unconditional drop to `abc` | Simplest, strongest | Silently breaks every deployment using `restartcontainers` — the socket becomes unreachable, with a permission error far from its cause | Best literal fit, unacceptable operator break |
| C. Keep root, document the risk | No behaviour change | Leaves the finding open; documentation is not a control | Fails the overlay |
| D. Add a new `runasroot` setting | Explicit | A second setting that must agree with `restartcontainers` or the container misbehaves; the operator can only get it wrong | Rejected: derived state should not be re-entered by hand |

## Decision

Take Option A. `init-traefik-certificate-exporter-config` resolves the settings once, **by
asking the installed package** (`SettingsManager.loadFromFile`) rather than by parsing the
config file a second time, and writes the answer to
`/run/traefik-certificate-exporter/run-as-root`. `svc-traefik-certificate-exporter` reads
that one value and execs through a single `s6-setuidgid` call: `root` when it reads `true`,
`abc` otherwise.

Reusing the application's own resolver is not a convenience: a second parser would have its
own source list and its own truthiness, and the first value the two disagreed on would drop
privileges out from under a configuration that needs the Docker socket — producing a bare
permission error from `docker.from_env()` far from its cause.

Three properties are load-bearing:

1. **The safe answer is written first.** The state file is set to `false` before the config
   is parsed, so an unreadable, malformed or missing config — or any failure between the
   two — leaves "drop privileges", never "keep root". The init script warns when it falls
   back.
2. **A missing state file reads as drop.** If the init oneshot never ran, the service script
   sees an empty read and drops.
3. **Retaining root is announced.** The service logs a WARNING naming the condition
   (`settings.restartcontainers` enabled) and the remedies (disable it, or front the socket
   with an endpoint-restricted proxy).

When privileges are dropped, init also makes the `abc` account viable:

- It takes ownership of the **resolved** `settings.outputpath` (not the `/certs` default, so
  a custom mount is covered). The walk is `find … -xdev ! -type l -exec chown -h …`, never
  `chown -R` or `lsiown -R`: both of those dereference symlinks, which would turn this
  root-owned init into an arbitrary-chown primitive driven from the very volume the drop
  exists to contain.
- It probes every `settings.filespec` match under `settings.datapath` for readability as
  `abc` and warns, naming the files and the remedies, when they are not readable. Traefik
  writes `acme.json` mode `0600` owned by its own account, so this is the common upgrade
  break and it would otherwise surface only as a generic per-file error.
- It creates a tmpfs `HOME` owned by `abc` (`/run/traefik-certificate-exporter/home`) and
  the service exports it. `s6-setuidgid` changes the uid and nothing else, and `confuse`
  unconditionally creates its application directory under `$HOME` — which is a root-owned
  `0700` `/root` in the base image, so without this the dropped service dies before reading
  a single certificate.

`/config` is deliberately **not** chowned: it stays root-owned because
`settings.postexportcommand` makes it execution-equivalent configuration, and handing it to
the account that runs the hook would re-open the loop this ADR closes.

No new setting, environment variable or CLI flag is introduced. `settings.restartcontainers`
is the sole input.

## Consequences

- Positive: the default deployment no longer runs a long-lived root process that parses an
  attacker-influenceable store and executes an operator-supplied hook. RT-001, RT-003 and
  RT-009 all shrink with it.
- Positive: the root case is now visible in `docker logs` rather than implicit in a script.
- Negative / trade-offs accepted: operators who mounted the output path with host ownership
  that must not change will see it chowned to the PUID/PGID account on first boot of the
  dropped configuration. This is the linuxserver.io convention for owned volumes, but it is
  a real change for anyone upgrading.
- Negative / trade-offs accepted: the ACME store is **not** chowned (the exporter only reads
  it, and Traefik requires `0600`), so a store the dropped account cannot read stops exports
  until the operator sets `PUID`/`PGID` to a reader or relaxes the group permission. The
  start-up probe makes that condition loud rather than silent, but it does not fix it.
- Negative / trade-offs accepted: file logging writes a relative path under the root-owned
  `/config` and therefore degrades to console-only for the dropped account. Tracked as a
  follow-up; console logging plus the runtime's log driver is the supported path meanwhile.
- Negative: operators needing `restartcontainers` still get root. The documented
  least-privilege path for them is a docker-socket proxy (see `docs/operational.md`), which
  this ADR does not require or implement.
- Follow-ups: if a socket-proxy deployment becomes the documented default, the root branch
  can be removed entirely and this ADR superseded.

## Amendment (2026-10-10): drop only when the ACME store is proven readable

### Context

BL-E013-041 (maintainer review). Traefik writes `acme.json` mode `0600` owned by the user it
runs as, and refuses to start when the store is any more open
(`pkg/provider/acme/local_store_unix.go` `CheckFile`: `mode & 0o077 != 0` → "too open,
please use 600"). Traefik's official image runs as root, so the default store is
`root:root 0600`. Under the original decision every such deployment with
`settings.restartcontainers` off dropped to `abc` and could not read its own store: the
exporter's core function failed with only an init WARNING, and that WARNING's remedy —
relaxing the group permission — is one Traefik refuses. The original drop never shipped
(v0.2.0 always ran as root; the conditional drop arrived after it), so this amendment is
written against v0.2.0 behaviour.

### Decision

Maintainer decision 2026-10-10, option A: the service drops to the `PUID`/`PGID` account
**only** when every one of these is proven at container start — the settings resolved;
`settings.restartcontainers` is false; `settings.datapath` exists and is listable by `abc`;
at least one file matches `settings.filespec` there (the application's own `glob.glob`
matches, emitted by the init script's embedded resolver); every match is readable by `abc`;
and, after init takes ownership of it, `settings.outputpath` is writable by `abc`. Every probe
runs as `abc` through `s6-setuidgid`. Anything else keeps root, with exactly one start-up
WARNING naming the reason, the files, and the remedy: run Traefik as a non-root user and set
`PUID`/`PGID` to that user's uid/gid (`settings.restartcontainers` still forces root). The
decision lives in a sourced helper,
`/usr/local/lib/traefik-certificate-exporter/privilege-decision.sh`, so it is executed by the
test suite rather than only grepped. It is taken once per container start and not re-checked
at runtime. No new setting is introduced; option D stays rejected.

**Superseded passages of the original text** (left intact above as the historical record):

1. Property 1, "**The safe answer is written first.** The state file is set to `false` …
   never 'keep root'" — the pre-written answer is now `true`: nothing proven means root. An
   unresolved configuration keeps root; the exporter then fails its own configuration load
   and exits.
2. Property 2, "**A missing state file reads as drop.**" — a missing or empty state file now
   reads as root: nothing was proven, and the dropped path is not viable without init anyway
   (no tmpfs `HOME`).
3. Property 3 and the Decision text that the **service** script logs the root WARNING — the
   WARNING moves to init, exactly one per container start; a longrun restart does not repeat
   it.
4. The Decision bullet that init "probes every `settings.filespec` match … for readability as
   `abc` and warns" — the probe now **decides**; it no longer merely warns.
5. The Consequences bullet remedy "until the operator sets `PUID`/`PGID` to a reader or
   relaxes the group permission" — the group-permission remedy is withdrawn: Traefik's `0600`
   check makes it impossible. The only remedy is running Traefik as the `PUID`/`PGID` user.
6. The Context/Decision claim that `settings.restartcontainers` is "the sole input" — the
   ACME store's readability by `abc` and the output path's writability by `abc` are now
   inputs too.

### Consequences

- The default stock-Traefik deployment (root Traefik, `root:root 0600` store) runs the
  exporter as **root**, with one WARNING. Relative to the unreleased original decision this
  widens where root survives and keeps the RT-001/RT-003/RT-004/RT-009 surface for that
  deployment; relative to the released v0.2.0 (always root) it narrows nothing for stock
  Traefik and narrows it for stores readable by `PUID`/`PGID`. This is the maintainer's
  accepted trade-off: an exporter that exports nothing is worse than one that runs as root
  and says so.
- Unprivileged mode is only as sound as a **read-only `/data` mount**. With `PUID`/`PGID` set
  to Traefik's uid, `abc` owns the store; if `/data` is writable, a compromised `abc` can
  chmod, delete or plant an unreadable file and the next start keeps root. `/data:ro` is
  documented as a requirement for unprivileged mode, and the start-up log carries one line
  when the store is writable by `abc`; the container does not refuse to start.
- A store that first appears after a root decision keeps root until restart; a store that
  becomes unreadable after a drop produces the exporter's per-file errors until restart.
  Both are documented in `docs/operational.md`, not handled at runtime.
- Revisit if Traefik relaxes its `0600` check, or if a socket-proxy / non-root-Traefik
  deployment becomes the documented default.
