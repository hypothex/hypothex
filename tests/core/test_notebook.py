import os
import time
from collections.abc import Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from hypothex.core.context import Context
from hypothex.core.errors import ConfigError, StoreError
from hypothex.core.evaluation import evaluate_run
from hypothex.core.index import rebuild_index
from hypothex.core.notebook import (
    NOTEBOOK_MAX_BYTES,
    NotebookConflictError,
    NotebookTooLargeError,
    append_entry,
    day_path,
    hub_today,
    list_days,
    parse_day,
    parse_entries,
    read_day,
    run_links,
    today,
    write_day,
)
from hypothex.core.records import RunStatus
from hypothex.core.settings import settings_path
from tests.factories import PREDS_075, seed_finished_run

T = datetime(2026, 10, 4, 9, 14, tzinfo=UTC)
DAY = date(2026, 10, 4)


@pytest.fixture(autouse=True)
def utc_machine() -> Iterator[None]:
    """The default day is this machine's date: pin the machine to UTC."""
    old = os.environ.get("TZ")
    os.environ["TZ"] = "UTC"
    time.tzset()
    yield
    if old is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = old
    time.tzset()


@pytest.fixture
def toy(ctx: Context, toy_repo: Path) -> Context:
    ctx.register_project(toy_repo)
    return ctx


def test_append_writes_a_stamped_entry(toy: Context) -> None:
    day = append_entry(toy, "toy", "  first [[run:r1]]  ", "human:alice", now=T)
    path = day_path(toy.layout, "toy", DAY)
    assert path.read_text() == "\n## 2026-10-04T09:14:00+00:00 — human:alice\n\nfirst [[run:r1]]\n"
    assert day.day == DAY and day.text == path.read_text()
    assert day.hash.startswith("sha256:") and len(day.hash) == 7 + 64
    assert day.updated_at is not None


def test_list_days_is_newest_first_with_counts(toy: Context) -> None:
    append_entry(toy, "toy", "a", "human:sv", day=date(2026, 10, 3), now=T)
    append_entry(toy, "toy", "b", "human:sv", now=T)
    append_entry(toy, "toy", "c", "human:alice", now=T)
    days = list_days(toy, "toy")
    assert [d["day"] for d in days] == ["2026-10-04", "2026-10-03"]
    assert [d["entries"] for d in days] == [2, 1] and days[0]["bytes"] > 0


def test_missing_day_is_empty(toy: Context) -> None:
    day = read_day(toy, "toy", DAY)
    assert (day.text, day.hash, day.runs, day.updated_at) == ("", "", [], None)


def test_a_day_cleared_while_it_is_read_reads_as_empty(
    toy: Context, monkeypatch: pytest.MonkeyPatch
) -> None:
    append_entry(toy, "toy", "soon gone", "human:sv", now=T)
    real_open = Path.open

    def unlinked(self: Path, *args: Any, **kwargs: Any) -> Any:
        if self.suffix == ".md":  # an empty save removed the day after it was listed
            raise FileNotFoundError(str(self))
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unlinked)
    day = read_day(toy, "toy", DAY)
    assert (day.text, day.hash, day.updated_at) == ("", "", None)
    assert list_days(toy, "toy") == []


def test_run_chips_show_status_and_primary(toy: Context, toy_repo: Path) -> None:
    seed_finished_run(toy, toy_repo, "r1", predictions=PREDS_075)
    evaluate_run(toy, "r1")
    day = append_entry(toy, "toy", "see [[run:r1]] and [[run:nope]] and [[run:r1]]", "x", now=T)
    known, unknown = day.runs
    assert (known.run_id, known.status, known.task, known.primary) == (
        "r1",
        RunStatus.FINISHED,
        "toy-acc",
        0.75,
    )
    assert known.label == "r1"
    assert (unknown.status, unknown.label, unknown.primary) == (None, "nope", None)


def test_run_links_are_unique_in_order() -> None:
    text = "[[run:b]] [[run:a]] [[run:b]] [[run:-bad]] [[run:c.1_x-2]]"
    assert run_links(text) == ["b", "a", "c.1_x-2"]


def test_write_day_needs_the_current_hash(toy: Context) -> None:
    first = append_entry(toy, "toy", "one", "human:sv", now=T)
    edited = write_day(toy, "toy", DAY, "# edited\n", base_hash=first.hash, author="human:sv")
    assert edited.text == "# edited\n" and edited.hash != first.hash
    append_entry(toy, "toy", "two", "human:alice", now=T)  # appends never conflict
    with pytest.raises(NotebookConflictError) as info:
        write_day(toy, "toy", DAY, "mine", base_hash=edited.hash, author="human:sv")
    assert "two" in info.value.current.text
    cleared = write_day(toy, "toy", DAY, "", base_hash=info.value.current.hash, author="human:sv")
    assert cleared.text == "" and not day_path(toy.layout, "toy", DAY).exists()


def test_day_files_have_a_size_limit(toy: Context) -> None:
    with pytest.raises(NotebookTooLargeError):
        append_entry(toy, "toy", "x" * NOTEBOOK_MAX_BYTES, "human:sv", now=T)
    with pytest.raises(NotebookTooLargeError):
        write_day(toy, "toy", DAY, "y" * (NOTEBOOK_MAX_BYTES + 1), base_hash="", author="a")


def test_unknown_project_and_empty_entry(toy: Context) -> None:
    with pytest.raises(StoreError):
        append_entry(toy, "nope", "x", "human:sv")
    with pytest.raises(StoreError):
        list_days(toy, "nope")
    with pytest.raises(ConfigError):
        append_entry(toy, "toy", "   ", "human:sv")


def test_writes_emit_notebook_updated(toy: Context) -> None:
    before = toy.events.last_sequence()
    append_entry(toy, "toy", "x", "human:alice", now=T)
    (event,) = toy.events.since(before)
    assert event.type == "notebook.updated" and event.project == "toy"
    assert event.payload == {"project": "toy", "day": "2026-10-04", "author": "human:alice"}


def test_today_follows_the_timezone() -> None:
    late = datetime(2026, 10, 4, 23, 30, tzinfo=UTC)
    assert today(late, "Asia/Tokyo") == date(2026, 10, 5)
    assert today(late, "UTC") == date(2026, 10, 4)


def test_hub_today_uses_the_configured_zone_for_appends(toy: Context) -> None:
    late = datetime(2026, 10, 4, 23, 30, tzinfo=UTC)
    settings_path(toy.layout).write_text("digest: {timezone: Asia/Tokyo}\n")
    assert hub_today(toy, late) == date(2026, 10, 5)
    assert append_entry(toy, "toy", "late", "human:sv", now=late).day == date(2026, 10, 5)
    settings_path(toy.layout).write_text("digest: [broken\n")
    assert hub_today(toy, late) == today(late)  # a bad config.yaml falls back to this machine


def test_parse_day_and_entries() -> None:
    assert parse_day("2026-10-04") == DAY
    for bad in ("2026-13-01", "04-10-2026", "../x"):
        with pytest.raises(ConfigError):
            parse_day(bad)
    text = "\n## 2026-10-04T09:14:00+00:00 — human:alice\n\nbody one\n\n## bad — x\n\nlost\n"
    ((stamp, author, body),) = parse_entries(text)
    assert (stamp, author, body) == (T, "human:alice", "body one")


def test_reindex_never_touches_the_notebook(toy: Context) -> None:
    append_entry(toy, "toy", "keep", "human:sv", now=T)
    rebuild_index(toy.index, toy.store)
    assert "keep" in read_day(toy, "toy", DAY).text


def test_simultaneous_appends_preserve_every_entry(toy: Context) -> None:
    from concurrent.futures import ThreadPoolExecutor

    def add(index: int) -> None:
        append_entry(toy, "toy", f"entry-{index}", f"worker:{index}", now=T)

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(add, range(16)))
    entries = parse_entries(read_day(toy, "toy", DAY).text)
    assert len(entries) == 16
    assert {body for _, _, body in entries} == {f"entry-{i}" for i in range(16)}


def test_simultaneous_replacements_allow_one_current_hash(toy: Context) -> None:
    from concurrent.futures import ThreadPoolExecutor

    initial = append_entry(toy, "toy", "initial", "sv", now=T)

    def replace(index: int) -> bool:
        try:
            write_day(toy, "toy", DAY, f"writer-{index}", base_hash=initial.hash, author="sv")
        except NotebookConflictError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(replace, range(8)))
    assert sum(results) == 1


def test_hypothesis_chip_and_current_metric_versions(toy: Context, toy_repo: Path) -> None:
    from datetime import timedelta

    from hypothex.core.notebook import run_primary

    record = seed_finished_run(toy, toy_repo, "chip", predictions=PREDS_075)
    toy.update_run(
        "chip",
        "run.updated",
        lambda r: r.model_copy(update={"hypothesis": "Better features should improve accuracy"}),
    )
    evaluate_run(toy, "chip")
    scores = toy.index.scores_for(["chip"])["chip"]
    valid = next(s for s in scores if s.metric == "accuracy")
    toy.add_score(
        record,
        valid.model_copy(
            update={
                "version": "stale",
                "value": 0.99,
                "created_at": valid.created_at + timedelta(seconds=1),
            }
        ),
    )
    assert run_primary(toy, record) == 0.75
    chip = append_entry(toy, "toy", "[[run:chip]]", "sv", now=T).runs[0]
    assert chip.label == "Better features" and chip.primary == 0.75
    assert run_primary(toy, record.model_copy(update={"task": None})) is None
    assert run_primary(toy, record.model_copy(update={"task": "unknown"})) is None


def test_utf8_limit_and_rejected_write_preserve_previous_content(toy: Context) -> None:
    original = append_entry(toy, "toy", "keep", "sv", now=T)
    with pytest.raises(NotebookTooLargeError):
        write_day(
            toy, "toy", DAY, "é" * (NOTEBOOK_MAX_BYTES // 2), base_hash=original.hash, author="sv"
        )
    assert read_day(toy, "toy", DAY).hash == original.hash


def test_replacement_event_and_explicit_day(toy: Context) -> None:
    previous = date(2026, 10, 3)
    first = append_entry(toy, "toy", "prior", "sv", day=previous, now=T)
    before = toy.events.last_sequence()
    write_day(toy, "toy", previous, "replaced", base_hash=first.hash, author="alice")
    (event,) = toy.events.since(before)
    assert event.type == "notebook.updated"
    assert event.project == "toy"
    assert event.payload == {"project": "toy", "day": "2026-10-03", "author": "alice"}


def test_parse_entries_skips_naive_stamps_and_retains_bodies() -> None:
    text = (
        "## 2026-10-04T09:00:00 — naive\n\nignored\n"
        "## 2026-10-04T09:14:00+00:00 — alice\n\n**kept**\nsecond line\n"
    )
    assert parse_entries(text) == [(T, "alice", "**kept**\nsecond line")]
