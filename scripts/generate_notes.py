"""Generate study notes from transcripts using Claude API."""

import os
import json
from pathlib import Path

import anthropic

from common import (
    make_parser, resolve_classes, course_dir,
    load_template, get_settings, get_api_key
)

SUBJECT_NAMES = {
    "tfs": "Tafseer Foundation Series",
    "hadith": "Hadith Studies",
    "nahw": "Arabic Grammar (Nahw)",
    "sarf": "Arabic Morphology (Sarf)",
}


def generate_notes_for_class(subject, course, settings, force=False):
    """Generate notes for all sessions without notes. Returns list of new base names."""
    transcripts_dir = course_dir(subject, course, "transcripts")
    notes_dir = course_dir(subject, course, "notes")

    template = load_template(subject)
    model = settings.get("llm_model", "claude-sonnet-4-20250514")

    # Find transcripts (JSON) that don't have corresponding notes
    transcripts = sorted(
        f for f in os.listdir(transcripts_dir) if f.endswith(".json")
    )
    existing_notes = {
        f.replace(".md", "") for f in os.listdir(notes_dir) if f.endswith(".md")
    }

    remaining = [
        t for t in transcripts
        if os.path.splitext(t)[0] not in existing_notes or force
    ]

    if not remaining:
        print(f"[{subject} {course}] All notes up to date.")
        return []

    client = anthropic.Anthropic(api_key=get_api_key("anthropic-api-key"))
    new_notes = []

    for transcript_file in remaining:
        base_name = os.path.splitext(transcript_file)[0]
        print(f"  Generating notes for {base_name}...")

        # Prefer plain text transcript (fewer tokens)
        plain_path = transcripts_dir / f"{base_name}.txt"
        if plain_path.exists():
            transcript_text = plain_path.read_text(encoding="utf-8")
        else:
            json_path = transcripts_dir / transcript_file
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            transcript_text = data.get("text", "")

        prompt = _build_prompt(subject, course, base_name, transcript_text, template)

        response = client.messages.create(
            model=model,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )

        note_content = response.content[0].text
        note_path = notes_dir / f"{base_name}.md"
        note_path.write_text(note_content, encoding="utf-8")
        print(f"    Saved: {note_path.name}")
        new_notes.append(base_name)

    return new_notes


def _build_prompt(subject, course, date_str, transcript, template):
    """Build the LLM prompt for note generation."""
    subject_name = SUBJECT_NAMES.get(subject, subject.upper())

    return f"""You are an expert Islamic studies note-taker. Generate comprehensive, \
well-structured study notes from this class recording transcript.

**Class:** {subject_name} {course}
**Date:** {date_str}

Use the following template structure. Fill in every section based on the transcript \
content. If a section has no relevant content, write "Not covered in this session."

--- TEMPLATE ---
{template}
--- END TEMPLATE ---

--- TRANSCRIPT ---
{transcript}
--- END TRANSCRIPT ---

Generate the complete study notes now. Be thorough, accurate, and preserve all \
Arabic terms with their transliterations. Include all key points discussed."""


def main():
    parser = make_parser("Generate study notes from transcripts using AI")
    parser.add_argument("--force", action="store_true",
                        help="Regenerate notes even if they exist")
    args = parser.parse_args()
    classes = resolve_classes(args)
    settings = get_settings()

    all_new = {}
    for subject, course, config in classes:
        print(f"[{subject} {course}] Generating notes...")
        new = generate_notes_for_class(subject, course, settings, args.force)
        if new:
            all_new[(subject, course)] = new

    return all_new


if __name__ == "__main__":
    main()
