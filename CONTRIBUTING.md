# Contributing

Thanks for considering a contribution to `traefik-certificate-exporter`.

## Getting started

```bash
poetry install
poetry run pytest
pre-commit install
```

See [README.md](README.md) for the CLI reference and [docs/developer.md](docs/developer.md)
for a deeper walkthrough of the codebase.

## Before opening a pull request

- Run `poetry run pytest` — all tests must pass.
- Run `pre-commit run --files <your changed files>` — **do not** run
  `pre-commit run --all-files`, it will reformat unrelated files repo-wide (`ruff-check`/
  `ruff-format` are scoped to touched files only for this reason).
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

## Reporting bugs / requesting features

Please use the issue templates under `.github/ISSUE_TEMPLATE/`. For security
vulnerabilities, see [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Code of Conduct

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
