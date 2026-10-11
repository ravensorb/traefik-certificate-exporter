# Red Team Findings Report

**Scope:** Sprint: E014 / sprint 01 (stories E014-S01-001 … E014-S01-010), traefik-certificate-exporter
**Date:** 2026-10-11
**Analyst:** Red Team Agent (l3io-sec-redteam, headless orchestrator invocation)
**Inputs:** `/tmp/e014-s01-review/sprint-diff.patch` (uncommitted working tree), `stories/E014-S01-*.md` Files-in-scope lists
**Out of scope by instruction:** `.agents/`, `.claude/`, `_bmad/`, `uv.lock`; BL-E014-017 (env default `WATCHFORCHANGES=true` overrides the config file).

## Severity Summary

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 0 |
| MEDIUM | 3 |
| LOW | 6 |
| OBSERVATION | 3 |

## Findings

| Severity | ID | Title | Lens | Location |
|---|---|---|---|---|
| MEDIUM | RT-1 | A failed or interrupted post-export hook is never retried: "only on change" turns one transient failure into a permanent miss | CHA, DAR | `src/traefik_certificate_exporter/app.py:214-229`, `src/traefik_certificate_exporter/libs/certificate_exporter.py:1599-1617` |
| MEDIUM | RT-2 | A partial export restarts consumers into a mismatched key/certificate pair, and in watch mode nothing repairs it until the next store write | CHA | `src/traefik_certificate_exporter/libs/certificate_exporter.py:1010-1029`, `src/traefik_certificate_exporter/libs/docker.py:260` |
| MEDIUM | RT-3 | The primary compose sample, edited this sprint, still mounts `docker.sock:ro` with no host-root warning and enables restarts (EC-001 residue) | DAR, PBR | `docker/docker-compose.yml:13,18` |
| LOW | RT-4 | A planted `cert.pfx` with a huge KDF iteration count stalls the exporter for every domain (demonstrated) | CHA, INS | `src/traefik_certificate_exporter/libs/certificate_exporter.py:347-378` (also `:316-323`) |
| LOW | RT-5 | A future mtime in the output directory causes a restart every cooldown window forever; the 300 s floor does not hold across process restarts | ABU, CHA | `src/traefik_certificate_exporter/libs/docker.py:260`, `:110` |
| LOW | RT-6 | The hook's stderr is logged verbatim and leaks the credentials that ADR-0045 says never reach a log line (demonstrated) | INS, DAR | `src/traefik_certificate_exporter/libs/post_export.py:88-91`, `docs/adr/0045-restart-policy-only-on-change-defer-not-drop.md:171-172` |
| LOW | RT-7 | An empty `pkcs12passphrase` silently produces an unencrypted PFX, and silently downgrades an existing encrypted one | DAR | `src/traefik_certificate_exporter/libs/certificate_exporter.py:290-298` |
| LOW | RT-8 | The socket-proxy guidance is self-contradictory and now too narrow for S01-001's client; the privilege decision keeps root even behind a TCP proxy | DAR, PBR | `docs/operational.md:91-93` vs `:414-419`, `docker/root/usr/local/lib/traefik-certificate-exporter/privilege-decision.sh:86-91` |
| LOW | RT-9 | A run-once container exits 0 when exports fail, so a scheduler cannot see a failed renewal | DAR | `src/traefik_certificate_exporter/app.py:190-235`, `docker/README.md:71-73` |
| OBS | RT-10 | Verified good: the Docker client ignores CLI contexts, and restart labels never reach the filesystem | EXT | `libs/docker.py` `_create_client`; `libs/certificate_exporter.py:694-720` |
| OBS | RT-11 | Verified good: the settings and config dumps redact `postexportcommand` and Apprise URLs (demonstrated) | INS | `libs/settings.py` |
| OBS | RT-12 | Verified good: run-mode state cannot be tampered with by the unprivileged service | INS | `init-…-config/run:43,136-137`; `svc-…/finish` |

---

### RT-1 (MEDIUM): A failed or interrupted post-export hook is never retried

- **Lens:** CHA, DAR
- **Where:** `app.py:214-229` (run-at-start pass) and `certificate_exporter.py:1599-1617` (`__processPath`, watch pass). The hook and notifications run only when `exportCertificates*()` reports changed domains.
- **Evidence (executed):** two run-once passes against a real-material v3 fixture, with a hook that exits 1:
  ```
  pass 1: ERROR Post-export command /tmp/rt-e014/hook.sh exited 1:
  pass 2: INFO  No certificate changed; no hook or notification
  hooklog: "hook ran v3.example.test"   <- exactly once
  ```
  The files are written before the hook runs. After that, every later pass sees "unchanged" and the hook never runs again. A crash, `docker stop`, or s6 respawn between the write and the hook has the same effect.
- **Attack path / failure:** the hook pushes the renewed certificate to an appliance (load balancer, firewall, mail server, or a key-compromise rotation). It fails once (network blip, 30 s timeout, appliance busy). The appliance keeps the old certificate until it expires, or keeps the revoked key in service. The ERROR line is the only signal, and nothing retries.
- **Why this is a design gap:** ADR-0045 rejected option A ("restart on the pass's changed-domain list") for restarts because "a crash between write and restart … loses the restart for good". Decision 13 then applied that same rejected design to the hook. Restarts are recoverable; the hook is not. Before this sprint, every pass re-ran the hook, so it healed itself.
- **Fix:** give the hook the recovery property restarts have. Write a stamp file (`<outputPath>/.postexport-ok`, mode 0600) only after the hook exits 0. On every pass, run the hook for domains whose `artifactMtime` is newer than the stamp, and pass exactly those domains. This keeps "files are the only state". At minimum, make the failure line say it will not be retried, and make run-once exit non-zero (see RT-9).

### RT-2 (MEDIUM): A partial export restarts consumers into a mismatched key/certificate pair

- **Lens:** CHA
- **Where:** `certificate_exporter.py:1010-1029` writes the changed artifacts in the order key, cert, chain, fullchain, pfx. A failure after the first write returns `(True, paths)`, so the domain is reported, its paths are recorded, and the new `privkey.pem` mtime makes every labeled container a restart candidate in the same pass (`docker.py:260`, called on every pass at `app.py:235` and `certificate_exporter.py:1624`).
- **Attack path / failure:** a renewal rotates the key. `privkey.pem` is written, then `cert.pem` fails (`ENOSPC` on a full volume, `EACCES` on one file, an `EIO` blip). The exporter restarts nginx/haproxy/postfix with the new key and the old certificate. The consumer fails its key/cert match check and does not start, or serves handshake failures. The comment at `:1023-1024` says "the next pass sees the remaining differences and writes them". In watch mode, though, the next pass only happens on the next `acme.json` event, which can be days away for a quiet store. The outage lasts until then, or until someone restarts the exporter.
- **Fix:** (a) do not count a domain with an incomplete set toward the restart rule. Keep its previous recorded paths (the `keepNames` mechanism already exists) or record nothing new for it. (b) After a partial export, re-arm the drain timer for that store file so a retry happens within one debounce window rather than at the next store event. (c) Optionally, stage all temp files first and only `os.replace` them once every temp write has succeeded. That narrows the window to the renames.

### RT-3 (MEDIUM): The primary compose sample still mounts `docker.sock:ro` with no host-root warning (EC-001 residue)

- **Lens:** DAR, PBR
- **Where:** `docker/docker-compose.yml:18`: `- /var/run/docker.sock:/var/run/docker.sock:ro  # Only needed if you are going to be restarting containers`. In the same file, `:13` sets `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS=true`.
- **Evidence:** EC-001 (HIGH, E011 epic closure) fixed this wording in `docker/README.md:188,208`, which now say "WARNING: `ro` does NOT limit API calls … host-root-equivalent". The standalone `docker-compose.yml` was edited in this sprint (E014-S01-004: names, quoting, `version:` removed) without picking up the warning.
- **Why it matters more now:** before E014-S01-001, the restart client failed on its first call (B1), so the socket mount was latent. This sprint makes the restart path work. Under ADR-0030, `restartcontainers=true` forces the service to run as root. Copying the sample therefore produces a working root process with an unrestricted Engine socket and a `/config` code-load path (RT-004, accepted). The sample's comment implies `:ro` is a narrowed grant. Platform guidance: CIS Docker Benchmark; OWASP Docker Security Cheat Sheet rule #1 (cached `research-cache/container-and-key-material.md`, 2026-10-06).
- **Fix:** copy the README `:188` WARNING comment into `docker-compose.yml:18`. Better: ship the sample with a socket-proxy service and `DOCKER_HOST=tcp://socket-proxy:2375`, with the raw socket commented out. Add a test asserting every `docker.sock` mount in `docker/**` and `README.md` carries the warning, so the next sample edit cannot drop it (global rule 3/4: derive the scope from a glob, not a list).

### RT-4 (LOW): A planted `cert.pfx` with a huge KDF iteration count stalls the exporter

- **Lens:** CHA, INS (requires write access to the output directory)
- **Where:** `_pfx_differs` (`certificate_exporter.py:347-378`) parses whatever file sits at the PFX path with `pkcs12.load_key_and_certificates(existing, password)`. The PKCS12 MAC and PBES2 iteration counts are taken from that untrusted file. `_file_differs` (`:316-323`) also `read_bytes()`es any regular file at a PEM path with no size bound.
- **Evidence (executed, cryptography 50.0.2):** load time scales linearly with rounds: 2 M rounds took 2.4 s. End to end, with `--pkcs12-passphrase pw`, a baseline pass took 0.68 s. After planting a 0600 `cert.pfx` with 20 M rounds, the pass took **25.1 s**. At `INT_MAX` rounds that is about 45 min per planted file per pass. Passes are serialised, so every other domain's renewal waits too. The exporter overwrites the plant at the end of the pass, so the attacker re-plants to sustain it. The scope is limited to deployments with a passphrase set; with `password=None` the load returns immediately.
- **Why LOW:** ADR-0045 and `docs/operational.md:132-134` require the output directory to be writable only by the exporter, and a writer there can already replace served certificates. The new cost is liveness: one writer can block repairs for every domain. It also reaches parser code (OpenSSL PKCS12) that previously never read attacker-shaped input.
- **Fix:** before parsing, `lstat` the file. Treat it as "differs" without opening it when `st_uid != os.geteuid()` or `st_size > 64 KiB`. A file the exporter did not write is rewritten, never parsed. The same guard covers the unbounded `read_bytes()` in `_file_differs`.

### RT-5 (LOW): A future mtime causes perpetual restarts, and the cooldown resets with the process

- **Lens:** ABU, CHA
- **Where:** `docker.py:260`: `if newest > startedAt + RESTART_MTIME_SLACK_SECONDS`. The cooldown map `self.__lastRestart` (`:110`) lives in memory only.
- **Attack path / failure:** `touch -d 2099-01-01 /certs/<resolver>/<domain>/cert.pem`. The content is unchanged, so `_file_differs` never rewrites the file and the mtime never comes back. Every pass then satisfies the rule for every container labeled with that domain, so each is restarted once per 300 s window, indefinitely, and nothing heals it. The 300 s floor does not survive a process restart. In run-once mode under `restart: unless-stopped` (documented as wrong in `docker/README.md:74-77`, but easy to get wrong), or in a watch-mode crash/respawn loop, each fresh process has an empty map and restarts immediately. That defeats the RT-009 floor. A backup restore or NFS server clock running ahead does the same without an attacker. ADR-0045:162-164 says this "grants nothing new" over replacing certificates. The difference is that a replaced certificate is overwritten on the next pass, while a touched mtime is never repaired.
- **Fix:** in `_verdict`, if `newest > time.time() + RESTART_MTIME_SLACK_SECONDS`, log a WARNING and treat the domain as not a candidate. Alternatively, have `_breaks_write_policy` count a future mtime (or a non-exporter owner) as "differs", so the next pass rewrites the file and resets the mtime. Optionally persist the last-restart time per container in `/run/traefik-certificate-exporter` so the floor survives an s6 respawn.

### RT-6 (LOW): The hook's stderr leaks credentials that ADR-0045 says never reach a log line

- **Lens:** INS, DAR
- **Where:** `post_export.py:88-91` logs `result.stderr.strip()` at ERROR.
- **Evidence (executed):** with `--post-export-command "/tmp/rt-e014/hook2.sh --token SEKRETTOKEN"` and a hook emulating `curl --fail`:
  ```
  ERROR … Post-export command /tmp/rt-e014/hook2.sh exited 22: curl: (22) The requested URL returned error: 401 for https://hooks.example.test/SEKRETTOKEN
  ```
  The same run shows the DEBUG settings and config dumps redact both `postexportcommand` and `APPRISEURLS_0` (see RT-11). The leak is only through stderr. ADR-0045 decision 14 (`:151-152`) does record the stderr carve-out ("redacting it is out of scope"). However, the Consequences bullet at `:171-172` says a credential-carrying `postexportcommand` "never puts it in a log line". That overstates the coverage, which global rule 3 flags as worse than no claim.
- **Fix:** before logging stderr, replace every `argv[1:]` token of 8 or more characters, and any `://…@` userinfo, with `***REDACTED***`, and cap stderr at about 2 KiB. Correct ADR-0045:171-172 to say "the command line is never logged; the hook's own stderr is logged as written".

### RT-7 (LOW): An empty `pkcs12passphrase` silently produces an unencrypted PFX

- **Lens:** DAR
- **Where:** `_normalize_passphrase` (`certificate_exporter.py:290-298`) maps `""` to `None`. `_pfx_differs` then sees that an existing encrypted PFX does not load with `None` and rewrites it unencrypted. Nothing logs this.
- **Attack path / failure:** a compose file uses `PKCS12PASSPHRASE=${PFX_PASS}` and `PFX_PASS` is unset on a new host. The value becomes `""`, every encrypted `.pfx` is silently rewritten unencrypted, and nothing tells the operator. Before this sprint, `""` raised and produced no PFX, so it failed closed. The impact is bounded: the file stays 0600, and an unencrypted `privkey.pem` sits beside it anyway.
- **Fix:** distinguish "unset" (`None`) from "set but empty" (`""`). Log a WARNING once at start-up for the latter ("pkcs12passphrase is set but empty; PFX files are written unencrypted"), and another when an encrypted PFX is about to be rewritten unencrypted.

### RT-8 (LOW): The socket-proxy guidance contradicts itself and no longer matches the client

- **Lens:** DAR, PBR
- **Where:** `docs/operational.md:91-93` allowlists `_ping`, `version`, `containers/json`, `containers/{id}/json` and `containers/{id}/restart`. `docs/operational.md:414-419` allowlists only `GET /containers/json` and `POST /containers/{id}/restart`. Since E014-S01-001, the client calls `ping()`, `version()` (start-up `check()`), `containers.list()` (non-sparse, which inspects each container) and `containers.get()` (deferred restart).
- **Failure:** an operator who follows `:414-419` gets a start-up ERROR, and every restart fails on the inspect call. Certificates go stale in consumers. The quickest fix an operator will find is to widen Tecnativa's proxy with `POST=1`, which also allows `/containers/create` (a host bind mount, so host root) and removes the point of the proxy. Separately, `privilege-decision.sh:86-91` forces root whenever `restartcontainers=true`, even when `DOCKER_HOST` points at a TCP proxy and no socket is mounted. The hardened deployment the docs recommend therefore still runs as root for no reason (ADR-0030:113 already lists this as a follow-up).
- **Fix:** keep one allowlist, cross-referenced from both places. Name the proxy settings that implement it (`CONTAINERS=1`, `ALLOW_RESTARTS=1`, `POST=0`; ping and version are allowed by default) and say explicitly not to use `POST=1`. In `privilege-decision.sh`, keep root for restarts only when no `DOCKER_HOST` is set, or when it is a `unix://` path that needs socket access.

### RT-9 (LOW): A run-once container exits 0 when exports fail

- **Lens:** DAR
- **Where:** `app.py:190-235` (`_run_passes`). Export failures are logged and the process exits 0. This is documented at `docker/README.md:71-73` ("a scheduler cannot detect a failed export from it").
- **Failure:** a cron, systemd-timer or Kubernetes Job deployment reports success while a domain fails to export every night (bad store entry, full disk, RT-2, RT-1). The certificate expires unnoticed. Being documented does not close the gap.
- **Fix:** in run-once mode, exit with a distinct non-zero code (for example 3) when any domain failed to build or write, or when the hook failed. The `finish` script already forwards the code (ADR-0044 §3).

### RT-10 (OBS): Verified good: CLI contexts are ignored and restart labels never reach the filesystem

`_create_client` uses `docker.from_env(use_context=False)`, so a planted `~/.docker` context cannot redirect restarts. `artifactMtime(domain)` only compares the label-supplied string against recorded `(resolver, name)` keys and `stat`s recorded paths. A crafted label such as `../../etc` matches nothing and never builds a path.

### RT-11 (OBS): Verified good: the dumps redact `postexportcommand` and Apprise URLs

This was demonstrated at `-ll DEBUG` with `APPRISEURLS_0='json://u:APPRISETOK@h/'` and a token in the command. Across 207 log lines, the only token occurrence was the stderr line in RT-6. Legacy and unknown-name warnings (`legacy_settings.py`) carry names only, sanitised through `_sanitize_for_log`. Config parsing uses `yaml.safe_load`.

### RT-12 (OBS): Verified good: the unprivileged service cannot tamper with run-mode state

`/run/traefik-certificate-exporter` is created by root in init (`:43`). Only `home/` is chowned to `abc` (`:136-137`), so the unprivileged service cannot rewrite `watch-for-changes` or `run-as-root`. `finish` treats anything but the exact string `false` as watch mode. The exit-code mapping cannot wrap to 0. Prior fixes RT-001 (`_is_safe_path_component`, `:418`) and RT-002 (`_SECRET_FILE_MODE = 0o600`, `:65`) were spot-checked and still hold.

---

## Widening Record

| Widened to | Why |
|---|---|
| `docker/root/etc/s6-overlay/s6-rc.d/init-…-config/run` (whole file), `svc-…/finish`, `privilege-decision.sh:54-91` | Effective privilege outranks the Dockerfile (sanctum method note). Needed to score RT-3/RT-8/RT-12. |
| `docker/docker-compose.yml` (whole), `docker/README.md:44-85,188,208` | EC-001 follow-up from the E011 epic closure; the compose file is in S01-004's scope. |
| `docs/operational.md:86-96,130-140,410-420`, `docs/adr/0045-*.md:127-172` | Checked the documented trust assumptions (output-dir writers, stderr carve-out, proxy allowlist) against the code. |
| `libs/legacy_settings.py`, `libs/suggest.py` (whole) | New modules that read the environment and config files; checked for value leakage and unsafe YAML loading. |
| `.github/workflows/*.yaml` trigger blocks | To see when the new `pip-audit` gate runs; nothing reportable without speculating. |

Not read: test files (the behaviour was reached by executing the code instead), `poetry.lock`.

## Re-analysis Note (zero CRITICAL/HIGH)

The scope has no authentication code and no network listener; authority comes from filesystem modes and the Docker socket. A second pass covered: (1) container labels as untrusted input to the restart path (RT-10, clean); (2) a hostile second resolver or wildcard entry claiming another domain's files through `__owners`. The winner is still a key Traefik generated, so there is no key substitution. (3) TOCTOU on the run-mode state files (RT-12, clean); (4) the new parse-on-compare surface (RT-4, demonstrated but gated on output-dir write access); (5) failure-mode recovery of the new "only on change" contracts (RT-1 and RT-2, the most serious findings). No finding reaches HIGH without breaking the documented trust boundary on `/data`, `/config` or the output directory. The ratings follow that boundary.

## Platform Best Practices

The research cache was fresh (`container-and-key-material.md` and `ci-cd-github-actions.md`, both 2026-10-06, within the 30-day TTL), so no live research was run. Results: key and PFX mode 0600 is compliant (CIS Docker / TLS key handling). The `docker.sock` guidance is non-compliant in one sample (RT-3) and in the proxy allowlist (RT-8). Running as root whenever restarts are enabled remains the accepted ADR-0030 position; RT-8 shows a configuration where that root is not needed.

## Executive Summary

This review covered the E014 sprint-01 working-tree diff: the Docker SDK 7.2 restart path with mtime-versus-`StartedAt` restart rules and deferred restarts; the PKCS12 build-compare-write pipeline; CA-agnostic ACME parsing; settings, CLI and legacy-name handling; s6 run-once/watch lifecycle scripts; and dependency gates. The stack is a Python CLI in a LinuxServer/s6 image, with trust boundaries at `acme.json`, `/config`, the output volume and the Docker socket. Overall risk is **MEDIUM**: no CRITICAL or HIGH findings. Path containment, key-file modes, secret redaction in dumps, CLI-context isolation and run-mode state integrity were all verified by execution or by reading the code. The most dangerous finding is **RT-2**. A partial write of a rotated key makes the new restart-on-every-pass rule restart consumers into a mismatched key/certificate pair, and in watch mode nothing repairs that until Traefik next writes the store, which can take days. **RT-1** is the close second: "only on change" makes a single hook failure permanent. The most important recommendation is to give the post-export hook and partial exports the same file-derived recovery property ADR-0045 already gives restarts. Recover the hook from a success stamp, and keep a domain with an incomplete artifact set out of the restart rule while its write is retried.

## Closure triage (sprint closure, 2026-10-11)

| Finding | Severity | Disposition |
|---|---|---|
| RT-1 | MEDIUM | Deferred: BL-E014-055 (hook retry needs a design: stamp file or equivalent) |
| RT-2 | MEDIUM | Deferred: BL-E014-056 (export atomicity across key/cert pair needs a design) |
| RT-3 | MEDIUM | Fixed in closure: `docker/docker-compose.yml:18` carries the host-root warning; pinned by `tests/test_settings_surface.py::test_every_docker_socket_mount_carries_the_host_root_warning` (scope globbed over `docker/**`, root `*.md`, `docs/**/*.md`; fail-first confirmed on the old line 18) |
| RT-4 | LOW | Deferred: BL-E014-057 |
| RT-5 | LOW | Deferred: BL-E014-058 |
| RT-6 | LOW | Resolved by closure fix iteration 1 (ADV-3, `post_export._stderr_summary`) |
| RT-7 | LOW | Deferred: BL-E014-059 |
| RT-8 | LOW | Deferred: BL-E014-060 |
| RT-9 | LOW | Duplicate of BL-E014-016 (run-once exit code does not reflect export failures); not re-filed |
