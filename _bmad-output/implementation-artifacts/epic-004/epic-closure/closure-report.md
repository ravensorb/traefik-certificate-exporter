# Epic 4 — Closure Report

**Epic:** E004 — Smooth Docker Operator Experience
**Sprints:** 1 (S01), 2 stories, no carry-over

## Stories delivered

| Story | Title | Outcome |
|---|---|---|
| E004-S01-001 | Seed a Working Config on First Container Boot | s6 init script copied the sample to the wrong destination (`config.yaml.sample` instead of `config.yaml`); fixed and verified live against both an empty and a pre-existing config volume. |
| E004-S01-002 | Emit Structured Logs for File Output | File log handlers now use `python-json-logger`'s `JsonFormatter`; console output (coloredlogs) unchanged; redaction verified to survive. |

## Evidence

- `poetry run pytest`: 39/39 passed.
- Real `docker build` + `docker run` verification for the init-script fix (config seeded
  on empty volume, preserved on existing volume with a sentinel marker).
- Live `logging.config.dictConfig` verification that file logs are valid JSON with
  `asctime`/`levelname`/`name`/`message` as separate keys, and that redaction survives.
