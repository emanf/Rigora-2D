"""Disposable startup window with local recent projects and direct project commands."""

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from rigora.presentation.icons import AppLogo
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class WelcomeWindow(CustomDialog):
    """Offer startup actions without selecting, replacing or modifying a document."""

    def __init__(self, host: "MainWindow") -> None:
        """Bind existing commands and async IO status; never scan project directories."""
        super().__init__(host, "Welcome to Rigora 2D")
        self.host = host
        self._recent_signature: tuple[tuple[str, ...], str] | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMinimumSize(740, 480)
        self.resize(920, 590)
        self.titlebar.setFixedHeight(32)
        self.titlebar.minimize_button.hide()
        self.titlebar.maximize_button.hide()
        self.titlebar.close_button.setFixedSize(32, 32)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName("StartSidebar")
        sidebar.setFixedWidth(258)
        actions = QVBoxLayout(sidebar)
        actions.setContentsMargins(24, 30, 24, 24)
        actions.setSpacing(12)
        self.logo = AppLogo(self.icons, 48)
        actions.addWidget(self.logo)
        title = QLabel("Rigora 2D")
        title.setObjectName("StartHeading")
        actions.addWidget(title)
        description = QLabel("Create, rig and animate.\nYour next scene starts here.")
        description.setObjectName("Muted")
        description.setWordWrap(True)
        actions.addWidget(description)
        actions.addSpacing(18)
        self.new_button = QPushButton("New project")
        self.open_button = QPushButton("Open project…")
        for button, command in ((self.new_button, "new"), (self.open_button, "open")):
            button.setMinimumHeight(44)
            button.setProperty("startAction", True)
            button.setProperty(
                "materialIcon", host.command_actions[command].property("materialIcon")
            )
            button.setIcon(
                host.icons.icon(str(host.command_actions[command].property("materialIcon")))
            )
            button.setIconSize(QSize(20, 20))
            button.clicked.connect(host.command_actions[command].trigger)
            actions.addWidget(button)
        recover = QPushButton("Recover unsaved work…")
        recover.setProperty("materialIcon", "history")
        recover.setIcon(host.icons.icon("history"))
        recover.setMinimumHeight(36)
        recover.clicked.connect(host.show_recovery)
        actions.addWidget(recover)
        actions.addStretch(1)
        guide = QPushButton("Quick start and shortcuts")
        guide.setProperty("materialIcon", "menu_book")
        guide.setIcon(host.icons.icon("menu_book"))
        guide.clicked.connect(host.show_help)
        actions.addWidget(guide)
        version = QLabel(f"Version {host.viewmodel.info.version}")
        version.setObjectName("Muted")
        actions.addWidget(version)
        columns.addWidget(sidebar)
        projects = QVBoxLayout()
        projects.setContentsMargins(28, 28, 28, 20)
        projects.setSpacing(14)
        heading = QLabel("Recent projects")
        heading.setObjectName("StartSectionHeading")
        projects.addWidget(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a recent project")
        self.search.setAccessibleName("Find a recent project")
        self.search.addAction(host.icons.icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.filter_recent)
        projects.addWidget(self.search)
        self.recent = QListWidget()
        self.recent.setObjectName("StartRecentProjects")
        self.recent.setIconSize(QSize(28, 28))
        self.recent.setSpacing(4)
        self.recent.setWordWrap(False)
        self.recent.setAccessibleName("Recent projects · double-click to open")
        self.recent.itemActivated.connect(host.open_recent)
        projects.addWidget(self.recent, 1)
        self.empty = QLabel("No recent projects yet.\nCreate a project or open a .rigora file.")
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        projects.addWidget(self.empty)
        columns.addLayout(projects, 1)
        outer.addLayout(columns, 1)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(2)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Opening project")
        outer.addWidget(self.progress)
        footer = QFrame()
        footer.setObjectName("DialogFooter")
        row = QHBoxLayout(footer)
        row.setContentsMargins(20, 10, 20, 10)
        self.status = QLabel("All work stays on your computer")
        self.status.setObjectName("Muted")
        row.addWidget(self.status, 1)
        self.continue_button = QPushButton("Continue to workspace")
        self.continue_button.clicked.connect(self.close)
        row.addWidget(self.continue_button)
        outer.addWidget(footer)
        host.viewmodel.project_io.changed.connect(self.refresh_loading)
        host.viewmodel.theme_changed.connect(self.refresh_icons)
        self.refresh_recent()
        self.refresh_loading()

    def refresh_icons(self, *_: object) -> None:
        """Recolor open-window icons when the shared application theme changes."""
        self.titlebar.refresh()
        for button in self.findChildren(QPushButton):
            if icon := button.property("materialIcon"):
                button.setIcon(self.host.icons.icon(str(icon)))
        self.search.actions()[0].setIcon(self.host.icons.icon("search"))
        self.refresh_recent()

    def refresh_recent(self) -> None:
        """Display persisted paths without eager disk access or thumbnail generation."""
        signature = (tuple(self.host.viewmodel.preferences.recent), self.host.themes.name)
        if signature == self._recent_signature:
            return
        self._recent_signature = signature
        self.recent.clear()
        for path in self.host.viewmodel.preferences.recent:
            source = Path(path)
            item = QListWidgetItem(
                self.host.icons.icon("description"), f"{source.stem}\n{source.parent}"
            )
            item.setSizeHint(QSize(0, 64))
            item.setToolTip(path)
            item.setData(Qt.ItemDataRole.UserRole, path)
            self.recent.addItem(item)
        self.filter_recent()

    def filter_recent(self, *_: object) -> None:
        """Filter cached row text, keeping the empty state useful when nothing matches."""
        query = self.search.text().strip().casefold()
        visible = 0
        for index in range(self.recent.count()):
            item = self.recent.item(index)
            item.setHidden(query not in item.text().casefold())
            visible += not item.isHidden()
        self.recent.setVisible(visible > 0)
        self.empty.setVisible(visible == 0)
        self.empty.setText(
            "No matching projects. Try a different name."
            if self.recent.count()
            else "No recent projects yet.\nCreate a project or open a .rigora file."
        )

    def refresh_loading(self) -> None:
        """Keep the window responsive while the shared project service loads a file."""
        busy = any(key.startswith("open:") for key in self.host.viewmodel.project_io.jobs)
        self.progress.setVisible(busy)
        self.status.setText("Opening project…" if busy else "All work stays on your computer")
        self.open_button.setEnabled(not busy)
        self.recent.setEnabled(not busy)
