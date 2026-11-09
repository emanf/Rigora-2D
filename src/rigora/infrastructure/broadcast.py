"""Explicit loopback-only PNG output for local browser-source capture, with no remote service."""

import secrets
import struct
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Lock, Thread
from urllib.parse import urlsplit

from rigora.domain.project import ProjectError


class LocalBroadcast:
    """Own a single local listener and latest immutable frame until explicit stop."""

    def __init__(self) -> None:
        """Initialize dormant state without listening, rendering or opening another application."""
        self.server: HTTPServer | None = None
        self.thread: Thread | None = None
        self.url = ""
        self.frame: bytes | None = None
        self.frames = 0
        self.lock = Lock()

    def start(self, *, port: int = 0, fps: int = 24) -> str:
        """Bind IPv4 loopback with a fresh private session URL; port zero chooses a free port."""
        if self.server is not None:
            raise ProjectError("Stop the active local output before starting another.")
        if (
            type(port) is not int
            or not 0 <= port <= 65535
            or type(fps) is not int
            or not 1 <= fps <= 30
        ):
            raise ProjectError("Choose a port from 0–65535 and an output rate from 1–30 FPS.")
        token = secrets.token_urlsafe(24)
        owner = self
        page = (
            '<!doctype html><meta charset="utf-8"><title>Rigora output</title>'
            "<style>html,body{margin:0;width:100%;height:100%;overflow:hidden;background:transparent}"
            "img{width:100%;height:100%;object-fit:contain;display:block}</style>"
            '<img id="output"><script>const output=document.getElementById("output");'
            'async function update(){try{const r=await fetch("frame.png",{cache:"no-store"});'
            "if(r.ok&&r.status!==204){const blob=await r.blob();const previous=output.src;"
            'output.src=URL.createObjectURL(blob);if(previous.startsWith("blob:"))URL.revokeObjectURL(previous);}}'
            f"finally{{setTimeout(update,{1000 / fps:g});}}}}update();</script>"
        ).encode()

        class Handler(BaseHTTPRequestHandler):
            """Serve only the session page/frame; no filesystem, project or command endpoints."""

            server_version, sys_version = "Rigora", ""

            def setup(self) -> None:
                """Bound slow local clients so Stop can promptly release the listener."""
                super().setup()
                self.connection.settimeout(0.5)

            def do_GET(self) -> None:
                """Return immutable PNG/page snapshots behind the current session path."""
                path = urlsplit(self.path).path
                if path == f"/{token}/":
                    data, kind, status = page, "text/html; charset=utf-8", 200
                elif path == f"/{token}/frame.png":
                    with owner.lock:
                        data = owner.frame or b""
                    kind, status = "image/png", 200 if data else 204
                else:
                    self.send_error(404)
                    return
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", kind)
                    self.send_header("Content-Length", str(len(data)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Cross-Origin-Resource-Policy", "same-origin")
                    self.send_header("X-Content-Type-Options", "nosniff")
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError, TimeoutError):
                    return

            def log_message(self, format: str, *args: object) -> None:
                """Keep private session URLs out of console/access logs."""

        try:
            self.server = HTTPServer(("127.0.0.1", port), Handler)
        except OSError as error:
            raise ProjectError(f"Cannot start local output: {error}") from error
        self.frame, self.frames = None, 0
        self.url = f"http://127.0.0.1:{self.server.server_port}/{token}/"
        self.thread = Thread(
            target=self.server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True
        )
        self.thread.start()
        return self.url

    def publish(self, png: bytes) -> None:
        """Replace one bounded PNG atomically, retaining transparency without a frame backlog."""
        if (
            not isinstance(png, bytes)
            or not 24 <= len(png) <= 16 * 1024 * 1024
            or png[:8] != b"\x89PNG\r\n\x1a\n"
        ):
            raise ProjectError("Local output requires a PNG frame up to 16 MiB.")
        width, height = struct.unpack(">II", png[16:24])
        if not 1 <= width <= 4096 or not 1 <= height <= 4096 or width * height > 8_000_000:
            raise ProjectError("Local output exceeds its frame dimensions or pixel budget.")
        if self.server is not None:
            with self.lock:
                self.frame, self.frames = png, self.frames + 1

    def stop(self) -> None:
        """Stop accepting clients, release the socket/thread and forget the session's pixels/URL."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
        self.server, self.thread, self.url = None, None, ""
        with self.lock:
            self.frame = None
