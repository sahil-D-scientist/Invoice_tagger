"""
Add a product QR code to each page of a merged invoice PDF.

Each QR encodes a URL to the viewer page (the same Streamlit app in view-mode),
so scanning it opens a simple page showing the product image + text.

For every page:
  1. Extract the SKU from the "Product Details" section.
  2. Look up the SKU (WEBSITE_SKU) in the product sheet.
  3. Build a viewer URL carrying the product name, internal SKU and image URL.
  4. Render that URL as a QR code into the empty bottom area of the page.

Pages whose SKU is not found in the sheet are logged and left unchanged.
"""

import io
import logging
import re
from urllib.parse import urlencode

import fitz  # PyMuPDF
import pandas as pd
import qrcode

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger("qr")

# --- Config -----------------------------------------------------------------
SHEET_ID = "1BMwaGapRsoPJ8sdteFzpRenFJbkds0AIex75nWF9TTM"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=csv&gid=0"

QR_SIZE = 90          # QR side length in PDF points
QR_MARGIN = 20        # gap from page edges / from content above
SKU_RE = re.compile(r"Product Details.*?Order No\.\s*\n([^\n]+)", re.S)


# --- Data -------------------------------------------------------------------
def load_product_map(source=SHEET_URL):
    """Return {WEBSITE_SKU: {product_name, image_url, internal_sku}} from the sheet."""
    df = pd.read_csv(source, dtype=str).fillna("")
    mapping = {}
    for _, r in df.iterrows():
        mapping[r["WEBSITE_SKU"].strip()] = {
            "product_name": r["PRODUCT_NAME"].strip(),
            "image_url": r["PRODUCT_IMAGE"].strip(),
            "internal_sku": r["INTERNAL_SKU"].strip(),
        }
    log.info("Loaded %d products from sheet", len(mapping))
    return mapping


def extract_sku(page):
    """Return the SKU string from a page's Product Details section, or None."""
    m = SKU_RE.search(page.get_text())
    return m.group(1).strip() if m else None


def view_url(base_url: str, product: dict) -> str:
    """Build the viewer URL that shows this product's image + text when opened."""
    query = urlencode({
        "n": product["product_name"],
        "s": product["internal_sku"],
        "img": product["image_url"],
    })
    return f"{base_url.rstrip('/')}/?{query}"


def make_qr_png(data: str) -> bytes:
    """Render a string (the viewer URL) to a QR-code PNG (bytes)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def qr_rect(page):
    """Bottom-right rectangle for the QR, placed in the empty area below content."""
    blocks = page.get_text("blocks")
    content_bottom = max((b[3] for b in blocks), default=0)
    x1 = page.rect.width - QR_MARGIN
    x0 = x1 - QR_SIZE
    y0 = min(content_bottom + QR_MARGIN, page.rect.height - QR_MARGIN - QR_SIZE)
    y0 = max(y0, content_bottom + 2)  # ensure no overlap with content
    return fitz.Rect(x0, y0, x0 + QR_SIZE, y0 + QR_SIZE)


# --- Per-page + document processing ----------------------------------------
def process_page(page, product_map, base_url):
    """Add a product QR code to one page. Returns the SKU handled, or None if skipped."""
    sku = extract_sku(page)
    if not sku:
        log.warning("Page %d: no SKU found; skipped", page.number + 1)
        return None
    product = product_map.get(sku)
    if product is None:
        log.warning("Page %d: SKU %r not in sheet; skipped", page.number + 1, sku)
        return None
    page.insert_image(qr_rect(page), stream=make_qr_png(view_url(base_url, product)))
    log.info("Page %d: SKU %r -> internal %s", page.number + 1, sku, product["internal_sku"])
    return sku


def process_pdf(in_path, out_path, product_map, base_url, page_limit=None):
    """Process every page (or the first `page_limit` pages) and save a new PDF."""
    doc = fitz.open(in_path)
    added = 0
    for page in doc:
        if page_limit is not None and page.number >= page_limit:
            break
        if process_page(page, product_map, base_url):
            added += 1
    doc.save(out_path)
    doc.close()
    log.info("Saved %s (%d QR codes added)", out_path, added)


if __name__ == "__main__":
    import sys

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    base = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8501"
    pmap = load_product_map()
    out = "MergedPDF_prototype.pdf" if limit else "MergedPDF_with_QR.pdf"
    process_pdf("MergedPDF.pdf", out, pmap, base, page_limit=limit)
