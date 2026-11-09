"""Object Editor turnaround selection backed by persistent view-local records."""

from typing import TYPE_CHECKING

from rigora.application_services.object_views import ObjectViewsService
from rigora.domain.project import ProjectError

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


def change_view(host: "MainWindow", key: str, view: str) -> None:
    """Switch an editable slot without generating missing artwork or disabling the selector."""
    vm = host.viewmodel
    vm.playback.pause()
    try:
        service = ObjectViewsService(vm.documents)
        if service.edited_view(key) == view:
            return
        service.switch(key, view)
        if host.object_edit.active:
            host.object_edit.refresh()
        vm.changed.emit()
        host.statusBar().showMessage(f"Object View: {view}", 4000)
    except ProjectError as error:
        host.statusBar().showMessage(str(error), 6000)
        host.character_panel.refresh()
