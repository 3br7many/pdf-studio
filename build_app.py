#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Build PDF Studio into a standalone application.

Run this ONCE on a Windows machine that has Python installed:

    python build_app.py

It produces, in dist/:

    PDF Studio/              a self-contained folder — no Python needed
    PDFStudio-portable.zip   the same folder zipped, ready to hand out
    PDFStudio-Setup.exe      only if Inno Setup is installed (optional)

Everyone you give it to just runs it. They need no Python, no libraries and
no internet connection.
"""

import os
import re
import sys
import glob
import time
import shutil
import zipfile
import platform
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(HERE, "build")
DIST = os.path.join(HERE, "dist")
VENV = os.path.join(BUILD, "buildenv")
ICON = os.path.join(BUILD, "pdfstudio.ico")
APP_NAME = "PDF Studio"
IS_WIN = os.name == "nt"

# The layout-preserving Word converter pulls in OpenCV, which adds roughly
# 120 MB to the finished application. Word export still works without it —
# it falls back to text mode, which is what Arabic documents use anyway.
INCLUDE_LAYOUT_WORD = "--with-layout-word" in sys.argv


LOG_PATH = os.path.join(BUILD, "build.log")


class Tee:
    """Everything printed here also lands in build/build.log, so a failure
    can be read afterwards instead of vanishing when the window closes."""

    def __init__(self, *streams):
        self.streams = [s for s in streams if s]

    def write(self, text):
        for s in self.streams:
            try:
                s.write(text)
                s.flush()
            except Exception:
                pass
        return len(text)

    def flush(self):
        for s in self.streams:
            try:
                s.flush()
            except Exception:
                pass


os.makedirs(BUILD, exist_ok=True)
try:
    _logfile = open(LOG_PATH, "w", encoding="utf-8", errors="replace")
    sys.stdout = Tee(sys.__stdout__, _logfile)
    sys.stderr = sys.stdout
except OSError:
    _logfile = None


class BuildError(Exception):
    pass


def run(cmd, **kw):
    """Run a command, echoing its output to the console and the log."""
    print("  $", " ".join(str(c) for c in cmd[:6]), "…" if len(cmd) > 6 else "")
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True,
                                errors="replace", bufsize=1, **kw)
    except OSError as e:
        print(f"  could not start: {e}")
        return 1
    for line in proc.stdout:
        print("  " + line.rstrip())
    return proc.wait()


def must(cmd, what, **kw):
    if run(cmd, **kw) != 0:
        raise BuildError(what)


def python_in(venv):
    return os.path.join(venv, "Scripts", "python.exe") if IS_WIN \
        else os.path.join(venv, "bin", "python")


def pick_venv():
    """Reuse the environment run.py already built, when there is one. It
    holds every library this build needs, so reusing it turns a few hundred
    megabytes of downloading into almost none."""
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        runtime = os.path.join(base, "PDFStudio", "venv")
    elif sys.platform == "darwin":
        runtime = os.path.expanduser("~/Library/Application Support/PDFStudio/venv")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        runtime = os.path.join(base, "pdfstudio", "venv")
    if os.path.exists(python_in(runtime)) and "--fresh-env" not in sys.argv:
        return runtime, True
    return VENV, False


def venv_python():
    return python_in(pick_venv()[0])


def step(n, text):
    print(f"\n[{n}] {text}")


def make_icon(py):
    """Draw the application icon rather than shipping a binary blob."""
    script = os.path.join(BUILD, "_icon.py")
    with open(script, "w", encoding="utf-8") as fh:
        fh.write(f'''
from PIL import Image, ImageDraw
sizes = [16, 24, 32, 48, 64, 128, 256]
base = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
d = ImageDraw.Draw(base)
d.rounded_rectangle([28, 16, 214, 240], radius=26, fill=(255, 255, 255, 255),
                    outline=(79, 140, 255, 255), width=11)
d.polygon([(214, 16), (214, 76), (152, 16)], fill=(214, 226, 248, 255))
d.rectangle([64, 120, 178, 144], fill=(214, 60, 70, 255))
d.rectangle([64, 166, 150, 190], fill=(79, 140, 255, 255))
base.save(r"{ICON}", sizes=[(s, s) for s in sizes])
print("icon written")
''')
    must([py, script], "drawing the icon")


def ask(prompt, default=""):
    try:
        answer = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return default
    return answer or default


def ensure_release_setup(py):
    """Set up signed updates before the first build, so every copy that goes out
    already knows how to update itself. Skipping this is allowed — it just means
    the update check stays switched off in the finished application."""
    sys.path.insert(0, HERE)
    try:
        import updater
        import importlib
        importlib.reload(updater)
    except Exception as e:
        print(f"  could not load updater.py ({e}) — updates will be off")
        return

    key_file = os.path.join(updater.state_dir(), "keys", "release_private.key")
    have_key = os.path.exists(key_file)
    configured = bool(updater.PUBLIC_KEY_HEX) and "OWNER/REPO" not in updater.UPDATE_URL

    if have_key and configured:
        print(f"  already set up — releases are signed with:\n  {key_file}")
        return

    print("\n  Automatic updates are not set up yet.")
    print("  With them, changing something later means publishing a 35 KB file")
    print("  instead of sending everyone a new 100 MB download.\n")
    known = ""
    try:
        known = open(os.path.join(HERE, ".release-repo"), encoding="utf-8").read().strip()
    except OSError:
        pass
    if known:
        print(f"  Publishing to: https://github.com/{known}")
        repo = known
    else:
        repo = ask("  GitHub repository for updates as owner/name\n"
                   "  (or press Enter to skip and build without updates): ")
    if not repo:
        print("\n  Skipped. The application will be built with updates switched off.")
        return
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        print(f"\n  '{repo}' doesn't look like owner/name — skipping update setup.")
        return

    if not have_key:
        print("\n  Creating your signing key…")
        if run([py, os.path.join(HERE, "release.py"), "--init"]) != 0:
            print("  Key creation failed — building without updates.")
            return
    elif not updater.PUBLIC_KEY_HEX:
        # The key survived but updater.py came from a fresh download.
        print("\n  Re-applying your existing signing key…")
        run([py, os.path.join(HERE, "release.py"), "--reseal"])

    # Point the channel at the repository.
    path = os.path.join(HERE, "updater.py")
    source = open(path, encoding="utf-8").read()
    source = re.sub(
        r'"https://github\.com/[^"]*/releases/latest/download/update\.json"',
        f'"https://github.com/{repo}/releases/latest/download/update.json"',
        source, count=1)
    open(path, "w", encoding="utf-8").write(source)

    with open(os.path.join(HERE, ".release-repo"), "w", encoding="utf-8") as fh:
        fh.write(repo)

    print(f"\n  Updates will be published to: https://github.com/{repo}/releases")
    print(f"  Signing key: {key_file}")
    print("  Keep that file safe and off shared folders — it is what proves a")
    print("  release came from you.\n")


def main():
    # Work from the project folder no matter where this was launched from.
    # PyInstaller flatly refuses to run with System32 as the current
    # directory, which is exactly what you get from some terminal windows.
    try:
        os.chdir(HERE)
    except OSError:
        pass

    print("=" * 64)
    print(f"  Building {APP_NAME}")
    print(f"  Platform: {platform.system()} {platform.machine()}")
    print(f"  Python:   {sys.version.split()[0]}")
    print("=" * 64)

    if not IS_WIN:
        print("\n  NOTE: this is not Windows. The build will still run, but it\n"
              "  produces an application for THIS platform. A Windows .exe has\n"
              "  to be built on Windows — PyInstaller cannot cross-compile.\n")

    for path in (BUILD, DIST):
        os.makedirs(path, exist_ok=True)

    step(1, "Preparing a build environment")
    target, reused = pick_venv()
    if reused:
        print(f"  reusing the environment PDF Studio already installed:\n  {target}")
        print("  (pass --fresh-env to build in a clean one instead)")
    else:
        print(f"  creating {target}")
        if not os.path.exists(python_in(target)):
            import venv as venv_mod
            venv_mod.EnvBuilder(with_pip=True, clear=False).create(target)
    py = python_in(target)

    step(2, "Installing the libraries to bundle")
    must([py, "-m", "pip", "install", "--upgrade", "pip", "-q"], "upgrading pip")
    must([py, "-m", "pip", "install", "-q", "-r",
          os.path.join(HERE, "requirements.txt")], "installing requirements")
    must([py, "-m", "pip", "install", "-q", "pyinstaller>=6.0", "pystray>=0.19"],
         "installing the packaging tools")
    if INCLUDE_LAYOUT_WORD:
        print("  including the layout-preserving Word converter (larger build)")
        must([py, "-m", "pip", "install", "-q", "-r",
              os.path.join(HERE, "requirements-optional.txt")], "installing extras")

    step(3, "Setting up signed updates")
    ensure_release_setup(py)

    step(4, "Drawing the application icon")
    make_icon(py)

    step(5, "Packaging (this takes a few minutes)")
    sep = ";" if IS_WIN else ":"
    cmd = [
        py, "-m", "PyInstaller",
        "--noconfirm", "--clean",
        "--name", APP_NAME,
        "--windowed",                      # no console window
        "--icon", ICON,
        "--distpath", DIST,
        "--workpath", os.path.join(BUILD, "work"),
        "--specpath", BUILD,
        "--add-data", f"{os.path.join(HERE, 'templates')}{sep}templates",
        "--add-data", f"{os.path.join(HERE, 'fonts')}{sep}fonts",
        "--hidden-import", "app",
        "--paths", HERE,
    ]
    # Packages that carry data files or load submodules dynamically. Missing
    # any of these shows up only at runtime, so collect them wholesale.
    for pkg in ("reportlab", "arabic_reshaper", "bidi", "pikepdf", "pymupdf",
                "pdfplumber", "pdfminer", "docx", "openpyxl", "pypdf", "pystray"):
        cmd += ["--collect-all", pkg]
    excluded = ["PIL._tkinter_finder", "tkinter", "matplotlib", "pytest", "IPython"]
    if not INCLUDE_LAYOUT_WORD:
        # app.py imports pdf2docx inside a try/except, so PyInstaller would
        # bundle it — and OpenCV with it — whenever it happens to be present
        # in the environment being reused. Excluding it keeps the size of the
        # finished application the same no matter where it was built.
        excluded += ["pdf2docx", "cv2", "fire", "numpy", "numpy.f2py", "scipy", "pandas"]
    for mod in excluded:
        cmd += ["--exclude-module", mod]
    cmd.append(os.path.join(HERE, "desktop.py"))
    must(cmd, "packaging with PyInstaller", cwd=HERE)

    out_dir = os.path.join(DIST, APP_NAME)
    if not os.path.isdir(out_dir):
        raise BuildError(f"packaging produced no output at {out_dir}")

    step(6, "Trimming development leftovers")
    freed = 0
    for root, dirs, files in os.walk(out_dir, topdown=True):
        for d in list(dirs):
            if d in ("mupdf-devel", "__pycache__", "tests", "testing", "include"):
                path = os.path.join(root, d)
                freed += sum(os.path.getsize(os.path.join(r, f))
                             for r, _x, fs in os.walk(path) for f in fs)
                shutil.rmtree(path, ignore_errors=True)
                dirs.remove(d)
        for f in files:
            if f.endswith((".h", ".hpp", ".pyi", ".pyx", ".c", ".pdb")):
                path = os.path.join(root, f)
                try:
                    freed += os.path.getsize(path)
                    os.remove(path)
                except OSError:
                    pass
    print(f"  removed {freed / 1024 / 1024:.0f} MB of headers and test data")

    step(7, "Adding the user-facing readme")
    with open(os.path.join(out_dir, "READ ME FIRST.txt"), "w", encoding="utf-8") as fh:
        fh.write(READ_ME)

    step(8, "Zipping for distribution")
    zip_path = os.path.join(DIST, "PDFStudio-portable.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _dirs, files in os.walk(out_dir):
            for name in files:
                full = os.path.join(root, name)
                z.write(full, os.path.join(APP_NAME, os.path.relpath(full, out_dir)))

    step(9, "Building an installer (optional)")
    iss = os.path.join(HERE, "installer.iss")
    iscc = shutil.which("iscc") or next(
        (p for p in glob.glob(r"C:\Program Files*\Inno Setup*\ISCC.exe")), None)
    if IS_WIN and iscc and os.path.exists(iss):
        run([iscc, f"/DAppDir={out_dir}", f"/DOutDir={DIST}",
             f"/DIconFile={ICON}", iss])
    else:
        print("  skipped — Inno Setup is not installed.")
        print("  The portable zip above is a complete, working distribution.")
        print("  For a Setup.exe, install Inno Setup (jrsoftware.org/isdl.php)")
        print("  and run this script again.")

    size = sum(os.path.getsize(os.path.join(r, f))
               for r, _d, fs in os.walk(out_dir) for f in fs) / 1024 / 1024
    print("\n" + "=" * 64)
    print("  Done.")
    print(f"  Application : {out_dir}   ({size:.0f} MB)")
    print(f"  Portable zip: {zip_path}")
    for setup in glob.glob(os.path.join(DIST, "*Setup*.exe")):
        print(f"  Installer   : {setup}")
    print("=" * 64)

    repo = ""
    try:
        repo = open(os.path.join(HERE, ".release-repo"), encoding="utf-8").read().strip()
    except OSError:
        pass
    print("\n  NEXT")
    print("  1. Send PDFStudio-portable.zip to your colleagues. They extract it")
    print("     anywhere and run PDF Studio.exe — nothing else to install.")
    if repo:
        print(f"  2. The update channel points at https://github.com/{repo}")
        print("     It has to stay PUBLIC: release files in a private repository")
        print("     need a token to download, and a token shipped inside the app")
        print("     would be readable by anyone who has the app.")
        print("  3. From then on, to ship a change:")
        print(f"        python release.py 1.1.0 -m \"what changed\" --repo {repo} --publish")
        print("     Everyone is offered it the next time they open the app.")
        print("     That step needs the GitHub CLI: https://cli.github.com")
    else:
        print("  2. Updates are off in this build. To turn them on later, delete")
        print("     the build folder and run this script again.")


READ_ME = """PDF Studio
==========

Double-click "PDF Studio.exe" to start.

The application opens in its own window. There is no console window to leave
open, and an icon appears near the clock: right-click it to reopen the window
or to quit.

Every file you open is processed on this computer only. The application runs a
small server on 127.0.0.1 (this machine, reachable by nothing else) and no file
is ever uploaded anywhere. It works with no internet connection.

Arabic is fully supported, both for text written onto a PDF (watermarks,
signatures, form values) and for text pulled out of one. Arabic PDFs often
store their text in a reversed, disconnected form; the "Letter order repair"
option on the Extract tab puts it back the way it should read.

The first time Windows sees this application it may show a blue
"Windows protected your PC" notice, because the file is not signed by a
certificate Microsoft recognises. Click "More info", then "Run anyway".
Ask your IT team if you are unsure.

Files you upload are kept in a temporary folder until you delete them or the
machine restarts. Download anything you want to keep.
"""


if __name__ == "__main__":
    start = time.time()
    code = 0
    try:
        main()
    except BuildError as e:
        print("\n" + "=" * 64)
        print("  BUILD FAILED")
        print("=" * 64)
        print(f"\n  Step: {e}")
        print("  The reason is in the output above.")
        code = 1
    except KeyboardInterrupt:
        print("\nCancelled.")
        code = 1
    except Exception:
        import traceback
        print("\n" + "=" * 64)
        print("  BUILD FAILED — unexpected error")
        print("=" * 64)
        traceback.print_exc()
        code = 1

    print(f"\n({time.time() - start:.0f} seconds)")
    print(f"Full log: {LOG_PATH}")
    try:
        if _logfile:
            _logfile.flush()
    except Exception:
        pass
    if IS_WIN:
        # Without this the window vanishes and takes the error with it.
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    sys.exit(code)
