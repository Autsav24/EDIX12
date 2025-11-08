from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Dict, Optional
import pandas as pd
import os

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

# ---------------- Built-in Payer Profiles ----------------
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

# ---------------- 270 Builder ----------------
def build_270(
    isa_ctrl: int, gs_ctrl: int, st_ctrl: int, payer_id: str,
    provider: Provider, subscriber: Party, dependent: Optional[Party],
    service_types: List[str], date_start: str, date_end: Optional[str] = None,
    profile: Dict = None, trn_trace: Optional[str] = None,
    dmg_dob: Optional[str] = None, dmg_gender: Optional[str] = None,
    include_prv: Optional[bool] = None, provider_taxonomy: Optional[str] = None,
    include_addresses: Optional[bool] = None, provider_addr: Optional[Dict[str, str]] = None,
    subscriber_addr: Optional[Dict[str, str]] = None,
    elem_t: str = DEFAULT_ELEM, seg_t: str = DEFAULT_SEG,
) -> str:

    prof = profile or PAYER_PROFILES["default"]
    segs: List[str] = []

    if include_prv is None:
        include_prv = prof.get("include_prv", False)
    if not provider_taxonomy:
        provider_taxonomy = prof.get("provider_taxonomy", "")
    if include_addresses is None:
        include_addresses = prof.get("include_addresses", False)

    segs.append(build_ISA(isa_ctrl, "SENDERID", "RECEIVERID", elem_t, seg_t))
    segs.append(build_GS(gs_ctrl, "SENDER", "RECEIVER", elem_t, seg_t))
    segs.append(build_ST(st_ctrl, elem_t, seg_t))
    segs.append(elem_t.join(["BHT","0022","13", f"CN{st_ctrl}", datetime.utcnow().strftime("%Y%m%d"), datetime.utcnow().strftime("%H%M")]) + seg_t)
    segs.append(elem_t.join(["HL","1","","20","1"]) + seg_t)
    segs.append(elem_t.join(["NM1","PR","2","PAYER NAME","","","", "PI", payer_id]) + seg_t)
    segs.append(elem_t.join(["HL","2","1","21","1"]) + seg_t)
    segs.append(elem_t.join(["NM1","1P","2",provider.name,"","","","XX",provider.npi]) + seg_t)

    if include_prv and provider_taxonomy:
        segs.append(elem_t.join(["PRV","PE","PXC", provider_taxonomy]) + seg_t)

    if include_addresses and provider_addr:
        line1 = provider_addr.get("line1",""); line2 = provider_addr.get("line2","")
        city  = provider_addr.get("city","");  state = provider_addr.get("state",""); zipc = provider_addr.get("zip","")
        if line1:
            segs.append(elem_t.join(["N3", line1, line2]) + seg_t if line2 else elem_t.join(["N3", line1]) + seg_t)
        if city or state or zipc:
            segs.append(elem_t.join(["N4", city, state, zipc]) + seg_t)

    for ref in prof.get("extra_ref", []):
        segs.append(elem_t.join(["REF", ref, "PLACEHOLDER"]) + seg_t)

    has_child = "1" if dependent else "0"
    sub_id_qual = prof.get("id_qual","MI")
    segs.append(elem_t.join(["HL","3","2","22",has_child]) + seg_t)
    segs.append(elem_t.join(["NM1","IL","1",subscriber.last,subscriber.first,subscriber.middle,"",sub_id_qual,subscriber.id_code]) + seg_t)

    if prof.get("expect_trn") and trn_trace:
        segs.append(elem_t.join(["TRN","2", trn_trace]) + seg_t)

    if include_addresses and subscriber_addr:
        s_line1 = subscriber_addr.get("line1",""); s_line2 = subscriber_addr.get("line2","")
        s_city  = subscriber_addr.get("city","");  s_state = subscriber_addr.get("state",""); s_zipc = subscriber_addr.get("zip","")
        if s_line1:
            segs.append(elem_t.join(["N3", s_line1, s_line2]) + seg_t if s_line2 else elem_t.join(["N3", s_line1]) + seg_t)
        if s_city or s_state or s_zipc:
            segs.append(elem_t.join(["N4", s_city, s_state, s_zipc]) + seg_t)

    if prof.get("require_dmg") or (dmg_dob or dmg_gender):
        segs.append(elem_t.join(["DMG","D8",(dmg_dob or "19000101"),(dmg_gender or "U")]) + seg_t)

    if date_end:
        segs.append(elem_t.join(["DTP","291","RD8", f"{date_start}-{date_end}"]) + seg_t)
    else:
        segs.append(elem_t.join(["DTP","291","D8", date_start]) + seg_t)

    if dependent:
        dep_id_qual = prof.get("id_qual","MI")
        segs.append(elem_t.join(["HL","4","3","23","0"]) + seg_t)
        segs.append(elem_t.join(["NM1","QD","1",dependent.last,dependent.first,dependent.middle,"",dep_id_qual,dependent.id_code]) + seg_t)

    eq_list = service_types or prof.get("preferred_eq", ["30"])
    for stc in eq_list:
        segs.append(elem_t.join(["EQ", stc]) + seg_t)

    seg_count = len(segs)
    segs.append(build_SE(st_ctrl, seg_count, elem_t, seg_t))
    segs.append(build_GE(gs_ctrl, 1, elem_t, seg_t))
    segs.append(build_IEA(isa_ctrl, 1, elem_t, seg_t))

    return "".join(segs)

# ---------------- Validators ----------------
def validate_envelopes(edi_text: str) -> List[str]:
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
        except:
            declared = 0
        actual = len(between)
        if declared and declared != actual:
            warnings.append(f"SE01={declared} but counted {actual} segments between ST..SE.")
    return warnings

# ---------------- Improved 271 Parser (hierarchical) ----------------
def parse_271(edi_text: str) -> Dict:
    seg_t, elem_t, _ = detect_delimiters(edi_text)
    segs = parse_segments(edi_text, seg_t, elem_t)

    out = {"payer": {}, "provider": {}, "subscriber": {}, "dependent": {},
           "eb": {"payer": [], "provider": [], "subscriber": [], "dependent": []},
           "aaa": [], "trace": {}, "dtp": [], "ref": [], "_debug": {}}

    current_context = None

    for parts in segs:
        if not parts: continue
        tag = parts[0].upper()

        if tag == "HL":
            if len(parts) > 3:
                hl_code = parts[3]
                if hl_code == "20": current_context = "payer"
                elif hl_code == "21": current_context = "provider"
                elif hl_code == "22": current_context = "subscriber"
                elif hl_code == "23": current_context = "dependent"
            continue

        if tag == "NM1":
            ent = parts[1].upper() if len(parts) > 1 else ""
            rec = {"last": parts[3] if len(parts) > 3 else "",
                   "first": parts[4] if len(parts) > 4 else "",
                   "id_qual": parts[8] if len(parts) > 8 else "",
                   "id": parts[9] if len(parts) > 9 else ""}
            if ent == "PR": out["payer"] = rec
            elif ent == "1P": out["provider"] = rec
            elif ent == "IL": out["subscriber"] = rec
            elif ent == "QD": out["dependent"] = rec
            continue

        if tag == "TRN":
            out["trace"] = {"trace_type": parts[1] if len(parts) > 1 else "",
                            "trace_num": parts[2] if len(parts) > 2 else ""}
            continue

        if tag == "EB":
            eb = {f"E{i:02d}": (parts[i] if len(parts) > i else "") for i in range(1, 14)}
            rec = {"EB01": eb["E01"], "Coverage": EB01_MAP.get(eb["E01"], ""),
                   "EB02": eb["E02"], "ServiceType": eb["E03"], "PlanDesc": eb["E04"],
                   "TimePeriod": eb["E05"], "BenefitAmt": eb["E06"], "Percent": eb["E07"],
                   "QtyQual": eb["E08"], "Qty": eb["E09"], "AuthInd": eb["E10"],
                   "InPlan": eb["E11"], "Proc": eb["E12"], "Raw": eb}
            out["eb"][current_context or "subscriber"].append(rec)
            continue

        if tag == "AAA":
            out["aaa"].append({"context": current_context,
                               "reject_code": parts[3] if len(parts) > 3 else "",
                               "followup_action": parts[4] if len(parts) > 4 else ""})
            continue

        if tag == "DTP":
            out["dtp"].append({"context": current_context, "data": parts})
            continue

        if tag == "REF":
            out["ref"].append({"context": current_context, "data": parts})
            continue

    out["_validation"] = validate_envelopes(edi_text)
    return out

# ---------------- Flatten 271 for Excel ----------------
def parse_271_to_table(edi_text: str, output_excel: Optional[str] = None) -> List[Dict]:
    parsed = parse_271(edi_text)
    results: List[Dict] = []

    payer_name = parsed.get("payer", {}).get("last", "")
    payer_id = parsed.get("payer", {}).get("id", "")
    provider_name = parsed.get("provider", {}).get("last", "")
    provider_npi = parsed.get("provider", {}).get("id", "")
    trace_number = parsed.get("trace", {}).get("trace_num", "")

    subscriber = parsed.get("subscriber", {})
    sub_id = subscriber.get("id", "")
    sub_first = subscriber.get("first", "")
    sub_last = subscriber.get("last", "")

    dependent = parsed.get("dependent", {})
    dep_first = dependent.get("first", "")
    dep_last = dependent.get("last", "")
    dep_id = dependent.get("id", "")

    for ctx, eb_list in parsed.get("eb", {}).items():
        for eb in eb_list:
            coverage_status = EB01_MAP.get(eb.get("EB01",""), "")
            eligibility_start, eligibility_end = "", ""
            for dtp in parsed.get("dtp", []):
                if len(dtp.get("data", [])) >= 4 and dtp["data"][1] == "291":
                    val = dtp["data"][3]
                    if "-" in val: eligibility_start, eligibility_end = val.split("-", 1)
                    else: eligibility_start = val

            rejection_code, rejection_msg = "", ""
            for aaa in parsed.get("aaa", []):
                if aaa.get("context") == ctx:
                    rejection_code = aaa.get("reject_code", "")
                    rejection_msg = aaa.get("followup_action", "")

            results.append({
                "PayerName": payer_name,
                "PayerID": payer_id,
                "ProviderName
