# app.py
import io
import zipfile
import streamlit as st
from datetime import datetime, timedelta
from edi_x12 import (
    Provider, Party, build_270, parse_271, ServiceTypeMap,
    PAYER_PROFILES, normalize_eb_for_reporting
)

st.set_page_config(page_title="X12 EDI – 270/271 (Profiles)", page_icon="📡", layout="wide")
st.title("📡 X12 EDI – 270/271 (Profile-ready MVP)")

# --------- Robust decoder (fixes Windows-1252 0x96 etc.) ----------
def robust_decode(raw: bytes) -> str:
    if raw.startswith(b"%PDF"):
        raise ValueError("Not a plain-text X12 file (PDF detected).")
    if raw[:2] == b"\x1f\x8b":
        raise ValueError("GZIP detected. Upload uncompressed X12 or a ZIP containing it.")
    for enc in ("cp1252", "utf-8", "utf-8-sig", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

def normalize_punctuation(text: str) -> str:
    return (text.replace("\u2013", "-").replace("\u2014", "-")
                .replace("\u2018", "'").replace("\u2019", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u00a0", " "))

tab_build, tab_parse, tab_help = st.tabs(["Build 270", "Parse 271", "Help & Notes"])

# =========================
# Build 270 (profile-aware)
# =========================
with tab_build:
    st.subheader("Build a 270 Request")

    colA, colB, colC = st.columns([1,1,1])
    with colA:
        profile_key = st.selectbox("Payer Profile", options=list(PAYER_PROFILES.keys()), index=0)
        payer_id = st.text_input("Payer ID (PI)", value="12345")
        prov_name = st.text_input("Provider Name", value="Buddha Clinic")
        npi = st.text_input("Provider NPI", value="1234567890")
    with colB:
        subscriber_last = st.text_input("Subscriber Last Name", value="DOE")
        subscriber_first = st.text_input("Subscriber First Name", value="JOHN")
        subscriber_id = st.text_input("Subscriber Member ID", value="W123456789")
        trn_trace = st.text_input("TRN Trace (optional)", value="TRACE12345")
    with colC:
        # Profile’s preferred EQ as default selection
        default_eq = PAYER_PROFILES[profile_key].get("preferred_eq", ["30"])
        service_types = st.multiselect(
            "Service Type Codes (EQ)",
            options=list(ServiceTypeMap.keys()),
            default=default_eq,
            format_func=lambda x: f"{x} – {ServiceTypeMap.get(x,'')}"
        )
        dt_start = st.date_input("Eligibility Start", datetime.today().date())
        ranged = st.checkbox("Use Date Range (RD8)", value=True)
        dt_end = st.date_input("Eligibility End", datetime.today().date() + timedelta(days=30)) if ranged else None

    # Optional dependent
    with st.expander("Dependent (optional)"):
        use_dependent = st.checkbox("Query Dependent?", value=False)
        dep_last = st.text_input("Dependent Last Name", value="") if use_dependent else ""
        dep_first = st.text_input("Dependent First Name", value="") if use_dependent else ""
        dep_id = st.text_input("Dependent ID", value="") if use_dependent else ""

    # Optional DMG (DOB/Gender)
    with st.expander("Subscriber Demographics (DMG)"):
        require_dmg = PAYER_PROFILES[profile_key].get("require_dmg", False)
        dmg_dob = st.text_input("DOB (YYYYMMDD)", value="19800101" if require_dmg else "")
        dmg_gender = st.selectbox("Gender", ["", "M", "F", "U"], index=0 if not require_dmg else 3)

    if st.button("Generate 270"):
        profile = PAYER_PROFILES[profile_key]
        provider = Provider(name=prov_name, npi=npi)
        subscriber = Party(last=subscriber_last, first=subscriber_first, id_code=subscriber_id, id_qual=profile.get("id_qual","MI"))
        dependent = None
        if use_dependent:
            dependent = Party(last=dep_last, first=dep_first, id_code=dep_id, id_qual=profile.get("id_qual","MI"))

        edi270 = build_270(
            isa_ctrl=1, gs_ctrl=1, st_ctrl=1,
            payer_id=payer_id,
            provider=provider,
            subscriber=subscriber,
            dependent=dependent,
            service_types=service_types,
            date_start=dt_start.strftime("%Y%m%d"),
            date_end=dt_end.strftime("%Y%m%d") if ranged and dt_end else None,
            profile=profile,
            trn_trace=trn_trace if profile.get("expect_trn") else None,
            dmg_dob=dmg_dob or None,
            dmg_gender=dmg_gender or None,
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

        # ZIP support (take first file)
        if uploaded.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    names = [n for n in zf.namelist() if not n.endswith("/")]
                    if not names:
                        st.error("ZIP has no files"); st.stop()
                    raw = zf.read(names[0])
            except zipfile.BadZipFile:
                st.error("Uploaded file looks like a ZIP but couldn't be opened.")
                st.stop()

        try:
            content = normalize_punctuation(robust_decode(raw))
        except ValueError as e:
            st.error(str(e)); st.stop()

        parsed = parse_271(content)

        with st.expander("🔎 Debug parser info"):
            dbg = parsed.get("_debug", {})
            st.write({
                "segment_terminator": dbg.get("segment_terminator"),
                "element_separator": dbg.get("element_separator"),
                "segment_count": dbg.get("segment_count"),
                "first_tags": dbg.get("first_tags"),
            })
            st.code(content[:400].replace("\r", "\\r").replace("\n", "\\n\n"))

        if parsed.get("_validation"):
            st.warning("Validation: " + "; ".join(parsed["_validation"]))

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
            st.write("### Quick Summary (heuristic)")
            st.json(normalize_eb_for_reporting(parsed["eb"]))
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
        preview = content[:2000] + ("...\n" if len(content) > 2000 else "")
        st.code(preview, language="plain")

# =========================
# Help & Notes
# =========================
with tab_help:
    st.markdown("""
### Profiles & universality
This app includes a **profile system** so you can tune small differences per payer/clearinghouse:
- preferred `EQ` codes
- whether `DMG` is required
- whether to include `TRN`
- ID qualifiers (`MI`, etc.)
- extra `REF` segments (e.g., `REF*6P`)

Add or edit profiles in `edi_x12.PAYER_PROFILES`.

### EB interpretation
We capture a broad EB shape and provide a **heuristic summary** (Active, Copay, Coinsurance, Deductible).
For production, extend the mapping per payer's companion guide.

### Validation
We include a light ST/SE count check and basic envelope warnings to catch common formatting issues.

### Security
Treat member data as PHI. Store/process securely and use AS2/SFTP for transport in production.
""")
