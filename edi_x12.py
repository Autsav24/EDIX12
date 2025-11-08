import streamlit as st
import pandas as pd
import io
from edi_x12 import parse_271_to_table

st.set_page_config(page_title="EDI 271 Parser", layout="wide")

st.title("🏥 EDI 271 Eligibility Response Parser")

st.markdown("Upload your **EDI 271 (X12)** file and extract full structured data below.")

uploaded_file = st.file_uploader("📂 Upload EDI 271 File", type=["txt", "edi", "dat"])

if uploaded_file:
    edi_text = uploaded_file.read().decode("utf-8", errors="ignore")
    with st.spinner("Parsing 271 file..."):
        results = parse_271_to_table(edi_text)

    if not results:
        st.warning("⚠️ No EB (Eligibility/Benefit) segments found.")
    else:
        df = pd.DataFrame(results)
        st.success(f"✅ Parsed {len(df)} coverage records successfully.")
        st.dataframe(df, use_container_width=True)

        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Eligibility")
        buffer.seek(0)

        st.download_button(
            "📥 Download Excel",
            data=buffer,
            file_name="EDI_271_Parsed.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
else:
    st.info("👆 Upload an EDI 271 file to begin.")
