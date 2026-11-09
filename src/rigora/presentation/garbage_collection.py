"""Keep cyclic Qt wrapper destruction on the application thread."""

import gc

from PySide6.QtCore import QObject, QTimer


class GuiGarbageCollector(QObject):
    """Replace allocation-triggered collections with threshold checks in the GUI event loop.

    A worker can allocate the object that triggers Python's cyclic collector and
    thereby finalize unreachable widget wrappers on that worker. Qt widgets and
    their Python virtual methods must instead be destroyed on the GUI thread.
    Reference counting remains immediate; only cyclic collection is scheduled.
    """

    def __init__(self, parent: QObject) -> None:
        """Retain the caller's GC policy and start bounded, generation-aware checks."""
        super().__init__(parent)
        self.was_enabled = gc.isenabled()
        gc.disable()
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.collect)
        self.timer.start()

    def collect(self) -> None:
        """Apply Python's configured generation thresholds exclusively from the GUI loop."""
        counts, thresholds = gc.get_count(), gc.get_threshold()
        if thresholds[0] and counts[0] >= thresholds[0]:
            generation = 2 if counts[2] >= thresholds[2] else 1 if counts[1] >= thresholds[1] else 0
            gc.collect(generation)

    def close(self) -> None:
        """Drain cycles after desktop workers stop and restore the embedding process's policy."""
        self.timer.stop()
        gc.collect()
        if self.was_enabled:
            gc.enable()
