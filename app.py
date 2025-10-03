import streamlit as st
from datetime import datetime, timedelta
from edi_x12 import (
    Provider, Party, build_270, parse_271, ServiceTypeMap
)

st.set_page_config(page_title="X12 EDI – 270/271", page_icon="??", layout="wide")
st.title("?? X12 EDI – 270/271 Eligibility (MVP)")

tab_build, tab_parse, tab_help = st.tabs(["Build 270", "Parse 271", "Help & Notes"])

# ---------- Build 270 ----------
with tab_build:
    st.subheader("Build a 270 Request")

    col1, col2 = st.columns(2)
    with col1:
        payer_id = st.text_input("Payer ID (PI)", value="12345")
        npi = st.text_input("Provider NPI", value="1234567890")
        prov_name = st.text_input("Provider Name", value="Buddha Clinic")
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

        st.code(edi270, language="plain")
        st.download_button("?? Download 270", data=edi270.encode("utf-8"),
                           file_name=f"270_{subscriber_last}_{datetime.now().strftime('%Y%m%d%H%M')}.x12",
                           mime="text/plain")

# ---------- Parse 271 ----------
with tab_parse:
    st.subheader("Parse a 271 Response")

    uploaded = st.file_uploader("Upload 271 (text/X12)", type=["x12","edi","txt"])
    if uploaded:
        content = uploaded.read().decode("utf-8", errors="ignore")
        parsed = parse_271(content)
        st.write("### Payer")
        st.json(parsed.get("payer", {}))
        st.write("### Provider")
        st.json(parsed.get("provider", {}))
        st.write("### Subscriber")
        st.json(parsed.get("subscriber", {}))
        if parsed.get("dependent", {}):
            st.write("### Dependent")
            st.json(parsed.get("dependent", {}))

        st.write("### Benefit (EB) Segments")
        if parsed["eb"]:
            st.dataframe(parsed["eb"], use_container_width=True)
        else:
            st.info("No EB segments found. Check AAA segments or payer’s companion guide requirements.")

        if parsed["aaa"]:
            st.write("### Rejections (AAA)")
            st.dataframe(parsed["aaa"], use_container_width=True)

        st.write("### Raw 271")
        st.code(content[:2000] + ("...\n" if len(content) > 2000 else ""), language="plain")

# ---------- Help ----------
with tab_help:
    st.markdown("""
### Notes & Next Steps
- If a payer returns **no EB**, they may need different `EQ` (commonly `30`) or additional REF/NM1 values.
- Control numbers (`ISA13`, `GS06`, `ST02`) must be unique per interchange; persist counters in a DB and **rollover safely** at their max.
- Add **TRN** and **REF** per trading partner’s guide, plus real demographics `DMG` (DOB/Gender).
- For production:
  - Store PHI only in secure DB (Postgres/Supabase/Neon). Encrypt at rest, restrict access.
  - Transport via **AS2** or secure **SFTP** to clearinghouse/payer. Consider managed AS2 (Kiteworks, Axway, AWS Transfer + partner).
  - Keep **message tracking**: Request ID, time, control nums, payer, status, file hashes.
- Testing:
  - Use payer/clearinghouse test endpoints and sample files from their companion guides.
  - Validate segment counts (SE01), envelopes (IEA/GE totals).
""")
