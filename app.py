"""RGB Panel desktop app: the web panel in a native window, plus the OpenRGB watchdog.

If the "RGB Panel" web task is already serving on 127.0.0.1:6780 the window simply opens that, so
there is exactly one backend (and one effects engine) at a time. Otherwise the same backend from
panel.py is started in-process on a private port.

Build:  uv run pyinstaller app.spec --noconfirm
Run from source:  uv run python app.py
"""
from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import webview

import panel

WINDOW_TITLE = "RGB Panel"
WEB_PANEL_PORT = 6780


def serve() -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), panel.Handler)
    host, port = srv.server_address[:2]
    threading.Thread(target=srv.serve_forever, name="http", daemon=True).start()
    return srv, f"http://{host}:{port}/"


def main():
    srv = None
    stop = None
    if panel.port_open(WEB_PANEL_PORT):
        url = f"http://127.0.0.1:{WEB_PANEL_PORT}/"
    else:
        srv, url = serve()
        stop = panel.start_watchdog()
        panel.resume_effect_later()
        if not panel.port_open(panel.OPENRGB_PORT):
            panel.start_openrgb_task()
    webview.create_window(WINDOW_TITLE, url, width=1180, height=820, min_size=(760, 520),
                          background_color="#0f1115")
    try:
        webview.start(icon=str(panel.resource_dir() / "app.ico"))
    finally:
        if stop:
            stop.set()
        if srv:
            srv.shutdown()
            panel.ENGINE.stop()
        panel.reset_client()


if __name__ == "__main__":
    main()
