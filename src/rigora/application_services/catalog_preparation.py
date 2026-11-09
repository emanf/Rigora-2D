"""Prepare generated content in a cancellable process so native raster work cannot stall Qt."""

import multiprocessing
import time
from concurrent.futures import CancelledError
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any

from rigora.application_services.illustration_cache import (
    Progress,
    cached_catalog,
    catalog_ready,
    ensure_catalog,
)
from rigora.domain.project import ProjectError


def _prepare(root: Path, pipe: Connection, stop: Any) -> None:
    """Own cache publication in the child; send only bounded progress and completion messages."""
    try:
        target = ensure_catalog(root, lambda *data: pipe.send(("progress", data)), stop.is_set)
        pipe.send(("ready", str(target)))
    except CancelledError:
        pipe.send(("cancelled", ""))
    except Exception as error:
        pipe.send(("error", str(error)[:4096]))
    finally:
        pipe.close()


def prepare_catalog(root: Path, progress: Progress | None = None, cancelled: Any = None) -> Path:
    """Wait on a worker thread while a spawned process builds and atomically publishes the cache.

    No live document or Qt object crosses the process boundary. Cancellation is
    cooperative so the child can remove its private staging files before exiting.
    """
    if catalog_ready(root):
        return cached_catalog(root)
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    stop = context.Event()
    child = context.Process(target=_prepare, args=(root, send, stop), daemon=True)
    try:
        child.start()
    except BaseException:
        receive.close()
        send.close()
        child.close()
        raise
    send.close()
    deadline = time.monotonic() + 900
    cancel_deadline: float | None = None
    try:
        while True:
            if cancelled and cancelled():
                stop.set()
                cancel_deadline = cancel_deadline or time.monotonic() + 5
            if receive.poll(0.025):
                try:
                    kind, value = receive.recv()
                except EOFError as error:
                    raise ProjectError("Content preparation stopped before completion.") from error
                if kind == "progress":
                    if progress:
                        progress(*value)
                elif kind == "ready":
                    if stop.is_set():
                        raise CancelledError()
                    return Path(value)
                elif kind == "cancelled":
                    raise CancelledError()
                else:
                    raise ProjectError("Content preparation failed: " + value)
            if cancel_deadline and time.monotonic() > cancel_deadline:
                raise CancelledError()
            if not child.is_alive():
                raise ProjectError(f"Content preparation exited unexpectedly ({child.exitcode}).")
            if time.monotonic() > deadline:
                raise ProjectError("Content preparation exceeded its time limit; try again.")
    finally:
        stop.set()
        child.join(1)
        if child.is_alive():
            child.terminate()
            child.join(2)
        receive.close()
        child.close()
