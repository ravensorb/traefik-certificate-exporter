# RED TEAM FINDINGS REPORT

**Scope:** Epic `E011` — epic-level closure (all 4 sprint-01 stories together): CI verification + release evidence; repo governance / vendored-tree integrity; CLI + settings hardening; export-pipeline correlation IDs, safe shutdown, atomic writes.
**Date:** 2026-10-06
**Analyst:** Red Team Agent (l3io-sec-redteam)
**Target:** `traefik-certificate-exporter` — Python/Poetry CLI + LinuxServer/s6 container that parses Traefik's ACME JSON store and exports PEM/PKCS12 key material, optionally restarting labeled Docker containers and sending Apprise notifications.

**Relationship to the sprint-01 closure pass:** sprint-01's own red-team pass (`_bmad-output/implementation-artifacts/epic-011/sprint-01/closure/redteam-report.md`) found 0 Critical / 4 High / 5 Medium / 5 Low / 3 Observation (IDs RT-001..RT-017). Per `fix-verification.md`, RT-001 through RT-005 are **RESOLVED** and independently re-confirmed in this pass by reading the live code (path-escape validation, `0o600` key-bearing modes, metadata-inheritance refusal, SIGTERM handling, and the logging-config auto-discovery half of RT-004). Those are **not re-raised** here. RT-006 through RT-009 and the un-fixed halves of RT-004 (root execution; `postexportcommand`/`.env`/`config.yaml` reachable from the `/config` volume) remain open exactly as previously described and documented (`docs/operational.md` §"Trust boundary: `/config` and `settings.postexportcommand`") — also **not re-raised** as new findings; they are carried forward as known, accepted, documented risk only (see "Carried-forward residual risk" at the end).

This pass's mandate was to look at the **combined, final surface** the four stories produced together, not to repeat the per-story review. Three findings below are new to this pass.

---

## SEVERITY SUMMARY

```
  CRITICAL:    0
  HIGH:        1
  MEDIUM:      2
  LOW:         0
  OBSERVATION: 2
```

---

## SCOPE AND SURFACE MAP (internal scaffolding, epic-wide)

**Entry points**
- `acme.json` files under `dataPath` — the only data-plane input, fully trusted, now with a whitelist + containment gate on everything joined into a path (story 4).
- Process `argv` (strict parse in `main()`, lenient parse at import — story 3), environment variables, `/config/config.yaml`, `$CWD/.env`/module `.env`, confuse's user-config dir. `logging.yaml` auto-discovery from CWD was removed (story 4); `config.yaml`/`.env` auto-discovery from CWD was not, and is documented instead as a trust requirement on the `/config` mount.
- Docker daemon socket (outbound), gated by a container label and by `restartContainers`.
- Apprise destination URLs (outbound), post-export hook (`subprocess.run`, `shell=False`, fixed 30s timeout, argv wholly operator-configured).

**Trust boundaries**
1. Traefik's ACME store → exporter: now validated against a DNS-label whitelist and a resolved-path containment check before any join (RT-001 fix), re-confirmed by direct testing this pass (see Finding M2 for what still reaches the log sink unsanitised).
2. Operator-mounted `/config` volume → exporter process configuration (documented as trusted; not enforced at runtime — Finding M1).
3. Exporter (root, unchanged this epic) → `/certs`, with per-content mode floors (`0o600` for key-bearing files, umask-derived for public material) and metadata-inheritance refusal for foreign UID/overly-permissive existing files.
4. Exporter → Docker socket. This is the boundary this pass widened into furthest, because all three code changes that reduced the attack surface elsewhere (path validation, key-file modes, CWD auto-discovery removal) leave this boundary's documented mitigation unexamined — and it does not hold (Finding H1).

**Data flows (sensitive)**
Unchanged in shape from the sprint pass: `acme.json` → `__exportCertificate` → `_atomic_write*` → `/certs/**`. New this epic: every rejected/invalid domain or resolver name is logged verbatim before the function returns (Finding M2).

**Auth checkpoints**
Still none — no network listener, no identity, no authorization decision anywhere in the four stories' combined code. The equivalent controls remain filesystem modes and Docker-socket authority. Per standing order, this is stated explicitly rather than left silent: auth findings genuinely do not apply to this scope.

**Persistent state**
Unchanged: `/certs` exports, `.{name}.*.tmp` staging (reaped after 1h — story 4), `traefik-certificate-exporter.log`, `/config/config.yaml`.

**AI/ML components (poisoning cross-cut)**
No runtime model. The repo's vendored `.agents/`/`.claude/`/`_bmad/` trees remain the executable surface the cross-cut applies to. Story 2 (this epic) added a payload-manifest hash check and tightened the citation in `.github/CODEOWNERS` (ADR-0027), but deliberately did not close the manifest-coverage gap — `test_the_vendored_integrity_guard_records_what_it_cannot_verify` requires the gap to stay **stated**, not fixed. No new AIP finding: the compensating control (hash-matched trees + an honest, test-enforced coverage caveat) is unchanged in strength by this epic and was already credited in the sprint pass as RT-006.

**What was widened to, and why** — seeds were the epic diff (`2213e42..434dc87`), the 4 story files, ADRs 0023–0027, and the sprint-01 closure report for context. Widened to: `docker/README.md` and the `docker-compose` samples it embeds (the sprint pass read `docs/operational.md`'s socket guidance but not the shipped compose examples that demonstrate it — both needed to be read together to see the guidance is consistent *and consistently wrong*); live execution of the rejected-name code path against `.venv/bin/python` to confirm log/terminal injection rather than inferring it from the regex; and a live web search for current, dated guidance on Docker-socket `ro` mounts, cached to `research-cache/container-and-key-material.md`.

---

## FINDINGS

### HIGH

#### EC-001 — Shipped documentation and compose samples claim a read-only Docker-socket mount narrows the exporter's privilege; it does not, and the claim is false confidence on the one boundary every other epic-01 hardening pass left untouched
**Lens:** DAR, PBR
**Component:** `docs/operational.md` ("Runbook: container not restarting after cert change", step 3) and `docker/README.md` (both `docker-compose` examples, lines ~178 and ~197), consumed by `libs/docker.py::DockerManager.restartLabeledContainers`.

**Attack path:**
1. An operator follows either shipped `docker-compose` sample verbatim: `/var/run/docker.sock:/var/run/docker.sock:ro`, captioned "Only needed if you are going to be restarting containers" — read as "the ro flag limits what this grants."
2. `docs/operational.md`'s own runbook reinforces the belief explicitly: "read-only is sufficient for the `docker` SDK's list/restart calls over the socket."
3. This is not how the Docker Engine API works. The `ro` mount flag is a filesystem-level restriction on replacing/unlinking the socket special file; it has no effect on what requests a connected client may send over that socket. `docker.from_env()` inside this container (or any process that compromises it — e.g. via the still-open `postexportcommand`/`.env` channel documented as accepted risk) can create a privileged container with `-v /:/host`, exec into any container on the host, or otherwise obtain host root, exactly as if the mount were `rw`. This is long-established, widely documented Docker security guidance (CIS Docker Benchmark; OWASP Docker Security Cheat Sheet; Docker's own security docs) — not a theoretical edge case.
4. The result: every operator who deploys from these samples and reads this runbook believes they have granted a narrow "list and restart" capability. They have granted host root, with no code in this project doing anything to narrow it (`restartLabeledContainers` itself has no endpoint allowlist — it calls the general `docker-py` client).

**Impact:** Operators following the project's own shipped guidance systematically under-provision their threat model for this container. Combined with the already-documented, already-accepted `postexportcommand`/`/config` RCE channel, a compromise of this single low-profile sidecar container becomes host-root compromise, while every piece of project documentation available to the operator says otherwise. This is the single most dangerous finding of this pass precisely because it is a documentation defect sitting underneath a code posture (least-privilege container, no identity, filesystem-mode discipline) that everything else in this epic worked hard to get right.

**Recommendation:** Correct both `docker/README.md` samples and the `docs/operational.md` runbook to state plainly that mounting `docker.sock` — `ro` or `rw` — grants host-root-equivalent access to this container, with no narrowing from the `ro` flag. If a narrower grant is actually wanted, document (or better, ship) a socket-proxy pattern (e.g. Tecnativa/docker-socket-proxy or an equivalent allowlisting proxy restricted to `GET /containers/json` and `POST /containers/{id}/restart`) as the only mount compose examples should show by default. At minimum, strike "read-only is sufficient" from the runbook; it is the exact sentence an operator will quote back when asked why the socket is exposed.

---

### MEDIUM

#### EC-002 — The documented `/config` trust-boundary invariant has no runtime check; the process will happily start and run against a world-writable mount
**Lens:** DAR, CHA
**Component:** `docs/operational.md` §"Trust boundary: `/config` and `settings.postexportcommand`"; `libs/settings.py::SettingsManager.loadFromFile`; `app.py::_run`.

**Attack path:** The documented mitigation for the still-open half of RT-004 (`.env`/`config.yaml` auto-discovery from CWD, `postexportcommand` execution) is entirely a documentation instruction: "`/config` is a trusted mount... must be root-owned and must not be world-writable." Nothing in `loadFromFile` or `main()`/`_run()` checks this before reading `.env`/`config.yaml` from CWD or before honouring `postexportcommand`. A deployment that violates the documented invariant — a common failure mode: Docker Desktop bind mounts on non-Linux hosts default to permissive modes, an NFS-backed volume with squashed UIDs, an operator who ran `chmod -R 777` on a compose project's data directory to fix an unrelated permission error — silently falls into the exact RCE condition the documentation warns about, with no log line, no refusal to start, and no signal to the operator that the invariant they were told to maintain has been violated. This is the same class of gap the vendored-tree integrity guard (story 2) explicitly refuses to leave undocumented — "a gate that documents its own coverage gap is still a gap" — applied to a runtime invariant instead of a CI one.

**Impact:** The single code-level control this epic chose *not* to add (in favour of documentation) has no fallback if the documentation is not read, is out of date relative to the deployment, or the deployment drifts after initial setup. Defense-in-depth here is one layer deep, and that layer is prose.

**Recommendation:** At minimum, log a WARNING at startup if the resolved `/config` directory (or the specific `.env`/`config.yaml` files within it) is group- or world-writable (`os.stat(...).st_mode & (stat.S_IWGRP | stat.S_IWOTH)`), naming the file and the specific mode found — mirroring the pattern `_inheritable_metadata` already uses for export targets. This converts a silent trust assumption into an observable one without changing default behaviour, and gives an operator who *did* misconfigure the mount a concrete signal instead of a quiet RCE surface.

#### EC-003 — Rejected ACME domain/resolver names reach the log sink unsanitised: ANSI terminal-escape and newline (log-forging) injection from the one data-plane input, demonstrated by execution
**Lens:** EXT, CHA
**Component:** `libs/certificate_exporter.py::AcmeCertificateExporter.__exportCertificate` (the `self.__logger.error(f"Refusing to export domain '{name}': ...")` and `f"Refusing to export: resolver name '{resolverName}' ..."` lines), consumed by `coloredlogs`/console and the rotating file handler (`logging_utils.py`, `logging.yaml`).

**Attack path (verified by execution):**
1. The sprint-01 fix correctly rejects any `name`/`resolverName` that is not a safe path component before it is ever joined into a filesystem path — but the *rejected, raw* value is still interpolated directly into the log message that reports the rejection.
2. Reproduced locally: a crafted `domain.main` of `"evil\x1b[31mFAKE ERROR\x1b[0m\ninjected-line"` is correctly refused as a path component (`_is_safe_path_component` returns `False`, no file is written), but the resulting log line renders as two physical lines on a console/log file, one of them coloured as a terminal-escape-driven fake error, and both carrying content the attacker chose:
   ```
   Refusing to export domain 'evilFAKE ERROR
   injected-line': not a valid certificate name for a filesystem path
   ```
   (the escape codes are not visible in this transcript; on an ANSI-rendering terminal they recolour and can reposition/clear subsequent output).
3. The same value also reaches the structured JSON file sink as the literal (unexecuted, but still attacker-chosen) string in the `message` field, which is a log-forging primitive against any downstream tooling that parses `message` as free text (e.g. a dashboard that greps for `ERROR` lines) rather than the JSON envelope.

**Impact:** The actor who can write to `dataPath` (already a fully trusted, already-exploited boundary for RT-001) can inject fabricated log lines — including ones styled to look like a different severity or a different component — into both the console stream an operator watches with `docker logs` and the rotating JSON log file this project's own documentation recommends `jq`-filtering by `correlation_id` for incident tracing. This does not grant code execution, but it directly undermines the observability story this epic invested in (ADR-0023's correlation IDs exist specifically so an operator can trust what the log says happened during a given pass); an attacker able to reach this boundary can make that trust misplaced.

**Recommendation:** Strip or escape control characters (at minimum `\r`, `\n`, and the ESC/CSI sequence family `\x1b[...`) from `name`/`resolverName` before they are interpolated into any log message, not only before they are used as a path component — a single `_sanitize_for_log(value)` helper applied at the two call sites above (and anywhere else rejected ACME-sourced values are logged) closes this without weakening the path-safety regex itself. Consider doing this at the logging layer (a `logging.Filter` that scrubs control characters from `record.msg`/`record.args`) so it covers this value and any future one that reaches a log line from the same untrusted source.

---

### OBSERVATIONS

#### EC-OBS-001 — `Apprise.add()` failure is attributed by `urls.index(url)`, which reports the wrong index for a duplicated destination URL
**Lens:** ABU
**Component:** `libs/notify.py::_notify`.

If the same Apprise URL is configured twice and is rejected, `urls.index(url)` always reports the *first* occurrence's index, mislabeling which configured entry actually failed. Not a vulnerability — a diagnostic-accuracy nit surfaced while reviewing the notification path for the credential-in-value handling this epic's settings redaction work also touches. Fix opportunistically (`enumerate(urls)` instead of a post-hoc `.index()` lookup) if this file is touched again.

#### EC-OBS-002 — AI poisoning cross-cut: unchanged this epic, explicitly re-confirmed rather than skipped
**Lens:** AIP
**Component:** `.github/CODEOWNERS`, `tests/ci/test_gates.py::test_the_vendored_integrity_guard_records_what_it_cannot_verify`.

Per standing order, the cross-cut was run rather than assumed clean given it applied last sprint. Story 2's ADR-0027 citation fix and the payload-manifest hash check are unchanged in their actual security contribution this epic (same coverage gap, now correctly attributed to CODEOWNERS instead of a file that never made the claim). No new finding; recorded so this pass's AIP coverage is auditable rather than silent.

---

## CARRIED-FORWARD RESIDUAL RISK (context only — not counted in the severity summary above)

These remain open, exactly as sprint-01's closure pass left them, and are **not** re-raised as new findings in this report:
- Process runs as root unconditionally (`s6-setuidgid root` in `svc-traefik-certificate-exporter/run`), despite the image advertising PUID/PGID.
- `settings.postexportcommand` and `.env`/`config.yaml` auto-discovery from the `/config` CWD remain live RCE-equivalent configuration, now explicitly documented as a trust requirement on the mount rather than closed in code (see EC-002 above for the new angle this pass adds on top of that).
- `acme.json` is read fully into memory with no size cap and `b64decode` runs without `validate=True` (memory-exhaustion DoS from the same trusted-but-unvalidated input).
- Docker-socket label-driven restarts (`DOCKER_LABEL`) let any container on the host opt itself into being restarted by this process with no ownership check beyond the label string (RT-009's scope; EC-001 above is the adjacent-but-distinct documentation-accuracy finding about the socket mount itself).
- Tag-pinned (not SHA-pinned) GitHub Actions, including third-party `LiquidLogicLabs/*` actions.
- The vendored `.agents/`/`.claude/`/`_bmad/` trees are excluded from both linting and secret scanning by design, with partial (manifest-hash-based) integrity coverage honestly stated as partial.

---

## EXECUTIVE SUMMARY

This pass reviewed the combined surface of Epic E011's four sprint-01 stories as they now sit together in the final codebase — CI/release-evidence hardening, vendored-tree governance, CLI/settings hardening, and the export pipeline's correlation-ID/shutdown/atomic-write work — rather than re-running the sprint-scoped review each story already received. The sprint-01 fixes (path-escape validation, 0600 key-bearing file modes, metadata-inheritance refusal, and SIGTERM handling) were independently re-confirmed as resolved by reading the live code, and are not re-litigated here. Overall risk posture for the **new** findings in this pass is **HIGH**, carried by one finding: the project's own shipped `docker-compose` samples and operational runbook assert that a read-only Docker-socket mount narrows this container's privilege to "list/restart," when in fact any client connected to `docker.sock` — `ro` or `rw` — has host-root-equivalent control, a well-established and specifically-cited fact this epic's otherwise careful hardening work (path validation, key-file permissions, CWD auto-discovery removal) did not touch. The most important recommendation is to correct that documentation immediately — it is the one place this project actively tells an operator that a boundary is safer than it is — and, longer-term, to replace the direct socket mount in the shipped samples with an endpoint-restricted proxy. The two Medium findings (no runtime check of the documented `/config` trust invariant; log/terminal injection via rejected ACME names) are real but lower-impact gaps in defense-in-depth and observability integrity respectively, both demonstrated by direct execution rather than inferred.
