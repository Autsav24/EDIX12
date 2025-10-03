# app.py
import io
import zipfile
import streamlit as st
from datetime import datetime, timedelta
from edi_x12 import (
    Provider, Party, build_270, parse_271, ServiceTypeMap
)

st.set_page_config(page_title="X12 EDI – 270/271", page_icon="📡", layout="wide")
st.title("📡 X12 EDI – 270/271 Eligibility (MVP)")

tab_build, tab_parse, tab_help = st.tabs(["Build 270", "Parse 271", "Help & Notes"])

# =========================
# Build 270
# =========================
with tab_build:
    st.subheader("Build a 270 Request")

    col1, col2 = st.columns(2)
    with col1:
        payer_id = st.text_input("Payer ID (PI)", value="12345")
        prov_name = st.text_input("Provider Name", value="Buddha Clinic")
        npi = st.text_input("Provider NPI", value="1234567890")

        subscriber_last = st.text_input("Subscriber Last Name", value="DOE")
        subscriber_first = st.text_input("Subscriber First Name", value="JOHN")
        subscriber_id = st.text_input("Subscriber Member ID (MI)", value="W123456789")
    with col2:
        service_types = st.multiselect(
            "Service Type Codes (EQ)",
            options=list(ServiceTypeMap.keys()),
            default=["30"],
            format_func=lambda x: f"{x} – {ServiceTypeMap.get(x,'')}"
        )
        dt_start = st.date_input("Eligibility Start", datetime.today().date())
        ranged = st.checkbox("Use Date Range (RD8)", value=True)
        dt_end = st.date_input("Eligibility End", datetime.today().date() + timedelta(days=30)) if ranged else None

        use_dependent = st.checkbox("Query Dependent?", value=False)
        dep_last = st.text_input("Dependent Last Name", value="") if use_dependent else ""
        dep_first = st.text_input("Dependent First Name", value="") if use_dependent else ""
        dep_id = st.text_input("Dependent ID (if required)", value="") if use_dependent else ""

    if st.button("Generate 270"):
        provider = Provider(name=prov_name, npi=npi)
        subscriber = Party(last=subscriber_last, first=subscriber_first, id_code=subscriber_id)
        dependent = Party(last=dep_last, first=dep_first, id_code=dep_id) if use_dependent else None

        edi270 = build_270(
            isa_ctrl=1, gs_ctrl=1, st_ctrl=1,
            payer_id=payer_id,
            provider=provider,
            subscriber=subscriber,
            dependent=dependent,
            service_types=service_types,
            date_start=dt_start.strftime("%Y%m%d"),
            date_end=dt_end.strftime("%Y%m%d") if ranged and dt_end else None,
        )

        st.write("### Generated 270")
        st.code(edi270, language="plain")
        st.download_button(
            "⬇️ Download 270",
            data=edi270.encode("utf-8"),
            file_name=f"270_{subscriber_last}_{datetime.now().strftime('%Y%m%d%H%M')}.x12",
            mime="text/plain"
        )

# =========================
# Parse 271
# =========================
with tab_parse:
    st.subheader("Parse a 271 Response")

    uploaded = st.file_uploader("Upload 271 (text/X12 or ZIP)", type=["x12","edi","txt","dat","zip"])
    if uploaded:
        raw = uploaded.read()

        # If it's a ZIP, open first file inside
        if uploaded.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    # pick the first file-like entry
                    names = [n for n in zf.namelist() if not n.endswith("/")]
                    if not names:
                        st.error("ZIP has no files")
                        st.stop()
                    raw = zf.read(names[0])
            except zipfile.BadZipFile:
                st.error("Uploaded file looks like a ZIP but couldn't be opened.")
                st.stop()

        # Guard: PDFs uploaded by mistake
        if raw[:4] == b"%PDF":
            st.error("This appears to be a PDF, not a raw X12 271. Please upload the .x12/.edi text file.")
            st.stop()

        # Try decodings (handles cp1252 where 0x96 en-dash exists)
        decoded = None
        for enc in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
            try:
                decoded = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if decoded is None:
            decoded = raw.decode("utf-8", errors="replace")

        # Normalize some “smart” punctuation and non-breaking spaces
        replacements = {
            "\u2013": "-", "\u2014": "-",
            "\u2018": "'", "\u2019": "'",
            "\u201c": '"', "\u201d": '"',
            "\u00a0": " ",
        }
        for k, v in replacements.items():
            decoded = decoded.replace(k, v)

        # Parse
        parsed = parse_271(decoded)

        st.write("### Payer")
        st.json(parsed.get("payer", {}))

        st.write("### Provider")
        st.json(parsed.get("provider", {}))

        st.write("### Subscriber")
        st.json(parsed.get("subscriber", {}))

        if parsed.get("dependent"):
            st.write("### Dependent")
            st.json(parsed.get("dependent", {}))

        st.write("### Benefit (EB) Segments")
        if parsed.get("eb"):
            st.dataframe(parsed["eb"], use_container_width=True)
        else:
            st.info("No EB segments found. Check AAA segments or try service type EQ=30.")

        if parsed.get("aaa"):
            st.write("### Rejections (AAA)")
            st.dataframe(parsed["aaa"], use_container_width=True)

        if parsed.get("dtp"):
            st.write("### DTP (Dates)")
            st.dataframe(parsed["dtp"], use_container_width=True)

        if parsed.get("ref"):
            st.write("### REF (References)")
            st.dataframe(parsed["ref"], use_container_width=True)

        st.write("### Raw 271 (first 2000 chars)")
        preview = decoded[:2000] + ("...\n" if len(decoded) > 2000 else "")
        st.code(preview, language="plain")

# =========================
# Help & Notes
# =========================
with tab_help:
    st.markdown("""
### How this MVP works
- **Build 270**: Creates a simple eligibility request with ISA/GS/ST envelopes, payer (NM1*PR), provider (NM1*1P),
  subscriber (NM1*IL) and optional dependent (NM1*QD), date (DTP*291), and one or more service types (EQ).
- **Parse 271**: Pragmatically parses NM1 (payer/provider/subscriber/dependent), EB (benefits), AAA (rejections),
  and surfaces REF/DTP segments. It does not fully implement every variation from payer companion guides.

### Common tips
- If a payer returns **no EB**, try service type **EQ=30** (many payers prefer this over **1**).
- Ensure **control numbers** (ISA13/GS06/ST02) are unique in production; store counters in a DB.
- Respect partner **companion guides** for exact qualifiers (REF/TRN/DMG), date rules, and loop usage.

### Production notes
- Persist requests/responses and counters in a secure DB (Postgres/Supabase/Neon).
- Use secure transport (AS2/SFTP) via your clearinghouse or partner.
- Treat all member data as PHI and follow HIPAA best practices.
""")
