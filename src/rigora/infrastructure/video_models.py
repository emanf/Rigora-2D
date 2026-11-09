"""Explicit, cancellable installation of the local video pose model bundle."""

import hashlib
import os
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path
from threading import Event

from rigora.domain.project import ProjectError
from rigora.resources import asset_path

# Upstream release filenames and the animal repository revision are immutable sources.
MODELS = {
    "human_detector": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "yolox_s_8xb8-300e_humanart-3ef259a7.zip",
        "332e09ea9696e3401049b6c5314851db020b6430f85da159e65f37034ab3aee8",
    ),
    "human_pose": (
        "https://download.openmmlab.com/mmpose/v1/projects/rtmposev1/onnx_sdk/"
        "rtmpose-m_simcc-body7_pt-body7_420e-256x192-e48f03d0_20230504.zip",
        "5c0a4bf67953e6d2ac43ce15e77dc9d5d354ae18430a47d2c5963a7bc5683e3c",
    ),
    "animal_detector": (
        "https://github.com/Megvii-BaseDetection/YOLOX/releases/download/0.1.1rc0/yolox_s.onnx",
        "c5c2d13e59ae883e6af3b45daea64af4833a4951c92d116ec270d9ddbe998063",
    ),
    "animal_pose": (
        "https://huggingface.co/JunkyByte/easy_ViTPose/resolve/"
        "e83805274e89428969355ec4afffcbc413e79188/onnx/apt36k/vitpose-s-apt36k.onnx",
        "2a40f76421d87f1b03f1204949d67014dbb876b7572c2bbc60ce2be45f6b4172",
    ),
}


def model_directory() -> Path:
    """Locate optional downloaded models outside the source and project archives."""
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache"))
    return base / "Rigora" / "models" / "video-rig-v1"


def check_cancel(cancel: Event) -> None:
    """Abort before the next decode, inference or disk publication boundary."""
    if cancel.is_set():
        raise ProjectError("Video rig operation cancelled.")


def install_models(
    directory: Path,
    *,
    cancel: Event | None = None,
    progress: Callable[[float, str], None] = lambda value, message: None,
) -> None:
    """Download known upstream ONNX models on explicit request, publishing each atomically.

    Archives are read by member rather than extracted into the filesystem. Interrupted
    downloads remain temporary and never replace a previously usable model.
    """
    cancel = cancel or Event()
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("NOTICE.txt", "Apache-2.0.txt"):
        source = asset_path("licenses/video-rig/" + name)
        (directory / name).write_bytes(source.read_bytes())
    for index, (key, (url, expected)) in enumerate(MODELS.items()):
        check_cancel(cancel)
        target = directory / (key + ".onnx")
        if target.is_file() and target.stat().st_size <= 512 * 1024 * 1024:
            with target.open("rb") as cached:
                if hashlib.file_digest(cached, "sha256").hexdigest() == expected:
                    continue
        progress(index / len(MODELS), "Downloading " + key.replace("_", " "))
        with tempfile.TemporaryFile() as stream:
            with urllib.request.urlopen(url, timeout=30) as response:
                size = 0
                total = int(response.headers.get("Content-Length", 0))
                while block := response.read(1024 * 1024):
                    check_cancel(cancel)
                    size += len(block)
                    if size > 512 * 1024 * 1024:
                        raise ProjectError("Video model download exceeds 512 MiB.")
                    stream.write(block)
                    fraction = min(0.99, size / total) if total > 0 else 0
                    progress(
                        (index + fraction) / len(MODELS),
                        f"Downloading {key.replace('_', ' ')} · {size / 1024**2:.1f} MiB",
                    )
            stream.seek(0)
            if url.endswith(".zip"):
                with zipfile.ZipFile(stream) as archive:
                    members = [
                        item for item in archive.infolist() if item.filename.endswith(".onnx")
                    ]
                    if len(members) != 1 or members[0].file_size > 512 * 1024 * 1024:
                        raise ProjectError("The upstream model archive has an unexpected layout.")
                    data = archive.read(members[0])
            else:
                data = stream.read()
        if expected and hashlib.sha256(data).hexdigest() != expected:
            raise ProjectError("Video model checksum mismatch: " + key)
        check_cancel(cancel)
        descriptor, temporary = tempfile.mkstemp(dir=directory, suffix=".download")
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)
            Path(temporary).replace(target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    progress(1, "Video pose models installed; future analysis works offline.")
