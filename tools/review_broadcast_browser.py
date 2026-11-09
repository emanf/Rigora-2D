"""Validate actual local browser-source decoding offscreen without OBS or any capture hardware."""

import json
import os
from pathlib import Path


def review() -> None:
    """Run the private page in Qt WebEngine and check decoded dimensions/transparency."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--disable-gpu"
    import resvg_py
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtWebEngineCore import QWebEnginePage
    from PySide6.QtWidgets import QApplication

    from rigora.infrastructure.broadcast import LocalBroadcast

    app = QApplication([])
    output = LocalBroadcast()
    address = output.start(fps=10)
    output.publish(
        resvg_py.svg_to_bytes(
            svg_string='<svg xmlns="http://www.w3.org/2000/svg" '
            'width="64" height="36"><rect x="10" y="10" width="8" height="8" fill="#ffffff"/></svg>'
        )
    )
    page = QWebEnginePage()
    result = {}

    def received(value: object) -> None:
        """Poll until a PNG is decoded, then record actual browser pixels and stop."""
        if not isinstance(value, str):
            return
        data = json.loads(value)
        if not data.get("width"):
            QTimer.singleShot(100, inspect)
            return
        result.update(data)
        app.quit()

    def inspect() -> None:
        """Read the page's real decoded image, never an assumed successful HTTP response."""
        page.runJavaScript(
            '(()=>{const image=document.getElementById("output");'
            "if(!image.naturalWidth)return JSON.stringify({});"
            'const c=document.createElement("canvas");'
            'c.width=64;c.height=36;const x=c.getContext("2d");x.drawImage(image,0,0);'
            "return JSON.stringify({width:image.naturalWidth,height:image.naturalHeight,"
            'blob:image.src.startsWith("blob:"),transparent:x.getImageData(0,0,1,1).data[3],'
            "opaque:x.getImageData(12,12,1,1).data[3]});})()",
            received,
        )

    def loaded(ok: bool) -> None:
        """Start DOM checks only after local navigation; fail cleanly if the page cannot load."""
        if ok:
            QTimer.singleShot(100, inspect)
        else:
            app.quit()

    page.loadFinished.connect(loaded)
    page.load(QUrl(address))
    QTimer.singleShot(15000, app.quit)
    try:
        app.exec()
    finally:
        output.stop()
        page.deleteLater()
        app.processEvents()
    expected = {"width": 64, "height": 36, "blob": True, "transparent": 0, "opaque": 255}
    if result != expected:
        raise AssertionError(result)
    target = Path("build/broadcast-browser-review.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    review()
