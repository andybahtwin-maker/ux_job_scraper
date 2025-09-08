import os, subprocess, shlex, time, pathlib
import streamlit as st
import pandas as pd

PROJECT_DIR = pathlib.Path(__file__).resolve().parent
BOOTSTRAP = PROJECT_DIR / "se_bootstrap.sh"
DATA_CSV  = PROJECT_DIR / "data" / "filtered_jobs.csv"

st.set_page_config(page_title="ApplyPilot Ultra — SE/SC Finder", layout="wide")

st.title("ApplyPilot Ultra — SE/SC Finder")
st.caption("Minimal GUI wrapper for your existing pipeline")

with st.form("controls", clear_on_submit=False):
    col1, col2, col3 = st.columns(3)

    with col1:
        keywords = st.text_input("Keywords (comma or space separated)", 
                                 value="sales engineer, solutions engineer, solutions consultant, pre-sales, presales, technical sales engineer, technical account manager, customer engineer, implementation engineer, field applications engineer, solutions architect, value engineer")
        include_countries = st.text_input("Include countries (CSV, optional)", value="")
        exclude_countries = st.text_input("Exclude countries (CSV, optional)", value="")

    with col2:
        days = st.number_input("Days back", min_value=1, max_value=365, value=30, step=1)
        max_jobs = st.number_input("Max to collect", min_value=10, max_value=5000, value=150, step=10)
        min_score = st.slider("Min score", min_value=0, max_value=100, value=45, step=1)

    with col3:
        loose = st.checkbox("Loose mode", value=True)
        strict = st.checkbox("Strict mode", value=False)
        no_arch = st.checkbox("Drop Architect-heavy titles", value=True)
        do_print = st.checkbox("Print table to console", value=True)
        do_email = st.checkbox("Send email", value=False)

    submitted = st.form_submit_button("Run Search")

# Build and run the command when submitted
if submitted:
    if not BOOTSTRAP.exists():
        st.error(f"Bootstrap script not found: {BOOTSTRAP}")
        st.stop()

    # Assemble CLI
    args = [str(BOOTSTRAP)]
    if do_print: args.append("--print")
    if do_email: args.append("--email")
    args += ["--max", str(max_jobs), "--days", str(days), "--min-score", str(min_score)]
    if loose:  args.append("--loose")
    if strict: args.append("--strict")
    # keywords / include / exclude are optional flags in your script; pass only if provided
    if keywords.strip():
        args += ["-k", keywords.strip()]
    if include_countries.strip():
        args += ["--include-countries", include_countries.strip()]
    if exclude_countries.strip():
        args += ["--exclude-countries", exclude_countries.strip()]

    # Environment: enable architect suppression via env (works even if CLI flag isn’t present)
    env = os.environ.copy()
    env["NO_ARCHITECT"] = "1" if no_arch else "0"

    st.write("**Command**:", " ".join(shlex.quote(a) for a in args))
    with st.spinner("Collecting jobs…"):
        try:
            # Stream logs to the UI
            proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=env)
            log_lines = []
            log_area = st.empty()
            for line in iter(proc.stdout.readline, ""):
                log_lines.append(line.rstrip("\n"))
                # Throttle updates a bit for performance
                if len(log_lines) % 5 == 0:
                    log_area.code("\n".join(log_lines[-400:]), language="bash")
            proc.wait()
            log_area.code("\n".join(log_lines[-400:]), language="bash")
            if proc.returncode != 0:
                st.error(f"Pipeline exited with code {proc.returncode}. See logs above.")
        except Exception as e:
            st.exception(e)

    # Load and show results if present
    if DATA_CSV.exists():
        try:
            df = pd.read_csv(DATA_CSV)
            st.success(f"Loaded {len(df)} jobs from {DATA_CSV}")
            st.dataframe(df, use_container_width=True)
            st.download_button("Download CSV", df.to_csv(index=False).encode("utf-8"), file_name="filtered_jobs.csv", mime="text/csv")
        except Exception as e:
            st.warning(f"Could not read CSV: {e}")
    else:
        st.info("No CSV found yet; check the logs for details.")
