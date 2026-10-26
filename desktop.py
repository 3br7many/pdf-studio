#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Studio — desktop entry point.

This is what the packaged Windows application runs. It differs from app.py in
three ways that matter to someone using it as an installed program:

  * no console window — everything is logged to a file instead
  * the interface opens in its own frameless window, not a browser tab
  * a tray icon near the clock is the way to reopen or quit it

The web server still only listens on 127.0.0.1, on a port picked at startup,
so nothing is reachable from outside the machine.
"""

import os
import sys
import time
import socket
import shutil
import atexit
import ctypes
import logging
import tempfile
import threading
import subprocess
import webbrowser

APP_NAME = "PDF Studio"
STATE_DIR = os.path.join(
    os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "PDFStudio")
os.makedirs(STATE_DIR, exist_ok=True)
LOG_FILE = os.path.join(STATE_DIR, "pdfstudio.log")
LOCK_FILE = os.path.join(STATE_DIR, "running.port")
IS_WIN = os.name == "nt"


# ---------------------------------------------------------------------------
# A windowed build has no stdout. Anything that prints would raise, so the
# very first thing we do is give the process somewhere to write.
# ---------------------------------------------------------------------------
def redirect_output():
    try:
        stream = open(LOG_FILE, "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w")
    if sys.stdout is None or getattr(sys, "frozen", False):
        sys.stdout = stream
    if sys.stderr is None or getattr(sys, "frozen", False):
        sys.stderr = stream
    logging.basicConfig(stream=stream, level=logging.INFO,
                        format="%(asctime)s  %(levelname)s  %(message)s")
    return stream


redirect_output()
log = logging.getLogger("pdfstudio")


def fatal(title, message):
    """Show a real dialog — there is no console to print an error to."""
    log.error("%s: %s", title, message)
    if IS_WIN:
        try:
            ctypes.windll.user32.MessageBoxW(
                None, str(message), f"{APP_NAME} — {title}", 0x10)
        except Exception:
            pass
    sys.exit(1)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def already_running():
    """Return the port of a copy that is already up, if there is one."""
    try:
        with open(LOCK_FILE) as fh:
            port = int(fh.read().strip())
    except (OSError, ValueError):
        return None
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.6):
            return port
    except OSError:
        return None


def start_server(port):
    from werkzeug.serving import make_server

    # An applied update lives beside the installed application, not inside it.
    # Putting it first on the import path means the newer code is what runs,
    # while the libraries and fonts still come from the bundle.
    os.environ.setdefault(
        "PDFSTUDIO_HOME",
        getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))))
    try:
        import updater
        content = updater.active_content_dir()
        if content:
            sys.path.insert(0, content)
            log.info("running updated content from %s", content)
    except Exception as e:
        log.warning("could not check for applied updates (%s)", e)

    import app as backend

    server = make_server("127.0.0.1", port, backend.app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    log.info("server listening on 127.0.0.1:%s", port)
    return server


def wait_until_up(port, timeout=25):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
def find_browser():
    """Edge and Chrome can both run a page in a frameless window. Edge ships
    with Windows, so on a company machine it is essentially always there."""
    if not IS_WIN:
        for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge"):
            path = shutil.which(name)
            if path:
                return path
        return None
    candidates = []
    for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = os.environ.get(var)
        if not root:
            continue
        candidates += [
            os.path.join(root, "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(root, "Google", "Chrome", "Application", "chrome.exe"),
        ]
    return next((p for p in candidates if os.path.exists(p)), None)


def open_window(port):
    """Own window, own browser profile — so closing it closes this app only,
    and it never touches the user's normal browsing session."""
    url = f"http://127.0.0.1:{port}/"
    browser = find_browser()
    if not browser:
        log.warning("no Chromium-based browser found; using the default browser")
        webbrowser.open(url)
        return None
    profile = os.path.join(STATE_DIR, "window")
    os.makedirs(profile, exist_ok=True)
    cmd = [
        browser,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--window-size=1280,860",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=Translate,TranslateUI",
    ]
    try:
        flags = subprocess.CREATE_NO_WINDOW if IS_WIN else 0
        return subprocess.Popen(cmd, creationflags=flags) if IS_WIN \
            else subprocess.Popen(cmd)
    except Exception as e:
        log.warning("could not open the app window (%s); using the default browser", e)
        webbrowser.open(url)
        return None


# ---------------------------------------------------------------------------
# Tray icon
# ---------------------------------------------------------------------------
def tray_image():
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([6, 4, 52, 60], radius=7, fill=(255, 255, 255, 255),
                        outline=(70, 110, 220, 255), width=3)
    d.polygon([(52, 4), (52, 20), (36, 4)], fill=(220, 228, 245, 255))
    d.rectangle([16, 30, 44, 36], fill=(220, 60, 70, 255))
    d.rectangle([16, 42, 38, 48], fill=(70, 110, 220, 255))
    return img


def run_tray(port, on_quit):
    """Never let a tray problem take the application down with it — the app is
    perfectly usable without an icon, so every failure here is survivable."""
    try:
        import pystray

        def show(icon=None, item=None):
            open_window(port)

        def quit_app(icon=None, item=None):
            try:
                icon.stop()
            except Exception:
                pass
            on_quit()

        icon = pystray.Icon(
            "pdfstudio", tray_image(), APP_NAME,
            menu=pystray.Menu(
                pystray.MenuItem(f"Open {APP_NAME}", show, default=True),
                pystray.MenuItem("Quit", quit_app),
            ))
    except Exception as e:
        log.info("no tray icon (%s)", e)
        return None

    def spin():
        try:
            icon.run()
        except Exception as e:
            log.info("tray icon stopped (%s)", e)

    threading.Thread(target=spin, daemon=True).start()
    return icon


# ---------------------------------------------------------------------------
def main():
    running = already_running()
    if running:
        log.info("already running on port %s — opening a window for it", running)
        open_window(running)
        return

    port = free_port()
    try:
        server = start_server(port)
    except Exception as e:
        fatal("Could not start", f"The internal server failed to start.\n\n{e}\n\n"
                                 f"Details are in:\n{LOG_FILE}")
        return

    if not wait_until_up(port):
        fatal("Could not start",
              f"The internal server did not respond.\n\nDetails are in:\n{LOG_FILE}")
        return

    with open(LOCK_FILE, "w") as fh:
        fh.write(str(port))
    atexit.register(lambda: os.path.exists(LOCK_FILE) and os.remove(LOCK_FILE))

    stopping = threading.Event()

    def shutdown():
        if stopping.is_set():
            return
        stopping.set()
        log.info("shutting down")
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass
        os._exit(0)

    window = open_window(port)
    icon = run_tray(port, shutdown)

    try:
        import updater
        updater.check_in_background()      # the interface asks for the result
    except Exception:
        pass

    if window is None and icon is None:
        # Nothing to watch and no tray icon: keep serving until killed.
        while not stopping.is_set():
            time.sleep(1)
        return

    if window is not None and icon is None:
        window.wait()          # closing the window quits the app
        shutdown()
        return

    # With a tray icon present, the app outlives its window: closing the
    # window leaves it running quietly, and Quit in the tray ends it.
    while not stopping.is_set():
        time.sleep(0.5)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        log.exception("unhandled error")
        fatal("Unexpected error", f"{e}\n\nDetails are in:\n{LOG_FILE}")
