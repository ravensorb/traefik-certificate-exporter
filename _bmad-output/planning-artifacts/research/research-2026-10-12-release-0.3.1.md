# Research brief — 0.3.1 (epic E015)

- **Date:** 2026-10-12
- **Repository:** traefik-certificate-exporter @ `8e54307` (`main`)
- **Revision:** §1 rewritten 2026-10-12 after the maintainer's LSIO constraint (see §1 header).
- **Inputs:** BL-E014-105, -106, -107, -108, -111 (spec proposal AD-1), -112 (spec proposal AD-2), -119 (red-team RT-1), -120 (RT-2); `_bmad-output/implementation-artifacts/epic-014/epic-closure/` (redteam-report.md, spec-proposals/); `epic-014/sprint-02/closure/live-host-test-rwusdckrls6-2026-10-12.md`.
- **Method:** every fact below was checked on 2026-10-12 against a primary source: an upstream repository at a named ref (`gh api`), PyPI JSON, official documentation, the installed package in the project `.venv` (file:line cited), the digest-pinned base image or released image (read with `docker create` + `docker cp` / `docker run`), or a local probe. Probe files lived under `/tmp` and were deleted; probe containers were removed. No repository source was modified.
- **Assumption recorded:** where a section says "Recommended", the brief makes the choice so planning can proceed. Each choice that needs the maintainer is listed in `_bmad-output/implementation-artifacts/epic-015/maintainer-decisions.md`. Nothing here is an ADR.

| § | Topic | Story |
|---|---|---|
| 1 | LinuxServer conventions and the root boundary (revised 2026-10-12 under the LSIO constraint) | E015-S01-001 |
| 2 | cryptography: RSA key validation cost and PKCS#12 change detection | E015-S01-002 |
| 3 | watchdog moved events | E015-S01-003 |
| 4 | Historical `TRAEFIK_*` / pre-confuse environment names | E015-S01-004 |
| 5 | `docker/setup-buildx-action` v4 inputs and input validation | E015-S02-001 |
| 6 | pre-commit hook dependency pinning and audit coverage | E015-S02-003 |
| 7 | Registries: GHCR credentials, one-digest fan-out, forge release | E015-S02-002 |
| 8 | Release 0.3.1 and the production upgrade path | E015-S02-004 |

---

## 1. LinuxServer conventions and the root boundary (E015-S01-001)

**Maintainer constraint (2026-10-12), verbatim:** "for the root fix -- do NOT break lsio and the way they do things". `/config` stays `abc`-owned (PUID/PGID), the base image's `lsiown` lines and init scripts are not disabled, patched or worked around, and host operators keep editing `config.yaml` as their PUID user. The first version of this section recommended taking `/config`, `/app`, `/defaults` back to root, neutralising `lsiown` at build, and refusing non-root-owned config; that recommendation is **withdrawn** (maintainer-decisions MD-01 … MD-05).

| Fact | Source |
|---|---|
| Base `ghcr.io/linuxserver/baseimage-alpine:3.24@sha256:d2deff7a9aff1388bd79ded33a4efda6bd4b26358f9234a23deccba724738fea`, label `4bf86442-ls13`, revision `f6b732b1`. | `docker/Dockerfile:6`; `docker inspect traefik-certificate-exporter:local` |
| `init-adduser/run` runs `lsiown abc:abc /app`, `/config` and `/defaults` on every boot unless `LSIO_READ_ONLY_FS` or `LSIO_NON_ROOT_USER` is set. | `linuxserver/docker-baseimage-alpine@f6b732b1:root/etc/s6-overlay/s6-rc.d/init-adduser/run:54-56` (`gh api …?ref=3.24`); image `:53-57` |
| `lsiown` without `-R` is `find -maxdepth 0 … -exec chown`: it changes the directory, not its contents. | image `/usr/bin/lsiown:30` |
| s6 order: init-adduser → … → init-config → init-traefik-certificate-exporter-config → init-config-end → mods → custom files → svc. Oneshots re-run on every start; the chown is re-applied on every restart. | image `dependencies.d`; 0.3.0 probe |
| Booted with `PUID=1000`: `/config`, `/app`, `/defaults` are `1000:1000 755`; the seeded `config.yaml` is `0:0 644`; uid 1000 can replace it by rename (in-place editors fail). | `docker run -e PUID=1000 …:0.3.0`, `docker exec stat` (2026-10-12) |
| RT-1 reproduces on the current `:local` image: a uid-1000 rename of `config.yaml` carrying `restartcontainers: true` + `postexportcommand` made the next boot's hook write `uid=0(root)`. | manual replay 2026-10-12 |
| The service working directory is its s6 service dir; init's `python -` does not import a planted `/config/glob.py` or `tempfile.py`. | `/proc/<pid>/cwd`; planted-module probe with restart (2026-10-12) |
| As `abc`, `os.rename('/app/.venv', …)` fails with `EXDEV` on overlay2; creating new entries in `/app` succeeds. (Filed as BL-E015-002.) | `docker exec -u 1000:1000 … python -c os.rename` (2026-10-12) |
| `/usr/bin/s6-setuidgid` (→ `/command/s6-setuidgid`) and `/bin/setpriv` are present in the image; its Python is 3.14.8. | `docker exec … command -v` |
| `subprocess.Popen` accepts `user`/`group`/`extra_groups` (Python 3.9+); the project floor is `>=3.10`. | `inspect.signature`; `pyproject.toml:15` |
| confuse 2.3.0 `ConfigView.resolve()` yields each value with the source that supplied it (and whether it is the packaged default); its YAML loader subclasses `SafeLoader`. | local check; `confuse.yaml_util.Loader.__mro__` |
| Apprise 1.13.1 loads plugins only when told to (`plugin_paths` defaults to empty; `notify.py:55` passes none); `ntfy ?attach=` sends a remote URL and reads no local file; the only process-spawning plugin (`macosx`) is Darwin-only. | image `apprise/asset.py:202,244-265`, `plugins/ntfy.py:873`, `plugins/macosx.py` |
| `docker.py` only calls `ping`, `version`, `containers.list(filters=label)`, `containers.get` and `restart`; the endpoint comes from `DOCKER_HOST` only. | `src/traefik_certificate_exporter/libs/docker.py:139,157-158,300-301,365,479` |
| The image `ENV` sets `…_OUTPUTPATH=/certs` and `…_DATAPATH=/data`, and the environment outranks the file; the logging config is already environment-only. | `docker/Dockerfile:123-130`; `settings.py:325-346`; `logging_utils.py:240-260` |
| Output writes are temp file + `os.replace`: a symlink at the target is replaced, not written through; path parts are whitelisted and containment-checked. | `certificate_exporter.py:107-235,448-470` |
| LSIO practice for root components configured from `/config`: swag copies `/config/fail2ban` into `/etc/fail2ban` and runs `fail2ban-client` as root (no privilege-split service pattern). | `linuxserver/docker-swag@0cc53e20:root/etc/s6-overlay/s6-rc.d/init-fail2ban-config/run`, `svc-fail2ban/run` |
| LSIO Python images build their venv at `/lsiopy`, not under `/app`. | `linuxserver/docker-bazarr`, `linuxserver/docker-sabnzbd` `Dockerfile` (`python3 -m venv /lsiopy`) |
| LSIO documents PUID/PGID as the mapping to a host user for file ownership and reduced privilege. | https://docs.linuxserver.io/general/understanding-puid-and-pgid/ |

**Settings classification** (all 16 keys of `config_default.yaml`):
- **Environment/CLI-only when running as root:** `postexportcommand` (root executes it), `outputpath` (root writes there and init chowns under it).
- **Any source:** `datapath`, `filespec` (read only); `traefikresolverid`, `resolverinpathname`, `flat`, `domains.include`, `domains.exclude` (shape whitelisted, contained paths); `restartcontainers` (bounded Docker API use, above); `appriseurls` (network egress only); `pkcs12passphrase`, `dryrun`, `watchforchanges`, `runatstart`, `watchinterval` (no privilege effect).

**Candidates evaluated:**
- (a) Hook as `abc` in root mode (`subprocess.run(user=)`, `s6-setuidgid`, `setpriv`): rejected as the primary fix. Root writes keys `0600 root:root`, so an `abc` hook cannot read `privkey.pem`/`.pfx` or reach the socket, breaking legitimate root hooks; any root opt-in would still have to come from the environment.
- (b) Root-sensitive settings from environment/CLI only when euid is 0: **recommended**. It closes the reproduced attack (the payload's hook is file-sourced, so root ignores it), changes no ownership and no LSIO init.
- (c) Root-only reader handing the store to an `abc` worker: no maintained simple mechanism and no LSIO precedent for one app; the hook and Docker restarts would still need root.
- (d) Restart path: a file-set `restartcontainers: true` still forces root mode, but with (b) root then runs no file-sourced command and writes no file-chosen path; the remaining gain is restarting containers that carry the restart label.

**Recommended:** in root mode, `postexportcommand` and `outputpath` come only from environment/CLI; a file-sourced value is ignored with one ERROR (setting and file named, value never). A declared trust class for every key (`ROOT_SETTING_TRUST`) with tests that every key is classified, every file the loader opens is covered, and the hook is the package's only process-spawn site; an image test replays RT-1 and a regression test proves `/config` stays PUID-owned and editable. LSIO init untouched.

**Risks:**
- An operator's environment-set root hook that runs a script stored in `/config` (abc-writable) re-opens the path; documented.
- `LOGGING_CFGFILE` or a `FILE__*` secret pointed into `/config` makes that file root-sensitive; documented.
- Docker mods and custom init scripts run as root after our init (operator-supplied).
- The venv under `abc`-owned `/app` (BL-E015-002); only overlay2's `EXDEV` blocks the rename today.
- Apprise egress carries domain names (unchanged).
- Root-mode users with the hook in `config.yaml` must move it to the container environment at upgrade.

---

## 2. cryptography: RSA key validation cost and PKCS#12 change detection (E015-S01-002)

| Fact | Source |
|---|---|
| Locked/installed cryptography is 50.0.2 (Python 3.11.11 in `.venv`). | `pyproject.toml:24` (`^50.0.2`), `poetry.lock`; `poetry run python -c 'import cryptography; print(cryptography.__version__)'` |
| `load_pem_private_key` and `load_der_private_key` accept keyword-only `unsafe_skip_rsa_key_validation=False`. | `inspect.signature` on 50.0.2: `(data, password, backend=None, *, unsafe_skip_rsa_key_validation=False)` |
| Documented semantics: "If True RSA private keys will not be validated. This significantly speeds up loading the keys, but is unsafe unless you are certain the key is valid. User supplied keys should never be loaded with this parameter set to True. If you do load an invalid key this way and attempt to use it OpenSSL may hang, crash, or otherwise misbehave." Added in 39.0.0. | https://cryptography.io/en/latest/hazmat/primitives/asymmetric/serialization/ |
| The 39.0.0 changelog entry adds disabling RSA key validation for the PEM/DER loaders and `private_key()`; 45.0.0 (yanked) extended it to `load_ssh_private_key`. No entry concerns PKCS#12 loaders. | https://cryptography.io/en/latest/changelog/ |
| `pkcs12.load_key_and_certificates(data, password, backend=None)` and `load_pkcs12` do **not** accept the flag: PKCS#12 loads always validate. | serialization docs; `inspect.signature` on 50.0.2 |
| `serialize_key_and_certificates` rejects a key that does not match the certificate (`ValueError: Certificate public key and provided private key do not match`); the flag only affects loading. | local probe, 50.0.2 |
| PKCS#12 output differs on every build, with `BestAvailableEncryption` and with `NoEncryption()` — byte comparison cannot detect "unchanged". | local probe: two builds compared, `False` in both modes |
| `BestAvailableEncryption`: "The encryption algorithm may vary based on which version of OpenSSL the library is compiled against … may change over time"; the docs warn "PKCS12 encryption is typically not secure". | serialization docs |
| Fingerprinting is cheap: `Certificate.fingerprint(SHA256())` ≈ 0.01 ms; SHA-256 of public-key DER ≈ 0.008 ms; SHA-256 of PKCS8 DER ≈ 0.02 ms. | local probe |
| cryptography `Scrypt(n=2**14, r=8, p=1, length=32)` ≈ 63 ms per derive, `.verify` raises `InvalidKey` on a wrong passphrase; `hashlib.scrypt` same parameters ≈ 67 ms; `pbkdf2_hmac` SHA-256 600k iterations ≈ 390 ms. | local probe (x86_64, 8 CPUs) |

Local timing probe (cryptography 50.0.2, Python 3.11.11, x86_64):

| Operation | RSA-2048 | RSA-4096 |
|---|---|---|
| `load_pem_private_key`, validating | 51 ms | 656 ms |
| `load_pem_private_key`, skip flag | 0.03 ms | 0.04 ms |
| PKCS#12 load, unencrypted | 51 ms | 576 ms |
| PKCS#12 load, encrypted | 72 ms | 629 ms |
| Serialize, `NoEncryption` | not recorded | 1.8 ms |
| Serialize, `BestAvailableEncryption` | not recorded | 26 ms |

Current-tree exporter, 5 domains sharing one RSA-4096 leaf:

| Pass | Time | Key loads | PKCS#12 loads |
|---|---|---|---|
| First | 5.95 s | 10 | 0 |
| Unchanged | 9.09 s | 10 | 5 (10 with a passphrase) |

The first/unchanged ratio matches production's 74 s / 108 s (BL-E014-106).

**Recommended:**
- Load each key at most once per domain, through one helper passing `unsafe_skip_rsa_key_validation=not settings.validatekeys`.
- Load and build only when the `.pfx` must be rebuilt or verified.
- Detect changes with a sidecar holding the `.pfx` file's SHA-256, the key PEM's SHA-256, ordered SHA-256 certificate fingerprints, and a cryptography `Scrypt` hash of the passphrase (random salt, parameters stored, `functools.lru_cache` memo).
- Fall back once to the old content compare when the sidecar is missing, unusable, or does not match the `.pfx`.
- stdlib `json` for the file; the existing `_atomic_write_bytes` at mode 0600.

**Risks:**
- An invalid key loaded with the flag can make OpenSSL misbehave; skip validation only for a trusted Traefik store; the default stays on.
- PKCS#12 loads cannot skip validation, so the verify path (upgrade, damaged sidecar) still costs ~0.6 s per RSA-4096 `.pfx`, once.
- `BestAvailableEncryption`'s algorithm can change between cryptography versions without the sidecar noticing (ADR-0043 already chose not to compare the algorithm).
- The scrypt cost is paid once per sidecar per process (~5 s for 74 domains at the first verification).

---

## 3. watchdog moved events (E015-S01-003)

| Fact | Source |
|---|---|
| Installed watchdog is 6.0.0; `Observer` resolves to `InotifyObserver` on Linux. The released 0.3.0 image is the same (6.0.0, `InotifyObserver`). | `poetry.lock`; `pyproject.toml` `watchdog = "^6.0"`; `.venv/.../watchdog/observers/__init__.py:54-56`; `docker run` on 0.3.0, 2026-10-12 |
| `FileSystemEvent` has `src_path` and `dest_path` (default `""`); `FileMovedEvent` subclasses `FileSystemMovedEvent` (`event_type = "moved"`). | `.venv/lib/python3.11/site-packages/watchdog/events.py:105-129,153` (6.0.0) |
| `FileSystemEventHandler.on_moved(self, event: DirMovedEvent \| FileMovedEvent) -> None` is a no-op that dispatch calls by `event_type`. | `events.py:208-216,228` (6.0.0) |
| `PatternMatchingEventHandler.dispatch` builds `paths = [dest_path, src_path]` and dispatches if **any** path matches (`match_any_paths`): a rename onto, away from, or between watched names all reach `on_moved`. | `events.py:342-365` (6.0.0) |
| Matching is `PurePath.match` (`PureWindowsPath` when `case_sensitive=False`); public helper `watchdog.utils.patterns.match_any_paths`. | `watchdog/utils/patterns.py:24-45,81-99` (6.0.0) |
| inotify: a paired MOVED_FROM/TO becomes `FileMovedEvent(src, dest)`; an unpaired MOVED_TO (from outside the watched dir) becomes `FileCreatedEvent`; an unpaired MOVED_FROM becomes `FileDeletedEvent` (delivered late), under the default `generate_full_events=False`. | `observers/inotify.py:141-172,250-251` (6.0.0) |
| `FileClosedEvent` (`IN_CLOSE_WRITE`) exists but only `InotifyObserver` emits it. | `observers/inotify.py:189-191`; https://raw.githubusercontent.com/gorakhargosh/watchdog/master/changelog.rst |
| 7.0.0-dev switches matching to `PurePath.full_match()`, so `*.json` stops matching absolute paths (breaking). | changelog above |
| The readthedocs "stable" API page documents 2.1.5, not 6.x; the installed source is the authority. | https://python-watchdog.readthedocs.io/en/stable/api.html |
| Probe (real observers, `os.replace`): temp file renamed onto `acme.json` → inotify `FileMovedEvent` only, polling Deleted+Created; rename from another dir → `FileCreatedEvent`; rename away → `FileMovedEvent` under both; vim-style save handled through `created`; a directory moved in → nothing. | throwaway probe 2026-10-12 (recorded in the story's Context table) |

**Recommended:** add `on_moved` to `AcmeCertificateFileHandler`. If the old name matches, drop it from the pending set. If the new name matches (checked with `match_any_paths` against the handler's own patterns), queue it through the same path as created/modified. Otherwise log one INFO line. Keep the watch non-recursive, keep ignoring directories, keep the default `generate_full_events`, do not trigger on `on_closed`. Test with real watchdog event classes through `dispatch()`, and with a real `Observer` and a `PollingObserver` on `tmp_path`.

**Risks:**
- watchdog 7.x `full_match` breaks `*.json` matching; the `^6.0` pin and the real-observer tests catch it at the upgrade.
- Residual race: a rename more than 2 s after the temp file's `created` event can make one drain log the existing `File not found` ERROR (accepted, documented).
- inotify does not see changes made from another host on NFS/SMB (existing limitation).

---

## 4. Historical TRAEFIK_* environment names (E015-S01-004)

The 0.0.x image (tags v0.0.2–v0.0.9.2) read these names in `docker/root/app/run.sh` (`${NAME+x}` presence tests that appended CLI flags to `appParams`). Confuse replaced it at `3f14b25` (2024-03-29, first in v0.0.10.0). Since then every one of them is silently ignored, and legacy detection never looks at them because it only scans `TRAEFIK_CERTIFICATE_EXPORTER_*`. Eight of the eleven have no `TRAEFIK_` prefix.

| Name | Introduced | Removed (run.sh) | Last doc mention removed | Modern key / replacement |
|---|---|---|---|---|
| TRAEFIK_FILESPEC | 141815b | 3f14b25 | 3f14b25 | settings.filespec → TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC |
| TRAEFIK_RESOLVERID | 141815b | 3f14b25 | 3f14b25 | settings.traefikresolverid → …_SETTINGS_TRAEFIKRESOLVERID |
| TRAEFIK_RESOLVERID_INOUTPUTPATHNAME (sic) | 4a3c411 | 3f14b25 | 2fd6b3f | settings.resolverinpathname → …_SETTINGS_RESOLVERINPATHNAME |
| DRYRUN | 141815b | 3f14b25 | 3f14b25 | settings.dryrun → …_SETTINGS_DRYRUN |
| FLAT | 141815b | 3f14b25 | 3f14b25 | settings.flat → …_SETTINGS_FLAT |
| RESTART_CONTAINERS | 141815b | 3f14b25 | 3f14b25 | settings.restartcontainers → …_SETTINGS_RESTARTCONTAINERS |
| DOMAINS_INCLUDE | 141815b | 3f14b25 | 3f14b25 | settings.domains.include → …_SETTINGS_DOMAINS_INCLUDE |
| DOMAINS_EXCLUDE | 141815b | 3f14b25 | 3f14b25 | settings.domains.exclude → …_SETTINGS_DOMAINS_EXCLUDE |
| RUN_AT_START | 479da80 | 3f14b25 | never documented | settings.runatstart → …_SETTINGS_RUNATSTART |
| CONFIG_FILE | 141815b | 3f14b25 | 3f14b25 | none (container always reads /config/config.yaml; CLI -c) |
| TEST_VERSION | ca678ee | 3f14b25 | a7b2b6f | none (it only echoed the command line) |

These flags were switched on by the variable's presence, whatever its value: `NAME=false` meant on.

Excluded by rule, not by a list: `LLL_EX_INSTALL_*` and `PACKAGE_REPO_URL` (`${…+x}` in `docker/Dockerfile` and `docker/root/opt/l3io/common/scripts/10-install-packages.sh`). Neither file ever contained `appParams`; these are build-time helpers.

Derivation commands (full history: `git rev-parse --is-shallow-repository` = false, 234 commits):

```sh
git log --format= --name-only -G appParams HEAD | sort -u          # translator files → docker/root/app/run.sh
git log -p --no-color --format= HEAD -- docker/root/app/run.sh | grep -E '^[+-]' \
  | grep -oE '\$\{[A-Za-z_][A-Za-z0-9_]*\+x\}' | sort -u
git log -p --no-color --format= HEAD -- '*.md' '*.yml' '*.yaml' '*.sample' '*Dockerfile' \
  ':(exclude)_bmad-output/**' ':(exclude)docs/adr/**' ':(exclude).github/**' \
  | grep -oE '\bTRAEFIK_[A-Z0-9_]+' | grep -v '^TRAEFIK_CERTIFICATE_EXPORTER_' | sort -u
for n in <name>; do git log --reverse --format=%h -S "\${$n+x}" HEAD -- docker/root/app/run.sh | head -1; \
  git log --format=%h -S "\${$n+x}" HEAD -- docker/root/app/run.sh | head -1; done   # introduced / removed
git log -p --no-color --format='COMMIT %h' HEAD -- . ':(exclude)_bmad-output/**' \
  | awk '/^COMMIT /{c=$2} /^diff --git /{f=$4} /^[+-].*TRAEFIK_(RESOLVERID|FILESPEC)/ && !/TRAEFIK_CERTIFICATE_EXPORTER_/{print c, f}'  # doc attribution
```

**Recommended:** the table lives once, as data in `legacy_settings.py`; detection matches exact, case-sensitive names (the unprefixed ones included); warn and ignore (no aliasing); values never printed. The derivation is recorded reproducibly (commands above + a committed fixture) because CI checkouts may be shallow.

**Risks:** a CLI user whose shell happens to export e.g. `FLAT=1` gets one advisory warning (exact match only; nothing outside the table is reported).

---

## 5. docker/setup-buildx-action v4 inputs and input validation (E015-S02-001)

| Fact | Source |
| --- | --- |
| `dev.yaml:409-412` and `release.yaml:477-480` pin `docker/setup-buildx-action@f87e5991…` (`# v4.4.1`, tag v4.4.1 = that SHA) and pass `config:`. `build.yaml:154` uses `driver: docker` only. | repo tree; `gh api repos/docker/setup-buildx-action/git/ref/tags/v4.4.1` |
| At `f87e599` the inputs are: version, driver, driver-opts, buildkitd-flags, buildkitd-config, buildkitd-config-inline, use, name, endpoint, platforms, append, keep-state, cache-binary, cleanup. There is no `config` input. | `gh api repos/docker/setup-buildx-action/contents/action.yml?ref=f87e599…` |
| In v3.12.0, `config` and `config-inline` carried `deprecationMessage: 'Use buildkitd-config instead'`. v4.0.0 (2026-03-05) removed them ("Remove deprecated inputs/outputs", #464). | action.yml@v3.12.0; v4.0.0 release notes |
| `src/context.ts:74-77` adds `--config <file>` to `buildx create` only when `buildkitd-config` (or `-inline`) is non-empty; an empty value is a no-op. | action source @ f87e599 |
| The CI spine prescribes the bug: AD-18 (`ARCHITECTURE-SPINE.md:304`) says "as `config`"; `docs/ci/gitea-runners.md:40,48` say the same. | repo |
| actionlint checks `with:` only for popular actions and "only … specifying major versions like `actions/checkout@v4`". Probe with hook binary v1.7.12: flagged `config` on `@v4`, passed the same step pinned by SHA and by `@v4.4.1`. | actionlint `docs/checks.md`@v1.7.12; `popular_actions.go`; local probe |
| No other maintained tool validates inputs of SHA-pinned actions: zizmor 1.30.1 has no input audit; ghalint v1.5.6 covers permissions, secrets and pinning only; action-validator v0.9.0 checks SchemaStore schemas and path globs; gha-workflow-linter 1.8.1 checks that refs exist (network + token) and documents no `with:` validation. | zizmor `docs/audits.md`@v1.30.1; ghalint README; action-validator README; https://pypi.org/project/gha-workflow-linter/ |
| The GitHub runner checks every step's `with:` against the pinned `action.yml` and warns "Unexpected input(s)"; it did so twice in run 38281339396. | `epic-014/sprint-02/closure/notes-E014-S02-007.md` AC 6 |

**Recommended:** rename the input to `buildkitd-config`; add the pygrep guard `workflows-no-removed-buildx-inputs` (a mechanism allowed by CI spine AD-4) over `^\.github/(workflows|actions)/`; add a per-release checklist item "zero `Unexpected input` lines in the run log".

**Risks:** the static guard covers only the removed key names and pygrep cannot tie a key to its step, so any action's `config:` key is refused; inputs other actions remove later are caught only by the runtime warning (not CI-gating); the act proof that the CA reaches BuildKit needs clone-only workflow edits.

---

## 6. pre-commit hook dependency pinning and audit coverage (E015-S02-003)

| Fact | Source |
| --- | --- |
| A `language: python` hook repo "must be installable via `pip install .`"; additional dependencies "will be appended to the `pip install` command". `golang` hooks are "installed via `go install ./...`". | https://pre-commit.com/ (Supported languages; `additional_dependencies`) |
| pre-commit has no hash or lock option. FR #3679 (hash-locked python hook installs) was closed 2026-05-10 by the maintainer ("there's several duplicates. you can already feed this into `additional_dependencies`"); #2201 (lockfile) was answered with `autoupdate --freeze`. | `gh issue view` on pre-commit/pre-commit |
| pip turns on hash-checking for everything once any requirement has `--hash`, so every requirement then needs a hash. | pip docs, "Secure installs" |
| pre-commit 4.4.0 added `language: unsupported` as an alias for `system`; the lock has pre-commit 3.8.0. | pre-commit CHANGELOG; `poetry.lock` |
| import-linter 2.15 requires `click>=6`, `grimp>=3.17`, `rich>=14.2.0`, `typing-extensions>=3.10`. mypy 2.4.0 requires typing_extensions, mypy_extensions, pathspec, librt, `ast-serialize<1.0.0,>=0.11.2`. | PyPI JSON |
| A fresh `PRE_COMMIT_HOME` run built two hook environments: import-linter's resolved click 8.5.0, grimp 3.17, rich 15.0.0, markdown-it-py 4.2.0, mdurl 0.1.2, Pygments 2.21.0, typing_extensions 4.16.0; mypy's resolved ast_serialize 0.13.0, librt 0.16.0, mypy_extensions 1.1.0, pathspec 1.1.1 and the two stubs. | local run 2026-10-12 |
| The `pip-audit` hook audits only the Poetry venv; mypy 2.4.0 is in the dev group but the mirrors-mypy hook does not use it. | `.pre-commit-config.yaml`; `pyproject.toml:36` |
| Other remote python hooks: pre-commit-hooks v6.0.0 resolves the range `ruamel.yaml>=0.15`; ruff-pre-commit pins `ruff==0.16.5` and zizmor-pre-commit `zizmor==1.30.1` with no dependencies; shellcheck-py's binary download is sha256-pinned but its build tool `setuptools-download` is unpinned. gitleaks and actionlint are golang hooks checked by `go.sum`. | each repo's manifest and packaging at the frozen SHA; PyPI JSON |
| `poetry run mypy --config-file=pyproject.toml src/` in the project venv: "Success: no issues found in 14 source files". | local probe |

**Recommended (option A):** move import-linter, mypy and the two type stubs into the Poetry dev group (hash-locked by `poetry.lock`, audited by pip-audit), run both hooks as `language: system`, delete the mirrors-mypy repo entry; add the pygrep guard `precommit-hook-deps-locked`; amend ADR-0042 "Not covered" with the full hook inventory; file one Low backlog item for `ruamel.yaml`.

**Risks:** mypy now sees the real installed packages, so new findings are possible; the guard cannot see languages declared in remote repos' own manifests and misses flow-style hook entries; ruff and zizmor wheels are still fetched without hashes.

---

## 7. Registries: GHCR credentials, one-digest fan-out, forge release (E015-S02-002)

| Fact | Source |
| --- | --- |
| Current digests: Docker Hub `0.3.0`/`0.3`/`latest` = `sha256:e3be0498…f986`; Gitea all three = `sha256:244015fe…7f74`; GHCR has no `0.3.0` or `0.3`, and its `latest`, `0.2.0`, `0.2`, `0` = `sha256:2e2cf7f7…536f` (0.2.0, 2026-09-07). | anonymous `docker buildx imagetools inspect`; `gh api …/packages/container/…/versions` |
| The GHCR package is public, linked to `ravensorb/traefik-certificate-exporter`, created 2026-09-03. | `gh api /users/ravensorb/packages/container/traefik-certificate-exporter` |
| There is no `v0.3.0` GitHub release (newest is v0.2.0). The `release` environment holds `PUBLISH_PYPI_TOKEN`, `PUBLISH_DOCKERHUB_TOKEN` and the two Docker Hub variables. | `gh release list`; `gh secret list --env release`; `gh variable list --env release` (names only) |
| "GitHub Packages only supports authentication using a personal access token (classic)"; pushing needs `write:packages`; a first push is private by default. | GitHub docs, "Working with the Container registry" |
| GitHub recommends `GITHUB_TOKEN` with `packages: write`; repos publishing via a workflow get admin on the package. Here that would widen job permissions (CI spine AD-13 forbids) and hand the ambient token to a publish step (AD-9 forbids). | GitHub docs, "Publishing Docker images"; CI spine |
| Gitea: "`GITEA_TOKEN` cannot publish to the package registry of its repository", and `jobs.<id>.environment` is ignored; Gitea provides no GHCR token. | https://docs.gitea.com/usage/actions/comparison |
| `git-action-release` needs `contents: write`; the changelog builder needs no special permissions. | LiquidLogicLabs action READMEs |
| `docker buildx imagetools create` with a single index source makes a "carbon copy"; buildx copies across registries (`util/imagetools/create.go`, `CopyWithIngester`/`CopyChain`). A `--dry-run` from Docker Hub to Gitea produced index bytes hashing to `e3be0498…`. | buildx docs and source; local dry run (buildx v0.38.0) |
| `crane copy` copies "while retaining the digest value". | go-containerregistry v0.22.1 crane docs |
| `docker buildx imagetools inspect --format '{{json .Manifest.Digest}}'` prints no trailing newline: piping several lookups into `sort -u` yields one line regardless of how many digests exist. E014-S02-007's digest row could therefore never fail; on 2026-10-12 it printed 1 across Docker Hub and Gitea, which hold two digests. | local check 2026-10-12 |
| act 0.2.89 reads `~/.actrc`, `.secrets` and `.vars` by default; `~/.actrc` on this workstation pulls Infisical-backed secrets, so `just act` does not keep its "no secrets" promise (`justfile:52`). | act docs/flags; `epic-014/execution-notes.md` |
| The Gitea repository is not anonymously readable (`git ls-remote` → "Repository not found"). | local check |

**Recommended:** publish every destination from GitHub only (one forge per release); GHCR via a classic PAT scoped to `write:packages` only, with an expiry; release token = fine-grained PAT on this repository (Contents read/write, Pull requests read); revoke the Gitea admin token and issue a `write:package`-only token stored only in the GitHub `release` environment; retag Gitea `0.3.0`, `0.3`, `latest` to the Docker Hub digest with `imagetools create`; backfill the `v0.3.0` GitHub release; digest equality is a checklist command (each lookup followed by `echo`), not a recipe; harden `just act` against ambient secrets.

**Risks:** a classic `write:packages` PAT can write every package the account owns; Gitea package access is per user/org, never per package; whether re-running only the old `release` job can still download that run's `dist` artifact is unverified (fallback: manual `gh release create`); the digest check is not CI-gating; a raw `act -s` run cannot be prevented by the repository.

---

## 8. Release 0.3.1 and the production upgrade path (E015-S02-004)

| Fact | Source |
| --- | --- |
| Production (rwusdckrls6) runs `ghcr.io/ravensorb/traefik-certificate-exporter:latest` (0.2.0) with Watchtower, sets `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME=1`, runs as root, writes `/mnt/certificates`, and is reached over SSH as `svc.claude` with passwordless sudo. | `epic-014/sprint-02/closure/live-host-test-rwusdckrls6-2026-10-12.md` |
| `containrrr/watchtower` is archived (last push 2025-12-17); last release v1.7.1 (2023-11-11). The maintained fork `nicholas-fedor/watchtower` released v1.23.0 on 2026-10-06. | `gh api repos/containrrr/watchtower`, `gh api repos/nicholas-fedor/watchtower/releases` |
| Watchtower defaults to an 86400 s poll; `--label-enable` uses `com.centurylinklabs.watchtower.enable`; HEAD digest checks skip unchanged pulls. | https://containrrr.dev/watchtower/arguments/ |
| Docker 29.0–29.2 rejects old API clients ("client version … too old"; Watchtower issues #2122, #2124, #2126); reported workarounds: `DOCKER_API_VERSION=1.44` or the fork. | https://github.com/containrrr/watchtower/issues/2124, /2122, /2126; https://forums.docker.com/t/docker-29-increased-minimum-api-version-breaks-traefik-reverse-proxy/150384 |
| The live test saw Docker Engine API 1.56 on the host. | live-host test, row E |

**Recommended:** before tagging, pin production to the 0.2.0 digest so the GHCR `latest` move cannot upgrade it unobserved; release with `just release patch` (maintainer); verify every destination (six `enabled` lines, zero partial-destination warnings, zero `Unexpected input`, one digest across all registry/tag lookups); upgrade production by hand to `:0.3`; post-check version label, privilege line, legacy warning, `/config` still PUID-owned, a `Post-export command:` line showing source and uid, no `Ignoring settings.` line, `cert.pem` fingerprints unchanged, export pass time; rollback = pin back to `@sha256:2e2cf7f7…`.

**Risks:** Watchtower may already be broken on this host (Docker 29 API floor); if production runs as root with the hook in `config.yaml`, E015-S01-001 ignores it: move it to the container `environment:` before the upgrade; GHCR `latest` jumps straight from 0.2.0 to 0.3.1 for every GHCR consumer.
