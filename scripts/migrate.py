"""One-time migration: move flat TFS files into subjects/{subject}/{course}/ structure."""

import os
import re
import shutil
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Pattern: "TFS 101 2023-09-21" or "TFS 102 2024-01-18"
FILENAME_RE = re.compile(r'^TFS (\d+) (\d{4}-\d{2}-\d{2})')

# Directories to migrate and their target subfolder under subjects/tfs/{course}/
MIGRATIONS = {
    "videos":            ("videos",      ".mp4"),
    "transcripts":       ("transcripts", ".json"),
    "plain_transcripts": ("transcripts", ".txt"),   # plain text goes alongside JSON
    "notes":             ("notes",       ".md"),
}


def parse_filename(filename):
    """Extract course number and date from a TFS filename.

    Returns (course, date) or None if no match.
    """
    stem = Path(filename).stem
    m = FILENAME_RE.match(stem)
    if m:
        return m.group(1), m.group(2)
    return None


def migrate_directory(src_dir_name, dest_subfolder, dest_ext, dry_run=False):
    """Move files from a flat directory into the subject/course structure."""
    src_dir = PROJECT_ROOT / src_dir_name
    if not src_dir.exists():
        print(f"  SKIP: {src_dir_name}/ does not exist")
        return 0

    moved = 0
    for f in sorted(src_dir.iterdir()):
        if not f.is_file():
            continue

        parsed = parse_filename(f.name)
        if not parsed:
            print(f"  SKIP: {f.name} (doesn't match TFS pattern)")
            continue

        course, date = parsed
        new_name = f"{date}{dest_ext}"
        dest_dir = PROJECT_ROOT / "subjects" / "tfs" / course / dest_subfolder
        dest_path = dest_dir / new_name

        if dry_run:
            print(f"  [DRY RUN] {src_dir_name}/{f.name} -> subjects/tfs/{course}/{dest_subfolder}/{new_name}")
        else:
            dest_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), str(dest_path))
            print(f"  MOVED: {src_dir_name}/{f.name} -> subjects/tfs/{course}/{dest_subfolder}/{new_name}")
        moved += 1

    return moved


def migrate_docs(dry_run=False):
    """Move docs/tfs-{course}/*.md into subjects/tfs/{course}/notes/."""
    docs_dir = PROJECT_ROOT / "docs"
    moved = 0

    for subdir in sorted(docs_dir.iterdir()):
        if not subdir.is_dir() or not subdir.name.startswith("tfs-"):
            continue

        # Extract course from "tfs-101" -> "101"
        course = subdir.name.split("-")[1]

        for f in sorted(subdir.glob("*.md")):
            dest_dir = PROJECT_ROOT / "subjects" / "tfs" / course / "notes"
            dest_path = dest_dir / f.name

            # Only move if not already in notes/ (notes/ takes priority since
            # docs were copies of notes)
            if dest_path.exists():
                if dry_run:
                    print(f"  [DRY RUN] SKIP docs/{subdir.name}/{f.name} (already migrated from notes/)")
                continue

            if dry_run:
                print(f"  [DRY RUN] docs/{subdir.name}/{f.name} -> subjects/tfs/{course}/notes/{f.name}")
            else:
                dest_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(f), str(dest_path))
                print(f"  COPIED: docs/{subdir.name}/{f.name} -> subjects/tfs/{course}/notes/{f.name}")
            moved += 1

    return moved


def main():
    parser = argparse.ArgumentParser(description="Migrate flat TFS files to subject/course structure")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without moving files")
    args = parser.parse_args()

    if args.dry_run:
        print("=== DRY RUN MODE ===\n")

    total = 0

    print("Migrating videos/")
    total += migrate_directory("videos", "videos", ".mp4", args.dry_run)

    print("\nMigrating transcripts/ (JSON)")
    total += migrate_directory("transcripts", "transcripts", ".json", args.dry_run)

    print("\nMigrating plain_transcripts/ (TXT)")
    total += migrate_directory("plain_transcripts", "transcripts", ".txt", args.dry_run)

    print("\nMigrating notes/")
    total += migrate_directory("notes", "notes", ".md", args.dry_run)

    print("\nMigrating docs/ (as fallback for notes)")
    total += migrate_docs(args.dry_run)

    print(f"\n{'Would move' if args.dry_run else 'Moved'} {total} files total.")

    if args.dry_run:
        print("\nRun without --dry-run to actually move files.")


if __name__ == "__main__":
    main()
