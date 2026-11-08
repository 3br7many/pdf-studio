# PDF Studio — local PDF toolkit

A complete PDF editor that runs entirely on your own machine through a local web
interface. Nothing is uploaded anywhere: the server binds to `127.0.0.1` only, so
not even other devices on your network can reach it.

Built with full Arabic support — see [Arabic support](#arabic-support) below.

---

## Running it

**Windows** — double-click **`run.py`**

Use `run.py`, not `start.bat`. Windows Smart App Control blocks `.bat` files that
came from the internet, but a `.py` file opens with the signed Python launcher and
runs normally. `start.bat` is kept for machines without Smart App Control.

**macOS / Linux**
```bash
chmod +x start.sh     # first time only
./start.sh
```

**Any platform**
```bash
python run.py
```

The first run takes 1–3 minutes to install the libraries. After that it starts in
seconds and opens your browser at `http://127.0.0.1:8765`. Press `Ctrl+C` in the
console window, or just close it, to stop.

The only requirement is **Python 3.9 or newer**. If it isn't installed, get it from
<https://www.python.org/downloads/> — and on Windows make sure to tick
**Add Python to PATH** during installation.

### Where the Python environment lives

Not in this folder. It holds thousands of files, and this folder often sits in
OneDrive, Dropbox or iCloud, where that would be uploaded and re-synced endlessly.
It goes here instead, so you can keep the tool anywhere, cloud folders included:

| | |
|---|---|
| Windows | `%LOCALAPPDATA%\PDFStudio\venv` |
| macOS | `~/Library/Application Support/PDFStudio/venv` |
| Linux | `~/.local/share/pdfstudio/venv` |

Set `PDFSTUDIO_VENV` to override the location. Deleting that folder is harmless —
the next run rebuilds it. The environment is also rebuilt automatically whenever
`requirements.txt` changes.

One dependency, `pdf2docx`, is installed separately as an optional extra, because
it pulls in OpenCV which is sometimes slow to publish wheels for a brand-new Python
release. If it fails, the install still succeeds and Word export falls back to text
mode — which is what Arabic documents use in any case.

---

## Deploying to other machines

For colleagues, don't hand out this folder — build the standalone application
instead. It needs no Python, no libraries and no internet connection, opens in
its own window with no console, and puts an icon near the clock.

**Build it once**, on any Windows machine that has Python:

```
python build_app.py
```

Roughly five minutes. It produces, in `dist/`:

| | |
|---|---|
| `PDF Studio\` | the finished application — a folder, ~180 MB |
| `PDFStudio-portable.zip` | the same thing zipped, ~100 MB — what you send people |
| `PDFStudio-Setup.exe` | only if Inno Setup is installed (see below) |

The build must run on Windows to produce a Windows application — PyInstaller
cannot cross-compile. Running the script on macOS or Linux builds for that
platform instead.

**Two ways to distribute:**

*Portable* — send the zip. They extract it anywhere and run `PDF Studio.exe`.
No installation, no administrator rights. Good for laptops you don't manage.

*Installer* — install [Inno Setup](https://jrsoftware.org/isdl.php) and run
`build_app.py` again; it picks it up automatically and produces
`PDFStudio-Setup.exe`. This installs per-user (no admin rights), adds Start
Menu and desktop shortcuts, and registers a proper uninstaller. Adjust the
publisher name and version in `installer.iss`.

**About the Windows warning.** The application is not signed by a certificate
Microsoft recognises, so the first run may show *"Windows protected your PC"* —
the user clicks **More info** → **Run anyway**. Three ways around it:

- Distribute over the company network or a USB drive rather than by download or
  email. Files that never carry an internet mark-of-the-web usually don't
  trigger the warning at all
- Sign the application with a code-signing certificate if your company has one:
  `signtool sign /fd SHA256 /tr <timestamp-url> "dist\PDF Studio\PDF Studio.exe"`
  before zipping, and sign the Setup.exe too
- Deploy through Intune, SCCM or Group Policy, which bypasses the prompt

**Size.** Most of it is the PDF engine (MuPDF) and the imaging libraries; there
is no way to make that much smaller. The layout-preserving Word converter is
left out by default because it adds about 120 MB for a feature Arabic documents
don't use. Include it with:

```
python build_app.py --with-layout-word
```

---

## Updating everyone, after the first rollout

Once people have the application, they don't need a new copy every time
something changes. PDF Studio checks for updates when it starts and offers them
in a bar at the top of the window; one click installs and it takes effect on the
next start.

Only the parts that actually change are downloaded — the Python code and the
interface, about **35 KB** — not the 140 MB of libraries. Nothing in the
installed folder is modified: the update is unpacked into the user's own
application-data folder and loaded from there. That is also why antivirus
software has no reason to complain, unlike an application that rewrites its own
executable.

### Set it up once

```
python release.py --init
```

This creates an Ed25519 signing key in your user folder and writes the matching
public key into `updater.py`. **Then build and distribute the application once
more**, so every copy carries the public key. From that point on, updates are
automatic.

The private key is what makes this safe, and what makes it dangerous if
mishandled. Anyone holding it can push code to every machine running the
application. Keep it off shared drives, keep a backup somewhere safe, and don't
commit it. Until `--init` has been run, updates are simply switched off — a
build with no key refuses every package.

### Publish a release

```
python release.py 1.1.0 -m "What changed" --repo owner/name --publish
```

That packages the changed files, signs them, and uploads `update.zip` and
`update.json` to a GitHub release. **The repository has to be public** —
release assets in a private repository need an access token to download, and a
token shipped inside the application would be readable by anyone who has the
application. What gets published is the tool's own source, which everyone
receiving it already has a copy of; the signing key is what keeps releases
trustworthy, not the repository being hidden. Without `--publish` it just writes both files
to `dist/release/` for you to attach by hand. `gh` (the GitHub CLI) does the
upload; if it isn't installed the script says so and prints the two paths.

The channel URL points at `releases/latest/download/…`, so it always resolves to
your newest release and never needs changing.

### What stops a bad package

Each release is signed over its version and checksum together. On the receiving
end, a package is rejected unless the download matches its checksum, the
signature verifies against the built-in public key, the version is actually
newer, and the archive contains nothing but the expected files. Anything else is
deleted rather than run — so being able to change the file on the server is not
enough to reach anyone's laptop.

If an update ever misbehaves, the previous one is kept, and
`POST /api/update/rollback` returns to the version that shipped inside the
application.

### When a full rebuild is still needed

Adding or upgrading a Python library changes what is bundled, which the small
update cannot carry. In that case rebuild with `build_app.py` and redistribute
as before. In practice that is rare — most changes are code and interface.

---

## What it does

| Tab | What it does |
|---|---|
| **Files** | Drag-and-drop upload for PDFs and images, plus a library of everything in the session including results |
| **Merge** | Combine several PDFs in an order you choose by clicking them |
| **Organize pages** | Page thumbnails you can delete, rotate, and reorder by dragging |
| **Split** | One file per page · every N pages · custom ranges · extract a range into a single file |
| **Extract & convert** | Text (TXT) · text with column layout · convert to Word · tables to Excel · embedded images · pages as PNG |
| **OCR** | Turn a scan into searchable text (needs Tesseract installed) |
| **Compress** | Three levels; medium and strong downsample images and subset fonts |
| **Security** | AES-256 encryption with per-action permissions, and password removal |
| **Watermark** | Text or a logo, with adjustable opacity, angle and size, tiled or single, above or behind the content |
| **Edit page** | Drag a box over anything and erase it, retype it, or drop an image in its place — plus find-and-replace, and a list of the page's images |
| **Sign & stamp** | Place a signature or stamp image by clicking on a page preview, plus free text |
| **Fill forms** | Reads the form fields automatically and fills them, with optional flattening |

Every result comes with a **Download** button and a **Use as input** button, which
feeds the output straight back into the other tools so you can chain operations —
merge → watermark → compress → protect.

---

## Editing an existing page

The **Edit page** tab draws a box over any part of the page and then erases it,
replaces it with new text, or drops an image in its place. Erasing genuinely
removes the content from the file rather than covering it with a white
rectangle, so the old text cannot be recovered by copying it out or opening the
file in another program.

**The replacement text matches the original.** When a region is selected, the
font name, point size, colour and weight are read from the page itself — and
where possible the *embedded font file is extracted from the PDF and reused*, so
the new text is set in the same typeface as everything around it rather than a
lookalike. The tab shows what it detected and which font it ended up using,
every time.

Two things are worth knowing:

- **A PDF does not reflow.** If the replacement is longer than what it replaces,
  the surrounding text will not move aside. Rather than printing over its
  neighbours, the new text is shrunk to fit the space the old text occupied, and
  the size change is reported. Where even that isn't enough, you get a warning.
- **Subsetted fonts.** Most PDFs embed only the glyphs they actually use, which
  strips the character map and makes the font unusable for new text. That is
  detected, and the closest available match is used instead — the standard PDF
  font of the same name, then the same family installed on this machine, then
  the bundled Arabic face. Whichever it lands on is stated plainly.

What this is not is a word processor. Clicking into a paragraph and retyping it
with everything after it flowing to fit is not something a PDF can do; tools
that claim otherwise rebuild the page and lose the layout.

---

## Arabic support

Arabic in PDFs breaks in two directions, and PDF Studio handles both.

**Writing Arabic into a PDF.** PDF libraries do no text shaping: hand them Arabic
and you get isolated, disconnected letters in the wrong order, or nothing at all.
PDF Studio shapes the letters and applies the bidirectional algorithm before
drawing, so watermarks, free text and form values come out correctly joined and
correctly ordered. The **Amiri** typeface (SIL Open Font License) ships in `fonts/`,
so this works out of the box with no system font to install. If you prefer a
different face, drop any Arabic `.ttf` into `fonts/` as `arabic.ttf`.

**Reading Arabic out of a PDF.** Many Arabic PDFs store pre-rendered glyphs
(Unicode "presentation forms") laid out in visual rather than logical order.
Copy that text anywhere and it comes out reversed and disconnected. On the
**Extract & convert** tab, *Letter order repair* rebuilds the real letters and the
proper reading order — including lam-alef ligatures, embedded English phrases, and
numbers, all of which naive reversal gets wrong. Leave it on **Auto** and it only
touches pages that actually need it.

Arabic is also handled in:

- **Word export** — Arabic documents are converted in text mode with right-to-left
  paragraphs, because the layout-preserving converter mangles Arabic
- **Excel export** — sheets containing Arabic are set right-to-left with
  right-aligned cells
- **Form filling** — Arabic values are always flattened onto the page. Interactive
  PDF form fields render with built-in fonts that contain no Arabic glyphs, so an
  editable field would show empty boxes in most viewers; drawing the text onto the
  page with a real Arabic font is the only reliable way
- **File names and passwords** — Arabic works in both

**OCR** needs Tesseract installed separately, with the Arabic language data:

- Windows: the `tesseract-ocr-w64` installer, ticking Arabic under language data
- macOS: `brew install tesseract tesseract-lang`
- Linux: `sudo apt install tesseract-ocr tesseract-ocr-ara`

---

## Notes

**Temporary files.** Everything is written to a `pdfstudio_work` folder inside your
system temp directory and stays there until you delete it or the machine restarts.
Download anything you want to keep, and remove files from the library when done.

**Changing the port**, if 8765 is taken:
```bash
PDFSTUDIO_PORT=9000 python run.py        # macOS / Linux
set PDFSTUDIO_PORT=9000 && python run.py # Windows
```

---

## Layout

```
pdftool/
├── app.py              server and all processing
├── templates/
│   └── index.html      the whole interface (HTML + CSS + JS in one file)
├── requirements.txt    dependencies
├── requirements-optional.txt
├── run.py              builds the environment and launches (development)
├── desktop.py          entry point for the standalone application
├── build_app.py        builds the standalone application — run once
├── installer.iss       optional Inno Setup installer script
├── start.bat           Windows launcher
├── start.sh            macOS / Linux launcher
└── fonts/
    ├── arabic.ttf      Amiri Regular  (SIL OFL 1.1)
    ├── arabic-bold.ttf Amiri Bold
    └── AMIRI-LICENSE.txt
```

Libraries: Flask · pypdf · pikepdf · PyMuPDF · pdfplumber · ReportLab · Pillow ·
python-docx · openpyxl · pdf2docx · arabic-reshaper · python-bidi.
