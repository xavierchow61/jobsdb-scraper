"""Manual repro test for URL ↔ session_state sync.

Run with:
    python -m streamlit run _test_url_sync.py

Then in the browser:
  1. Change the slider — URL should update with ?score=X
  2. Note the URL, then change to another page (none here, but simulate
     by opening a new tab to the same URL).
"""

import streamlit as st

st.title("URL sync test")

# Read URL
url_score = st.query_params.get("score")
st.write(f"URL `?score=` raw value: `{url_score!r}`")

# Init session state from URL
if "score" not in st.session_state:
    st.session_state.score = float(url_score) if url_score else 0.0

st.write(f"Before widget: session_state.score = `{st.session_state.score}`")

# Slider widget
score = st.slider("Score", 0.0, 100.0, st.session_state.score, key="score")

st.write(f"After widget: session_state.score = `{st.session_state.score}`")

# Sync session_state to URL
if st.session_state.score != 0:
    st.query_params["score"] = str(st.session_state.score)
else:
    if "score" in st.query_params:
        del st.query_params["score"]

# Display current URL params
st.divider()
st.write("**Current st.query_params:**")
st.json({k: st.query_params[k] for k in st.query_params})
