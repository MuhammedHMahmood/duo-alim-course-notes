"""Transcribe video recordings using OpenAI Whisper."""

import os
import json
import subprocess
import sys
from pathlib import Path

from common import make_parser, resolve_classes, course_dir, get_settings


def transcribe_for_class(subject, course, settings):
    """Transcribe all untranscribed videos for a class. Returns list of new base names."""
    videos_dir = course_dir(subject, course, "videos")
    transcripts_dir = course_dir(subject, course, "transcripts")

    model = settings.get("whisper_model", "large-v3-turbo")
    language = settings.get("whisper_language", "en")

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
            sys.executable, "-m", "whisper",
            video_path,
            "--model", model,
            "--language", language,
            "--word_timestamps", "True",
            "--output_format", "json",
            "--output_dir", str(transcripts_dir),
        ]

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(cmd, env=env)

        if result.returncode != 0:
            print(f"    ERROR: Failed to transcribe {video}")
        else:
            base_name = os.path.splitext(video)[0]
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
