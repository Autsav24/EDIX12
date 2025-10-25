import streamlit as st
from datetime import datetime, timedelta
from io import BytesIO
import pandas as pd
from edi_x12 import Provider, Party, build_270, parse_271, ServiceTypeMap, normalize_eb_for_reporting

# ================== CONFIG ==================
st.set_page_config(page_title="X12 EDI Portal", page_icon="📡", layout="wide")
st.title("📡 X12 EDI Utility – 270 / 271 / 835 / 837")

# ================== BUILD 835 ==================
def build_835(isa_ctrl, gs_ctrl, st_ctrl, payer_name, payer_id, provider_npi, claim_id, patient_name, paid_amount, check_number, payment_date):
    now = datetime.now()
    edi = ""
    edi += f"ISA*00*          *00*          *ZZ*{payer_id:<15}*ZZ*RECEIVERID     *{now.strftime('%y%m%d')}*{now.strftime('%H%M')}*^*00501*{isa_ctrl:09d}*0*T*:~\n"
    edi += f"GS*HP*{payer_id}*RECEIVER*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*{gs_ctrl}*X*005010X221A1~\n"
    edi += f"ST*835*{st_ctrl}*005010X221A1~\n"
    edi += f"BPR*I*{paid_amount}*C*CHK*01*999999999*DA*123456789*{now.strftime('%Y%m%d')}~\n"
    edi += f"TRN*1*{check_number}*{payer_id}~\n"
    edi += f"DTM*405*{payment_date}~\n"
    edi += f"N1*PR*{payer_name}*PI*{payer_id}~\n"
    edi += f"N1*PE*BUDDHA CLINIC*XX*{provider_npi}~\n"
    edi += f"CLP*{claim_id}*1*150*{paid_amount}**MC*{patient_name}*12*1~\n"
    edi += "CAS*CO*45*50~\n"
    edi += f"NM1*QC*1*{patient_name}****MI*123456789~\n"
    edi += f"DTM*232*{payment_date}~\n"
    edi += f"DTM*233*{payment_date}~\n"
    edi += f"SE*12*{st_ctrl}~\n"
    edi += f"GE*1*{gs_ctrl}~\n"
    edi += f"IEA*1*{isa_ctrl:09d}~"
    return edi

# ================== BUILD 837 ==================
def build_837(isa_ctrl, gs_ctrl, st_ctrl, sender_id, receiver_id, provider_npi, patient_name, patient_id, claim_id, claim_amount, dos_start, dos_end=None):
    now = datetime.now()
    dos_segment = f"DTP*472*D8*{dos_start}~" if not dos_end else f"DTP*472*RD8*{dos_start}-{dos_end}~"
    edi = ""
    edi += f"ISA*00*          *00*          *ZZ*{sender_id:<15}*ZZ*{receiver_id:<15}*{now.strftime('%y%m%d')}*{now.strftime('%H%M')}*^*00501*{isa_ctrl:09d}*0*T*:~\n"
    edi += f"GS*HC*{sender_id}*{receiver_id}*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*{gs_ctrl}*X*005010X222A1~\n"
    edi += f"ST*837*{st_ctrl}*005010X222A1~\n"
    edi += f"BHT*0019*00*{claim_id}*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*CH~\n"
    edi += "NM1*41*2*BUDDHA CLINIC*****46*12345~\n"
    edi += "PER*IC*BILLING OFFICE*TE*8005551212~\n"
    edi += "NM1*40*2*PAYER NAME*****46*99999~\n"
    edi += "HL*1**20*1~\n"
    edi += f"NM1*85*2*BUDDHA CLINIC*****XX*{provider_npi}~\n"
    edi += "N3*123 MAIN STREET~\nN4*LUCKNOW*UP*226001~\n"
    edi += "REF*EI*123456789~\n"
    edi += "HL*2*1*22*0~\n"
    edi += f"NM1*IL*1*{patient_name}****MI*{patient_id}~\n"
    edi += dos_segment + "\n"
    edi += f"CLM*{claim_id}*{claim_amount}***11:B:1*Y*A*Y*I~\n"
    edi += "HI*BK:12345~\n"
    edi += "LX*1~\n"
    edi += "SV1*HC:99213*100*UN*1***1~\n"
    edi += f"SE*20*{st_ctrl}~\n"
    edi += f"GE*1*{gs_ctrl}~\n"
    edi += f"IEA*1*{isa_ctrl:09d}~"
    return edi

# ================== TABS ==================
tab_270, tab_271, tab_837, tab_835 = st.tabs(["270", "271", "837", "835"])

# ================== 270 ==================
with tab_270:
    st.subheader("🩺 Build 270 – Eligibility Inquiry")
    payer_id = st.text_input("Payer ID (PI)", "12345")
    prov_name = st.text_input("Provider Name", "Buddha Clinic")
    npi = st.text_input("Provider NPI", "1234567890")
    subscriber_last = st.text_input("Subscriber Last Name", "DOE")
    subscriber_first = st.text_input("Subscriber First Name", "JOHN")
    subscriber_id = st.text_input("Subscriber Member ID", "W123456789")
    dmg_dob = st.text_input("Subscriber DOB (YYYYMMDD)", "19800101")
    dmg_gender = st.selectbox("Gender", ["", "M", "F"], index=1)
    dt_start = st.date_input("Eligibility Start", datetime.today().date())
    dt_end = st.date_input("Eligibility End", datetime.today().date() + timedelta(days=30))

    if st.button("Generate 270"):
        provider = Provider(name=prov_name, npi=npi)
        subscriber = Party(last=subscriber_last, first=subscriber_first, id_code=subscriber_id)
        edi270 = build_270(1, 1, 1000, payer_id, provider, subscriber, None, ["30"], dt_start.strftime("%Y%m%d"), dt_end.strftime("%Y%m%d"), dmg_dob, dmg_gender)
        st.code(edi270, language="plain")
        st.download_button("⬇️ Download 270", edi270.encode("utf-8"), "270.x12")

# ================== 271 ==================
with tab_271:
    st.subheader("📄 Parse 271 Response")
    uploaded = st.file_uploader("Upload 271", type=["x12", "edi", "txt"])
    if uploaded:
        content = uploaded.read().decode("utf-8", errors="ignore")
        parsed = parse_271(content)
        st.json(parsed)
        st.download_button("⬇️ Download JSON", pd.DataFrame(parsed["eb"]).to_csv(index=False).encode(), "271_eb.csv")

# ================== 837 ==================
with tab_837:
    st.subheader("📤 Build 837 – Professional Claim")
    sender = st.text_input("Sender ID", "SENDERID")
    receiver = st.text_input("Receiver ID", "RECEIVERID")
    provider_npi = st.text_input("Provider NPI", "1234567890")
    patient = st.text_input("Patient Name", "John Doe")
    pid = st.text_input("Patient ID", "W123456789")
    claim = st.text_input("Claim ID", "CLM1001")
    amt = st.text_input("Claim Amount", "150")
    dos_start = st.text_input("DOS Start (YYYYMMDD)", "20251025")
    dos_end = st.text_input("DOS End (YYYYMMDD)", "")

    if st.button("Generate 837"):
        edi837 = build_837(1, 1, 1000, sender, receiver, provider_npi, patient, pid, claim, amt, dos_start, dos_end or None)
        st.code(edi837, language="plain")
        st.download_button("⬇️ Download 837", edi837.encode("utf-8"), "837.x12")

# ================== 835 ==================
with tab_835:
    st.subheader("💰 Build 835 – Remittance Advice")
    payer = st.text_input("Payer Name", "Insurance Co")
    payer_id = st.text_input("Payer ID", "12345")
    provider_npi = st.text_input("Provider NPI", "1234567890")
    claim = st.text_input("Claim ID", "CLM1001")
    patient = st.text_input("Patient Name", "John Doe")
    paid = st.text_input("Paid Amount", "150")
    chk = st.text_input("Check Number", "CHK12345")
    pdate = st.text_input("Payment Date (YYYYMMDD)", datetime.today().strftime("%Y%m%d"))

    if st.button("Generate 835"):
        edi835 = build_835(1, 1, 1000, payer, payer_id, provider_npi, claim, patient, paid, chk, pdate)
        st.code(edi835, language="plain")
        st.download_button("⬇️ Download 835", edi835.encode("utf-8"), "835.x12")

    # 835 Parser
    with st.expander("📤 Parse Existing 835 File to Excel"):
        uploaded_835 = st.file_uploader("Upload 835 (EDI/Text)", type=["835", "edi", "txt"])
        if uploaded_835:
            raw = uploaded_835.read().decode("utf-8", errors="ignore")
            lines = [seg.strip() for seg in raw.replace("~", "\n").splitlines() if seg.strip()]
            payer, payee, check_info, claims = {}, {}, {}, []
            current_claim = None

            for line in lines:
                parts = line.split("*")
                tag = parts[0].upper()
                if tag == "BPR":
                    check_info["PaymentAmount"] = parts[2] if len(parts) > 2 else ""
                    check_info["PaymentDate"] = parts[-1] if len(parts) > 10 else ""
                elif tag == "TRN":
                    check_info["CheckNumber"] = parts[2] if len(parts) > 2 else ""
                elif tag == "N1":
                    if len(parts) > 1 and parts[1] == "PR":
                        payer["PayerName"] = parts[2]
                        payer["PayerID"] = parts[-1]
                    elif len(parts) > 1 and parts[1] == "PE":
                        payee["PayeeName"] = parts[2]
                        payee["NPI"] = parts[-1]
                elif tag == "CLP":
                    if current_claim:
                        claims.append(current_claim)
                    current_claim = {"ClaimID": parts[1], "TotalCharge": parts[3], "TotalPaid": parts[4]}
                elif tag == "NM1" and len(parts) > 1 and parts[1] == "QC" and current_claim is not None:
                    current_claim["PatientName"] = parts[3]
                elif tag == "CAS" and current_claim is not None:
                    current_claim["AdjustmentCode"] = parts[2]
                    current_claim["AdjustmentAmt"] = parts[3]

            if current_claim:
                claims.append(current_claim)

            if not claims:
                st.warning("No CLP segments found.")
                st.stop()

            df = pd.DataFrame(claims)
            df["PayerName"] = payer.get("PayerName", "")
            df["PayeeName"] = payee.get("PayeeName", "")
            df["CheckNumber"] = check_info.get("CheckNumber", "")
            df["PaymentDate"] = check_info.get("PaymentDate", "")
            df["PaymentAmount"] = check_info.get("PaymentAmount", "")
            st.dataframe(df, use_container_width=True)

            output = BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df.to_excel(writer, index=False, sheet_name="835_Claims")
            output.seek(0)

            st.download_button("⬇️ Download Excel", data=output, file_name="835_summary.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
