# edi_x12.py
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Dict, Optional

# ---------------- Defaults & Maps ----------------
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

# ---------------- Built-in Payer Profiles (extend via UI in app.py) ----------------
PAYER_PROFILES: Dict[str, Dict] = {
    "default": {
        "preferred_eq": ["30"],
        "require_dmg": False,
        "expect_trn": True,
        "id_qual": "MI",
        "subscriber_is_primary": True,
        "extra_ref": [],
        "include_prv": False,
        "provider_taxonomy": "",
        "include_addresses": False,
    },
    # Example specialized payer
    "ACME_HEALTH_12345": {
        "preferred_eq": ["30"],
        "require_dmg": True,
        "expect_trn": True,
        "id_qual": "MI",
        "subscriber_is_primary": True,
        "extra_ref": ["6P"],
        "include_prv": True,
        "provider_taxonomy": "207Q00000X",
        "include_addresses": True,
    },
}

# ---------------- Delimiter utils ----------------
def detect_delimiters(edi_text: str) -> Tuple[str, str, str]:
    """
    From ISA:
      - element separator at index 3
      - component separator at index 104 (ISA16, 0-based)
      - segment terminator at index 105
    Fallback: if few seg chars but many newlines, use '\n'.
    """
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

def ensure_seg_terminated(text: str, seg_t: str) -> str:
    t = text.strip()
    return t if t.endswith(seg_t) else (t + seg_t)

def split_segments(edi_text: str, seg_t: str) -> List[str]:
    text = edi_text.strip()
    if seg_t == "\n":
        parts = [p.strip() for p in text.replace("\r\n", "\n").split("\n")]
    else:
        if not text.endswith(seg_t):
            text += seg_t
        parts = [p.strip() for p in text.split(seg_t)]
    return [p for p in parts if p]

def parse_segments(edi_text: str, seg_t: str, elem_t: str) -> List[List[str]]:
    return [seg.split(elem_t) for seg in split_segments(edi_text, seg_t)]

# ---------------- Envelopes ----------------
def build_ISA(control_num: int, sender_id: str, receiver_id: str,
              elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG) -> str:
    now = datetime.utcnow()
    # Simplified demo ISA (qualifiers 'ZZ', repetition sep '^')
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
    # 270 inquiry => GS01 must be HS (HB is for 271 response)
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

# ---------------- Business objects ----------------
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

# ---------------- 270 Builder (profile-aware, PRV + N3/N4) ----------------
def build_270(
    isa_ctrl: int,
    gs_ctrl: int,
    st_ctrl: int,
    payer_id: str,
    provider: Provider,
    subscriber: Party,
    dependent: Optional[Party],
    service_types: List[str],
    date_start: str,                  # YYYYMMDD
    date_end: Optional[str] = None,   # YYYYMMDD
    profile: Dict = None,
    trn_trace: Optional[str] = None,
    dmg_dob: Optional[str] = None,    # YYYYMMDD
    dmg_gender: Optional[str] = None, # M/F/U
    include_prv: Optional[bool] = None,
    provider_taxonomy: Optional[str] = None,
    include_addresses: Optional[bool] = None,
    provider_addr: Optional[Dict[str, str]] = None,   # {"line1","line2","city","state","zip"}
    subscriber_addr: Optional[Dict[str, str]] = None, # same
    elem_t: str = DEFAULT_ELEM,
    seg_t: str = DEFAULT_SEG,
) -> str:
    prof = profile or PAYER_PROFILES["default"]
    segs: List[str] = []

    if include_prv is None:
        include_prv = prof.get("include_prv", False)
    if not provider_taxonomy:
        provider_taxonomy = prof.get("provider_taxonomy", "")
    if include_addresses is None:
        include_addresses = prof.get("include_addresses", False)

    # Envelope
    segs.append(build_ISA(isa_ctrl, sender_id="SENDERID", receiver_id="RECEIVERID", elem_t=elem_t, seg_t=seg_t))
    segs.append(build_GS(gs_ctrl, sender_code="SENDER", receiver_code="RECEIVER", elem_t=elem_t, seg_t=seg_t))
    segs.append(build_ST(st_ctrl, elem_t=elem_t, seg_t=seg_t))

    # BHT
    segs.append(elem_t.join(["BHT","0022","13", f"CN{st_ctrl}", datetime.utcnow().strftime("%Y%m%d"), datetime.utcnow().strftime("%H%M")]) + seg_t)

    # 2100A Payer
    segs.append(elem_t.join(["HL","1","","20","1"]) + seg_t)
    segs.append(elem_t.join(["NM1","PR","2","PAYER NAME","","","", "PI", payer_id]) + seg_t)

    # 2100B Provider
    segs.append(elem_t.join(["HL","2","1","21","1"]) + seg_t)
    segs.append(elem_t.join(["NM1","1P","2",provider.name,"","","","XX",provider.npi]) + seg_t)

    # PRV (taxonomy)
    if include_prv and provider_taxonomy:
        segs.append(elem_t.join(["PRV","PE","PXC", provider_taxonomy]) + seg_t)

    # Provider N3/N4
    if include_addresses and provider_addr:
        line1 = provider_addr.get("line1",""); line2 = provider_addr.get("line2","")
        city  = provider_addr.get("city","");  state = provider_addr.get("state",""); zipc = provider_addr.get("zip","")
        if line1:
            segs.append(elem_t.join(["N3", line1, line2]) + seg_t if line2 else elem_t.join(["N3", line1]) + seg_t)
        if city or state or zipc:
            segs.append(elem_t.join(["N4", city, state, zipc]) + seg_t)

    # Extra REF per profile
    for ref in prof.get("extra_ref", []):
        segs.append(elem_t.join(["REF", ref, "PLACEHOLDER"]) + seg_t)

    # 2100C Subscriber
    has_child = "1" if dependent else "0"
    sub_id_qual = prof.get("id_qual","MI")
    segs.append(elem_t.join(["HL","3","2","22",has_child]) + seg_t)
    segs.append(elem_t.join(["NM1","IL","1",subscriber.last,subscriber.first,subscriber.middle,"",sub_id_qual,subscriber.id_code]) + seg_t)

    # TRN
    if prof.get("expect_trn") and trn_trace:
        segs.append(elem_t.join(["TRN","2", trn_trace]) + seg_t)

    # Subscriber N3/N4
    if include_addresses and subscriber_addr:
        s_line1 = subscriber_addr.get("line1",""); s_line2 = subscriber_addr.get("line2","")
        s_city  = subscriber_addr.get("city","");  s_state = subscriber_addr.get("state",""); s_zipc = subscriber_addr.get("zip","")
        if s_line1:
            segs.append(elem_t.join(["N3", s_line1, s_line2]) + seg_t if s_line2 else elem_t.join(["N3", s_line1]) + seg_t)
        if s_city or s_state or s_zipc:
            segs.append(elem_t.join(["N4", s_city, s_state, s_zipc]) + seg_t)

    # DMG
    if prof.get("require_dmg") or (dmg_dob or dmg_gender):
        segs.append(elem_t.join([
            "DMG","D8",
            (dmg_dob or "19000101"),
            (dmg_gender or "U")
        ]) + seg_t)

    # DTP
    if date_end:
        segs.append(elem_t.join(["DTP","291","RD8", f"{date_start}-{date_end}"]) + seg_t)
    else:
        segs.append(elem_t.join(["DTP","291","D8", date_start]) + seg_t)

    # 2100D Dependent
    if dependent:
        dep_id_qual = prof.get("id_qual","MI")
        segs.append(elem_t.join(["HL","4","3","23","0"]) + seg_t)
        segs.append(elem_t.join(["NM1","QD","1",dependent.last,dependent.first,dependent.middle,"",dep_id_qual,dependent.id_code]) + seg_t)

    # EQ service types
    eq_list = service_types or prof.get("preferred_eq", ["30"])
    for stc in eq_list:
        segs.append(elem_t.join(["EQ", stc]) + seg_t)

    # Segment count ST..SE
    current_text = "".join(segs[2:])
    seg_count = current_text.count(seg_t) + 1
    segs.append(build_SE(st_ctrl, seg_count, elem_t, seg_t))
    segs.append(build_GE(gs_ctrl, 1, elem_t, seg_t))
    segs.append(build_IEA(isa_ctrl, 1, elem_t, seg_t))

    return "".join(segs)

# ---------------- Validators ----------------
def validate_envelopes(edi_text: str) -> List[str]:
    """Light checks: ST/SE segment count."""
    warnings: List[str] = []
    seg_t, elem_t, _ = detect_delimiters(edi_text)
    segs = parse_segments(edi_text, seg_t, elem_t)

    st_idx = [i for i,s in enumerate(segs) if s and s[0].upper()=="ST"]
    se_idx = [i for i,s in enumerate(segs) if s and s[0].upper()=="SE"]
    for i, si in enumerate(st_idx):
        if i >= len(se_idx):
            warnings.append("SE segment missing for an ST.")
            break
        ei = se_idx[i]
        between = segs[si:ei+1]
        try:
            declared = int(segs[ei][1])
        except Exception:
            declared = 0
            warnings.append("SE01 missing or not integer.")
        actual = len(between)
        if declared and declared != actual:
            warnings.append(f"SE01={declared} but counted {actual} segments between ST..SE.")
    return warnings

# ---------------- 271 Parser + post-processing ----------------
def parse_271(edi_text: str) -> Dict:
    seg_t, elem_t, _ = detect_delimiters(edi_text)
    if "ISA" not in edi_text[:200] and seg_t == DEFAULT_SEG and edi_text.count(DEFAULT_SEG) < 2:
        seg_t = "\n"
    segs = parse_segments(edi_text, seg_t, elem_t)

    out: Dict = {
        "payer": {}, "provider": {}, "subscriber": {}, "dependent": {},
        "eb": [], "aaa": [], "trace": {}, "dtp": [], "ref": [],
        "_debug": {
            "segment_terminator": repr(seg_t),
            "element_separator": repr(elem_t),
            "segment_count": len(segs),
            "first_tags": [s[0] if s else "" for s in segs[:12]],
        }
    }

    for parts in segs:
        if not parts: continue
        tag = parts[0].strip().upper()

        if tag == "NM1":
            ent = parts[1].strip().upper() if len(parts) > 1 else ""
            if ent == "PR":
                out["payer"] = {
                    "name": parts[3] if len(parts) > 3 else "",
                    "id_qual": parts[8] if len(parts) > 8 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }
            elif ent == "1P":
                out["provider"] = {
                    "name": parts[3] if len(parts) > 3 else "",
                    "id_qual": parts[8] if len(parts) > 8 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }
            elif ent == "IL":
                out["subscriber"] = {
                    "last": parts[3] if len(parts) > 3 else "",
                    "first": parts[4] if len(parts) > 4 else "",
                    "id_qual": parts[8] if len(parts) > 8 else "",
                    "id": parts[9] if len(parts) > 9 else "",
                }
            elif ent == "QD":
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
            eb = {f"E{i:02d}": (parts[i] if len(parts) > i else "") for i in range(1, 14)}
            rec = {
                "EB01": eb["E01"],
                "Coverage": EB01_MAP.get(eb["E01"], ""),
                "EB02": eb["E02"],
                "ServiceType": eb["E03"],
                "PlanDesc": eb["E04"],
                "TimePeriod": eb["E05"],
                "BenefitAmt": eb["E06"],
                "Percent": eb["E07"],
                "QtyQual": eb["E08"],
                "Qty": eb["E09"],
                "AuthInd": eb["E10"],
                "InPlan": eb["E11"],
                "Proc": eb["E12"],
                "Raw": eb,
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

    out["_validation"] = validate_envelopes(edi_text)
    return out

def normalize_eb_for_reporting(eb_rows: List[Dict]) -> Dict[str, Optional[str]]:
    summary = {
        "Active": None,
        "DeductibleRemaining": None,
        "CoinsurancePercent": None,
        "CopayAmount": None,
        "InNetwork": None,
    }
    for r in eb_rows:
        if r.get("EB01") == "1":
            summary["Active"] = "Yes"
        if "deduct" in (r.get("PlanDesc","") or "").lower():
            amt = r.get("BenefitAmt") or r["Raw"].get("E06","")
            if amt: summary["DeductibleRemaining"] = amt
        if r.get("Percent"):
            summary["CoinsurancePercent"] = r["Percent"]
        if "copay" in (r.get("PlanDesc","") or "").lower():
            amt = r.get("BenefitAmt") or r["Raw"].get("E06","")
            if amt: summary["CopayAmount"] = amt
        if r.get("InPlan"):
            summary["InNetwork"] = "Yes" if r["InPlan"] == "Y" else ("No" if r["InPlan"] == "N" else None)
    return summary
