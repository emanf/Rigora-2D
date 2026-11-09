"""Discoverable local automation configuration and canonical project inspection in the desktop."""

import json
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
)

from rigora.api import AutomationError, RigoraAPI
from rigora.infrastructure.processes import module_command
from rigora.presentation.widgets.window_frame import CustomDialog

if TYPE_CHECKING:
    from rigora.presentation.views.main_window import MainWindow


class AutomationDialog(CustomDialog):
    """Inspect the active document and prepare local MCP connection settings."""

    def __init__(self, window: "MainWindow") -> None:
        """Build inspection controls for the public API and authorized workspace."""
        super().__init__(window, "Automation & MCP")
        self.host = window
        self.resize(850, 620)
        box = QVBoxLayout(self.content)
        info = QLabel(
            "Python API, CLI and MCP use the same document, rig, mesh and animation "
            "services as the editor. Local stdio runs offline; HTTP must be explicitly "
            "enabled. No shell or Python-evaluation tool is exposed."
        )
        info.setWordWrap(True)
        box.addWidget(info)
        box.addWidget(QLabel("Authorized workspace directory"))
        doc = window.viewmodel.documents
        self.root = QLineEdit(str(doc.path.parent if doc.path else Path.cwd()))
        self.root.setAccessibleName("Automation workspace directory")
        box.addWidget(self.root)
        self.tabs = QTabWidget()
        box.addWidget(self.tabs, 1)
        self.inspect_output, self.config_output, self.cli_output = (
            QPlainTextEdit() for _ in range(3)
        )
        for title, widget in (
            ("Project inspection", self.inspect_output),
            ("MCP connection", self.config_output),
            ("CLI workflow", self.cli_output),
        ):
            widget.setReadOnly(True)
            self.tabs.addTab(widget, title)
        row = QHBoxLayout()
        inspect_button = QPushButton(window.icons.icon("refresh"), "Refresh inspection")
        inspect_button.setProperty("materialIcon", "refresh")
        inspect_button.clicked.connect(self.refresh)
        row.addWidget(inspect_button)
        copy = QPushButton(window.icons.icon("content_copy"), "Copy connection config")
        copy.setProperty("materialIcon", "content_copy")
        copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self.config_output.toPlainText())
        )
        row.addWidget(copy)
        self.export_button = export = QPushButton(window.icons.icon("image"), "Export SVG preview…")
        export.setProperty("materialIcon", "image")
        export.setEnabled(doc.project is not None)
        export.clicked.connect(window.export_preview)
        row.addWidget(export)
        box.addLayout(row)
        self.root.editingFinished.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        """Inspect through the canonical API and generate a path-scoped stdio configuration."""
        self.export_button.setEnabled(self.host.viewmodel.documents.project is not None)
        try:
            root = Path(self.root.text()).resolve(strict=True)
            api = RigoraAPI(root, document=self.host.viewmodel.documents)
            data = api.execute("project_inspect" if api.document.project else "diagnostics")
            self.inspect_output.setPlainText(json.dumps(data.to_dict(), indent=2))
            command = module_command("rigora.interfaces.mcp_server", "--root", str(root))
            config = {
                "mcpServers": {
                    "rigora": {
                        "command": command[0],
                        "args": command[1:],
                    }
                }
            }
            self.config_output.setPlainText(json.dumps(config, indent=2))
            self.cli_output.setPlainText(
                "uv sync --locked --extra gui --extra mcp\n\n"
                'rigora-automation --root "' + str(root) + '" diagnostics\n\n'
                'rigora-automation --root "'
                + str(root)
                + '" --dry-run batch examples/agent-workflow.json\n\n'
                'rigora-automation --root "'
                + str(root)
                + '" batch examples/agent-workflow.json\n\n'
                "The batch example must be inside the authorized root. "
                "Review its output paths first.\n"
                "MCP is optional; install the mcp extra before launching a client connection."
            )
        except (AutomationError, OSError, ValueError) as error:
            self.inspect_output.setPlainText(str(error))
            self.config_output.clear()
            self.cli_output.clear()
