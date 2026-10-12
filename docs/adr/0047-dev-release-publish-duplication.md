# ADR-0047: Dev/release publish duplication accepted

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** Maintainer (ravensorb), via the E014 plan (E014-S02-003 enricher decision 2);
  recorded by E014-S02-003
- **Epic:** E014
- **Spine:** CI/CD spine AD-1 (four workflows; duplicated publish logic accepted) and
  Conventions row "Shared publish logic"
- **Departs from spec:** n/a. Resolves review finding F-05 (`review-all-epics-2026-10-10/review-cicd.md`)
  and BL-E013-025

## Context

AD-1 fixes the pipeline at four workflow files chosen by trigger. `dev.yaml` and
`release.yaml` each carry their own `publish-package` and `publish-image` jobs, so about 150
lines of publish logic exist twice (review F-05: `dev.yaml:80-115` vs `release.yaml:126-161`,
and `dev.yaml:126-284` vs `release.yaml:172-329` at the time of the review). E014-S02-002
added a `Destination configuration` step to every publish job. It exists in **5 copies**
(`dev.yaml` 2, `release.yaml` 3). The `run:` body is identical in all five; the copies differ
only in step `env` (`JOB`, `ENVIRONMENT`, the `DESTINATIONS` and `LEGACY` lists and the
`HAS_*` booleans they name) (`notes-E014-S02-002.md`).

Duplicated logic can drift: a fix lands in one file and not the other. No ADR accepted this.

## Decision

Accept the duplication for 0.3.0.

- **Owner:** the maintainer, through CODEOWNERS review of `.github/workflows/`.
- **Review rule:** a change to a shared step of one publish job lands in the matching job of
  the other workflow in the same commit, and the pull request description says so.
- **Not mechanically enforced** (global rule 3). No check compares `dev.yaml` with
  `release.yaml`. One partial exception: the `Destination configuration` step fails with
  `::error::` when its list names a flag or input that job `env` does not define, so a copy
  whose lists drift from its own job is loud. A copy whose `run:` body drifts from the other
  four is not detected.
- **Considered and deferred:** local composite actions for the shared steps. They would
  remove the copies but add a third kind of file to the pipeline, which the 2026-10-08
  redesign (ADR-0035) removed along with `verified-bundle`, `publication-contract` and
  `setup-poetry-python`. Re-introducing them is a separate decision.

## Consequences

- **Accepted cost:** every shared publish change is made twice (and the Destination
  configuration body five times), and a reviewer has to check the copies match. The
  correctness risk is a fix that lands in one workflow only; the maintainer owns catching it
  in review.
- The four-workflow shape of AD-1 stays as is, and each workflow stays readable on its own.

## Revisit when

- a fix lands in only one of the two files (found in review, in an incident, or by a diff of
  the two jobs); or
- a third copy of the publish logic is needed (a new workflow or a new publish job).
