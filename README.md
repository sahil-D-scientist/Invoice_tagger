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

## Deploy

Push to GitHub and deploy `app.py` on [Streamlit Community Cloud](https://share.streamlit.io).
The QR "App URL" auto-detects the deployed URL, so scans work from any phone.

## Files

- `app.py` — Streamlit UI (tool + viewer modes)
- `add_qr_codes.py` — PDF/QR processing logic (also runnable as a CLI)
- `requirements.txt` — dependencies
