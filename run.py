#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PDF Studio launcher.

Creates an isolated Python environment (first run only), installs the
dependencies, then starts the app.

    python run.py

The environment is deliberately NOT created inside this folder. It holds
thousands of files, and this folder often lives in OneDrive / Dropbox / iCloud,
where a virtual environment would be synced to the cloud over and over. It goes
into the local application-data directory instead, so this folder stays small
and sync-safe wherever you keep it.
"""
import os
import sys
import hashlib
import subprocess
import venv

HERE = os.path.dirname(os.path.abspath(__file__))
REQ = os.path.join(HERE, "requirements.txt")
REQ_OPT = os.path.join(HERE, "requirements-optional.txt")
IS_WIN = os.name == "nt"


def env_root():
    """A per-user location outside any cloud-synced folder."""
    override = os.environ.get("PDFSTUDIO_VENV")
    if override:
        return override
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "PDFStudio", "venv")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/PDFStudio/venv")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "pdfstudio", "venv")


VENV = env_root()
STAMP = os.path.join(VENV, ".deps")


def venv_python():
    return os.path.join(VENV, "Scripts", "python.exe") if IS_WIN \
        else os.path.join(VENV, "bin", "python")


def req_hash():
    h = hashlib.sha256()
    for path in (REQ, REQ_OPT):
        try:
            with open(path, "rb") as fh:
                h.update(fh.read())
        except OSError:
            h.update(b"missing")
    return h.hexdigest()


def stop(message, code=1):
    print("\n" + message)
    if IS_WIN:
        # Keep the console open when the script was started by double-clicking.
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    sys.exit(code)


def main():
    if sys.version_info < (3, 9):
        stop(f"Python 3.9 or newer is required. This is {sys.version.split()[0]}.")

    if not os.path.exists(REQ):
        stop(f"requirements.txt is missing from:\n  {HERE}\n"
             "Extract the whole folder from the zip, then run this again.")

    py = venv_python()
    if not os.path.exists(py):
        print(f"Creating an isolated Python environment (first run only):\n  {VENV}\n")
        try:
            os.makedirs(os.path.dirname(VENV), exist_ok=True)
            venv.EnvBuilder(with_pip=True, clear=False).create(VENV)
        except Exception as e:
            stop(f"Could not create the environment: {e}\n"
                 "On Debian/Ubuntu you may need:  sudo apt install python3-venv")
        py = venv_python()

    want = req_hash()
    have = ""
    if os.path.exists(STAMP):
        try:
            with open(STAMP) as fh:
                have = fh.read().strip()
        except OSError:
            pass

    if have != want:
        print("Installing the required libraries. The first run takes 1-3 minutes.\n")
        subprocess.call([py, "-m", "pip", "install", "--upgrade", "pip", "-q"])
        rc = subprocess.call([py, "-m", "pip", "install", "-r", REQ])
        if rc != 0:
            stop("Some required libraries failed to install.\n"
                 "This usually means one of them has no wheel yet for Python "
                 f"{sys.version_info.major}.{sys.version_info.minor}.\n"
                 "Installing Python 3.12 or 3.13 alongside it and running this "
                 "script with that version fixes it.\n\n"
                 "To see the full error, run:\n"
                 f'  "{py}" -m pip install -r "{REQ}"')

        # Optional extras: nice to have, never fatal.
        if os.path.exists(REQ_OPT):
            print("\nInstalling optional extras (layout-preserving Word export)…\n")
            if subprocess.call([py, "-m", "pip", "install", "-r", REQ_OPT]) != 0:
                print("\n  Note: the optional extras did not install. Everything still\n"
                      "  works — Word export falls back to text mode, which is what\n"
                      "  Arabic documents use anyway.\n")

        with open(STAMP, "w") as fh:
            fh.write(want)
        print("\nInstalled.\n")

    app = os.path.join(HERE, "app.py")
    try:
        sys.path.insert(0, HERE)
        import updater
        content = updater.active_content_dir()
        if content and os.path.exists(os.path.join(content, "app.py")):
            app = os.path.join(content, "app.py")
            print(f"Running update {updater.current_version()} from {content}\n")
    except Exception:
        pass
    if not os.path.exists(app):
        stop(f"app.py is missing from:\n  {HERE}")

    # The updated app.py still imports updater.py and reads fonts from the
    # installed folder, so both have to stay reachable from the subprocess.
    env = dict(os.environ, PDFSTUDIO_HOME=HERE)
    env["PYTHONPATH"] = os.pathsep.join(
        [HERE] + ([env["PYTHONPATH"]] if env.get("PYTHONPATH") else []))
    try:
        rc = subprocess.call([py, app], env=env)
    except KeyboardInterrupt:
        rc = 0
    if rc not in (0, None):
        stop(f"PDF Studio exited with code {rc}. The message above says why.", rc)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as e:
        stop(f"Unexpected error: {e}")
