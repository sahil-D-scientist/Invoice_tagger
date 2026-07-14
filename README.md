# Invoice QR Tagger

A Streamlit app that adds a product **QR code** to every page of a merged invoice PDF.
Scanning a QR opens a simple page showing the product **image + text**.

## How it works

- **Tool mode** — paste a Google Sheet link, confirm the app URL, upload the merged PDF,
  and download a new PDF with a QR code placed in the empty bottom area of each page.
- **Viewer mode** — the QR encodes a URL back to this same app (`?n=&s=&img=`).
  Opening it shows the product image, name, and internal SKU.

Each page's **SKU** (from the "Product Details" section) is matched against the sheet's
`WEBSITE_SKU` column. Pages whose SKU is not found are logged and left unchanged.

## Product sheet columns

`WEBSITE_SKU`, `INTERNAL_SKU`, `PRODUCT_NAME`, `PRODUCT_IMAGE`

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
  QR's URL parameters (`?n=&s=&img=&size=&qty=&color=`) and renders the product card
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
- `requirements.txt` — dependencies
