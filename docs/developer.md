# Developer Guide — traefik-certificate-exporter

## Prerequisites

- Python compatible with the `^3.10` constraint in `pyproject.toml`.
- No repository interpreter pin exists; Poetry uses the active compatible Python interpreter.
- Poetry 2.4.2 (the tested baseline) or a compatible release to create the project environment.
- `just` 1.58.0 (the tested baseline) for the optional local command facade.
- Docker with Buildx for the `image` recipe.
- `act` plus Docker with Buildx for the optional local verifier run.

Install the Poetry-managed project and development tools with either `just install` or its
authoritative command:

```bash
poetry install
```

No generated requirements file or separately maintained dependency list is used.

## Local command facade

Run `just --list` from the repository root to see the supported recipes.

| Recipe | Purpose and delegate | Prerequisites | Produced files or state |
|---|---|---|---|
| `just install` | Runs `poetry install`. | Python and Poetry | The project Poetry environment. |
| `just lint` | Runs `poetry check --lock`, then every configured pre-commit hook. | Installed development environment | Hook caches only; source files may be formatted by configured hooks. |
| `just test` | Runs `poetry run pytest`. | Installed development environment | Pytest's configured local cache. |
| `just check` | Requires both `lint` and `test`; it duplicates neither command body. | Installed development environment | Only the underlying tool outputs. |
| `just test-local` | Delegates to `docker/act-build.sh`, which invokes the governed verifier's direct `workflow_dispatch` entry point. | Poetry, `act`, Docker, and Buildx | Verifier outputs plus `act-build-traefik-certificate-exporter.log`; no publication. |
| `just release-dry-run <bump>` | Delegates a read-only `major`, `minor`, or `patch` release check to `scripts/release_version.py`. | Clean, synchronized release branch; Git, Poetry, and `just` | Console report only. |
| `just release <bump>` | Delegates guarded preparation and atomic publication to `scripts/release_version.py --push`. | Dry-run preconditions plus remote push access | One local release commit/tag and, on success, the corresponding two remote refs. |
| `just release-resume` | Revalidates and atomically publishes an existing local release identity. | A single valid unpushed release commit and exact annotated tag | The existing branch/tag refs on the remote; no new local identity. |
| `just build` | Requires `check`, runs a clean Poetry build, requires one wheel and one sdist, and validates both with Twine. | Installed development environment | `dist/*.whl` and `dist/*.tar.gz`. |
| `just image` | Requires `build`, derives the exact wheel inputs, and runs the shared Bake `image` target. | Docker Buildx plus build prerequisites | Locally loaded `traefik-certificate-exporter:local`. |

The non-release recipes are local validation/build conveniences and perform no publication.
Release recipes contain no version arithmetic or credentials; they only delegate to the guarded
Python transaction. CI invokes the authoritative build tools and `docker-bake.hcl` directly; CI
does not install or invoke `just`.

## Validate CI locally

Run the same reusable verifier used by pull requests from a clean checkout:

```bash
just test-local
```

The wrapper passes channel `ci`, the committed Poetry version, and the full current Git SHA to
`act workflow_dispatch -W .github/workflows/verify-build.yaml`. It supplies no registry, package,
forge, or OIDC publication credential. The workflow runs strict failure handling, so a failed
`act` process remains a failed command even though its output is also written to a log.

This local run validates the verifier job graph; it does **not** validate the top-level
pull-request orchestration DAG in `.github/workflows/ci.yaml`. Run the configured actionlint and
workflow-policy pre-commit hooks for syntax and contract validation. GitHub and Gitea forge runs
remain the conformance checks for event delivery, concurrency cancellation, permissions, and the
job-level reusable-workflow call.

The governed verifier allows external actions owned only by `actions`, `docker`, `pypa`, and
`LiquidLogicLabs`; another owner requires an approved ADR or architecture update. Maintained
floating major aliases are used where available. Upstream documentation was rechecked on
2026-09-01 for `actions/checkout@v7`, `actions/setup-python@v7`,
`docker/setup-buildx-action@v4`, and `LiquidLogicLabs/git-action-docker-test@v2`. The deliberate
artifact-transfer compatibility baseline remains the paired `actions/upload-artifact@v4` and
`actions/download-artifact@v4` majors until a different pair passes both GitHub and Gitea
conformance. Dependabot proposes action, Poetry/Python, and `/docker` dependency updates, but
major action changes remain normal review-required pull requests; automation does not merge them.

## Prepare and publish a release

The committed `[tool.poetry].version` in `pyproject.toml` is the package-version authority. Before
preparing a release, the helper requires:

- a clean working tree and configured Git author/committer identity;
- the checked-out branch to be the default branch advertised by `origin`;
- local `HEAD` to equal the current remote default-branch tip;
- local exact stable tags (`vMAJOR.MINOR.PATCH`) to match the remote history completely; and
- the greatest stable tag to equal the committed Poetry version.

Create a repository-local identity if one is not configured, then inspect the starting state:

```bash
git config user.name "Your Name"
git config user.email "you@example.com"
git status --short
git branch --show-current
git ls-remote --symref origin HEAD
git tag --list 'v*' --sort=-v:refname
poetry version --short
```

Start with one of the only accepted bump kinds:

```bash
just release-dry-run patch
```

The dry-run performs the read-only preconditions and asks Poetry to calculate the next version in
dry-run mode. It prints the proposed version, predictable commit message, annotated exact tag, and
the exact atomic two-ref push command. It does not change a file, index entry, commit, tag, or
remote ref.

For preparation without remote publication, invoke the helper directly:

```bash
poetry run python scripts/release_version.py patch
```

Poetry updates the committed version, `just check` validates that changed tree, and the helper
creates one `chore(release): vMAJOR.MINOR.PATCH` commit plus an annotated
`vMAJOR.MINOR.PATCH` tag. It prints, but does not execute:

```text
git push --atomic origin HEAD:<default-branch> refs/tags/vMAJOR.MINOR.PATCH
```

Inspect that local identity safely with `git status --short`, `git show --stat --decorate HEAD`,
`git cat-file -t vMAJOR.MINOR.PATCH`, and `git rev-parse 'vMAJOR.MINOR.PATCH^{}'`.

To prepare and publish in one guarded transaction, run `just release patch`. Immediately before
mutation the helper refetches and revalidates the remote branch tip, remote tag absence, local
commit, committed Poetry version, and annotated tag. It then issues exactly one atomic branch/tag
push. It never broad-pushes tags, forces a ref, splits the two pushes, or falls back when the remote
does not support atomic publication.

## Build package distributions

```bash
just build
```

Poetry builds one wheel and one source distribution into `dist/`; Twine validates the metadata
and rendering of both artifacts. `poetry-dynamic-versioning` is present but currently disabled,
so local artifacts use the committed Poetry version.

## Build the native image

```bash
just image
```

The recipe supplies the local wheel path and SHA-256, committed package version, and full Git
revision to `docker buildx bake image`. Bake owns the Docker context, Dockerfile, runtime target,
pinned base, pinned builder Poetry version, labels, and local-load output. See
[docker/README.md](../docker/README.md) for the direct Bake interface and smoke-test commands.

The image builder deliberately cannot fall back to PyPI or a private package index for the
application. It installs only the supplied, hash-verified wheel, ensuring the image contains the
same package artifact that local and CI checks validated.

## Run locally

```bash
poetry run traefik-certificate-exporter -d ./data -o ./certs -fs "acme-*.json" -r
```

See [README.md](../README.md) for the full CLI flag reference and config-file/env-var equivalents
(`confuse`-based, precedence: CLI > env vars > config file > packaged default).

## Conventions

- `src/` layout package (`traefik_certificate_exporter`), with type hints used as contracts and
  private attributes used for encapsulation in existing classes.
- Global singletons for existing cross-cutting concerns: `globalLogger`, `globalArgs`, and
  `globalSettingsMgr`.
- Config keys are lowercase and dotted (`settings.datapath`), mapped from CLI flags with
  `argparse`'s `dest=` and from environment variables with the
  `TRAEFIK_CERTIFICATE_EXPORTER_` prefix and `_` as `confuse`'s separator.

## Where work lands

- Certificate parsing/export: [certificate_exporter.py](../src/traefik_certificate_exporter/libs/certificate_exporter.py)
- Docker container restarts: [docker.py](../src/traefik_certificate_exporter/libs/docker.py)
- Configuration loading: [settings.py](../src/traefik_certificate_exporter/libs/settings.py)
- CLI flags: [cli_args.py](../src/traefik_certificate_exporter/libs/cli_args.py)
- Container image and s6 init scripts: [docker/](../docker/)
