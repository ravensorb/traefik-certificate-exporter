# Contributing

Thanks for considering a contribution to `traefik-certificate-exporter`.

## Getting started

You need [Poetry](https://python-poetry.org/) 2.x and [`just`](https://just.systems/).

```bash
git fetch --tags   # versions come from vX.Y.Z tags (AD-7)
just install
pre-commit install
```

Versioning is strict (AD-7): a shallow or tagless clone cannot *install*, not only build.
`just install` and the `poetry-lock` hook fail with poetry-dynamic-versioning's "No tags
available and fallbacks disabled by strict mode". Recover a shallow
clone with `git fetch --tags --unshallow` (`--unshallow` is an error on a full clone, where
`git fetch --tags` is enough).

See [README.md](README.md) for the CLI reference and [docs/developer.md](docs/developer.md)
for a deeper walkthrough of the codebase.

## Before opening a pull request

- Run `just check` before pushing. It runs every pre-commit hook over the whole
  repository and then the test suite — the same gates the pull-request check runs. The
  pull-request check also builds the distributions and the image, and runs on Python
  3.14; `just image` covers that locally.
- The required check on a pull request is `build / build` (`ci.yaml`). Pull requests
  never see a credential and never publish anything. How the pipeline works:
  [docs/ci/pipeline-walkthrough.md](docs/ci/pipeline-walkthrough.md).
- Follow the conventions in [docs/guidelines.md](docs/guidelines.md) — in particular,
  config keys are lowercase-dotted, env vars use the `TRAEFIK_CERTIFICATE_EXPORTER_`
  prefix, and new dependencies should be well-maintained libraries rather than hand-rolled
  equivalents (see the [ADRs](docs/adr/) for examples of that trade-off being made
  explicitly).
- If you're changing CLI flags, config keys, or environment variables, update
  [README.md](README.md), [docker/README.md](docker/README.md),
  [config.sample.yml](config.sample.yml), and
  [config_default.yaml](src/traefik_certificate_exporter/config_default.yaml)
  consistently — see how existing settings are documented across all four.

Releases are cut by maintainers with `just release <major|minor|patch>`; contributors do
not bump versions or edit a changelog.

## Reporting bugs / requesting features

Please use the issue templates under `.github/ISSUE_TEMPLATE/`. For security
vulnerabilities, see [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
