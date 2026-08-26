"""
Streamlit app with two modes:

• Viewer mode  — opened via a QR link (?n=&s=&hsn=&img=). Shows the product
  image + text on a simple page.
• Tool mode    — upload an Amazon invoice PDF (optionally with a Google Sheet of
  product images) and download a PDF with a product QR code on every page.

Reuses the per-page logic from add_qr_codes.py.
"""

import re

import fitz  # PyMuPDF
import pandas as pd
import streamlit as st

from add_qr_codes import extract_item, fetch_image, make_qr_png, sheet_key, stamp_tag, view_url

REQUIRED_COLS = ["WEBSITE_SKU", "INTERNAL_SKU", "PRODUCT_NAME", "PRODUCT_IMAGE"]
# Bump on deploy, so a stale Streamlit Cloud deployment is visible at a glance.
BUILD = "build 7 - product image beside the QR"
# Static GitHub Pages viewer that QR codes open when scanned.
VIEWER_URL = "https://sahil-d-scientist.github.io/Invoice_tagger"

st.set_page_config(page_title="Invoice QR Tagger", page_icon="🏷️", layout="centered")


# --- Viewer mode (what a scanned QR opens) ---------------------------------
def render_viewer(params):
    sku = params.get("s", "")
    img = params.get("img", "")
    st.markdown(
        """
        <style>.block-container {max-width: 480px; padding-top: 3rem; text-align:center;}</style>
        """,
        unsafe_allow_html=True,
    )
    if img:
        st.image(img, use_container_width=True)
    st.markdown(f"## {sku}")
    rows = [("ASIN", params.get("asin", "")),
            ("HSN", params.get("hsn", "")),
            ("Qty", params.get("qty", ""))]
    st.table(pd.DataFrame([{"Field": k, "Value": v} for k, v in rows if v]))


qp = st.query_params
if "img" in qp or "n" in qp:
    render_viewer(qp)
    st.stop()


# --- Tool-mode helpers ------------------------------------------------------
def sheet_csv_url(link: str) -> str:
    m = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", link)
    if not m:
        raise ValueError("That doesn't look like a Google Sheets link.")
    gid = re.search(r"[#&?]gid=(\d+)", link)
    gid = gid.group(1) if gid else "0"
    return f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}"


@st.cache_data(show_spinner=False)
def load_sheet(link: str) -> pd.DataFrame:
    return pd.read_csv(sheet_csv_url(link), dtype=str).fillna("")


@st.cache_data(show_spinner=False)
def build_product_map(df: pd.DataFrame) -> dict:
    """Map each sheet row by its description, downloading its product image."""
    return {
        sheet_key(r["WEBSITE_SKU"]): {
            "product_name": r["PRODUCT_NAME"].strip(),
            "image_url": r["PRODUCT_IMAGE"].strip(),
            "internal_sku": r["INTERNAL_SKU"].strip(),
            "image": fetch_image(r["PRODUCT_IMAGE"].strip()) if r["PRODUCT_IMAGE"].strip() else b"",
        }
        for _, r in df.iterrows()
    }


def process_pdf_bytes(pdf_bytes: bytes, product_map: dict, base_url: str):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    results = []
    for page in doc:
        item = extract_item(page)
        if not item:
            results.append((page.number + 1, "", "No invoice item found"))
            continue
        product = product_map.get(sheet_key(item["text"]))
        if product is None:
            results.append((page.number + 1, item["sku"], "Not in sheet"))
            continue
        stamp_tag(page, make_qr_png(view_url(base_url, item, product)),
                  product["internal_sku"], product["image"])
        results.append((page.number + 1, product["internal_sku"], "Tagged"))
    out = doc.tobytes()
    doc.close()
    return out, results


# --- Tool-mode UI -----------------------------------------------------------
st.markdown(
    """
    <style>
      .block-container {max-width: 720px; padding-top: 3rem;}
      div[data-testid="stMetric"] {
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.12);
        border-radius: 10px; padding: 14px 18px;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("🏷️ Invoice QR Tagger")
st.markdown("Add a product QR code to every Amazon invoice page.")
st.caption(BUILD)
st.divider()

sheet_link = st.text_input(
    "Product sheet",
    placeholder="Paste Google Sheet link…",
    help="Maps the invoice description (WEBSITE_SKU) to an internal SKU + image. "
         "Only pages whose item is in the sheet get a QR code.",
)
app_url = st.text_input(
    "App URL for QR codes",
    value=VIEWER_URL,
    help="The static viewer QR codes open when scanned. Defaults to the GitHub Pages viewer.",
)

df = None
if sheet_link.strip():
    try:
        df = load_sheet(sheet_link.strip())
        missing = [c for c in REQUIRED_COLS if c not in df.columns]
        if missing:
            st.error(f"Sheet is missing columns: {', '.join(missing)}")
            df = None
        else:
            st.success(f"Sheet connected — {len(df)} products found.", icon="✅")
    except Exception as e:
        st.error(f"Couldn't read the sheet: {e}", icon="⚠️")

pdf_file = st.file_uploader("Invoice PDF", type=["pdf"])

st.write("")
ready = df is not None and pdf_file is not None and bool(app_url.strip())
if st.button("Generate PDF", type="primary", use_container_width=True, disabled=not ready):
    with st.spinner("Adding QR codes…"):
        product_map = build_product_map(df)
        out_bytes, results = process_pdf_bytes(
            pdf_file.getvalue(), product_map, app_url.strip()
        )
    no_image = [p["internal_sku"] for p in product_map.values() if p["image_url"] and not p["image"]]
    if no_image:
        st.warning(
            "Couldn't load the image for: " + ", ".join(no_image)
            + ". The link must open the image itself (or be a Drive share link).",
            icon="⚠️",
        )
    # Persist so the download click (which reruns the script) doesn't clear it.
    st.session_state["result"] = {
        "bytes": out_bytes,
        "results": results,
        "name": pdf_file.name.rsplit(".", 1)[0] + "_with_QR.pdf",
    }

# Render results from session_state (survives the download rerun).
if "result" in st.session_state:
    r = st.session_state["result"]
    results = r["results"]
    tagged = sum(1 for _, _, s in results if s.startswith("Tagged"))
    skipped = len(results) - tagged

    st.divider()
    c1, c2, c3 = st.columns(3)
    c1.metric("Total pages", len(results))
    c2.metric("Tagged", tagged)
    c3.metric("Skipped", skipped)

    st.download_button(
        "⬇️  Download tagged PDF",
        data=r["bytes"],
        file_name=r["name"],
        mime="application/pdf",
        type="primary",
        use_container_width=True,
    )

    with st.expander(f"Page-by-page status ({skipped} skipped)"):
        st.dataframe(
            pd.DataFrame(results, columns=["Page", "Internal SKU", "Status"]),
            use_container_width=True,
            hide_index=True,
        )
