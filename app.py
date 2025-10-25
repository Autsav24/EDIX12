# app.py
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO
from edi_x12 import Provider, Party, build_270, parse_271

st.set_page_config(page_title="X12 EDI Suite - 270/271/276/277/835/837", page_icon="📡", layout="wide")
st.title("📡 X12 EDI Transaction Suite")

# ---------------------------------------------------------------------
# Helper: 276 / 277 Builders and Parsers
# ---------------------------------------------------------------------
def build_276(isa_ctrl, gs_ctrl, st_ctrl, payer_id, provider_name, provider_npi,
              subscriber_last, subscriber_first, subscriber_id,
              claim_control_number="", date_of_service=None):
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
    seg_t = "~"
    if edi_text.count("~") < 2 and edi_text.count("\n") >= 2:
        seg_t = "\n"
    lines = [l.strip() for l in edi_text.replace("\r\n", "\n").split(seg_t) if l.strip()]
    rows, current = [], {}
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
    return pd.DataFrame(rows)

# ---------------------------------------------------------------------
# Helper: 837 & 835 (short versions)
# ---------------------------------------------------------------------
def build_837(payer_id, provider_npi, patient_name, patient_id, claim_id, amount):
    now = datetime.now()
    edi = f"""ISA*00**00**ZZ*SENDER*ZZ*RECEIVER*{now:%y%m%d}*{now:%H%M}*^*00501*000000001*0*T*:~
GS*HC*SENDER*RECEIVER*{now:%Y%m%d}*{now:%H%M}*1*X*005010X222A1~
ST*837*0001*005010X222A1~
BHT*0019*00*{claim_id}*{now:%Y%m%d}*{now:%H%M}*CH~
NM1*85*2*BUDDHA CLINIC*****XX*{provider_npi}~
HL*1**20*1~
NM1*IL*1*{patient_name}****MI*{patient_id}~
CLM*{claim_id}*{amount}***11:B:1*Y*A*Y*I~
SE*12*0001~
GE*1*1~
IEA*1*000000001~"""
    return edi

def build_835(payer_name, payer_id, provider_npi, claim_id, patient_name, paid_amount):
    now = datetime.now()
    edi = f"""ISA*00**00**ZZ*{payer_id:<15}*ZZ*RECEIVER*{now:%y%m%d}*{now:%H%M}*^*00501*000000001*0*T*:~
GS*HP*{payer_id}*RECEIVER*{now:%Y%m%d}*{now:%H%M}*1*X*005010X221A1~
ST*835*0001*005010X221A1~
BPR*I*{paid_amount}*C*CHK*01*999999999*DA*123456789*{now:%Y%m%d}~
N1*PR*{payer_name}*PI*{payer_id}~
N1*PE*BUDDHA CLINIC*XX*{provider_npi}~
CLP*{claim_id}*1*150*{paid_amount}**MC*{patient_name}*12*1~
SE*12*0001~
GE*1*1~
IEA*1*000000001~"""
    return edi

# ---------------------------------------------------------------------
# TABS
# ---------------------------------------------------------------------
tabs = st.tabs(["270", "271", "276", "277", "837", "835"])

# ---------------- 270 ----------------
with tabs[0]:
    st.header("🩺 270 – Eligibility Inquiry")
    payer_id = st.text_input("Payer ID", "12345", key="270_payer")
    prov = st.text_input("Provider Name", "Buddha Clinic", key="270_prov")
    npi = st.text_input("Provider NPI", "1234567890", key="270_npi")
    sub_last = st.text_input("Subscriber Last Name", "DOE", key="270_last")
    sub_first = st.text_input("Subscriber First Name", "JOHN", key="270_first")
    sub_id = st.text_input("Subscriber ID", "W123456789", key="270_id")
    dob = st.text_input("DOB (YYYYMMDD)", "19800101", key="270_dob")
    gender = st.selectbox("Gender", ["", "M", "F"], key="270_gender")
    date = st.date_input("Date of Service", datetime.today(), key="270_date")

    if st.button("Generate 270", key="270_btn"):
        provider = Provider(name=prov, npi=npi)
        subscriber = Party(last=sub_last, first=sub_first, id_code=sub_id)
        edi = build_270(1, 1, 1000, payer_id, provider, subscriber, None, ["30"], date.strftime("%Y%m%d"),
                        None, dmg_dob=dob, dmg_gender=gender)
        st.code(edi, language="plain")
        st.download_button("⬇️ Download 270", data=edi.encode(), file_name="270_request.x12", key="270_dl")

# ---------------- 271 ----------------
with tabs[1]:
    st.header("📄 271 – Parse Eligibility Response")
    file = st.file_uploader("Upload 271 File", type=["x12", "edi", "txt"], key="271_file")
    if file:
        text = file.read().decode("utf-8", errors="ignore")
        result = parse_271(text)
        st.json(result)
        if "eb" in result and result["eb"]:
            df = pd.DataFrame(result["eb"])
            st.dataframe(df, use_container_width=True)

# ---------------- 276 ----------------
with tabs[2]:
    st.header("📨 276 – Claim Status Inquiry")
    payer_id = st.text_input("Payer ID", "12345", key="276_payer")
    prov_name = st.text_input("Provider Name", "Buddha Clinic", key="276_prov")
    prov_npi = st.text_input("Provider NPI", "1234567890", key="276_npi")
    sub_last = st.text_input("Subscriber Last", "DOE", key="276_last")
    sub_first = st.text_input("Subscriber First", "JOHN", key="276_first")
    sub_id = st.text_input("Subscriber ID", "W123456789", key="276_subid")
    claim_ctrl = st.text_input("Claim Control Number", "", key="276_claim")
    dos = st.text_input("Date of Service (YYYYMMDD)", datetime.today().strftime("%Y%m%d"), key="276_dos")

    if st.button("Generate 276", key="276_btn"):
        edi276 = build_276(1, 1, 1000, payer_id, prov_name, prov_npi, sub_last, sub_first, sub_id, claim_ctrl, dos)
        st.code(edi276, language="plain")
        st.download_button("⬇️ Download 276", data=edi276.encode(), file_name="276_request.x12", key="276_dl")

# ---------------- 277 ----------------
with tabs[3]:
    st.header("📬 277 – Parse Claim Status Response")
    file = st.file_uploader("Upload 277 File", type=["x12", "edi", "txt"], key="277_file")
    if file:
        text = file.read().decode("utf-8", errors="ignore")
        df = parse_277(text)
        if df.empty:
            st.warning("No claims found in file.")
        else:
            st.dataframe(df, use_container_width=True)
            out = BytesIO()
            with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="277_Parsed")
            out.seek(0)
            st.download_button("⬇️ Download 277 Excel", out, file_name="277_parsed.xlsx",
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key="277_dl")

# ---------------- 837 ----------------
with tabs[4]:
    st.header("📤 837 – Professional Claim")
    payer_id = st.text_input("Payer ID", "12345", key="837_payer")
    npi = st.text_input("Provider NPI", "1234567890", key="837_npi")
    patient = st.text_input("Patient Name", "John Doe", key="837_patient")
    pid = st.text_input("Patient ID", "W123456789", key="837_pid")
    claim = st.text_input("Claim ID", "CLM1001", key="837_claim")
    amt = st.text_input("Amount", "150", key="837_amt")

    if st.button("Generate 837", key="837_btn"):
        edi837 = build_837(payer_id, npi, patient, pid, claim, amt)
        st.code(edi837, language="plain")
        st.download_button("⬇️ Download 837", data=edi837.encode(), file_name="837_claim.x12", key="837_dl")

# ---------------- 835 ----------------
with tabs[5]:
    st.header("💰 835 – Payment / Remittance")
    payer_name = st.text_input("Payer Name", "Insurance Co", key="835_payer")
    payer_id = st.text_input("Payer ID", "12345", key="835_pid")
    prov_npi = st.text_input("Provider NPI", "1234567890", key="835_npi")
    claim = st.text_input("Claim ID", "CLM1001", key="835_claim")
    patient = st.text_input("Patient Name", "John Doe", key="835_patient")
    amt = st.text_input("Paid Amount", "150", key="835_amt")

    if st.button("Generate 835", key="835_btn"):
        edi835 = build_835(payer_name, payer_id, prov_npi, claim, patient, amt)
        st.code(edi835, language="plain")
        st.download_button("⬇️ Download 835", data=edi835.encode(), file_name="835_remit.x12", key="835_dl")

st.caption("© 2025 Buddha Clinic EDI Suite")
