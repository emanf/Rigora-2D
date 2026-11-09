"""Explicit executable-code trust, lifecycle diagnostics and SDK callback execution controls."""

import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from rigora.application_services.documents import DocumentService
from rigora.application_services.plugin_jobs import run_isolated
from rigora.domain.project import ProjectError
from rigora.presentation.viewmodels.content_library import LibraryJob
from rigora.presentation.viewmodels.main_window import MainWindowViewModel
from rigora.presentation.widgets.file_dialogs import choose_open_file
from rigora.presentation.widgets.window_frame import CustomDialog
from rigora.sdk import API_VERSION, PluginRequest


class PluginManagerDialog(CustomDialog):
    """Inspect metadata before trust and expose activation, development loading and bounded jobs."""

    def __init__(self, parent: QWidget, model: MainWindowViewModel) -> None:
        """Build the shared custom window chrome and keep newly discovered Python disabled."""
        super().__init__(parent, "Rigora plugin manager")
        self.model, self.manager = model, model.plugins
        self.jobs: list[LibraryJob] = []
        self.resize(1000, 760)
        self.setMinimumSize(820, 600)
        layout = QVBoxLayout(self.content)
        top = QHBoxLayout()
        top.addWidget(
            QLabel(
                f"EXTENSIONS · API {API_VERSION}"
                + (" · SAFE MODE" if self.manager.safe_mode else "")
            ),
            1,
        )
        self.refresh_button = self.button("Refresh", "refresh", self.rediscover)
        self.add_button = self.button("Add development plugin…", "add", self.add_source)
        self.install_button = self.button("Install ZIP…", "file_download", self.install_archive)
        top.addWidget(self.refresh_button)
        top.addWidget(self.add_button)
        top.addWidget(self.install_button)
        layout.addLayout(top)
        note = QLabel(
            "Plugins execute Python code. Permissions describe intended access; they are not a "
            "security sandbox. Review the source and trust its author before enabling it."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        split = QSplitter()
        self.plugins = QListWidget()
        self.plugins.setAccessibleName("Discovered plugins")
        self.plugins.currentRowChanged.connect(self.select_plugin)
        split.addWidget(self.plugins)
        detail = QWidget()
        right = QVBoxLayout(detail)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("Plugin manifest and permissions")
        right.addWidget(self.details, 1)
        self.trust = QCheckBox("I have reviewed and trust this plugin's Python code and resources")
        self.trust.toggled.connect(self.update_controls)
        right.addWidget(self.trust)
        row = QHBoxLayout()
        self.enable_button = self.button("Trust and enable", "check_circle", self.enable)
        self.disable_button = self.button("Disable", "block", self.disable)
        row.addWidget(self.enable_button)
        row.addWidget(self.disable_button)
        self.open_button = self.button("Open panel", "open_in_new", self.open_panel)
        row.addWidget(self.open_button)
        right.addLayout(row)
        developer = QGroupBox("Developer console · validators and data callbacks")
        self.developer_console = developer
        developer.setCheckable(True)
        developer.setChecked(False)
        developer_layout = QVBoxLayout(developer)
        developer_body = QWidget()
        developer_layout.addWidget(developer_body)
        console = QVBoxLayout(developer_body)
        developer.toggled.connect(developer_body.setVisible)
        developer_body.hide()
        right.addWidget(developer)
        self.contributions = QComboBox()
        self.contributions.setAccessibleName("Active plugin callbacks")
        self.contributions.currentIndexChanged.connect(self.update_controls)
        console.addWidget(self.contributions)
        self.arguments = QPlainTextEdit("{}")
        self.arguments.setMaximumHeight(100)
        self.arguments.setAccessibleName("Plugin JSON arguments")
        console.addWidget(self.arguments)
        run_row = QHBoxLayout()
        self.isolated = QCheckBox("Run data job in a separate process (30 s timeout)")
        self.isolated.setChecked(True)
        run_row.addWidget(self.isolated, 1)
        self.run_button = self.button("Run callback", "play_arrow", self.run)
        run_row.addWidget(self.run_button)
        console.addLayout(run_row)
        split.addWidget(detail)
        split.setSizes([260, 720])
        layout.addWidget(split, 1)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setMaximumHeight(150)
        self.output.setAccessibleName("Plugin result and diagnostic log")
        layout.addWidget(self.output)
        close = self.button("Close", "close", self.close)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)
        model.plugins_changed.connect(self.refresh)
        self.refresh()

    def button(self, text: str, icon: str, callback: Any) -> QPushButton:
        """Create an accessible shared Material button with theme-aware icon metadata."""
        button = QPushButton(text)
        button.setProperty("materialIcon", icon)
        button.setIcon(self.icons.icon(icon))
        button.clicked.connect(callback)
        return button

    def selected_id(self) -> str:
        """Return the selected manifest identity without retaining a stale discovery object."""
        item = self.plugins.currentItem()
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else ""

    def refresh(self) -> None:
        """Rebuild metadata/status rows after activation while retaining the selected identity."""
        selected = self.selected_id()
        self.plugins.blockSignals(True)
        self.plugins.clear()
        index = 0
        for key, state in self.manager.states.items():
            status = "Enabled" if key in self.manager.contexts else "Disabled"
            if state.error:
                status = "Incompatible"
            item = QListWidgetItem(f"{state.manifest.name}\n{state.manifest.version} · {status}")
            item.setIcon(self.icons.icon(state.manifest.icon))
            item.setData(Qt.ItemDataRole.UserRole, key)
            self.plugins.addItem(item)
            if key == selected:
                index = self.plugins.count() - 1
        self.plugins.blockSignals(False)
        self.plugins.setCurrentRow(index if self.plugins.count() else -1)
        self.select_plugin()
        self.output.setPlainText("\n".join(self.manager.diagnostics[-30:]))

    def select_plugin(self, *_: Any) -> None:
        """Display manifest details and reset trust acknowledgement on selection."""
        state = self.manager.states.get(self.selected_id())
        self.trust.setChecked(False)
        self.contributions.clear()
        if state:
            self.details.setPlainText(
                state.manifest.description
                + "\n\nIntegration points:\n"
                + "\n".join(
                    f"• {c.name} [{c.kind}] " + ", ".join(c.metadata.get("placements", ()))
                    for c in self.manager.contributions()
                    if c.plugin_id == state.manifest.id
                )
                + "\n\nManifest:\n"
                + json.dumps(state.manifest.to_dict(), indent=2)
                + f"\n\nSource: {state.root}\nSHA-256: {state.fingerprint}\n"
                + (state.error or "")
                + f"\nDiagnostics: {self.manager.preferences.path.parent / 'plugins.log'}"
            )
            for contribution in self.manager.contributions():
                if contribution.plugin_id == state.manifest.id:
                    self.contributions.addItem(
                        f"{contribution.kind} · {contribution.name}", contribution
                    )
        else:
            self.details.setPlainText(
                f"No plugins discovered.\nLocal directory: {self.manager.root}\n"
                "Add a development rigora-plugin.json, or install a plugin wheel into Rigora's "
                "Python environment and refresh."
            )
        self.update_controls()

    def update_controls(self, *_: Any) -> None:
        """Require trust for activation and limit isolated execution to data callbacks."""
        state = self.manager.states.get(self.selected_id())
        trusted = bool(state and self.manager.trusted(state))
        busy = bool(self.jobs)
        self.enable_button.setText("Enable" if trusted else "Trust and enable")
        self.enable_button.setEnabled(
            bool(
                state
                and not state.error
                and not self.manager.safe_mode
                and not busy
                and state.manifest.id not in self.manager.contexts
                and (trusted or self.trust.isChecked())
            )
        )
        self.disable_button.setEnabled(self.selected_id() in self.manager.contexts and not busy)
        contribution = self.contributions.currentData()
        executable = bool(
            contribution
            and contribution.kind
            not in ("panels", "inspectors", "renderers", "track_types", "tools", "asset_packs")
        )
        self.run_button.setEnabled(executable and not busy)
        self.isolated.setEnabled(
            bool(
                contribution
                and contribution.kind in ("batch_jobs", "validators", "generators", "services")
            )
            and not busy
        )
        self.refresh_button.setEnabled(not busy)
        self.add_button.setEnabled(not busy)
        self.install_button.setEnabled(not busy)
        self.open_button.setEnabled(
            any(
                c.kind == "panels" and c.plugin_id == self.selected_id()
                for c in self.manager.contributions()
            )
        )

    def open_panel(self) -> None:
        """Navigate to the selected plugin's primary dock."""
        host = self.model.extensions.host
        if host:
            for contribution in self.manager.contributions("panels"):
                if contribution.plugin_id == self.selected_id():
                    host.show_panel(contribution.id)
                    return

    def install_archive(self) -> None:
        """Read a package on the worker, then refresh metadata on the GUI thread."""
        path, _ = choose_open_file(self, "Install Rigora plugin", "", "Plugin ZIP (*.zip)")
        if not path:
            return
        job = LibraryJob(lambda: self.manager.install_archive(Path(path)))
        self.jobs.append(job)

        def complete(result: Any) -> None:
            """Publish installation without trusting or executing new code."""
            self.jobs.remove(job)
            self.rediscover()
            self.output.setPlainText(
                f"Installed {result}. Review the source, then trust and enable."
            )
            self.update_controls()

        job.signals.done.connect(complete)
        job.signals.failed.connect(lambda error: self.finished_job(job, error))
        self.model.content.pool.start(job)
        self.output.setPlainText("Installing plugin…")
        self.update_controls()

    def rediscover(self) -> None:
        """Refresh fingerprints and restore only unchanged, previously enabled trusted code."""
        self.manager.discover()
        self.manager.restore()

    def add_source(self) -> None:
        """Remember a chosen manifest directory without importing or implicitly trusting it."""
        path, _ = choose_open_file(
            self,
            "Add development plugin",
            str(self.manager.root),
            "Plugin manifest (rigora-plugin.json)",
        )
        if path:
            try:
                self.manager.add_development(Path(path).parent)
            except (ProjectError, OSError) as error:
                self.output.setPlainText(str(error))

    def enable(self) -> None:
        """Apply the explicit checkbox decision through the shared ViewModel lifecycle command."""
        self.model.enable_plugin(self.selected_id(), trust=self.trust.isChecked())
        if self.model.plugin_error:
            self.output.setPlainText(self.model.plugin_error)

    def disable(self) -> None:
        """Disable a plugin and its dependents while retaining authored project data."""
        self.manager.disable(self.selected_id())

    def run(self) -> None:
        """Run shared commands or schedule bounded child jobs off the GUI thread."""
        contribution = self.contributions.currentData()
        if contribution is None:
            return
        try:
            if len(self.arguments.toPlainText()) > 65536:
                raise ProjectError("Plugin arguments must be smaller than 64 KiB.")
            arguments = json.loads(self.arguments.toPlainText())
            if not isinstance(arguments, dict):
                raise ProjectError("Plugin arguments must be a JSON object.")
            if self.isolated.isEnabled() and self.isolated.isChecked():
                state = self.manager.states[contribution.plugin_id]
                document = self.model.documents
                snapshot = None
                if document.project and "project.read" in state.manifest.permissions:
                    snapshot = DocumentService()
                    snapshot.new()
                    snapshot.project = document.project
                request = PluginRequest(snapshot, arguments)
                job = LibraryJob(lambda: run_isolated(self.manager, contribution.id, request))
                self.jobs.append(job)
                job.signals.done.connect(lambda result: self.finished_job(job, result))
                job.signals.failed.connect(lambda error: self.finished_job(job, error))
                self.model.content.pool.start(job)
                self.output.setPlainText("Running in a separate process…")
                self.update_controls()
            else:
                self.show_result(self.model.run_plugin(contribution.id, arguments))
        except (ProjectError, ValueError, TypeError, KeyError, RecursionError) as error:
            self.output.setPlainText(str(error))

    def finished_job(self, job: LibraryJob, result: Any) -> None:
        """Release the job on the GUI thread and display its data without publishing mutations."""
        self.jobs.remove(job)
        self.show_result(result)
        self.update_controls()

    def show_result(self, result: Any) -> None:
        """Display a bounded human-readable result including non-JSON path return values."""
        self.output.setPlainText(json.dumps(result, indent=2, default=str)[:65536])
