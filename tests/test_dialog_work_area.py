"""Custom dialog geometry remains reachable on smaller and offset monitor work areas."""

import pytest
from PySide6.QtCore import QRect, QSize

from rigora.presentation.widgets.window_frame import bounded_window_geometry


@pytest.mark.parametrize("available", (QRect(0, 0, 1280, 680), QRect(-1600, 100, 1600, 900)))
def test_dialog_fits_work_area_without_losing_footer(available):
    fitted = bounded_window_geometry(QRect(1800, 1000, 1400, 920), QSize(900, 560), available)
    assert available.contains(fitted)
    assert fitted.width() >= 900 and fitted.height() >= 560
