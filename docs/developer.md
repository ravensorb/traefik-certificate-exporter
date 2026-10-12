# Developer Guide — traefik-certificate-exporter

## Prerequisites

- Python compatible with the `>=3.10,<3.15` constraint in `pyproject.toml`.
- No repository interpreter pin exists; Poetry uses the active compatible Python interpreter.
- Poetry 2.4.2 (the tested baseline). The first `poetry install` also installs the
  `poetry-dynamic-versioning` plugin from `[tool.poetry.requires-plugins]`, which needs
  network access.
- `just` — every local operation below is a `just` recipe (AD-16).
- A clone with its tags: versions come only from `vX.Y.Z` tags (AD-7, strict), so in a
  shallow or tagless clone run `git fetch --tags --unshallow` first.
- Docker with Buildx for `just image`.
- [`act`](https://github.com/nektos/act) for `just act` (optional).

Install the Poetry-managed project and development tools:

```bash
just install
```

Every group in `poetry.lock` is installed, the optional `publish` group (`twine`) included,
so `twine` is available locally and audited by the `pip-audit` hook (ADR-0042). The one
package set outside `poetry.lock` is the CI-only Poetry bootstrap file described under
[Keep pinned tools current](#keep-pinned-tools-current).

## Verification topology

The pipeline is four workflows chosen by trigger (ADR-0035, AD-1). Every one of them calls
the same reusable, credential-free `build.yaml`, which is the only place the project is
checked, tested, built and versioned (AD-2):

```text
 pull_request   ci.yaml        build
 push to main   dev.yaml       build ─► publish-package, publish-image   (dev)
 tag vX.Y.Z     release.yaml   validate-tag ─► build ─► publish-package, publish-image ─► release
```

The `build` job runs exactly what `just check` runs locally — every pre-commit hook, then
`pytest` (AD-3) — and then builds the wheel, sdist and a single-architecture smoke-tested
image. The required pull-request check is `build / build`. The full picture, with the
destination table and the `PUBLISH_*` secrets, is in
[ci/pipeline-walkthrough.md](ci/pipeline-walkthrough.md).

## Local command facade

| Recipe | Does |
| --- | --- |
| `just install` | `poetry sync --all-groups` (every lock group, so the pip-audit hook sees every group as installed for this Python and platform; ADR-0042) |
| `just check` | every pre-commit hook over the whole repository, then `pytest` — the CI gate |
| `just build` | clean `dist/`, then `poetry build` (one wheel, one sdist) |
| `just image` | `just build`, then build and load `traefik-certificate-exporter:local` from that wheel |
| `just act [workflow]` | run a workflow under `act` with its own trigger event; default `ci.yaml` |
| `just release <major\|minor\|patch>` | cut a release by pushing one `vX.Y.Z` tag |

The recipes are thin: no release or verification logic lives in a script (AD-16).

## Validate CI locally

```bash
just act              # ci.yaml, as a pull_request
just act dev.yaml     # the dev pipeline, as a push
```

- `just act` passes `--detect-event`, so each workflow runs under the event it declares.
  Without it `act` sends `push`, and a `pull_request`-only workflow runs no job and exits 0.
  Check that the `build` job actually ran, not only the exit status (AD-16, ADR-0036).
- No secrets or variables are passed, so every publishing destination is disabled and
  nothing is published (AD-9). `publish-package` and `publish-image` run their guards and
  skip every publishing step.
- The exit status is `act`'s own.
- Run `just act dev.yaml` from `main` (or pass an event file with `ref: refs/heads/main`)
  so the run matches `dev.yaml`'s branch filter.
- No checkout carries a `ref:` (ADR-0028) and no step reads `env.ACT` (AD-6), so `act`
  runs the same YAML as GitHub and Gitea, against your working tree.
- The artifact actions are pinned to the newest `act`-compatible pair (upload-artifact
  v5.0.0, download-artifact v6.0.0); newer majors fail under `act` 0.2.89. See the spine's
  Deferred section (`_bmad-output/planning-artifacts/architecture/architecture-ci-cd-pipeline-2026-10-08/ARCHITECTURE-SPINE.md`).

### Vendored tool trees

`.agents/`, `.claude/` and `_bmad/` are installed BMad tooling, not project source. They
are excluded from the lint and format hooks, but secret scanning still reads them: the
repository adds no path exemption to the `gitleaks` and `gitleaks-history` hooks (ADR-0033,
as restated by ADR-0037). They have no repository-side integrity record; that record was
retired by ADR-0035, and changes to them are held by CODEOWNERS review.

`.gitleaks.toml` sets `useDefault = true`, so gitleaks' own default global allowlist is
inherited (ADR-0037): it skips lock files, dependency site-packages and the VCS directory
by path. With gitleaks v8.30.1 (the pre-commit hook `rev`), the `skipping file|directory:
global allowlist` lines of
`gitleaks dir --redact --no-banner --config .gitleaks.toml --log-level trace .` on a fully
installed tree (Python 3.11 venv; plugins poetry-dynamic-versioning 1.10.0, dunamai 1.26.2,
jinja2 3.1.6, markupsafe 3.0.4) name exactly these paths; `gitleaks git` skips only
`poetry.lock` by path:

- `.git`
- `.gitleaks.toml`
- `.poetry/plugins/dunamai-1.26.2.dist-info`
- `.poetry/plugins/jinja2-3.1.6.dist-info`
- `.poetry/plugins/markupsafe-3.0.4.dist-info`
- `.poetry/plugins/poetry.lock`
- `.poetry/plugins/poetry_dynamic_versioning-1.10.0.dist-info`
- `.venv/lib/python3.11`
- `poetry.lock`

Ignored install and cache trees outside that set — the rest of `.poetry/plugins/`,
`.mypy_cache/`, `.ruff_cache/`, `dist/`, the rest of `.venv/` — are scanned, and that
over-scan fails closed. A credential placed in `poetry.lock` or `.gitleaks.toml` is not
reported; ADR-0037 accepts that risk. The list is the same one in the `.gitleaks.toml`
header. It is not checked by any standing CI job: it was verified by diffing a fresh trace
against it. The concrete paths follow the gitleaks version, the locked plugin versions and
the venv's interpreter, so a gitleaks upgrade, a plugin-lock bump or a different interpreter
can change them; a change that alters the set must update both records in the same change.

## Keep pinned tools current

**Pre-commit hooks.** Every remote hook `rev` in `.pre-commit-config.yaml` is a commit SHA
with a `# frozen: vX.Y.Z` comment, written by `pre-commit autoupdate --freeze`; the
`precommit-revs-frozen` hook fails on any other form (BL-E013-020). On GitHub, Dependabot's
`pre-commit` ecosystem proposes the updates weekly. Gitea has no Dependabot, so there, and
whenever a release is prepared, update them by hand:

```bash
poetry run pre-commit autoupdate --freeze
just check
```

`autoupdate` takes the newest tag reachable from each upstream's default branch, which can
be older than the current rev (gitleaks v8.30.1 is not on its default branch). Hold such a
repo at its current tag by writing that tag's commit, from
`git ls-remote <repo> 'refs/tags/<tag>^{}'` (or `refs/tags/<tag>` for a lightweight tag),
as `rev: <sha>  # frozen: <tag>`. A gitleaks rev change also re-checks the inherited
allowlist above (ADR-0037).

**Poetry bootstrap for CI.** The workflows install Poetry with
`pip install --require-hashes -r .github/requirements/poetry.txt`; the
`workflows-pip-install-from-requirements` hook rejects any other workflow `pip install`, and
the `pip-audit-bootstrap` hook audits the file (ADR-0042). It is a bootstrap-only exception
to ADR-0001: it installs Poetry and nothing else. It is generated from
`.github/requirements/poetry.in`, never edited by hand. To bump Poetry, edit the pin in
`poetry.in`, then regenerate from the repository root (the variable makes pip-compile write
this exact command into the file's header):

```bash
export CUSTOM_COMPILE_COMMAND="pipx run --python 3.14 --spec 'pip-tools==7.6.2' pip-compile --generate-hashes --output-file .github/requirements/poetry.txt .github/requirements/poetry.in"
eval "$CUSTOM_COMPILE_COMMAND"
```

`--python 3.14` is the interpreter the workflows install; pip-compile writes no environment
markers, so the file resolves for that interpreter only and is regenerated when the
workflows' Python changes. On GitHub, Dependabot's `pip` ecosystem on
`/.github/requirements` proposes updates weekly. If one of its PRs drops the `--hash=` lines
or fails `pip install --require-hashes`, close it, remove that Dependabot entry, and update
by hand with the command above. On Gitea the update is always by hand.


```bash
git switch main && git pull
just release minor     # or major / patch
```

`just release`:

1. refuses unless the tree is clean, the current branch is the default branch, and
   `HEAD` equals `origin/<default>` after a fetch (AD-15);
2. runs `just check`;
3. finds the latest `vX.Y.Z` tag reachable from `HEAD`, refuses if it already points at
   `HEAD`, and computes the next version with `pysemver bump`;
4. creates the annotated tag `vX.Y.Z` and pushes only that tag.

A release creates no commit and needs no changelog file. The tag push triggers
`release.yaml`, which validates the tag, builds, publishes to every configured destination,
and creates the forge release with generated notes and the wheel and sdist attached. If the
push fails, the recipe prints the retry (`git push origin refs/tags/vX.Y.Z`) and abandon
(`git tag -d vX.Y.Z`) commands. Recovery is in
[operational.md](operational.md#ci-recovery-runbook).

## Build package distributions

```bash
just build
```

Poetry builds one wheel and one sdist into `dist/`. The version is computed from git tags by
`poetry-dynamic-versioning` (AD-7): exactly `X.Y.Z` on a release tag, `X.Y.(Z+1).devN` between
releases. `pyproject.toml` always says `0.0.0`.

## Build the native image

```bash
just image
```

The recipe builds `dist/` first, then runs `docker build` with `docker/Dockerfile`, target
`runtime`, and the AD-17 build arguments: the wheel path and its SHA-256, the wheel's own
version, the Poetry version, and the full Git revision. The result is loaded as
`traefik-certificate-exporter:local`. See [docker/README.md](../docker/README.md) for
smoke-test commands.

The image builder deliberately cannot fall back to PyPI or a private package index for the
application. It installs only the supplied, hash-verified wheel, ensuring the image contains the
same package artifact that local and CI checks validated (ADR-0008).

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
