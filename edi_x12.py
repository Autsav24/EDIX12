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

# ---------------- Hierarchical 271 Parser ----------------
def parse_271(edi_text: str) -> Dict:
    seg_t, elem_t, _ = detect_delimiters(edi_text)
    segs = parse_segments(edi_text, seg_t, elem_t)
    out = {"payer": {}, "provider": {}, "subscriber": {}, "dependent": {},
           "eb": {"payer": [], "provider": [], "subscriber": [], "dependent": []},
           "aaa": [], "trace": {}, "dtp": [], "ref": [], "_debug": {}}
    current_context = None

    for parts in segs:
        if not parts:
            continue
        tag = parts[0].upper()

        if tag == "HL":
            if len(parts) > 3:
                code = parts[3]
                current_context = {
                    "20": "payer",
                    "21": "provider",
                    "22": "subscriber",
                    "23": "dependent"
                }.get(code, None)
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

# ---------------- Flatten to Table + Excel ----------------
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
            coverage_status = EB01_MAP.get(eb.get("EB01", ""), "")
            eligibility_start, eligibility_end = "", ""
            for dtp in parsed.get("dtp", []):
                if len(dtp.get("data", [])) >= 4 and dtp["data"][1] == "291":
                    val = dtp["data"][3]
                    if "-" in val:
                        eligibility_start, eligibility_end = val.split("-", 1)
                    else:
                        eligibility_start = val

            rejection_code, rejection_msg = "", ""
            for aaa in parsed.get("aaa", []):
                if aaa.get("context") == ctx:
                    rejection_code = aaa.get("reject_code", "")
                    rejection_msg = aaa.get("followup_action", "")

            results.append({
                "PayerName": payer_name,
                "PayerID": payer_id,
                "ProviderName": provider_name,
                "ProviderNPI": provider_npi,
                "TraceNumber": trace_number,
                "SubscriberID": sub_id,
                "MemberFirstName": sub_first,
                "MemberLastName": sub_last,
                "DependentFirstName": dep_first,
                "DependentLastName": dep_last,
                "DependentID": dep_id,
                "EligibilityStart": eligibility_start,
                "EligibilityEnd": eligibility_end,
                "CoverageStatus": coverage_status,
                "CoverageLevel": eb.get("EB02", ""),
                "ServiceTypeCode": eb.get("ServiceType", ""),
                "InsuranceType": eb.get("PlanDesc", ""),
                "Description": eb.get("TimePeriod", ""),
                "TimeQualifier": eb.get("BenefitAmt", ""),
                "BenefitAmount": eb.get("Percent", ""),
                "QuantityQualifier": eb.get("QtyQual", ""),
                "QuantityValue": eb.get("Qty", ""),
                "RejectionCode": rejection_code,
                "RejectionMsg": rejection_msg,
                "Context": ctx,
            })

    if output_excel:
        df = pd.DataFrame(results)
        os.makedirs(os.path.dirname(output_excel), exist_ok=True)
        df.to_excel(output_excel, index=False)
        print(f"✅ Saved {len(results)} rows to {output_excel}")

    return results
