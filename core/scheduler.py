import inspect
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

from core.config import SCHEDULES_DIR

logger = logging.getLogger("SCHEDULER")

CALLBACKS: dict[str, Callable] = {}
_job_queue = None


def register_callback(key: str, fn: Callable) -> None:
    CALLBACKS[key] = fn


def unregister_callback(key: str) -> None:
    CALLBACKS.pop(key, None)


def list_callbacks() -> list[str]:
    return sorted(CALLBACKS.keys())


def set_job_queue(queue) -> None:
    global _job_queue
    _job_queue = queue


def _queue():
    if _job_queue is None:
        raise RuntimeError("Scheduler not initialized: set_job_queue() was not called")
    return _job_queue


def _file_for(name: str) -> Path:
    safe = "".join(
        c if (c.isalnum() or c in "-_.") else "_" for c in name
    ).strip("-_.")
    SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
    return SCHEDULES_DIR / f"{safe or 'job'}.yml"


def _to_absolute(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, timedelta):
        return datetime.now(timezone.utc) + value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    raise TypeError(f"Unsupported time value: {value!r}")


def _to_interval(value) -> float:
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (int, float)):
        return float(value)
    raise TypeError(f"Unsupported interval value: {value!r}")


def _serialize_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _deserialize_time(value) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _json_safe(value) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False


def _validate(callback: str, args: dict | None) -> None:
    if callback not in CALLBACKS:
        raise ValueError(
            f"Unknown callback key {callback!r}; register it first via register_callback()"
        )
    if args is not None and not isinstance(args, dict):
        raise TypeError("args must be a dict")
    if args and not _json_safe(args):
        raise ValueError("args must be JSON-serializable")


def _persist(spec: dict) -> None:
    path = _file_for(spec["name"])
    path.write_text(
        yaml.safe_dump(spec, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _delete(name: str) -> None:
    SCHEDULES_DIR.mkdir(parents=True, exist_ok=True)
    _file_for(name).unlink(missing_ok=True)


def _cancel_named(queue, name: str) -> None:
    for job in queue.get_jobs_by_name(name):
        job.schedule_removal()


def _cancel_all(queue) -> None:
    # KIV: cancels EVERY job in the queue, including any non-scheduler jobs
    # registered directly on application.job_queue by working code (they are
    # not re-registered from data/schedules/). If direct job_queue use is ever
    # introduced, track scheduler-owned names and cancel only those.
    for job in queue.jobs():
        job.schedule_removal()


def schedule_once(name: str, callback: str, when, args: dict | None = None):
    queue = _queue()
    _validate(callback, args)
    when_dt = _to_absolute(when)
    spec = {
        "name": name,
        "type": "once",
        "callback": callback,
        "when": _serialize_time(when_dt),
        "args": args or {},
    }
    _persist(spec)
    _cancel_named(queue, name)
    data = {"callback": callback, "args": args or {}}
    job = queue.run_once(_dispatch, when_dt, data=data, name=name)
    logger.info(
        "Scheduled once %r (callback=%r) at %s",
        name, callback, when_dt.isoformat(),
    )
    return job


def schedule_repeating(
    name: str,
    callback: str,
    interval,
    first=None,
    args: dict | None = None,
):
    queue = _queue()
    _validate(callback, args)
    interval_s = _to_interval(interval)
    first_dt = _to_absolute(first) if first is not None else None
    spec = {
        "name": name,
        "type": "repeating",
        "callback": callback,
        "interval": interval_s,
        "first": _serialize_time(first_dt) if first_dt else None,
        "args": args or {},
    }
    _persist(spec)
    _cancel_named(queue, name)
    data = {"callback": callback, "args": args or {}}
    job = queue.run_repeating(_dispatch, interval_s, first=first_dt, data=data, name=name)
    logger.info(
        "Scheduled repeating %r (callback=%r) every %ss",
        name, callback, interval_s,
    )
    return job


def remove_schedule(name: str) -> None:
    queue = _queue()
    _cancel_named(queue, name)
    _delete(name)
    logger.info("Removed schedule %r", name)


def list_schedules() -> list[dict]:
    if not SCHEDULES_DIR.exists():
        return []
    specs = []
    for path in sorted(SCHEDULES_DIR.glob("*.yml")):
        try:
            spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read schedule %s", path.name)
            continue
        if isinstance(spec, dict):
            specs.append(spec)
    return specs


async def _dispatch(context) -> None:
    job = context.job
    key = job.data.get("callback")
    args = job.data.get("args") or {}
    fn = CALLBACKS.get(key)
    if fn is None:
        logger.warning("No callback registered for key %r (job %r)", key, job.name)
        return
    try:
        result = fn(context, **args)
        if inspect.isawaitable(result):
            await result
    except Exception:
        logger.exception("Scheduled callback %r (job %r) failed", key, job.name)


def load_from_disk() -> None:
    queue = _queue()
    _load(queue)


def reload_from_disk() -> None:
    queue = _queue()
    _cancel_all(queue)
    _load(queue)
    logger.info("Schedules reloaded from %s", SCHEDULES_DIR)


def _load(queue) -> None:
    if not SCHEDULES_DIR.exists():
        return
    for path in sorted(SCHEDULES_DIR.glob("*.yml")):
        try:
            spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read schedule %s", path.name)
            continue
        if not isinstance(spec, dict):
            logger.warning("Invalid schedule spec in %s", path.name)
            continue
        _schedule_from_spec(queue, spec, path)


def _schedule_from_spec(queue, spec: dict, path: Path) -> None:
    name = spec.get("name")
    callback = spec.get("callback")
    job_type = spec.get("type")
    args = spec.get("args") or {}
    if not name or not callback or not isinstance(args, dict):
        logger.warning("Invalid schedule spec in %s", path.name)
        return
    if callback not in CALLBACKS:
        logger.warning("Schedule %r references unknown callback %r; skipping", name, callback)
        return
    _cancel_named(queue, name)
    data = {"callback": callback, "args": args}
    if job_type == "once":
        when = _deserialize_time(spec.get("when"))
        if when is None:
            logger.warning("Schedule %r has no 'when'; skipping", name)
            return
        if when <= datetime.now(timezone.utc):
            logger.info("One-time schedule %r already fired; removing file", name)
            path.unlink(missing_ok=True)
            return
        queue.run_once(_dispatch, when, data=data, name=name)
    elif job_type == "repeating":
        interval = spec.get("interval")
        if interval is None:
            logger.warning("Schedule %r has no 'interval'; skipping", name)
            return
        first = _deserialize_time(spec.get("first"))
        queue.run_repeating(_dispatch, float(interval), first=first, data=data, name=name)
    else:
        logger.warning("Unknown schedule type %r in %s", job_type, path.name)
