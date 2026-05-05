"""faster-whisper worker — invoked by transcribe.py via WHISPER_PYTHON.

Outputs segment lines to stdout in openai-whisper verbose format:
  [MM:SS.mmm --> MM:SS.mmm]  text
so transcribe.py's progress parser works unchanged.
Writes final JSON to output_dir/{stem}.json in openai-whisper format.
"""

import argparse
import json
import sys
from pathlib import Path

from faster_whisper import WhisperModel


def fmt_ts(secs):
    m, s = divmod(secs, 60)
    return f"{int(m):02d}:{s:06.3f}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("audio")
    p.add_argument("--model", default="large-v3")
    p.add_argument("--output_dir", required=True)
    p.add_argument("--device", default="cuda")
    p.add_argument("--condition_on_previous_text", default="False")
    p.add_argument("--language", default=None)
    args = p.parse_args()

    condition = args.condition_on_previous_text.lower() not in ("false", "0", "no")

    model = WhisperModel(args.model, device=args.device, compute_type="float16")

    segments_iter, info = model.transcribe(
        args.audio,
        language=args.language,
        condition_on_previous_text=condition,
    )

    print(f"Detected language: {info.language} (p={info.language_probability:.2f})", flush=True)

    segments_list = []
    full_text = ""

    for seg in segments_iter:
        line = f"[{fmt_ts(seg.start)} --> {fmt_ts(seg.end)}]  {seg.text}"
        print(line, flush=True)
        segments_list.append({"start": seg.start, "end": seg.end, "text": seg.text})
        full_text += seg.text

    out_path = Path(args.output_dir) / f"{Path(args.audio).stem}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"text": full_text, "segments": segments_list}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
