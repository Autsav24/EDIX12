from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Dict, Optional
import pandas as pd

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
        "dependent_require_dmg": False,
        "dependent_id_required": False,
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
        "dependent_require_dmg": True,
        "dependent_id_required": False,
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

# ---------------- Envelope Builders ----------------
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

# ---------------- Data Classes ----------------
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
        except Exception:
            declared = 0
            warnings.append("SE01 missing or not integer.")
        actual = len(between)
        if declared and declared != actual:
            warnings.append(f"SE01={declared} but counted {actual} segments between ST..SE.")
    return warnings

# ---------------- 271 Parser (with auto DataFrame output) ----------------
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
        if not parts:
            continue
        tag = parts[0].strip().upper()

        if tag == "NM1":
            ent = parts[1].strip().upper() if len(parts) > 1 else ""
            if ent == "PR":
                out["payer"] = {"name": parts[3] if len(parts) > 3 else "", "id_qual": parts[8] if len(parts) > 8 else "", "id": parts[9] if len(parts) > 9 else ""}
            elif ent == "1P":
                out["provider"] = {"name": parts[3] if len(parts) > 3 else "", "id_qual": parts[8] if len(parts) > 8 else "", "id": parts[9] if len(parts) > 9 else ""}
            elif ent == "IL":
                out["subscriber"] = {"last": parts[3] if len(parts) > 3 else "", "first": parts[4] if len(parts) > 4 else "", "id_qual": parts[8] if len(parts) > 8 else "", "id": parts[9] if len(parts) > 9 else ""}
            elif ent == "QD":
                out["dependent"] = {"last": parts[3] if len(parts) > 3 else "", "first": parts[4] if len(parts) > 4 else "", "id_qual": parts[8] if len(parts) > 8 else "", "id": parts[9] if len(parts) > 9 else ""}

        elif tag == "TRN":
            out["trace"] = {"trace_type": parts[1] if len(parts) > 1 else "", "trace_num": parts[2] if len(parts) > 2 else ""}

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
            out["aaa"].append({"reject_code": parts[3] if len(parts) > 3 else "", "followup_action": parts[4] if len(parts) > 4 else ""})

        elif tag == "DTP":
            out["dtp"].append(parts)

        elif tag == "REF":
            out["ref"].append(parts)

    out["_validation"] = validate_envelopes(edi_text)

    # Convert EB and AAA into DataFrames
    out["_eb_df"] = pd.DataFrame(out["eb"]) if out["eb"] else pd.DataFrame()
    out["_aaa_df"] = pd.DataFrame(out["aaa"]) if out["aaa"] else pd.DataFrame()

    # Add summary reporting for EB data
    out["_summary"] = normalize_eb_for_reporting(out["eb"])

    return out

# ---------------- EB Normalizer ----------------
def normalize_eb_for_reporting(eb_rows: List[Dict]) -> Dict[str, Optional[str]]:
    summary = {"Active": None, "DeductibleRemaining": None, "CoinsurancePercent": None, "CopayAmount": None, "InNetwork": None}
    for r in eb_rows:
        if r.get("EB01") == "1":
            summary["Active"] = "Yes"
        if "deduct" in (r.get("PlanDesc", "") or "").lower():
            amt = r.get("BenefitAmt") or r["Raw"].get("E06", "")
            if amt: summary["DeductibleRemaining"] = amt
        if r.get("Percent"):
            summary["CoinsurancePercent"] = r["Percent"]
        if "copay" in (r.get("PlanDesc", "") or "").lower():
            amt = r.get("BenefitAmt") or r["Raw"].get("E06", "")
            if amt: summary["CopayAmount"] = amt
        if r.get("InPlan"):
            summary["InNetwork"] = "Yes" if r["InPlan"] == "Y" else ("No" if r["InPlan"] == "N" else None)
    return summary
