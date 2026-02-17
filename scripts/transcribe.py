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
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)

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

    return new_transcripts


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
