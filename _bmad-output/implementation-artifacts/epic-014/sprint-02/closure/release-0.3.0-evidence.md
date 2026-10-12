# Release 0.3.0 — evidence (E014-S02-005, pre-tag agent part)

Written by the E014-S02-005 story agent on 2026-10-11/12 (session l3io-pm-20261011T161302Z-43c8ef). E014-S02-007 appends its own sections. Release commit candidate: HEAD `6e230db` plus the uncommitted sprint-02 work (S02-001, -002, -003, -004, -006 and this story), as the working tree; sprint closure commits it. No tag, branch, release or package was created in the real repository or on any real forge or registry: every act run used a throwaway clone under `/tmp/e014-s02-005` and a throwaway local Gitea container (see AC 2). No secret value, prefix or length appears below.

## AC 1 — Preconditions

Row 1 (`pm-status show` for E014 S01, E014 S02, E013 S02):

```text
E014-S01-004 done   E014-S01-009 done   E014-S01-010 done
E014-S02-001 done   E014-S02-002 done   E014-S02-003 done   E014-S02-004 done   E014-S02-006 done
E014-S02-005 in-progress (this story)   E014-S02-007 ready-for-dev
E013-S02-001 in-progress
```

E013-S02-001 is **not** done. Its dependency was moved from this story to E014-S02-007 by the maintainer's commit `364cd49` ("docs(plan): move E013-S02-001 dependency from E014-S02-005 to E014-S02-007 — S02-005 ... re-verifies the Gitea dev path itself"); this story's `depends_on` no longer lists it, and AC 2 below is the Gitea re-verification. The AC 1/row 1 text still names it: a stale story line, recorded here rather than treated as a block.

Row 2 — CI spine AD-9 (`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`):

> 178: ### AD-9 — Configuration-gated destinations, one forge per release [ADOPTED]
>
> 188: **One release run per tag.** All destinations of a release publish from one forge's run, all-GitHub or all-Gitea. Every `PUBLISH_*` secret and variable lives on that forge only; the other forge holds none, so a mirrored run there is silent and publishes nothing [...] The forge release is created on the publishing forge. An all-Gitea release can publish to every destination [...] Not mechanically enforced: the per-release checklist compares secret names on both forges.

`just check` at the release commit candidate: see "Close-out" at the end of this file (row 17).

## AC 2 — Gitea re-verification (dev path)

**Deviation, recorded (BL-E014-004 and the dispatch rule "no package on any real forge/registry"):** no Gitea test token was in the environment, and the dispatch forbids publishing to the real `git.ravenwolf.org`. Row 12 was therefore run against a **throwaway local Gitea 1.24.7** (`docker.gitea.com/gitea:1.24-rootless`, container `tce-s005-gitea`, `http://localhost:3300`, user `ravensorb`, a `write:package`-only token created inside it and passed to act by process environment via `-s PUBLISH_GITEA_TOKEN`). It has both a PyPI index and a container registry, so the whole dev path ran, including the files check. The instance and everything in it were deleted afterwards (AC 5, row 14). The real-Gitea run remains available as the optional `act_runner` item of the maintainer checklist.

Command (`dev.yaml`, act 0.2.89, throwaway clone with a bare `origin`, story shorthands `clone`/`actrun`):

```sh
actrun push -W .github/workflows/dev.yaml -s PUBLISH_GITEA_TOKEN --var PUBLISH_GITEA_USERNAME=ravensorb \
  --var PUBLISH_GITEA_PYPI_URL=http://localhost:3300/api/packages/ravensorb/pypi \
  --var PUBLISH_GITEA_REGISTRY=localhost:3300 --var PUBLISH_GITEA_IMAGE=localhost:3300/ravensorb/traefik-certificate-exporter-test
```

Runs 1 and 2 exited 1 at `docker/build-push-action`: `dial tcp [::1]:3300: connect: connection refused` — the BuildKit container is not on the host network, so `localhost` was its own. Harness, not product. Run 3 applied, **in the clone only** (a separate clone-only commit; the repository's workflows are unchanged), the E014-S02-002 C-17 pattern to the `setup-buildx-action` `with:` block: `driver-opts: network=host` plus `buildkitd-config-inline` marking `localhost:3300` plain HTTP. Run 3: **exit 0**.

```text
[build/build/build] 🏁  Job succeeded
[dev/publish-package]   | Gitea package index enabled
[dev/publish-image  ]   | Gitea container registry enabled
[dev/publish-package] 🏁  Job succeeded
[dev/publish-image  ] 🏁  Job succeeded
grep -c 'partially configured' act-dev.log  ->  0     (no ::warning from a Destination configuration step)
[dev/publish-package] dist/traefik_certificate_exporter-0.2.1.dev22-py3-none-any.whl: expected ae1e1dfdd58f86af6dc711d76b75d90355f78a0b1382ff633ee705ecd3e56ced computed ae1e1dfd…
[dev/publish-package] dist/traefik_certificate_exporter-0.2.1.dev22-py3-none-any.whl: OK
[dev/publish-package] dist/traefik_certificate_exporter-0.2.1.dev22.tar.gz: OK
[dev/publish-image  ] dist/traefik_certificate_exporter-0.2.1.dev22-py3-none-any.whl: OK
[dev/publish-image  ] dist/traefik_certificate_exporter-0.2.1.dev22.tar.gz: OK
[dev/publish-package] ⭐ Run Main Upload to Gitea
[dev/publish-package]   | Uploading distributions to http://localhost:3300/api/packages/ravensorb/pypi
[dev/publish-package]   | Uploading traefik_certificate_exporter-0.2.1.dev22-py3-none-any.whl
[dev/publish-package]   | Uploading traefik_certificate_exporter-0.2.1.dev22.tar.gz
[dev/publish-package]   ✅  Success - Main Upload to Gitea
[dev/publish-image  ]   | #32 pushing manifest for localhost:3300/ravensorb/traefik-certificate-exporter-test:dev@sha256:abf35070458c71418be9e07132486d38fd6287fec888e31177209d0bbc623c9c
[dev/publish-image  ]   | Testing Docker Image: localhost:3300/ravensorb/traefik-certificate-exporter-test@sha256:abf35070458c71418be9e07132486d38fd6287fec888e31177209d0bbc623c9c
[dev/publish-image  ]   ✅  Success - Main LiquidLogicLabs/git-action-docker-test@v2
```

Files check sends its header on stdin: the step (`.github/workflows/dev.yaml:206`) is `code="$(printf 'Authorization: token %s\n' "$TWINE_PASSWORD" | curl -sS -o existing.json -w '%{http_code}' -H @- "$files_url")"`; in run 3 it took the `404` (new version) branch with an authenticated request and then uploaded both files. Published in the throwaway Gitea: PyPI `0.2.1.dev22` (and `0.2.1.dev21` from runs 1–2, whose package job succeeded), image tags `0.2.1-dev.22`, `dev`, `sha-99e4296`.

## AC 3 — Pre-release integration evidence

Row 3 — `just image && docker image inspect traefik-certificate-exporter:local --format '{{.Id}}'`: exit 0. Image id `sha256:fc42ebb52881338aaf3a8dcfb772f04859e0d1822f4f4fb8c92d72cf39bf8486` (built from wheel `traefik_certificate_exporter-0.2.1.dev20-py3-none-any.whl`, sha256 `5b942d0655a93bfd824171766bca295f91b1b468b3f27c674ea2c9a0b5b003d5`). A `--load` image has no registry digest; the image id is the identity. Observation: the local image's `org.opencontainers.image.version` label is the base image's (`4bf86442-ls13`); in the release path the metadata action's `labels:` set it (checked in AC 5).

Row 4 — `TCE_DOCKER_INTEGRATION=1 poetry run pytest -m integration -v -rs`: exit 0. All four modules collected, all PASSED, no skip (`-rs` printed no skip summary). FR-15 (newer-file restart, unchanged-store no-restart, crash recovery) is credited to `tests/test_container_restart.py` (ADR-0041), not `tests/libs/test_docker_engine.py`.

```text
collecting ... collected 466 items / 461 deselected / 5 selected

tests/libs/test_docker_engine.py::test_restart_labeled_container_against_a_real_engine PASSED [ 20%]
tests/test_container_pkcs12.py::test_the_image_exports_a_passphrase_protected_pfx_with_its_intermediate PASSED [ 40%]
tests/test_container_restart.py::test_the_image_restarts_only_on_change_and_recovers_a_lost_restart PASSED [ 60%]
tests/test_container_run_once.py::test_run_once_container_exits_zero_after_one_pass PASSED [ 80%]
tests/test_container_run_once.py::test_run_once_container_exits_one_for_a_missing_data_path PASSED [100%]

====================== 5 passed, 461 deselected in 44.75s ======================
```

Row 5 — first boot seeds `/config/config.yaml` (NFR-7). The row as written (`docker run --rm -v "$C":/config …:local; test -s "$C/config.yaml"`) uses watch mode, which never exits (BL-E014-003), and its host-side `test`/`ls` cannot read the directory, because init chowns `/config` to `abc` mode 0700 (`ls: cannot open directory … Permission denied`, exit 1 — recorded). Run instead in run-once mode with a timeout, checking the seed inside a container: `timeout 180 docker run --rm -e TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_WATCHFORCHANGES=false -v "$C":/config traefik-certificate-exporter:local`, then `docker run --rm -v "$C":/c --entrypoint sh …:local -c 'ls -la /c; test -s /c/config.yaml && echo seeded'`:

```text
Setting up sample config.yaml
WARNING: running as root because no file matches '*.json' under '/data' yet, so the ACME store cannot be proven readable by abc. [...]
Starting application (run-once mode)
... No certificate changed; no hook or notification
run-once pass finished with exit code 0; stopping container
exit=0
-rw-r--r-- 1 root root  742 Oct 12 02:23 config.yaml
seeded
```

Exit 0 is what S01-005 defines for a start-up whose data path exists (the image's empty `/data`); also covered by `test_run_once_container_exits_zero_after_one_pass`.

Row 6 — arm64 (qemu-aarch64 binfmt present on the host; nothing installed): `docker buildx build --builder default --platform linux/arm64 … -t traefik-certificate-exporter:arm64 .` then `docker run --rm --platform linux/arm64 --entrypoint traefik-certificate-exporter traefik-certificate-exporter:arm64 --help`: exit 0. Image `arm64 sha256:3d508d920047a5d8f77d45fdb7a74c27760da8ef01428c27d743ee83d8ba94f4`; output begins `usage: traefik-certificate-exporter [-h] [-c PATH] [-d PATH] [-w] [-fs GLOB]`. (`--builder default` because the host's selected builder is a docker-container builder that cannot `--load` into the local store for the run.)

Row 7 — wheel installs on both ends of `>=3.10,<3.15` (fresh `uv venv`s under `/tmp/e014-s02-005-py`, interpreters fetched by uv): exit 0.

```text
Python 3.10.20
py3.10 ok
Python 3.14.4
py3.14 ok
```

## AC 4 — Upgrade notes

`docs/upgrading.md` (new) has `## 0.2.0 → 0.3.0` with one `###` per required item; `README.md` links it (§"Releases and images") and `docs/README.md` lists it. The legacy table is rendered from `LEGACY_SETTING_NAMES` between `<!-- legacy-settings:begin -->`/`<!-- legacy-settings:end -->`; `legacy_settings` exposes no renderer, so `render_legacy_table()` lives in `tests/test_settings_surface.py` (its only consumer) and the comment above the markers names the regeneration command `poetry run python -m tests.test_settings_surface`. The file carries E014-S01-009's marker `tce-settings-scan: legacy-names-listed` (the derived legacy-location rule); no exclusion, scope entry or allowlist was added, and placeholders use the accepted forms (`…_SETTINGS_<KEY>`, `…_APPRISEURLS_<n>`).

Row 8 — `poetry run pytest -q tests/test_settings_surface.py::test_upgrading_lists_every_legacy_name`: passed; plants (each restored from a copy, `cmp` identical after): one row's name changed (`…_FLAT` → `…_FLATX`) → **failed**; the `settings.restartcontainer` row deleted → **failed**; the end marker removed (attacks the scope) → **failed**; restored → passed.

Row 9: one link in each index (`README.md:192`, `docs/README.md:18`); `docs/upgrading.md` heading `## 0.2.0 → 0.3.0`; every required item heading present (Restarts now take effect, Privilege model, Settings renames and fixes, Legacy setting names, Settings precedence and container run mode, Container run-once, Exported-domain contract, PKCS12, Docker client, CA-agnostic ACME parsing, Dependencies, Versioning and image tag naming, Where releases come from).

Row 11 — `docs/ci/pipeline-walkthrough.md` §"Releasing": line 271 adds "A release can run from either forge, one forge per release" with the reason (AD-10 one digest, AD-8 one writer per tag); line 280 already held the "zero destination warnings" checklist item (E014-S02-002).

Row 19: `CLI > env > config file > defaults` at `docs/upgrading.md:106`; `from any source` absent; `WATCHFORCHANGES` lines 110–121 give the env-var run-mode wording and the `WATCHFORCHANGES=1` rejection.

Row 10 / row 18: see the cross-read table below (61 rows against 47 `notes` lines; every closure-notes file with a release-notes section is cited; `execution-notes.md` is cited in rows 57–58).

## Upgrade-notes cross-read table

Sources (decision 5): the "0.3.0 release notes" subsections of E014-S01-001 … S01-010 and S02-001/002/006 (`notes` in the Verification shorthands prints the S01 bullets: 47 lines, sub-bullets included); the release-notes sections of the six closure notes files that have one (`notes-E014-S01-002/003/004/005/009/010.md`, which take precedence over their story's bullets); and `epic-014/execution-notes.md` §"Maintainer decisions during execution (2026-10-11)". Destinations are `###` headings under `## 0.2.0 → 0.3.0` in `docs/upgrading.md`. Every claim was checked against the working tree at the release-commit candidate (HEAD `6e230db` plus the uncommitted sprint-02 work).

| # | Source | Bullet (abridged) | Destination heading / disposition |
|---|---|---|---|
| 1 | E014-S01-001 story | restarts now work; 0.2.x SDK could not reach the Engine; labeled containers start restarting | Restarts now take effect |
| 2 | E014-S01-001 story | Docker CLI context ignored; `DOCKER_HOST` or default socket | Docker client (checked: `docker.from_env(use_context=False)`, `libs/docker.py:139`) |
| 3 | E014-S01-001 story | Engine API ≥ 1.24 | Docker client |
| 4 | E014-S01-001 story | start-up Engine check: INFO reachable / one ERROR | Restarts now take effect (last bullet; checked `libs/docker.py:159`) |
| 5 | E014-S01-001 story | unreachable Engine = one ERROR, no `http+docker` traceback | Docker client |
| 6 | E014-S01-002 story | `pkcs12passphrase` works | PKCS12 |
| 7 | E014-S01-002 story | `.pfx` includes intermediates | PKCS12 |
| 8 | E014-S01-002 story | `cert.pem`/`chain.pem` single-certificate fix | PKCS12 |
| 9 | E014-S01-002 story | unexportable domain no longer rotates its PEM files | Exported-domain contract ("keeps its old files") |
| 10 | E014-S01-002 story | AES-256/SHA-256 when encrypted; consumer floor | PKCS12 (checked `certificate_exporter.py:1198`) |
| 11 | E014-S01-002 story | empty passphrase = unencrypted | PKCS12 |
| 12 | E014-S01-002 story | unchanged certificates not rewritten; stable mtimes | Exported-domain contract |
| 13 | E014-S01-002 story | hook/notification domain list = changed domains | Exported-domain contract |
| 14 | E014-S01-002 story | first pass after upgrade rewrites every `.pfx`; one restart, hook and notification each | Restarts now take effect ("One-time post-upgrade effect") |
| 15 | notes-E014-S01-002.md | key/`.pfx` looser than 0600 rewritten and reported on first pass | Exported-domain contract (checked `_SECRET_FILE_MODE = 0o600`) |
| 16 | E014-S01-003 story | CA-agnostic parsing; shape from keys | CA-agnostic ACME parsing |
| 17 | E014-S01-003 story | `Certificates: null` / `Account: null` no longer abort | CA-agnostic ACME parsing |
| 18 | E014-S01-003 story | invalid base64 reported per certificate | CA-agnostic ACME parsing |
| 19 | E014-S01-003 story | one resolver's failure no longer drops others' domains | Exported-domain contract |
| 20 | E014-S01-003 story | no size limit on `acme.json` | CA-agnostic ACME parsing |
| 21 | notes-E014-S01-003.md | two resolvers mapping to the same files: latest expiry wins, other skipped with a warning | Exported-domain contract (checked `certificate_exporter.py:902-921`) |
| 22 | E014-S01-004 story + notes-E014-S01-004.md | `--restart-container` now enables restarts | Settings renames and fixes |
| 23 | E014-S01-004 story + notes-E014-S01-004.md | sample env names corrected; compose `version:` dropped; `CONFIGFILE`/`CONFIG_FILE` never worked (closure addition) | Settings renames and fixes (closure wording used) |
| 24 | E014-S01-004 story + notes-E014-S01-004.md | new `..._LOGGING_LEVEL`; invalid falls back to INFO; source logged | Settings renames and fixes (checked `app.py:93-102`, sources `cli`/`env`/`default`) |
| 25 | E014-S01-004 story + notes-E014-S01-004.md | `config.sample.yml` and seed config logging defaults | Settings renames and fixes |
| 26 | E014-S01-005 story | "honours `watchforchanges: false` from any source" | **Replaced** by notes-E014-S01-005.md's reworded bullet (row 27); "from any source" contradicts the env-over-file rule and is not used |
| 27 | notes-E014-S01-005.md | env var `..._WATCHFORCHANGES=false` selects run-once; env default outranks `/config/config.yaml`; resolved by the exporter | Settings precedence and container run mode; Container run-once |
| 28 | E014-S01-005 story | `restart: "no"`; `always` turns run-once into a loop | Container run-once |
| 29 | E014-S01-005 story | exit code 0 / 1 (missing data path); export failures do not change it | Container run-once (checked `app.py:42-48`; row 5 run shows `exit code 0`) |
| 30 | E014-S01-005 story | "Skipping start of application" loop gone | Container run-once (checked: no match in `src/`, `docker/`) |
| 31 | E014-S01-005 story | nothing-to-do WARNING | Container run-once (checked `app.py:195`) |
| 32 | notes-E014-S01-005.md | `WATCHFORCHANGES=1` rejected; use `true`/`false` | Settings precedence and container run mode |
| 33 | E014-S01-006 story | restarts take effect, only on change (heading bullet) | Restarts now take effect |
| 34 | E014-S01-006 story (sub) | every pass incl. start-up; newer-than-start; unchanged store restarts nothing | Restarts now take effect ("Only on change") |
| 34a | E014-S01-006 story (sub) | "`runatstart` stays on by default" | not carried: true for the image only (`docker/Dockerfile:129` sets `..._SETTINGS_RUNATSTART=true`); the package default is `false` (`config_default.yaml:16`), unchanged from 0.2.x; the image default is stated in Settings precedence and container run mode (review finding 2) |
| 35 | E014-S01-006 story (sub) | triggers: first export, renewal, deleted/edited file, cut-short restart | Restarts now take effect |
| 36 | E014-S01-006 story (sub) | first post-upgrade pass restarts every labeled container once | Restarts now take effect ("One-time post-upgrade effect") |
| 37 | E014-S01-006 story (sub) | 2 s clock slack; run against the local daemon | Restarts now take effect (checked `RESTART_MTIME_SLACK_SECONDS = 2`) |
| 38 | E014-S01-006 story | 5-minute cooldown defers instead of dropping | Restarts now take effect (checked `RESTART_COOLDOWN_SECONDS = 300`) |
| 39 | E014-S01-006 story | opt out: `restartcontainers: false` or remove the label | Restarts now take effect (checked `DOCKER_LABEL`, `libs/docker.py:27`) |
| 40 | E014-S01-007 story | dependency refresh versions | Dependencies |
| 41 | E014-S01-007 story | `requests`, `docker-pycreds`, `expandvars` no longer install requirements | Dependencies (checked `pyproject.toml`) |
| 42 | E014-S01-007 story | `pyyaml` declared | Dependencies (checked `pyproject.toml:28`) |
| 43 | E014-S01-007 story | base image refreshed | Dependencies |
| 44 | E014-S01-008 story | `Did you mean …?` for unrecognised flags; exit 2 | Command line and logs |
| 45 | E014-S01-008 story | readable `--help` placeholders | Command line and logs |
| 46 | E014-S01-008 story | redacted Apprise URLs keep count and scheme | Command line and logs |
| 47 | E014-S01-008 story | DEBUG settings dump multi-line JSON; scrapers must update | Command line and logs |
| 48 | E014-S01-009 story + notes-E014-S01-009.md | WARNING at start-up per legacy/misspelled name; replacement named; value never logged | Legacy setting names (plus the rendered table) |
| 49 | E014-S01-009 story + notes-E014-S01-009.md | unknown `..._*` env var gets nearest-name WARNING | Legacy setting names |
| 50 | E014-S01-010 story + notes-E014-S01-010.md | hook and notifications run only when a domain changed; 0.2.x ran every pass incl. start | Exported-domain contract ("If you relied on the hook firing every pass, stop") |
| 51 | E014-S01-010 story + notes-E014-S01-010.md | `postexportcommand` treated as a secret | Exported-domain contract |
| 52 | E014-S02-001 story | internal-only: SHA-frozen hooks, hash hand-off, hashed Poetry bootstrap, `publish` group | internal-only: CI/supply-chain mechanics with no operator-visible effect |
| 53 | E014-S02-002 story | destination enabled only when token + every variable set; one warning when partial | Where releases come from (fork/mirror bullet) |
| 54 | E014-S02-002 story | internal-only: fail-fast guard removed; flag renames in workflows | internal-only: workflow internals |
| 55 | E014-S02-006 story | release tags `X.Y.Z`, `X.Y`, `latest`; no `:0`; `:0` frozen; `:1` from 1.0.0 | Versioning and image tag naming (checked `release.yaml` metadata `enable=${{ !startsWith(…, '0.') }}`; dry run AC 5) |
| 56 | E014-S02-006 story | internal-only: token on stdin, pre-pull, guards, concurrency wording | internal-only: workflow internals |
| 57 | execution-notes.md (BL-E014-017 wontfix) | `CLI > env > config file > defaults` for all settings; image env default is the run-mode switch | Settings precedence and container run mode |
| 58 | execution-notes.md (import layering, SD-01-1) | strict import-linter layer order | internal-only: code structure, no operator effect |
| 59 | story decision / AC 4 (no source bullet) | privilege model | Privilege model. **Discrepancy, code wins:** the AC says "v0.2.0 dropped to PUID/PGID"; ADR-0030's amendment and the v0.2.0 service script say v0.2.0 always ran as root (`s6-setuidgid root`). The note states the code's version. |
| 60 | story decision / AC 4 | versioning 0.x then v1; dev tags; image names | Versioning and image tag naming |
| 61 | story decision / AC 4 (AD-9) | release from either forge, one forge per release | Where releases come from |

## AC 5 — Dry run

`release.yaml` under act 0.2.89 in the throwaway clone (bare `origin`), local-only tag `v0.3.0` (annotated, pushed to the bare origin only), payload `{"ref":"refs/tags/v0.3.0","repository":{"default_branch":"main"}}` (the corrected payload from `notes-E014-S02-002.md`, deviation 2). Only the Gitea registry enabled, TEST image on the throwaway local Gitea (AC 2 deviation): `-s PUBLISH_GITEA_TOKEN --var PUBLISH_GITEA_USERNAME=ravensorb --var PUBLISH_GITEA_REGISTRY=localhost:3300 --var PUBLISH_GITEA_IMAGE=localhost:3300/ravensorb/traefik-certificate-exporter-test`; `PUBLISH_GITEA_PYPI_URL` and `PUBLISH_RELEASE_TOKEN` unset. Same clone-only BuildKit `network=host` commit as AC 2 (tag on top of it). **Exit 0.**

```text
[release/validate-tag]   | tag=v0.3.0 commit=a4ff702a37f7a29df3375fe75231c2f7a955bacc default-branch=main
[release/validate-tag]   ✅  Success - Main Tag is on the default branch          (merge-base --is-ancestor against origin/main)
[release/validate-tag]   🚧  ::warning::Tag 'v0.3.0' not found in repository; parsing tag string only.   (tag-validate action under act; not a destination warning, as in notes-E014-S02-002 row 7)
[release/validate-tag] 🏁  Job succeeded
[build/build/build] ::set-output:: wheel-sha256=6f8dd26aba4d67316504fb9902471f05769007ba5a041ab791a0f0b9240a3df5
[build/build/build] ::set-output:: sdist-sha256=39fbc9c41be12b367b9a5c1716d8aa54a569803b0de0cd67f23832271f8be170
[build/build/build] 🏁  Job succeeded
[release/publish-image  ]   | Gitea container registry enabled
[release/publish-package]   | dist/traefik_certificate_exporter-0.3.0-py3-none-any.whl: OK
[release/publish-package]   | dist/traefik_certificate_exporter-0.3.0.tar.gz: OK
[release/publish-image  ]   | dist/traefik_certificate_exporter-0.3.0-py3-none-any.whl: OK
[release/publish-image  ]   | dist/traefik_certificate_exporter-0.3.0.tar.gz: OK
[release/release        ]   | dist/traefik_certificate_exporter-0.3.0-py3-none-any.whl: OK
[release/release        ]   | dist/traefik_certificate_exporter-0.3.0.tar.gz: OK
[release/publish-image  ]   ::group::Docker tags
[release/publish-image  ]   | localhost:3300/ravensorb/traefik-certificate-exporter-test:0.3
[release/publish-image  ]   | localhost:3300/ravensorb/traefik-certificate-exporter-test:0.3.0
[release/publish-image  ]   | localhost:3300/ravensorb/traefik-certificate-exporter-test:latest
pushing manifest for …-test:0.3.0@sha256:50d22ff4bbc6499e7d01ce71148ea7a6b458ead2e739cad4cd652adb54201d35
pushing manifest for …-test:0.3@sha256:50d22ff4bbc6499e7d01ce71148ea7a6b458ead2e739cad4cd652adb54201d35
pushing manifest for …-test:latest@sha256:50d22ff4bbc6499e7d01ce71148ea7a6b458ead2e739cad4cd652adb54201d35
[release/publish-image  ]   | Testing Docker Image: localhost:3300/ravensorb/traefik-certificate-exporter-test@sha256:50d22ff4bbc6499e7d01ce71148ea7a6b458ead2e739cad4cd652adb54201d35
[release/publish-image  ]   ✅  Success - Main LiquidLogicLabs/git-action-docker-test@v2
[release/publish-package] 🏁  Job succeeded
[release/publish-image  ] 🏁  Job succeeded
[release/release        ] 🏁  Job succeeded
grep -c 'partially configured' act-release.log  ->  0
```

After the run: `docker buildx imagetools inspect …-test:0.3.0` → one index `sha256:50d22ff4…201d35` with `linux/amd64` and `linux/arm64` (one multi-arch push, three tags, one digest); `…-test:0` → `not found` (no `:0` written).

**Defect found, filed (not fixed here): BL-E014-075 (High).** The metadata step reports `Docker image version 0.3`, and the pushed image's `org.opencontainers.image.version` label is **`0.3`**, not `0.3.0` (`docker image inspect … --format '{{index .Config.Labels "org.opencontainers.image.version"}}'` → `0.3`). E014-S02-007 AC 8 requires `0.3.0`. Per this story's error handling, it should be fixed in a patch commit on `main` (and the dry run's label check re-run) before the tag; the maintainer decides.

Row 14 — clean-up on the throwaway Gitea (token on stdin): every container version `204` (`0.3.0`, `0.3`, `latest`, `dev`, `sha-99e4296`, `0.2.1-dev.22` and 8 untagged `sha256:` manifests), final `jq length` → `0`; PyPI `0.2.1.dev21` and `0.2.1.dev22` → `204`, package count `0`. Then the Gitea container was removed (`docker rm -f tce-s005-gitea`), the token file deleted and the pulled test image removed. Nothing was published to `git.ravenwolf.org` or any other real registry.

## AC 6 — Maintainer checklist prepared

The next section holds all 20 checklist items of E014-S02-007, in its order, with concrete owner, repository, Gitea API URLs and image names. Row 15: 20 items here = 20 in E014-S02-007; no `<owner>`/`<repo>`/`{owner}`/`{repo}` placeholder (grep empty). The pre-tag agent sections AC 1–5 are complete, with one open defect for the maintainer to decide before tagging: **BL-E014-075** (image version label `0.3`, AC 5).

## Maintainer checklist (E014-S02-007)

Copied in order from E014-S02-007 §"Files in scope" (20 items), with concrete commands. GitHub repository `ravensorb/traefik-certificate-exporter`; Gitea `https://git.ravenwolf.org`, repository `ravensorb/traefik-certificate-exporter`, owner `ravensorb` (a user, not an organisation: the org-level secrets call applies only if that changes). Image names: `ghcr.io/ravensorb/traefik-certificate-exporter`, `docker.io/ravensorb/traefik-certificate-exporter`, `git.ravenwolf.org/ravensorb/traefik-certificate-exporter`. Gitea PyPI upload URL `https://git.ravenwolf.org/api/packages/ravensorb/pypi`. Secret values never appear here; Gitea calls read the token from the environment (`GITEA_READ_TOKEN`) and send it on stdin:

```sh
GH=ravensorb/traefik-certificate-exporter; G=https://git.ravenwolf.org; T=/tmp/e014-s02-007; mkdir -p "$T"
gitea() { printf 'Authorization: token %s\n' "$GITEA_READ_TOKEN" | curl -fsS -H @- "$@"; }
```

Pre-tag agent sections of E014-S02-005 (AC 1–5 above) are complete; see each section for its result.

- [ ] **Hygiene (F-01).** `gh secret list -R ravensorb/traefik-certificate-exporter` shows no repository-level secrets. If `DOCKERHUB_TOKEN`/`DOCKERHUB_USERNAME` are listed: `gh secret delete DOCKERHUB_TOKEN -R ravensorb/traefik-certificate-exporter; gh secret delete DOCKERHUB_USERNAME -R ravensorb/traefik-certificate-exporter`, then revoke that token at https://app.docker.com/settings/personal-access-tokens.
- [ ] **Hygiene (F-02), verification only (already applied).** `gh api repos/ravensorb/traefik-certificate-exporter/actions/permissions/workflow` shows `"default_workflow_permissions":"read"` and `"can_approve_pull_request_reviews":false`. Paste the output. If it differs, stop and file it (`pm-status append-issue`); do not re-apply silently.
- [ ] **Secret scanning (PRD #19).** `gh api repos/ravensorb/traefik-certificate-exporter --jq .security_and_analysis` shows `secret_scanning` and `secret_scanning_push_protection` `enabled`, or the gap is filed with `uv run -q _bmad/scripts/pm-status.py append-issue --file _bmad-output/implementation-artifacts/state/issues.yaml --epic 014 --sprint 02 --title "secret scanning / push protection not enabled" --source-phase verification --source-ref E014-S02-007 --severity High`.
- [ ] **Confirm the environments.** `gh api repos/ravensorb/traefik-certificate-exporter/environments --jq '.environments[].name'` lists `dev` and `release`; `gh api repos/ravensorb/traefik-certificate-exporter/environments/dev/deployment-branch-policies --jq '.branch_policies[] | [.name,.type]'` shows `["main","branch"]`; `gh api repos/ravensorb/traefik-certificate-exporter/environments/release/deployment-branch-policies --jq '.branch_policies[] | [.name,.type]'` shows `["v*","tag"]`; `gh api repos/ravensorb/traefik-certificate-exporter/rulesets --jq '.[] | [.name,.enforcement]'` shows `main` and `release-tags` `active` (walkthrough §"Forge settings the maintainer applies", step 5).
- [ ] **Live checks moved from E014-S02-001/002/006 (AC 3).** After the sprint's commits reach `main`: `gh run list -R ravensorb/traefik-certificate-exporter --workflow ci.yaml --event pull_request --limit 10 --json databaseId,headSha,conclusion,createdAt`, then `gh run view <run-id> -R ravensorb/traefik-certificate-exporter --log | grep -i -m3 'pull'` (base-image pre-pull); `gh secret list --env dev -R ravensorb/traefik-certificate-exporter; gh variable list --env dev -R ravensorb/traefik-certificate-exporter` (empty), `gh run list -R ravensorb/traefik-certificate-exporter --workflow dev.yaml --branch main --limit 5 --json databaseId,headSha,conclusion`, then `gh run view <run-id> -R ravensorb/traefik-certificate-exporter --log | grep -cE 'partially configured| enabled$'` → `0`. Record both run ids.
- [ ] **Dependabot keeps the bootstrap hashes (AG-12, AC 3).** `gh pr list -R ravensorb/traefik-certificate-exporter --app dependabot --state all --search 'requirements' --json number,title,state,url`; for the first PR touching `.github/requirements/poetry.txt`: `gh pr diff <pr-number> -R ravensorb/traefik-certificate-exporter | grep -cE '^\+.*--hash=sha256:'` (> 0) and `gh pr checks <pr-number> -R ravensorb/traefik-certificate-exporter` (`build / build` pass). Otherwise remove the `pip` entry for `/.github/requirements` in `.github/dependabot.yml` and file it. No PR yet: `uv run -q _bmad/scripts/pm-status.py append-issue --file _bmad-output/implementation-artifacts/state/issues.yaml --epic 014 --sprint 02 --title "observe first Dependabot pip PR on .github/requirements/poetry.txt keeps --hash lines" --source-phase verification --source-ref E014-S02-007 --severity Low`.
- [ ] **Optional: Gitea dev path on the real `act_runner`** (E014-S02-005 AC 2 accepted its local-act run instead). If chosen: on `https://git.ravenwolf.org/ravensorb/traefik-certificate-exporter/settings/actions/secrets` add `PUBLISH_GITEA_TOKEN` (a `write:package` test token) and on `.../settings/actions/variables` `PUBLISH_GITEA_USERNAME=ravensorb`, `PUBLISH_GITEA_REGISTRY=git.ravenwolf.org`, `PUBLISH_GITEA_IMAGE=git.ravenwolf.org/ravensorb/traefik-certificate-exporter-test`, at a commit including E014-S02-002 and E014-S02-006; run; delete the test package (`gitea -X DELETE "$G/api/v1/packages/ravensorb/container/traefik-certificate-exporter-test/<version>"` per version); then remove those secrets and variables, so Gitea holds no `PUBLISH_*` secret before tagging (`gitea "$G/api/v1/repos/ravensorb/traefik-certificate-exporter/actions/secrets" | jq -r '.[].name'` → no `PUBLISH_*`).
- [ ] **Record the publishing forge** (GitHub for 0.3.0) in the evidence file.
- [ ] **Gitea topology (only if Gitea is the publishing forge; option 2, 2026-10-11).** Not applicable when GitHub publishes. If chosen: record evidence of each AD-13 mitigation before any token is stored: `gitea "$G/api/v1/repos/ravensorb/traefik-certificate-exporter/branch_protections" | jq '.[] | {rule_name, enable_push, push_whitelist_usernames}'` (`main` protected, push limited to trusted accounts); `gitea "$G/api/v1/repos/ravensorb/traefik-certificate-exporter/tag_protections" | jq '.[] | {name_pattern, whitelist_usernames}'` (`v*` protected); every token project-scoped (PyPI project token, GHCR/Docker Hub tokens limited to this image, Gitea tokens from a bot or namespace account); the rotation rule written in the evidence file (rotate every token after any untrusted push). Then store the `PUBLISH_*` secrets as Gitea repository secrets and the variables as repository variables; GitHub then holds no `PUBLISH_*` secret (one-forge check with roles swapped).
- [ ] **Gitea side (GitHub topology).** `gitea "$G/api/v1/repos/ravensorb/traefik-certificate-exporter/actions/secrets" | jq -r '.[].name'` lists no `PUBLISH_*` name (owner `ravensorb` is a user, so there is no organisation secret list).
- [ ] **Review the S02-005 evidence:** the act dry run (sections AC 2 and AC 5 above; the throwaway Gitea with the test package was deleted), the pre-release integration, arm64 and Python-range results (section AC 3).
- [ ] **Confirm the upgrade notes** (`docs/upgrading.md`, E014-S02-005 AC 4) and the cross-read table above.
- [ ] **Create the tokens:** PyPI (project-scoped to `traefik-certificate-exporter` once the project exists; account-scoped only for a first upload, rotated after), GHCR (classic PAT with `write:packages` only, or fine-grained limited to this repository), Docker Hub (access token, Read & Write, repository `ravensorb/traefik-certificate-exporter`), Gitea (`write:package` only, from a bot or namespace account), GitHub release token (fine-grained, repository `ravensorb/traefik-certificate-exporter`, `Contents: Read and write`).
- [ ] **Populate the GitHub `release` environment secrets:** `for s in PUBLISH_GITEA_TOKEN PUBLISH_PYPI_TOKEN PUBLISH_GHCR_TOKEN PUBLISH_DOCKERHUB_TOKEN PUBLISH_RELEASE_TOKEN; do gh secret set "$s" --env release -R ravensorb/traefik-certificate-exporter; done` (each prompts for the value on stdin; never pass it as an argument).
- [ ] **Set the variables** on GitHub: `gh variable set PUBLISH_GITEA_USERNAME --body ravensorb -R ravensorb/traefik-certificate-exporter; gh variable set PUBLISH_GITEA_PYPI_URL --body https://git.ravenwolf.org/api/packages/ravensorb/pypi -R ravensorb/traefik-certificate-exporter; gh variable set PUBLISH_GITEA_REGISTRY --body git.ravenwolf.org -R ravensorb/traefik-certificate-exporter; gh variable set PUBLISH_GITEA_IMAGE --body git.ravenwolf.org/ravensorb/traefik-certificate-exporter -R ravensorb/traefik-certificate-exporter; gh variable set PUBLISH_GHCR_USERNAME --body ravensorb -R ravensorb/traefik-certificate-exporter; gh variable set PUBLISH_GHCR_IMAGE --body ghcr.io/ravensorb/traefik-certificate-exporter -R ravensorb/traefik-certificate-exporter; gh variable set PUBLISH_DOCKERHUB_USERNAME --body ravensorb --env release -R ravensorb/traefik-certificate-exporter; gh variable set PUBLISH_DOCKERHUB_IMAGE --body docker.io/ravensorb/traefik-certificate-exporter --env release -R ravensorb/traefik-certificate-exporter` (Docker Hub variables in `release` only if Docker Hub is release-only; walkthrough §"Where things are published"). Verify with `gh variable list -R ravensorb/traefik-certificate-exporter` and `gh variable list --env release -R ravensorb/traefik-certificate-exporter`.
- [ ] **One-forge check.** `gh secret list --env release -R ravensorb/traefik-certificate-exporter; gh secret list -R ravensorb/traefik-certificate-exporter; gitea "$G/api/v1/repos/ravensorb/traefik-certificate-exporter/actions/secrets" | jq -r '.[].name'`. Paste the names only. Pass: every `PUBLISH_*` secret is in the GitHub `release` environment only; GitHub repository level and Gitea list none. Do not tag on a failure.
- [ ] **Cut the release:** `git switch main && git pull && just release minor`. Confirm the printed base tag is `v0.2.x` and the new tag `v0.3.0`.
- [ ] **Watch the run:** `gh run list -R ravensorb/traefik-certificate-exporter --workflow release.yaml --limit 1 --json databaseId`, `gh run watch <run-id> -R ravensorb/traefik-certificate-exporter`, then `gh run view <run-id> -R ravensorb/traefik-certificate-exporter --log | grep -E 'partially configured| enabled$'`. Confirm **zero** `partially configured` lines and exactly six `enabled` lines (Gitea package index, PyPI, GHCR, Gitea container registry, Docker Hub, Forge release). A non-zero warning count means fix and re-run before announcing.
- [ ] **First-push fix-ups.** GHCR: https://github.com/users/ravensorb/packages/container/traefik-certificate-exporter/settings → visibility Public, and "Connect repository" `ravensorb/traefik-certificate-exporter`. Rotate the PyPI token to project-scoped if an account-scoped token was used (`gh secret set PUBLISH_PYPI_TOKEN --env release -R ravensorb/traefik-certificate-exporter`).
- [ ] **Run the verifications** in E014-S02-007 AC 7–9 (its Verification rows 13–18, which name every command) and paste the output.

## Close-out (AC 7)

- Row 17 — `just check`: exit 0. Every pre-commit hook Passed (including E014-S01-009's legacy-name scan over the marked `docs/upgrading.md`); `pip-audit (CI bootstrap requirements, ADR-0042)` Skipped (no files to check — expected until sprint closure commits `poetry.txt`); pytest `462 passed, 5 skipped` (the 5 opt-in integration tests, run separately in AC 3 row 4).
- Code review (`closure/review-E014-S02-005.md`): critical 0, high 0, medium 1 (uncited bullets in `docs/upgrading.md`), low 1 (cross-read row 34 dropped "`runatstart` stays on by default"). Both fixed in fix iteration 1 (source lines added per section; row 34a added). Re-checked with `poetry run pytest -q tests/test_settings_surface.py` (29 passed) and `pre-commit run --files` on the story's files (all Passed).
- Defects filed, not fixed here: **BL-E014-075** (High) — release image `org.opencontainers.image.version` label is `0.3`, not `0.3.0`. Blocks E014-S02-007 AC 8 as written; fix before tagging.
- Recorded deviations: AC 2/5 ran against a throwaway local Gitea (no test token in the environment; dispatch forbids real-registry packages; BL-E014-004); row 5 ran in run-once mode with an in-container check (BL-E014-003; the as-written row's host-side check fails on the 0700 `abc`-owned `/config` and is recorded with its real exit 1); E013-S02-001 is not `done` but is no longer a dependency (commit `364cd49`); a clone-only BuildKit `network=host` commit was needed for act to reach the local registry (E014-S02-002 C-17 pattern).
- Story-text defects for the planner: row 5's host-side `test -s "$C/config.yaml"` cannot pass on a correct image (init chowns `/config` to `abc` 0700); AC 1 / row 1 still list E013-S02-001; AC 4 says "v0.2.0 dropped to PUID/PGID" but ADR-0030's amendment says v0.2.0 always ran as root (the code wins; cross-read row 59).

## BL-E014-075 fix — AC 5 dry run re-run (sprint 02 closure, 2026-10-11)

Fix: `,priority=1000` on the `type=raw,value=${{ needs.build.outputs.image-version }}` line in `release.yaml` and `dev.yaml` (the action takes `org.opencontainers.image.version` from the highest-priority tag; `type=semver` defaults to 900, `type=raw` to 200). Enforced by the `workflows-version-label-priority` pygrep hook (passes on the fixed tree; planted removal in `dev.yaml` → hook exit 1).

Re-run: act 0.2.89, throwaway clone `/tmp/e014-s02-closure-bl075` (bare `origin`, working tree + fix committed as `wip`, then a clone-only BuildKit `network=host` + `http = true` commit for `localhost:5055`), annotated `v0.3.0` pushed to the bare origin only, payload `{"ref":"refs/tags/v0.3.0","repository":{"default_branch":"main"}}`. Registry: a throwaway `registry:2` on `127.0.0.1:5055` (no auth) in place of the throwaway Gitea; only the Gitea image destination enabled (`-s PUBLISH_GITEA_TOKEN` dummy, `--var PUBLISH_GITEA_USERNAME=ravensorb --var PUBLISH_GITEA_REGISTRY=localhost:5055 --var PUBLISH_GITEA_IMAGE=localhost:5055/ravensorb/traefik-certificate-exporter-test`). **act exit 0.**

```text
[release/validate-tag]   | tag=v0.3.0 commit=bbe02f94a7cae40b0cadb305c1a6289586d3cd19 default-branch=main
[release/validate-tag]   ✅  Success - Main Tag is on the default branch
[release/publish-image  ]   ::group::Docker image version
[release/publish-image  ]   | 0.3.0
[release/publish-image  ]   | localhost:5055/ravensorb/traefik-certificate-exporter-test:0.3.0
[release/publish-image  ]   | localhost:5055/ravensorb/traefik-certificate-exporter-test:0.3
[release/publish-image  ]   | localhost:5055/ravensorb/traefik-certificate-exporter-test:latest
[release/publish-image  ]   | org.opencontainers.image.version=0.3.0
validate-tag, build, publish-package, publish-image, release: Job succeeded
grep -c 'partially configured' act-release.log  ->  0
GET /v2/…-test/tags/list  ->  {"tags":["0.3","0.3.0","latest"]}
GET /v2/…-test/manifests/0  ->  404   (no :0 written)
imagetools inspect …-test:0.3.0  ->  index sha256:3cf207af823cb0f330b53f26f2319b2b5102928cd36130f1808e12d1a7f78999, linux/amd64 + linux/arm64
label org.opencontainers.image.version  ->  {'linux/amd64': '0.3.0', 'linux/arm64': '0.3.0'}
```

Clean-up: registry container `tce-e014-closure-reg` removed (`--rm`) and the clone deleted. Nothing was published to any real forge or registry.
