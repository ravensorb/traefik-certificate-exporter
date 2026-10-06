# RED TEAM FINDINGS REPORT

**Scope:** Epic `E011` / Sprint `01` — "Residual Backlog Cleanup" (4 stories: CI verification + release evidence; repo governance / vendored-tree integrity; CLI + settings hardening; export-pipeline correlation IDs, safe shutdown, atomic writes)
**Date:** 2026-10-06
**Analyst:** Red Team Agent (l3io-sec-redteam)
**Target:** `traefik-certificate-exporter` — Python/Poetry CLI + LinuxServer/s6 container that parses Traefik's ACME JSON store and exports PEM/PKCS12 key material, optionally restarting labeled Docker containers and sending Apprise notifications.

---

## SEVERITY SUMMARY

```
  CRITICAL:    0
  HIGH:        4
  MEDIUM:      5
  LOW:         5
  OBSERVATION: 3
```

---

## SCOPE AND SURFACE MAP (internal scaffolding)

**Entry points**
- `acme.json` files under `dataPath` (glob `fileSpec`, default `*.json`) — parsed on start-up sweep and on every watchdog create/modify event. **The only data-plane input, and it is fully trusted.**
- Process `argv` (now strictly parsed — story 3), environment variables (`TRAEFIK_CERTIFICATE_EXPORTER_*`), `/config/config.yaml`, `$CWD/.env`, the packaged module `.env`, confuse's user-config dir, and `$CWD/logging.yaml`.
- Docker daemon socket (outbound) via `docker.from_env()`.
- Apprise destination URLs (outbound), post-export hook (`subprocess.run`, shell=False).

**Trust boundaries**
1. Traefik's ACME store → exporter. No schema validation, no domain-name validation, no size bound.
2. Operator-mounted `/config` volume → exporter process **configuration and logging-framework configuration** (which is code).
3. Exporter (running as **root**, see RT-002/RT-004) → `/certs` bind mount shared with consuming services.
4. Exporter → Docker socket: host-root-equivalent authority, gated only by a container label.

**Data flows (sensitive)**
`acme.json` (b64 private keys) → `__exportCertificate` → `_atomic_write_text/_bytes` → `/certs/**` PEM + PKCS12 → consumed by other containers. Secondary: `pkcs12passphrase` and Apprise URLs → settings dumps (redacted, verified) and → `os.environ.copy()` of the post-export child process (not redacted — by necessity).

**Auth checkpoints**
There are none. This is a local-trust daemon: no network listener, no identity, no authorization decision anywhere in the code. Per the skill's standing order on auth findings — **auth findings genuinely do not exist in this scope**, because no component in scope performs an identity or access-control decision. The equivalent controls here are *filesystem* authorization (file modes/ownership) and *socket* authorization (Docker), and both produced findings (RT-002, RT-003, RT-009).

**Persistent state**
`/certs` exports (now replaced inode-by-inode), `.{name}.*.tmp` staging files, `traefik-certificate-exporter.log` (rotating, written to CWD = `/config`), `/config/config.yaml`.

**AI/ML components**
No model at runtime. However the repo vendors ~2,364 agent-instruction files under `.agents/` and `.claude/` that agents with write access execute as instructions — the AI poisoning cross-cut applies there (RT-006).

**What I widened to, and why** — seeds were the sprint diff, four story files, and ADRs 0023–0027. I widened to: `libs/settings.py` (story 3's redaction mechanism is there but the file is *not* in the sprint diff — the claim had to be verified against the live code), `libs/certificate_exporter.py` in full (the atomic-write helper's callers and the ACME parse that feeds it), `libs/docker.py`, `libs/post_export.py`, `libs/notify.py`, `libs/logging_utils.py` + `logging.yaml` (sinks for the redacted values), `docker/Dockerfile` **and `docker/root/etc/s6-overlay/**/run`** (the Dockerfile alone does not say which UID the process runs as — the s6 run script does, and it changes the severity of two findings), `tests/ci/test_gates.py` headers, and `.github/workflows/*.yaml` (story 1 is a CI-hardening story). Two live findings were confirmed by execution against the project venv rather than by reading: RT-001 and RT-002.

---

## FINDINGS

### HIGH

#### RT-001 — ACME `domain.main` is used unvalidated as a filesystem path: absolute-path/traversal escape from `outputPath`, writing attacker-controlled bytes as root
**Lens:** EXT, DAR
**Component:** `libs/certificate_exporter.py::AcmeCertificateExporter.__exportCertificate` (lines ~180–270), feeding the sprint's new `_atomic_write_text` / `_atomic_write_bytes`.

**Attack path (verified by execution, not inference):**
1. Obtain write access to any file matched by `fileSpec` under `dataPath` (shared `/data` mount, a compromised Traefik, a backup-restore path, or any sidecar with the volume mounted).
2. Set the certificate's name field to an absolute path or a traversal, e.g. `{"Certificates":[{"domain":{"main":"/etc/s6-overlay/s6-rc.d/svc-x/run"}, "key":"<b64>", "certificate":"<b64>"}]}`.
3. The only sanitation applied is `name.removeprefix("*.")`. In non-flat mode the code does `directory = directory / name`; `pathlib` discards the left operand when the right is absolute, so `Path("/certs") / "/etc/..."` is `/etc/...`. `directory.mkdir(parents=True)` then creates it and five files are written there.

Reproduced locally: with `outputPath=/tmp/out` and `main="/tmp/escape/pwned"`, the exporter reported `processed: ['/tmp/escape/pwned']` and wrote `privkey.pem, cert.pem, chain.pem, fullchain.pem, cert.pfx` into `/tmp/escape/pwned/` at mode `0644`. Relative traversal (`../../`) escapes identically.

**Impact:** Arbitrary directory creation and arbitrary file write, with partially attacker-controlled content (the PEM body is whatever was placed in the ACME file), **as root inside the container** (`docker/root/etc/s6-overlay/s6-rc.d/svc-traefik-certificate-exporter/run` runs `s6-setuidgid root`). That is container-root code execution via s6 service scripts, cron drop-ins, or overwriting `/app/.venv` content; and on any host path bind-mounted into the container, it reaches the host. It also silently relocates private key material outside the directory the operator believes it is confined to.

**Recommendation:** Validate `name` before it is ever joined to a path: reject anything that is not a syntactically valid DNS name (`^(?!-)[A-Za-z0-9-]{1,63}(\.[A-Za-z0-9-]{1,63})*$` after the `*.` strip), and in addition resolve the candidate directory and assert `Path(outputPath).resolve() in candidate.resolve().parents`. Do the same for `resolverName` (it is also joined into the path, and also comes from the JSON). Fail the domain, log it at ERROR, and continue the sweep — the existing per-domain `except` already provides that shape.

---

#### RT-002 — Exported private keys and unencrypted PKCS12 bundles are written world-readable (0644); the new atomic-write helper codifies a umask-derived mode with no floor for key material
**Lens:** DAR, PBR
**Component:** `libs/certificate_exporter.py::_default_file_mode` / `_atomic_write` (new this sprint, ADR-0023 Decision 3 / ADR-0024).

**Attack path:**
1. Run the shipped image with the documented `/certs` bind mount (default umask 022).
2. Export any certificate. Verified locally: `privkey.pem 0o644`, `cert.pfx 0o644`, same for the flat-mode `.key`.
3. Any other container or host user that can see the mount reads the TLS private key. With no `pkcs12passphrase` configured — the documented default, `serialization.NoEncryption()` — the `.pfx` is a world-readable unencrypted key bundle too.

**Impact:** Full compromise of every exported TLS identity to any local reader: passive decryption where PFS is not negotiated, and impersonation of every exported domain. This is the single highest-value asset the project handles.

**Why it belongs to this sprint:** ADR-0023 explicitly reasoned about modes ("a private key must not be loosened, and a public chain must not be tightened") and the implementation resolved that tension by reproducing `open(path,"w")` semantics — `0o666 & ~umask` — for *all five* outputs. The decision was made deliberately and is wrong for the two that contain a private key. CIS guidance is `0600` for TLS private keys; `0644` is explicitly non-compliant (`https://www.cisecurity.org/benchmark/docker`).

**Recommendation:** Split the mode policy by content, not by umask: `privkey.pem` / `*.key` / `*.pfx` → `0600` (or `0640` with an explicit configurable group), chain/cert/fullchain → the current umask-derived mode. Add a `SECRET_OUTPUT_MODE` constant next to `_DEFAULT_FILE_MODE` and pass an explicit `mode=` into `_atomic_write` from the key-bearing call sites. Document the group-sharing recipe for services that need to read the key as a different UID, so operators do not reach for `chmod 644` themselves.

---

#### RT-003 — `_atomic_write` adopts the mode *and (as root) the ownership* of whatever file already occupies the target path
**Lens:** INS, CHA
**Component:** `libs/certificate_exporter.py::_atomic_write` (new this sprint).

**Attack path:**
1. A low-privileged principal with write access to `/certs` (a sidecar container sharing the mount, an unprivileged user on the host side of the bind mount) pre-creates `/certs/example.com/privkey.pem` owned by itself with mode `0666` — or simply `chmod 666` the existing one.
2. At the next renewal `_atomic_write` does `existing = target.stat()`, takes `mode = existing.st_mode & 0o7777`, then `os.chown(tmpPath, existing.st_uid, existing.st_gid)` and `os.chmod(tmpPath, mode)` before `os.replace`.
3. Because the process runs as root, the `chown` **succeeds** — the comment "an unprivileged process cannot give a file away" does not hold for the shipped runtime profile. The freshly issued private key is handed to the attacker's UID at `0666`, permanently, and re-established on every renewal.

**Impact:** A persistent, self-healing private-key disclosure channel that survives operator remediation: an admin who runs `chmod 600` on the key sees it reverted to `0666` at the next export, because the helper now treats the on-disk ACL as the source of truth. Attribution also breaks — the key file is owned by the attacker, not by the exporter.

**Recommendation:** Only inherit owner/mode when the existing file is already owned by the process EUID *and* its mode is not more permissive than the policy floor from RT-002; otherwise write the policy mode and log a WARNING naming the file ("refusing to inherit permissive mode 0666 from an existing export"). Also `os.lstat` rather than `stat` so a symlink planted at the target is detected instead of followed.

---

#### RT-004 — `/config` is simultaneously an operator-writable volume, the process working directory, and a code-load path (`logging.yaml` → `dictConfig`, `.env`/`config.yaml` → `postexportcommand`)
**Lens:** EXT, INS, DAR
**Component:** `docker/Dockerfile` (`WORKDIR /config`, `VOLUME /config`), `libs/logging_utils.py::setup_logging`, `libs/settings.py::loadFromFile`, `libs/post_export.py`.

**Attack path:**
1. Anything that can write one file into `/config` (a compromised neighbouring container sharing the volume, a stale 0777 host directory, a misconfigured file-manager UI) drops either:
   - `logging.yaml` — `setup_logging` prefers `$CWD/logging.yaml` over the packaged copy, loads it with `yaml.safe_load` (which blocks YAML object construction) and then hands it to `logging.config.dictConfig`, which resolves arbitrary dotted names for `class:`/`()` factory keys and instantiates them with attacker-chosen arguments. `safe_load` does not make `dictConfig` safe; or
   - `.env` / `config.yaml` with `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND=<anything>` — `run_post_export_command` executes it (`shell=False`, but the argv is wholly attacker-chosen) after the next export pass, which `RUNATSTART=true` guarantees on the next restart.
2. Either path executes as **root**, and where `restartcontainers` is in use the process also holds the Docker socket — host root.

**Impact:** Container-root code execution from a single file write into a volume operators routinely treat as unprivileged data, escalating to host root through the Docker socket. No configuration change is needed by the operator; both are default discovery behaviours.

**Recommendation:** (a) Do not auto-discover logging config from CWD — honour only the explicit `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_CFGFILE`, and prefer the packaged copy otherwise; at minimum refuse a CWD config whose owner is not the process EUID. (b) Stop running the service as root: replace `s6-setuidgid root` with the LinuxServer PUID/PGID account the image already provisions, and document the `/certs` group model that makes that work. (c) Document `/config` as a trusted, root-owned, non-world-writable mount in `docs/operational.md`, and state that `postexportcommand` is remote-code-execution-equivalent configuration.

---

### MEDIUM

#### RT-005 — Story 4's "safe shutdown" covers SIGINT only; `docker stop` (SIGTERM) bypasses `cancel()` entirely
**Lens:** CHA, DAR
**Component:** `app.py::main` (`except KeyboardInterrupt: observer.stop(); event_handler.cancel()`), ADR-0026.

**Attack path:** Not an attack so much as the normal production path. The container's stop signal is SIGTERM; Python's default SIGTERM disposition terminates the process without raising `KeyboardInterrupt`, so `event_handler.cancel()` never runs, `shuttingDown` is never latched, the debounce timer is never cancelled, and the bounded 5s join never happens. The entire shutdown design tested in story 4 is reachable only from an interactive Ctrl-C — which the shipped image never experiences. A `kill -TERM` during a drain also skips the `BaseException` unwind in `doTheWork`, leaving no "will not be exported by this process" warning for the operator to find.

**Impact:** The observability and clean-abandonment guarantees the sprint paid for are absent in the deployed configuration; an export pass can be lost silently at every redeploy, and the ADR-0026 invariant ("no drain runs after 'stopping'") is unenforced for the only shutdown that actually occurs. Mitigated to data-loss-only (not corruption) by the atomic writes.

**Recommendation:** Install `signal.signal(signal.SIGTERM, ...)` (and SIGINT) handlers in `main()` that run the same `observer.stop(); event_handler.cancel(); observer.join()` sequence, then exit; keep the `KeyboardInterrupt` arm for the non-container path. Add a test that sends SIGTERM to a child process and asserts the "Shutdown requested" line appears.

#### RT-006 — 2,222 of 2,364 vendored agent-instruction files are verified against nothing; the byte-identical check is defeated by any commit that edits both trees
**Lens:** INS, AIP, DAR
**Component:** `.github/CODEOWNERS` framing (ADR-0027), `tests/ci/test_gates.py::test_the_vendored_trees_match_the_manifests_their_installer_shipped` / `..._are_byte_identical_copies_of_each_other`.

**Attack path:** A contributor (or a compromised agent with write access — these trees are agent-writable by design) edits `.agents/skills/<x>/SKILL.md` and makes the identical edit to `.claude/skills/<x>/SKILL.md`. Both integrity gates pass: the file is named by no `payload-manifest.json`, so there is no hash to compare, and the two copies still match each other. The trees are excluded from the linting gates and from the secret scanner (RT-008). The injected text is then read as instructions by every agent that loads that skill — including agents that hold write access to source and CI configuration.

**Impact:** Indirect prompt injection with a persistent, reviewed-looking foothold: the poisoned instruction can direct future agent runs to weaken gates, exfiltrate repository content through a "research" step, or introduce code changes that a human reviewer attributes to the agent's own judgement. The project's own gate text (`test_the_vendored_integrity_guard_records_what_it_cannot_verify`) documents the gap honestly, which is good practice, but documenting a hole is not closing it.

**Recommendation:** Generate a repository-side lockfile (`vendored-trees.lock`) of SHA-256 for **every** file in both trees at install time, commit it, and have the gate diff the trees against it; require a separate, explicitly-labelled commit (`chore(vendor): refresh skills <release>`) to regenerate it, so an in-band edit fails CI instead of passing two checks. Pair it with a CODEOWNERS review requirement that cannot be satisfied by the agent account.

#### RT-007 — Third-party GitHub Actions are pinned to mutable tags while one action is SHA-pinned
**Lens:** PBR, INS
**Component:** `.github/workflows/dev.yaml`, `ci.yaml`, `publish-image.yaml`.

**Attack path:** `LiquidLogicLabs/git-action-docker-metadata@v6`, `LiquidLogicLabs/git-action-ca-certificate-import@v3`, `docker/setup-buildx-action@v4`, `docker/login-action@v3`, `docker/setup-qemu-action@v3` and `actions/checkout@v7` are referenced by tag. An upstream maintainer compromise (or a repointed tag) executes attacker code inside the publish jobs, which hold `packages: write`, `id-token: write`, `secrets.FORGE_PACKAGE_TOKEN` and `secrets.GITHUB_TOKEN`. `pypa/gh-action-pypi-publish@dc37677b…` in the same file *is* SHA-pinned, so the discipline exists and was applied unevenly — the weakest reference in a job sets the trust level of the whole job.

**Impact:** Supply-chain takeover of the published wheel and image, and theft of the package-index token — the exact failure mode of the 2025-26 `tj-actions/changed-files` class of incidents.

**Recommendation:** Pin every non-local `uses:` to a full 40-character commit SHA with a trailing `# vX.Y.Z` comment, and let Dependabot update them; add a `tests/ci` gate asserting that no `uses:` outside `./.github/` matches `@v?\d`. Reference: GitHub Actions security hardening guidance and OpenSSF Scorecard `Pinned-Dependencies`.

#### RT-008 — The secret scanner's vendored-tree exclusion is an uncovered commit path for credentials
**Lens:** INS
**Component:** `tests/ci/test_gates.py::test_the_secret_scanner_and_pre_commit_exclude_the_same_vendored_trees`.

**Attack path:** The gate asserts that the secret scanner and pre-commit exclude the *same* vendored trees — i.e. the exclusion is enforced as a contract. A credential placed in `.agents/**` or `.claude/**` (a plausible-looking example API key in a skill's `assets/`, say) is therefore never scanned, in the tree or in history, and reaches the public repository.

**Impact:** Silent credential disclosure through the one part of the tree the project has deliberately removed from scanning; also the obvious staging location for an insider who knows the exclusion list.

**Recommendation:** Keep the *lint* exclusion, drop the *secret-scanner* exclusion — detect-secrets/gitleaks over these trees costs little and the trees are large, text-heavy, and agent-writable. If baseline noise is the concern, use an allowlist baseline rather than a path exclusion, and let RT-006's lockfile prove the baseline is still accurate.

#### RT-009 — Container restarts are driven by attacker-influenced domain strings over a host-root-equivalent socket
**Lens:** EXT, ABU
**Component:** `libs/docker.py::restartLabeledContainers`, called from `app.py` and `AcmeCertificateFileHandler.__processPath`.

**Attack path:** The restart set is computed as `set(domains).isdisjoint(container.labels[DOCKER_LABEL].split(","))`, where `domains` comes straight from the ACME JSON. An entity that can write the ACME file (RT-001's precondition) enumerates the label values and emits a cert entry whose `main` matches any labeled container, then rewrites the file repeatedly — each write passes the 2s debounce and triggers another restart cycle.

**Impact:** Targeted denial of service against every labeled container (typically the reverse proxy itself, i.e. all ingress), driven by data, with the log line reading like normal operation. The blast radius is bounded only by the label, while the authority held is the full Docker API.

**Recommendation:** Require the restart to follow an export that actually *changed* bytes (compare the new PEM against the file being replaced — `_atomic_write` already stats the target, so the comparison is nearly free), rate-limit restarts per container (e.g. one per `watchInterval`), and document that `restartcontainers: true` grants host-root-equivalent authority so it should be paired with a socket proxy (`tecnativa/docker-socket-proxy` with `POST=1, CONTAINERS=1` only) rather than a raw socket mount.

---

### LOW

#### RT-010 — Process-wide umask probe races concurrent drain threads
**Lens:** CHA. `_default_file_mode()` performs `current = os.umask(0o022); os.umask(current)`. `os.umask` is per-process, and drains run on `threading.Timer` threads; a file created by another thread inside that window gets a mode derived from `0o022` rather than the real umask. The one-shot cache limits it to the first call, and the lock does not help because the racing thread is not inside the lock. **Recommendation:** read the umask once at import time in `main()` before any thread exists, or stop deriving secret file modes from umask altogether (see RT-002), which removes the probe.

#### RT-011 — Abandoned `.tmp` staging files containing key material are never reaped
**Lens:** CHA. `_atomic_write` unlinks its temp file on any exception, but SIGKILL (the end of every `docker stop` that exceeds the grace period — a path story 4 explicitly plans for) leaves `.privkey.pem.<rand>.tmp` in the export directory. They accumulate across restarts, and `os.chmod(tmpPath, mode)` has already widened them to the final mode (0644 today) before `os.replace`. **Recommendation:** sweep `.{name}.*.tmp` in the output directories at start-up, and apply the final mode only at the moment the content is complete — or simply keep `0600` on the temp file and `fchmod` after `fsync`.

#### RT-012 — `os.replace` without a directory `fsync` does not deliver the durability ADR-0023 claims
**Lens:** CHA. The helper fsyncs the file contents but not the parent directory, so after a host crash or power loss the rename may not have reached stable storage — the target can revert to the previous file, or (on some filesystems/mount options) appear with the new name and no data. ADR-0023's "a kill at any point leaves either the previous file or the complete new one" is true for process death and overclaimed for machine death. **Recommendation:** `dirfd = os.open(directory, os.O_DIRECTORY); os.fsync(dirfd)` after `os.replace`, or narrow the ADR's claim to process-level atomicity and say so.

#### RT-013 — Redaction protects the project's own dumps only; the root logger is opened to third-party loggers at DEBUG
**Lens:** EXT, DAR. `setup_logging` ends with `logging.getLogger().setLevel(default_level)`, and the root logger carries `standard_console_handler`. Running with `--logging-level DEBUG` therefore enables DEBUG propagation for any logger created *after* `dictConfig` — `apprise`, `docker`, `urllib3` — whose records can carry full notification URLs (which are the credential) and Docker API traffic. Today most of those loggers happen to be created at import time and are suppressed by `disable_existing_loggers: True`, but that is an accident of import order, not a control, and it silently un-does story 3's redaction work the moment an import moves. **Recommendation:** pin third-party logger levels explicitly in `logging.yaml` (`apprise: WARNING`, `urllib3: WARNING`, `docker: WARNING`, `propagate: False`), and set the project logger's level from `--logging-level` rather than the root's.

#### RT-014 — ACME file ingestion is unbounded and unvalidated
**Lens:** CHA, ABU. `json.loads(Path(sourceFile).read_text())` reads the whole file into memory with no size cap, `b64decode` runs without `validate=True`, and `data[elementNames[0]]` indexes a possibly-empty dict (caught, but only by the broad outer handler, which reports it as "Error processing file"). A large or deeply nested JSON file in the watched directory exhausts memory in a container that typically has a small limit; the resulting OOM-kill takes the exporter down and, because `RUNATSTART=true`, into a restart loop. **Recommendation:** `os.stat().st_size` guard (a few MB is generous for acme.json) before reading, `b64decode(..., validate=True)`, and an explicit "no resolver node found" branch instead of relying on IndexError.

---

### OBSERVATIONS

#### RT-015 — Story 3's redaction was verified working end-to-end, including the sink that previously leaked
Executed against the project venv with `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE`, an indexed `..._APPRISEURLS_0` containing a Telegram-shaped token, and an argparse namespace carrying a CLI passphrase. All three were masked in all three sinks (`Command Line Args:` → `***REDACTED***`, `_dump_config` → confuse path-redaction `REDACTED`, `_dump_settings` → `***REDACTED***`). The same three sinks were re-checked against the real `traefik-certificate-exporter.log` in the working tree: no plaintext. The path-registry design (`SECRET_CONFIG_KEYS` as the single declaration, with the name pattern retained only as a backstop) is the right mechanism for the list-valued Apprise case and is worth preserving as the pattern for any future credential setting.

#### RT-016 — The post-export hook inherits the full process environment, including the passphrase and Apprise URLs
`run_post_export_command` passes `os.environ.copy()` to the child. That is necessary (the hook needs PATH and the documented exported-domains variable), and the hook is operator-configured, so this is not a vulnerability — but it means every credential supplied by environment variable is readable by the hook and by anything the hook spawns, and the hook's stderr is logged verbatim at ERROR. Operators writing hooks should be told not to `env`-dump on failure. Worth one line in `docs/operational.md`.

#### RT-017 — Strict CLI parsing (story 3) behaves correctly and introduces no new import-time surface
`parse_args_strict()` is a function, invoked only from `main()`, and the lenient module-level `globalArgs` remains the import-time default (ADR-0025). An unrecognized flag exits 2 with argparse's usage message before `setup_logging` runs; no argv content reaches a log sink before redaction is in place. No finding.

---

## EXECUTIVE SUMMARY

This sprint's four stories were reviewed together with the runtime they ship into: the ACME ingestion path, the new atomic-write helper and its callers, the settings/secret-redaction machinery, the logging configuration, the Docker-socket client, the container image **and its s6 service definition**, and the CI/governance gates the sprint hardened. The sprint's stated goals were met and, in the case of story 3's redaction, verified empirically — the secret-handling work is genuinely sound. **Overall risk posture: HIGH**, driven not by the sprint's own regressions but by trust assumptions the sprint formalised without re-examining: that the ACME file is trustworthy input, that `/config` is data rather than code, and that the process is not root (it is — `s6-setuidgid root`).

The single most dangerous finding is **RT-001**: the certificate's `domain.main` value flows unvalidated into a filesystem path, so an absolute path or `../` in the ACME store makes the newly-hardened atomic writer place five attacker-influenced files, including a private key, anywhere the root-running process can reach — demonstrated here by execution, not by reading. It is the sprint's own helper that carries the payload, and ADR-0023/0024 reasoned carefully about *how* those bytes are written while never asking *where*.

The single most important recommendation is to **close the gap between what the code assumes about its own privilege and what the image actually grants it**: validate `domain.main` and `resolverName` as DNS names and confine the resolved path under `outputPath` (RT-001), give private-key outputs an explicit `0600` floor instead of a umask-derived mode and refuse to inherit a permissive mode or foreign ownership from an existing target (RT-002, RT-003), and drop the service from `s6-setuidgid root` to the PUID/PGID account the LinuxServer base already provides — which simultaneously reduces RT-001, RT-003, RT-004 and RT-009 from "root" to "the export user".

**CRITICAL: 0 | HIGH: 4 | MEDIUM: 5 | LOW: 5 | OBSERVATION: 3**
