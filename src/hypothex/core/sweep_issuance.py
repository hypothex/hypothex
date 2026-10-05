"""Durable, sweep-specific metadata acceptance and cooperative issuance ownership."""

from __future__ import annotations

import fcntl
import hashlib
import logging
import re
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from hypothex.core import sweeps
from hypothex.core.context import Context
from hypothex.core.errors import StoreError
from hypothex.core.ids import utcnow
from hypothex.core.records import RunStatus

log = logging.getLogger(__name__)
ACTIVE = {"preparing", "queued", "issuing", "settling"}


class SweepIssuanceActiveError(sweeps.SweepError):
    """An accepted episode must finish before an explicit extension can begin."""


class SweepLegacyResumeRequiredError(sweeps.SweepError):
    """A legacy claim has no durable original options or acceptance receipt."""


@contextmanager
def _lock(ctx: Context, name: str, *, blocking: bool = True) -> Iterator[bool]:
    path = ctx.layout.home / "sweep-issuance" / hashlib.sha256(name.encode()).hexdigest()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class SweepIssuer:
    """
    Accept immutable sweep operations and own one bounded issuance worker.

    Parameters
    ----------
    ctx : Context
        Application-owned context; must remain available until ``stop`` returns.
    checkpoint : callable, optional
        Metadata boundary observer used for deterministic crash tests.
    """

    def __init__(self, ctx: Context, *, checkpoint: Callable[[str], None] | None = None) -> None:
        self.ctx = ctx
        self.checkpoint = checkpoint or (lambda _: None)
        self.wake = threading.Event()
        self.stopping = threading.Event()
        self.thread: threading.Thread | None = None

    def _read(self, key: str) -> dict[str, Any]:
        data = self.ctx.events.sweep_operation_by_key(key)
        if data is None:
            raise StoreError("missing durable sweep operation")
        return data

    def _update(
        self, key: str, *, state: dict[str, Any] | None = None, emit: bool = True, **changes: Any
    ) -> dict[str, Any]:
        while True:
            current = self._read(key)
            issuance = {**current["issuance"], **(state or {}), "updated_at": utcnow().isoformat()}
            updated = self.ctx.events.update_sweep(
                key, current["issuance"]["revision"], {**changes, "issuance": issuance}, emit=emit
            )
            if updated is not None:
                return updated

    def _new(
        self, key: str, request: dict[str, Any], *, previous: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        spec = sweeps.SweepSpec.model_validate(request["spec"])
        episode = previous["episode"] + 1 if previous else 1
        return {
            "schema_version": 1,
            "operation_key": key,
            "project": spec.project,
            "sweep_id": spec.id if previous else None,
            "episode": episode,
            "request": request,
            "run_ids": list(previous["run_ids"]) if previous else [],
            "inflight": None,
            "unresolved": _attempts(previous) if previous else [],
            "issuance": {
                "state": "preparing",
                "episode": episode,
                "revision": previous["issuance"]["revision"] + 1 if previous else 0,
                "planned": sweeps.planned_runs(spec),
                "accepted_at": None,
                "updated_at": utcnow().isoformat(),
                "cancel_requested": False,
                "reason": None,
                "error": None,
                "resume": None,
            },
        }

    def accept(
        self, command_id: str | None, prepare: Callable[[], dict[str, Any]]
    ) -> dict[str, Any]:
        """
        Commit metadata and return the original queued acceptance snapshot.

        Parameters
        ----------
        command_id : str or None
            Effective shared receipt key; None creates independent work.
        prepare : callable
            Validates original inputs and returns spec, repo and launch options.
            Evaluated only for a previously unclaimed key.

        Returns
        -------
        dict
            Immutable SweepSummary receipt; no member launch occurs here.
        """
        key = command_id or f"sweep:{uuid.uuid4()}"
        with _lock(self.ctx, f"accept:{key}"):
            op = self.ctx.events.sweep_operation_by_key(key)
            if op is None:
                receipt = self.ctx.events.command_result(key)
                if receipt is not None:
                    return receipt
                request = prepare()
                spec = sweeps.SweepSpec.model_validate(request["spec"])
                legacy = sweeps._claimed_sweep(self.ctx.layout, spec.project, command_id)
                if legacy:
                    raise SweepLegacyResumeRequiredError(
                        f"sweep {legacy} has a legacy claim; use hx sweep extend {legacy} --seeds "
                        f"{','.join(map(str, spec.seeds))}. Original zero-run launch options are "
                        "unavailable; use a new create command to specify them."
                    )
                op = self._new(key, request)
                if not self.ctx.events.prepare_sweep(key, op):
                    receipt = self.ctx.events.command_result(key)
                    if receipt is None:
                        raise StoreError("sweep command claim disappeared")
                    return receipt
                self.checkpoint("prepared")
            if op["issuance"]["state"] != "preparing":
                receipt = self.ctx.events.command_result(key)
                if receipt is None:
                    raise StoreError("accepted sweep has no receipt")
                return receipt
            return self._complete(op)

    def _complete(self, op: dict[str, Any]) -> dict[str, Any]:
        try:
            return self._publish(op)
        except Exception as exc:
            # This narrow recovery remains metadata-only; no launcher ran. Preserve
            # a diagnostic without acknowledging work or changing ordinary receipts.
            current = self._read(op["operation_key"])
            if current["issuance"]["state"] == "preparing":
                self._update(op["operation_key"], state={"error": _safe_error(exc)}, emit=False)
            raise

    def _publish(self, op: dict[str, Any]) -> dict[str, Any]:
        key = op["operation_key"]
        spec = sweeps.SweepSpec.model_validate(op["request"]["spec"])
        if op["sweep_id"] is None:
            sid = sweeps.new_sweep_id(self.ctx.layout, spec.project)
            op = self._update(key, sweep_id=sid, emit=False)
            self.checkpoint("bound")
        spec = spec.model_copy(update={"id": op["sweep_id"]})
        with sweeps._sweep_lock(self.ctx.layout, spec.project, spec.id):
            path = sweeps.sweep_path(self.ctx.layout, spec.project, spec.id)
            if path.exists() and path.stat().st_size:
                existing = sweeps.load_sweep(self.ctx.layout, spec.project, spec.id)
                # An extension intentionally publishes its grown seed list. Everything
                # else was frozen before preparation and must retain the same identity.
                if op["episode"] == 1 and existing != spec:
                    raise StoreError("prepared sweep definition differs from its saved request")
            sweeps._claim_sweep(self.ctx.layout, spec.project, key, spec.id)
            sweeps.save_sweep(self.ctx.layout, spec)
        self.checkpoint("published")
        op = self._read(key)
        queued = {
            **op["issuance"],
            "state": "queued",
            "accepted_at": utcnow().isoformat(),
            "updated_at": utcnow().isoformat(),
            "revision": op["issuance"]["revision"] + 1,
            "error": None,
        }
        receipt = sweeps.summarize_sweep(self.ctx, spec.project, spec.id).model_dump(mode="json")
        receipt["issuance"] = queued
        result = self.ctx.events.update_sweep(
            key, op["issuance"]["revision"], {"issuance": queued}, receipt=receipt
        )
        if result is None:
            raise StoreError("sweep preparation changed before acceptance")
        self.checkpoint("committed")
        self.wake.set()
        return receipt

    def extend(
        self, command_id: str | None, project: str, sweep_id: str, seeds: list[int]
    ) -> dict[str, Any]:
        """
        Accept a new episode using the saved options and immutable code pin.

        Parameters
        ----------
        command_id : str or None
            Effective command key; retry replays its original receipt.
        project, sweep_id : str
            Durable sweep identity.
        seeds : list of int
            New or existing seeds; existing seeds explicitly resume missing cells.

        Returns
        -------
        dict
            New queued acceptance snapshot.
        """
        key = command_id or f"sweep:{uuid.uuid4()}"
        with _lock(self.ctx, f"accept:{key}"):
            own = self.ctx.events.sweep_operation_by_key(key)
            if own is not None:
                if own["issuance"]["state"] == "preparing":
                    return self._complete(own)
                return self.ctx.events.command_result(key) or {}
            receipt = self.ctx.events.command_result(key)
            if receipt is not None:
                return receipt
            with _lock(self.ctx, f"episode:{project}:{sweep_id}"):
                previous = self.ctx.events.sweep_operation(project, sweep_id)
                if previous is None:
                    raise StoreError("sweep has no durable acceptance")
                if previous["issuance"]["state"] in ACTIVE:
                    raise SweepIssuanceActiveError(
                        f"sweep {sweep_id} issuance is active; inspect it before extending"
                    )
                if not seeds:
                    raise sweeps.SweepError("give at least one seed")
                spec = sweeps.load_sweep(self.ctx.layout, project, sweep_id)
                grown = spec.model_copy(
                    update={"seeds": list(dict.fromkeys([*spec.seeds, *seeds]))}
                )
                sweeps._check_launchable(grown)
                runs = sweeps.sweep_runs(self.ctx, spec)
                commit, diff = sweeps._pinned_code(self.ctx, spec, runs[0] if runs else None)
                grown = grown.model_copy(
                    update={
                        "commit": commit,
                        "diff": diff.decode() if isinstance(diff, bytes) else diff,
                    }
                )
                request = {**previous["request"], "spec": grown.model_dump(mode="json")}
                op = self._new(key, request, previous=previous)
                if not self.ctx.events.prepare_sweep(
                    key,
                    op,
                    previous=(previous["operation_key"], previous["issuance"]["revision"]),
                ):
                    current = self.ctx.events.sweep_operation(project, sweep_id)
                    if current is not None and current["issuance"]["state"] in ACTIVE:
                        raise SweepIssuanceActiveError(
                            f"sweep {sweep_id} issuance changed; inspect it before extending"
                        )
                    receipt = self.ctx.events.command_result(key)
                    if receipt is not None:
                        return receipt
                    raise StoreError("extension command or previous episode changed concurrently")
                return self._complete(op)

    def request_cancel(self, project: str, sweep_id: str) -> None:
        """
        Persist cooperative cancellation before the caller inspects queued runs.

        Parameters
        ----------
        project, sweep_id : str
            Sweep whose currently active episode should stop issuing.
        """
        target = self.ctx.events.sweep_operation(project, sweep_id)
        if target is None:
            return
        while True:
            current = self._read(target["operation_key"])
            latest = self.ctx.events.sweep_operation(project, sweep_id)
            if latest is None or latest["operation_key"] != target["operation_key"]:
                return
            unresolved_failure = current["issuance"]["state"] in {
                "incomplete",
                "interrupted",
            } and bool(_attempts(current) or current["run_ids"])
            if current["issuance"]["state"] not in ACTIVE and not unresolved_failure:
                return
            state = current["issuance"]
            if state["state"] == "preparing":
                raise SweepIssuanceActiveError(
                    "sweep acceptance is preparing; retry after acceptance"
                )
            if state["cancel_requested"]:
                return
            changed = {**state, "cancel_requested": True, "updated_at": utcnow().isoformat()}
            if unresolved_failure:
                changed.update(state="settling", reason=None, resume=None)
            if (
                self.ctx.events.update_sweep(
                    current["operation_key"],
                    state["revision"],
                    {"issuance": changed},
                    require_current=True,
                )
                is not None
            ):
                self.wake.set()
                return

    def _finish(
        self, key: str, state: str, reason: str | None = None, error: dict[str, str] | None = None
    ) -> None:
        while True:
            op = self._read(key)
            spec = sweeps.load_sweep(self.ctx.layout, op["project"], op["sweep_id"])
            resume = None
            target = state
            if op["issuance"]["cancel_requested"] and reason != "cancelled":
                target = "settling"  # cancellation won the terminal CAS; drain its stops
            if target in {"incomplete", "interrupted"}:
                resume = {
                    "seeds": spec.seeds,
                    "message": (
                        f"Resume missing cells with hx sweep extend {spec.id} --seeds "
                        f"{','.join(map(str, spec.seeds))}; running members continue."
                    ),
                }
            issuance = {
                **op["issuance"],
                "state": target,
                "reason": reason if target != "settling" else None,
                "error": error,
                "resume": resume,
                "updated_at": utcnow().isoformat(),
            }
            if (
                self.ctx.events.update_sweep(
                    key, op["issuance"]["revision"], {"issuance": issuance}
                )
                is not None
            ):
                return

    def _settle(self, key: str, stopper: Callable[[list[str]], sweeps.CancelResult] | None) -> None:
        op = self._read(key)
        spec = sweeps.load_sweep(self.ctx.layout, op["project"], op["sweep_id"])
        observed = {r.run_id: r for r in sweeps.sweep_runs(self.ctx, spec)}
        members = {(r.seed, sweeps._combo_key(r.params)): r for r in observed.values()}
        unresolved = []
        resolved = []
        for attempt in _attempts(op):
            member = members.get((attempt["seed"], sweeps._combo_key(attempt["params"])))
            if member is None:
                unresolved.append(attempt)
            else:
                resolved.append(member.run_id)
        if resolved:
            op = self._update(
                key,
                run_ids=list(dict.fromkeys([*op["run_ids"], *resolved])),
                inflight=None,
                unresolved=unresolved,
                emit=False,
            )
        if op["issuance"]["cancel_requested"]:
            pending = [
                rid
                for rid in op["run_ids"]
                if rid not in op.get("stopped_ids", [])
                and (rid not in observed or observed[rid].status == RunStatus.QUEUED)
            ]
            for offset in range(0, len(pending), sweeps.CANCEL_BATCH):
                batch = pending[offset : offset + sweeps.CANCEL_BATCH]
                try:
                    result = stopper(batch) if stopper else sweeps.stop_queued_runs(self.ctx, batch)
                except Exception as exc:
                    self._update(key, state={"error": _safe_error(exc)})
                    return
                if result.failed:
                    self._update(
                        key,
                        state={
                            "error": {
                                "type": "SweepCancellationError",
                                "message": (
                                    "Conditional cancellation remains unresolved; "
                                    "retry after the host is available."
                                ),
                            }
                        },
                    )
                    return
                op = self._update(key, stopped_ids=[*op.get("stopped_ids", []), *batch], emit=False)
            if unresolved:
                return  # no timeout or absent mirror can prove the attempt was not accepted
            self._finish(key, "interrupted", "cancelled")
            return
        if unresolved or not set(op["run_ids"]).issubset(observed):
            return
        if op.get("failed_attempt"):
            self._finish(key, "incomplete", "launch_failed", op["issuance"]["error"])
        else:
            self._finish(key, "issued")

    def _issue(self, op: dict[str, Any], launcher: sweeps.Launcher | None) -> None:
        key = op["operation_key"]
        spec = sweeps.load_sweep(self.ctx.layout, op["project"], op["sweep_id"])
        actual = launcher or sweeps._local_launcher(self.ctx, spec.id)

        def launch(req: sweeps.RunRequest, command_id: str) -> sweeps.RunRecord:
            while True:
                current = self._read(key)
                if self.stopping.is_set() or current["issuance"]["cancel_requested"]:
                    raise _Halt()
                # Admission and cancellation race on the same revision. A lost CAS
                # rechecks intent, rather than admitting a new call after cancellation.
                admitted = self.ctx.events.update_sweep(
                    key,
                    current["issuance"]["revision"],
                    {
                        "inflight": {
                            "command_id": command_id,
                            "seed": req.seed,
                            "params": req.params,
                        },
                        "unresolved": _attempts(current),
                        "issuance": {**current["issuance"], "updated_at": utcnow().isoformat()},
                    },
                    emit=False,
                )
                if admitted is not None:
                    break
            # From here the current attempt is durably identified; cancellation drains
            # this call, including any accepted remote run whose response is lost.
            record = actual(req, command_id)
            current = self._read(key)
            self._update(
                key,
                run_ids=list(dict.fromkeys([*current["run_ids"], record.run_id])),
                inflight=None,
                unresolved=[
                    attempt
                    for attempt in current.get("unresolved", [])
                    if (attempt["seed"], attempt["params"]) != (record.seed, record.params)
                ],
                emit=False,
            )
            return record

        request = op["request"]
        with sweeps._sweep_lock(self.ctx.layout, spec.project, spec.id):
            requests = sweeps._requests(
                spec,
                spec.seeds,
                Path(request["repo"]),
                owner=self.ctx.descriptor.environment_id,
                hypothesis=request["hypothesis"],
                gpus=request["gpus"],
                queue=request["queue"],
                commit=spec.commit,
                diff=spec.diff,
            )
            sweeps._issue(self.ctx, spec, launch, requests)

    def tick(
        self,
        launch: Callable[[sweeps.SweepSpec], sweeps.Launcher | None],
        stop: Callable[[sweeps.SweepSpec, str], Callable[[list[str]], sweeps.CancelResult] | None]
        | None = None,
    ) -> None:
        """
        Recover or dispatch available work once, with cross-process ownership.

        Parameters
        ----------
        launch : callable
            Build a launcher using the saved spec and live connection manager.
        stop : callable, optional
            Build the existing conditional batch stopper for a saved host.
        """
        for snapshot in self.ctx.events.sweep_operations(ACTIVE - {"preparing"}):
            if self.stopping.is_set():
                return
            key = snapshot["operation_key"]
            with _lock(self.ctx, "dispatcher", blocking=False) as owns_slot:
                if not owns_slot:
                    return
                with _lock(
                    self.ctx, f"issuer:{snapshot['project']}:{snapshot['sweep_id']}", blocking=False
                ) as owned:
                    if not owned:
                        continue
                    op = self._read(key)
                    state = op["issuance"]["state"]
                    if state not in ACTIVE:
                        continue
                    spec = sweeps.load_sweep(self.ctx.layout, op["project"], op["sweep_id"])
                    stopper = stop(spec, key) if stop else None
                    if state == "settling":
                        self._settle(key, stopper)
                        continue
                    if state == "issuing":
                        if op["issuance"]["cancel_requested"]:
                            self._update(key, state={"state": "settling"})
                            self._settle(key, stopper)
                        else:
                            self._finish(key, "interrupted", "worker_lost")
                        continue
                    if op["issuance"]["cancel_requested"]:
                        self._update(key, state={"state": "settling"})
                        self._settle(key, stopper)
                        continue
                    op = self._update(key, state={"state": "issuing"})
                    try:
                        self._issue(op, launch(spec))
                    except _Halt:
                        if self._read(key)["issuance"]["cancel_requested"]:
                            self._update(key, state={"state": "settling"})
                            self._settle(key, stopper)
                        else:
                            self._finish(key, "interrupted", "shutdown")
                        continue
                    except Exception as exc:
                        current = self._read(key)
                        attempt = current["inflight"]
                        if attempt is not None:
                            member = sweeps._member(
                                self.ctx, spec, attempt["seed"], attempt["params"]
                            )
                            if member is not None:
                                self._update(
                                    key,
                                    inflight=None,
                                    run_ids=list(
                                        dict.fromkeys([*current["run_ids"], member.run_id])
                                    ),
                                    emit=False,
                                )
                        cause = exc.__cause__ or exc
                        # A lost HTTP reply cannot establish whether the host accepted
                        # this member. Keep its deterministic identity until mirroring.
                        ambiguous = (
                            spec.host is not None
                            and getattr(cause, "status_code", "known") is None
                            and getattr(cause, "may_have_been_sent", True)
                        )
                        if self._read(key)["issuance"]["cancel_requested"]:
                            self._update(
                                key,
                                state={"state": "settling", "error": _safe_error(exc)},
                                failed_attempt=True,
                                inflight=self._read(key)["inflight"] if ambiguous else None,
                            )
                            self._settle(key, stopper)
                        else:
                            if not ambiguous:
                                self._update(key, inflight=None, emit=False)
                            self._finish(key, "incomplete", "launch_failed", _safe_error(exc))
                        continue
                    self._update(key, state={"state": "settling"})
                    self._settle(key, stopper)

    def start(
        self,
        launch: Callable[[sweeps.SweepSpec], sweeps.Launcher | None],
        stop: Callable[[sweeps.SweepSpec, str], Callable[[list[str]], sweeps.CancelResult] | None]
        | None = None,
    ) -> None:
        """
        Start one lifespan-owned periodic dispatcher.

        Parameters
        ----------
        launch, stop : callable
            Live host adapters passed through to ``tick``.
        """
        if self.thread is not None:
            raise RuntimeError("sweep issuer already started")

        def work() -> None:
            while not self.stopping.is_set():
                self.wake.clear()
                try:
                    self.tick(launch, stop)
                except Exception as exc:
                    log.error("sweep dispatcher failed (%s)", type(exc).__name__)
                self.wake.wait(0.25)

        self.thread = threading.Thread(target=work, name="hx-sweep-issuer", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        """Stop taking work and drain the current call before releasing host resources."""
        self.stopping.set()
        self.wake.set()
        if self.thread is not None:
            self.thread.join()


class _Halt(Exception):
    """Cooperative stop between member attempts, never halfway through a launch."""


def _attempts(op: dict[str, Any]) -> list[dict[str, Any]]:
    """Keep every unresolved admission, including those inherited from an earlier episode."""
    attempts = [*op.get("unresolved", [])]
    if op["inflight"] is not None:
        attempts.append(op["inflight"])
    return list({attempt["command_id"]: attempt for attempt in attempts}.values())


def _safe_error(exc: Exception) -> dict[str, str]:
    message = str(exc).replace("\n", " ")
    message = re.sub(
        r"""(?ix)\b(authorization|token|password|secret|api[_-]?key)
            ["']?\s*[:=]\s*["']?(?:(?:bearer|basic)\s+)?[^\s,;]+""",
        r"\1=[redacted]",
        message,
    )
    message = re.sub(r"(?i)\bbearer\s+\S+", "Bearer [redacted]", message)
    message = re.sub(r"https?://[^\s]+", "[endpoint]", message)
    return {"type": type(exc).__name__[:100], "message": message[:500]}
