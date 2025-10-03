# app.py
import io, os, json, zipfile
import streamlit as st
from datetime import datetime, timedelta
from edi_x12 import (
    Provider, Party, build_270, parse_271, ServiceTypeMap,
    PAYER_PROFILES, normalize_eb_for_reporting
)

st.set_page_config(page_title="X12 EDI – 270/271 (Profiles)", page_icon="📡", layout="wide")

# ---------------- Profiles (UI-managed) ----------------
PROFILES_FILE = "profiles.json"

def load_profiles() -> dict:
    """Merge built-in profiles from edi_x12 with any user-defined profiles saved on disk."""
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

st.title("📡 X12 EDI – 270/271 (Profile-ready MVP)")

# ---------------- Manage Profiles Panel ----------------
with st.expander("⚙️ Manage Payer Profiles"):
    profiles = st.session_state.profiles
    keys = list(profiles.keys())
    sel_idx = keys.index("default") if "default" in keys else 0
    sel = st.selectbox("Select profile to view/edit", options=keys, index=sel_idx)

    cur = profiles.get(sel, {})
    col1, col2, col3 = st.columns(3)
    with col1:
        new_key = st.text_input("Profile key (unique ID)", value=sel)
        preferred_eq = st.text_input("Preferred EQ (comma-separated)", value=",".join(cur.get("preferred_eq", ["30"])))
        id_qual = st.text_input("ID Qualifier (e.g., MI)", value=cur.get("id_qual", "MI"))
    with col2:
        require_dmg = st.checkbox("Require DMG (DOB/Gender)", value=cur.get("require_dmg", False))
        expect_trn = st.checkbox("Include TRN", value=cur.get("expect_trn", True))
        include_prv = st.checkbox("Include PRV (taxonomy)", value=cur.get("include_prv", False))
        provider_taxonomy = st.text_input("Provider Taxonomy (PRV03)", value=cur.get("provider_taxonomy", ""))
    with col3:
        include_addresses = st.checkbox("Include Addresses (N3/N4)", value=cur.get("include_addresses", False))
        extra_ref = st.text_input("Extra REF codes (comma-separated)", value=",".join(cur.get("extra_ref", [])))
        subscriber_is_primary = st.checkbox("Subscriber is Primary", value=cur.get("subscriber_is_primary", True))

    c1, c2, c3, c4 = st.columns([1,1,1,1])
    with c1:
        if st.button("💾 Save/Update Profile"):
            profiles[new_key] = {
                "preferred_eq": [x.strip() for x in preferred_eq.split(",") if x.strip()],
                "require_dmg": require_dmg,
                "expect_trn": expect_trn,
                "id_qual": id_qual.strip() or "MI",
                "subscriber_is_primary": subscriber_is_primary,
                "extra_ref": [x.strip() for x in extra_ref.split(",") if x.strip()],
                "include_prv": include_prv,
                "provider_taxonomy": provider_taxonomy.strip(),
                "include_addresses": include_addresses,
            }
            if new_key != sel and sel in profiles:
                del profiles[sel]
            save_profiles(profiles)
            st.success(f"Profile '{new_key}' saved.")
    with c2:
        if st.button("🗑️ Delete Profile", disabled=(sel == "default")):
            if sel != "default" and sel in profiles:
                del profiles[sel]
                save_profiles(profiles)
                st.success(f"Profile '{sel}' deleted.")
    with c3:
        exported = json.dumps(profiles, indent=2, ensure_ascii=False).encode("utf-8")
        st.download_button("⬇️ Export All Profiles (JSON)", data=exported, file_name="profiles.json", mime="application/json")
    with c4:
        up = st.file_uploader("Import Profiles (JSON)", type=["json"], label_visibility="collapsed")
        if up:
            try:
                imported = json.loads(up.read().decode("utf-8"))
                for k, v in imported.items():
                    profiles[k] = v
                save_profiles(profiles)
                st.success("Profiles imported and saved.")
            except Exception as e:
                st.error(f"Import failed: {e}")

# ---------------- Robust decoder ----------------
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

def normalize_punctuation(text: str) -> str:
    return (text.replace("\u2013", "-").replace("\u2014", "-")
                .replace("\u2018", "'").replace("\u2019", "'")
                .replace("\u201c", '"').replace("\u201d", '"')
                .replace("\u00a0", " "))

# ---------------- Tabs ----------------
tab_build, tab_parse, tab_help = st.tabs(["Build 270", "Parse 271", "Help & Notes"])

# ===== Build 270 (profile-aware, PRV + N3/N4) =====
with tab_build:
    st.subheader("Build a 270 Request")

    profiles = st.session_state.profiles
    pkeys = list(profiles.keys())
    pidx = pkeys.index("default") if "default" in pkeys else 0
    profile_key = st.selectbox("Payer Profile", options=pkeys, index=pidx)
    profile = profiles[profile_key]

    colA, colB, colC = st.columns([1,1,1])
    with colA:
        payer_id = st.text_input("Payer ID (PI)", value="12345")
        prov_name = st.text_input("Provider Name", value="Buddha Clinic")
        npi = st.text_input("Provider NPI", value="1234567890")
    with colB:
        subscriber_last = st.text_input("Subscriber Last Name", value="DOE")
        subscriber_first = st.text_input("Subscriber First Name", value="JOHN")
        subscriber_id = st.text_input("Subscriber Member ID", value="W123456789")
        trn_trace = st.text_input("TRN Trace (optional)", value="TRACE12345")
    with colC:
        default_eq = profile.get("preferred_eq", ["30"])
        service_types = st.multiselect(
            "Service Type Codes (EQ)",
            options=list(ServiceTypeMap.keys()),
            default=default_eq,
            format_func=lambda x: f"{x} – {ServiceTypeMap.get(x,'')}"
        )
        dt_start = st.date_input("Eligibility Start", datetime.today().date())
        ranged = st.checkbox("Use Date Range (RD8)", value=True)
        dt_end = st.date_input("Eligibility End", datetime.today().date() + timedelta(days=30)) if ranged else None

    with st.expander("Provider Details (PRV + Address)"):
        include_prv = st.checkbox("Include PRV (taxonomy)", value=profile.get("include_prv", False))
        provider_taxonomy = st.text_input("Provider Taxonomy (PRV03)", value=profile.get("provider_taxonomy",""))
        include_addresses = st.checkbox("Include Addresses (N3/N4)", value=profile.get("include_addresses", False))

        st.caption("Provider Address (optional)")
        p_line1 = st.text_input("Provider Address Line 1", value="")
        p_line2 = st.text_input("Provider Address Line 2", value="")
        p_city  = st.text_input("Provider City", value="")
        p_state = st.text_input("Provider State (2-letter)", value="")
        p_zip   = st.text_input("Provider ZIP", value="")

    with st.expander("Subscriber Demographics & Address"):
        require_dmg = profile.get("require_dmg", False)
        dmg_dob = st.text_input("DOB (YYYYMMDD)", value="19800101" if require_dmg else "")
        dmg_gender = st.selectbox("Gender", ["", "M", "F", "U"], index=0 if not require_dmg else 3)

        st.caption("Subscriber Address (optional, used if 'Include Addresses' is checked)")
        s_line1 = st.text_input("Subscriber Address Line 1", value="")
        s_line2 = st.text_input("Subscriber Address Line 2", value="")
        s_city  = st.text_input("Subscriber City", value="")
        s_state = st.text_input("Subscriber State (2-letter)", value="")
        s_zip   = st.text_input("Subscriber ZIP", value="")

    with st.expander("Dependent (optional)"):
        use_dependent = st.checkbox("Query Dependent?", value=False)
        dep_last = st.text_input("Dependent Last Name", value="") if use_dependent else ""
        dep_first = st.text_input("Dependent First Name", value="") if use_dependent else ""
        dep_id = st.text_input("Dependent ID", value="") if use_dependent else ""

    if st.button("Generate 270"):
        provider = Provider(name=prov_name, npi=npi)
        subscriber = Party(last=subscriber_last, first=subscriber_first, id_code=subscriber_id, id_qual=profile.get("id_qual","MI"))
        dependent = None
        if use_dependent:
            dependent = Party(last=dep_last, first=dep_first, id_code=dep_id, id_qual=profile.get("id_qual","MI"))

        prov_addr = {"line1": p_line1, "line2": p_line2, "city": p_city, "state": p_state, "zip": p_zip}
        subs_addr = {"line1": s_line1, "line2": s_line2, "city": s_city, "state": s_state, "zip": s_zip}

        edi270 = build_270(
            isa_ctrl=1, gs_ctrl=1, st_ctrl=1,
            payer_id=payer_id,
            provider=provider,
            subscriber=subscriber,
            dependent=dependent,
            service_types=service_types,
            date_start=dt_start.strftime("%Y%m%d"),
            date_end=dt_end.strftime("%Y%m%d") if ranged and dt_end else None,
            profile=profile,
            trn_trace=trn_trace if profile.get("expect_trn") else None,
            dmg_dob=dmg_dob or None,
            dmg_gender=dmg_gender or None,
            include_prv=include_prv,
            provider_taxonomy=provider_taxonomy,
            include_addresses=include_addresses,
            provider_addr=prov_addr if any(prov_addr.values()) else None,
            subscriber_addr=subs_addr if any(subs_addr.values()) else None,
        )

        st.write("### Generated 270")
        st.code(edi270, language="plain")

        # Optional: quick replace for REF placeholders via UI
        with st.expander("Replace REF placeholders (optional)"):
            extra_ref_codes = profile.get("extra_ref", [])
            if extra_ref_codes:
                cols = st.columns(len(extra_ref_codes))
                ref_vals = {}
                for i, code in enumerate(extra_ref_codes):
                    ref_vals[code] = cols[i].text_input(f"REF*{code} value", value="")
                if st.button("Apply REF values"):
                    for code, val in ref_vals.items():
                        if val:
                            edi270 = edi270.replace(f"REF*{code}*PLACEHOLDER", f"REF*{code}*{val}")
                    st.code(edi270, language="plain")

        st.download_button(
            "⬇️ Download 270",
            data=edi270.encode("utf-8"),
            file_name=f"270_{subscriber_last}_{datetime.now().strftime('%Y%m%d%H%M')}.x12",
            mime="text/plain"
        )

# ===== Parse 271 =====
with tab_parse:
    st.subheader("Parse a 271 Response")

    uploaded = st.file_uploader("Upload 271 (text/X12 or ZIP)", type=["x12","edi","txt","dat","zip"])
    if uploaded:
        raw = uploaded.read()

        if uploaded.name.lower().endswith(".zip"):
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as zf:
                    names = [n for n in zf.namelist() if not n.endswith("/")]
                    if not names:
                        st.error("ZIP has no files"); st.stop()
                    raw = zf.read(names[0])
            except zipfile.BadZipFile:
                st.error("Uploaded file looks like a ZIP but couldn't be opened.")
                st.stop()

        try:
            content = normalize_punctuation(robust_decode(raw))
        except ValueError as e:
            st.error(str(e)); st.stop()

        parsed = parse_271(content)

        with st.expander("🔎 Debug parser info"):
            dbg = parsed.get("_debug", {})
            st.write({
                "segment_terminator": dbg.get("segment_terminator"),
                "element_separator": dbg.get("element_separator"),
                "segment_count": dbg.get("segment_count"),
                "first_tags": dbg.get("first_tags"),
            })
            st.code(content[:400].replace("\r", "\\r").replace("\n", "\\n\n"))

        if parsed.get("_validation"):
            st.warning("Validation: " + "; ".join(parsed["_validation"]))

        st.write("### Payer")
        st.json(parsed.get("payer", {}))

        st.write("### Provider")
        st.json(parsed.get("provider", {}))

        st.write("### Subscriber")
        st.json(parsed.get("subscriber", {}))

        if parsed.get("dependent"):
            st.write("### Dependent")
            st.json(parsed.get("dependent", {}))

        st.write("### Benefit (EB) Segments")
        if parsed.get("eb"):
            st.dataframe(parsed["eb"], use_container_width=True)
            st.write("### Quick Summary (heuristic)")
            st.json(normalize_eb_for_reporting(parsed["eb"]))
        else:
            st.info("No EB segments found. Check AAA segments or try service type EQ=30.")

        if parsed.get("aaa"):
            st.write("### Rejections (AAA)")
            st.dataframe(parsed["aaa"], use_container_width=True)

        if parsed.get("dtp"):
            st.write("### DTP (Dates)")
            st.dataframe(parsed["dtp"], use_container_width=True)

        if parsed.get("ref"):
            st.write("### REF (References)")
            st.dataframe(parsed["ref"], use_container_width=True)

        st.write("### Raw 271 (first 2000 chars)")
        preview = content[:2000] + ("...\n" if len(content) > 2000 else "")
        st.code(preview, language="plain")

# ===== Help =====
with tab_help:
    st.markdown("""
### What this app does
- **Build 270** (005010X279A1): profile-aware envelopes, optional PRV (taxonomy) and N3/N4 addresses, extra REF codes.
- **Parse 271**: robust delimiter/encoding handling; shows NM1/EB/AAA/DTP/REF, plus a quick eligibility summary.
- **Profiles**: create/edit/delete/import/export payer profiles from the UI (saved to `profiles.json`).

### Tips
- Many payers prefer `EQ=30`. If you get no EB rows, try just 30.
- Use real DOB/Gender in **DMG** if the payer requires it.
- Replace `REF*..*PLACEHOLDER` with real IDs via the “Replace REF placeholders” expander.

### Security
Treat member data as PHI. Use secure storage/transport when you go beyond testing.
""")
