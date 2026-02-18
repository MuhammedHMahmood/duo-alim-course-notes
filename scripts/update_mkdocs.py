"""Sync study notes to docs/ and update mkdocs.yml navigation."""

import re
import shutil
import yaml
from datetime import datetime
from pathlib import Path

from common import load_config, SUBJECTS_DIR, DOCS_DIR, PROJECT_ROOT

SUBJECT_NAMES = {
    "tfs": "Tafseer",
    "hadith": "Hadith",
    "nahw": "Nahw",
    "sarf": "Sarf",
    "fqh": "Fiqh",
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


def _extract_topic(md_path):
    """Extract a short topic label from a note file for nav sidebar.

    Reads the first 20 lines and tries multiple extraction strategies:
    - Tafseer: Surah name (e.g., "Surah Al-Duha")
    - Hadith: Hadith number (e.g., "Hadith #20")
    - All: Bold terms, "focused on" / "covered" phrases, parenthetical
      Arabic terms, or first Key Theme from the Session Overview.
    """
    try:
        with open(md_path, "r", encoding="utf-8") as f:
            lines = [f.readline() for _ in range(40)]

        # --- Tafseer: Extract surah name ---
        for line in lines[:15]:
            line = line.strip()
            m = re.match(r'\*\*Surah Covered:\*\*\s*(.+)', line)
            if m:
                return _clean_surah_name(m.group(1))
            m = re.match(r'\*\*Surah:\*\*\s*(.+)', line)
            if m:
                return _clean_surah_name(m.group(1))
            m = re.match(r'##\s+Surah Covered:\s*(.+)', line)
            if m:
                return _clean_surah_name(m.group(1))
            m = re.match(r'##\s+(Surah\s+(?!Covered).+)', line)
            if m:
                return _clean_surah_name(m.group(1))

        # --- Extract Session Overview text ---
        overview_text = ""
        in_overview = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## Session Overview"):
                in_overview = True
                continue
            if in_overview:
                if stripped.startswith("---") or stripped.startswith("##"):
                    break
                overview_text += stripped + " "

        if overview_text:
            topic = _topic_from_overview(overview_text)
            if topic:
                return topic

        # --- Extract first Key Theme as last resort ---
        in_themes = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("## Key Themes"):
                in_themes = True
                continue
            if in_themes:
                if stripped.startswith("---") or stripped.startswith("##"):
                    break
                # Look for "- **Topic**: description" or "- Topic"
                m = re.match(r'-\s+\*\*([^*]+)\*\*', stripped)
                if m:
                    return _truncate(m.group(1), 30)
                m = re.match(r'-\s+(.+?)(?::|$)', stripped)
                if m and len(m.group(1).strip()) > 3:
                    return _truncate(m.group(1).strip(), 40)

        # --- Surah in heading fallback ---
        for line in lines[:15]:
            line = line.strip()
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                m = re.search(r'(Surah\s+\S+(?:\s+\S+)?)', title)
                if m:
                    return _clean_surah_name(m.group(1))

    except Exception:
        pass
    return None


def _topic_from_overview(text):
    """Extract a short topic label from the Session Overview paragraph."""

    # --- Hadith number ---
    m = re.search(r'[Hh]adith\s*(?:#|No\.?\s*|number\s*)(\d+)', text)
    if m:
        return f"Hadith #{m.group(1)}"

    # --- Bold terms (most specific) ---
    bold = re.findall(r'\*\*([^*]+)\*\*', text)
    if bold:
        return _truncate(bold[0], 30)

    # --- "focused on" / "covering" / "covered" pattern ---
    # e.g. "focused on the nullifiers of wudu and the obligations of ghusl"
    # e.g. "covered fi'il mudareh (present/future tense verbs)"
    for pattern in [
        r'(?:focused|focusing)\s+on\s+(?:the\s+)?(?:concept\s+of\s+)?(.+?)(?:\.|,\s+(?:and|with|the instructor|the class|ranging|including|examining|emphasizing))',
        r'(?:covered|covering)\s+(?:the\s+)?(.+?)(?:\.|,\s+(?:and|with|the instructor|the class|ranging|including|focusing))',
        r'(?:introduced?|introducing)\s+(?:the\s+)?(.+?)(?:\.|,\s+(?:and|with|the))',
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            topic = m.group(1).strip()
            # Extract parenthetical Arabic term if present
            arabic = _extract_parenthetical(topic)
            if arabic:
                return _truncate(arabic, 30)
            # Clean up the English topic
            topic = _clean_topic_phrase(topic)
            if topic and len(topic) > 2:
                return _truncate(topic, 30)

    # --- "Introduction to X" pattern ---
    m = re.search(r'[Ii]ntroduction\s+to\s+(.+?)(?:\.|,|\()', text)
    if m:
        topic = m.group(1).strip()
        arabic = _extract_parenthetical(topic + text[m.end():m.end()+50])
        if arabic:
            return _truncate(f"Intro to {arabic}", 30)
        return _truncate(f"Intro to {_clean_topic_phrase(topic)}", 30)

    # --- "about [topic]" pattern ---
    m = re.search(r'about\s+(?:the\s+)?(.+?)(?:\.|,|\()', text)
    if m:
        topic = _clean_topic_phrase(m.group(1).strip())
        if topic and len(topic) > 2:
            return _truncate(topic, 30)

    # --- Parenthetical Arabic terms anywhere in overview ---
    # e.g. "(wudu)", "(ghusl)", "(istinja)", "(bid'a)"
    parens = re.findall(r'\(([a-z][a-z\' -]{2,25})\)', text, re.IGNORECASE)
    # Filter out common non-topic parentheticals
    skip = {'e.g', 'i.e', 'fard', 'wajib', 'sunnah', 'nafl', 'pbuh',
            'may allah', 'rahmatullahi', 'peace be upon him'}
    for p in parens:
        if p.lower() not in skip and not p[0].isupper():
            return _truncate(p[0].upper() + p[1:], 30)

    return None


def _extract_parenthetical(text):
    """Extract a short Arabic term from parentheses, e.g. '(ghusl)' -> 'Ghusl'."""
    m = re.search(r'\(([a-z][a-z\' -]{2,30})\)', text, re.IGNORECASE)
    if m:
        term = m.group(1).strip()
        skip = {'e.g', 'i.e', 'fard', 'wajib', 'sunnah', 'nafl'}
        if term.lower() not in skip:
            return term[0].upper() + term[1:]
    return None


def _clean_topic_phrase(topic):
    """Clean a topic phrase to a short, readable label."""
    # Remove leading articles and filler words
    topic = re.sub(
        r'^(?:the\s+)?(?:concept\s+of\s+|importance\s+of\s+|'
        r'significance\s+of\s+|foundations?\s+of\s+|'
        r'fundamentals?\s+of\s+|basics?\s+of\s+)?(?:the\s+)?',
        '', topic, flags=re.IGNORECASE,
    ).strip()
    # Capitalize first letter
    if topic:
        topic = topic[0].upper() + topic[1:]
    return topic


def _truncate(text, max_len):
    """Truncate text to max_len, adding '...' if needed."""
    text = text.strip()
    if len(text) > max_len:
        return text[:max_len - 3] + "..."
    return text


def _clean_surah_name(raw):
    """Clean up a surah name to a short display label.

    'Surah Al-Duha (Chapter 93), with references...' -> 'Surah Al-Duha'
    'Surah Al-Asr (Completion of Tafseer)' -> 'Surah Al-Asr (contd.)'
    """
    # Remove markdown formatting
    raw = raw.replace("*", "").strip()

    # Extract just "Surah X" or "Surah Al-X"
    m = re.match(r'(Surah\s+(?:Al[- ]|At[- ]|Az[- ]|Ad[- ])?[\w\'-]+)', raw)
    if m:
        name = m.group(1)
    else:
        name = raw

    # Check if it's a continuation
    lower = raw.lower()
    if "contd" in lower or "continuation" in lower or "continued" in lower or "completion" in lower:
        name += " (contd.)"
    elif "part" in lower or "session" in lower or "segment" in lower:
        # Extract part number
        pm = re.search(r'(?:part|session|segment)\s*(\d+)', lower)
        if pm:
            name += f" (Part {pm.group(1)})"
    elif "ayat" in lower or "ayaat" in lower:
        # Extract ayah range
        am = re.search(r'(?:ayat|ayaat)\s*([\d\-]+)', lower)
        if am:
            name += f" (Ayat {am.group(1)})"

    # Truncate if too long
    if len(name) > 50:
        name = name[:47] + "..."

    return name


def generate_course_index(subject, course, docs_course_dir, class_meta):
    """Generate an index.md for a course with a table of sessions."""
    meta = class_meta.get((subject, course), {})
    semester = meta.get("semester", "")
    course_name = meta.get("name", f"{subject.upper()} {course}")
    teacher = meta.get("teacher", "")

    title = f"{subject.upper()} {course}"
    if semester:
        title += f" ({semester})"

    rows = []
    for note_file in sorted(docs_course_dir.glob("*.md")):
        if note_file.name == "index.md":
            continue
        date_str = note_file.stem
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            date_display = dt.strftime("%b %d, %Y")
        except ValueError:
            date_display = date_str

        topic = _extract_topic(note_file) or "\u2014"
        rows.append(f"| [{date_display}]({note_file.name}) | {topic} |")

    if not rows:
        return

    # Build metadata line
    meta_parts = [f"**{course_name}**"]
    if semester:
        meta_parts.append(f"**Semester:** {semester}")
    if teacher:
        meta_parts.append(f"**Teacher:** {teacher}")
    meta_parts.append(f"**Sessions:** {len(rows)}")
    meta_line = " &nbsp;|&nbsp; ".join(meta_parts)

    content = f"""# {title}

{meta_line}

---

| Date | Topic |
|------|-------|
{chr(10).join(rows)}
"""

    index_path = docs_course_dir / "index.md"
    index_path.write_text(content, encoding="utf-8")


def build_nav():
    """Build mkdocs.yml nav structure from docs/ directory.

    Top-level structure:
      - Home (index.md)
      - Course Archive (archive.md)  — links to all courses
      - About (about.md)             — pipeline / architecture
      - One section per subject containing course sub-sections
    """
    nav = [
        {"Home": "index.md"},
        {"Course Archive": "archive.md"},
        {"About": "about.md"},
    ]
    config = load_config()

    class_meta = {}
    for c in config["classes"]:
        key = (c["subject"], c["course"])
        class_meta[key] = c

    for subject_dir in sorted(DOCS_DIR.iterdir()):
        if not subject_dir.is_dir():
            continue
        subject = subject_dir.name
        if subject in ("stylesheets", "assets", "javascripts"):
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

            # Generate the course index page
            generate_course_index(subject, course, course_dir, class_meta)

            course_nav = []
            # First entry: the course overview/index
            course_nav.append({"Overview": f"{subject}/{course}/index.md"})

            for note_file in sorted(course_dir.glob("*.md")):
                if note_file.name == "index.md":
                    continue
                date_str = note_file.stem
                try:
                    dt = datetime.strptime(date_str, "%Y-%m-%d")
                    display = dt.strftime("%b %d")
                except ValueError:
                    display = date_str

                topic = _extract_topic(note_file)
                if topic:
                    label = f"{display} - {topic}"
                else:
                    label = display

                rel_path = f"{subject}/{course}/{note_file.name}"
                course_nav.append({label: rel_path})

            if course_nav:
                subject_nav.append({course_display: course_nav})

        if subject_nav:
            nav.append({subject_display: subject_nav})

    return nav


def update_mkdocs_yml(nav):
    """Update the mkdocs.yml file with new navigation.

    Uses text-level replacement to preserve !!python/name: tags and other
    special YAML constructs that yaml.safe_load cannot parse.
    """
    mkdocs_path = PROJECT_ROOT / "mkdocs.yml"

    with open(mkdocs_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Render the new nav section as YAML text
    nav_yaml = yaml.dump({"nav": nav}, default_flow_style=False,
                         allow_unicode=True, sort_keys=False)

    # Replace everything from "nav:" to end of file (nav is always last)
    import re
    content = re.sub(r'^nav:.*', nav_yaml.rstrip(), content, flags=re.DOTALL | re.MULTILINE)

    with open(mkdocs_path, "w", encoding="utf-8") as f:
        f.write(content)


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
