#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Self-updating, without turning the application into a way in.

Only the parts that actually change between releases are downloaded — the
Python files and the interface, about 80 KB — rather than the 140 MB of
libraries that stay the same. Nothing in the installed folder is touched: the
update is unpacked beside it in the user's own application-data folder and
loaded from there on the next start, which is also why antivirus software has
no reason to object.

The part that matters most is the signature. An application that downloads code
and runs it is a back door unless it can prove where the code came from. Every
release is signed with a private key that never leaves the machine that builds
it, and the public half is compiled into this file. A package whose signature
does not verify is deleted, not run — so being able to change the file on the
server is not enough to reach anybody's laptop.
"""

import io
import os
import re
import sys
import json
import shutil
import hashlib
import zipfile
import tempfile
import threading
import urllib.error
import urllib.request

VERSION = "1.1.0"

# Where releases are published. `latest/download/<file>` always resolves to the
# newest release, so this URL never has to change.
UPDATE_URL = os.environ.get(
    "PDFSTUDIO_UPDATE_URL",
    "https://github.com/3br7many/pdf-studio/releases/latest/download/update.json")

# Ed25519 public key, hex. `release.py --init` writes the matching line here.
PUBLIC_KEY_HEX = "55a2fde00e7b15b6990a707fd9ffb2ab4ba1c990da0e6bbe9b696c2b272c60fa"

# Only these may appear in a package. Anything else is a red flag.
ALLOWED = {"app.py", "editing.py", "updater.py", "version.json",
           "templates/index.html"}

USER_AGENT = f"PDFStudio/{VERSION}"
TIMEOUT = 20


# ---------------------------------------------------------------------------
def state_dir():
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(base, "PDFStudio")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/PDFStudio")
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "pdfstudio")


UPDATE_ROOT = os.path.join(state_dir(), "updates")
POINTER = os.path.join(UPDATE_ROOT, "active.json")


def parse_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:4]) or (0,)


def is_newer(candidate, current):
    return parse_version(candidate) > parse_version(current)


def current_version():
    """The running version — an applied update reports its own."""
    active = active_content_dir()
    if active:
        try:
            with open(os.path.join(active, "version.json")) as fh:
                return json.load(fh).get("version", VERSION)
        except Exception:
            pass
    return VERSION


def active_content_dir():
    """The folder to load code and templates from, or None for the bundled copy."""
    try:
        with open(POINTER) as fh:
            path = json.load(fh).get("path")
    except Exception:
        return None
    if path and os.path.isdir(path) and os.path.exists(os.path.join(path, "app.py")):
        return path
    return None


def clear_active():
    """Fall back to the version that shipped with the application."""
    try:
        os.remove(POINTER)
    except OSError:
        pass


# ---------------------------------------------------------------------------
def verify_signature(payload: bytes, signature_hex: str):
    if not PUBLIC_KEY_HEX:
        return False, "this build has no update key, so updates are disabled"
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(PUBLIC_KEY_HEX))
        key.verify(bytes.fromhex(signature_hex), payload)
        return True, ""
    except Exception as e:
        return False, f"signature check failed ({type(e).__name__})"


def fetch(url, limit=25 * 1024 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("the file at that address is unexpectedly large")
    return data


def check():
    """Ask the release channel what the newest version is."""
    if not PUBLIC_KEY_HEX:
        return {"ok": False, "error": "updates are not configured in this build"}
    try:
        meta = json.loads(fetch(UPDATE_URL, 256 * 1024).decode("utf-8"))
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"could not reach the update server ({e.reason})"}
    except Exception as e:
        return {"ok": False, "error": f"could not read the update information ({e})"}

    latest = str(meta.get("version", ""))
    now = current_version()
    return {
        "ok": True,
        "current": now,
        "latest": latest,
        "available": bool(latest) and is_newer(latest, now),
        "notes": meta.get("notes", ""),
        "date": meta.get("date", ""),
        "_meta": meta,
    }


def safe_extract(data: bytes, target: str):
    """Unpack only the expected files, and never outside the target folder."""
    os.makedirs(target, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = z.namelist()
        for name in names:
            norm = name.replace("\\", "/")
            if norm.endswith("/"):
                continue
            if norm not in ALLOWED:
                raise ValueError(f"the package contains an unexpected file: {name}")
            dest = os.path.realpath(os.path.join(target, norm))
            if not dest.startswith(os.path.realpath(target) + os.sep):
                raise ValueError("the package tried to write outside its folder")
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with z.open(name) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
    if not os.path.exists(os.path.join(target, "app.py")):
        raise ValueError("the package has no app.py")


def apply(meta=None):
    """Download, verify and stage an update. It takes effect on the next start."""
    if meta is None:
        info = check()
        if not info.get("ok"):
            return info
        if not info.get("available"):
            return {"ok": False, "error": "already up to date"}
        meta = info["_meta"]

    version = str(meta.get("version", ""))
    url = meta.get("url") or ""
    digest = str(meta.get("sha256", "")).lower()
    signature = str(meta.get("signature", ""))
    if not (version and url and digest and signature):
        return {"ok": False, "error": "the update information is incomplete"}
    if not is_newer(version, current_version()):
        return {"ok": False, "error": "already up to date"}

    try:
        blob = fetch(url)
    except Exception as e:
        return {"ok": False, "error": f"download failed ({e})"}

    actual = hashlib.sha256(blob).hexdigest()
    if actual != digest:
        return {"ok": False, "error": "the download did not match its checksum"}

    # The signature covers the checksum and the version together, so neither the
    # package nor the version it claims to be can be swapped independently.
    signed = f"{version}:{digest}".encode()
    good, why = verify_signature(signed, signature)
    if not good:
        return {"ok": False, "error": f"this update is not signed by us — {why}"}

    target = os.path.join(UPDATE_ROOT, version)
    staging = target + ".part"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        safe_extract(blob, staging)
        with open(os.path.join(staging, "version.json"), "w") as fh:
            json.dump({"version": version, "notes": meta.get("notes", "")}, fh)
        shutil.rmtree(target, ignore_errors=True)
        os.replace(staging, target)
        os.makedirs(UPDATE_ROOT, exist_ok=True)
        with open(POINTER, "w") as fh:
            json.dump({"path": target, "version": version}, fh)
    except Exception as e:
        shutil.rmtree(staging, ignore_errors=True)
        return {"ok": False, "error": f"could not install the update ({e})"}

    prune(keep=version)
    return {"ok": True, "version": version,
            "note": f"Version {version} installed. Restart PDF Studio to use it."}


def prune(keep=None, limit=2):
    """Keep the newest couple of updates so a bad one can be rolled back."""
    try:
        versions = sorted((d for d in os.listdir(UPDATE_ROOT)
                           if os.path.isdir(os.path.join(UPDATE_ROOT, d))),
                          key=parse_version, reverse=True)
    except OSError:
        return
    for old in versions[limit:]:
        if old != keep:
            shutil.rmtree(os.path.join(UPDATE_ROOT, old), ignore_errors=True)


def rollback():
    """Drop the applied update and go back to the bundled version."""
    active = active_content_dir()
    clear_active()
    if active:
        shutil.rmtree(active, ignore_errors=True)
    return {"ok": True, "note": f"Reverted to the built-in version {VERSION}."}


# ---------------------------------------------------------------------------
_cache = {"result": None}


def check_in_background(callback=None):
    def run():
        try:
            _cache["result"] = check()
        except Exception as e:
            _cache["result"] = {"ok": False, "error": str(e)}
        if callback:
            try:
                callback(_cache["result"])
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


def cached():
    return _cache["result"]
