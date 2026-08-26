# Invoice QR Tagger

A Streamlit app that stamps the **internal SKU**, the product **image** and a **QR code**
onto every page of a merged Amazon invoice PDF. Scanning a QR opens a simple page showing
the product image + text.

## How it works

- **Tool mode** — upload the merged PDF, confirm the app URL, optionally paste a Google
  Sheet link, and download a new PDF with the internal SKU above the product image and QR
  code, placed side by side in the tallest empty band of each page.
- **Viewer mode** — the QR encodes a URL back to this same app (`?n=&s=&hsn=&img=`).
  Opening it shows the product title, SKU, ASIN, HSN and qty (plus the image, if a sheet
  is connected).

Each invoice page's item line is read straight off the invoice table: **product title**,
**ASIN**, **seller SKU**, **HSN code** and **qty**. Pages with no invoice table (e.g.
shipping labels) are logged and left unchanged.

## Product sheet columns (optional — supplies the internal SKU + image)

`WEBSITE_SKU`, `INTERNAL_SKU`, `PRODUCT_NAME`, `PRODUCT_IMAGE`

`WEBSITE_SKU` holds the item's **full invoice description**, e.g.

```
Pramila Creations Rakhi for Brother and Bhabhi Combo |
Pack of 6 Traditional Beaded Rakhi Bracelet Set for
Rakshabandhan with Roli Chawal | Family Rakhi Gift Pack |
B0HC4JSYM4 ( RAKHI-NEW-Z-6 PCS )
HSN:63079090
```

Matching ignores line breaks and letter case. **Only pages whose item is in the sheet are
tagged** — anything else is logged and left untouched.

`PRODUCT_IMAGE` takes either a **direct image URL** (right-click the product photo ->
*Copy image address*; ends in `.jpg` / `.png`) or a **Google Drive share link**, which is
rewritten to the URL that serves the file itself. A link to an ordinary web page will not
work — it downloads HTML rather than an image — and neither will a picture pasted into the
cell, since that is not the cell's value and never reaches the CSV export. Rows whose
image can't be fetched are logged and simply get no picture.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Architecture

Two independent pieces, so the scan experience is instant:

- **Generator** — the Streamlit app (`app.py`) produces the tagged PDF. Deploy on
  [Streamlit Community Cloud](https://share.streamlit.io); Python is needed for PDF work.
- **Viewer** — a static page (`index.html`) hosted on **GitHub Pages**. It reads the
  QR's URL parameters (`?n=&s=&asin=&hsn=&qty=&img=`) and renders the product card
  in the browser with no server / no cold start.

### Set up the viewer (GitHub Pages)

1. Repo **Settings → Pages** → Source **Deploy from a branch** → `main` / `/ (root)` → Save.
2. Viewer goes live at `https://sahil-d-scientist.github.io/Invoice_tagger/`.
3. In the Streamlit tool, set **"App URL for QR codes"** to that URL. Every QR then opens
   the static viewer when scanned.

## Files

- `app.py` — Streamlit UI (PDF generator; also renders a fallback viewer)
- `add_qr_codes.py` — PDF/QR processing logic (also runnable as a CLI)
- `index.html` — fast static viewer for QR scans (GitHub Pages)
- `fonts/` — Noto Sans Devanagari (SIL Open Font License), used for Hindi SKU captions
- `requirements.txt` — dependencies
