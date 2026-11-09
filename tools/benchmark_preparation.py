"""Compare real cold catalog worker responsiveness with thread and process preparation.

Runs offscreen, cancels each fresh-cache sample, and removes its temporary data.
The process mode runs the same generators without sharing the GUI interpreter's GIL.
"""

import argparse
import json
import os
import statistics
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QApplication

from rigora.application_services.content_library import ContentLibrary
from rigora.infrastructure.preferences import PreferencesStore
from rigora.presentation.viewmodels.content_library import LibraryViewModel


def measure(app: QApplication, folder: Path, isolated: bool, seconds: float) -> dict:
    """Measure GUI event gaps during actual preparation, excluding shutdown and setup."""
    owner = QObject()
    model = LibraryViewModel(owner, ContentLibrary(PreferencesStore(folder / "prefs.json")))
    model.library.isolate_preparation = isolated
    stamps = [time.perf_counter()]
    progress = []
    model.generation_progress.connect(lambda *value: progress.append(value))
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: stamps.append(time.perf_counter()))
    timer.start()
    model.reload()
    start = time.monotonic()
    while model.busy and time.monotonic() - start < seconds:
        app.processEvents()
        time.sleep(0.001)
    timer.stop()
    model.cancel_generation = True
    deadline = time.monotonic() + 10
    while model.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    model.shutdown()
    app.processEvents()
    gaps = sorted((b - a) * 1000 for a, b in zip(stamps, stamps[1:], strict=False))
    return {
        "mode": "process" if isolated else "thread",
        "samples": len(gaps),
        "median_gap_ms": round(statistics.median(gaps), 3),
        "p95_gap_ms": round(gaps[int((len(gaps) - 1) * 0.95)], 3),
        "max_gap_ms": round(max(gaps), 3),
        "last_progress": progress[-1] if progress else None,
        "preparation_error": model.error,
        "abandoned_staging": len(list(folder.rglob(".preparing-*"))),
    }


def main() -> None:
    """Use fresh temporary caches for both modes and retain only the measured JSON report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--output", type=Path, default=Path("build/preparation-performance.json"))
    args = parser.parse_args()
    if not 2 <= args.seconds <= 60:
        parser.error("seconds must be between 2 and 60")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication([])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=args.output.parent, prefix="preparation-") as directory:
        results = [
            measure(app, Path(directory) / str(mode), mode, args.seconds) for mode in (False, True)
        ]
    args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
