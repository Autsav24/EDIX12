# edi_x12.py
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Dict, Optional

# ---------- Delimiters ----------
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

def detect_delimiters(edi_text: str) -> Tuple[str, str, str]:
    """
    Detect element and component separators from ISA if present.
    Segment terminator is commonly '~'; we keep default if uncertain.
    """
    seg = DEFAULT_SEG
    elem = DEFAULT_ELEM
    comp = DEFAULT_SUBELEM
    if edi_text.startswith("ISA") and len(edi_text) >= 106:
        elem = edi_text[3]                     # element sep is ISA01's trailing char
        comp = edi_text[104] if len(edi_text) > 104 else DEFAULT_SUBELEM  # ISA16 at pos 105 (0-index 104)
    return seg, elem, comp

# ---------- Low-level helpers ----------
def ensure_seg_terminated(text: str, seg_t: str) -> str:
    t = text.strip()
    return t if t.endswith(seg_t) else (t + seg_t)

def split_segments(edi_text: str, seg_t: str) -> List[str]:
    raw = ensure_seg_terminated(edi_text, seg_t)
    return [s for s in raw.split(seg_t) if s.strip()]

def parse_segments(edi_text: str, seg_t: str, elem_t: str) -> List[List[str]]:
    return [seg.split(elem_t) for seg in split_segments(edi_text, seg_t)]

# ---------- X12 envelope builders ----------
def build_ISA(control_num: int, sender_id: str, receiver_id: str,
              elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG) -> str:
    now = datetime.utcnow()
    # NOTE: This is simplified (qualifiers 'ZZ' and ^ as repetition sep). Adjust per partner profile.
    return elem_t.join([
        "ISA","00","" * 10,"00","" * 10,"ZZ",sender_id.ljust(15),
        "ZZ",receiver_id.ljust(15),
        now.strftime("%y%m%d"), now.strftime("%H%M"), "^","00501",
        f"{control_num:09d}", "0","T",":"
    ]) + seg_t

def build_IEA(control_num: int, group_count: int = 1,
              elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG) -> str:
    return elem_t.join(["IEA", str(group_count), f"{control_num:09d}"]) + seg_t

def build_GS(control_num: int, sender_code: str, receiver_code: str,
             elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG) -> str:
    now = datetime.utcnow()
    return elem_t.join([
        "GS","HS",sender_code,receiver_code,now.strftime("%Y%m%d"), now.strftime("%H%M"),
        str(control_num),"X","005010X279A1"
    ]) + seg_t

def build_GE(control_num: int, txn_count: int = 1,
             elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG) -> str:
    return elem_t.join(["GE", str(txn_count), str(control_num)]) + seg_t

def build_ST(control_num: int, elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG) -> str:
    return elem_t.join(["ST","270", f"{control_num:09d}"]) + seg_t

def build_SE(control_num: int, segment_count: int,
             elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG) -> str:
    return elem_t.join(["SE", str(segment_count), f"{control_num:09d}"]) + seg_t

# ---------- Business objects ----------
@dataclass
class Party:
    last: str
    first: str = ""
    middle: str = ""
    id_code: str = ""   # e.g., Member ID
    id_qual: str = "MI" # Member Identification Number

@dataclass
class Provider:
    name: str
    npi: str

# ---------- 270 Builder (single sub/dependent) ----------
def build_270(
    isa_ctrl: int,
    gs_ctrl: int,
    st_ctrl: int,
    payer_id: str,
    provider: Provider,
    subscriber: Party,
    dependent: Optional[Party],
    service_types: List[str],  # e.g., ["30"]
    date_start: str,           # YYYYMMDD
    date_end: Optional[str] = None,
    elem_t: str = DEFAULT_ELEM,
    seg_t: str = DEFAULT_SEG,
) -> str:
    segs: List[str] = []

    # Envelope
    segs.append(build_ISA(isa_ctrl, sender_id="SENDERID", receiver_id="RECEIVERID", elem_t=elem_t, seg_t=seg_t))
    segs.append(build_GS(gs_ctrl, sender_code="SENDER", receiver_code="RECEIVER", elem_t=elem_t, seg_t=seg_t))
    segs.append(build_ST(st_ctrl, elem_t=elem_t, seg_t=seg_t))

    # BHT – generic
    segs.append(elem_t.join(["BHT","0022","13", f"CN{st_ctrl}", datetime.utcnow().strftime("%Y%m%d"), datetime.utcnow().strftime("%H%M")]) + seg_t)

    # 2100A Payer (HL 1)
    segs.append(elem_t.join(["HL","1","","20","1"]) + seg_t)  # Info Source, has child
    segs.append(elem_t.join(["NM1","PR","2","PAYER NAME","","","", "PI", payer_id]) + seg_t)

    # 2100B Provider (HL 2)
    segs.append(elem_t.join(["HL","2","1","21","1"]) + seg_t)  # Info Receiver, has child
    segs.append(elem_t.join(["NM1","1P","2",provider.name,"","","","XX",provider.npi]) + seg_t)

    # 2100C Subscriber (HL 3)
    segs.append(elem_t.join(["HL","3","2","22","1" if dependent else "0"]) + seg_t)  # Subscriber
    segs.append(elem_t.join(["NM1","IL","1",subscriber.last,subscriber.first,subscriber.middle,"",subscriber.id_qual,subscriber.id_code]) + seg_t)
    # Demo DMG values—replace with real DOB/Gender if required by partner
    segs.append(elem_t.join(["DMG","D8","19000101","U"]) + seg_t)

    # DTP (Eligibility Date or Range)
    if date_end:
        segs.append(elem_t.join(["DTP","291","RD8", f"{date_start}-{date_end}"]) + seg_t)
    else:
        segs.append(elem_t.join(["DTP","291","D8", date_start]) + seg_t)

    # 2100D Dependent (HL 4) if any
    if dependent:
        segs.append(elem_t.join(["HL","4","3","23","0"]) + seg_t)
        segs.append(elem_t.join(["NM1","QD","1",dependent.last,dependent.first,dependent.middle,"",dependent.id_qual,dependent.id_code]) + seg_t)

    # EQ – service types
    for stc in service_types:
        segs.append(elem_t.join(["EQ", stc]) + seg_t)

    # Count segments between ST and SE inclusive.
    # We built segs from the beginning, so count ST..(right now) and add SE after.
    # Calculate segments from the first ST occurrence to this point.
    # Simple approach: count segment terminators between first ST and end, then +1 for SE.
    st_index = 0  # ST is at segs[2]
    current_text = "".join(segs[2:])  # from ST onward
    seg_count = current_text.count(seg_t) + 1  # +1 for SE itself

    segs.append(build_SE(st_ctrl, seg_count, elem_t, seg_t))
    segs.append(build_GE(gs_ctrl, 1, elem_t, seg_t))
    segs.append(build_IEA(isa_ctrl, 1, elem_t, seg_t))

    return "".join(segs)

# ---------- 271 Parser (pragmatic) ----------
def parse_271(edi_text: str) -> Dict:
    seg_t, elem_t, _ = detect_delimiters(edi_text)
    segs = parse_segments(edi_text, seg_t, elem_t)

    out: Dict = {
        "payer": {},
        "provider": {},
        "subscriber": {},
        "dependent": {},
        "eb": [],   # list of EB dicts
        "aaa": [],  # list of rejection dicts
        "trace": {},  # TRN
        "dtp": [],    # dates found
        "ref": [],    # refs found
    }

    for parts in segs:
        tag = parts[0]
        # Key loops by NM1
        if tag == "NM1":
            ent = parts[1] if len(parts) > 1 else ""
            if ent == "PR":  # payer
                out["payer"] = {
                    "name": parts[3] if len(parts) > 3 else "",
                    "id_qual": parts[8] if len(parts) > 8 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }
            elif ent == "1P":  # provider
                out["provider"] = {
                    "name": parts[3] if len(parts) > 3 else "",
                    "id_qual": parts[8] if len(parts) > 8 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }
            elif ent == "IL":  # subscriber
                out["subscriber"] = {
                    "last": parts[3] if len(parts) > 3 else "",
                    "first": parts[4] if len(parts) > 4 else "",
                    "id_qual": parts[8] if len(parts) > 8 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }
            elif ent == "QD":  # dependent
                out["dependent"] = {
                    "last": parts[3] if len(parts) > 3 else "",
                    "first": parts[4] if len(parts) > 4 else "",
                    "id_qual": parts[8] if len(parts) > 8 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }

        elif tag == "TRN":
            out["trace"] = {
                "trace_type": parts[1] if len(parts) > 1 else "",
                "trace_num": parts[2] if len(parts) > 2 else "",
            }

        elif tag == "EB":
            rec = {
                "EB01": parts[1] if len(parts) > 1 else "",
                "Coverage": EB01_MAP.get(parts[1], ""),
                "EB02": parts[2] if len(parts) > 2 else "",
                "ServiceType": parts[3] if len(parts) > 3 else "",
                "PlanDesc": parts[4] if len(parts) > 4 else "",
                "TimePeriod": parts[5] if len(parts) > 5 else "",
                "BenefitAmt": parts[6] if len(parts) > 6 else "",
                # Additional positions (co-pay, coins, etc.) vary by payer; extend as needed.
            }
            out["eb"].append(rec)

        elif tag == "AAA":
            out["aaa"].append({
                "reject_code": parts[3] if len(parts) > 3 else "",
                "followup_action": parts[4] if len(parts) > 4 else "",
            })

        elif tag == "DTP":
            out["dtp"].append(parts)

        elif tag == "REF":
            out["ref"].append(parts)

    return out
