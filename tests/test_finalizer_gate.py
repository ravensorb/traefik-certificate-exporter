"""Decision cases for the finalization gate (ADR-0011).

The workflow wiring -- that every publisher's `needs.<job>.result` actually reaches this
module, and that the two mandatory anchors hold end to end -- is asserted in
`tests/ci/test_workflow_contracts.py` by executing the real step body. What is here is
the decision table itself, including the error paths a workflow cannot reach on purpose:
a destination with no result, a result for a destination nobody planned, and the states
and results neither forge produces.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

PROJECT_ROOT = Path(__file__).parents[1]


def _load() -> Any:
    location = PROJECT_ROOT / "scripts" / "finalizer_gate.py"
    spec = importlib.util.spec_from_file_location("finalizer_gate", location)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _load()

ENABLED = {
    "image-forge": "enabled",
    "image-dockerhub": "disabled",
    "package-forge": "unsupported",
    "package-pypi": "enabled",
}


def _results(**overrides: str) -> dict[str, str]:
    results = {
        "image-forge": "success",
        "image-dockerhub": "success",
        "package-forge": "skipped",
        "package-pypi": "success",
    }
    results.update(overrides)
    return results


def test_every_enabled_destination_succeeding_finalizes() -> None:
    rows = gate.evaluate(ENABLED, _results(), {"verify": "success"})
    assert {row[0] for row in rows} == set(ENABLED) | {"verify"}
    assert all(row[3] == "ok" for row in rows)


@pytest.mark.parametrize("destination", ["image-dockerhub", "package-forge"])
def test_a_destination_that_is_off_may_be_skipped(destination: str) -> None:
    """Disabled by toggle and absent by host capability both report `skipped`, both are
    legitimate, and they stay distinguishable in the evidence table -- conflating them
    makes "the forge stopped publishing packages" read like "someone turned it off"."""
    rows = gate.evaluate(
        ENABLED, _results(**{destination: "skipped"}), {"verify": "success"}
    )
    state = next(row[1] for row in rows if row[0] == destination)
    assert state in {"disabled", "unsupported"}
    assert all(row[3] == "ok" for row in rows)


def test_a_destination_that_is_off_may_also_have_run() -> None:
    """One job can carry several destinations: the image publisher pushes to the forge
    registry and to Docker Hub from a single Buildx invocation, so its `success` answers
    for both even when only one of them was addressed."""
    rows = gate.evaluate(
        ENABLED, _results(**{"image-dockerhub": "success"}), {"verify": "success"}
    )
    assert all(row[3] == "ok" for row in rows)


def test_an_enabled_destination_that_skipped_blocks_everything() -> None:
    with pytest.raises(SystemExit) as raised:
        gate.evaluate(
            ENABLED, _results(**{"package-pypi": "skipped"}), {"verify": "success"}
        )
    assert "package-pypi" in str(raised.value)


@pytest.mark.parametrize("result", ["failure", "cancelled"])
@pytest.mark.parametrize(
    "destination", ["image-forge", "image-dockerhub", "package-forge", "package-pypi"]
)
def test_any_failure_or_cancellation_blocks_even_a_disabled_destination(
    destination: str, result: str
) -> None:
    """`disabled` excuses an absence, never an error. A destination the plan turned off
    that nevertheless failed means the graph and the enabled set disagree, and moving
    `latest` over that disagreement is exactly what this gate exists to stop."""
    with pytest.raises(SystemExit) as raised:
        gate.evaluate(ENABLED, _results(**{destination: result}), {"verify": "success"})
    assert destination in str(raised.value)


def test_a_required_job_that_did_not_succeed_blocks() -> None:
    with pytest.raises(SystemExit) as raised:
        gate.evaluate(ENABLED, _results(), {"verify": "failure"})
    assert "verify" in str(raised.value)


def test_every_failure_is_reported_not_only_the_first() -> None:
    with pytest.raises(SystemExit) as raised:
        gate.evaluate(
            ENABLED,
            _results(**{"package-pypi": "skipped", "image-forge": "failure"}),
            {"verify": "failure"},
        )
    message = str(raised.value)
    assert "package-pypi" in message
    assert "image-forge" in message
    assert "verify" in message


def test_a_destination_with_no_result_is_a_wiring_defect() -> None:
    """The finalizer must `needs:` every publisher. A destination whose result never
    arrives would otherwise be silently treated as absent -- the static graph and the
    runtime set drifting apart, which is the defect ADR-0011 is about."""
    results = _results()
    del results["package-pypi"]
    with pytest.raises(SystemExit) as raised:
        gate.evaluate(ENABLED, results, {})
    assert "package-pypi" in str(raised.value)


def test_a_result_for_a_destination_nobody_planned_is_a_wiring_defect() -> None:
    with pytest.raises(SystemExit) as raised:
        gate.evaluate(ENABLED, _results(**{"package-testpypi": "success"}), {})
    assert "package-testpypi" in str(raised.value)


def test_an_empty_enabled_set_blocks_rather_than_finalizing_nothing() -> None:
    with pytest.raises(SystemExit):
        gate.evaluate({}, {}, {})


@pytest.mark.parametrize("state", ["", "true", "on", "ENABLED"])
def test_an_unrecognised_destination_state_blocks(state: str) -> None:
    with pytest.raises(SystemExit) as raised:
        gate.evaluate({"image-forge": state}, {"image-forge": "success"}, {})
    assert "image-forge" in str(raised.value)


@pytest.mark.parametrize("result", ["", "succeeded", "neutral"])
def test_an_unrecognised_job_result_blocks(result: str) -> None:
    with pytest.raises(SystemExit):
        gate.evaluate({"image-forge": "enabled"}, {"image-forge": result}, {})


@pytest.mark.parametrize("raw", ["", "   ", "not json", "[]", '{"a": 1}'])
def test_a_malformed_input_document_blocks(raw: str) -> None:
    """An upstream job that died before emitting the enabled set leaves the expression
    empty. Falling through to "no destinations, therefore nothing failed" would finalize
    a run whose plan job never finished."""
    with pytest.raises(SystemExit):
        gate._parse("ENABLED_DESTINATIONS", raw)


def test_the_cli_writes_its_evidence_table_where_it_is_told(tmp_path: Path) -> None:
    output = tmp_path / "summary.md"
    assert (
        gate.main(
            [
                "--enabled-destinations",
                json.dumps(ENABLED),
                "--results",
                json.dumps(_results()),
                "--required",
                json.dumps({"verify": "success"}),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    rendered = output.read_text(encoding="utf-8")
    for destination in ENABLED:
        assert f"`{destination}`" in rendered
    assert "`unsupported`" in rendered
    assert "`disabled`" in rendered
