"""Generate the weekly review (condensed recap) and weekly quiz (multiple choice).

Each is built independently from every session note in the Mon-Sun week across
all active classes, using the same CLI/API backends as generate_notes.py.

  weekly/reviews/{week-ending}.md   condensed recap per class (markdown)
  weekly/quizzes/{week-ending}.json multiple-choice quiz (rendered by update_mkdocs)
"""

import json
import random
from datetime import datetime, timedelta

from common import get_active_classes, CONFIG_DIR, PROJECT_ROOT
from generate_notes import _call_api, _call_cli, SUBJECT_NAMES

WEEKLY_DIR = PROJECT_ROOT / "weekly" / "reviews"
QUIZ_DIR = PROJECT_ROOT / "weekly" / "quizzes"

QUIZ_OPTIONS = 4
QUIZ_SCHEMA = """{"sections": [{"title": "Nahw 201", "questions": [
  {"type": "concept", "question": "...", "options": ["...", "...", "...", "..."],
   "answer": 0, "explanation": "..."}]}]}"""


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


def date_range_label(start, end):
    return f"{start.strftime('%b %d')} - {end.strftime('%b %d, %Y')}"


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


def _sessions_text(sessions):
    blocks = []
    for subject, course, date_str, text in sessions:
        subject_name = SUBJECT_NAMES.get(subject, subject.upper())
        blocks.append(f"--- {subject_name} {course} — {date_str} ---\n{text}")
    return "\n\n".join(blocks)


def _call_llm(prompt, settings, backend, output_kind=None, max_tokens=8000):
    model = settings.get("llm_model", "claude-sonnet-4-6")
    if backend == "api":
        return _call_api(prompt, model, max_tokens=max_tokens)
    if output_kind:
        return _call_cli(prompt, model, output_kind=output_kind)
    return _call_cli(prompt, model)


# --- Weekly review (condensed recap) -------------------------------------------------

def _build_digest_prompt(start, end, sessions, template):
    date_range = date_range_label(start, end)
    return f"""You are writing a condensed weekly recap for a student in the DUO 6-year \
Alim course, covering everything taught this week ({date_range}). The student will read \
this to refresh the week's material before taking a quiz, so it should be short enough to \
read in about ten minutes and clear enough to learn from.

Use the following template structure. It shows one class section as an example — repeat \
that section for each subject/course represented below.

--- TEMPLATE ---
{template}
--- END TEMPLATE ---

Base everything strictly on the study notes below — do not add content from outside them. \
Condense: merge repeated points across sessions, drop anecdotes and filler, and keep the \
rules, rulings, explanations and terms a student must remember. Preserve Arabic terms with \
their transliterations.

--- THIS WEEK'S NOTES ---
{_sessions_text(sessions)}
--- END THIS WEEK'S NOTES ---

Generate the complete weekly review now, with the date range "{date_range}" in the title. \
Do not include any links."""


def build_digest(settings, backend, start, end, sessions):
    prompt = _build_digest_prompt(start, end, sessions, load_weekly_template())
    return _call_llm(prompt, settings, backend)


# --- Weekly quiz (multiple choice) ----------------------------------------------------

def _build_quiz_prompt(start, end, sessions):
    date_range = date_range_label(start, end)
    return f"""You are creating a multiple-choice quiz for a student in the DUO 6-year Alim \
course, covering everything taught this week ({date_range}). The student has read the \
notes once, not memorized them: questions should check understanding of the main ideas and \
terms from this week's lessons, and the right answer should be recognizable from the \
lesson. Avoid trick questions and obscure details.

Output ONLY a JSON object (no prose, no code fences) shaped like this:
{QUIZ_SCHEMA}

Rules:
- One section per class (subject + course) that had a session this week; "title" is e.g. "Nahw 201".
- In each section: 5 questions with "type": "concept" (rules, rulings, explanations, meanings of \
ayat or hadith), then 5 with "type": "vocab" (an Arabic term and its meaning or usage, or a \
meaning and its term).
- Exactly {QUIZ_OPTIONS} options per question, exactly one correct. "answer" is the 0-based index of the \
correct option.
- Distractors must be plausible: related terms, rules or rulings from the same notes. Keep \
options similar in length. Never use "all of the above" or "none of the above".
- "explanation" is 1-2 sentences on why the answer is right.
- Use Arabic script (with harakat where the notes have them) for Arabic terms; everything else in English.
- Base every question strictly on the notes below.

--- THIS WEEK'S NOTES ---
{_sessions_text(sessions)}
--- END THIS WEEK'S NOTES ---"""


def parse_quiz(raw, start, end):
    """Parse and validate model output into the stored quiz structure.

    Drops malformed questions, shuffles each question's options (models favour
    putting the right answer in the same slot), and raises ValueError if nothing
    usable is left.
    """
    text = raw.strip()
    first = text.find("{")
    if first == -1:
        raise ValueError("no JSON object in model output")
    data, _ = json.JSONDecoder().raw_decode(text, first)  # ignores any trailing commentary

    rng = random.Random(end.isoformat())
    sections = []
    for sec in data.get("sections", []):
        questions = []
        for q in sec.get("questions", []):
            opts, ans = q.get("options"), q.get("answer")
            question = str(q.get("question", "")).strip()
            if not question or not isinstance(opts, list) or not 2 <= len(opts) <= 6:
                continue
            opts = [str(o).strip() for o in opts]
            if len(set(opts)) != len(opts) or "" in opts:
                continue
            if isinstance(ans, bool) or not isinstance(ans, int) or not 0 <= ans < len(opts):
                continue
            correct = opts[ans]
            rng.shuffle(opts)
            questions.append({
                "type": "vocab" if q.get("type") == "vocab" else "concept",
                "question": question,
                "options": opts,
                "answer": opts.index(correct),
                "explanation": str(q.get("explanation", "")).strip(),
            })
        if questions:
            sections.append({"title": str(sec.get("title", "")).strip(), "questions": questions})

    if not sections:
        raise ValueError("no valid questions in model output")
    return {"week_start": start.isoformat(), "week_end": end.isoformat(), "sections": sections}


def quiz_from_prompt(prompt, settings, backend, start, end, attempts=2):
    """Call the model for quiz JSON, retrying once on unparseable output."""
    last_err = None
    for attempt in range(1, attempts + 1):
        raw = _call_llm(prompt, settings, backend, output_kind="A SINGLE JSON OBJECT",
                        max_tokens=16000)
        try:
            return parse_quiz(raw, start, end)
        except ValueError as e:  # json.JSONDecodeError is a ValueError
            last_err = e
            print(f"[weekly-quiz] quiz output invalid (attempt {attempt}/{attempts}): {e}")
    raise RuntimeError(f"Could not generate a valid quiz: {last_err}")


def build_quiz(settings, backend, start, end, sessions):
    return quiz_from_prompt(_build_quiz_prompt(start, end, sessions), settings, backend, start, end)


def write_quiz(end, quiz):
    QUIZ_DIR.mkdir(parents=True, exist_ok=True)
    path = QUIZ_DIR / f"{end.isoformat()}.json"
    path.write_text(json.dumps(quiz, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


# --- Orchestration --------------------------------------------------------------------

def _week_to_generate(reference_date, path_for, force, tag):
    """Resolve the Mon-Sun week most recently completed on or before reference_date
    (defaults to today) and its sessions. Returns (start, end, path, sessions), or
    None if the page already exists (and not force) or the week had no sessions."""
    start, end = _week_range(reference_date)
    path = path_for(end)
    if path.exists() and not force:
        print(f"[{tag}] {path.name} already exists, skipping.")
        return None
    sessions = collect_week_sessions(start, end)
    if not sessions:
        print(f"[{tag}] No sessions between {start} and {end}, skipping.")
        return None
    print(f"[{tag}] {len(sessions)} session(s), {start} to {end}")
    return start, end, path, sessions


def generate_weekly_review(settings, backend="cli", reference_date=None, force=False):
    """Generate that week's review page. Returns its Path, or None if skipped."""
    week = _week_to_generate(reference_date, lambda end: WEEKLY_DIR / f"{end.isoformat()}.md",
                             force, "weekly-review")
    if not week:
        return None
    start, end, path, sessions = week

    content = build_digest(settings, backend, start, end, sessions)
    WEEKLY_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"[weekly-review] Saved: {path}")
    return path


def generate_weekly_quiz(settings, backend="cli", reference_date=None, force=False):
    """Generate that week's quiz. Returns its Path, or None if skipped."""
    week = _week_to_generate(reference_date, lambda end: QUIZ_DIR / f"{end.isoformat()}.json",
                             force, "weekly-quiz")
    if not week:
        return None
    start, end, _, sessions = week

    quiz = build_quiz(settings, backend, start, end, sessions)
    path = write_quiz(end, quiz)
    n = sum(len(s["questions"]) for s in quiz["sections"])
    print(f"[weekly-quiz] Saved: {path} ({n} questions)")
    return path
