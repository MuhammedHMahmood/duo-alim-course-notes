"""Generate study notes from transcripts using Claude.

Supports two backends:
  --backend api    : Uses Anthropic API (requires API credits)
  --backend cli    : Uses Claude Code CLI via `npx` (uses Pro plan, no API credits)

Use --workers N to run N note generations in parallel (default: 1).
"""

import os
import json
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from common import (
    make_parser, resolve_classes, course_dir,
    load_template, get_settings,
)

SUBJECT_NAMES = {
    "tfs": "Tafseer",
    "hadith": "Hadith",
    "nahw": "Nahw",
    "sarf": "Sarf",
    "fqh": "Fiqh",
}


def _call_api(prompt, model):
    """Generate notes using Anthropic API (requires API credits)."""
    import anthropic
    from common import get_api_key

    client = anthropic.Anthropic(api_key=get_api_key("anthropic-api-key"))
    response = client.messages.create(
        model=model,
        max_tokens=8000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def _call_cli(prompt, model):
    """Generate notes using Claude Code CLI (uses Pro plan).

    Pipes the full prompt via stdin to avoid Windows command-line length limits.
    Uses --max-turns 1 to prevent agentic behavior.
    """
    CLAUDE_CMD = os.path.join(
        os.environ.get("USERPROFILE", ""), ".local", "bin", "claude.exe"
    )

    # Prepend explicit instruction to output notes directly
    full_prompt = (
        "OUTPUT ONLY THE STUDY NOTES IN MARKDOWN FORMAT. "
        "Do not describe what you would generate. Do not ask for permission. "
        "Do not include any preamble or commentary. "
        "Just output the formatted study notes directly.\n\n"
        + prompt
    )

    cmd = [
        CLAUDE_CMD, "-p",
        "--model", model,
        "--output-format", "text",
        "--max-turns", "1",
    ]

    env = os.environ.copy()
    env.pop("CLAUDECODE", None)
    env["PYTHONIOENCODING"] = "utf-8"

    result = subprocess.run(
        cmd, input=full_prompt, capture_output=True, text=True, env=env,
        timeout=600, encoding="utf-8",
    )

    stdout = result.stdout or ""
    stderr = result.stderr or ""

    if result.returncode != 0:
        raise RuntimeError(f"Claude CLI failed (exit {result.returncode}): {stderr[:500]}")

    output = stdout.strip()
    if not output:
        raise RuntimeError(f"Claude CLI returned empty output. stderr: {stderr[:300]}")

    return output


def _generate_single_note(subject, course, base_name, transcripts_dir, notes_dir, template, model, backend, label):
    """Generate a single note file. Returns (base_name, success, error_msg)."""
    print(f"  {label} Generating notes for {base_name}...")

    # Prefer plain text transcript (fewer tokens)
    plain_path = transcripts_dir / f"{base_name}.txt"
    if plain_path.exists():
        transcript_text = plain_path.read_text(encoding="utf-8")
    else:
        json_path = transcripts_dir / f"{base_name}.json"
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        transcript_text = data.get("text", "")

    prompt = _build_prompt(subject, course, base_name, transcript_text, template)

    try:
        if backend == "api":
            note_content = _call_api(prompt, model)
        else:
            note_content = _call_cli(prompt, model)

        note_path = notes_dir / f"{base_name}.md"
        note_path.write_text(note_content, encoding="utf-8")
        print(f"    Saved: {note_path.name}")
        return (base_name, True, None)
    except Exception as e:
        print(f"    ERROR ({base_name}): {e}")
        return (base_name, False, str(e))


def generate_notes_for_class(subject, course, settings, force=False, backend="cli", workers=1):
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

    total = len(remaining)
    print(f"[{subject} {course}] {total} notes to generate (backend: {backend}, workers: {workers})")
    new_notes = []

    if workers <= 1:
        # Sequential mode
        for i, transcript_file in enumerate(remaining, 1):
            base_name = os.path.splitext(transcript_file)[0]
            label = f"[{i}/{total}]"
            bn, ok, err = _generate_single_note(
                subject, course, base_name, transcripts_dir, notes_dir,
                template, model, backend, label,
            )
            if ok:
                new_notes.append(bn)
    else:
        # Parallel mode
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for i, transcript_file in enumerate(remaining, 1):
                base_name = os.path.splitext(transcript_file)[0]
                label = f"[{i}/{total}]"
                fut = executor.submit(
                    _generate_single_note,
                    subject, course, base_name, transcripts_dir, notes_dir,
                    template, model, backend, label,
                )
                futures[fut] = base_name

            for fut in as_completed(futures):
                bn, ok, err = fut.result()
                if ok:
                    new_notes.append(bn)

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
    parser.add_argument("--backend", choices=["api", "cli"], default="cli",
                        help="Backend to use: 'api' (Anthropic API) or 'cli' (Claude Code CLI, default)")
    parser.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1)")
    args = parser.parse_args()
    classes = resolve_classes(args)
    settings = get_settings()

    all_new = {}
    for subject, course, config in classes:
        new = generate_notes_for_class(
            subject, course, settings, args.force, args.backend, args.workers,
        )
        if new:
            all_new[(subject, course)] = new

    total = sum(len(v) for v in all_new.values())
    print(f"\nDone. Generated {total} new notes.")
    return all_new


if __name__ == "__main__":
    main()
