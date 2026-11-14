"""Trusted host only. Consume one bounded JSON document, never an agent report or executable."""

from collections.abc import Sequence
from dataclasses import asdict
import errno
import json
import os
from pathlib import Path
import stat

from .contracts import Evaluation, InvalidPlan, World
from .grading import evaluate, evaluate_any, evaluate_quarterly, invalid
from .validation import decode_any_plan, decode_plan, decode_quarterly_plan


def _read_bounded_utf8(path: Path) -> tuple[str | None, Evaluation | None]:
    """Read regular UTF-8 JSON file <= 16_384 bytes with O_NOFOLLOW; return (text, None) or (None, invalid_eval)."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except (FileNotFoundError, IsADirectoryError):
        return None, invalid("missing submission")
    except OSError as exc:
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES):
            return None, invalid("unreadable submission")
        raise
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > 16_384:
            return None, invalid("expected a regular JSON file of at most 16384 bytes")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            contents = stream.read(16_385)
        if len(contents) > 16_384:
            return None, invalid("oversized submission")
        return contents.decode("utf-8"), None
    except UnicodeError as exc:
        return None, invalid(str(exc))
    finally:
        os.close(fd)


def verify_file(world, path: Path, days):
    # Reject links, directories, FIFOs and huge files even for local replays.
    text, err = _read_bounded_utf8(path)
    if err is not None:
        return err
    assert text is not None
    try:
        plan = decode_plan(text, world)
    except InvalidPlan as exc:
        return invalid(str(exc))
    return evaluate(world, json.loads(json.dumps(asdict(plan))), days)


def verify_quarterly_file(world: World, path: Path, seeds: Sequence[int]) -> Evaluation:
    text, err = _read_bounded_utf8(path)
    if err is not None:
        return err
    assert text is not None
    try:
        plan = decode_quarterly_plan(text, world)
    except InvalidPlan as exc:
        return invalid(str(exc))
    return evaluate_quarterly(world, json.loads(json.dumps(asdict(plan))), seeds)


def verify_any_file(world: World, path: Path, seeds: Sequence[int]) -> Evaluation:
    text, err = _read_bounded_utf8(path)
    if err is not None:
        return err
    assert text is not None
    try:
        plan = decode_any_plan(text, world)
    except InvalidPlan as exc:
        return invalid(str(exc))
    return evaluate_any(world, json.loads(json.dumps(asdict(plan))), seeds)
