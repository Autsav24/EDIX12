from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Dict, Optional

DEFAULT_SEG = "~"
DEFAULT_ELEM = "*"
DEFAULT_SUBELEM = ":"

EB01_MAP = {
    "1": "Active Coverage",
    "6": "Inactive Coverage",
    "7": "Policy Cancelled",
    "8": "Policy Not Renewed",
    "I": "Non-Covered",
    "F": "Financial/Remaining Benefits",
}

ServiceTypeMap = {
    "1": "Medical Care",
    "30": "Health Benefit Plan Coverage",
    "33": "Chiropractic",
    "35": "Dental Care",
    "47": "Hospital",
    "86": "Emergency Services",
    "88": "Pharmacy",
    "98": "Professional (Physician)",
}

PAYER_PROFILES: Dict[str, Dict] = {
    "default": {"preferred_eq": ["30"], "id_qual": "MI"}
}

def detect_delimiters(edi_text: str) -> Tuple[str, str, str]:
    seg = DEFAULT_SEG
    elem = DEFAULT_ELEM
    comp = DEFAULT_SUBELEM
    if edi_text.startswith("ISA") and len(edi_text) >= 106:
        elem = edi_text[3]
        if len(edi_text) > 104:
            comp = edi_text[104]
        if len(edi_text) > 105:
            seg = edi_text[105]
    if edi_text.count(seg) < 2 and edi_text.count("\n") >= 2:
        seg = "\n"
    return seg, elem, comp

def parse_segments(edi_text: str, seg_t: str, elem_t: str) -> List[List[str]]:
    parts = edi_text.strip().split(seg_t)
    return [p.split(elem_t) for p in parts if p]

@dataclass
class Party:
    last: str
    first: str = ""
    middle: str = ""
    id_code: str = ""
    id_qual: str = "MI"

@dataclass
class Provider:
    name: str
    npi: str

# ---------------- Exact-match 270 Builder ----------------
def build_270(
    isa_ctrl: int,
    gs_ctrl: int,
    st_ctrl: int,
    payer_id: str,
    provider: Provider,
    subscriber: Party,
    dependent: Optional[Party],
    service_types: List[str],
    date_start: str,
    date_end: Optional[str] = None,
    profile: Dict = None,
    trn_trace: Optional[str] = None,
    dmg_dob: Optional[str] = None,
    dmg_gender: Optional[str] = None,
    elem_t: str = DEFAULT_ELEM,
    seg_t: str = DEFAULT_SEG,
) -> str:

    now = datetime.now()
    gender = (dmg_gender or "").upper().strip()
    if gender not in ("M", "F"):
        gender = ""

    acct_num = subscriber.id_code
    f_name = subscriber.first
    l_name = subscriber.last
    PAYER_NAME = "PAYER NAME"
    PAYER_ID = payer_id
    PROVIDER_NAME = provider.name
    PROVIDER_NPI = provider.npi
    SERVICE_TYPE = service_types[0] if service_types else "30"

    edi = ""
    edi += f"ISA*00*          *00*          *ZZ*SENDERID       *ZZ*RECEIVERID     *{now.strftime('%y%m%d')}*{now.strftime('%H%M')}*^*00501*{isa_ctrl:09d}*0*T*:~\n"
    edi += f"GS*HS*SENDER*RECEIVER*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}*{gs_ctrl}*X*005010X279A1~\n"
    edi += f"ST*270*{st_ctrl}*005010X279A1~\n"
    edi += f"BHT*0022*13*{st_ctrl - 1000}*{now.strftime('%Y%m%d')}*{now.strftime('%H%M')}~\n"
    edi += "HL*1**20*1~\n"
    edi += f"NM1*PR*2*{PAYER_NAME}*****PI*{PAYER_ID}~\n"
    edi += "HL*2*1*21*1~\n"
    edi += f"NM1*1P*2*{PROVIDER_NAME}*****XX*{PROVIDER_NPI}~\n"
    edi += "HL*3*2*22*0~\n"
    edi += f"NM1*IL*1*{l_name}*{f_name}****MI*{acct_num}~\n"
    if gender:
        edi += f"DMG*D8*{dmg_dob}*{gender}~\n"
    else:
        edi += f"DMG*D8*{dmg_dob}~\n"
    edi += f"DTP*291*D8*{date_start}~\n"
    edi += f"EQ*{SERVICE_TYPE}~\n"
    edi += f"SE*12*{st_ctrl}~\n"
    edi += f"GE*1*{gs_ctrl}~\n"
    edi += f"IEA*1*{isa_ctrl:09d}~"
    return edi

# ---------------- Validators ----------------
def validate_envelopes(edi_text: str) -> List[str]:
    warnings: List[str] = []
    seg_t, elem_t, _ = detect_delimiters(edi_text)
    segs = parse_segments(edi_text, seg_t, elem_t)
    st_idx = [i for i, s in enumerate(segs) if s and s[0].upper() == "ST"]
    se_idx = [i for i, s in enumerate(segs) if s and s[0].upper() == "SE"]
    for i, si in enumerate(st_idx):
        if i >= len(se_idx):
            warnings.append("SE segment missing for an ST.")
            break
        ei = se_idx[i]
        between = segs[si:ei + 1]
        try:
            declared = int(segs[ei][1])
        except Exception:
            declared = 0
            warnings.append("SE01 missing or not integer.")
        actual = len(between)
        if declared and declared != actual:
            warnings.append(f"SE01={declared} but counted {actual} segments between ST..SE.")
    return warnings

# ---------------- Simple 271 Parser ----------------
def parse_271(edi_text: str) -> Dict:
    seg_t, elem_t, _ = detect_delimiters(edi_text)
    segs = parse_segments(edi_text, seg_t, elem_t)
    out: Dict = {
        "payer": {}, "provider": {}, "subscriber": {}, "eb": [],
        "_debug": {"segment_count": len(segs)},
    }
    for parts in segs:
        if not parts: continue
        tag = parts[0].strip().upper()
        if tag == "NM1" and len(parts) > 2:
            ent = parts[1].strip().upper()
            if ent == "PR":
                out["payer"] = {"name": parts[3] if len(parts) > 3 else ""}
            elif ent == "1P":
                out["provider"] = {"name": parts[3] if len(parts) > 3 else ""}
            elif ent == "IL":
                out["subscriber"] = {
                    "last": parts[3] if len(parts) > 3 else "",
                    "first": parts[4] if len(parts) > 4 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }
    out["_validation"] = validate_envelopes(edi_text)
    return out

def normalize_eb_for_reporting(eb_rows: List[Dict]) -> Dict[str, Optional[str]]:
    summary = {"Active": None}
    for r in eb_rows:
        if r.get("EB01") == "1":
            summary["Active"] = "Yes"
    return summary
