# Epic 4 / Sprint 1 — Retrospective

## What happened

Both stories done, no carry-over.

- **E004-S01-001** (Seed config on first container boot): the init script's `cp -u`
  copied the sample to `/config/config.yaml.sample` instead of `/config/config.yaml` --
  the existence check (`[ ! -f /config/config.yaml ]`) and the copy destination had
  silently drifted apart. Fixed the destination path; the pre-existing existence check
  already satisfies NFR7 (no overwrite of user edits) once the destination is correct.
  Verified live with a real `docker build` + `docker run` against an empty `/config`
  volume (config seeded correctly) and again with a pre-existing, marked config.yaml
  (preserved untouched across a restart).
- **E004-S01-002** (Structured JSON file logs): added `python-json-logger` (a maintained
  library, not a hand-rolled `json.dumps` formatter) and repointed the two file-handler
  formatters at `pythonjsonlogger.json.JsonFormatter`, keeping the existing `format` string
  syntax (so field names/order stayed self-documenting) and leaving both console
  formatters on `coloredlogs.ColoredFormatter` untouched. Verified end-to-end via
  `logging.config.dictConfig` that file output is valid, parseable JSON with
  `asctime`/`levelname`/`name`/`message` as separate keys, and that an already-redacted
  message (Epic 1) survives the new format unchanged.

## Learnings

- The Dockerfile installs the *published PyPI package* into the image, not the local
  working tree -- Docker-level verification for a Python-source-only change (like the
  logging formatter) doesn't exercise the local diff at all. Only shell-script/`docker/root`
  changes (like the config-seed fix) are meaningfully verified by a local `docker build`.
  Python source changes need their own test suite as the primary verification, with Docker
  verification reserved for things that only exist at the container level.
- A container running under s6-overlay with no exit condition (watch-for-changes off,
  run-at-start off) still runs indefinitely -- `docker run --rm -d` + a fixed `sleep` +
  `docker stop` is the right pattern for verifying init-time side effects without hanging
  the terminal.
