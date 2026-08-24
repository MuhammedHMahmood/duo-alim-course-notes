"""Generate a weekly self-test quiz across all active classes.

Combines every session note from the past 7 days (across every active class)
into one quiz testing concepts and vocabulary, using the same CLI/API
backends as generate_notes.py.
"""

from datetime import datetime, timedelta

from common import get_active_classes, CONFIG_DIR, PROJECT_ROOT
from generate_notes import _call_api, _call_cli, SUBJECT_NAMES

WEEKLY_DIR = PROJECT_ROOT / "weekly" / "reviews"


def load_weekly_template():
    template_path = CONFIG_DIR / "templates" / "weekly_review.md"
    return template_path.read_text(encoding="utf-8")


def _week_range(reference_date=None):
    """Return (start, end) dates for the Mon-Sun calendar week most recently
    completed on or before reference_date (defaults to today).

    Snapping to the nearest Sunday (rather than treating reference_date itself
    as the end of the window) means running this on any day of the week always
    lands on the same file for that week, instead of producing a new
    near-duplicate every time the reference day shifts.
    """
    ref = reference_date or datetime.now().date()
    end = ref - timedelta(days=(ref.weekday() + 1) % 7)  # snap back to the last Sunday
    start = end - timedelta(days=6)
    return start, end


def collect_week_sessions(start, end):
    """Gather (subject, course, date_str, note_text) for every note dated
    within [start, end] across active classes, oldest first."""
    sessions = []
    for cls in get_active_classes():
        subject, course = cls["subject"], cls["course"]
        notes_dir = PROJECT_ROOT / "subjects" / subject / course / "notes"
        if not notes_dir.exists():
            continue
        for note_file in notes_dir.glob("*.md"):
            try:
                dt = datetime.strptime(note_file.stem, "%Y-%m-%d").date()
            except ValueError:
                continue
            if start <= dt <= end:
                sessions.append(
                    (subject, course, note_file.stem, note_file.read_text(encoding="utf-8"))
                )
    sessions.sort(key=lambda s: s[2])
    return sessions


def _build_prompt(start, end, sessions, template):
    date_range = f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"

    blocks = []
    for subject, course, date_str, text in sessions:
        subject_name = SUBJECT_NAMES.get(subject, subject.upper())
        blocks.append(f"--- {subject_name} {course} — {date_str} ---\n{text}")
    sessions_text = "\n\n".join(blocks)

    return f"""You are creating a self-test quiz for a student in the DUO 6-year Alim \
course, covering everything taught this week ({date_range}).

Use the following template structure for the quiz. It shows one subject section \
as an example — repeat that section for each subject/course represented below.

--- TEMPLATE ---
{template}
--- END TEMPLATE ---

Base every question strictly on the study notes below — do not invent content \
outside them. Cover both concepts (grammar rules, fiqh rulings, tafseer points, \
hadith lessons, as applicable to each subject) and vocabulary.

--- THIS WEEK'S NOTES ---
{sessions_text}
--- END THIS WEEK'S NOTES ---

Generate the complete quiz now, with the date range "{date_range}" in the title."""


def generate_weekly_review(settings, backend="cli", reference_date=None, force=False):
    """Generate the weekly review quiz for the 7-day window ending on
    reference_date (defaults to today). Returns the output Path, or None if
    skipped (already exists, or no sessions this week)."""
    start, end = _week_range(reference_date)
    out_path = WEEKLY_DIR / f"{end.isoformat()}.md"

    if out_path.exists() and not force:
        print(f"[weekly-review] {out_path.name} already exists, skipping.")
        return None

    sessions = collect_week_sessions(start, end)
    if not sessions:
        print(f"[weekly-review] No sessions between {start} and {end}, skipping.")
        return None

    template = load_weekly_template()
    model = settings.get("llm_model", "claude-sonnet-4-6")
    prompt = _build_prompt(start, end, sessions, template)

    print(f"[weekly-review] Generating quiz for {len(sessions)} session(s), {start} to {end}...")
    if backend == "api":
        content = _call_api(prompt, model)
    else:
        content = _call_cli(prompt, model)

    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"[weekly-review] Saved: {out_path}")
    return out_path
