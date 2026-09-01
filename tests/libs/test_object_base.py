"""Event-handler registration on ObjectBase.

`__event_handlers` was a class attribute holding a mutable dict. `on()` mutates it in
place, so it never created an instance attribute and every ObjectBase ever constructed
shared one registry: emitting an event on one object ran every other object's handlers,
and the registry grew without bound across instances. These tests pin the per-instance
behaviour so that regression cannot return quietly.
"""

from __future__ import annotations

from traefik_certificate_exporter.libs.object import ObjectBase


class _Recorder(ObjectBase):
    def __init__(self) -> None:
        self.seen: list[str] = []
        super().__init__()

    def _handle_on_progress(self, message: str) -> None:
        self.seen.append(message)


def test_emitting_on_one_instance_does_not_reach_another() -> None:
    first = _Recorder()
    second = _Recorder()

    first._raise_on_progress("only-for-first")

    assert first.seen == ["only-for-first"]
    assert second.seen == []


def test_each_instance_registers_its_progress_handler_exactly_once() -> None:
    # The shared-registry bug showed up here as a count that grew with every instance
    # constructed anywhere in the process, including by earlier tests.
    for _ in range(3):
        instance = _Recorder()
        assert len(instance._ObjectBase__event_handlers["progress"]) == 1


def test_a_handler_added_after_construction_stays_on_its_own_instance() -> None:
    subscriber = _Recorder()
    bystander = _Recorder()
    extra: list[str] = []

    subscriber.on("custom", extra.append)
    subscriber._emit("custom", "payload")

    assert extra == ["payload"]
    assert "custom" not in bystander._ObjectBase__event_handlers


def test_emitting_an_unregistered_event_is_a_no_op() -> None:
    _Recorder()._emit("never-registered", "payload")
