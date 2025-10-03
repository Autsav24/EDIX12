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

# ---------------- Manage Profiles Panel (unique keys) ----------------
with st.expander("⚙️ Manage Payer Profiles"):
    profiles = st.session_state.profiles
    keys = list(profiles.keys())
    sel_idx = keys.index("default") if "default" in keys else 0
    sel = st.selectbox("Select profile to view/edit", options=keys, index=sel_idx, key="mp_select_profile")

    cur = profiles.get(sel, {})
    col1, col2, col3 = st.columns(3)
    with col1:
        new_key = st.text_input("Profile key (unique ID)", value=sel, key="mp_profile_key")
        preferred_eq = st.text_input("Preferred EQ (comma-separated)", value=",".join(cur.get("preferred_eq", ["30"])), key="mp_preferred_eq")
        id_qual = st.text_input("ID Qualifier (e.g., MI)", value=cur.get("id_qual", "MI"), key="mp_id_qual")
    with col2:
        require_dmg = st.checkbox("Require DMG (DOB/Gender)", value=cur.get("require_dmg", False), key="mp_require_dmg")
        dep_require_dmg = st.checkbox("Dependent requires DMG", value=cur.get("dependent_require_dmg", False), key="mp_dep_require_dmg")
        dep_id_required = st.checkbox("Dependent ID required (NM109)", value=cur.get("dependent_id_required", False), key="mp_dep_id_required")
        expect_trn = st.checkbox("Include TRN", value=cur.get("expect_trn", True), key="mp_expect_trn")
    with col3:
        include_prv_mp = st.checkbox("Include PRV (taxonomy)", value=cur.get("include_prv", False), key="mp_include_prv")
        provider_taxonomy_mp = st.text_input("Provider Taxonomy (PRV03)", value=cur.get("provider_taxonomy", ""), key="mp_provider_taxonomy")
        include_addresses_mp = st.checkbox("Include Addresses (N3/N4)", value=cur.get("include_addresses", False), key="mp_include_addresses")
        extra_ref = st.text_input("Extra REF codes (comma-separated)", value=",".join(cur.get("extra_ref", [])), key="mp_extra_ref")

    subscriber_is_primary = st.checkbox("Subscriber is Primary", value=cur.get("subscriber_is_primary", True), key="mp_sub_is_primary")

    c1, c2, c3, c4 = st.columns([1,1,1,1])
    with c1:
        if st.button("💾 Save/Update Profile", key="mp_save"):
            profiles[new_key] = {
                "preferred_eq": [x.strip() for x in preferred_eq.split(",") if x.strip()],
                "require_dmg": require_dmg,
                "dependent_require_dmg": dep_require_dmg,
                "dependent_id_required": dep_id_required,
                "expect_trn": expect_trn,
                "id_qual": id_qual.strip() or "MI",
                "subscriber_is_primary": subscriber_is_primary,
                "extra_ref": [x.strip() for x in extra_ref.split(",") if x.strip()],
                "include_prv": include_prv_mp,
                "provider_taxonomy": provider_taxonomy_mp.strip(),
                "include_addresses": include_addresses_mp,
            }
            if new_key != sel and sel in profiles:
                del profiles[sel]
            save_profiles(profiles)
            st.success(f"Profile '{new_key}' saved.", icon="✅")
    with c2:
        if st.button("🗑️ Delete Profile", disabled=(sel == "default"), key="mp_delete"):
            if sel != "default" and sel in profiles:
                del profiles[sel]
                save_profiles(profiles)
                st.success(f"Profile '{sel}' deleted.", icon="🗑️")
    with c3:
        exported = json.dumps(profiles, indent=2, ensure_ascii=False).encode("utf-8")
        st.download_button("⬇️ Export All Profiles (JSON)", data=exported, file_name="profiles.json", mime="application/json", key="mp_export")
    with c4:
        up = st.file_uploader("Import Profiles (JSON)", type=["json"], label_visibility="collapsed", key="mp_import")
        if up:
            try:
                imported = json.loads(up.read().decode("utf-8"))
                for k, v in imported.items():
                    profiles[k] = v
                save_profiles(profiles)
                st.success("Profiles imported and saved.", icon="📥")
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

# ===== Build 270 =====
with tab_build:
    st.subheader("Build a 270 Request")

    profiles = st.session_state.profiles
    pkeys = list(profiles.keys())
    pidx = pkeys.index("default") if "default" in pkeys else 0
    profile_key = st.selectbox("Payer Profile", options=pkeys, index=pidx, key="b_profile_select")
    profile = profiles[profile_key]

    colA, colB, colC = st.columns([1,1,1])
    with colA:
        payer_id = st.text_input("Payer ID (PI)", value="12345", key="b_payer_id")
        prov_name = st.text_input("Provider Name", value="Buddha Clinic", key="b_prov_name")
        npi = st.text_input("Provider NPI", value="1234567890", key="b_npi")
    with colB:
        subscriber_last = st.text_input("Subscriber Last Name", value="DOE", key="b_sub_last")
        subscriber_first = st.text_input("Subscriber First Name", value="JOHN", key="b_sub_first")
        subscriber_id = st.text_input("Subscriber Member ID", value="W123456789", key="b_sub_id")
        trn_trace = st.text_input("TRN Trace (optional)", value="TRACE12345", key="b_trn")
    with colC:
        default_eq = profile.get("preferred_eq", ["30"])
        service_types = st.multiselect(
            "Service Type Codes (EQ)",
            options=list(ServiceTypeMap.keys()),
            default=default_eq,
            format_func=lambda x: f"{x} – {ServiceTypeMap.get(x,'')}",
            key="b_eq_multiselect"
        )
        dt_start = st.date_input("Eligibility Start", datetime.today().date(), key="b_dt_start")
        ranged = st.checkbox("Use Date Range (RD8)", value=True, key="b_ranged")
        dt_end = st.date_input("Eligibility End", datetime.today().date() + timedelta(days=30), key="b_dt_end") if ranged else None

    # Provider details
    with st.expander("Provider Details (PRV + Address)"):
        include_prv = st.checkbox("Include PRV (taxonomy)", value=profile.get("include_prv", False), key="b_include_prv")
        provider_taxonomy = st.text_input("Provider Taxonomy (PRV03)", value=profile.get("provider_taxonomy",""), key="b_provider_taxonomy")
        include_addresses = st.checkbox("Include Addresses (N3/N4)", value=profile.get("include_addresses", False), key="b_include_addresses")

        st.caption("Provider Address (optional)")
        p_line1 = st.text_input("Provider Address Line 1", value="", key="b_p_line1")
        p_line2 = st.text_input("Provider Address Line 2", value="", key="b_p_line2")
        p_city  = st.text_input("Provider City", value="", key="b_p_city")
        p_state = st.text_input("Provider State (2-letter)", value="", key="b_p_state")
        p_zip   = st.text_input("Provider ZIP", value="", key="b_p_zip")

    # Subscriber DMG + address
    with st.expander("Subscriber Demographics & Address"):
        require_dmg = profile.get("require_dmg", False)
        dmg_dob = st.text_input("Subscriber DOB (YYYYMMDD)", value="19800101" if require_dmg else "", key="b_dmg_dob")
        dmg_gender = st.selectbox("Subscriber Gender", ["", "M", "F", "U"], index=0 if not require_dmg else 3, key="b_dmg_gender")

        st.caption("Subscriber Address (optional, used if 'Include Addresses' is checked)")
        s_line1 = st.text_input("Subscriber Address Line 1", value="", key="b_s_line1")
        s_line2 = st.text_input("Subscriber Address Line 2", value="", key="b_s_line2")
        s_city  = st.text_input("Subscriber City", value="", key="b_s_city")
        s_state = st.text_input("Subscriber State (2-letter)", value="", key="b_s_state")
        s_zip   = st.text_input("Subscriber ZIP", value="", key="b_s_zip")

    # Dependent loop
    with st.expander("Dependent (optional)"):
        use_dependent = st.checkbox("Query Dependent?", value=False, key="b_dep_use")
        dep_last = st.text_input("Dependent Last Name", value="", key="b_dep_last") if use_dependent else ""
        dep_first = st.text_input("Dependent First Name", value="", key="b_dep_first") if use_dependent else ""
        dep_id = st.text_input("Dependent ID (NM109) – leave blank if none", value="", key="b_dep_id") if use_dependent else ""
        dep_dmg_dob = st.text_input("Dependent DOB (YYYYMMDD)", value="", key="b_dep_dob") if use_dependent else ""
        dep_dmg_gender = st.selectbox("Dependent Gender", ["", "M", "F", "U"], index=0, key="b_dep_gender") if use_dependent else ""

    if st.button("Generate 270", key="b_generate"):
        provider = Provider(name=prov_name, npi=npi)
        subscriber = Party(last=subscriber_last, first=subscriber_first, id_code=subscriber_id, id_qual=profile.get("id_qual","MI"))

        dependent = None
        if use_dependent:
            dependent = Party(last=dep_last, first=dep_first, id_code=dep_id or "", id_qual=profile.get("id_qual","MI"))

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
            dep_dmg_dob=dep_dmg_dob or None,
            dep_dmg_gender=dep_dmg_gender or None,
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
                    ref_vals[code] = cols[i].text_input(f"REF*{code} value", value="", key=f"b_ref_{code}")
                if st.button("Apply REF values", key="b_apply_ref"):
                    for code, val in ref_vals.items():
                        if val:
                            edi270 = edi270.replace(f"REF*{code}*PLACEHOLDER", f"REF*{code}*{val}")
                    st.code(edi270, language="plain")

        st.download_button(
            "⬇️ Download 270",
            data=edi270.encode("utf-8"),
            file_name=f"270_{subscriber_last}_{datetime.now().strftime('%Y%m%d%H%M')}.x12",
            mime="text/plain",
            key="b_download"
        )

# ===== Parse 271 =====
with tab_parse:
    st.subheader("Parse a 271 Response")

    uploaded = st.file_uploader("Upload 271 (text/X12 or ZIP)", type=["x12","edi","txt","dat","zip"], key="p_upload")
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
### What changed (for dependents)
- Builder now **omits `MI*`** when a dependent ID is not supplied (prevents invalid `MI*` with blank ID).
- Added **Dependent DMG** inputs and support. If your profile sets `dependent_require_dmg=True`, the builder will always include `DMG` for 2100D.
- Two new profile flags:
  - `dependent_require_dmg`: enforce dependent DOB/Gender
  - `dependent_id_required`: (advisory) if you set this to True but don't supply an ID, the 270 is still syntactically valid but your payer may reject it.

### Tips
- If a payer requires dependent ID, make sure you fill **Dependent ID (NM109)**.
- Many payers accept dependent **name + DOB/Gender** without a separate ID—use that when you don’t have a dependent ID.
- If you get no EB back, try **EQ=30** only.

### Security
Treat member data as PHI. Use secure storage/transport when moving beyond testing.
""")
