# Epic 008 — Retrospective

**Epic:** E008 — Action-Based Multi-Channel Delivery
**Sprints:** 1 (S01), 4/4 stories done, carry-over 0
**Closed:** 2026-09-03

## Summary

One sprint delivered the whole publication pipeline: five workflow files (two reusable), three
composite actions, twelve jobs, three registered finalizers, two disjoint credential classes, and
the retirement of the entire legacy publish path. Seven ADRs (0006–0012) record the decisions. The
contract suite grew from 34 guards to 285.

Velocity was not the interesting number. **Closure cost more than implementation** — four review
phases returned 1 BLOCKER, 1 CRITICAL, 9 HIGH, 6 MAJOR, 11 MEDIUM and 14 MINOR/LOW, and the fix
pass took twenty commits. Every finding is closed. That ratio is the epic's main signal, and it is
not a complaint about the reviews: the reviews found two live publication bugs and two controls
that had never worked, none of which any amount of implementation care would have surfaced.

## Learnings to carry forward

**1. A derivation added beside a literal does not remove the literal.** The epic's signature defect
appeared eleven times: a guard whose rule is correct over a set that is wrong. The clearest case is
the one worth remembering — tier 1's hand-kept two-tuple *was* replaced by a filesystem derivation,
and the identical two-tuple was left eight lines below it carrying the tier-2 rules, which matter
more. Nobody was careless; the derivation was written, documented, and correct. What was missing was
anything that checked the *old* value had gone. When replacing an enumeration with a derivation,
grep for the enumeration afterwards, and prefer deleting it in the same commit.

**2. Plant the violation, and make the plant attack the scope.** Every guard in this epic was
"proven" by a plant, and five guards still fell to the sprint reviewer's plants — because the
original plants attacked the *rule* ("does it catch a force-push?") and not the *set* ("does it look
at composite actions?"). The discipline caught two of the author's own mistakes during remediation:
an https test that passed against a deliberately weakened check, because the URLs chosen hit an
unrelated fail-closed branch; and a region-replace that silently deleted seven definitions, noticed
only because the collected test count fell by four. A plant that cannot fail teaches nothing.

**3. A green control is not evidence it looked.** Two gates had never done anything. The secret
scanner ran the upstream `--staged` invocation under `--all-files`, which stages nothing: 0 bytes
scanned, exit 0, on every commit of this project's history. The pytest matrix declared five Python
versions, installed one, and interpolated the dimension into the job *name* — so CI displayed five
interpreters while running 3.14 five times, and the 3.10 floor `pyproject.toml` promises had never
executed. Both had been green throughout. The remedy that generalises: make the control prove itself
against a planted failure, in CI, on every run — which the gitleaks job now does.

**4. Test the constraint before you accept it, and re-test it when the maintainer is in the room.**
Two of this epic's larger course corrections came from the maintainer, not from a review: "no Python
scripts in the publication path" retired three modules and 749 lines that had ADRs justifying them,
and "docker/build.sh was never in the pipeline" retired a guard whose false-positive class had just
cost a fix. Both were right, and neither was reachable from inside the work. Surface the constraint
early rather than building on the assumed one.

**5. Where a third party's output is load-bearing, check the output, not the input.** The image tag
list is rendered by a forked metadata action; the suite asserted `flavor: latest=false` was *passed*,
which is not the same as *honoured*. Reading the action's manifest confirmed the input exists — but
the durable fix was refusing an alias-shaped tag at the point the list becomes real, so the guarantee
no longer depends on the action's behaviour at all.

## Process notes

- Man-hours ran 185 against a 65–80 estimate (2.3–2.8×). The estimate was formed against the story
  scope; it did not anticipate that closure remediation would exceed implementation. Sprint estimates
  for review-heavy CONFIG/MIXED work should carry a closure band that reflects this.
- The work type was reclassified CONFIG → MIXED mid-epic, correctly: E007's CONFIG classification
  had skipped adversarial and red-team phases over 3,482 lines of Python. That reclassification is
  what surfaced most of this epic's findings.
- Three items are carried to backlog deliberately (BL-E008-007, -008, -009). Two are settings outside
  the repository tree that the guards state plainly they cannot observe; the third is a checkable
  claim about vendored trees with no source of truth to check against yet.
