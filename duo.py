"""DUO Class Notes CLI — unified tool for the study notes pipeline.

Usage:
    python duo.py fetch --all
    python duo.py transcribe --active-only
    python duo.py notes --subject hadith --course 101
    python duo.py build
    python duo.py pipeline --active-only
    python duo.py status
"""

import sys
import argparse
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))

from common import (
    load_config, get_active_classes, get_settings,
    course_dir, VALID_SUBJECTS, SUBJECTS_DIR,
)


def _resolve(args):
    """Resolve which classes to process from args."""
    config = load_config()
    if args.all:
        return [(c["subject"], c["course"], c) for c in config["classes"]]
    elif args.active_only:
        active = get_active_classes()
        return [(c["subject"], c["course"], c) for c in active]
    elif args.subject and args.course:
        for c in config["classes"]:
            if c["subject"] == args.subject and c["course"] == str(args.course):
                return [(c["subject"], c["course"], c)]
        print(f"Error: {args.subject} {args.course} not found in config.")
        sys.exit(1)
    else:
        print("Error: provide --all, --active-only, or --subject and --course")
        sys.exit(1)


def cmd_fetch(args):
    """Fetch new MP4 recordings from Google Drive."""
    import fetch
    classes = _resolve(args)
    service = fetch.get_drive_service()

    total = 0
    for subject, course, config in classes:
        print(f"[{subject} {course}] Checking Google Drive...")
        count = fetch.fetch_for_class(service, subject, course, config)
        print(f"  {count} new file(s) downloaded.")
        total += count

    print(f"\nTotal: {total} new file(s) downloaded.")


def cmd_transcribe(args):
    """Transcribe video recordings using Whisper."""
    import transcribe
    classes = _resolve(args)
    settings = get_settings()

    total = 0
    for subject, course, config in classes:
        new = transcribe.transcribe_for_class(subject, course, settings)
        total += len(new)

    print(f"\nTotal: {total} new transcript(s).")


def cmd_notes(args):
    """Generate study notes from transcripts."""
    import generate_notes
    classes = _resolve(args)
    settings = get_settings()
    workers = getattr(args, "workers", 1)

    total = 0
    for subject, course, config in classes:
        new = generate_notes.generate_notes_for_class(
            subject, course, settings, args.force, args.backend, workers,
        )
        total += len(new)

    print(f"\nTotal: {total} new note(s) generated.")


def cmd_build(args):
    """Sync notes to docs/ and update MkDocs site."""
    import update_mkdocs

    print("Syncing notes to docs/...")
    update_mkdocs.sync_notes_to_docs()

    print("Building navigation...")
    nav = update_mkdocs.build_nav()

    print("Updating mkdocs.yml...")
    update_mkdocs.update_mkdocs_yml(nav)

    print("Done. Run 'mkdocs serve' to preview.")


def cmd_pipeline(args):
    """Run the full pipeline: fetch -> transcribe -> notes -> build."""
    args_copy = argparse.Namespace(**vars(args))

    print("=" * 50)
    print("Step 1/4: Fetching new recordings...")
    print("=" * 50)
    cmd_fetch(args_copy)

    print("\n" + "=" * 50)
    print("Step 2/4: Transcribing new videos...")
    print("=" * 50)
    cmd_transcribe(args_copy)

    print("\n" + "=" * 50)
    print("Step 3/4: Generating notes...")
    print("=" * 50)
    cmd_notes(args_copy)

    print("\n" + "=" * 50)
    print("Step 4/4: Building site...")
    print("=" * 50)
    cmd_build(args_copy)

    print("\nPipeline complete.")


def cmd_status(args):
    """Show status of all classes."""
    config = load_config()

    # Try to connect to Drive for remote counts; degrade gracefully if unavailable
    drive_service = None
    try:
        import fetch
        drive_service = fetch.get_drive_service()
    except Exception as e:
        print(f"[Drive unavailable: {e}]\n")

    print(f"{'Subject':<10} {'Course':<8} {'Remote':<8} {'Local':<8} {'Trans':<8} {'Notes':<8} {'Active':<8} Status")
    print("-" * 80)

    total_r = total_v = total_t = total_n = 0

    for c in config["classes"]:
        subject, course = c["subject"], c["course"]
        active = "yes" if c.get("active") else ""
        folder_id = c.get("gdrive_folder_id", "")

        vids_dir = SUBJECTS_DIR / subject / course / "videos"
        trans_dir = SUBJECTS_DIR / subject / course / "transcripts"
        notes_dir = SUBJECTS_DIR / subject / course / "notes"

        vids = len([f for f in vids_dir.glob("*.mp4")]) if vids_dir.exists() else 0
        trans = len([f for f in trans_dir.glob("*.json")]) if trans_dir.exists() else 0
        notes = len([f for f in notes_dir.glob("*.md")]) if notes_dir.exists() else 0

        total_v += vids
        total_t += trans
        total_n += notes

        # Remote video count
        remote = None
        if not folder_id:
            remote_str = "-"
        elif drive_service is None:
            remote_str = "?"
        else:
            try:
                import fetch
                remote = len(fetch.list_mp4s_in_folder(drive_service, folder_id))
                remote_str = str(remote)
                total_r += remote
            except Exception:
                remote_str = "?"

        # Status
        if remote is not None and remote > vids:
            status = "fetch needed"
        elif vids > trans:
            status = "transcribe needed"
        elif trans > notes:
            status = "notes needed"
        else:
            status = "up to date"

        print(f"{subject:<10} {course:<8} {remote_str:<8} {vids:<8} {trans:<8} {notes:<8} {active:<8} {status}")

    print("-" * 80)
    print(f"{'TOTAL':<10} {'':<8} {total_r:<8} {total_v:<8} {total_t:<8} {total_n:<8}")


def main():
    parser = argparse.ArgumentParser(
        prog="duo",
        description="DUO Class Notes — study notes pipeline CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # Shared arguments for class selection
    def add_class_args(p):
        group = p.add_mutually_exclusive_group()
        group.add_argument("--all", action="store_true",
                           help="All classes (active and inactive)")
        group.add_argument("--active-only", action="store_true",
                           help="Active classes only")
        p.add_argument("--subject", choices=VALID_SUBJECTS,
                       help="Specific subject")
        p.add_argument("--course", help="Course number (e.g., 101, 102)")

    # fetch
    p_fetch = sub.add_parser("fetch", help="Download new recordings from Google Drive")
    add_class_args(p_fetch)
    p_fetch.set_defaults(func=cmd_fetch)

    # transcribe
    p_trans = sub.add_parser("transcribe", help="Transcribe videos using Whisper")
    add_class_args(p_trans)
    p_trans.set_defaults(func=cmd_transcribe)

    # notes
    p_notes = sub.add_parser("notes", help="Generate study notes from transcripts")
    add_class_args(p_notes)
    p_notes.add_argument("--force", action="store_true",
                         help="Regenerate notes even if they exist")
    p_notes.add_argument("--backend", choices=["api", "cli"], default="cli",
                         help="Backend: 'api' (Anthropic API) or 'cli' (Claude Code CLI)")
    p_notes.add_argument("--workers", type=int, default=1,
                         help="Number of parallel workers (default: 1)")
    p_notes.set_defaults(func=cmd_notes)

    # build
    p_build = sub.add_parser("build", help="Sync notes to docs/ and update MkDocs")
    p_build.set_defaults(func=cmd_build)

    # pipeline
    p_pipe = sub.add_parser("pipeline", help="Run full pipeline: fetch -> transcribe -> notes -> build")
    add_class_args(p_pipe)
    p_pipe.add_argument("--force", action="store_true",
                        help="Regenerate notes even if they exist")
    p_pipe.add_argument("--backend", choices=["api", "cli"], default="cli",
                        help="Backend: 'api' (Anthropic API) or 'cli' (Claude Code CLI)")
    p_pipe.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1)")
    p_pipe.set_defaults(func=cmd_pipeline)

    # status
    p_status = sub.add_parser("status", help="Show status of all classes")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
