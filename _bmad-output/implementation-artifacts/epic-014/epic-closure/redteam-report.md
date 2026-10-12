# RED TEAM FINDINGS REPORT

**Scope:** Epic E014: release 0.3.0 of traefik-certificate-exporter (both sprints), epic-level surface analysis
**Date:** 2026-10-12
**Analyst:** Red Team Agent (l3io-sec-redteam, orchestrator invocation, headless)

## SEVERITY SUMMARY

| Severity | Count |
|---|---|
| CRITICAL | 0 |
| HIGH | 1 |
| MEDIUM | 1 |
| LOW | 2 |
| OBSERVATION | 2 |

## Scope, seeds and widening

**Seeds read:**
- The cumulative `364cd49..HEAD` diff stat. Lockfiles were skipped as generated.
- Both sprint-level red-team reports.
- The open E013/E014 backlog in `state/issues.yaml`, including BL-E014-105..108.
- The live code of the epic's runtime path: `post_export.py`, `notify.py`, `docker.py` (restart rule, cooldown, client), and `certificate_exporter.py` (path whitelist, owner selection, `_atomic_write`, temp sweep, artifact index, PKCS12 build).
- The s6 scripts: init, run, finish, and `privilege-decision.sh`.
- ADR-0030 and ADR-0039.

The two sprint passes already covered the per-story code thoroughly, so this pass did not replay them. Everything they dispositioned (S01 RT-1..12, S02 RT-1..8, now BL-E014-055..060, 081..083, 088..094) and BL-E014-105..108 is not re-raised here.

**Widened to, and why:**

| Widened to | Why |
|---|---|
| The **published 0.3.0 image** (`ravensorb/traefik-certificate-exporter:0.3.0`), run locally against a throwaway `/config`, `/data` and `/certs` | Effective privilege is decided at runtime by the s6 chain, which includes the **base image's** init scripts, not only this repo's. The trust boundary between `/config` and the service account can only be checked on a running container. |
| Base-image `init-adduser/run`, `init-custom-files/run`, `init-envfile/run` (read inside the image) | To find which code changes ownership of `/config`, which no file in this repository does. |
| `docs/operational.md:294-298,410-425`, `docker/README.md:92-97` | These are the operator-facing statements of the `/config` trust boundary and of the PUID guidance. |
| `epic-014/sprint-02/closure/gitea-live-publish-2026-10-12.md`, `release-0.3.0-evidence.md`, `live-host-test-rwusdckrls6-2026-10-12.md`; `gh run view 38281339396` (GitHub release run for `v0.3.0`); PyPI JSON for 0.3.0; `git` tags | The release is part of the epic. How 0.3.0 actually reached each registry is a supply-chain fact that neither sprint pass saw, because both ran before the release. |
| `justfile:52-60` (`just act` contract) | To check the workstation-publish procedure against the repository's own stated contract. |

**Executed (all against the released image, in throwaway directories that were removed afterwards):**
1. A first boot in run-once mode with an `abc`-readable store. The service dropped to `abc`, and `/config` came up `drwxr-xr-x 911:911`.
2. As uid 911, replace `/config/config.yaml`, then reboot. The service ran as root, and the hook wrote `uid=0(root)` (RT-1).
3. A planted `glob.py`/`tempfile.py` in `/config` to test whether init's `python -` imports from `/config`. **It does not**: init's cwd is not `/config`, the drop still happened, and nothing was imported. No finding.
4. An `abc` rename of `/app/.venv`. Blocked on this host: overlayfs returned EXDEV and the copy fallback could not delete. This is noted in RT-1 as host-dependent.

**Platform research:** the cached `container-and-key-material.md` and `ci-cd-github-actions.md` (2026-10-06) are within the 30-day TTL. No live research was needed. The LinuxServer `lsiown abc:abc /config` behaviour was read directly from the shipped image rather than from documentation.

**Surface map (internal):**
- **Entry points:**
  - the ACME store under `/data` (watch events and run-at-start);
  - `/config/config.yaml` and the environment, which supply settings, `postexportcommand` and `appriseurls`;
  - CLI flags (PyPI install only, because the image fixes argv);
  - Docker container labels;
  - the forge triggers: push to `main`, `v*` tags, PRs;
  - the workstation `act` path.
- **Trust boundaries:**
  - `/config` versus the PUID account;
  - root versus `abc`, decided at init;
  - the Docker socket or a proxy;
  - the output volume, which consumers read and other writers can reach;
  - the hook process environment;
  - forge environments and registries.
- **Data flows:**
  - store → whitelisted name → paths → keys at 0600 → mtimes → restart rule → Engine API;
  - changed domains → hook env and Apprise body;
  - CI: build → hash hand-off → twine/buildx → indexes and registries.
- **Auth checkpoints:** there is no identity anywhere in the product. Authority comes only from file ownership, the privilege decision, and socket reachability. In CI it comes from environments, protected refs and token scope.

## FINDINGS

| Severity | ID | Title | Lens | Location |
|---|---|---|---|---|
| HIGH | RT-1 | `/config` is chowned to the PUID account on every boot by the base image, so the account the privilege drop is meant to contain can rewrite execution-equivalent config and get root on the next start (demonstrated) | DAR, INS, PBR | base image `/etc/s6-overlay/s6-rc.d/init-adduser/run:55`; contradicts `docs/adr/0030-*.md:89-91`, `docs/operational.md:418-420` |
| MEDIUM | RT-2 | 0.3.0 was published to Gitea from a workstation `act` run with an instance-admin token, split across two forges, against ADR-0039's own required mitigations; the Gitea image's revision is not the `v0.3.0` tag's commit | INS, DAR, PBR | `gitea-live-publish-2026-10-12.md:20-28,86-88`; `docs/adr/0039-*.md:170-179`; `justfile:52` |
| LOW | RT-3 | The post-export hook inherits the exporter's whole environment, including the PKCS12 passphrase and Apprise URLs | INS, DAR | `src/traefik_certificate_exporter/libs/post_export.py:81` |
| LOW | RT-4 | The product's two secret settings are accepted as argv flags, with no warning, while the epic made "no secret on argv" a mechanically enforced rule for CI | DAR | `src/traefik_certificate_exporter/libs/cli_args.py:112-135` |
| OBS | RT-5 | Verified good: the 0.3.0 wheel and sdist are byte-identical across PyPI (GitHub CI, `046016b`) and Gitea (workstation act, `c7394e2`) | PBR | PyPI JSON 0.3.0; `gitea-live-publish-2026-10-12.md:70` |
| OBS | RT-6 | Verified good: epic-level data flows from the untrusted store into the hook, notifications, restarts and paths are all whitelisted or recorded-path-only | EXT | `certificate_exporter.py:440-455,721-747`; `docker.py:78-81,242-275` |

---

### RT-1 (HIGH): `/config` is owned by the PUID account at runtime, so the account the drop contains can make the next start run its command as root

- **Lens:** DAR, INS, PBR
- **Where:** the LinuxServer base image's `init-adduser/run:53-57` runs unconditionally, unless `LSIO_READ_ONLY_FS` or `LSIO_NON_ROOT_USER` is set:
  ```
  lsiown abc:abc /app
  lsiown abc:abc /config
  lsiown abc:abc /defaults
  ```
  This repository's own init (`init-traefik-certificate-exporter-config/run`) runs after it and never takes `/config` back. The repository's statements say the opposite:
  - `docs/adr/0030-*.md:89-91`: "`/config` is deliberately **not** chowned: it stays root-owned because `settings.postexportcommand` makes it execution-equivalent configuration, and handing it to the account that runs the hook would re-open the loop this ADR closes."
  - `docs/operational.md:418-420`: "`/config` deliberately stays root-owned … the account that runs the hook must not be able to rewrite it."

  Nothing tests either claim. `tests/test_s6_privilege_drop.py` greps this repository's scripts and never sees the base image's init.
- **Evidence (executed against `ravensorb/traefik-certificate-exporter:0.3.0`):**
  1. First boot (run-once, store readable by `abc`) dropped to `abc`. Afterwards, `ls -lan /config` showed `drwxr-xr-x 911 911 .` and `-rw-r--r-- 0 0 config.yaml`.
  2. As uid 911, `mv -f new.yaml /config/config.yaml` succeeded, because the account owns the directory. The new file set `restartcontainers: true` and `postexportcommand: "/bin/sh -c \"id > /certs/pwned.txt\""`. The account also removed its own `/certs/le` to force a change.
  3. Next boot: init printed `WARNING: running as root because settings.restartcontainers is enabled…`. `pwned.txt` contained `uid=0(root) gid=0(root) groups=0(root),1(bin),2(daemon),3(sys),4(adm),6(disk),…`.

  The only config-file check, `_warn_if_group_or_world_writable` (`settings.py:275,343`), passed silently. The replaced file was `0644` and owned by 911: it is not group- or world-writable, it is simply owned by the wrong account.
- **Attack paths (this deployment model):**
  - **(a) Dropped mode.** The defence-in-depth case ADR-0030 exists for: code execution as `abc` inside the exporter. One file write plus any container (re)start defeats the drop. A Watchtower update counts as a restart, and Watchtower is active on the production host (`live-host-test-rwusdckrls6-2026-10-12.md:39`). So does a host reboot or a scheduled run-once. An s6 respawn alone does not: it re-reads the root-owned `/run/…/run-as-root`.
  - **(b) Root mode (`restartcontainers: true`, socket mounted), the most common restart deployment.** The chown happens anyway, so on the host the `/config` bind-mount directory is owned by the PUID's host uid. `docker/README.md:97` tells operators to set PUID to Traefik's uid; the LinuxServer convention is the operator's uid 1000. Any process with that host uid that can reach the directory sets `postexportcommand`, which the root exporter then runs, with the Engine socket. That is host root. In homelab stacks, file-manager, backup and code-server containers routinely run as PUID 1000 with the whole appdata tree mounted.
- **Impact:** the privilege boundary that ADR-0030 and `operational.md` promise does not exist in the shipped image. With the socket mounted, this is a host-uid-PUID → host-root escalation. Without the socket, it is `abc` → container root, which can read every key (already readable by `abc`) and every other volume.
- **Related, host-dependent:** `/app` is also owned by `abc` at runtime. Renaming the root-owned `/app/.venv` (and planting a venv that root then executes) failed on this host only because overlayfs returned EXDEV for the directory rename. On a host with overlay `redirect_dir=on`, the same ownership would allow it. `/defaults` is `abc`-owned too.
- **Why not CRITICAL:** both paths need a prior foothold, either as `abc` or as the PUID's uid on the host. Neither is reachable from the network on its own.
- **Recommendation:**
  1. In `init-traefik-certificate-exporter-config/run`, after the base init and before the decision, take the code-load paths back: `chown root:root /config /app /defaults && chmod 0755 /config`, and `chown root:root /config/config.yaml && chmod 0644` when the file exists. Do this in both modes, because path (b) is root mode.
  2. In `SettingsManager.loadFromFile`, when `os.geteuid() == 0`, refuse (or at least WARN loudly about) a config file or `.env` whose `st_uid != 0`. Also check its parent directory.
  3. Add a container test, in the style of the existing `tests/test_container_*.py`, that boots the image and asserts `stat /config` is `0:0`. This tests the running image rather than grepping scripts (global rules 3 and 4: the scope must include the base image's init).
  4. Correct ADR-0030:89-91 and `operational.md:418-420` until the fix lands.

### RT-2 (MEDIUM): 0.3.0 reached Gitea from a workstation act run with an instance-admin token, and the release spans two forges

- **Lens:** INS, DAR, PBR
- **Evidence:**
  - `gitea-live-publish-2026-10-12.md:3,20-28`: dev and 0.3.0 were published to `git.ravenwolf.org` by `act push` on a workstation, in a throwaway clone. The `v0.3.0` tag was created **only in that clone** and pushed to a bare repo in `/tmp`.
  - The same file, `:86-88`: "The token used is the maintainer's admin token, as on 2026-10-10. ADR-0039 recommends a scoped bot account for CI."
  - The real `v0.3.0` tag (`git for-each-ref`) points to `046016b`. The GitHub release run 38281339396 published PyPI and Docker Hub from `046016b`.
  - The Gitea image's `org.opencontainers.image.revision` is `c7394e26…` (`gitea-live-publish…:77`). Its digest is `sha256:244015fe…`; Docker Hub `0.3.0` is `sha256:e3be0498…`.

  This violates ADR-0039 three ways:
  - `:170-172`, "**One forge per release.** All destinations of a release publish from one forge's run". Here Gitea came from act, and PyPI and Docker Hub came from GitHub.
  - `:179`, "every token is scoped to this project only". An instance-admin token is not.
  - `justfile:52`, the `just act` contract: "No secrets or variables are passed, so every publishing destination stays disabled."

  The `validate-tag` ancestry gate ran against a bare repository that the operator created in `/tmp`. Protected-tag and protected-branch rules were never consulted.
- **Attack path:** the admin token was injected into an act job running on `ghcr.io/catthehacker/ubuntu:act-latest`. That is a mutable tag (`--pull=false` uses whatever was cached). The job also ran the ref-pinned `LiquidLogicLabs/*` actions after registry login (BL-E013-022). A compromise of either one would capture a token that administers **every repository and user on the Gitea instance**, not just this package. The run then also moved Gitea `:latest` with no forge-side record.
- **Impact:** the blast radius of BL-E013-022/029 grows from this project's packages to the whole forge. The released artifacts also lose their tie to a protected tag: anyone auditing Gitea `0.3.0` finds a revision that no `v0.3.0` tag points to, and no forge run that produced it.
- **Recommendation:**
  1. Rotate the Gitea admin token used on 2026-10-10 and 2026-10-12. It was in reach of non-hash-pinned code.
  2. Create a bot account scoped to this repository's package write, and use only that.
  3. Either forbid workstation publishing (ADR-0039 already implies it), or record it as an emergency path in an ADR, with the mitigations it needs: pinned runner image digest, scoped token, a tag that also exists on the forge.
  4. Re-publish Gitea `0.3.0` from the real tag via the forge, or add a note to the Gitea package recording the revision difference.

### RT-3 (LOW): The hook inherits the exporter's full environment, secrets included

- **Lens:** INS, DAR
- **Where:** `post_export.py:81` `env = os.environ.copy()`. In the image, `with-contenv` exports every container variable, including any `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_PKCS12PASSPHRASE`, `…_APPRISEURLS_n`, `…_POSTEXPORTCOMMAND` itself, `DOCKER_HOST`, and the values produced by the base image's `FILE__*` secrets (`init-envfile`).
- **Failure:** hooks are commonly third-party CLIs or scripts (`curl`, vendor reload tools, `ssh` wrappers) that log their environment on `-v`/debug, ship crash reports, or pass the environment on to their own children. The redaction work this epic did on dumps and stderr (S01 RT-6, RT-11) does not reach a secret that has been handed to the child process. Nothing in the README hook section (`README.md:105-125`) says the environment is inherited.
- **Recommendation:** build the hook environment from an allowlist: `PATH`, `HOME`, `LANG`/`LC_*`, `TZ`, plus the two `TRAEFIK_CERTIFICATE_EXPORTER_*` hook variables. Alternatively, strip every name the redaction registry (`SECRET_CONFIG_KEYS` → env names) marks secret. Document the result.

### RT-4 (LOW): Secret settings are accepted on argv with no warning

- **Lens:** DAR
- **Where:** `cli_args.py:112-135`: `--pkcs12-passphrase PASSPHRASE` and `--post-export-command COMMAND`. The help text of the second calls the value "Treated as a secret". Both predate E014, but this epic rewrote their help text and regenerated the README usage from it (`README.md:25,50-53`).
- **Failure:** on a PyPI/systemd install, any local user reads the values from `/proc/<pid>/cmdline` or `ps`. In S02 the epic made "a token never reaches argv" a mechanical rule for CI (`workflows-no-auth-header-argv`, the token on curl's stdin). The product's own secrets have no equivalent guidance. The image is not affected, because its command line is fixed to `-c /config/config.yaml`.
- **Recommendation:** add "visible to other local users via the process list; prefer the config file or the environment variable" to both help strings. Optionally, log a WARNING when either one arrives through argv.

### RT-5 (OBS): Verified good: reproducible 0.3.0 distributions across forges

PyPI's `traefik_certificate_exporter-0.3.0-py3-none-any.whl` has sha256 `6f8dd26a…a3df5`, and its sdist `39fbc9c4…f170`. These equal the Gitea files built by act from a different commit (`c7394e2`, which has no `src`/`docker`/`pyproject`/lock difference from `046016b`). The AD-17 hash hand-off and the deterministic build mean a package consumer can verify Gitea 0.3.0 against PyPI 0.3.0. RT-2's provenance gap is therefore limited to the image, not the Python distributions.

### RT-6 (OBS): Verified good: untrusted store values do not reach a dangerous sink across the epic's new flows

- Domain and resolver names are whitelisted by `_PATH_COMPONENT_PATTERN` (`certificate_exporter.py:440-445`, `\Z`-anchored, `[A-Za-z0-9_-]` labels) before they become a path, a hook env value (`EXPORTED_DOMAINS`, comma-joined), or an Apprise body.
- The restart rule only `stat`s recorded paths (`artifactMtime`, `:721-747`), and the label value is only compared, never joined.
- The hook runs with `shell=False` from `shlex.split` and a 30 s timeout.
- PKCS12 output uses `BestAvailableEncryption` (AES-256/SHA-256).
- The init `python -` runs from a non-`/config` cwd (executed check above).

No new path, command or log-injection sink was found in the epic's cross-sprint flows.

---

## Re-analysis note

The scope has no authentication code; authority is file ownership, the privilege decision, and the socket. The first pass, done code-only, found nothing above LOW beyond what the sprint passes had already filed. Following the method note in the sanctum (effective privilege outranks this repository's scripts), the second pass ran the **released image** and attacked the scope of the privilege guard rather than its rules. That is how RT-1 surfaced: the guard and its tests examine only this repository's init, and the ownership change comes from the base image's init. The third angle was the release itself (RT-2), which neither sprint pass could see.

Not found, and checked:
- init importing planted modules from `/config`;
- the `chown -h` sweep following symlinks (the hard-link variant is blocked by EXDEV across the bind mount and by `protected_hardlinks`);
- run-mode state tampering;
- secret leakage into logs beyond what is already filed.

## Platform best practices

The cached guidance holds:
- key files and PFX at 0600 (compliant);
- do not let the service account control its own code or config path (non-compliant, RT-1);
- treat any socket mount as host root (unchanged; S01 RT-3 fixed the samples);
- scope CI tokens to one project, and keep secrets out of reach of mutable-ref code (non-compliant for the workstation run, RT-2).

Citations are in `research-cache/container-and-key-material.md` (CIS Docker Benchmark, OWASP Docker Security Cheat Sheet) and `research-cache/ci-cd-github-actions.md` (GitHub Actions hardening guidance).

## EXECUTIVE SUMMARY

This pass covered E014 at the epic level, as released in 0.3.0:
- the Docker SDK 7.2 restart path with its mtime rule and cooldown;
- PKCS12 build, compare and write;
- CA-agnostic ACME parsing;
- settings, CLI and legacy detection;
- the post-export hook and Apprise notifications;
- the s6 run-once/watch lifecycle and the conditional privilege drop;
- the CI/CD supply-chain hardening and publish gating;
- the 0.3.0 release as actually carried out.

The stack is a Python CLI in a LinuxServer/s6 image. Its trust boundaries are `acme.json`, `/config`, the output volume, the Docker socket and the publishing forges.

**Overall risk: HIGH, because of one finding.** The code-level controls built across the two sprints hold up:
- path whitelisting;
- 0600 key material;
- recorded-path restarts;
- shell-free hook;
- redacted dumps;
- reproducible, hash-verified distributions.

The most dangerous finding is **RT-1**, a privilege boundary the documentation promises but the shipped image does not deliver. The LinuxServer base init chowns `/config` to the PUID account on every boot, so that account (or any host process running as that uid) can rewrite the execution-equivalent config. On the next start the service runs the attacker's command as root, and with the Engine socket mounted that is host root. This was demonstrated against the released image.

The most important recommendation: have this image's own init take `/config` (and `/app`, `/defaults`) back to `root:root` in both modes, refuse root-time config files that root does not own, and pin that with a container test that inspects the running image rather than this repository's scripts. Rotate the Gitea admin token used for the workstation publishes (RT-2).
