"""Transcribe video recordings using faster-whisper.

--backend cuda (default) uses a dedicated virtual environment with GPU-compatible
PyTorch for CUDA acceleration on RTX 5080 (Blackwell / sm_120) — the home machine.
--backend cpu runs the same whisper_worker.py under the current interpreter instead,
using faster-whisper's int8 CPU path — no GPU needed, used by the GitHub Actions runner.
"""

import os
import json
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from common import make_parser, resolve_classes, course_dir, get_settings

# Whisper runs in a separate venv with CUDA 12.8 PyTorch for RTX 5080 support
WHISPER_PYTHON = r"C:\Users\moham\whisper-env\Scripts\python.exe"
WHISPER_WORKER = str(Path(__file__).parent / "whisper_worker.py")

# faster-whisper uses "large-v3" where openai-whisper used "large-v3-turbo"
_MODEL_MAP = {"large-v3-turbo": "large-v3"}

_SEGMENT_RE = re.compile(r'^\[(\d+:\d{2}\.\d+) --> (\d+:\d{2}\.\d+)\]')


def _parse_ts(ts):
    m, s = ts.split(':')
    return float(m) * 60 + float(s)


def _fmt_time(secs):
    m, s = divmod(int(secs), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _get_duration(video_path):
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        val = r.stdout.strip()
        return float(val) if val and val != "N/A" else None
    except Exception:
        return None


def _run_whisper_with_progress(cmd, env, partial_path, duration=None):
    """Run Whisper with live progress via --verbose segment output. Returns (returncode, stderr_text)."""
    process = subprocess.Popen(
        cmd, env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    stderr_lines = []

    def read_stderr():
        for line in process.stderr:
            stderr_lines.append(line.rstrip())

    def read_stdout():
        last_print = 0.0
        for line in process.stdout:
            line = line.rstrip()
            m = _SEGMENT_RE.match(line)
            if m:
                now = time.time()
                if now - last_print >= 2.0:
                    pos = _parse_ts(m.group(2))
                    if duration:
                        pct = min(100, int(pos / duration * 100))
                        print(f"\r    {pct}%  [{_fmt_time(pos)} / {_fmt_time(duration)}]   ", end="", flush=True)
                    else:
                        print(f"\r    [{_fmt_time(pos)} transcribed]   ", end="", flush=True)
                    last_print = now
            elif line:
                print(f"\n    {line}", flush=True)

    t_err = threading.Thread(target=read_stderr, daemon=True)
    t_out = threading.Thread(target=read_stdout, daemon=True)
    t_err.start()
    t_out.start()
    try:
        process.wait()
    except (KeyboardInterrupt, Exception):
        process.kill()
        process.wait()
        raise
    finally:
        t_err.join(timeout=2)
        t_out.join(timeout=2)
        print()
        if process.returncode != 0 and os.path.exists(partial_path):
            os.remove(partial_path)

    return process.returncode, "\n".join(stderr_lines)


def transcribe_for_class(subject, course, settings, backend="cuda"):
    """Transcribe all untranscribed videos for a class. Returns list of new base names.

    backend: "cuda" (default) runs whisper_worker.py in the dedicated GPU venv on the
    home machine. "cpu" runs the same worker under the current interpreter instead — no
    GPU needed, used by the free GitHub Actions runner (faster-whisper's int8 CPU path is
    fast enough for the ~1 new video/day this normally sees).
    """
    videos_dir = course_dir(subject, course, "videos")
    transcripts_dir = course_dir(subject, course, "transcripts")
    notes_dir = course_dir(subject, course, "notes")

    model = settings.get("whisper_model", "large-v3-turbo")

    videos = sorted(
        f for f in os.listdir(videos_dir)
        if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm"))
    )

    # A session whose note is already committed is done even if its transcript isn't
    # present locally — cloud routine runs start from a fresh checkout each time, so only
    # committed notes persist across runs.
    already_done = {
        f.replace(".json", "")
        for f in os.listdir(transcripts_dir) if f.endswith(".json")
    } | {
        f.replace(".md", "")
        for f in os.listdir(notes_dir) if f.endswith(".md")
    }

    # If a combined transcript exists for a date, treat its part videos as done too
    # e.g. 2026-01-30.json means 2026-01-30-p1 and 2026-01-30-p2 are already covered
    part_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})-p\d+$')
    for video_base in [os.path.splitext(v)[0] for v in videos]:
        m = part_pattern.match(video_base)
        if m and m.group(1) in already_done:
            already_done.add(video_base)

    remaining = [v for v in videos if os.path.splitext(v)[0] not in already_done]

    print(f"[{subject} {course}] {len(videos)} videos, "
          f"{len(videos) - len(remaining)} done, {len(remaining)} to transcribe.")

    new_transcripts = []

    for i, video in enumerate(remaining, 1):
        video_path = os.path.join(videos_dir, video)
        base_name = os.path.splitext(video)[0]
        partial_path = os.path.join(str(transcripts_dir), f"{base_name}.json")
        duration = _get_duration(video_path)
        dur_str = f"  ({_fmt_time(duration)})" if duration else ""
        print(f"  [{i}/{len(remaining)}] Transcribing: {video}{dur_str}", flush=True)

        language = settings.get("whisper_language")

        if backend == "cpu":
            # No dedicated venv on a CI runner — use the current interpreter, which has
            # faster-whisper installed via requirements.txt. The turbo model (not
            # downgraded to large-v3 the way the GPU path is) keeps CPU runs fast.
            python_exe = sys.executable
            fw_model = model
        else:
            python_exe = WHISPER_PYTHON
            fw_model = _MODEL_MAP.get(model, model)

        cmd = [
            python_exe, "-u", WHISPER_WORKER,
            video_path,
            "--model", fw_model,
            "--output_dir", str(transcripts_dir),
            "--device", backend,
            "--condition_on_previous_text", "False",
        ]
        if language:
            cmd += ["--language", language]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"

        start = time.time()
        returncode, error_msg = _run_whisper_with_progress(cmd, env, partial_path, duration)
        elapsed = int(time.time() - start)
        mins, secs = divmod(elapsed, 60)

        if returncode != 0:
            is_cuda = any(s in error_msg.lower() for s in ["cuda", "out of memory", "oom"])
            if is_cuda:
                print(f"    CUDA ERROR: {video} — skipping (GPU may have run out of memory)", flush=True)
                time.sleep(5)
            else:
                print(f"    ERROR: Failed to transcribe {video} (exit code {returncode})", flush=True)
                if error_msg:
                    print(f"    {error_msg[:200]}", flush=True)
                else:
                    print("    No error output captured — likely a hard crash (driver/CUDA fault) rather than a Python exception.", flush=True)
        else:
            print(f"    Done in {mins}m {secs}s", flush=True)
            new_transcripts.append(base_name)

            # Generate plain text version alongside JSON
            _generate_plain_text(transcripts_dir, base_name)

    _merge_parts(transcripts_dir)

    return new_transcripts


def _merge_parts(transcripts_dir):
    """Merge multi-part transcripts (*-p1.json, *-p2.json, ...) into a single file.

    If a combined transcript already exists for that date, the part files are
    simply removed (preserving any manually created combined transcript).
    Otherwise the parts are merged in order, with timestamps adjusted for
    continuity, and written as {date}.json / {date}.txt.
    """
    import re
    part_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})-p(\d+)\.json$')

    groups = {}
    for f in Path(transcripts_dir).glob("*-p*.json"):
        m = part_pattern.match(f.name)
        if m:
            date = m.group(1)
            part_num = int(m.group(2))
            groups.setdefault(date, []).append((part_num, f))

    for date, parts in groups.items():
        parts.sort(key=lambda x: x[0])
        combined_path = Path(transcripts_dir) / f"{date}.json"

        if combined_path.exists():
            print(f"  [{date}] Combined transcript already exists — removing part files.")
        else:
            # Merge: concatenate text and segments, adjusting timestamps
            combined_text = ""
            combined_segments = []
            time_offset = 0.0

            for _, part_file in parts:
                with open(part_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                combined_text += data.get("text", "")
                for seg in data.get("segments", []):
                    adjusted = dict(seg)
                    adjusted["start"] = seg["start"] + time_offset
                    adjusted["end"] = seg["end"] + time_offset
                    combined_segments.append(adjusted)
                if combined_segments:
                    time_offset = combined_segments[-1]["end"]

            with open(combined_path, "w", encoding="utf-8") as f:
                json.dump({"text": combined_text, "segments": combined_segments},
                          f, ensure_ascii=False, indent=2)
            txt_path = combined_path.with_suffix(".txt")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(combined_text)
            print(f"  [{date}] Merged {len(parts)} parts into {date}.json")

        # Remove part files regardless
        for _, part_file in parts:
            part_file.unlink()
            txt_file = part_file.with_suffix(".txt")
            if txt_file.exists():
                txt_file.unlink()


def _generate_plain_text(transcripts_dir, base_name):
    """Extract plain text from Whisper JSON transcript."""
    json_path = os.path.join(transcripts_dir, f"{base_name}.json")
    if not os.path.exists(json_path):
        return

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    text = data.get("text", "")
    txt_path = os.path.join(transcripts_dir, f"{base_name}.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(text)


def main():
    parser = make_parser("Transcribe video recordings using Whisper")
    parser.add_argument("--backend", choices=["cuda", "cpu"], default="cuda",
                        help="'cuda' uses the GPU whisper-env venv, 'cpu' runs faster-whisper under the current interpreter (no GPU needed)")
    args = parser.parse_args()
    classes = resolve_classes(args)
    settings = get_settings()

    all_new = {}
    for subject, course, config in classes:
        new = transcribe_for_class(subject, course, settings, backend=args.backend)
        if new:
            all_new[(subject, course)] = new

    return all_new


if __name__ == "__main__":
    main()
