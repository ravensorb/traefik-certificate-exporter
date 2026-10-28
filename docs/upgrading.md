# Upgrading

What changes for an operator between releases, and what to do about it. Newest first. Each
item names the file or ADR it comes from; where this page and the code disagree, the code is
right and this page is a defect.

<!-- tce-settings-scan: legacy-names-listed -->

## 0.3.1 → 0.3.2

### Notifications use Apprise 2

Apprise, which delivers `appriseurls` notifications, moves from 1.13.1 to 2.0.1. Most URLs
work unchanged. Check yours if they use email PGP options:

- **`?pgpkey=` and `?use_pgp=` are silently ignored.** Apprise 2 removed both. The URL is
  still accepted, so the email is sent **unencrypted** with no error. Use
  `?pgp=encrypt&pgppub=<path to the public key>`.
- **`?pgp=` takes `no`, `sign` or `encrypt`.** Any other value (such as `pgp=yes`) makes
  Apprise reject the URL. That destination is then skipped with
  `Apprise rejected a configured destination (index N)`, and the others are still notified.

Destinations are now notified in parallel, so a pass waits for the slowest one rather than
for each in turn, and Apprise stops waiting for any one destination after 60 seconds. The
per-destination `cto`/`rto` timeouts are unchanged
([ADR-0014](adr/0014-post-export-notifications-via-apprise.md) §6).

## 0.3.0 → 0.3.1

### Root mode: hook, output path and data path from the environment only

- **Security (BL-E014-119): a root exporter no longer takes `postexportcommand` or
  `outputpath` from a file.** `/config` is owned by your `PUID`/`PGID` account, as in every
  LinuxServer image. In 0.3.0 that account could set `postexportcommand` in `config.yaml` and
  have the next start run it as root. From 0.3.1, when the exporter runs as root, these two
  settings are read only from `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND` /
  `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_OUTPUTPATH` or the command line. A value from
  `config.yaml` or a `.env` file is ignored, with one ERROR at start
  ([ADR-0049](adr/0049-root-mode-trust-covers-hook-output-and-store-location.md)).
- **Action if you run as root with a hook in `config.yaml`:** move it to the container's
  `environment:` as `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_POSTEXPORTCOMMAND`. The start-up
  line `Post-export command: … (source: …), runs as uid …` shows where the hook came from and
  which uid runs it. In unprivileged mode (`runs as uid` = your `PUID`) a `config.yaml` hook
  keeps working.
- **Nothing changes in `/config` ownership.** It stays owned by `PUID`/`PGID` and editable
  from the host as that user. Earlier documentation that said `/config` stays root-owned was
  wrong and has been corrected
  ([ADR-0030](adr/0030-conditional-privilege-drop.md) as amended 2026-10-12).
- **PyPI installs run as root:** the same rule applies, to `datapath` as well. Pass
  `--post-export-command` / `--output-path` / `--data-path`, or set the environment
  variables.
- **Security (arch gate AG-1): `datapath` joins the root-mode rule, and `filespec` must be a
  file name or glob.** A root exporter no longer takes `datapath` from a file. In every mode,
  `filespec` (`--file-spec`, `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC`) must be a file
  name or glob without a directory part, such as `acme.json` or `acme-*.json`. A value that is
  absolute, contains `/` or `\`, or is `..` is ignored with one ERROR at start, and `*.json`
  is used. Before 0.3.1 an absolute `filespec` let a file choose which store root exported. If
  you used one, set `datapath` to its directory and `filespec` to its name.
- **Mount `/data` read-only in both modes.** The ACME store must not be writable by your
  `PUID`/`PGID` account, whether the exporter runs as root or not.
- **Security: a root exporter loads only setting variables from a `.env` file.** In root
  mode a `.env` file (a CLI run as root) may set only `any-source` settings such as
  `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN`. Any other variable it would add, such as
  `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_*`, `DOCKER_HOST` or `LD_PRELOAD`, is dropped with one
  ERROR at start that lists the names. **Action:** move those variables to the real
  environment
  ([ADR-0049](adr/0049-root-mode-trust-covers-hook-output-and-store-location.md), amendment
  2026-10-12). The image reads no `.env` at all; see
  [.env files: CLI only; not read in the image](#env-files-cli-only-not-read-in-the-image).

### .env files: CLI only; not read in the image

- **The container no longer reads `/config/.env`.** The image sets
  `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV=false`. Put variables in the container's
  `environment:` or Docker's `env_file:` (Docker applies it), and settings in
  `/config/config.yaml`. If `/config/.env` exists, start-up logs one WARNING saying it is not
  read. The service never read it in 0.3.0 (s6 starts it outside `/config`); only one-off
  `docker exec … traefik-certificate-exporter` runs did.
- **CLI: `.env` is read from the current directory only.** A `.env` inside the installed
  package's folder is no longer read. Turn `.env` loading off with `--no-dotenv` or
  `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_LOADDOTENV=false`. The switch is read only from the
  environment or the command line; `loaddotenv` in `config.yaml` or `.env` is ignored with one
  ERROR.
- **CLI run as root (`sudo`):** unchanged from the root-mode rule above. A `.env` may set only
  `any-source` settings, and `${VAR}` is not expanded.

### PKCS12 fingerprint files and validatekeys

- **New files: `cert.pfx.fingerprint.json`** (flat layout: `<name>.pfx.fingerprint.json`)
  beside every `.pfx`, mode `0600`. They hold hashes only — no key bytes, the passphrase only
  as a salted scrypt hash — and let the exporter tell that a `.pfx` is current without
  opening it, so passes over unchanged RSA-4096 certificates are fast again (BL-E014-106).
  They are not exported artifacts: they never trigger a restart, the hook or a notification
  ([ADR-0051](adr/0051-pfx-fingerprint-sidecar.md), amending
  [ADR-0043](adr/0043-export-commit-and-reporting-contract.md)). If a consumer globs the
  output directory, exclude `*.fingerprint.json`.
- **Upgrading from 0.3.0: one slower first pass, nothing rewritten, nothing restarted.** The
  first pass verifies every existing `.pfx` by content once (one key and one PKCS#12 load per
  domain) and writes its fingerprint file. It rewrites no certificate file, so no container
  restarts and no hook or notification fires. Later passes over unchanged certificates load
  nothing. A dry run writes no fingerprint file, so dry runs stay slow until one real pass
  has run.
- **Upgrading from 0.2.x** still gets the one-time rewrite described under
  [0.2.0 → 0.3.0](#restarts-now-take-effect): every `.pfx` is rebuilt with its intermediates
  once, and its fingerprint file is written with it; `cert.pem` and `chain.pem` are
  rewritten once with the same certificates.
- **New setting `settings.validatekeys`** (env `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_VALIDATEKEYS`,
  CLI `--no-validate-keys`), default `true`. `false` skips RSA private-key validation when a
  `.pfx` is built (~0.5 s per RSA-4096 key). Use it only when the ACME store is written by
  your own Traefik: the keys are then trusted, not checked. The key/certificate match is
  always checked. Changing the setting rebuilds nothing. See
  [operational.md](operational.md#the-pfx-fingerprint-file-and-settingsvalidatekeys).

### Output on a filesystem that ignores chmod (CIFS/SMB)

- **One WARNING per pass instead of one per file.** On a mount with a fixed mode, such as
  CIFS with `nounix` and `file_mode=0755`, `chmod` succeeds and changes nothing, so the
  exporter cannot narrow a key or `.pfx` to `0600`. 0.3.0 logged `Tightened mode of … to
  0600` for every such file on every pass, which was not true. 0.3.1 logs one WARNING per
  store file per pass: `N exported file(s) from '<store>' keep a mode wider than the export
  policy …`. Nothing is rewritten because of it (BL-E015-068).
- **Action:** the files, private keys included, are as readable as the mount and the share
  allow. With `nounix`, `file_mode` is applied by this client only: other clients of the
  share see the server's permissions. Mount with `file_mode=0600,dir_mode=0700` (the
  `uid`/`gid` the mount forces decide who reads a `0600` file), restrict the share's own
  permissions on the server, or export to a filesystem that keeps modes.
- **Rewrites on such a mount warn about ownership.** A rewrite of a file the mount shows as
  owned by another uid (`forceuid`) logs `refusing to inherit ownership (uid N) from an
  existing export at …` for that file. It is expected there, and it is logged only when the
  file is rewritten: on the first pass after the upgrade and at each renewal.

### Environment names of the 0.0.x image are warned about

- **Start-up now warns about the environment variables of the 0.0.x image**, which have been
  ignored since v0.0.10.0: `TRAEFIK_FILESPEC`, `TRAEFIK_RESOLVERID`,
  `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME`, `DRYRUN`, `FLAT`, `RESTART_CONTAINERS`,
  `DOMAINS_INCLUDE`, `DOMAINS_EXCLUDE`, `RUN_AT_START`, `CONFIG_FILE` and `TEST_VERSION`. One
  WARNING per variable present names the `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_*`
  replacement; the value is never logged. The names are still ignored, and behaviour is
  unchanged (BL-E014-107; table under [Legacy setting names](#legacy-setting-names)).
- **Action:** replace each with its new name. In 0.0.x these variables switched their option
  on whatever their value, so `FLAT=false` meant flat: set the replacement to `true` or
  `false` explicitly.
- Only these exact, upper-case names are matched. Other variables, Traefik's own `TRAEFIK_*`
  included, produce no warning. Outside the container a shell that sets one of the generic
  names (`FLAT`, `DRYRUN`, `CONFIG_FILE`, ...) for another tool gets the same advisory
  WARNING; it changes nothing.
- **Root mode and `.env` (CLI only; the image reads no `.env`):** a legacy name in a `.env` file is removed in root mode like any
  non-setting variable, but it is reported by this WARNING, with its replacement, and not
  listed in the root-mode `.env` ERROR (moving it to the container's environment would not
  make it work).

### Watch mode detects stores replaced by rename

- **Watch mode now detects an ACME store that is replaced by renaming a file onto it** (an
  atomic `write temp + rename`, a restore from backup, many editors). Before 0.3.1 only
  in-place writes, which is what Traefik does, triggered an export.
- **Renaming a store file away** (for example `acme.json` → `acme.json.bak`) is logged at INFO
  and exports nothing. Exported certificates are left in place, as before.

### Where releases come from

- **GHCR receives releases again.** 0.3.0 was not published to
  `ghcr.io/ravensorb/traefik-certificate-exporter`, so `ghcr.io/…:latest` there moves straight
  from 0.2.0 to 0.3.1. If you follow `ghcr.io/…:latest` (for example with Watchtower), read
  [0.2.0 → 0.3.0](#020--030) as well: its changes reach you with this upgrade.
- **In particular, 0.3.0's one-time post-upgrade effect applies to a 0.2.x → 0.3.1 upgrade.**
  The first pass rewrites every `.pfx` (it now carries the intermediates) and every
  `cert.pem` and `chain.pem` (their trailing blank line goes; the certificates are the same),
  reports every domain once, restarts each labelled container once, and fires the
  post-export hook and notifications once
  ([Restarts now take effect](#restarts-now-take-effect)). The 0.3.1
  "verify once, rewrite nothing" behaviour above covers output written by 0.3.0 only.
- **GHCR has no `0.3.0` tag.** Pin `0.3.1` or later there, or use Docker Hub or the Gitea
  registry for `0.3.0`.
- **The Gitea and Docker Hub `0.3.0` images are different builds of the same source.**
  Gitea's came from a local test run, Docker Hub's from the GitHub release run
  ([ADR-0052](adr/0052-release-publication-one-forge-run.md)). 0.3.1 is one build on every
  registry.
- From 0.3.1 every release is one build from one GitHub release run, published to PyPI,
  Docker Hub, GHCR, the Gitea registry and package index, and a GitHub release.
- **For forks: publishing images to a Gitea registry behind a private CA now works.** The
  imported CA is passed to BuildKit for the `PUBLISH_GITEA_REGISTRY` host
  (`docker/setup-buildx-action` v4 renamed its `config` input to `buildkitd-config`, and
  `git-action-ca-certificate-import` v3.1.0+ writes a BuildKit registry config from
  `buildkit-registries`).

## 0.2.0 → 0.3.0

### Restarts now take effect

- **In 0.2.x `restartcontainers` silently failed.** The Docker SDK 0.2.x shipped could not
  talk to the Engine API, so no restart ever happened, and `--restart-container` set a key
  nothing read. A 0.2.x deployment with labeled containers and `restartcontainers: true` (or
  `--restart-container`) **starts restarting labeled containers after the upgrade**
  (`src/traefik_certificate_exporter/libs/docker.py`,
  [ADR-0045](adr/0045-restart-policy-only-on-change-defer-not-drop.md)).
- **Only on change.** Every pass, including the start-up pass, restarts a labeled container
  only when one of its domains' exported files is newer than the container's start time, with
  2 s of clock slack (`RESTART_MTIME_SLACK_SECONDS`). Unchanged certificates are not
  rewritten, so restarting the exporter over an unchanged store restarts nothing. A restart
  happens after the first export into an empty output directory, a renewal or reissue, an
  output file deleted or edited by hand, or a restart that an exporter crash or shutdown cut
  short (the next pass makes it, because the files are still newer than the container). Run
  the exporter against the local Docker daemon, whose clock the comparison shares.
- **One-time post-upgrade effect.** The first pass after upgrading from 0.2.x rewrites every
  `.pfx`, because it now carries the intermediates, and every `cert.pem` and `chain.pem`,
  whose trailing blank line goes (see PKCS12 below). That pass counts as a
  change for every domain: every labeled container restarts once, and the post-export hook
  and notifications fire once.
- **5-minute floor, deferred not dropped.** A container is restarted at most once per
  5 minutes (`RESTART_COOLDOWN_SECONDS = 300`). A restart that falls inside the window is
  deferred to its end instead of being dropped, so rapid successive changes never lose the
  last one.
- **Opt out:** set `restartcontainers: false` (it is off unless enabled), or remove the
  `com.github.ravensorb.traefik-certificate-exporter.domain-restart` label from the container.
- When `restartcontainers` is on, the exporter checks the Engine once at start-up: one INFO
  `Docker Engine reachable (API <version>)`, or one ERROR naming the endpoint. Exporting
  continues either way.

### Privilege model

- v0.2.0 ran the exporter as root: its service script never dropped to the `PUID`/`PGID`
  account, whatever `PUID`/`PGID` said.
- 0.3.0 keeps root unless the container proves at start-up that the unprivileged account can
  read every ACME store file and write the output path, and `restartcontainers` is off; it
  then runs as `PUID`/`PGID`. Otherwise it runs as root and logs one WARNING saying why.
  Traefik writes `acme.json` mode `0600` owned by its own user, so with a stock (root)
  Traefik the exporter keeps running as root, as before. To run unprivileged, run Traefik as
  a non-root user, set `PUID`/`PGID` to that user, and mount `/data` read-only
  ([ADR-0030](adr/0030-conditional-privilege-drop.md) as amended 2026-10-10,
  [docker/README.md](../docker/README.md#which-user-does-the-exporter-run-as)).

### Settings renames and fixes

- `--restart-container` now enables restarts. It previously set an unread key, so restarts
  were off even with the flag (`src/traefik_certificate_exporter/libs/settings.py`).
- The sample `docker-compose.yml` and `docker/README.md` environment variable names are
  corrected. If you copied them, rename to `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_<KEY>`
  (table below). The compose sample drops the obsolete `version:` key and no longer quotes
  values (Compose passed the quotes through). The two config-file variables in the table
  never did anything: the container's config file is always `/config/config.yaml`.
- New `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL` sets the log level when `-ll` is not
  given; it is the container's verbosity switch. An invalid value falls back to INFO with one
  WARNING. One INFO line at start-up names the effective level and its source (`cli`, `env`
  or `default`) (`_log_level_with_source` in `src/traefik_certificate_exporter/app.py`).
- `config.sample.yml` and the image's seed config state the logging defaults correctly (the
  image sets `CONSOLEONLY=true`) (`config.sample.yml`,
  `docker/root/defaults/config/config.yaml.sample`).

### Legacy setting names

0.3.0 logs one WARNING at start-up for each legacy name it finds, in the environment or the
config file, naming the replacement and never the value. **Legacy names are ignored**: they
never set anything, and there are no aliases. Any other unknown
`TRAEFIK_CERTIFICATE_EXPORTER_*` environment variable gets one WARNING with the nearest valid
name (`src/traefik_certificate_exporter/libs/legacy_settings.py`). From 0.3.1 the start-up
check also warns about the pre-confuse environment names of the 0.0.x image (v0.0.2 to
v0.0.9.2), such as `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME`, matched exactly and case-sensitively.
Those names were presence-based in 0.0.x, so `NAME=false` meant on: set the replacement to
`true` or `false` explicitly.

<!-- Rendered from LEGACY_SETTING_NAMES in src/traefik_certificate_exporter/libs/legacy_settings.py;
     do not edit by hand. Regenerate: poetry run python -m tests.test_settings_surface
     (tests/test_settings_surface.py::test_upgrading_lists_every_legacy_name fails on drift). -->
<!-- legacy-settings:begin -->
| Source | Legacy name | Replacement or fix |
| --- | --- | --- |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_CONFIG_FILE` | the container always reads /config/config.yaml; outside the container pass -c/--config-file on the command line |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_CONFIGFILE` | the container always reads /config/config.yaml; outside the container pass -c/--config-file on the command line |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_FILESPEC` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_RESOLVERID` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_TRAEFIKRESOLVERID` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_RESOLVERID_INOUTPUTPATHNAME` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESOLVERINPATHNAME` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_DRYRUN` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_FLAT` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_RESTART_CONTAINERS` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_INCLUDE_DOMAINS` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_EXCLUDE_DOMAINS` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINER` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS.RESTARTCONTAINER` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_INCLUDE_DOMAINS` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_EXCLUDE_DOMAINS` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_XCLUDE_DOMAINS` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_LOGGINGLEVEL` | `TRAEFIK_CERTIFICATE_EXPORTER_LOGGING_LEVEL` |
| env | `TRAEFIK_CERTIFICATE_EXPORTER_NOTIFY_*` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_APPRISEURLS_<n>` |
| env | `TRAEFIK_FILESPEC` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FILESPEC` |
| env | `TRAEFIK_RESOLVERID` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_TRAEFIKRESOLVERID` |
| env | `TRAEFIK_RESOLVERID_INOUTPUTPATHNAME` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESOLVERINPATHNAME` |
| env | `DRYRUN` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DRYRUN` |
| env | `FLAT` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_FLAT` |
| env | `RESTART_CONTAINERS` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RESTARTCONTAINERS` |
| env | `DOMAINS_INCLUDE` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE` |
| env | `DOMAINS_EXCLUDE` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_EXCLUDE` |
| env | `RUN_AT_START` | `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_RUNATSTART` |
| env | `CONFIG_FILE` | the container always reads /config/config.yaml; outside the container pass -c/--config-file on the command line |
| env | `TEST_VERSION` | it only printed the 0.0.x image's command line; nothing replaces it |
| config | `settings.restartcontainer` | `settings.restartcontainers` |
<!-- legacy-settings:end -->

### Settings precedence and container run mode

- For every setting the order is `CLI > env > config file > defaults`: a CLI flag beats a
  `TRAEFIK_CERTIFICATE_EXPORTER_*` environment variable, which beats the config file, which
  beats the packaged default ([ADR-0044](adr/0044-container-run-once-contract.md),
  [docs/operational.md](operational.md)).
- The image sets `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=true` (and
  `..._RUNATSTART=true`) in its environment (`docker/Dockerfile`). That environment default
  outranks `/config/config.yaml`, so in the container run-once is selected with
  `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false` (any YAML false spelling),
  not with `watchforchanges: false` in the config file. The mode is resolved by the exporter
  itself, not by the s6 script.
- `WATCHFORCHANGES=1` is rejected by the settings loader (confuse: `must be a bool, not int`;
  it was in 0.2.x too); use `true`/`false` ([ADR-0044](adr/0044-container-run-once-contract.md)).

### Container run-once

- With `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false` the container runs one
  pass and then **exits** ([ADR-0044](adr/0044-container-run-once-contract.md),
  [docker/README.md](../docker/README.md#run-once)). The 0.2.x "Skipping start of application"
  respawn loop is gone.
- Run-once containers must use `restart: "no"` (or be started by cron, a systemd timer or a
  Kubernetes Job). With `restart: always` or `unless-stopped`, Docker restarts the exited
  container, which turns run-once into a loop.
- The exit code reflects start-up failures only: 0 after the pass, 1 when the data path is
  missing. Export failures are logged at ERROR and do **not** change the exit code, so a
  scheduler cannot detect them from it.
- When both `runatstart` and `watchforchanges` are false, the exporter logs one WARNING that it
  has nothing to do.

### Exported-domain contract

- A domain is reported to the post-export hook (`TRAEFIK_CERTIFICATE_EXPORTER_EXPORTED_DOMAINS`)
  and to notifications only when its exported artifacts **changed** in that pass, not merely
  when they were written ([ADR-0043](adr/0043-export-commit-and-reporting-contract.md)).
- Unchanged certificates are no longer rewritten: a file is replaced only when its content
  changed, so modification times are stable. When nothing changed, neither the hook nor the
  notifications run.
- **If you relied on the hook firing every pass, stop.** In 0.2.x the hook and notifications
  ran after every pass, including every exporter start; in 0.3.0 they do not, and nothing
  restores that behaviour.
- One resolver's failure no longer drops the other resolvers' domains from the restart, the
  hook and notifications.
- A malformed or unexportable domain keeps its old files: its PEM files are not rotated.
- A key or `.pfx` file whose mode is looser than `0600` is rewritten (and its domain
  reported) on the first pass, even when its content is unchanged.
- When two resolvers (or a wildcard and its apex) map to the same exported files, the
  certificate that expires last is exported and the other is skipped with a warning, instead
  of the two overwriting each other on every pass.
- `postexportcommand` is treated as a secret: it is redacted in DEBUG dumps, and hook log
  lines name only the program, not its arguments.

### PKCS12

Source: `src/traefik_certificate_exporter/libs/certificate_exporter.py` (`build_pkcs12` and the
PEM writers).

- `pkcs12passphrase` works. In 0.2.x, setting it made every PKCS12 export fail and suppressed
  the restart, hook and notification for that domain.
- `.pfx` files now include the intermediate certificates.
- When encrypted, PKCS12 uses AES-256/SHA-256
  (`src/traefik_certificate_exporter/libs/certificate_exporter.py`). The consumer floor is
  Windows 10 1709+/Server 2019+, OpenSSL 3 or current macOS; **Windows Server 2016 and older
  cannot import an encrypted `.pfx`**.
- An empty `pkcs12passphrase` (`""`) means no passphrase: the `.pfx` is unencrypted.
- `cert.pem`/`chain.pem` are correct for single-certificate chains: `chain.pem` is empty when
  the store holds no intermediates, and `cert.pem` keeps its final newline.
- **`cert.pem` and `chain.pem` change once for every domain.** 0.2.x ended both with a blank
  line; 0.3.x ends them with one newline. The first 0.3.x pass rewrites both files for every
  domain. The certificates in them are the same, and `fullchain.pem` is unchanged. A consumer
  that compares file bytes or hashes sees one change per domain.

### Docker client

- The Docker client ignores the Docker CLI context (`docker context use …`): `DOCKER_HOST` or
  the default socket `unix:///var/run/docker.sock` is used (`from_env(use_context=False)` in
  `src/traefik_certificate_exporter/libs/docker.py`). This matters for PyPI installs on
  workstations with a non-default context.
- Docker Engine API 1.24 or newer is required (the docker-py 7.x floor).
- An unreachable Engine is reported as one start-up ERROR naming the endpoint, instead of the
  misleading `Not supported URL scheme http+docker` traceback.

### CA-agnostic ACME parsing

Source: `src/traefik_certificate_exporter/libs/certificate_exporter.py` (store-shape detection
and per-certificate decoding).

- Stores from any RFC 8555 CA (Let's Encrypt, ZeroSSL, Google Trust Services, step-ca, ...)
  are supported; the store shape is detected from its keys, not from the CA URL.
- Resolvers with `"Certificates": null` or `"Account": null` no longer abort the file.
- Invalid base64 in the store is reported per certificate instead of producing empty files.
- There is no size limit on `acme.json`; it is trusted Traefik output.

### Dependencies

- `requests`, `docker-pycreds` and `expandvars` are no longer install requirements of the
  package. If your own code in the same virtualenv imported them through this package,
  install them yourself (`requests` is still installed transitively, through `docker` and
  `apprise`). `pyyaml` is now declared (`pyproject.toml`).
- Refreshed: urllib3 ≥ 2.8.0 (security), requests ≥ 2.33 (transitive), idna ≥ 3.15,
  watchdog 6, cryptography 50.0.2, python-dotenv 1.2.x; base image
  `ghcr.io/linuxserver/baseimage-alpine:3.24` (new digest).

### Command line and logs

Source: `src/traefik_certificate_exporter/libs/cli_args.py` (strict parse, suggestions,
placeholders; [ADR-0025](adr/0025-strict-cli-parse-without-import-time-regression.md)) and
`src/traefik_certificate_exporter/libs/settings.py` (redaction and the settings dump).

- An unrecognised flag gets a `Did you mean …?` suggestion and a `--help` pointer; the exit
  code is still 2.
- `--help` shows readable placeholders (`PATH`, `DOMAIN`, `LEVEL`) instead of internal config
  paths; the `-c` help says it is the configuration file to load.
- Redacted Apprise URLs in DEBUG output keep their count and scheme
  (`tgram://***REDACTED***`).
- The DEBUG active-settings dump is now multi-line, indented JSON. **Log scrapers that parsed
  the old single-line dump must be updated.**

### Versioning and image tag naming

- The project stays on 0.x until it is declared stable, then releases 1.0.0.
- Release images are tagged `X.Y.Z`, `X.Y` and `latest` (0.3.0: `0.3.0`, `0.3`, `latest`).
  While the major version is 0 no bare `X` tag is written: the existing `:0` tag stays frozen
  at its last old-pipeline image and is not updated. From 1.0.0 the `:1` tag appears
  automatically, with no workflow change (`.github/workflows/release.yaml`,
  [ADR-0046](adr/0046-e014-pipeline-amendments.md)).
- Dev builds of `main` are tagged `X.Y.Z-dev.N`, `sha-<7>` and `dev`; the package carries
  `X.Y.Z.devN` ([docs/ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md#versions)).
- Images: `ghcr.io/ravensorb/traefik-certificate-exporter`,
  `docker.io/ravensorb/traefik-certificate-exporter` and
  `git.ravenwolf.org/ravensorb/traefik-certificate-exporter`, built for `amd64` and `arm64`.
  Packages: PyPI and the Gitea package index (`https://git.ravenwolf.org/api/packages/ravensorb/pypi`).

### Where releases come from

- GitHub is the release forge (ADR-0052): its `release` environment holds every publish
  setting, the Gitea registry and package index included, and every destination of a
  release publishes from that one run. A Gitea mirror holds no publish secret or variable,
  so a mirrored tag run there publishes no package or image (it still creates that forge's
  own release with its job token). One run per release keeps one image digest across every
  registry and one writer per tag (CI spine AD-9,
  [docs/ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md#releasing)).
- A fork may make Gitea its release forge instead; then it configures every destination
  there and none on GitHub, with the token mitigations of CI spine AD-13: protected `main`
  and `v*` tags limited to trusted accounts, project-scoped tokens, rotation after any
  untrusted push ([docs/ci/gitea-runners.md](ci/gitea-runners.md)).
- For forks and mirrors: a publish destination is enabled only when its token and every
  variable it needs are set. A partly configured destination is skipped with one warning
  naming what is missing; an unconfigured one is silent. The Gitea package index and the
  Gitea registry can be enabled separately
  ([docs/ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md#where-things-are-published)).
