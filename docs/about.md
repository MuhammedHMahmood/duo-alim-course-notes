# How These Notes Are Made

These study notes are generated through a fully automated pipeline — from raw class recordings to a published website.

---

## Architecture

```mermaid
flowchart LR
    A[":material-microphone: Class Recording"] -->|Google Drive| B[":material-download: Fetch"]
    B -->|MP4/WebM files| C[":material-waveform: Whisper"]
    C -->|Transcript .txt| D[":material-brain: Claude AI"]
    D -->|Structured .md| E[":material-book-open: MkDocs"]
    E -->|Static HTML| F[":material-github: GitHub Pages"]

    style A fill:#1a5c4c,color:#fff
    style B fill:#2d8a73,color:#fff
    style C fill:#2d8a73,color:#fff
    style D fill:#c8963e,color:#fff
    style E fill:#2d8a73,color:#fff
    style F fill:#1a5c4c,color:#fff
```

---

## Pipeline Steps

### 1. Recording

Class recordings are uploaded to Google Drive by the course coordinators after each session. The pipeline monitors configured Drive folders for new files.

### 2. Transcription

Audio is extracted and transcribed using [OpenAI Whisper](https://github.com/openai/whisper) (large-v3-turbo model) with local GPU acceleration. The model handles mixed English/Arabic speech and produces timestamped plaintext transcripts.

### 3. Note Generation

Transcripts are processed by [Claude](https://claude.ai) (Anthropic's Claude Sonnet) using subject-specific prompt templates. Each template enforces a consistent structure:

- **Session overview** — high-level summary of the class
- **Key themes** — major topics covered
- **Detailed explanations** — organized by topic with Arabic terms, transliterations, and references
- **Practical takeaways** — actionable points for students

### 4. Publishing

The site is built with [MkDocs](https://www.mkdocs.org/) using the [Material for MkDocs](https://squidfunk.github.io/mkdocs-material/) theme. A build script syncs notes into the docs directory, generates course index pages, and updates the navigation. The site is deployed to GitHub Pages via `mkdocs gh-deploy`.

---

## Tech Stack

| Component | Tool |
|-----------|------|
| Transcription | OpenAI Whisper (large-v3-turbo) |
| Note generation | Claude Sonnet (Anthropic) |
| Site framework | MkDocs + Material theme |
| Hosting | GitHub Pages |
| Orchestration | Python pipeline scripts |
| Source control | Git + GitHub |
