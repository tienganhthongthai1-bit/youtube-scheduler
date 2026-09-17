#!/usr/bin/env python3
"""
YouTube Uploader for GitHub Actions
- Reads videos from /videos folder
- Each video needs: video.mp4 + video.txt (description) + video.png (thumbnail, optional)
- Uploads one video per run, marks as done by moving to /videos/uploaded/
- Schedules publish time based on START_DATE + TIME env vars
"""

import os
import json
import glob
import datetime
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

TIMEZONE     = ZoneInfo("Asia/Ho_Chi_Minh")
SCOPES       = ["https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube"]
TOKEN_FILE   = "token.json"
CREDS_FILE   = "client_secrets.json"


def get_credentials():
    creds = None
    # GitHub Actions: token stored as secret TOKEN_JSON
    token_json = os.environ.get("TOKEN_JSON")
    if token_json:
        with open(TOKEN_FILE, "w") as f:
            f.write(token_json)

    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(TOKEN_FILE, "w") as f:
                f.write(creds.to_json())
        else:
            raise RuntimeError(
                "No valid credentials. Run locally first to generate token.json, "
                "then add TOKEN_JSON to GitHub Secrets."
            )
    return creds


def get_pending_videos():
    """Return sorted list of video files not yet uploaded."""
    videos_dir = Path("videos")
    uploaded_dir = videos_dir / "uploaded"
    uploaded_dir.mkdir(exist_ok=True)

    extensions = ["*.mp4", "*.MP4", "*.mov", "*.MOV", "*.avi", "*.mkv"]
    videos = []
    for ext in extensions:
        videos.extend(videos_dir.glob(ext))

    return sorted(videos)


def read_description(video_path):
    txt = video_path.with_suffix(".txt")
    if txt.exists():
        return txt.read_text(encoding="utf-8").strip()
    return video_path.stem  # fallback to filename


def find_thumbnail(video_path):
    for ext in [".png", ".jpg", ".jpeg", ".PNG", ".JPG"]:
        thumb = video_path.with_suffix(ext)
        if thumb.exists():
            return str(thumb)
    return None


def get_publish_time(index):
    start_date_str = os.environ.get("START_DATE", "2026-05-20")
    time_str       = os.environ.get("PUBLISH_TIME", "07:00")

    start_date = datetime.datetime.strptime(start_date_str, "%Y-%m-%d").date()
    pub_time   = datetime.datetime.strptime(time_str, "%H:%M").time()

    local_dt = datetime.datetime.combine(
        start_date + datetime.timedelta(days=index),
        pub_time,
        tzinfo=TIMEZONE,
    )
    return local_dt.astimezone(datetime.timezone.utc)


def upload_video(youtube, video_path, title, description, publish_at, thumbnail_path=None):
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": "27",  # Education
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=32 * 1024 * 1024, resumable=True)
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  Upload {int(status.progress() * 100)}%", flush=True)

    video_id = response["id"]

    # Set thumbnail if exists
    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(thumbnail_path)
            ).execute()
            print(f"  Thumbnail set.")
        except Exception as e:
            print(f"  Thumbnail failed (non-fatal): {e}")

    return video_id


def mark_uploaded(video_path):
    """Move video + associated files to videos/uploaded/"""
    uploaded_dir = video_path.parent / "uploaded"
    uploaded_dir.mkdir(exist_ok=True)

    for f in video_path.parent.glob(video_path.stem + ".*"):
        dest = uploaded_dir / f.name
        f.rename(dest)
        print(f"  Moved: {f.name} → uploaded/")


def main():
    # Read optional INDEX from env (which video slot to upload)
    # Default: upload the FIRST pending video
    index_override = os.environ.get("VIDEO_INDEX")

    creds   = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)

    videos = get_pending_videos()
    if not videos:
        print("No pending videos found in /videos folder.")
        sys.exit(0)

    # Determine which video to upload and its schedule index
    if index_override is not None:
        idx = int(index_override)
        if idx >= len(videos):
            print(f"VIDEO_INDEX={idx} out of range (only {len(videos)} videos).")
            sys.exit(1)
        video_path = videos[idx]
    else:
        idx        = 0
        video_path = videos[0]

    description   = read_description(video_path)
    thumbnail     = find_thumbnail(video_path)
    publish_at    = get_publish_time(idx)
    title         = video_path.stem

    print(f"\nUploading [{idx+1}/{len(videos)}]: {video_path.name}")
    print(f"  Title      : {title}")
    print(f"  Publish at : {publish_at.astimezone(TIMEZONE).strftime('%Y-%m-%d %H:%M')} ICT")
    print(f"  Thumbnail  : {thumbnail or 'none'}")

    video_id = upload_video(youtube, video_path, title, description, publish_at, thumbnail)
    print(f"  ✅ Done! youtube.com/watch?v={video_id}")

    mark_uploaded(video_path)


if __name__ == "__main__":
    main()
