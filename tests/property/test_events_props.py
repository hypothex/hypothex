"""Stateful property test of the SQLite event log against a list model."""

import json
import tempfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import HealthCheck, settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, rule

from hypothex.core.events import EventLog

# sqlite cannot store lone surrogates in TEXT; event types and ids never hold them
texts = st.text(st.characters(blacklist_categories=["Cs"]), max_size=10)
json_values = st.recursive(
    st.one_of(
        st.none(),
        st.booleans(),
        st.integers(-(2**63), 2**63 - 1),
        st.floats(allow_nan=False),
        texts,
    ),
    lambda kids: st.one_of(st.lists(kids, max_size=3), st.dictionaries(texts, kids, max_size=3)),
    max_leaves=8,
)
payloads = st.one_of(st.none(), st.dictionaries(texts, json_values, max_size=4))


class Boom(Exception):
    """A command that fails; its claim must be released."""


class EventLogMachine(RuleBasedStateMachine):
    def __init__(self) -> None:
        super().__init__()
        self._tmp = tempfile.TemporaryDirectory()
        self.log = EventLog(Path(self._tmp.name) / "events.db")
        self.model: list[tuple[str, str | None, str | None, dict[str, Any]]] = []
        self.keys: set[str] = set()
        self.results: dict[str, dict[str, Any]] = {}
        self.calls: dict[str, int] = {}

    def teardown(self) -> None:
        self._tmp.cleanup()

    def _expect(self, type_: str, project: str | None, run_id: str | None, payload: Any) -> None:
        self.model.append((type_, project, run_id, json.loads(json.dumps(payload or {}))))

    @rule(
        type_=texts,
        project=st.one_of(st.none(), texts),
        run_id=st.one_of(st.none(), texts),
        payload=payloads,
    )
    def append(self, type_: str, project: str | None, run_id: str | None, payload: Any) -> None:
        event = self.log.append(type_, project=project, run_id=run_id, payload=payload)
        self._expect(type_, project, run_id, payload)
        assert event.sequence == len(self.model)
        assert (event.type, event.project, event.run_id, event.payload) == self.model[-1]

    @rule(key=st.sampled_from(["k1", "k2", "k3", "mirror:h:e:1"]), type_=texts, payload=payloads)
    def append_once(self, key: str, type_: str, payload: Any) -> None:
        event = self.log.append_once(key, type_, payload=payload)
        if key in self.keys:
            assert event is None
            return
        self.keys.add(key)
        self._expect(type_, None, None, payload)
        assert event is not None and event.sequence == len(self.model)

    @rule(after=st.integers(-3, 40), limit=st.integers(1, 50))
    def since(self, after: int, limit: int) -> None:
        got = self.log.since(after, limit=limit)
        start = max(after, 0)
        want = self.model[start : start + limit]
        assert [e.sequence for e in got] == list(range(start + 1, start + 1 + len(want)))
        assert [(e.type, e.project, e.run_id, e.payload) for e in got] == want

    @rule(cid=st.sampled_from(["c1", "c2", "c3"]), value=json_values, fail=st.booleans())
    def run_once(self, cid: str, value: Any, fail: bool) -> None:
        def fn() -> dict[str, Any]:
            self.calls[cid] = self.calls.get(cid, 0) + 1
            if fail:
                raise Boom(cid)
            return {"value": value}

        before = self.calls.get(cid, 0)
        if cid in self.results:  # done once: never run again, same result
            assert self.log.run_once(cid, fn) == self.results[cid]
            assert self.calls.get(cid, 0) == before
            return
        if fail:  # a failure releases the claim, so a later call may run it
            with pytest.raises(Boom):
                self.log.run_once(cid, fn)
            assert self.calls[cid] == before + 1
            return
        result = self.log.run_once(cid, fn)
        assert result == json.loads(json.dumps({"value": value}))
        self.results[cid] = result

    @rule(value=json_values)
    def run_without_id_always_runs(self, value: Any) -> None:
        ran = []
        assert self.log.run_once(None, lambda: ran.append(1) or {"v": value}) == {"v": value}
        assert ran == [1]

    @invariant()
    def last_sequence_matches(self) -> None:
        assert self.log.last_sequence() == len(self.model)


EventLogMachine.TestCase.settings = settings(
    max_examples=25,
    stateful_step_count=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
TestEventLog = EventLogMachine.TestCase
