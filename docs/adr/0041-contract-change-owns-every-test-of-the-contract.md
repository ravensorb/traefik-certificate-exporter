# ADR-0041: A story that changes a contract owns every test of that contract

- **Status:** Accepted
- **Date:** 2026-10-11
- **Deciders:** E014 epic architecture gate (l3io-arch-review + bmad-agent-architect)
- **Epic:** E014
- **Departs from spec:** n/a. Applies PRD NFR-5
  (`_bmad-output/planning-artifacts/prds/prd-traefik-certificate-exporter-2026-08-30/prd.md`);
  resolves arch-gate finding AG-2
  (`_bmad-output/implementation-artifacts/epic-014/arch/arch-gate-review.md`)
- **Principle(s) in tension:** Core §4 Testability; Global rule 3 (enforce mechanically);
  delivery speed of a story versus the cost of the opt-in integration run

## Context

The opt-in integration tests (`pytest.mark.integration`, gated on
`TCE_DOCKER_INTEGRATION=1`, a Docker socket and a built image) are skipped by `just check`
and by CI. A story that changes a contract those tests exercise can therefore pass every
gate while leaving an integration test wrong.

E014 had this case. E014-S01-001 adds `tests/libs/test_docker_engine.py`, which calls
`restartLabeledContainers(["it.example.test"])` and expects a restart. E014-S01-006 then
changes the signature to `restartLabeledContainers(artifactMtime)` and makes a restart
depend on exported files newer than the container's start. The S01-001 test breaks twice
over, S01-006 did not list it in its files or its Verification, and the break would first
surface at the release run (E014-S02-005), where the FR-15 evidence was also credited to
the wrong test.

## Options considered

| Option | Pros | Cons | Standards fit |
|---|---|---|---|
| A. Leave opt-in tests to the release story, which runs them all | Cheapest per story | Defects surface at release time, after the story that caused them closed; ownership is unclear | Weak Core §4 |
| B. Make integration tests run in `just check`/CI | Mechanical | Needs a Docker daemon and an image build in every gate; contradicts the opt-in design of E014-S01-001 | Strong Global rule 3; costly and out of E014 scope |
| C. The contract-changing story owns every test of the contract, opt-in ones included, and runs the affected integration modules in its own Verification | Breakage is fixed by the story that causes it; evidence is attributed to the test that proves it | Each such story needs a Docker host at dev time | Core §4; Global rule 3 partly (see Consequences) |

## Decision

Option C.

1. A story that changes a public or cross-module contract (a signature, a return value,
   or the rule a function applies) lists in its "Files in scope" every test that
   exercises that contract, including opt-in integration tests, and updates them in the
   same change.
2. Its `## Verification` table has a row that runs each affected integration module with
   `TCE_DOCKER_INTEGRATION=1`, with "passed, none skipped" as the expected result. A
   missing Docker daemon at dev time is recorded in the notes file and the story's
   closure is flagged; it is not a silent pass.
3. Release evidence names the test module that proves each requirement. A release story
   does not credit a requirement to a test that does not exercise it, and its
   "missing or skipped test → BLOCKED" guard names every module it relies on.

## Consequences

- Positive: E014-S01-006 owns `tests/libs/test_docker_engine.py` alongside its new
  `tests/test_container_restart.py`, and E014-S02-005 credits FR-15 to
  `tests/test_container_restart.py`.
- Negative: stories that touch the Docker seam need a Docker host at dev time.
- Not mechanically enforced: nothing checks that a story's Verification covers every
  integration test of a contract it changes. The arch gate and code review check it.
  What is enforced: E014-S02-005 runs `pytest -m integration -v -rs` over every
  integration module and requires no skip, so a broken test still blocks the release.

## Revisit when

- integration tests run in CI on every pull request (then rule 2 is covered by the gate
  and can be dropped).
