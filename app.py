import streamlit as st
from datetime import datetime, timedelta
from io import BytesIO
import pandas as pd
from edi_x12 import Provider, Party, build_270, parse_271, ServiceTypeMap, normalize_eb_for_reporting

# ================== APP CONFIG ==================
st.set_page_config(page_title="X12 EDI Generator (270/271/835/837)", page_icon="📡", layout="wide")
st.title("📡 X12 EDI Utility – 270 / 271 / 835 / 837")

# ================== 835 BUILDER ==================
def build_835(
    isa_ctrl:int,
    gs_ctrl:int,
    st_ctrl:int,
    payer_name:str,
    payer_id:str,
    provider_npi:str,
    claim_id:str,
    patient_name:str,
    paid_amount:str,
    check_number:str,
    payment_date:str
):
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

# ================== 837 BUILDER ==================
def build_837(
    isa_ctrl:int,
    gs_ctrl:int,
    st_ctrl:int,
    sender_id:str,
    receiver_id:str,
    billing_provider_npi:str,
    patient_name:str,
    patient_id:str,
    claim_id:str,
    claim_amount:str,
    dos_start:str,
    dos_end:str=None
):
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
    edi += f"NM1*85*2*BUDDHA CLINIC*****XX*{billing_provider_npi}~\n"
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


# ================== MAIN TABS ==================
tab_270, tab_271, tab_837, tab_835 = st.tabs(["270", "271", "837", "835"])

# ================== 270 BUILDER ==================
with tab_270:
    st.subheader("🩺 Build 270 – Eligibility Inquiry")

    payer_id = st.text_input("Payer ID (PI)", value="12345", key="payer_270")
    prov_name = st.text_input("Provider Name", value="Buddha Clinic", key="prov_270")
    npi = st.text_input("Provider NPI", value="1234567890", key="npi_270")
    subscriber_last = st.text_input("Subscriber Last Name", value="DOE", key="sub_last_270")
    subscriber_first = st.text_input("Subscriber First Name", value="JOHN", key="sub_first_270")
    subscriber_id = st.text_input("Subscriber Member ID", value="W123456789", key="sub_id_270")
    dmg_dob = st.text_input("Subscriber DOB (YYYYMMDD)", value="19800101", key="dob_270")
    dmg_gender = st.selectbox("Subscriber Gender", ["", "M", "F"], index=1, key="gender_270")

    service_types = st.multiselect(
        "Service Type Codes (EQ)",
        options=list(ServiceTypeMap.keys()),
        default=["30"],
        format_func=lambda x: f"{x} – {ServiceTypeMap.get(x, '')}",
        key="servtype_270"
    )

    dt_start = st.date_input("Eligibility Start", datetime.today().date(), key="start_270")
    ranged = st.checkbox("Use Date Range (RD8)", value=False, key="range_270")
    dt_end = st.date_input("Eligibility End", datetime.today().date() + timedelta(days=30), key="end_270") if ranged else None

    if st.button("Generate 270", key="btn_270"):
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
        st.download_button("⬇️ Download 270", data=edi270.encode("utf-8"), file_name="270.x12", mime="text/plain", key="download_270")

# ================== 271 PARSER ==================
with tab_271:
    st.subheader("📄 Parse 271 Response")
    uploaded = st.file_uploader("Upload 271 (X12/Text)", type=["x12", "edi", "txt"], key="upload_271")
    if uploaded:
        content = uploaded.read().decode("utf-8", errors="ignore")
        parsed = parse_271(content)
        st.json(parsed)
        st.write(parsed.get("_validation", []))
        st.code(content[:2000])

# ================== 837 BUILDER ==================
with tab_837:
    st.subheader("📄 Build 837 – Professional Claim (837P)")
    sender = st.text_input("Sender ID", "SENDERID", key="sender_837")
    receiver = st.text_input("Receiver ID", "RECEIVERID", key="receiver_837")
    provider_npi = st.text_input("Billing Provider NPI", "1234567890", key="npi_837")
    patient_name = st.text_input("Patient Name", "John Doe", key="pname_837")
    patient_id = st.text_input("Patient ID", "W123456789", key="pid_837")
    claim_id = st.text_input("Claim ID", "CLM1001", key="claim_837")
    claim_amount = st.text_input("Claim Amount", "150", key="amt_837")
    dos_start = st.text_input("Date of Service Start (YYYYMMDD)", "20251025", key="dosstart_837")
    dos_end = st.text_input("Date of Service End (YYYYMMDD)", "", key="dosend_837")

    if st.button("Generate 837", key="btn_837"):
        edi837 = build_837(1, 1, 1000, sender, receiver, provider_npi, patient_name, patient_id, claim_id, claim_amount, dos_start, dos_end or None)
        st.write("### Generated 837 EDI File")
        st.code(edi837, language="plain")
        st.download_button("⬇️ Download 837", data=edi837.encode("utf-8"), file_name="837.x12", mime="text/plain", key="download_837")

# ================== 835 BUILDER WITH EXCEL ==================
with tab_835:
    st.subheader("💰 Build 835 – Remittance Advice")
    payer = st.text_input("Payer Name", "Insurance Co", key="payer_835")
    payer_id = st.text_input("Payer ID", "12345", key="payerid_835")
    provider_npi = st.text_input("Provider NPI", "1234567890", key="npi_835")
    claim = st.text_input("Claim ID", "CLM1001", key="claim_835")
    patient = st.text_input("Patient Name", "John Doe", key="patient_835")
    paid = st.text_input("Paid Amount", "150", key="paid_835")
    chk = st.text_input("Check Number", "CHK12345", key="chk_835")
    pdate = st.text_input("Payment Date (YYYYMMDD)", datetime.today().strftime("%Y%m%d"), key="pdate_835")

    if st.button("Generate 835", key="btn_835"):
        edi835 = build_835(1, 1, 1000, payer, payer_id, provider_npi, claim, patient, paid, chk, pdate)
        st.write("### Generated 835 EDI File")
        st.code(edi835, language="plain")

        # Download EDI file
        st.download_button(
            "⬇️ Download 835 EDI",
            data=edi835.encode("utf-8"),
            file_name=f"835_{claim}.x12",
            mime="text/plain",
            key="download_835_edi"
        )

        # Create Excel summary
        data = [{
            "Payer Name": payer,
            "Payer ID": payer_id,
            "Provider NPI": provider_npi,
            "Claim ID": claim,
            "Patient Name": patient,
            "Paid Amount": paid,
            "Check Number": chk,
            "Payment Date": pdate,
            "Generated On": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }]
        df = pd.DataFrame(data)

        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="835 Summary")
            worksheet = writer.sheets["835 Summary"]
            for i, col in enumerate(df.columns):
                worksheet.set_column(i, i, 20)
        output.seek(0)

        # Excel download
        st.download_button(
            "⬇️ Download Excel Summary",
            data=output,
            file_name=f"835_{claim}_summary.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="download_835_excel"
        )

        st.success("✅ 835 EDI and Excel Summary generated successfully!")
