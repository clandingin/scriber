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
A: Mood and affect today look congruent; thought process linear?
B: Yeah I feel sad but I'm thinking clearly, no voices or delusions.
A: Do you feel supported by family?
B: Yes, my family is very supportive and I'm engaged in treatment.
"""


def main() -> None:
    st.set_page_config(page_title="Note Checkbox Resolver", layout="wide")
    st.title("Clinical note checkbox resolver")
    st.caption(
        "Local pipeline (keyword + MiniLM). Resolves RADIO3 / MULTI_TAG / ROLLUP "
        "fields only — free-text and C-SSRS are out of scope."
    )

    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Transcript (A: doctor / B: patient)")
        uploaded = st.file_uploader(
            "Upload transcript .txt",
            type=["txt"],
            help="Optional. Uploading fills the transcript box below.",
        )
        if uploaded is not None:
            text = uploaded.read().decode("utf-8", errors="replace")
            st.session_state["transcript"] = text

        transcript = st.text_area(
            "Paste transcript",
            value=st.session_state.get("transcript", SAMPLE_TRANSCRIPT),
            height=420,
            key="transcript_area",
        )

        if st.button("Load uploaded / pasted transcript into resolver", type="secondary"):
            st.session_state["transcript"] = transcript
            st.success(f"Transcript ready ({len(transcript.splitlines())} lines).")

    with col_r:
        st.subheader("Diagnosis")
        diagnosis = st.text_area(
            "Diagnosis code + label",
            value=st.session_state.get("diagnosis", "F32.1 — Major depressive disorder, single episode, moderate"),
            height=100,
            key="diagnosis_area",
        )
        use_embeddings = st.checkbox(
            "Use local sentence-transformer embeddings (fallback if unavailable)",
            value=True,
        )
        run = st.button("Resolve checkboxes", type="primary")

    if run:
        with st.spinner("Running local pipeline…"):
            _note, report = run_pipeline(
                transcript,
                diagnosis,
                enable_embeddings=use_embeddings,
            )
        st.subheader("Form answers (text)")
        st.text_area("Resolved fields", value=report, height=560)
        st.download_button(
            "Download report .txt",
            data=report,
            file_name="note_checkbox_resolution.txt",
            mime="text/plain",
        )


if __name__ == "__main__":
    main()
