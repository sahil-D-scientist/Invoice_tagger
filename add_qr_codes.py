"""
Add a product QR code to each page of a merged Amazon invoice PDF.

Each QR encodes a URL to the static viewer page, so scanning it opens a simple
page showing the product image + text.

For every page:
  1. Extract the item line from the invoice table: product title, ASIN,
     seller SKU, HSN code and qty.
  2. Match the item's full description against the sheet's WEBSITE_SKU column
     to get its INTERNAL_SKU (and product image).
  3. Stamp the internal SKU with the QR code below it into the empty area of
     the page.

Pages without an invoice table (e.g. shipping labels) are logged and left
unchanged.
"""

import io
import logging
import re
import urllib.request
import zipfile
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
SKU_FONTSIZE = 13     # internal SKU caption above the QR
SKU_GAP = 6           # gap between the caption and the QR
IMG_SIZE = 90         # product image drawn beside the QR
IMG_GAP = 10          # gap between the image and the QR

# Invoice table column bounds, in PDF points.
DESC_X0, DESC_X1 = 57, 344
QTY_X0, QTY_X1 = 372, 397

# "Title | B0XXXXXXXX ( seller sku )" tail of the description.
ASIN_RE = re.compile(r"\|\s*(B0[A-Z0-9]{8})\s*\((.*?)\)\s*$")


# --- Data -------------------------------------------------------------------
def sheet_key(text: str) -> str:
    """Normalise an invoice description so sheet / PDF text compare equal."""
    return " ".join(text.split()).lower()


def load_sheet_pictures(sheet_id=SHEET_ID):
    """Return {data row index: image bytes} for pictures pasted into the sheet.

    Pictures float above their cell rather than being its value, so they are
    absent from the CSV export; the xlsx export carries them as drawings.
    """
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=xlsx"
    try:
        book = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(url).read()))
    except Exception as e:
        log.warning("Could not read pictures from the sheet: %s", e)
        return {}
    if "xl/drawings/drawing1.xml" not in book.namelist():
        return {}

    rels = dict(re.findall(
        r'Id="([^"]+)"[^>]*Target="([^"]+)"',
        book.read("xl/drawings/_rels/drawing1.xml.rels").decode("utf-8"),
    ))
    drawing = book.read("xl/drawings/drawing1.xml").decode("utf-8")
    pictures = {}
    for anchor in re.findall(r"<xdr:(?:one|two)CellAnchor.*?</xdr:(?:one|two)CellAnchor>",
                             drawing, re.S):
        row = re.search(r"<xdr:row>(\d+)</xdr:row>", anchor)
        rid = re.search(r'r:embed="([^"]+)"', anchor)
        if not row or not rid:
            continue
        target = rels[rid.group(1)].replace("../", "xl/")
        pictures[int(row.group(1)) - 1] = book.read(target)   # row 0 is the header
    log.info("Found %d pasted picture(s) in the sheet", len(pictures))
    return pictures


def fetch_image(url: str) -> bytes:
    """Download a product image, or return b"" if it can't be fetched."""
    try:
        return urllib.request.urlopen(url, timeout=10).read()
    except Exception as e:
        log.warning("Could not fetch image %s: %s", url, e)
        return b""


def load_product_map(source=SHEET_URL, pictures=None):
    """Return {sheet_key(WEBSITE_SKU): {product_name, image_url, internal_sku, image}}."""
    df = pd.read_csv(source, dtype=str).fillna("")
    if pictures is None:
        pictures = load_sheet_pictures()
    mapping = {}
    for i, r in df.iterrows():
        image_url = r["PRODUCT_IMAGE"].strip()
        mapping[sheet_key(r["WEBSITE_SKU"])] = {
            "product_name": r["PRODUCT_NAME"].strip(),
            "image_url": image_url,
            "internal_sku": r["INTERNAL_SKU"].strip(),
            "image": fetch_image(image_url) if image_url else pictures.get(i, b""),
        }
    log.info("Loaded %d products from sheet", len(mapping))
    return mapping


def _words(page):
    """Page words as {text, x0, x1, top} dicts."""
    return [
        {"text": w[4], "x0": w[0], "x1": w[2], "top": w[1]}
        for w in page.get_text("words")
    ]


def extract_items(page):
    """Return the invoice table's items as [{title, asin, sku, hsn, qty}]."""
    words = _words(page)
    hdr = next((w for w in words if w["text"] == "Description"), None)
    tot = next((w for w in words if w["text"] == "TOTAL:"), None)
    if not hdr or not tot:
        return []
    top, bot = hdr["top"], tot["top"]

    # Each item starts with its Sl. No in the leftmost column.
    starts = sorted(
        (w for w in words
         if w["x1"] < DESC_X0 and w["text"].isdigit() and top < w["top"] < bot),
        key=lambda w: w["top"],
    )

    items = []
    for i, s in enumerate(starts):
        y0 = s["top"] - 2
        y1 = starts[i + 1]["top"] - 2 if i + 1 < len(starts) else bot
        row = [w for w in words if y0 <= w["top"] < y1]
        row.sort(key=lambda w: (round(w["top"]), w["x0"]))

        tokens, hsn = [], ""
        for w in row:
            if not (DESC_X0 <= w["x0"] and w["x1"] <= DESC_X1):
                continue
            t = w["text"]
            if t.startswith("HSN:"):
                hsn = t[4:]
                break
            if t.startswith("₹"):      # price column wrapping into the description
                if tokens and tokens[-1] == "-":
                    tokens.pop()
                continue
            tokens.append(t)

        desc = " ".join(tokens)
        m = ASIN_RE.search(desc)
        title, asin, sku = (desc[: m.start()].rstrip(" |"), m.group(1), m.group(2).strip()) \
            if m else (desc, "", "")
        qty = next((w["text"] for w in row if QTY_X0 <= w["x0"] and w["x1"] <= QTY_X1), "")
        items.append({"title": title, "asin": asin, "sku": sku, "hsn": hsn, "qty": qty,
                      "text": f"{desc} HSN:{hsn}" if hsn else desc})
    return items


def extract_item(page):
    """Return the page's first invoice item, or None."""
    items = extract_items(page)
    return items[0] if items else None


def view_url(base_url: str, item: dict, product=None) -> str:
    """Build the viewer URL that shows the product's details when opened."""
    query = {
        "n": item["title"],
        "asin": item["asin"],
        "s": item["sku"],
        "hsn": item["hsn"],
        "qty": item["qty"],
    }
    if product:
        query["img"] = product["image_url"]
        if product["internal_sku"]:
            query["s"] = product["internal_sku"]
    return f"{base_url.rstrip('/')}/?{urlencode({k: v for k, v in query.items() if v})}"


def make_qr_png(data: str) -> bytes:
    """Render a string (the viewer URL) to a QR-code PNG (bytes)."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    buf = io.BytesIO()
    qr.make_image(fill_color="black", back_color="white").save(buf, format="PNG")
    return buf.getvalue()


def empty_band(page):
    """Return (top, height) of the tallest gap between text blocks on the page."""
    spans = sorted((b[1], b[3]) for b in page.get_text("blocks"))
    merged = []
    for top, bottom in spans:
        if merged and top <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], bottom)
        else:
            merged.append([top, bottom])

    edges = [QR_MARGIN] + [y for span in merged for y in span] + [page.rect.height - QR_MARGIN]
    gaps = [(edges[i + 1] - edges[i], edges[i]) for i in range(0, len(edges) - 1, 2)]
    height, top = max(gaps)
    return top, height


def stamp_tag(page, qr_png: bytes, internal_sku: str = "", image: bytes = b""):
    """Draw the internal SKU, its QR code, and the product image beside the QR."""
    top, height = empty_band(page)
    caption = (SKU_FONTSIZE + SKU_GAP) if internal_sku else 0
    block = max(QR_SIZE, IMG_SIZE if image else 0) + caption
    y = top + max((height - block) / 2, 0)
    y = min(y, page.rect.height - QR_MARGIN - block)
    cx = page.rect.width / 2

    if internal_sku:
        width = fitz.get_text_length(internal_sku, fontname="hebo", fontsize=SKU_FONTSIZE)
        page.insert_text((cx - width / 2, y + SKU_FONTSIZE),
                         internal_sku, fontname="hebo", fontsize=SKU_FONTSIZE)

    # Image and QR sit side by side, centred together on the page.
    row_width = QR_SIZE + (IMG_GAP + IMG_SIZE if image else 0)
    x = cx - row_width / 2
    y += caption
    if image:
        page.insert_image(fitz.Rect(x, y, x + IMG_SIZE, y + IMG_SIZE), stream=image,
                          keep_proportion=True)
        x += IMG_SIZE + IMG_GAP
    page.insert_image(fitz.Rect(x, y, x + QR_SIZE, y + QR_SIZE), stream=qr_png)


# --- Per-page + document processing ----------------------------------------
def process_page(page, product_map, base_url):
    """Add a product QR code to one page. Returns the item handled, or None if skipped."""
    item = extract_item(page)
    if not item:
        log.warning("Page %d: no invoice item found; skipped", page.number + 1)
        return None
    product = product_map.get(sheet_key(item["text"])) if product_map else None
    stamp_tag(page, make_qr_png(view_url(base_url, item, product)),
              product["internal_sku"] if product else "",
              product["image"] if product else b"")
    log.info("Page %d: %s -> internal %s", page.number + 1, item["sku"],
             product["internal_sku"] if product else "(not in sheet)")
    return item


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

    in_pdf = sys.argv[1] if len(sys.argv) > 1 else "MergedPDF.pdf"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    base = sys.argv[3] if len(sys.argv) > 3 else "https://sahil-d-scientist.github.io/Invoice_tagger"
    pmap = load_product_map()
    out = in_pdf.rsplit(".", 1)[0] + ("_prototype.pdf" if limit else "_with_QR.pdf")
    process_pdf(in_pdf, out, pmap, base, page_limit=limit)
