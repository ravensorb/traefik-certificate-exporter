# ADR-0048: Exporter module layering

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** Maintainer (ravensorb), via the E014 plan (E014-S02-003 enricher decision 1)
  and the sprint-01 closure decision on SD-01-1; recorded by E014-S02-003
- **Epic:** E014
- **Spine:** product spine
  `_bmad-output/planning-artifacts/architecture/architecture-traefik-certificate-exporter-2026-08-30/ARCHITECTURE-SPINE.md`
  Design Paradigm and AD-13
- **Departs from spec:** n/a. Resolves review finding M7 (`review-all-epics-2026-10-10/review-product.md`)

## Context

`src/traefik_certificate_exporter/libs/certificate_exporter.py` has three jobs:

- the domain: ACME store parsing and PEM/PKCS12 build;
- I/O: the atomic writes (`_atomic_write*`) and change detection against the files on disk;
- pass orchestration: the watch handler `AcmeCertificateFileHandler`, which runs a pass
  (export → post-export hook → notifications → restart) and calls the Docker, hook and
  Apprise adapters.

`app.py` orchestrates the run-at-start pass with the same sequence. Review M7 found that no
ADR records this shape. In sprint 01 two import cycles appeared (arch drift SD-01-1); the
closure fixed them and added an `import-linter` pre-commit hook that enforces the layering
as built. The maintainer decided to keep that strict layer order (2026-10-11,
`epic-014/execution-notes.md`).

## Decision

1. **Accept the current shape for 0.3.0.** `certificate_exporter` keeps its three jobs. No
   module is extracted now; the release is near and the shape is enforced.
2. **The layer order is enforced.** `[tool.importlinter]` in `pyproject.toml` declares three
   contracts: `no-cycles` (acyclic siblings), `entrypoint-on-top` (`app` above `libs`) and
   `libs-layers` (exhaustive, top to bottom: `certificate_exporter`, `cli_args`, `docker`,
   `settings`, `legacy_settings`, `notify | post_export`, `logging_utils | object |
   suggest`). The `import-linter` pre-commit hook (`.pre-commit-config.yaml`, id
   `import-linter`; its version comes from `poetry.lock`, ADR-0042 as amended by
   E015-S02-003) runs them in `just check` and CI. Coverage limit:
   only what the contracts declare is checked; an object handed to a function at run time
   is not an import and is not seen.
3. **Planned work, not done now:** extract an orchestration module (the watch handler and
   the export → hook → notify → restart pass, shared by `app` and the handler) and an I/O
   module (`_atomic_write*`). A Low backlog item records it.

## Consequences

- **Accepted cost:** `certificate_exporter.py` stays the largest module, and the pass
  sequence is written twice (`app._run` and the watch handler), so a change to the sequence
  must be made in both. Product spine AD-9 states the sequence once; review is what keeps
  the two call paths equal. The maintainer owns it.
- A new module must find its place in the `libs-layers` contract, or the hook fails
  (`exhaustive = true`). This is intended: the layer order is a decision, not an accident.

## Revisit when

The next feature that touches the pass sequence. That change does the extraction in item 3
first, and amends this ADR and AD-13.
