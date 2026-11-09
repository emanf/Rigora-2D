import os
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def catalog_cache_root(tmp_path_factory):
    """Prepare the real catalog once; each test still owns its projects and preferences."""
    from rigora.application_services.illustration_cache import ensure_catalog

    root = tmp_path_factory.getbasetemp().parent / "rigora-test-generated-content"
    ensure_catalog(root)
    return root


@pytest.fixture
def current_pack(catalog_cache_root):
    """Read a real generated source collection without relying on retired bundled files."""
    from rigora.application_services.illustration_cache import cached_catalog
    from rigora.infrastructure.content_packs import read_pack

    return lambda name: read_pack(cached_catalog(catalog_cache_root) / (name + ".rigpack"))


@pytest.fixture(autouse=True)
def shared_generated_content(request, monkeypatch):
    """Inject reusable immutable test media; explicit cache roots retain cold-cache behavior."""
    from rigora.application_services.content_library import ContentLibrary

    initialize = ContentLibrary.__init__

    def initialize_library(self, *args, **kwargs):
        if kwargs.get("bundled") is None and "cache_root" not in kwargs:
            kwargs["cache_root"] = request.getfixturevalue("catalog_cache_root")
            if kwargs.get("allowed_roots") is not None:
                kwargs["allowed_roots"] = (*kwargs["allowed_roots"], kwargs["cache_root"].resolve())
        initialize(self, *args, **kwargs)

    monkeypatch.setattr(ContentLibrary, "__init__", initialize_library)


@pytest.fixture(autouse=True)
def isolated_preferences(tmp_path, monkeypatch):
    """Tests and their subprocesses never change the real desktop workspace."""
    monkeypatch.setenv("RIGORA_PREFERENCES_PATH", str(tmp_path / "workspace.json"))


@pytest.fixture(autouse=True)
def readable_ui_fonts(request):
    """Give offscreen Windows widgets real font metrics without importing Qt in core tests."""
    if not {"qtbot", "qapp"}.intersection(request.fixturenames):
        return
    app = request.getfixturevalue("qapp")
    request.getfixturevalue("gui_collection")
    if app.property("rigora_test_font_ready"):
        return
    font = Path(os.environ.get("WINDIR", "/nonexistent")) / "Fonts" / "segoeui.ttf"
    if font.exists():
        from PySide6.QtGui import QFont, QFontDatabase

        QFontDatabase.addApplicationFont(str(font))
        app.setFont(QFont("Segoe UI", 10))
    app.setProperty("rigora_test_font_ready", True)


@pytest.fixture(scope="session")
def gui_collection(qapp):
    """Match desktop bootstrap: finalize cyclic Qt wrappers only on the GUI thread."""
    from rigora.presentation.garbage_collection import GuiGarbageCollector

    collector = GuiGarbageCollector(qapp)
    yield collector
    collector.close()


@pytest.fixture
def fake_microphone(monkeypatch):
    """Substitute only the OS device boundary; real Qt buffers and capture services still run."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, Signal
    from PySide6.QtMultimedia import QAudioFormat, QtAudio

    from rigora.presentation.viewmodels import microphone

    class Device:
        """Expose one deterministic PCM input without contacting any hardware."""

        def id(self):
            return QByteArray(b"test-input")

        def isNull(self):
            return False

        def preferredFormat(self):
            audio_format = QAudioFormat()
            audio_format.setSampleRate(16000)
            return audio_format

        def isFormatSupported(self, audio_format):
            return audio_format.sampleRate() == 16000

    class Devices:
        """Resolve the explicit input using the same selection interface as Qt."""

        @staticmethod
        def audioInputs():
            return [Device()]

        @staticmethod
        def defaultAudioInput():
            return Device()

    class Source(QObject):
        """Return a real readable Qt device with deterministic signed PCM bytes."""

        stateChanged = Signal(object)

        def __init__(self, device, audio_format, parent):
            super().__init__(parent)
            self.buffer = QBuffer(self)
            self.buffer.setData(b"\x00\x20" * 1600)

        def start(self):
            self.buffer.open(QIODevice.OpenModeFlag.ReadOnly)
            return self.buffer

        def stop(self):
            self.buffer.close()
            self.stateChanged.emit(QtAudio.State.StoppedState)

        def error(self):
            return QtAudio.Error.NoError

    monkeypatch.setattr(microphone, "QMediaDevices", Devices)
    monkeypatch.setattr(microphone, "QAudioSource", Source)
    return microphone
