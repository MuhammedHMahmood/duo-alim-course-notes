"""Main pipeline: fetch -> transcribe -> generate notes -> update site.

Intended to be run weekly via Windows Task Scheduler.
"""

import sys
import logging
from datetime import datetime
from pathlib import Path

# Add scripts dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import get_active_classes, get_settings, PROJECT_ROOT
import fetch
import transcribe
import generate_notes
import update_mkdocs

LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            LOG_DIR / f"pipeline_{datetime.now():%Y-%m-%d}.log",
            encoding="utf-8"
        ),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


def run_pipeline():
    """Run the full pipeline for all active classes."""
    log.info("=" * 60)
    log.info("DUO Class Notes Pipeline - Starting")
    log.info("=" * 60)

    active = get_active_classes()
    if not active:
        log.info("No active classes found. Nothing to do.")
        return

    log.info(f"Active classes: {len(active)}")
    for c in active:
        log.info(f"  - {c['subject']} {c['course']} ({c.get('semester', '')})")

    settings = get_settings()
    total_fetched = 0
    total_transcribed = 0
    total_notes = 0

    for cls in active:
        subject = cls["subject"]
        course = cls["course"]
        log.info(f"\n--- Processing {subject} {course} ---")

        # Step 1: Fetch new recordings
        try:
            service = fetch.get_drive_service()
            count = fetch.fetch_for_class(service, subject, course, cls)
            total_fetched += count
            log.info(f"  Fetched: {count} new video(s)")
        except Exception as e:
            log.error(f"  Fetch failed: {e}")
            continue

        # Step 2: Transcribe new recordings
        try:
            new_transcripts = transcribe.transcribe_for_class(
                subject, course, settings
            )
            total_transcribed += len(new_transcripts)
            log.info(f"  Transcribed: {len(new_transcripts)} new file(s)")
        except Exception as e:
            log.error(f"  Transcription failed: {e}")
            continue

        # Step 3: Generate notes from new transcripts
        try:
            new_notes = generate_notes.generate_notes_for_class(
                subject, course, settings
            )
            total_notes += len(new_notes)
            log.info(f"  Notes generated: {len(new_notes)} new file(s)")
        except Exception as e:
            log.error(f"  Note generation failed: {e}")
            continue

    # Step 4: Update MkDocs site (once, after all classes processed)
    if total_notes > 0:
        try:
            update_mkdocs.sync_notes_to_docs()
            nav = update_mkdocs.build_nav()
            update_mkdocs.update_mkdocs_yml(nav)
            log.info("MkDocs site updated.")
        except Exception as e:
            log.error(f"MkDocs update failed: {e}")

    log.info(f"\nPipeline complete: "
             f"{total_fetched} fetched, "
             f"{total_transcribed} transcribed, "
             f"{total_notes} notes generated.")


if __name__ == "__main__":
    run_pipeline()
