"""Fetch new MP4 recordings from Google Drive for active classes."""

import os
import re
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from common import make_parser, resolve_classes, course_dir, CONFIG_DIR

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
CREDENTIALS_PATH = CONFIG_DIR / "service_account.json"


def get_drive_service():
    """Build authenticated Google Drive API service."""
    creds = service_account.Credentials.from_service_account_file(
        str(CREDENTIALS_PATH), scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def list_mp4s_in_folder(service, folder_id):
    """List all MP4 files in a Google Drive folder."""
    query = f"'{folder_id}' in parents and mimeType='video/mp4' and trashed=false"
    results = service.files().list(
        q=query,
        fields="files(id, name, modifiedTime, size)",
        orderBy="name"
    ).execute()
    return results.get("files", [])


def download_file(service, file_id, dest_path):
    """Download a file from Google Drive."""
    request = service.files().get_media(fileId=file_id)
    with open(dest_path, "wb") as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
            if status:
                print(f"    Download {int(status.progress() * 100)}%")


def normalize_filename(original_name):
    """Extract date from filename, return normalized name.

    e.g., 'TFS 101 2023-09-21.MP4' -> '2023-09-21.mp4'
    """
    match = re.search(r'(\d{4}-\d{2}-\d{2})', original_name)
    if match:
        return f"{match.group(1)}.mp4"
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
    existing = {f.name for f in videos_dir.iterdir() if f.suffix.lower() == ".mp4"}

    remote_files = list_mp4s_in_folder(service, folder_id)
    new_count = 0

    for remote_file in remote_files:
        local_name = normalize_filename(remote_file["name"])
        if local_name in existing:
            continue

        dest_path = videos_dir / local_name
        print(f"  Downloading: {remote_file['name']} -> {local_name}")
        download_file(service, remote_file["id"], dest_path)
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
