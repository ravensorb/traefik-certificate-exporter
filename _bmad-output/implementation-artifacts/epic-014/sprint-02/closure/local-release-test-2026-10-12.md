# Local 0.3.0 release test — 2026-10-12

Tree under test: HEAD `e410285` plus the uncommitted working tree. That tree contains the AR-3 `latest` gate in `release.yaml`: the `validate-tag` step "Is this the highest release tag" with the `is-latest` output, `publish-image` needing `[validate-tag, build]`, and `type=raw,value=latest,enable=${{ needs.validate-tag.outputs.is-latest == 'true' }}`. It also contains the `workflows-latest-tag-gated` pre-commit hook.

Nothing was committed, tagged or pushed in the real repository, and nothing was published to any real forge or registry. The real repository's `git status` is unchanged, and it has no `v0.3.0` or `v0.2.9` tag.

Tools: act 0.2.89, Docker 29.9.0, Poetry 2.4.2.

## 1. Local build and image tests (real repository, no git changes)

| Command | Exit | Result |
|---|---|---|
| `just image` | 0 | Built `traefik-certificate-exporter:local` from the wheel `traefik_certificate_exporter-0.2.1.dev22-py3-none-any.whl`, image `sha256:c94b5416…3d87e`. |
| `TCE_DOCKER_INTEGRATION=1 poetry run pytest -q -m integration -rs` | 0 | **5 passed, 0 skipped**, 462 deselected, 43.4 s. Every integration module ran: `tests/libs/test_docker_engine.py`, `tests/test_container_pkcs12.py`, `tests/test_container_restart.py`, `tests/test_container_run_once.py` (2 tests). |
| `docker run --rm traefik-certificate-exporter:local --help` (as requested) | **127** | s6 init ran, then failed with `/run/s6/basedir/scripts/rc.init: line 91: --help: not found`. See deviation D1. |
| `docker run --rm --entrypoint traefik-certificate-exporter traefik-certificate-exporter:local --help` (the form in `docker/README.md:41`) | 0 | Printed the argparse usage (`usage: traefik-certificate-exporter [-h] [-c PATH] …`). |
| Installed version in the image (`importlib.metadata.version`) | 0 | `0.2.1.dev22` (dev version, as expected for a local build) |
| `org.opencontainers.image.version` label on `:local` | — | **`4bf86442-ls13`**. See deviation D2. |

## 2. act release dry run #1: `v0.3.0` on the clone's `main` tip

Setup:

- Clone `/tmp/tce-lrt/clone`, cloned from a bare `/tmp/tce-lrt/origin.git`, with full history.
- Commit `562a8bb` holds the working tree, applied as `git diff HEAD`.
- Commit `174d19d` is clone-only. It replaces `config: ${{ steps.ca.outputs.buildkit-path }}` in `setup-buildx-action` with `driver-opts: network=host` and `buildkitd-config-inline` `[registry."localhost:5055"] http = true`.
- Commit `059ddac` is an empty clone-only commit and is the `main` tip.
- The annotated `v0.3.0` tag is on `059ddac` and was pushed to the bare origin only.
- Registry: `registry:2` as container `tce-lrt-reg` on `127.0.0.1:5055`, without auth.

Command, run in the clone:

```sh
PUBLISH_GITEA_TOKEN=dummy HOME=$(mktemp -d) act push -e event-v0.3.0.json \
  -W .github/workflows/release.yaml -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest \
  --pull=false --defaultbranch main --artifact-server-path "$(mktemp -d)" \
  -s PUBLISH_GITEA_TOKEN --var PUBLISH_GITEA_USERNAME=ravensorb \
  --var PUBLISH_GITEA_REGISTRY=localhost:5055 \
  --var PUBLISH_GITEA_IMAGE=localhost:5055/ravensorb/traefik-certificate-exporter-test
# event-v0.3.0.json: {"ref":"refs/tags/v0.3.0","repository":{"default_branch":"main"}}
```

The first attempt was killed by my own 10-minute shell timeout during the emulated arm64 `pip install poetry`, which logged `context canceled`. That was the harness, not the product. The leftover act and buildkit containers were removed, and the re-run had a 90-minute limit.

Result of the re-run: **act exit 0.**

```text
[release/validate-tag]   | tag=v0.3.0 highest=v0.3.0 is-latest=true
validate-tag, build, publish-package, publish-image, release: Job succeeded
grep -c 'partially configured'  ->  0
Docker tags: …-test:0.3.0, …-test:0.3, …-test:latest
GET /v2/…-test/tags/list  ->  {"tags":["0.3","0.3.0","latest"]}
0.3.0 / 0.3 / latest  ->  sha256:4e4be2f594273a15d3ea89cf1afb400d4f6f37a202633b5b98af3c3083ddfbfc
GET /v2/…-test/manifests/0  ->  404
org.opencontainers.image.version: linux/amd64 0.3.0 (sha256:4e8e90c5…), linux/arm64 0.3.0 (sha256:184aa9d7…)
org.opencontainers.image.revision: 059ddac0f4afc747dfea40e42fa289f51640a64a (both platforms)
```

Labels were read from the registry API: index → per-platform manifest → config blob.

## 3. act release dry run #2: gate proof with `v0.2.9` on an older ancestor commit

Setup, in the same clone and with the registry still holding run #1:

- The annotated `v0.2.9` tag is on `174d19d`, one commit behind `main`, and was pushed to the bare origin.
- `git merge-base --is-ancestor v0.2.9 origin/main` returned true.
- `git diff v0.2.9 v0.3.0` is empty, so both runs used identical workflow files.
- The clone was checked out detached at `v0.2.9`, so the build version and `HEAD` match the tag.
- Same command as run #1, with the event `{"ref":"refs/tags/v0.2.9","repository":{"default_branch":"main"}}`.

Result: **act exit 0.**

```text
[release/validate-tag]   | tag=v0.2.9 commit=174d19d2cc4527f5ab726202d552001f845c04b0 default-branch=main
[release/validate-tag]   | tag=v0.2.9 highest=v0.3.0 is-latest=false
validate-tag, build, publish-package, publish-image, release: Job succeeded
grep -c 'partially configured'  ->  0
Docker tags: …-test:0.2.9, …-test:0.2          (no latest line)
GET /v2/…-test/tags/list  ->  {"tags":["0.2","0.3","0.2.9","0.3.0","latest"]}
0.2.9 / 0.2  ->  sha256:41bf1a7349e958a82c4e69c6bc73d21bf2a22a2c85a0969dae41c3ce5fb57804
0.2.9 version label: linux/amd64 0.2.9, linux/arm64 0.2.9 (revision 174d19d…)
```

`latest` digest before and after run #2:

| Tag | After run #1 | After run #2 |
|---|---|---|
| `latest` | `sha256:4e4be2f5…ddfbfc` | `sha256:4e4be2f5…ddfbfc` (unchanged; labels still 0.3.0 / rev 059ddac on both arches) |
| `0.3.0`, `0.3` | `sha256:4e4be2f5…ddfbfc` | unchanged |
| `0` | 404 | 404 |

The gate holds: an older release writes its `X.Y.Z` and `X.Y` tags and leaves `latest` on the highest release.

### Hook check (`workflows-latest-tag-gated`)

- On the real tree, `poetry run pre-commit run workflows-latest-tag-gated --all-files` printed `Passed` and exited 0.
- In the clone, I planted an ungated `type=raw,value=latest` line in `release.yaml` and ran the hook with the venv's `pre-commit` from the clone. It failed with **exit 1** and reported `.github/workflows/release.yaml:472`. The plant was then reverted.
- Harness note: my first planted run used `poetry -C <repo>`. Poetry's `-C` changes the working directory to the real repository, so the hook checked the real file and passed. That run is not evidence and is not counted.

## 4. Clean-up

- `docker rm -f tce-lrt-reg` removed the registry and every image it held.
- The clone `/tmp/tce-lrt/clone` and the bare `/tmp/tce-lrt/origin.git` were deleted, together with the helper script.
- The leftover containers from the killed first attempt (`act-release-publish-image-…` and `buildx_buildkit_builder-3664eb7d…`) were removed.
- Two older buildx builders were left in place, because they predate this session (created 2026-05-14 and 2026-08-31).
- Logs are kept in `/tmp/tce-lrt/`: `act-release-v0.3.0.log`, `act-release-v0.2.9.log`, `integration.log`, `just-image.log`.

## Deviations and findings

- **D1: the `--help` smoke as written exits 127. This is not an image defect.** The image's entrypoint is `/init` (s6-overlay). s6 treats CMD arguments as a command to exec after init, so a bare `--help` is run as a program and is not found. The supported form, documented in `docker/README.md:41`, is `--entrypoint traefik-certificate-exporter … --help`, and it exits 0.

  Proposed fix (optional, maintainer's call): use the documented form in any release checklist. If a bare `docker run IMAGE --help` should work, that would need an s6 CMD/arguments design change, which belongs in a separate story.

- **D2: the local `just image` build carries the linuxserver base image's labels.** The label is `org.opencontainers.image.version=4bf86442-ls13`, and title, source and revision also describe `docker-baseimage-alpine`. `docker/Dockerfile` has no `LABEL` instruction, and `just image` passes no `--label`.

  CI is not affected: `docker/metadata-action` passes `--label org.opencontainers.image.version=…`, which gave `0.3.0` and `0.2.9` above.

  Impact: a locally built image is mislabelled as the base image. Proposed fix: add `--label org.opencontainers.image.version="$version" --label org.opencontainers.image.revision="$(git rev-parse HEAD)"` to the `image` recipe in `justfile`, or add a `LABEL` in the Dockerfile's runtime stage that uses the existing `VERSION`/`REVISION` args. The Dockerfile route would also cover any other direct `docker build`. Not changed here.

- **D3: the release dry run takes more than 10 minutes under act**, because the arm64 build runs under QEMU emulation. Allow at least 30 minutes for an unattended run.

- Unchanged from earlier runs: under act, the tag-validate action prints `Tag 'v…' not found in repository; parsing tag string only` (seen in the 2026-10-11 evidence). It is not a destination warning.
