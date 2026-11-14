"""Trusted host only. Consume one bounded JSON document, never an agent report or executable."""
import json
import os
import stat
from dataclasses import asdict
from pathlib import Path
from .contracts import InvalidPlan
from .grading import evaluate, invalid
from .validation import decode_plan


def verify_file(world, path: Path, days):
    # Reject links, directories, FIFOs and huge files even for local replays.
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    except (FileNotFoundError, IsADirectoryError):
        return invalid("missing submission")
    except OSError as exc:
        import errno
        if exc.errno in (errno.ELOOP, errno.ENOTDIR, errno.EACCES):
            return invalid("unreadable submission")
        raise
    try:
        meta = os.fstat(fd)
        if not stat.S_ISREG(meta.st_mode) or meta.st_size > 16_384:
            return invalid("expected a regular JSON file of at most 16384 bytes")
        with os.fdopen(fd,"rb",closefd=False) as stream:
            contents = stream.read(16_385)
        if len(contents)>16_384:
            return invalid("oversized submission")
        plan = decode_plan(contents.decode("utf-8"),world)
    except (InvalidPlan,UnicodeError) as exc:
        return invalid(str(exc))
    finally:
        os.close(fd)
    return evaluate(world,json.loads(json.dumps(asdict(plan))),days)
