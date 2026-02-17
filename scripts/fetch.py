"""Fetch new MP4 recordings from Google Drive for active classes.

Uses a service account for authenticated access. This bypasses the virus
scan confirmation page that blocks unauthenticated downloads of large files.
The Drive folders are shared as "Anyone with the link can view", so the
service account can access them without explicit sharing.
"""

import os
import re
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from common import make_parser, resolve_classes, course_dir, CONFIG_DIR

SERVICE_ACCOUNT_FILE = CONFIG_DIR / "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def get_drive_service():
    """Build authenticated Google Drive API service using a service account."""
    if not SERVICE_ACCOUNT_FILE.exists():
        raise FileNotFoundError(
            f"Missing {SERVICE_ACCOUNT_FILE}\n"
            "Create a service account in Google Cloud Console:\n"
            "  1. Go to console.cloud.google.com > IAM & Admin > Service Accounts\n"
            "  2. Create a service account\n"
            "  3. Keys tab > Add Key > Create New Key > JSON\n"
            "  4. Save as config/service_account.json"
        )
    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_FILE), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def list_mp4s_in_folder(service, folder_id):
    """List all MP4 files in a Google Drive folder."""
    query = f"'{folder_id}' in parents and mimeType='video/mp4' and trashed=false"
    all_files = []
    page_token = None

    while True:
        results = service.files().list(
            q=query,
            fields="nextPageToken, files(id, name, modifiedTime, size)",
            orderBy="name",
            pageToken=page_token
        ).execute()
        all_files.extend(results.get("files", []))
        page_token = results.get("nextPageToken")
        if not page_token:
            break

    return all_files


def download_file(service, file_id, dest_path):
    """Download a file from Google Drive using authenticated API.

    Uses get_media() with service account credentials, which bypasses
    the virus scan confirmation page that blocks public downloads.
    """
    dest_path = Path(dest_path)
    request = service.files().get_media(fileId=file_id)

    try:
        with open(dest_path, "wb") as f:
            downloader = MediaIoBaseDownload(f, request, chunksize=32 * 1024 * 1024)
            done = False
            while not done:
                status, done = downloader.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    mb = status.resumable_progress / (1024 * 1024)
                    total_mb = status.total_size / (1024 * 1024)
                    print(f"    Download {pct}% ({mb:.0f}/{total_mb:.0f} MB)")
    except Exception:
        # Remove partial file so it gets retried next run
        if dest_path.exists():
            dest_path.unlink()
        raise

    size_mb = dest_path.stat().st_size / (1024 * 1024)
    print(f"    Done ({size_mb:.0f} MB)")
    return True


def normalize_filename(original_name):
    """Extract date (and optional part number) from filename, return normalized name.

    e.g., 'TFS 101 2023-09-21.MP4'    -> '2023-09-21.mp4'
          'SRF 102 2026-01-30 P1.mp4'  -> '2026-01-30-p1.mp4'
          'SRF 102 2026-01-30 P2.mp4'  -> '2026-01-30-p2.mp4'
    """
    match = re.search(r'(\d{4}-\d{2}-\d{2})', original_name)
    if match:
        date = match.group(1)
        # Check for part number after the date but before the extension
        name_without_ext = os.path.splitext(original_name)[0]
        after_date = name_without_ext[match.end():]
        part_match = re.search(r'(?:P|Part)\s*(\d+)', after_date, re.IGNORECASE)
        if part_match:
            return f"{date}-p{part_match.group(1)}.mp4"
        return f"{date}.mp4"
    # Fallback: lowercase extension, keep original name
    name, ext = os.path.splitext(original_name)
    return f"{name}{ext.lower()}"


def fetch_for_class(service, subject, course, class_config):
    """Fetch new videos for a single class. Returns count of new downloads."""
    folder_id = class_config.get("gdrive_folder_id", "")
    if not folder_id:
        print(f"  No Google Drive folder configured for {subject} {course}, skipping.")
        return 0

    videos_dir = course_dir(subject, course, "videos")
    existing = {
        f.name for f in videos_dir.iterdir()
        if f.suffix.lower() == ".mp4" and f.stat().st_size > 0
    }

    remote_files = list_mp4s_in_folder(service, folder_id)
    new_count = 0

    for remote_file in remote_files:
        local_name = normalize_filename(remote_file["name"])
        if local_name in existing:
            continue

        dest_path = videos_dir / local_name
        print(f"  Downloading: {remote_file['name']} -> {local_name}")
        success = download_file(service, remote_file["id"], dest_path)
        if success:
            new_count += 1

    return new_count


def main():
    parser = make_parser("Fetch new recordings from Google Drive")
    args = parser.parse_args()
    classes = resolve_classes(args)

    service = get_drive_service()

    total_new = 0
    for subject, course, config in classes:
        print(f"[{subject} {course}] Checking Google Drive...")
        count = fetch_for_class(service, subject, course, config)
        print(f"  {count} new file(s) downloaded.")
        total_new += count

    print(f"\nTotal: {total_new} new file(s) downloaded.")
    return total_new


if __name__ == "__main__":
    main()
