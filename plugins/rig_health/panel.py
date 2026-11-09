"""Owned dark-theme dock displaying immutable diagnostics computed outside the GUI thread."""

import json

from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal, Slot
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from rigora.presentation.icons import IconProvider

from . import analyze


class ScanSignals(QObject):
    """Deliver one worker result to a still-living Qt receiver on its owning thread."""

    done = Signal(object, str)


class ScanJob(QRunnable):
    """Inspect a captured immutable project, never a live mutable document or a widget."""

    def __init__(self, project):
        """Retain one project snapshot and create the result signal on the GUI thread."""
        super().__init__()
        self.project = project
        self.signals = ScanSignals()

    def run(self):
        """Return static findings, containing analysis errors at the thread boundary."""
        try:
            result = analyze(self.project)
        except Exception as error:
            self.signals.done.emit(None, str(error))
        else:
            self.signals.done.emit(result, "")


class HealthPanel(QWidget):
    """Show one explicit scan; project changes invalidate results without scanning on playback."""

    def __init__(self, request, parent):
        """Build inherited-theme controls; the host owns and removes this dock's widget."""
        super().__init__(parent)
        self.setMinimumWidth(300)
        self.request = request
        self.project = None
        self.job = None
        self.report = None
        self.icons = IconProvider()
        layout = QVBoxLayout(self)
        actions = QHBoxLayout()
        self.scan_button = QPushButton("Scan project")
        self.scan_button.setIcon(self.icons.icon("fact_check"))
        self.scan_button.setAccessibleName("Scan rig health")
        self.scan_button.clicked.connect(self.start_scan)
        self.copy_button = QPushButton("Copy report")
        self.copy_button.setIcon(self.icons.icon("content_copy"))
        self.copy_button.clicked.connect(self.copy_report)
        self.copy_button.setEnabled(False)
        actions.addWidget(self.scan_button)
        actions.addWidget(self.copy_button)
        layout.addLayout(actions)
        self.summary = QLabel("Open a project to inspect its rigs.")
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.summary)
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setFixedHeight(3)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Rig health scan in progress")
        self.progress.hide()
        layout.addWidget(self.progress)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Level", "Item", "Finding"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 75)
        self.table.setColumnWidth(1, 140)
        self.table.setAccessibleName("Rig health findings")
        self.table.itemSelectionChanged.connect(self.show_detail)
        layout.addWidget(self.table, 1)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(180)
        self.detail.setAccessibleName("Rig health repair guidance")
        self.detail.setPlainText("Select a finding to see its explanation and next steps.")
        layout.addWidget(self.detail)
        scope = QLabel(
            "Static authored-data checks. This does not grade artwork or animated poses."
        )
        scope.setWordWrap(True)
        layout.addWidget(scope)
        self.rigora_bind(request)

    def rigora_bind(self, request):
        """Rebind the active project and mark results stale only when authored identity changes."""
        self.request = request
        project = request.document.project if request.document else None
        if project is not self.project:
            self.project = project
            self.report = None
            self.copy_button.setEnabled(False)
            self.table.setRowCount(0)
            self.detail.clear()
            self.summary.setText("Project changed — scan again." if project else "Open a project.")
        self.scan_button.setEnabled(project is not None and self.job is None)

    def start_scan(self):
        """Capture the current immutable revision and schedule one bounded background scan."""
        if self.project is None or self.job is not None:
            return
        self.report = None
        self.copy_button.setEnabled(False)
        self.table.setRowCount(0)
        self.detail.clear()
        self.scan_button.setEnabled(False)
        self.summary.setText("Scanning project…")
        self.progress.show()
        self.job = ScanJob(self.project)
        self.job.signals.done.connect(self.finished)
        QThreadPool.globalInstance().start(self.job)

    @Slot(object, str)
    def finished(self, report, error):
        """Publish matching results only; closing the dock automatically disconnects this slot."""
        scanned = self.job.project
        self.job = None
        self.progress.hide()
        self.scan_button.setEnabled(self.project is not None)
        if scanned is not self.project:
            return
        if error:
            self.summary.setText("Scan failed. You can retry.")
            self.detail.setPlainText(error)
            return
        self.report = report
        score = "No rig/artwork data" if report["score"] is None else f"{report['score']}/100"
        totals = report["totals"]
        self.summary.setText(
            f"Static health: {score}\nErrors: {report['errors']} · "
            f"Warnings: {report['warnings']} · "
            f"Notes: {report['notes']}\nRigs: {totals['rigs']} · Bones: {totals['bones']} · "
            f"Meshes: {totals['meshes']} · Keys: {totals['keys']}"
            + (
                f"\n{report['omitted_findings']} further findings omitted."
                if report["omitted_findings"]
                else ""
            )
        )
        self.summary.setToolTip(report["score_criteria"])
        self.table.setRowCount(len(report["findings"]))
        for index, finding in enumerate(report["findings"]):
            for column, value in enumerate(
                (finding["severity"].title(), finding["item"], finding["message"])
            ):
                cell = QTableWidgetItem(value)
                cell.setToolTip(value)
                self.table.setItem(index, column, cell)
        self.copy_button.setEnabled(True)
        if report["findings"]:
            self.table.selectRow(0)
        else:
            self.detail.setPlainText(
                "No findings in the checks covered by this scan.\n\n" + report["scope"]
            )

    def show_detail(self):
        """Expose exact scene/item identifiers and practical guidance for the selected finding."""
        row = self.table.currentRow()
        if self.report and 0 <= row < len(self.report["findings"]):
            finding = self.report["findings"][row]
            self.detail.setPlainText(
                f"{finding['scene']} / {finding['item']}\n{finding['message']}\n\n"
                f"{finding['suggestion']}\n\nItem ID: {finding['item_id']}"
            )

    def copy_report(self):
        """Copy the bounded JSON report only when it still matches the active project revision."""
        if self.report:
            QApplication.clipboard().setText(json.dumps(self.report, indent=2, ensure_ascii=False))
