# Developer Guide — traefik-certificate-exporter

## Setup

```bash
poetry install
```

Requires Python `^3.10` (see `pyproject.toml`). No `.python-version`/`uv python` pin exists
today — Poetry resolves against whatever interpreter is active.

## Build

```bash
poetry build
```

`poetry-dynamic-versioning` is present but currently disabled (`enable = false` in
`pyproject.toml`); the version is read from the static `version = "0.1.3"` field.

## Run locally

```bash
poetry run traefik-certificate-exporter -d ./data -o ./certs -fs "acme-*.json" -r
```

See [README.md](../README.md) for the full CLI flag reference and config-file/env-var
equivalents (`confuse`-based, precedence: CLI > env vars > config file > packaged default).

## Test

**There is currently no test suite** (`tests/__init__.py` is empty) — this is PRD backlog
item #5 (BLOCKER). Until it lands, there is no `pytest`/`tox` command to run; changes to
ACME parsing (`certificate_exporter.py`) or settings loading are unverified except by manual
smoke-testing against a real or sample `acme.json`.

## Lint / format

`.pre-commit-config.yaml` currently only runs `poetry lock --check`, `check-toml`,
`check-yaml`, and `mixed-line-ending` — `black`/`isort` hooks are present but commented out,
and no `ruff`/`mypy` are configured (PRD backlog item #11 covers cleaning this up).

```bash
pre-commit run --all-files
```

## Conventions

- `src/` layout package (`traefik_certificate_exporter`), single-underscore-prefixed private
  attributes for encapsulation (e.g. `self.__settings`, `self.__logger`) inside classes.
- Global singletons for cross-cutting concerns: `globalLogger` ([logging_utils.py](../src/traefik_certificate_exporter/libs/logging_utils.py)),
  `globalArgs` ([cli_args.py](../src/traefik_certificate_exporter/libs/cli_args.py)), `globalSettingsMgr`
  ([settings.py](../src/traefik_certificate_exporter/libs/settings.py)) — imported directly rather than
  dependency-injected. This is a testability gap (review finding #1); new code should still
  prefer accepting these as constructor parameters where practical, as the existing classes do.
- Config keys are lowercase, dotted (`settings.datapath`), mapped from CLI flags via
  `argparse`'s `dest=` and from env vars via the `TRAEFIK_CERTIFICATE_EXPORTER_` prefix with
  `_` as the `confuse` separator.

## Where work lands

- Cert parsing/export logic: [src/traefik_certificate_exporter/libs/certificate_exporter.py](../src/traefik_certificate_exporter/libs/certificate_exporter.py)
- Docker container restart logic: [src/traefik_certificate_exporter/libs/docker.py](../src/traefik_certificate_exporter/libs/docker.py)
- Config loading: [src/traefik_certificate_exporter/libs/settings.py](../src/traefik_certificate_exporter/libs/settings.py)
- CLI flags: [src/traefik_certificate_exporter/libs/cli_args.py](../src/traefik_certificate_exporter/libs/cli_args.py)
- Container image + s6 init scripts: [docker/](../docker/)
