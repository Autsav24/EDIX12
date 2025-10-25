# claim_status_app.py
import streamlit as st
from datetime import datetime
import pandas as pd
from io import BytesIO

st.set_page_config(page_title="X12 276 / 277 Claim Status Portal", page_icon="📬", layout="wide")
st.title("📬 X12 EDI – Claim Status Inquiry (276) & Response (277)")

# ---------------- Helper functions ----------------
def build_276(isa_ctrl, gs_ctrl, st_ctrl, payer_id, provider_name, provider_npi,
              subscriber_last, subscriber_first, subscriber_id,
              claim_control_number="", date_of_service=None):
    """Builds a simple 276 Claim Status Inquiry"""
    now = datetime.now()
    dos = date_of_service or now.strftime("%Y%m%d")

    edi = ""
    edi += f"ISA*00*          *00*          *ZZ*SENDERID       *ZZ*RECEIVERID     *{now.strftime('%y%m%d')}*{now.strftime('%H%M')}*^*00501*{isa_ctrl:09d}*0*T*:~\n"
    edi += f"GS*HN*SENDER*RECEIVER*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*{gs_ctrl}*X*005010X212~\n"
    edi += f"ST*276*{st_ctrl}*005010X212~\n"
    edi += f"BHT*0010*13*{claim_control_number or st_ctrl}*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}~\n"
    edi += "HL*1**20*1~\n"
    edi += f"NM1*PR*2*PAYER NAME****PI*{payer_id}~\n"
    edi += "HL*2*1*21*1~\n"
    edi += f"NM1*41*2*{provider_name}*****XX*{provider_npi}~\n"
    edi += "HL*3*2*19*0~\n"
    edi += f"NM1*IL*1*{subscriber_last}*{subscriber_first}****MI*{subscriber_id}~\n"
    edi += f"DTP*472*D8*{dos}~\n"
    edi += f"SE*12*{st_ctrl}~\n"
    edi += f"GE*1*{gs_ctrl}~\n"
    edi += f"IEA*1*{isa_ctrl:09d}~"
    return edi


def parse_277(edi_text: str):
    """Parse 277 file and return structured DataFrame"""
    seg_t = "~"
    if edi_text.count("~") < 2 and edi_text.count("\n") >= 2:
        seg_t = "\n"

    lines = [l.strip() for l in edi_text.replace("\r\n", "\n").split(seg_t) if l.strip()]
    rows = []
    current = {}

    for line in lines:
        parts = line.split("*")
        tag = parts[0].upper()

        if tag == "TRN":
            current.setdefault("TraceNumber", parts[2] if len(parts) > 2 else "")
        elif tag == "CLP":
            if current:
                rows.append(current)
            current = {
                "ClaimID": parts[1] if len(parts) > 1 else "",
                "ClaimStatus": parts[2] if len(parts) > 2 else "",
                "TotalCharge": parts[3] if len(parts) > 3 else "",
                "TotalPaid": parts[4] if len(parts) > 4 else ""
            }
        elif tag == "STC":
            current["StatusComposite"] = parts[1] if len(parts) > 1 else ""
            current["StatusDate"] = parts[2] if len(parts) > 2 else ""
        elif tag == "NM1" and len(parts) > 1 and parts[1] == "QC":
            current["PatientLast"] = parts[3] if len(parts) > 3 else ""
            current["PatientFirst"] = parts[4] if len(parts) > 4 else ""
        elif tag == "DTP":
            current.setdefault("Dates", []).append(parts[1:])

    if current:
        rows.append(current)

    df = pd.DataFrame(rows)
    return df


# ---------------- Tabs ----------------
tab1, tab2 = st.tabs(["📨 Build 276", "📬 Parse 277"])

# ---------- 276 ----------
with tab1:
    st.subheader("📨 Build 276 – Claim Status Inquiry")
    payer_id = st.text_input("Payer ID (PI)", "12345", key="276_payer")
    provider_name = st.text_input("Provider Name", "Buddha Clinic", key="276_prov")
    provider_npi = st.text_input("Provider NPI", "1234567890", key="276_npi")
    subscriber_last = st.text_input("Subscriber Last Name", "DOE", key="276_sub_last")
    subscriber_first = st.text_input("Subscriber First Name", "JOHN", key="276_sub_first")
    subscriber_id = st.text_input("Subscriber ID", "W123456789", key="276_sub_id")
    claim_ctrl = st.text_input("Claim Control Number (optional)", "", key="276_claim_ctrl")
    dos = st.text_input("Date of Service (YYYYMMDD)", datetime.today().strftime("%Y%m%d"), key="276_dos")

    if st.button("Generate 276", key="276_gen_btn"):
        edi276 = build_276(1, 1, 1000, payer_id, provider_name, provider_npi,
                           subscriber_last, subscriber_first, subscriber_id,
                           claim_ctrl, dos)
        st.code(edi276, language="plain")
        st.download_button("⬇️ Download 276 File", data=edi276.encode("utf-8"),
                           file_name="276_request.x12", key="276_download")

# ---------- 277 ----------
with tab2:
    st.subheader("📬 Parse 277 – Claim Status Response")
    uploaded = st.file_uploader("Upload 277 File (.x12 / .edi / .txt)", type=["x12", "edi", "txt"], key="277_upload")
    if uploaded:
        content = uploaded.read().decode("utf-8", errors="ignore")
        df = parse_277(content)

        if df.empty:
            st.warning("No claim status data found in this file.")
        else:
            st.success(f"Parsed {len(df)} claim records.")
            st.dataframe(df, use_container_width=True)

            # Export to Excel
            out = BytesIO()
            with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="277_Parsed")
                worksheet = writer.sheets["277_Parsed"]
                for i, col in enumerate(df.columns):
                    worksheet.set_column(i, i, min(30, max(10, len(str(col)) + 5)))
            out.seek(0)

            st.download_button("⬇️ Download Excel", data=out,
                               file_name=f"277_parsed_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key="277_excel_dl")
