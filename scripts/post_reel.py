import json
import os
import random
import time
from datetime import datetime, timezone
import requests

# ─── Configuration (from GitHub Secrets) ───
ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]
VIDEO_BASE_URL = os.environ["VIDEO_BASE_URL"]  # e.g. https://yourusername.github.io/equationtoday-reels/reels
GRAPH_API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# ─── Paths ───
REELS_FILE = "data/reels.json"
HISTORY_FILE = "data/reel_history.json"

# How many posts before a reel can be reused
COOLDOWN = 30


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def pick_reel(reels, history):
    """Pick a random reel that hasn't been posted recently."""
    recent_ids = [h["id"] for h in history[-COOLDOWN:]]
    available = [rid for rid in reels if rid not in recent_ids]

    if not available:
        # All reels used recently — pick the least recent
        available = [h["id"] for h in history[:10]]

    return random.choice(available)


def create_reel_container(video_url, caption):
    """Create a media container for a Reel."""
    params = {
        "media_type": "REELS",
        "video_url": video_url,
        "caption": caption,
        "share_to_feed": "false",
        "access_token": ACCESS_TOKEN,
    }
    response = requests.post(f"{BASE_URL}/{IG_USER_ID}/media", params=params)
    response.raise_for_status()
    return response.json()["id"]


def check_container_status(container_id):
    """Check if a media container is ready to publish."""
    params = {
        "fields": "status_code,status",
        "access_token": ACCESS_TOKEN,
    }
    response = requests.get(f"{BASE_URL}/{container_id}", params=params)
    response.raise_for_status()
    data = response.json()
    return data.get("status_code"), data.get("status")


def wait_for_container(container_id, max_wait=300):
    """Wait for a container to finish processing.

    Video processing can take longer than images, so default
    max_wait is 5 minutes with 10-second polling intervals.
    """
    for _ in range(max_wait // 10):
        status_code, status = check_container_status(container_id)
        print(f"  Container status: {status_code} ({status})")
        if status_code == "FINISHED":
            return True
        if status_code == "ERROR":
            raise Exception(
                f"Container {container_id} failed processing: {status}"
            )
        time.sleep(10)
    raise Exception(f"Container {container_id} timed out after {max_wait}s")


def publish(container_id):
    """Publish a media container."""
    params = {
        "creation_id": container_id,
        "access_token": ACCESS_TOKEN,
    }
    response = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media_publish", params=params
    )
    response.raise_for_status()
    return response.json()["id"]


def main():
    # Load data
    reels = load_json(REELS_FILE)
    history = load_json(HISTORY_FILE)

    if not reels:
        print("No reels configured in reels.json — skipping.")
        return

    # Pick a reel
    reel_id = pick_reel(reels, history)
    reel = reels[reel_id]
    print(f"Selected reel: {reel_id}")

    # Build video URL
    filename = reel.get("filename", f"{reel_id}.mp4")
    video_url = f"{VIDEO_BASE_URL}/{filename}"

    # Build caption
    caption = reel["caption"]
    if reel.get("hashtags"):
        caption = f"{caption}\n\n{reel['hashtags']}"

    # Step 1: Create reel container
    print(f"Creating reel container: {video_url}")
    container_id = create_reel_container(video_url, caption)

    # Step 2: Wait for video processing
    print("Waiting for video processing...")
    wait_for_container(container_id)

    # Step 3: Publish
    print("Publishing reel...")
    post_id = publish(container_id)
    print(f"Published! Post ID: {post_id}")

    # Step 4: Update history
    history.append(
        {
            "id": reel_id,
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "post_id": post_id,
        }
    )
    save_json(HISTORY_FILE, history)
    print("Reel history updated.")


if __name__ == "__main__":
    main()
