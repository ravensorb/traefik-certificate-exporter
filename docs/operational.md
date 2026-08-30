# Operations Guide — traefik-certificate-exporter

## Deploy

**Docker (recommended):**

```bash
docker pull ravensorb/traefik-certificate-exporter:latest
```

See [docker/README.md](../docker/README.md) for `docker run` / `docker-compose` examples
(env-var-driven and config-file-driven variants).

**PyPI package:**

```bash
pip install traefik-certificate-exporter
```

> Until PRD backlog item #3 is fixed, a bare `pip install` may not pull in `cryptography`
> transitively on every platform/resolver — verify `python -c "import cryptography"` works
> after install, or install the Docker image instead until that's fixed.

## Configuration

Three layers, in precedence order (highest wins): CLI flags > environment variables
(`TRAEFIK_CERTIFICATE_EXPORTER_*`) > `config.yaml` (via `-c`) > packaged
[config_default.yaml](../src/traefik_certificate_exporter/config_default.yaml). Env vars
deliberately outrank the config file — this is a Docker-first tool, and env vars are the
standard vehicle for per-deployment overrides of a static/mounted config file. See
[config.sample.yml](../config.sample.yml) for a starting file.

**Known gap:** if you set `TRAEFIK_CERTIFICATE_EXPORTER_SETTINGS_DOMAINS_INCLUDE` via env
var or config file, also set `..._DOMAINS_EXCLUDE` (even to empty) — the CLI enforces
mutual exclusivity via `argparse`, but the env-var/config-file path does not (documented as
a `FIXME` in [docker/README.md](../docker/README.md); tracked as PRD backlog item #6).

## Runbook: certificate not exported

1. Check the container/process is actually seeing file events: run with `-ll DEBUG` and
   confirm `Watchdog received modified event` appears when Traefik renews.
2. Confirm `settings.dataPath` resolves to a real, mounted path — **note:** a misconfigured
   or unmounted data path does not currently fail loudly (PRD backlog item #2 / review
   finding #2); check the logged `Data Path: ...` line manually rather than trusting an error.
3. Confirm the domain isn't filtered out by an include/exclude list (`Skipping domain: ...`
   at INFO level).
4. Confirm the ACME JSON has a non-empty private key and cert for that domain (`Unable to
   find private key or full chain ...` at WARNING level is a Traefik-side/ACME-side symptom,
   not an exporter bug).

## Runbook: container not restarting after cert change

1. Confirm `restartContainers` / `--restart-container` is set.
2. Confirm the target container has label
   `com.github.ravensorb.traefik-certificate-exporter.domain-restart=<domain>` (comma-separated
   for multiple domains).
3. Confirm `/var/run/docker.sock` is mounted read-write into the exporter container (it is
   mounted read-only in the sample `docker-compose.yml` — read-only is sufficient for the
   `docker` SDK's list/restart calls over the socket, but verify against your Docker daemon's
   socket permission model if restarts silently fail).

## First-run config seeding (container)

**Known bug (PRD backlog item #6 / review finding #6):** the s6 init script that should seed
`/config/config.yaml` from `/defaults/config/config.yaml.sample` on first boot currently
writes to `/config/config.yaml.sample` instead — so no real config file is created
automatically. Until fixed, manually copy a config file into the mounted `/config` volume,
or rely entirely on environment variables.

## Monitoring / observability

None today — no metrics endpoint, no health check (PRD backlog item #15). The only signal
is the process's stdout/log-file output; monitor container/process liveness externally
(e.g. `docker inspect` health status is not configured either).

## Rollback

Pin the previous image tag/PyPI version; there is no migration/state to roll back — the
tool is stateless aside from the files it writes to the output volume, which are safe to
leave in place across versions.
