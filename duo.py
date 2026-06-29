"""DUO Class Notes CLI — unified tool for the study notes pipeline.

Usage:
    python duo.py fetch --all
    python duo.py transcribe --active-only
    python duo.py notes --subject hadith --course 101
    python duo.py build
    python duo.py serve
    python duo.py deploy
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
    return total


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
    return total


def cmd_notes(args):
    """Generate study notes from transcripts.

    Returns (total, breakdown) where breakdown is a list of (label, count)
    for each class that gained new notes — used for the Discord summary.
    """
    import generate_notes
    classes = _resolve(args)
    settings = get_settings()
    workers = getattr(args, "workers", 1)

    total = 0
    breakdown = []
    for subject, course, config in classes:
        new = generate_notes.generate_notes_for_class(
            subject, course, settings, args.force, args.backend, workers,
        )
        if new:
            breakdown.append((f"{subject} {course}", len(new)))
        total += len(new)

    print(f"\nTotal: {total} new note(s) generated.")
    return total, breakdown


def cmd_prune(args):
    """Delete MP4s whose transcript AND note both exist (free disk; videos are regeneratable)."""
    import re
    classes = _resolve(args)
    dry = getattr(args, "dry_run", False)
    part_re = re.compile(r'-p\d+$')

    total_files = 0
    total_bytes = 0
    for subject, course, config in classes:
        videos_dir = SUBJECTS_DIR / subject / course / "videos"
        trans_dir = SUBJECTS_DIR / subject / course / "transcripts"
        notes_dir = SUBJECTS_DIR / subject / course / "notes"
        if not videos_dir.exists():
            continue
        transcripts = {f.stem for f in trans_dir.glob("*.json")} if trans_dir.exists() else set()
        notes = {f.stem for f in notes_dir.glob("*.md")} if notes_dir.exists() else set()
        # A session is safe to prune only once both its transcript and note exist.
        done = transcripts & notes

        removed = 0
        for vid in videos_dir.glob("*.mp4"):
            if part_re.sub("", vid.stem) in done:
                size = vid.stat().st_size
                action = "would delete" if dry else "deleting"
                print(f"  {action}: {subject}/{course}/{vid.name} ({size / 1e6:.0f} MB)")
                if not dry:
                    vid.unlink()
                removed += 1
                total_files += 1
                total_bytes += size
        if removed == 0:
            print(f"[{subject} {course}] nothing to prune.")

    verb = "Would free" if dry else "Freed"
    print(f"\n{verb} {total_bytes / 1e9:.2f} GB across {total_files} video file(s).")
    return total_files, total_bytes


def cmd_build(args):
    """Sync notes to docs/ and update MkDocs site."""
    import update_mkdocs

    print("Syncing notes to docs/...")
    update_mkdocs.sync_notes_to_docs()

    print("Building navigation...")
    nav = update_mkdocs.build_nav()

    print("Updating mkdocs.yml...")
    update_mkdocs.update_mkdocs_yml(nav)

    print("Done. Run 'duo.py serve' to preview or 'duo.py deploy' to publish.")


def cmd_serve(args):
    """Launch MkDocs local preview server."""
    import subprocess
    subprocess.run(["mkdocs", "serve"], check=True)


def cmd_deploy(args):
    """Deploy the site to GitHub Pages via mkdocs gh-deploy."""
    import subprocess
    print("Deploying to GitHub Pages...")
    subprocess.run(["mkdocs", "gh-deploy", "--force"], check=True)
    print("Done. Site is live on gh-pages.")


def _run_git(*cmdargs):
    """Run a git command in the repo root; return CompletedProcess (capturing output)."""
    import subprocess
    return subprocess.run(
        ["git", *cmdargs],
        cwd=str(Path(__file__).resolve().parent),
        capture_output=True, text=True,
    )


def _commit_url(sha):
    """Build a GitHub commit URL from origin's remote, or None if it can't be derived."""
    remote = _run_git("remote", "get-url", "origin").stdout.strip()
    if not remote:
        return None
    if remote.endswith(".git"):
        remote = remote[:-4]
    if remote.startswith("git@"):  # git@github.com:user/repo -> https://github.com/user/repo
        host, _, path = remote[4:].partition(":")
        remote = f"https://{host}/{path}"
    return f"{remote}/commit/{sha}"


def _commit_and_push(message):
    """Stage, commit, and push everything. Returns a Discord field value:
    a clickable short-SHA link if a commit was made, or 'nothing to commit'.
    Raises on commit/push failure so the pipeline's error handler reports it.
    """
    _run_git("add", "-A")
    if not _run_git("status", "--porcelain").stdout.strip():
        return "`nothing to commit`"

    r = _run_git("commit", "-m", message)
    if r.returncode != 0:
        raise RuntimeError(f"git commit failed: {r.stderr.strip() or r.stdout.strip()}")

    sha = _run_git("rev-parse", "--short", "HEAD").stdout.strip()

    p = _run_git("push")
    if p.returncode != 0:
        raise RuntimeError(f"git push failed (committed {sha} locally): {p.stderr.strip()}")

    url = _commit_url(sha)
    return f"[`{sha}`]({url})" if url else f"`{sha}`"


def cmd_pipeline(args):
    """Run the full pipeline: fetch -> transcribe -> notes -> prune -> build -> deploy,
    plus an optional commit/push step with --commit.

    Posts a rich Discord embed on success and a failure alert (naming the failing step)
    on any exception — see scripts/notify.py. Both also append to logs/runs.log.
    """
    import time
    from datetime import datetime
    import notify as notifier

    args_copy = argparse.Namespace(**vars(args))
    start = time.time()
    date = datetime.now().strftime("%Y-%m-%d")
    do_commit = getattr(args, "commit", False)
    n_steps = 7 if do_commit else 6

    # Embeds size to their widest code-block line. A fixed-width rule in both the success
    # and failure code blocks pins them to the same (near-max) width — 54 chars is the
    # widest that fits on one line before Discord wraps it on desktop.
    RULE = "─" * 54

    def _elapsed():
        s = int(time.time() - start)
        return f"{s // 60}m {s % 60}s"

    def _step(num, name, fn):
        print("\n" + "=" * 50)
        print(f"Step {num}/{n_steps}: {name}...")
        print("=" * 50)
        try:
            return fn(args_copy)
        except Exception as e:
            notifier.notify(
                "error",
                "❌ Pipeline failed",
                description=f"**Error**\n```\n{RULE}\n{str(e)[:300]}\n```",
                fields=[("Failed step", name), ("Ran for", _elapsed())],
                footer="⚠️ Nothing committed",
            )
            print(f"\nPIPELINE FAILED at '{name}': {e}")
            sys.exit(1)

    fetched = _step(1, "fetch", cmd_fetch)
    transcribed = _step(2, "transcribe", cmd_transcribe)
    noted, breakdown = _step(3, "notes", cmd_notes)
    pruned_files, pruned_bytes = _step(4, "prune", cmd_prune)
    _step(5, "build", cmd_build)
    _step(6, "deploy", cmd_deploy)

    if do_commit:
        commit_value = _step(7, "commit", lambda a: _commit_and_push(f"Update notes — {date}"))
        footer = f"Ran in {_elapsed()}"
    else:
        commit_value = "`not committed`"
        footer = f"Ran in {_elapsed()} · commit manually"

    # The RULE line forces a consistent full embed width; rows align in monospace.
    if breakdown:
        rows = "\n".join(f"{label:<12} +{n} note{'' if n == 1 else 's'}" for label, n in breakdown)
        desc = f"**New notes this run**\n```\n{RULE}\n{rows}\n```"
    else:
        desc = f"**Up to date**\n```\n{RULE}\nNo new sessions — site redeployed.\n```"

    notifier.notify(
        "success",
        "✅ Pipeline complete",
        description=desc,
        fields=[
            ("📥 Fetched", f"{fetched} videos"),
            ("🎙️ Transcribed", str(transcribed)),
            ("📝 Notes", str(noted)),
            ("🧹 Pruned", f"{pruned_files} files · {pruned_bytes / 1e9:.2f} GB"),
            ("🚀 Deployed", "gh-pages"),
            ("💾 Commit", commit_value),
        ],
        footer=footer,
    )
    print("\nPipeline complete.")
    if not do_commit:
        print("Remember to commit & push the new notes/docs to main (or re-run with --commit).")


def cmd_notify(args):
    """Send a Discord notification (+ log it). For ad-hoc / runbook use."""
    import notify as notifier
    fields = []
    for f in (args.field or []):
        if "=" in f:
            k, v = f.split("=", 1)
            fields.append((k.strip(), v.strip()))
    ok = notifier.notify(args.level, args.title, description=args.body,
                         fields=fields or None, footer=args.footer)
    print("Sent to Discord." if ok else "Logged to logs/runs.log (no webhook configured or post failed).")


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

        # Work with sets of session dates (p1/p2 parts = one session) so status stays
        # correct after videos are pruned — a transcript implies we still "have" the session.
        import re as _re
        _part = _re.compile(r'-p\d+$')
        vid_dates = {_part.sub('', f.stem) for f in vids_dir.glob("*.mp4")} if vids_dir.exists() else set()
        trans_dates = {f.stem for f in trans_dir.glob("*.json")} if trans_dir.exists() else set()
        note_dates = {f.stem for f in notes_dir.glob("*.md")} if notes_dir.exists() else set()
        vids, trans, notes = len(vid_dates), len(trans_dates), len(note_dates)

        total_v += vids
        total_t += trans
        total_n += notes

        # Remote session count (deduped the same way as local)
        remote_dates = None
        if not folder_id:
            remote_str = "-"
        elif drive_service is None:
            remote_str = "?"
        else:
            try:
                import fetch
                remote_files = fetch.list_mp4s_in_folder(drive_service, folder_id)
                remote_dates = {
                    _part.sub('', fetch.normalize_filename(rf["name"]).rsplit('.', 1)[0])
                    for rf in remote_files
                }
                remote_str = str(len(remote_dates))
                total_r += len(remote_dates)
            except Exception:
                remote_str = "?"

        # Status — a session is "held" if it has a video OR a transcript (videos may be pruned).
        have = vid_dates | trans_dates
        if remote_dates is not None and (remote_dates - have):
            status = "fetch needed"
        elif vid_dates - trans_dates:
            status = "transcribe needed"
        elif trans_dates - note_dates:
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

    # prune
    p_prune = sub.add_parser("prune", help="Delete MP4s whose transcript+note both exist (free disk)")
    add_class_args(p_prune)
    p_prune.add_argument("--dry-run", action="store_true",
                         help="Show what would be deleted without deleting")
    p_prune.set_defaults(func=cmd_prune)

    # build
    p_build = sub.add_parser("build", help="Sync notes to docs/ and update MkDocs")
    p_build.set_defaults(func=cmd_build)

    # serve
    p_serve = sub.add_parser("serve", help="Launch MkDocs local preview server")
    p_serve.set_defaults(func=cmd_serve)

    # deploy
    p_deploy = sub.add_parser("deploy", help="Deploy site to GitHub Pages (mkdocs gh-deploy)")
    p_deploy.set_defaults(func=cmd_deploy)

    # pipeline
    p_pipe = sub.add_parser("pipeline", help="Run full pipeline: fetch -> transcribe -> notes -> prune -> build -> deploy")
    add_class_args(p_pipe)
    p_pipe.add_argument("--force", action="store_true",
                        help="Regenerate notes even if they exist")
    p_pipe.add_argument("--backend", choices=["api", "cli"], default="cli",
                        help="Backend: 'api' (Anthropic API) or 'cli' (Claude Code CLI)")
    p_pipe.add_argument("--workers", type=int, default=1,
                        help="Number of parallel workers (default: 1)")
    p_pipe.add_argument("--commit", action="store_true",
                        help="After deploy, git add -A && commit && push to main (closes the loop unattended)")
    p_pipe.set_defaults(func=cmd_pipeline)

    # notify
    p_notify = sub.add_parser("notify", help="Send a Discord notification + log it")
    p_notify.add_argument("--level", choices=["success", "error", "info"], default="info")
    p_notify.add_argument("--title", required=True, help="Embed title")
    p_notify.add_argument("--body", help="Embed description")
    p_notify.add_argument("--field", action="append", metavar="NAME=VALUE",
                          help="Inline field (repeatable)")
    p_notify.add_argument("--footer", help="Embed footer text")
    p_notify.set_defaults(func=cmd_notify)

    # status
    p_status = sub.add_parser("status", help="Show status of all classes")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
