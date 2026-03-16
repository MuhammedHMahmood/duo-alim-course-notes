"""Transcribe video recordings using OpenAI Whisper.

Uses a dedicated virtual environment with GPU-compatible PyTorch
for CUDA acceleration on RTX 5080 (Blackwell / sm_120).
"""

import os
import json
import subprocess
import sys
import time
from pathlib import Path

from common import make_parser, resolve_classes, course_dir, get_settings

# Whisper runs in a separate venv with CUDA 12.8 PyTorch for RTX 5080 support
WHISPER_PYTHON = r"C:\Users\moham\whisper-env\Scripts\python.exe"


def transcribe_for_class(subject, course, settings):
    """Transcribe all untranscribed videos for a class. Returns list of new base names."""
    videos_dir = course_dir(subject, course, "videos")
    transcripts_dir = course_dir(subject, course, "transcripts")

    model = settings.get("whisper_model", "large-v3-turbo")

    videos = sorted(
        f for f in os.listdir(videos_dir)
        if f.lower().endswith((".mp4", ".mkv", ".avi", ".mov", ".webm"))
    )

    already_done = {
        f.replace(".json", "")
        for f in os.listdir(transcripts_dir) if f.endswith(".json")
    }

    # If a combined transcript exists for a date, treat its part videos as done too
    # e.g. 2026-01-30.json means 2026-01-30-p1 and 2026-01-30-p2 are already covered
    import re
    part_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2})-p\d+$')
    for video_base in [os.path.splitext(v)[0] for v in videos]:
        m = part_pattern.match(video_base)
        if m and m.group(1) in already_done:
            already_done.add(video_base)

    remaining = [v for v in videos if os.path.splitext(v)[0] not in already_done]

    print(f"[{subject} {course}] {len(videos)} videos, "
          f"{len(already_done)} done, {len(remaining)} to transcribe.")

    new_transcripts = []

    for i, video in enumerate(remaining, 1):
        video_path = os.path.join(videos_dir, video)
        print(f"  [{i}/{len(remaining)}] Transcribing: {video}")

        cmd = [
            WHISPER_PYTHON, "-m", "whisper",
            video_path,
            "--model", model,
            "--word_timestamps", "True",
            "--output_format", "json",
            "--output_dir", str(transcripts_dir),
            "--device", "cuda",
            "--condition_on_previous_text", "False",
        ]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")

        base_name = os.path.splitext(video)[0]

        if result.returncode != 0:
            error_msg = result.stderr or ""
            is_cuda = any(s in error_msg.lower() for s in ["cuda", "out of memory", "oom"])
            if is_cuda:
                print(f"    CUDA ERROR: {video} — skipping (GPU may have run out of memory)")
                partial = os.path.join(transcripts_dir, f"{base_name}.json")
                if os.path.exists(partial):
                    os.remove(partial)
                time.sleep(5)
            else:
                print(f"    ERROR: Failed to transcribe {video}")
                if error_msg:
                    print(f"    {error_msg[:200]}")
        else:
            print(f"    Done.")
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
    args = parser.parse_args()
    classes = resolve_classes(args)
    settings = get_settings()

    all_new = {}
    for subject, course, config in classes:
        new = transcribe_for_class(subject, course, settings)
        if new:
            all_new[(subject, course)] = new

    return all_new


if __name__ == "__main__":
    main()
