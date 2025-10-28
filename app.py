import io, os, json, zipfile
import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from io import BytesIO
import importlib
import edi_x12
importlib.reload(edi_x12)
from edi_x12 import (
    Provider, Party, build_270, parse_271,
    ServiceTypeMap, PAYER_PROFILES, normalize_eb_for_reporting
)

# ======================================================
# Streamlit Config
# ======================================================
st.set_page_config(
    page_title="X12 EDI Suite - 270/271/276/277/837/835",
    page_icon="📡", layout="wide"
)
st.title("📡 X12 EDI Transaction Suite")

# ======================================================
# Profile Management
# ======================================================
PROFILES_FILE = "profiles.json"

def load_profiles() -> dict:
    base = {k: v.copy() for k, v in PAYER_PROFILES.items()}
    if os.path.exists(PROFILES_FILE):
        try:
            with open(PROFILES_FILE, "r", encoding="utf-8") as f:
                user = json.load(f)
            for k, v in user.items():
                base[k] = v
        except Exception:
            pass
    return base

def save_profiles(profiles: dict) -> None:
    with open(PROFILES_FILE, "w", encoding="utf-8") as f:
        json.dump(profiles, f, indent=2, ensure_ascii=False)

if "profiles" not in st.session_state:
    st.session_state.profiles = load_profiles()

# ======================================================
# Helper Functions
# ======================================================
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

# ======================================================
# Additional Transaction Builders & Parsers
# ======================================================
def build_276(isa_ctrl, gs_ctrl, st_ctrl, payer_id, provider_name, provider_npi,
              subscriber_last, subscriber_first, subscriber_id,
              claim_control_number="", date_of_service=None):
    now = datetime.now()
    dos = date_of_service or now.strftime("%Y%m%d")
    edi = (
        f"ISA*00*          *00*          *ZZ*SENDERID       *ZZ*RECEIVERID     *{now:%y%m%d}*{now:%H%M}*^*00501*{isa_ctrl:09d}*0*T*:~\n"
        f"GS*HN*SENDER*RECEIVER*{now:%Y%m%d}*{now:%H%M}*{gs_ctrl}*X*005010X212~\n"
        f"ST*276*{st_ctrl}*005010X212~\n"
        f"BHT*0010*13*{claim_control_number or st_ctrl}*{now:%Y%m%d}*{now:%H%M}~\n"
        f"HL*1**20*1~\n"
        f"NM1*PR*2*PAYER NAME****PI*{payer_id}~\n"
        f"HL*2*1*21*1~\n"
        f"NM1*41*2*{provider_name}*****XX*{provider_npi}~\n"
        f"HL*3*2*19*0~\n"
        f"NM1*IL*1*{subscriber_last}*{subscriber_first}****MI*{subscriber_id}~\n"
        f"DTP*472*D8*{dos}~\n"
        f"SE*12*{st_ctrl}~\n"
        f"GE*1*{gs_ctrl}~\n"
        f"IEA*1*{isa_ctrl:09d}~"
    )
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


def build_837(payer_id, provider_npi, patient_name, patient_id, claim_id, amount):
    now = datetime.now()
    return f"""ISA*00**00**ZZ*SENDER*ZZ*RECEIVER*{now:%y%m%d}*{now:%H%M}*^*00501*000000001*0*T*:~
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


def build_835(payer_name, payer_id, provider_npi, claim_id, patient_name, paid_amount):
    now = datetime.now()
    return f"""ISA*00**00**ZZ*{payer_id:<15}*ZZ*RECEIVER*{now:%y%m%d}*{now:%H%M}*^*00501*000000001*0*T*:~
GS*HP*{payer_id}*RECEIVER*{now:%Y%m%d}*{now:%H%M}*1*X*005010X221A1~
ST*835*0001*005010X221A1~
BPR*I*{paid_amount}*C*CHK*01*999999999*DA*123456789*{now:%Y%m%d}~
N1*PR*{payer_name}*PI*{payer_id}~
N1*PE*BUDDHA CLINIC*XX*{provider_npi}~
CLP*{claim_id}*1*150*{paid_amount}**MC*{patient_name}*12*1~
SE*12*0001~
GE*1*1~
IEA*1*000000001~"""


def parse_835_to_df(edi_text: str):
    seg_t = "~"
    if edi_text.count("~") < 2 and edi_text.count("\n") >= 2:
        seg_t = "\n"
    lines = [l.strip() for l in edi_text.replace("\r\n", "\n").split(seg_t) if l.strip()]
    payer, payee, claims, check = {}, {}, [], {}
    current = None

    for line in lines:
        parts = line.split("*")
        tag = parts[0].upper()
        if tag == "BPR":
            check["PaymentAmount"] = parts[2] if len(parts) > 2 else ""
        elif tag == "TRN":
            check["CheckNumber"] = parts[2] if len(parts) > 2 else ""
        elif tag == "N1":
            if len(parts) > 1 and parts[1] == "PR":
                payer["PayerName"] = parts[2]
                payer["PayerID"] = parts[-1]
            elif len(parts) > 1 and parts[1] == "PE":
                payee["PayeeName"] = parts[2]
                payee["PayeeNPI"] = parts[-1]
        elif tag == "CLP":
            if current:
                claims.append(current)
            current = {
                "ClaimID": parts[1],
                "ClaimStatus": parts[2],
                "TotalCharge": parts[3],
                "TotalPaid": parts[4],
                "PatientName": ""
            }
        elif tag == "NM1" and len(parts) > 1 and parts[1] == "QC":
            if current:
                current["PatientName"] = parts[3]
    if current:
        claims.append(current)
    df = pd.DataFrame(claims)
    df["PayerName"] = payer.get("PayerName", "")
    df["PayeeName"] = payee.get("PayeeName", "")
    df["CheckNumber"] = check.get("CheckNumber", "")
    df["PaymentAmount"] = check.get("PaymentAmount", "")
    return df

# ======================================================
# Streamlit Tabs
# ======================================================
tabs = st.tabs(["270/271", "276/277", "837/835", "Profiles", "Help"])

# ======================================================
# 270/271 TAB
# ======================================================
with tabs[0]:
    st.header("🩺 270/271 – Eligibility Inquiry & Response")
    sub_tabs = st.tabs(["Build 270", "Parse 271"])

    # --- Build 270 ---
    with sub_tabs[0]:
        profiles = st.session_state.profiles
        pkeys = list(profiles.keys())
        profile_key = st.selectbox("Payer Profile", options=pkeys, key="t270_profile")
        profile = profiles[profile_key]

        payer_id = st.text_input("Payer ID", "12345", key="t270_payer")
        prov_name = st.text_input("Provider Name", "Buddha Clinic", key="t270_prov")
        npi = st.text_input("Provider NPI", "1234567890", key="t270_npi")
        sub_last = st.text_input("Subscriber Last", "DOE", key="t270_last")
        sub_first = st.text_input("Subscriber First", "JOHN", key="t270_first")
        sub_id = st.text_input("Subscriber Member ID", "W123456789", key="t270_subid")
        dob = st.text_input("Subscriber DOB (YYYYMMDD)", "19800101", key="t270_dob")
        gender = st.selectbox("Gender", ["", "M", "F", "U"], key="t270_gender")
        service_types = st.multiselect(
            "Service Types (EQ)", list(ServiceTypeMap.keys()),
            default=["30"], format_func=lambda x: f"{x} – {ServiceTypeMap.get(x)}",
            key="t270_services"
        )

        if st.button("Generate 270", key="t270_btn"):
            provider = Provider(name=prov_name, npi=npi)
            subscriber = Party(last=sub_last, first=sub_first, id_code=sub_id)
            edi270 = build_270(
                1, 1, 1000, payer_id, provider, subscriber, None,
                service_types, datetime.today().strftime("%Y%m%d"),
                dmg_dob=dob, dmg_gender=gender
            )
            st.code(edi270)
            st.download_button("⬇️ Download 270", data=edi270.encode(), file_name="270_request.x12", key="t270_dl")

    # --- Parse 271 ---
    with sub_tabs[1]:
        file = st.file_uploader("Upload 271 File", type=["x12", "edi", "txt"], key="t271_upload")
        if file:
            text = file.read().decode("utf-8", errors="ignore")
            parsed = parse_271(text)
            st.dataframe(parsed["_eb_df"], use_container_width=True)
            st.json(parsed.get("_summary", {}))
            st.dataframe(parsed["_aaa_df"], use_container_width=True)

# ======================================================
# 276/277 TAB
# ======================================================
with tabs[1]:
    st.header("📨 276/277 – Claim Status Inquiry & Response")
    payer = st.text_input("Payer ID", "12345", key="t276_payer")
    prov = st.text_input("Provider Name", "Buddha Clinic", key="t276_prov")
    npi = st.text_input("Provider NPI", "1234567890", key="t276_npi")
    sub_last = st.text_input("Subscriber Last", "DOE", key="t276_last")
    sub_first = st.text_input("Subscriber First", "JOHN", key="t276_first")
    sub_id = st.text_input("Subscriber ID", "W123456789", key="t276_subid")
    if st.button("Generate 276", key="t276_btn"):
        edi276 = build_276(1, 1, 1000, payer, prov, npi, sub_last, sub_first, sub_id)
        st.code(edi276)
        st.download_button("⬇️ Download 276", edi276.encode(), "276_request.x12", key="t276_dl")

    file = st.file_uploader("Upload 277 File", type=["x12", "edi", "txt"], key="t277_upload")
    if file:
        text = file.read().decode("utf-8", errors="ignore")
        df = parse_277(text)
        st.dataframe(df, use_container_width=True)

# ======================================================
# 837/835 TAB
# ======================================================
with tabs[2]:
    st.header("💰 837/835 – Claims & Payments")
    payer = st.text_input("Payer ID", "12345", key="t837_payer")
    npi = st.text_input("Provider NPI", "1234567890", key="t837_npi")
    patient = st.text_input("Patient Name", "John Doe", key="t837_patient")
    pid = st.text_input("Patient ID", "W123456789", key="t837_pid")
    claim = st.text_input("Claim ID", "CLM1001", key="t837_claim")
    amt = st.text_input("Amount", "150", key="t837_amt")

    if st.button("Generate 837", key="t837_btn"):
        edi837 = build_837(payer, npi, patient, pid, claim, amt)
        st.code(edi837)
        st.download_button("⬇️ Download 837", edi837.encode(), "837_claim.x12", key="t837_dl")

    st.subheader("Parse / Build 835")
    payer_name = st.text_input("Payer Name", "Insurance Co", key="t835_payer")
    payer_id = st.text_input("Payer ID", "12345", key="t835_pid")
    prov_npi = st.text_input("Provider NPI", "1234567890", key="t835_npi")
    claim = st.text_input("Claim ID", "CLM1001", key="t835_claim")
    patient = st.text_input("Patient Name", "John Doe", key="t835_patient")
    amt = st.text_input("Paid Amount", "150", key="t835_amt")

    if st.button("Generate 835", key="t835_btn"):
        edi835 = build_835(payer_name, payer_id, prov_npi, claim, patient, amt)
        st.code(edi835)
        st.download_button("⬇️ Download 835", edi835.encode(), "835_remit.x12", key="t835_dl")

    file = st.file_uploader("Upload 835 File", type=["x12", "edi", "txt"], key="t835_upload")
    if file:
        text = file.read().decode("utf-8", errors="ignore")
        df = parse_835_to_df(text)
        st.dataframe(df, use_container_width=True)
        out = BytesIO()
        with pd.ExcelWriter(out, engine="xlsxwriter") as writer:
            df.to_excel(writer, index=False, sheet_name="835_Parsed")
        out.seek(0)
        st.download_button("⬇️ Download Excel", data=out,
                           file_name="835_parsed.xlsx",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           key="t835_excel_dl")

# ======================================================
# Profiles & Help
# ======================================================
with tabs[3]:
    st.subheader("⚙️ Manage Payer Profiles")
    st.json(st.session_state.profiles)

with tabs[4]:
    st.markdown("""
### 🧭 Help / Notes
- **270/271**: Eligibility inquiry and response with table and summary view.
- **276/277**: Claim status inquiry/response.
- **837**: Claim submission generator.
- **835**: Remittance advice builder & parser with Excel export.
- **Profiles**: Customize payer-specific 270 configurations (saved in `profiles.json`).
""")
