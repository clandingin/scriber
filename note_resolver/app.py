"""Minimal Streamlit UI: paste or upload transcript + diagnosis → text report."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from note_resolver.runner import run_pipeline  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

SAMPLE_TRANSCRIPT = """A: Good morning, how have you been feeling this week?
B: I've been pretty depressed and anxious most days.
A: Any alcohol use?
B: No, I don't drink at all.
A: Tobacco or smoking?
B: No cigarettes.
A: Cannabis or other drugs — marijuana, cocaine, opioids, meth?
B: No, I deny all of that. No drugs.
A: Any thoughts of suicide or wish to be dead?
B: No suicidal thoughts. I want to live for my kids.
A: Any history of suicide attempts or self-harm?
B: No attempts and I don't cut.
A: Any thoughts of harming others or violent behavior?
B: No, never.
A: How is your attention and memory?
B: Attention is okay, memory is fine.
A: Mood and affect today — thought process linear? Any voices or delusions?
B: I feel sad but I'm thinking clearly, no voices or delusions.
A: Do you feel supported by family? Engaged in treatment?
B: Yes, my family is very supportive and I'm engaged in treatment.
"""


def main() -> None:
    st.set_page_config(page_title="Note Checkbox Resolver", layout="wide")
    st.title("Clinical note checkbox resolver")
    st.caption(
        "Local pipeline (keyword + optional MiniLM). Resolves RADIO3 / MULTI_TAG / ROLLUP "
        "fields only — free-text and C-SSRS are out of scope."
    )

    if "transcript" not in st.session_state:
        st.session_state["transcript"] = SAMPLE_TRANSCRIPT
    if "diagnosis" not in st.session_state:
        st.session_state["diagnosis"] = (
            "F32.1 — Major depressive disorder, single episode, moderate"
        )

    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("1. Transcript (A: doctor / B: patient)")
        uploaded = st.file_uploader("Upload transcript .txt", type=["txt"])
        if st.button("Load uploaded .txt into transcript box", type="secondary"):
            if uploaded is None:
                st.warning("Choose a .txt file first.")
            else:
                st.session_state["transcript"] = uploaded.read().decode(
                    "utf-8", errors="replace"
                )
                st.success("Transcript loaded from file.")

        transcript = st.text_area(
            "Or paste transcript here",
            value=st.session_state["transcript"],
            height=420,
        )
        st.session_state["transcript"] = transcript

    with col_r:
        st.subheader("2. Diagnosis")
        diagnosis = st.text_area(
            "Diagnosis code + label",
            value=st.session_state["diagnosis"],
            height=100,
        )
        st.session_state["diagnosis"] = diagnosis

        use_embeddings = st.checkbox(
            "Use local sentence-transformer embeddings (falls back to keywords)",
            value=True,
        )

        st.subheader("3. Resolve")
        run = st.button("Resolve checkboxes", type="primary")

    if run:
        with st.spinner("Running local pipeline…"):
            _note, report = run_pipeline(
                st.session_state["transcript"],
                st.session_state["diagnosis"],
                enable_embeddings=use_embeddings,
            )
        st.subheader("Form answers (text representation)")
        st.text_area("Resolved fields", value=report, height=560)
        st.download_button(
            "Download report .txt",
            data=report,
            file_name="note_checkbox_resolution.txt",
            mime="text/plain",
        )


if __name__ == "__main__":
    main()
