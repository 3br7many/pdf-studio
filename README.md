# PDF Studio

A free PDF toolkit for Windows that runs entirely on your own computer.
Nothing is uploaded anywhere, and it works with Arabic text out of the box.

**Download:** [PDFStudio-portable.zip](https://github.com/3br7many/pdf-studio/releases/download/portable/PDFStudio-portable.zip)
(about 130 MB, no installation, no administrator rights)

## Run it

1. Extract the zip anywhere, for example your Desktop.
2. Open the extracted folder and run `PDF Studio.exe`.
3. If Windows shows "Windows protected your PC", click **More info**, then **Run anyway**.
   The app is not code-signed yet, so this warning is expected.

The SHA-256 checksum of the download is listed in the release notes of the
[portable release](https://github.com/3br7many/pdf-studio/releases/tag/portable).

## What it does

| Tool | What it does |
| --- | --- |
| Merge | Combine several PDFs in the order you choose |
| Organize pages | Delete, rotate and reorder pages with thumbnails |
| Split | One file per page, every N pages, or custom ranges |
| Extract & convert | Text, Word, Excel tables, images, pages as PNG |
| OCR | Make scans searchable (needs Tesseract installed) |
| Compress | Analyze the file, then Lossless, Balanced or Maximum |
| Security | AES-256 encryption with permissions, and password removal |
| Watermark | Text or logo, tiled or single |
| Edit page | Erase or retype text in the original font, find and replace |
| Sign & stamp | Place a signature or stamp image on a page |
| Fill forms | Fill PDF form fields, with optional flattening |

## Arabic support

Arabic is shaped and ordered correctly when it is written into a PDF, and
reversed or disconnected text is repaired when it is read out. The Amiri
typeface is bundled.

## Privacy

The app runs a small server on `127.0.0.1` only. Your files stay on your
computer, and nothing is sent anywhere except the update check described below.

## Updates

On start, the app asks this repository for a newer release. If one exists, a bar
offers **Update now**. Updates are signed: the app refuses any package whose
signature does not match the public key built into it. The header also has a
**Check for updates** button. Both need an internet connection.

## Run from source

Requires Python 3.9 or newer.

```
python run.py
```

The first run builds its own environment, then opens `http://127.0.0.1:8765`.
To build the standalone application, run `python build_app.py`. See
[docs/MAINTAINER.md](docs/MAINTAINER.md) for build and release notes.

## Support

Found a bug or have a suggestion? Open an
[issue](https://github.com/3br7many/pdf-studio/issues). Please do not attach
files that contain private information.

## License

Copyright (C) 2026 Abdelrahman Younes.

PDF Studio is free software under the **GNU Affero General Public License v3.0**
(see [LICENSE](LICENSE)). It is provided as is, without any warranty. It uses
[PyMuPDF](https://github.com/pymupdf/PyMuPDF), which is licensed under the
AGPL-3.0, and several permissively licensed libraries (Flask, pikepdf, pypdf,
pdfplumber, ReportLab, Pillow, python-docx, openpyxl, arabic-reshaper,
python-bidi). The bundled Amiri typeface is licensed under the SIL Open Font
License (see `fonts/AMIRI-LICENSE.txt`).
