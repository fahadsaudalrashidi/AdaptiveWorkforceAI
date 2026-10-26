"""Regenerate small, synthetic image-only PDFs (never real customer data).

Run from the repository root. Fixture authoring only requires arabic-reshaper
and python-bidi in addition to the runtime's Pillow and pypdfium2.
"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
import arabic_reshaper
from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import pypdfium2 as pdfium
from backend.tests.test_local_file_analytics import _simple_searchable_pdf

ROOT = Path(__file__).parent
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def scan(name, lines, arabic=False, blur=False):
    image = Image.new("RGB", (1500, 1000), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(FONT, 48)
    for i, line in enumerate(lines):
        if arabic:
            line = get_display(arabic_reshaper.reshape(line))
        draw.text((100, 100 + i * 100), line, font=font, fill="black")
    if blur:
        image = image.resize((450, 300)).resize((1500, 1000)).filter(ImageFilter.GaussianBlur(2))
    image.save(ROOT / name, "PDF", resolution=200)
    return image


if __name__ == "__main__":
    english = scan("scanned_english.pdf", [
        "Quarterly revenue report", "Retail revenue 1250 SAR",
        "Online revenue 750 SAR", "Renewal date December 2026",
    ])
    scan("scanned_arabic.pdf", [
        "تقرير المبيعات", "إجمالي الإيرادات ١٢٥٠ ريال",
        "المبيعات المحلية ٧٥٠ ريال", "تاريخ التقرير ديسمبر",
    ], arabic=True)
    scan("scanned_low_quality.pdf", [
        "Revenue report", "Retail 12O8.5O", "Online 7S8.O5",
    ], blur=True)
    scan("scanned_identifiers.pdf", [
        "Confidential contacts", "contact.person@example.com",
        "Mobile +966 50 123 4567",
    ])
    with pdfium.PdfDocument(_simple_searchable_pdf([
        "Department      Sales", "Retail          12.5",
        "Online          30.0", "Retail          7.5",
    ])) as mixed:
        with pdfium.PdfDocument(ROOT / "scanned_arabic.pdf") as arabic:
            mixed.import_pages(arabic)
        mixed.save(ROOT / "mixed_pages.pdf")
    with pdfium.PdfDocument(_simple_searchable_pdf("Searchable report heading")) as same:
        page = same[0]
        bitmap = pdfium.PdfBitmap.from_pil(english)
        obj = pdfium.PdfImage.new(same)
        obj.set_bitmap(bitmap)
        obj.set_matrix(pdfium.PdfMatrix(500, 0, 0, 333, 50, 200))
        page.insert_obj(obj)
        page.gen_content()
        same.save(ROOT / "mixed_same_page.pdf")
        bitmap.close()
        page.close()
