"""Application identity, creator contacts and runtime details in a dedicated About window."""

import platform

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import Qt, qVersion
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from rigora.app.application import ApplicationInfo
from rigora.infrastructure.migrations import CURRENT_VERSION
from rigora.presentation.icons import AppLogo
from rigora.presentation.widgets.window_frame import CustomDialog


class AboutDialog(CustomDialog):
    """Present app branding and owner information with scrollable details and a fixed footer."""

    def __init__(self, parent: QWidget, info: ApplicationInfo) -> None:
        """Build themed application details without loading remote content or modifying projects."""
        super().__init__(parent, f"About {info.name}")
        self.setMinimumSize(560, 420)
        self.resize(600, 600)
        outer = QVBoxLayout(self.content)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        body = QWidget()
        body.setObjectName("AboutBody")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        header = QHBoxLayout()
        header.setSpacing(20)
        self.logo = AppLogo(self.icons, 72)
        self.logo.setObjectName("AboutIcon")
        self.logo.setAccessibleName("Rigora 2D application icon")
        self.logo.setFixedSize(80, 80)
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(self.logo)
        identity = QVBoxLayout()
        identity.setSpacing(4)
        name = QLabel(info.name)
        name.setTextFormat(Qt.TextFormat.PlainText)
        name.setObjectName("AboutName")
        identity.addWidget(name)
        identity.addWidget(QLabel("A workspace for 2D rigging and animation"))
        version = QLabel(f"Version {info.version}  ·  In development")
        version.setObjectName("Muted")
        identity.addWidget(version)
        header.addLayout(identity, 1)
        layout.addLayout(header)

        description = QLabel(
            "Create and organize projects in a local desktop workspace with multiple tabs, "
            "a navigable canvas, portable assets, and undo/redo. Preview animated object "
            "transforms and hierarchical bones with real playback. Build rigs with bone "
            "tools, templates, IK / FK and constraints.\n"
            "Skinning, deformation and key editing are in development."
        )
        description.setWordWrap(True)
        description.setObjectName("Muted")
        layout.addWidget(description)

        creator = QFrame()
        creator.setObjectName("AboutContacts")
        contacts = QVBoxLayout(creator)
        contacts.setContentsMargins(16, 16, 16, 16)
        contacts.setSpacing(12)
        author = QLabel("Created by eManF")
        author.setObjectName("AboutCreator")
        contacts.addWidget(author)
        links = QGridLayout()
        links.setHorizontalSpacing(12)
        links.setVerticalSpacing(12)
        for row, (icon, title, text, target) in enumerate(
            (
                ("email", "Email", "emanf.cc0@gmail.com", "mailto:emanf.cc0@gmail.com"),
                (
                    "code",
                    "GitHub",
                    "github.com/emanf/rigora-2d",
                    "https://github.com/emanf/rigora-2d",
                ),
                ("language", "Website", "emanf.ir", "https://emanf.ir"),
            )
        ):
            glyph = QLabel()
            glyph.setPixmap(self.icons.icon(icon, 20).pixmap(20, 20))
            links.addWidget(glyph, row, 0)
            label = QLabel(title)
            label.setObjectName("Muted")
            links.addWidget(label, row, 1)
            link = QLabel(f'<a href="{target}">{text}</a>')
            link.setObjectName("AboutLink")
            link.setWordWrap(True)
            link.setOpenExternalLinks(True)
            link.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
            link.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            link.setAccessibleName(f"{title}: {text}")
            link.setToolTip(target)
            links.addWidget(link, row, 2)
        links.setColumnStretch(2, 1)
        contacts.addLayout(links)
        layout.addWidget(creator)

        details = QLabel(
            f"Python {platform.python_version()}  ·  PySide {pyside_version}  ·  Qt {qVersion()}\n"
            f"Project format {CURRENT_VERSION}  ·  {platform.system()} {platform.machine()}"
        )
        details.setObjectName("Muted")
        details.setWordWrap(True)
        details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(details)
        layout.addStretch(1)
        credits = QLabel(
            "Material Icons Outlined · Apache License 2.0\n"
            "Original Rigora app branding · bundled for offline use"
        )
        credits.setObjectName("Muted")
        credits.setWordWrap(True)
        layout.addWidget(credits)
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)

        footer = QFrame()
        footer.setObjectName("DialogFooter")
        buttons = QHBoxLayout(footer)
        buttons.setContentsMargins(24, 12, 24, 12)
        buttons.addStretch(1)
        self.close_button = QPushButton("Close")
        self.close_button.setObjectName("AboutClose")
        self.close_button.setAccessibleName("Close About Rigora 2D")
        self.close_button.setIcon(self.icons.icon("close"))
        self.close_button.setProperty("materialIcon", "close")
        self.close_button.setMinimumWidth(96)
        self.close_button.setDefault(True)
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        outer.addWidget(footer)
        self.close_button.setFocus()
