# E014 sprint 02 — sprint-closure UX review (operator experience)

- Date: 2026-10-11
- Mode: headless. `bmad-ux` was invoked. Its Reviewer Gate validates the DESIGN.md/EXPERIENCE.md spines, and this project has neither (it has no GUI), so the gate had nothing to run on. This review was performed directly, as the dispatch allows.
- Scope:
  - E014-S02-002: AC 5 (Destination configuration messages) and AC 9 (docs).
  - E014-S02-006: AC 3 (concurrency wording) and AC 5 (pre-pull and the "re-run on 429" docs).
  - The matching hunks of `/tmp/e014-s02-closure-review/sprint.diff`: the dev/release Destination configuration steps, `build.yaml` pre-pull, `README.md`, `docs/operational.md`, `docs/upgrading.md`, and `docs/ci/pipeline-walkthrough.md` (which the warnings and AC 9 point to).
- Lens: is each operator-facing message clear and actionable (does it name the missing item and the fix)? Do the messages and the docs agree? Is the upgrade guidance complete for an operator moving from 0.2.x to 0.3.0?
- Each claim below was checked against the working-tree text. Line numbers refer to the working tree.

## What works

- The partial-destination warning (`dev.yaml:89,99`, `release.yaml:151,345,538`) names every missing input by its full `secrets.NAME`/`vars.NAME`. It says where to set it on GitHub (`<env>` environment) and on Gitea (repository Actions), and how to disable the destination instead. Its format matches AC 5 exactly.
- The `<Destination> enabled` lines are plain log lines. Unconfigured destinations print nothing, as specified.
- The README bullet (`README.md:177-181`) and the upgrading fork bullet (`docs/upgrading.md:244-248`) use the story's release-note wording almost verbatim, so they agree with each other.
- The walkthrough's example warning (`docs/ci/pipeline-walkthrough.md:208`) matches the real message format.
- The release concurrency note gives the re-run command and the "only while no newer tag has released" caveat. The 429 note gives `gh run rerun <run-id> --failed`. Both match the workflow comments and the step parameters (4 attempts, 30 s apart, `build.yaml:149`).

## Findings

### UX-1 — MEDIUM — The "Gitea shared inputs" warning tells the operator to set all four variables, then says they are alternatives

- Evidence: `.github/workflows/dev.yaml:56,89,99` and `.github/workflows/release.yaml:108,151`. The missing list is computed over all five inputs, and the generic `$where` prefix says "Set them as …". With only `PUBLISH_GITEA_TOKEN` set (story row (e)), the rendered text is:
  `Gitea shared inputs partially configured, skipped: missing vars.PUBLISH_GITEA_USERNAME, vars.PUBLISH_GITEA_PYPI_URL, vars.PUBLISH_GITEA_REGISTRY, vars.PUBLISH_GITEA_IMAGE. Set them as dev environment secrets/variables (GitHub) or repository Actions secrets/variables (Gitea), or unset secrets.PUBLISH_GITEA_TOKEN to disable it. These are alternatives: …`
- Problems:
  - The first instruction ("set them", meaning all four) contradicts the trailing hint.
  - "Gitea shared inputs" is not a destination, yet the message says it is "partially configured, skipped" and tells the operator to "disable it".
- Fix: give this row its own message, built from the hint and not from `$where`. For example: `Gitea token/username set but no Gitea destination selected: set vars.PUBLISH_GITEA_PYPI_URL (package index) and/or vars.PUBLISH_GITEA_REGISTRY + vars.PUBLISH_GITEA_IMAGE (container registry)[, and vars.PUBLISH_GITEA_USERNAME], or unset <set items> to stop.` Put only the shared item that is actually missing (`USERNAME`) into a "missing" clause.

### UX-2 — MEDIUM — The runbook's "stop publishing" advice contradicts the gating rule for GHCR and Docker Hub

- Evidence, docs: `docs/operational.md:560-567` says:
  - "delete the secret from every environment … or clear one of the destination's required `PUBLISH_*` variables: the destination switches off and runs keep succeeding";
  - and then: "Clearing a variable while the secret remains reports the destination as partially configured … delete the secret too, or clear every variable it needs".
- Evidence, workflow: `ANY_GHCR` and `ANY_DOCKERHUB` include the token (`dev.yaml:246,250`).
- Why it is wrong:
  - Deleting only the GHCR or Docker Hub secret while its variables remain still warns on every run.
  - Clearing every variable while the secret remains also still warns.
  - Both outcomes block a release under the zero-warning checklist (`pipeline-walkthrough.md:280`).
  - The paragraph also contradicts itself: it first offers "clear one variable" as a clean way to stop.
- Fix: replace the clause with the walkthrough's rule (`pipeline-walkthrough.md:96-97`): to stop a destination, unset every input that is set (the token in every environment, and the destination's variables). The one exception is the Gitea index and registry, which are silenced by clearing their own variables (`PUBLISH_GITEA_PYPI_URL`, or `PUBLISH_GITEA_REGISTRY` + `PUBLISH_GITEA_IMAGE`) while the shared token stays for the other side.

### UX-3 — MEDIUM — operational.md describes the partial cases inaccurately

- Evidence: `docs/operational.md:471-473` says: "A registry whose token is set but whose image (or, for Gitea, registry) variable is empty is skipped with a warning".
- What actually happens:
  - A missing `PUBLISH_*_USERNAME` is also a partial case, and the sentence omits it.
  - For Gitea, a token with both `PUBLISH_GITEA_REGISTRY` and `PUBLISH_GITEA_IMAGE` empty does not produce a registry warning. `ANY_GITEA` is the registry/image disjunction only (`dev.yaml:248`). The registry is skipped silently, or covered by the "Gitea shared inputs" warning when the index URL is also empty.
- Fix: state the rule, not examples. A destination is partial when one of its intent inputs is set but not every required input (link the walkthrough's state table). Name `PUBLISH_*_USERNAME` among the required inputs.

### UX-4 — MEDIUM — upgrading.md has no publishing-migration section for a 0.2.x maintainer or fork

- Evidence: `docs/upgrading.md:234-248` ("Where releases come from") states the new gating rule only. Nothing in the 0.2.0 → 0.3.0 section mentions:
  - the CI secret renames (`DOCKERHUB_TOKEN` → `secrets.PUBLISH_DOCKERHUB_TOKEN`, `DOCKERHUB_USERNAME` → `vars.PUBLISH_DOCKERHUB_USERNAME`, `FORGE_PACKAGE_TOKEN`/`REGISTRY_PASSWORD` → `PUBLISH_GITEA_TOKEN`, …);
  - the move of GitHub publish secrets into the `dev`/`release` environments (ADR-0039);
  - the new `vars.PUBLISH_*` variables each destination needs.
- The secret mapping exists only in the workflow `LEGACY` lists and in `pipeline-walkthrough.md:107-114`. The walkthrough states that legacy variables (`DOCKER_IMAGENAME`, `PACKAGE_REPO`, …) "are not detected at all", and it gives no replacement for them anywhere.
- Impact: a 0.2.x operator gets no migration checklist. Their old variables are silently ignored, and they discover the new names one warning at a time.
- Fix: add a `### Publishing (maintainers, forks and mirrors)` subsection to the 0.2.0 → 0.3.0 section. It should hold:
  - an old → new table covering the legacy secrets and the legacy variables;
  - where each lives (GitHub environment `dev`/`release`; Gitea repository Actions);
  - a pointer to the zero-warning release check.

### UX-5 — LOW — The legacy-settings warning promises a replacement that one entry lacks

- Evidence: the `LEGACY` row `secrets.PYPI_USERNAME|` renders as `secrets.PYPI_USERNAME (no replacement)`. The message continues "Move each value to its replacement …, then delete the legacy name" (`dev.yaml:108`, `release.yaml:160`). `pipeline-walkthrough.md:111` likewise says "naming the `PUBLISH_*` replacement for each".
- Fix: render the empty case as `(not needed; delete it)`. Change the message to "Move each value to its replacement where one is named, then delete the legacy name". Correct the walkthrough sentence to match.

### UX-6 — LOW — It is unclear whether the "zero destination warnings" checklist covers the legacy-settings warning

- Evidence: `pipeline-walkthrough.md:280-283` requires "zero destination warnings". The same Destination configuration step also emits `Legacy settings found …` (`release.yaml:160`), which is not about a destination.
- Fix: phrase the checklist as "zero `::warning::` annotations from any `Destination configuration` step (partial destinations, Gitea shared inputs, legacy settings)".

### UX-7 — LOW — The walkthrough table abbreviates variable names that the warnings print in full

- Evidence: the `pipeline-walkthrough.md:71-77` table lists `GITEA_USERNAME, GITEA_PYPI_URL`, `GHCR_USERNAME, GHCR_IMAGE`, and so on. The header says "(secret + vars.PUBLISH_*)", but the warnings print `vars.PUBLISH_GHCR_IMAGE`. An operator who copies a name from the table creates `GHCR_IMAGE`, which nothing reads.
- Fix: write the full names (`vars.PUBLISH_GHCR_USERNAME`, …) in the table.

### UX-8 — LOW — Minor wording in the partial warning

- Evidence: `$where` always says "Set them" (`dev.yaml:89,285`), including when one item is missing (the walkthrough example at `:208` reads "missing vars.PUBLISH_GHCR_IMAGE. Set them …"). The disable clause says "unset secrets.PUBLISH_GHCR_TOKEN", but GitHub and Gitea call this deleting a secret (variables are deleted too).
- Fix: "Set it/them" by count, or "Set the missing items …". Say "or delete <set items> to disable it".

### UX-9 — LOW — The pre-pull log does not show the attempt number or the delay, which S02-006 Observability asked for

- Evidence: `build.yaml:149` echoes the same `pulling $BASE_IMAGE (up to 4 attempts, 30 s apart)` on every attempt. Story S02-006 §Observability requires "each attempt number and the delay before the next attempt", and §Error handling specified 15/30/60 s increasing delays. The implementation and the walkthrough (`pipeline-walkthrough.md` "Re-run on a ghcr.io 429") both say a fixed 30 s, so the docs are consistent with the code.
- Whether `nick-fields/retry` logs attempt numbers itself was not verified in this review.
- Fix: confirm from the S02-006 act log that the action prints the attempt numbers; if it does not, print them in the step. Record the 30 s-fixed deviation from the story's 15/30/60 s in the notes, if that has not been done.

## Not findings (checked)

- README, operational.md, upgrading.md and the walkthrough agree on the three states (silent / one warning / enabled) and on the independent Gitea destinations.
- The release concurrency wording in the workflow comment matches the walkthrough's operator note (S02-006 AC 3).
- No message prints a secret value. Only `HAS_*` booleans reach the step.

High: 0, Medium: 4, Low: 5
