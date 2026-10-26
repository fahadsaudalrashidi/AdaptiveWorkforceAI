# Local OCR fixtures

These are actual raster-image PDFs with synthetic content, not mocked OCR
responses or customer documents. No searchable text layer is present in the
`scanned_*` files. `mixed_pages.pdf` combines a searchable financial table with
an Arabic scanned page; `mixed_same_page.pdf` has both native text and an image
on one page. The deliberately degraded fixture contains ambiguous letter/digit
shapes; do not expect a particular incorrect recognized value.

Run `python backend/tests/fixtures/pdf_ocr/generate_fixtures.py` to regenerate.
The authoring script uses DejaVu Sans, Pillow, pypdfium2, arabic-reshaper 3.x and
python-bidi 0.6.x. The latter two are **authoring-only** dependencies; neither is
required to run the app or tests against the committed PDFs.

Tests require local Tesseract with both `ara` and `eng` language data. The Replit
Nix `tesseract` package includes them. Nothing is fetched at extraction time.
