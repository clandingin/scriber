# Clinical session note — checkbox resolver

Local Python pipeline that takes an **A:/B:** doctor/patient transcript plus a
diagnosis, and resolves **checkbox / checkmark** fields on a clinical session
note. Free-text sections and the C-SSRS block are **out of scope**.

Matching is **keyword-first** with an optional small **sentence-transformer**
(`all-MiniLM-L6-v2`) fallback. No cloud LLM; audio/transcript never leave the machine.

## Quick start

```bat
cd note_resolver
python -m venv .venv
.venv\Scripts\pip install -U pip
.venv\Scripts\pip install -e .

REM UI (paste transcript + diagnosis, or upload .txt)
.venv\Scripts\streamlit run app.py

REM CLI
.venv\Scripts\python -m note_resolver -t examples\sample_transcript.txt -d "F32.1 Major depressive disorder, moderate" -v
```

On first embedding run, `sentence-transformers` may download **model weights only**.

## Input

| Field | Format |
|-------|--------|
| Transcript | Lines like `A: …` (doctor) and `B: …` (patient) |
| Diagnosis | Free text, e.g. `F32.1 — Major depressive disorder, single episode, moderate` |

## Pipeline stages (swappable modules)

1. `pipeline/parser.py` — turns → `(speaker, index, text)`
2. `pipeline/indexer.py` — topical A→B spans + MiniLM embeddings
3. `pipeline/matcher.py` — keyword then semantic mention match + polarity
4. `pipeline/radio3.py` — Endorses / Denies / Not selected + citation
5. `pipeline/multi_tag.py` — per-tag checkboxes; default/WNL if none match
6. `pipeline/rollup.py` — derived checkboxes from child results
7. `pipeline/assembler.py` — structured payload + plain-text form dump

Orchestration: `runner.py` (`run_pipeline`).

## Config

Edit `note_resolver/config/fields.json` to add/change fields. Each field has
`type`: `RADIO3` | `MULTI_TAG` | `ROLLUP`, keyword hints, and (for rollups)
`children` + `rule` (`all_denies` | `all_default_only`).

Sections included in this pass: Substance Use, History of Harm, Risk Assessment,
Mental Status Exam.

## Chrome extension

The Tab Transcriber popup can open a **Note checkboxes** panel and call the
local helper (`resolve_note` WebSocket message). Keep `helper/` and
`note_resolver/` side by side in the repo (or `pip install -e note_resolver`
into the helper venv) so the helper can import the pipeline.

1. Start the helper as usual
2. Capture / load an A:/B: transcript in the extension
3. Click **Note checkboxes** → enter diagnosis → **Resolve checkboxes**
4. The text form dump appears in the extension UI


```
[   Denies    ]  Alcohol
    citation: [turn 3] B: No, I don't drink at all.
[X] ROLLUP  Denies all substance use  (rule=all_denies)
```

RADIO3 / MULTI_TAG cite transcript turn index + text. ROLLUP cites child field
results only.
