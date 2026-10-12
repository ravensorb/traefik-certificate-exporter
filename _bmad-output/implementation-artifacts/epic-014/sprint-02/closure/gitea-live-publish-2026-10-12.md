# Live Gitea publish from local act — dev and 0.3.0 release (2026-10-12)

The maintainer approved two live publishes to `git.ravenwolf.org`: a dev publish (`dev.yaml`), followed by the 0.3.0 release (`release.yaml` on tag `v0.3.0`). Both ran under local act in a throwaway clone of HEAD `c7394e2`.

Nothing was committed, tagged or pushed in the real repository. The real repository's `git status` is unchanged, and it has no `v0.3*` tag.

Tools: act 0.2.89, Docker 29.9.0. Gitea is at `https://git.ravenwolf.org`; its TLS certificate is publicly trusted.

## Setup

- `git clone --bare <repo> /tmp/tce-glp/origin.git` was made with full history and tags. The clone `/tmp/tce-glp/clone` was cloned from it, so `origin/main` is `c7394e2`.
- `git describe` gave `v0.2.0-23-gc7394e2`.
- Only these destination inputs were set:
  - Secret `PUBLISH_GITEA_TOKEN`. Its value came from Infisical `GITEA_TOKEN` through the process environment.
  - Variables `PUBLISH_GITEA_USERNAME=ravensorb`, `PUBLISH_GITEA_PYPI_URL=https://git.ravenwolf.org/api/packages/ravensorb/pypi`, `PUBLISH_GITEA_REGISTRY=git.ravenwolf.org`, `PUBLISH_GITEA_IMAGE=git.ravenwolf.org/ravensorb/traefik-certificate-exporter`.
  - No `PUBLISH_RELEASE_TOKEN` and no PyPI/TestPyPI/GHCR/Docker Hub input was set.
- The command was run inside a wrapper script under `infisical run --projectId 45365f20-… --env prod --silent -- <script>`:

```sh
export PUBLISH_GITEA_TOKEN="$GITEA_TOKEN"        # process env only, never argv
HOME=$(mktemp -d) act push -e <event.json> -W .github/workflows/<dev|release>.yaml \
  -P ubuntu-latest=ghcr.io/catthehacker/ubuntu:act-latest --pull=false --defaultbranch main \
  --artifact-server-path "$(mktemp -d)" -s PUBLISH_GITEA_TOKEN \
  --var PUBLISH_GITEA_USERNAME=ravensorb \
  --var PUBLISH_GITEA_PYPI_URL=https://git.ravenwolf.org/api/packages/ravensorb/pypi \
  --var PUBLISH_GITEA_REGISTRY=git.ravenwolf.org \
  --var PUBLISH_GITEA_IMAGE=git.ravenwolf.org/ravensorb/traefik-certificate-exporter
```

- Gitea API checks sent the token as a `curl -H @-` header read from stdin.
- After each run, `grep -cF "$GITEA_TOKEN"` over the act log returned `0` for both logs.

### Gitea state before the runs

| Item | State |
|---|---|
| PyPI versions | `0.2.1.dev13` only |
| `:latest` | `sha256:06e55cef4fabc2ba37e5843f920d5bb5b07555c2456288445c95562dbf3d2225`, created 2024-07-12 by the retired pipeline |
| `:dev` | `sha256:6e8deeee5c80…` (from the 2026-10-10 dev run) |
| `:0`, `:0.3`, `:0.3.0` | not found |

## (a) Dev publish — `dev.yaml`, push to `main`

Event: `{"ref":"refs/heads/main","repository":{"default_branch":"main"}}`

| Check | Result |
|---|---|
| act exit | **0**. Jobs `build`, `publish-package` and `publish-image` succeeded; tests `461 passed, 6 skipped`. |
| Dev version | package `0.2.1.dev23`, image `0.2.1-dev.23` |
| Destination steps | `Gitea package index enabled` and `Gitea container registry enabled`. `grep -c 'partially configured'` returned 0, and no `::warning`/`::error` came from the destination steps. |
| Hash checks | wheel `94a97fb5…8fb17`, sdist `4496850d…a7e1`, both `OK` |
| Gitea files (`/api/v1/packages/ravensorb/pypi/traefik-certificate-exporter/0.2.1.dev23/files`, HTTP 200) | `traefik_certificate_exporter-0.2.1.dev23-py3-none-any.whl` (69,273 B, sha256 `94a97fb5…`) and `traefik_certificate_exporter-0.2.1.dev23.tar.gz` (66,107 B, sha256 `4496850d…`) |
| Image tags (`docker buildx imagetools inspect`) | `dev`, `sha-c7394e2` and `0.2.1-dev.23` all point to `sha256:0e62c7e00eb2cc337a36be375d15f3420120ec22ca3619b8257f6555e58854b4`: linux/amd64 + linux/arm64, plus 2 attestation manifests (`unknown/unknown`) |

## (b) Release 0.3.0 — `release.yaml`, tag `v0.3.0`

- The annotated tag `v0.3.0` was created in the clone only, on `c7394e2`, which is the clone's `main` tip.
- It was pushed to the bare `/tmp/tce-glp/origin.git` only.
- Event: `{"ref":"refs/tags/v0.3.0","repository":{"default_branch":"main"}}`. The run had a 90-minute limit; the build was under QEMU for arm64.

| Check | Result |
|---|---|
| act exit | **0**. Jobs `validate-tag`, `build`, `publish-package`, `publish-image` and `release` succeeded. |
| validate-tag | `tag=v0.3.0 commit=c7394e26… default-branch=main`, then `tag=v0.3.0 highest=v0.3.0 is-latest=true` |
| Destination steps | Gitea package index and container registry `enabled`. `grep -c 'partially configured'` returned 0. |
| Forge release | The `release` job ran only Destination configuration, checkout, download-artifact and Verify dist hashes. The forge-release steps were skipped because `PUBLISH_RELEASE_TOKEN` was not set (intended). |
| Hash checks | wheel `6f8dd26a…a3df5` and sdist `39fbc9c4…f170` reported `expected == computed` and `OK` in `publish-package`, `publish-image` and `release` |
| Gitea files (`…/traefik-certificate-exporter/0.3.0/files`, HTTP 200) | `traefik_certificate_exporter-0.3.0-py3-none-any.whl` (69,203 B, sha256 `6f8dd26aba4d67316504fb9902471f05769007ba5a041ab791a0f0b9240a3df5`) and `traefik_certificate_exporter-0.3.0.tar.gz` (65,948 B, sha256 `39fbc9c41be12b367b9a5c1716d8aa54a569803b0de0cd67f23832271f8be170`) |
| `pip download traefik-certificate-exporter==0.3.0 --no-deps --index-url https://git.ravenwolf.org/api/packages/ravensorb/pypi/simple` | exit 0. Downloaded `traefik_certificate_exporter-0.3.0-py3-none-any.whl`; METADATA `Version: 0.3.0`; its sha256 equals the published wheel's. |
| Docker tags (metadata-action) | exactly `:0.3.0`, `:0.3` and `:latest` |
| Image digests | `0.3.0`, `0.3` and `latest` all point to `sha256:244015feba99fd9c529940beb27df8bf91f347d14b3cf7a2b1a93f00f81a7f74`: linux/amd64 + linux/arm64, plus 2 attestation manifests |
| `:0` | **not found**, both before and after the run. No `:0` existed from the retired pipeline, and this run created none. |
| `:latest` | moved from the 2024 `sha256:06e55cef…` to `sha256:244015fe…`, which is intended for the highest release |
| Labels | `org.opencontainers.image.version` is `0.3.0` on linux/amd64 and on linux/arm64; `org.opencontainers.image.revision` is `c7394e26e0958a7d113e5d70d33b476e05a08d81` on both |
| Smoke | `docker run --rm --entrypoint traefik-certificate-exporter git.ravenwolf.org/ravensorb/traefik-certificate-exporter:0.3.0 --help` exit **0** (argparse usage printed). The same with `--platform linux/arm64` also exited 0. |

### Gitea container tags after both runs (newest first, digest-only entries omitted)

`latest`, `0.3`, `0.3.0` (10:53:36Z); `sha-c7394e2`, `dev`, `0.2.1-dev.23` (10:39:33Z); then the older tags, unchanged: `sha-9f9398c`, `0.2.1-dev.13`, `202407120203`, `0.1.3`, `v0.1.0.0`, `ef1677b`, `5f65c81`, `644004b`, `v0.0.9.2`, `v0.0.10.0`, `990209b`, `3f14b25`.

## Notes

- validate-tag printed `::warning::Tag 'v0.3.0' not found in repository; parsing tag string only.` This is a known act-only message from the tag-validate action (see `local-release-test-2026-10-12.md`). It is not a destination warning.
- The `v0.3.0` tag exists only in the deleted clone. The real repository, and any forge, still has no `v0.3.0` git tag. Gitea now holds package `0.3.0` and image `0.3.0`; a real tag will be needed when the release is cut on a forge.
- The token used is the maintainer's admin token, as on 2026-10-10. ADR-0039 recommends a scoped bot account for CI.

## Clean-up

- Deleted: `/tmp/tce-glp/clone`, `/tmp/tce-glp/origin.git`, the temporary act HOME and artifact directories, the pip download directory and the helper scripts.
- `docker rmi` was run on the pulled `:0.3.0` image.
- Act containers and buildx builders that predate this session (2 days old) were left in place.
- Logs (token-free, as checked above) were kept: `/tmp/tce-glp/logs/act-dev.log`, `/tmp/tce-glp/logs/act-release-v0.3.0.log`, `/tmp/tce-glp/logs/smoke.txt`.
