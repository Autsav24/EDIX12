import streamlit as st
from datetime import datetime, timedelta
from edi_x12 import Provider, Party, build_270, parse_271, ServiceTypeMap, normalize_eb_for_reporting

st.set_page_config(page_title="X12 270/271 Generator", page_icon="📡", layout="wide")
st.title("📡 X12 EDI 270 / 271 Utility")

tab_build, tab_parse = st.tabs(["Build 270", "Parse 271"])

# ---------------- Build 270 ----------------
with tab_build:
    st.subheader("Build a 270 Eligibility Request")

    payer_id = st.text_input("Payer ID (PI)", value="12345")
    prov_name = st.text_input("Provider Name", value="Buddha Clinic")
    npi = st.text_input("Provider NPI", value="1234567890")
    subscriber_last = st.text_input("Subscriber Last Name", value="DOE")
    subscriber_first = st.text_input("Subscriber First Name", value="JOHN")
    subscriber_id = st.text_input("Subscriber Member ID", value="W123456789")
    dmg_dob = st.text_input("Subscriber DOB (YYYYMMDD)", value="19800101")
    dmg_gender = st.selectbox("Subscriber Gender", ["", "M", "F"], index=1)

    service_types = st.multiselect(
        "Service Type Codes (EQ)",
        options=list(ServiceTypeMap.keys()),
        default=["30"],
        format_func=lambda x: f"{x} – {ServiceTypeMap.get(x,'')}"
    )

    dt_start = st.date_input("Eligibility Start", datetime.today().date())
    ranged = st.checkbox("Use Date Range (RD8)", value=False)
    dt_end = st.date_input("Eligibility End", datetime.today().date() + timedelta(days=30)) if ranged else None

    if st.button("Generate 270"):
        provider = Provider(name=prov_name, npi=npi)
        subscriber = Party(last=subscriber_last, first=subscriber_first, id_code=subscriber_id)

        edi270 = build_270(
            isa_ctrl=1,
            gs_ctrl=1,
            st_ctrl=1000,
            payer_id=payer_id,
            provider=provider,
            subscriber=subscriber,
            dependent=None,
            service_types=service_types,
            date_start=dt_start.strftime("%Y%m%d"),
            date_end=dt_end.strftime("%Y%m%d") if ranged and dt_end else None,
            dmg_dob=dmg_dob or None,
            dmg_gender=dmg_gender or None
        )

        st.write("### Generated 270 EDI File")
        st.code(edi270, language="plain")
        st.download_button(
            "⬇️ Download 270",
            data=edi270.encode("utf-8"),
            file_name=f"270_{subscriber_last}_{datetime.now().strftime('%Y%m%d%H%M')}.x12",
            mime="text/plain",
        )

# ---------------- Parse 271 ----------------
with tab_parse:
    st.subheader("Parse a 271 Response")

    uploaded = st.file_uploader("Upload 271 (X12/Text)", type=["x12", "edi", "txt"])
    if uploaded:
        content = uploaded.read().decode("utf-8", errors="ignore")
        parsed = parse_271(content)
        st.write("### Parsed Segments")
        st.json(parsed)
        st.write("### Validation")
        st.write(parsed.get("_validation", []))
        st.write("### Raw Preview")
        st.code(content[:2000])
