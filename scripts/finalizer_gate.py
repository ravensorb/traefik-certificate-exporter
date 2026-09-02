#!/usr/bin/env python3
"""Decide whether a finalizer may create a Release and advance aliases (ADR-0011).

`needs:` collapses two unrelated outcomes into one state. A job is `skipped` when an
upstream `needs:` job failed **and** when its own `if:` evaluated false, so
"Docker Hub is switched off" and "Docker Hub was enabled and its upstream died" are
indistinguishable from the result alone.

The enabled set the plan job emitted once is what separates them. This module is handed
that set and the `needs.<job>.result` of every publisher, and answers one question:

| destination state | result                | outcome |
|-------------------|-----------------------|---------|
| `enabled`         | `success`             | proceed |
| `enabled`         | `skipped`             | **fail** -- it should have run |
| `disabled`        | `skipped` / `success` | proceed |
| `unsupported`     | `skipped` / `success` | proceed |
| any               | `failure`/`cancelled` | **fail** |

`disabled` and `unsupported` both pass and are still recorded distinctly, because
conflating them makes "the forge silently stopped publishing packages" indistinguishable
from "someone turned it off" (ADR-0011 section 2).

A `success` for a destination the plan says is off is not a contradiction: one job can
carry several destinations -- the image publisher pushes to the forge registry and to
Docker Hub from a single Buildx invocation -- so its result is the result of every image
destination, whichever subset was actually addressed.

**This gate detects under-publication, not over-publication**, and that is deliberate
rather than an oversight. It answers "did everything the release promises exist before
any convenient name pointed at it"; it cannot answer "did something publish where it was
told not to", because a job result carries no evidence of which destinations it actually
addressed. Over-publication is prevented upstream and separately: a disabled destination
receives no credentials (the `secrets:` block reads the same enabled set) and no requests
(`publish-image.yaml`'s permitted-authority check, and the alias steps' own gating), each
with its own guard. Widening this table to reject `success` on a disabled destination
would break the multi-destination publisher above for no gain.

The two maps must cover exactly the same destinations. A destination with no result, or
a result for a destination the plan never emitted, is a wiring defect between the static
job graph and the runtime set -- which is the drift ADR-0011 exists to prevent -- and it
fails here rather than being quietly treated as absent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# The states a plan job may report for a destination. `enabled` is the only one that
# obliges the destination to have run.
REQUIRED_STATES = frozenset({"enabled"})
OPTIONAL_STATES = frozenset({"disabled", "unsupported"})
KNOWN_STATES = REQUIRED_STATES | OPTIONAL_STATES

# GitHub and Gitea both report exactly these four.
BLOCKING_RESULTS = frozenset({"failure", "cancelled"})
KNOWN_RESULTS = BLOCKING_RESULTS | {"success", "skipped"}


class GateError(SystemExit):
    def __init__(self, message: str) -> None:
        super().__init__(f"finalizer gate: {message}")


def _parse(name: str, raw: str) -> dict[str, str]:
    if not raw.strip():
        raise GateError(
            f"{name} is empty. An upstream job that failed before emitting it must "
            f"block finalization, never fall through to an empty set."
        )
    try:
        document = json.loads(raw)
    except json.JSONDecodeError as error:
        raise GateError(f"{name} is not JSON: {error}") from error
    if not isinstance(document, dict) or not all(
        isinstance(key, str) and isinstance(value, str)
        for key, value in document.items()
    ):
        raise GateError(f"{name} must be a JSON object of string to string")
    return document


def evaluate(
    enabled: dict[str, str],
    results: dict[str, str],
    required: dict[str, str],
) -> list[tuple[str, str, str, str]]:
    """Rows of `(destination, state, result, verdict)`, raising when finalization stops.

    Returned rather than printed so the caller owns the evidence format and the tests
    can assert the decision rather than a rendering of it.
    """
    missing = sorted(set(enabled) - set(results))
    if missing:
        raise GateError(
            f"no publisher result was supplied for {missing}; the finalizer must "
            f"`needs:` every publisher and pass each `needs.<job>.result`"
        )
    unplanned = sorted(set(results) - set(enabled))
    if unplanned:
        raise GateError(
            f"results were supplied for {unplanned}, which the plan job's enabled set "
            f"does not mention; the static job graph and the runtime set have drifted"
        )
    if not enabled:
        raise GateError("the enabled set names no destination at all")

    rows: list[tuple[str, str, str, str]] = []
    failures: list[str] = []
    for job, result in sorted(required.items()):
        if result not in KNOWN_RESULTS:
            raise GateError(f"required job {job!r} reported unknown result {result!r}")
        verdict = "ok" if result == "success" else "blocks"
        if verdict == "blocks":
            failures.append(f"required job {job!r} reported {result!r}")
        rows.append((job, "required", result, verdict))

    for destination, state in sorted(enabled.items()):
        result = results[destination]
        if state not in KNOWN_STATES:
            raise GateError(
                f"destination {destination!r} has unknown state {state!r}; expected one "
                f"of {sorted(KNOWN_STATES)}"
            )
        if result not in KNOWN_RESULTS:
            raise GateError(
                f"destination {destination!r} reported unknown result {result!r}"
            )
        if result in BLOCKING_RESULTS:
            reason = f"{destination} reported {result}"
        elif state in REQUIRED_STATES and result == "skipped":
            reason = (
                f"{destination} is enabled but was skipped, so an artifact the release "
                f"promises was never published"
            )
        else:
            reason = ""
        if reason:
            failures.append(reason)
        rows.append((destination, state, result, "blocks" if reason else "ok"))

    if failures:
        raise GateError(
            "refusing to create the Release or move any alias:\n  - "
            + "\n  - ".join(failures)
        )
    return rows


def render(rows: list[tuple[str, str, str, str]]) -> str:
    lines = [
        "### Finalization gate",
        "",
        "| Destination | Planned state | Job result | Verdict |",
        "| --- | --- | --- | --- |",
    ]
    lines += [
        f"| `{destination}` | `{state}` | `{result}` | `{verdict}` |"
        for destination, state, result, verdict in rows
    ]
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--enabled-destinations",
        default=os.environ.get("ENABLED_DESTINATIONS", ""),
        help="The plan job's enabled set, as JSON.",
    )
    parser.add_argument(
        "--results",
        default=os.environ.get("PUBLISHER_RESULTS", ""),
        help="Destination to `needs.<job>.result`, as JSON.",
    )
    parser.add_argument(
        "--required",
        default=os.environ.get("REQUIRED_RESULTS", "{}"),
        help=(
            "Jobs that must succeed whatever the destination set says -- the governed "
            "verifier and the plan job itself -- as JSON."
        ),
    )
    parser.add_argument(
        "--output",
        default=os.environ.get("GITHUB_STEP_SUMMARY", ""),
        help="File to append the evidence table to; stdout when empty.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _build_parser().parse_args(argv)
    rows = evaluate(
        _parse("ENABLED_DESTINATIONS", arguments.enabled_destinations),
        _parse("PUBLISHER_RESULTS", arguments.results),
        _parse("REQUIRED_RESULTS", arguments.required or "{}"),
    )
    rendered = render(rows)
    if arguments.output:
        with Path(arguments.output).open("a", encoding="utf-8") as stream:
            stream.write(f"{rendered}\n")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    sys.exit(main())
