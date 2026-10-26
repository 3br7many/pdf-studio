#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Cut a signed release of PDF Studio.

    python release.py --init            once, to create the signing key
    python release.py 1.2.0 -m "..."    build and sign a release
    python release.py 1.2.0 -m "..." --publish     …and upload it to GitHub

Only the files that change between releases go into the package — the Python
code and the interface. Everyone running PDF Studio picks it up on their next
start, without reinstalling anything.

The signing key is the thing that keeps this safe. It is written once to your
own user folder, never into this project, and never uploaded. Anyone holding it
can push code to every machine running the application, so treat it the way you
would treat a password, and keep the backup it prints somewhere safe.
"""

import os
import re
import sys
import json
import shutil
import hashlib
import zipfile
import argparse
import subprocess
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dist", "release")
CONTENT = ["app.py", "editing.py", "templates/index.html"]

sys.path.insert(0, HERE)
import updater                                   # noqa: E402


def _reexec_in_venv():
    """Signing needs the cryptography library, which lives in the environment
    PDF Studio built for itself rather than in the system Python. Rather than
    making the user find the right interpreter, switch to it here."""
    try:
        import cryptography  # noqa: F401
        return
    except ImportError:
        pass
    venv = updater.state_dir()
    candidate = os.path.join(venv, "venv",
                             "Scripts" if os.name == "nt" else "bin",
                             "python.exe" if os.name == "nt" else "python")
    if os.path.exists(candidate) and os.path.realpath(candidate) != os.path.realpath(sys.executable):
        os.execv(candidate, [candidate, os.path.abspath(__file__)] + sys.argv[1:])
    die("The cryptography library is missing and PDF Studio's environment was\n"
        "not found. Run the tool once with run.py, then try again.")


_reexec_in_venv()

KEY_DIR = os.path.join(updater.state_dir(), "keys")
KEY_FILE = os.path.join(KEY_DIR, "release_private.key")


def die(message):
    print("\n" + message)
    if os.name == "nt":
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    sys.exit(1)


# ---------------------------------------------------------------------------
def init_key(force=False):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization

    if os.path.exists(KEY_FILE) and not force:
        die(f"A signing key already exists:\n  {KEY_FILE}\n\n"
            "Creating a new one would stop every copy already out there from\n"
            "accepting updates. Pass --force only if that is what you want.")

    os.makedirs(KEY_DIR, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption())
    with open(KEY_FILE, "wb") as fh:
        fh.write(raw)
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass

    write_public_key(private)

    print("=" * 68)
    print("  Signing key created")
    print("=" * 68)
    print(f"\n  Private key : {KEY_FILE}")
    print(f"  Public key  : written into updater.py\n")
    print("  Back the private key up somewhere safe and keep it off shared")
    print("  folders. Lose it and you cannot publish updates to the copies")
    print("  already installed; leak it and someone else can.\n")
    print("  Rebuild and redistribute the application once, so everyone has a")
    print("  copy that knows this key. After that, updates are automatic.\n")


def write_public_key(private):
    """Put the public half into updater.py. Also used to repair a project folder
    whose updater.py was overwritten by a fresh download — the key on disk is
    the source of truth, so the build never silently loses the ability to
    publish to copies already out there."""
    from cryptography.hazmat.primitives import serialization
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw).hex()
    path = os.path.join(HERE, "updater.py")
    source = open(path, encoding="utf-8").read()
    source = re.sub(r'^PUBLIC_KEY_HEX = ".*"$',
                    f'PUBLIC_KEY_HEX = "{public}"', source, count=1, flags=re.M)
    open(path, "w", encoding="utf-8").write(source)
    return public


def reseal():
    """Re-apply the existing key to updater.py."""
    if not os.path.exists(KEY_FILE):
        return False
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    private = Ed25519PrivateKey.from_private_bytes(open(KEY_FILE, "rb").read())
    write_public_key(private)
    return True


def load_key():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    if not os.path.exists(KEY_FILE):
        die("No signing key yet. Run this first:\n\n    python release.py --init")
    return Ed25519PrivateKey.from_private_bytes(open(KEY_FILE, "rb").read())


# ---------------------------------------------------------------------------
def set_version(version):
    path = os.path.join(HERE, "updater.py")
    source = open(path, encoding="utf-8").read()
    source = re.sub(r'^VERSION = ".*"$', f'VERSION = "{version}"',
                    source, count=1, flags=re.M)
    open(path, "w", encoding="utf-8").write(source)


def set_channel(url):
    path = os.path.join(HERE, "updater.py")
    source = open(path, encoding="utf-8").read()
    source = re.sub(r'^(\s*)"https://github\.com/[^"]*"',
                    lambda m: f'{m.group(1)}"{url}"', source, count=1, flags=re.M)
    open(path, "w", encoding="utf-8").write(source)


def build(version, notes, repo):
    os.makedirs(OUT, exist_ok=True)
    zip_path = os.path.join(OUT, "update.zip")
    meta_path = os.path.join(OUT, "update.json")

    missing = [f for f in CONTENT if not os.path.exists(os.path.join(HERE, f))]
    if missing:
        die("These files are missing: " + ", ".join(missing))

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for rel in CONTENT:
            z.write(os.path.join(HERE, rel), rel)
        z.writestr("version.json", json.dumps({"version": version, "notes": notes}))

    blob = open(zip_path, "rb").read()
    digest = hashlib.sha256(blob).hexdigest()
    signature = load_key().sign(f"{version}:{digest}".encode()).hex()

    url = (f"https://github.com/{repo}/releases/latest/download/update.zip"
           if repo else "REPLACE_WITH_THE_UPDATE_ZIP_URL")
    meta = {
        "version": version,
        "url": url,
        "sha256": digest,
        "signature": signature,
        "notes": notes,
        "date": datetime.date.today().isoformat(),
    }
    with open(meta_path, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2, ensure_ascii=False)
    return zip_path, meta_path, meta


def ensure_not_empty(gh, repo):
    """GitHub refuses to create a release in a repository that has no commits
    yet ("Repository is empty", HTTP 422). A freshly created repository with no
    README is exactly that, so put one commit in it first — through the API, so
    this works without git being installed or the repository being cloned."""
    if subprocess.call([gh, "api", f"repos/{repo}/commits", "--jq", ".[0].sha"],
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL) == 0:
        return True
    print("\n  The repository is empty — adding an initial commit first…")
    import base64
    body = ("# PDF Studio\n\n"
            "Update channel for PDF Studio. Releases here are downloaded and\n"
            "verified by the application itself; each one is signed, and a\n"
            "package that does not verify is discarded rather than run.\n")
    rc = subprocess.call(
        [gh, "api", f"repos/{repo}/contents/README.md", "-X", "PUT",
         "-f", "message=Initial commit",
         "-f", "content=" + base64.b64encode(body.encode()).decode()],
        stdout=subprocess.DEVNULL)
    if rc != 0:
        print("  Could not write the first commit. Add any file to the")
        print(f"  repository at https://github.com/{repo} and run this again.")
        return False
    return True


def publish(version, notes, repo, files):
    gh = shutil.which("gh")
    if not gh:
        print("\n  The GitHub CLI (gh) is not installed, so nothing was uploaded.")
        print("  Either install it from https://cli.github.com and run again with")
        print("  --publish, or create the release by hand and attach both files:")
        for f in files:
            print(f"    {f}")
        return False
    if not ensure_not_empty(gh, repo):
        return False
    tag = f"v{version}"
    subprocess.call([gh, "release", "delete", tag, "--yes", "--repo", repo],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rc = subprocess.call([gh, "release", "create", tag, *files,
                          "--repo", repo, "--title", f"PDF Studio {version}",
                          "--notes", notes or f"Version {version}"])
    if rc != 0:
        print("\n  Upload failed.")
        print("  If this is the first time, sign in once with:   gh auth login")
        print("  Then run this again — nothing was lost.")
        return False
    print(f"\n  Published: https://github.com/{repo}/releases/tag/{tag}")
    return True


def main():
    ap = argparse.ArgumentParser(description="Build and sign a PDF Studio release.")
    ap.add_argument("version", nargs="?", help="for example 1.2.0")
    ap.add_argument("-m", "--notes", default="", help="what changed, in one line")
    def _known_repo():
        try:
            return open(os.path.join(HERE, ".release-repo"), encoding="utf-8").read().strip()
        except OSError:
            return ""

    ap.add_argument("--repo", default=os.environ.get("PDFSTUDIO_REPO", "") or _known_repo(),
                    help="GitHub repository, as owner/name")
    ap.add_argument("--init", action="store_true", help="create the signing key")
    ap.add_argument("--force", action="store_true", help="with --init, replace the key")
    ap.add_argument("--publish", action="store_true", help="upload to GitHub Releases")
    ap.add_argument("--reseal", action="store_true",
                    help="re-apply the existing signing key to updater.py")
    args = ap.parse_args()

    if args.reseal:
        print("Signing key re-applied to updater.py."
              if reseal() else "No signing key found — run --init first.")
        return
    if args.init:
        init_key(args.force)
        return
    if not args.version and sys.stdin and sys.stdin.isatty():
        current = updater.VERSION
        parts = [int(x) for x in re.findall(r"\d+", current)] or [1, 0, 0]
        while len(parts) < 3:
            parts.append(0)
        parts[-1] += 1
        suggested = ".".join(str(p) for p in parts[:3])
        print("=" * 68)
        print(f"  Publishing an update. The version in this folder is {current}.")
        print("=" * 68)
        try:
            args.version = input(f"\n  New version [{suggested}]: ").strip() or suggested
            if not args.notes:
                args.notes = input("  What changed (one line): ").strip()
            if not args.publish:
                answer = input("  Upload it to GitHub now? [Y/n]: ").strip().lower()
                args.publish = answer in ("", "y", "yes")
        except (EOFError, KeyboardInterrupt):
            die("Cancelled.")
    if not args.version:
        ap.error("give a version number, for example:  python release.py 1.2.0")
    if not re.fullmatch(r"\d+(\.\d+){1,3}", args.version):
        ap.error("the version should look like 1.2.0")
    if not updater.is_newer(args.version, updater.VERSION):
        die(f"Version {args.version} is not newer than the current {updater.VERSION}.")

    repo = args.repo.strip()
    if args.publish and not repo:
        die("Publishing needs the repository name:\n"
            "    python release.py 1.2.0 --repo owner/name --publish")

    if repo:
        set_channel(f"https://github.com/{repo}/releases/latest/download/update.json")
    set_version(args.version)

    zip_path, meta_path, meta = build(args.version, args.notes, repo)
    size = os.path.getsize(zip_path) / 1024

    print("=" * 68)
    print(f"  PDF Studio {args.version}")
    print("=" * 68)
    print(f"\n  Package : {zip_path}  ({size:.0f} KB)")
    print(f"  Metadata: {meta_path}")
    print(f"  Checksum: {meta['sha256'][:16]}…")
    print(f"  Signed   ✓")

    if args.publish:
        publish(args.version, args.notes, repo, [zip_path, meta_path])
    else:
        print("\n  Not uploaded. Attach both files to a GitHub release, or run")
        print(f"  again with:  --repo {repo or 'owner/name'} --publish")

    print("\n  Everyone running PDF Studio will be offered this on their next start.")
    if os.name == "nt":
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass


if __name__ == "__main__":
    main()
