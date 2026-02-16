"""Sync study notes to docs/ and update mkdocs.yml navigation."""

import shutil
import yaml
from datetime import datetime
from pathlib import Path

from common import load_config, SUBJECTS_DIR, DOCS_DIR, PROJECT_ROOT

SUBJECT_NAMES = {
    "tfs": "Tafseer (TFS)",
    "hadith": "Hadith Studies",
    "nahw": "Arabic Grammar (Nahw)",
    "sarf": "Arabic Morphology (Sarf)",
}


def sync_notes_to_docs():
    """Copy all notes from subjects/*/notes/ to docs/{subject}/{course}/."""
    for subject_dir in sorted(SUBJECTS_DIR.iterdir()):
        if not subject_dir.is_dir():
            continue
        subject = subject_dir.name

        for course_dir in sorted(subject_dir.iterdir()):
            if not course_dir.is_dir():
                continue
            course = course_dir.name
            notes_dir = course_dir / "notes"

            if not notes_dir.exists():
                continue

            notes = list(notes_dir.glob("*.md"))
            if not notes:
                continue

            docs_dest = DOCS_DIR / subject / course
            docs_dest.mkdir(parents=True, exist_ok=True)

            for note_file in notes:
                shutil.copy2(note_file, docs_dest / note_file.name)


def build_nav():
    """Build mkdocs.yml nav structure from docs/ directory."""
    nav = [{"Home": "index.md"}]
    config = load_config()

    # Build lookup for class metadata
    class_meta = {}
    for c in config["classes"]:
        key = (c["subject"], c["course"])
        class_meta[key] = c

    for subject_dir in sorted(DOCS_DIR.iterdir()):
        if not subject_dir.is_dir():
            continue
        subject = subject_dir.name
        if subject in ("stylesheets", "assets"):
            continue

        subject_display = SUBJECT_NAMES.get(subject, subject.upper())
        subject_nav = []

        for course_dir in sorted(subject_dir.iterdir()):
            if not course_dir.is_dir():
                continue
            course = course_dir.name

            meta = class_meta.get((subject, course), {})
            semester = meta.get("semester", "")
            course_display = f"{subject.upper()} {course}"
            if semester:
                course_display += f" ({semester})"

            course_nav = []
            for note_file in sorted(course_dir.glob("*.md")):
                date_str = note_file.stem
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    display = dt.strftime("%b %d")
                except ValueError:
                    display = date_str

                title = _extract_title(note_file)
                if title:
                    label = f"{display} - {title}"
                else:
                    label = display

                rel_path = f"{subject}/{course}/{note_file.name}"
                course_nav.append({label: rel_path})

            if course_nav:
                subject_nav.append({course_display: course_nav})

        if subject_nav:
            nav.append({subject_display: subject_nav})

    return nav


def _extract_title(md_path):
    """Extract a short title from the first heading of a markdown file."""
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("# "):
                    title = line.lstrip("# ").strip()
                    # Try to extract just the surah/topic name
                    if " - " in title:
                        title = title.split(" - ", 1)[1].strip()
                    if len(title) > 60:
                        title = title[:57] + "..."
                    return title
    except Exception:
        pass
    return None


def update_mkdocs_yml(nav):
    """Update the mkdocs.yml file with new navigation."""
    mkdocs_path = PROJECT_ROOT / "mkdocs.yml"

    with open(mkdocs_path, "r", encoding="utf-8") as f:
        mkdocs_config = yaml.safe_load(f)

    mkdocs_config["nav"] = nav

    with open(mkdocs_path, "w", encoding="utf-8") as f:
        yaml.dump(mkdocs_config, f, default_flow_style=False,
                  allow_unicode=True, sort_keys=False)


def main():
    print("Syncing notes to docs/...")
    sync_notes_to_docs()

    print("Building navigation...")
    nav = build_nav()

    print("Updating mkdocs.yml...")
    update_mkdocs_yml(nav)

    print("Done. Run 'mkdocs serve' to preview.")


if __name__ == "__main__":
    main()
