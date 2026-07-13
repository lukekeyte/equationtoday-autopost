"""
Post the morning Instagram Story for @equationtoday.

Each equation has a two-slide quiz story (a "Today's Question" teaser and an
"Answer Reveal"). This script picks one equation at random (avoiding recent
repeats), publishes BOTH story slides in order, and records the choice so that
the afternoon carousel job posts the *matching* equation.

Coordination with the carousel:
    We write the chosen equation to data/today_equation.json, e.g.
        {"id": "stefan_boltzmann_law", "name": "...", "date": "2026-07-13"}
    The carousel job (scripts/post_to_instagram.py) reads that file and, if the
    date is today (UTC), posts that equation's carousel — so the morning story
    and afternoon carousel always match. If this job fails or is skipped, the
    carousel job falls back to its own random pick, so the feed never stalls.

Instagram note:
    Stories are published one media at a time with media_type=STORIES. Two
    slides therefore mean two publishes (slide 1 then slide 2), which appear as
    two consecutive frames in the account's story. Stories don't take captions
    (all the text lives in the image), so none is sent.
"""

import json
import os
import random
import time
from datetime import datetime, timezone

import requests

# ─── Configuration (from GitHub Secrets) ───
ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]
# Base URL that serves the story PNGs, e.g.
#   https://<user>.github.io/equationtoday-autopost/stories
STORY_BASE_URL = os.environ["STORY_BASE_URL"]
GRAPH_API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# ─── Paths ───
EQUATIONS_FILE = "data/equations.json"
HISTORY_FILE = "data/story_history.json"
TODAY_FILE = "data/today_equation.json"

# How many recent stories to avoid before an equation can be reused.
# With 152 equations this means ~4 months before a repeat.
COOLDOWN = 120


def load_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def pick_equation(equations, history):
    """Pick a random equation not used in the last COOLDOWN stories."""
    recent_ids = [h["id"] for h in history[-COOLDOWN:]]
    available = [eid for eid in equations if eid not in recent_ids]
    if not available:
        # Everything used recently — fall back to the least recently posted.
        available = [h["id"] for h in history[:10]] or list(equations)
    return random.choice(available)


def create_story_container(image_url):
    """Create a STORIES media container for a single image."""
    params = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": ACCESS_TOKEN,
    }
    response = requests.post(f"{BASE_URL}/{IG_USER_ID}/media", params=params)
    response.raise_for_status()
    return response.json()["id"]


def check_container_status(container_id):
    params = {"fields": "status_code", "access_token": ACCESS_TOKEN}
    response = requests.get(f"{BASE_URL}/{container_id}", params=params)
    response.raise_for_status()
    return response.json().get("status_code")


def wait_for_container(container_id, max_wait=60):
    """Wait for a container to finish processing before publishing."""
    for _ in range(max_wait // 5):
        status = check_container_status(container_id)
        if status == "FINISHED":
            return True
        if status == "ERROR":
            raise Exception(f"Container {container_id} failed processing")
        time.sleep(5)
    raise Exception(f"Container {container_id} timed out")


def publish(container_id):
    params = {"creation_id": container_id, "access_token": ACCESS_TOKEN}
    response = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media_publish", params=params
    )
    response.raise_for_status()
    return response.json()["id"]


def post_story_slide(image_url):
    """Create, wait for, and publish one story slide. Returns the media id."""
    print(f"Creating story container: {image_url}")
    container_id = create_story_container(image_url)
    wait_for_container(container_id)
    media_id = publish(container_id)
    print(f"  Published story slide: {media_id}")
    return media_id


def main():
    equations = load_json(EQUATIONS_FILE, {})
    history = load_json(HISTORY_FILE, [])

    if not equations:
        print("No equations configured — skipping.")
        return

    eq_id = pick_equation(equations, history)
    eq = equations[eq_id]
    print(f"Selected equation for today's story: {eq_id} ({eq['name']})")

    # Publish both slides in order: question first, then the answer reveal.
    slide_ids = []
    for n in (1, 2):
        url = f"{STORY_BASE_URL}/{eq_id}_story{n}.png"
        slide_ids.append(post_story_slide(url))
        # Small pause so the two frames register in the intended order.
        if n == 1:
            time.sleep(3)

    now = datetime.now(timezone.utc)

    # Record in story history.
    history.append(
        {
            "id": eq_id,
            "name": eq["name"],
            "posted_at": now.isoformat(),
            "story_ids": slide_ids,
        }
    )
    save_json(HISTORY_FILE, history)
    print("Story history updated.")

    # Hand off today's equation to the afternoon carousel job.
    save_json(
        TODAY_FILE,
        {"id": eq_id, "name": eq["name"], "date": now.date().isoformat()},
    )
    print(f"Wrote {TODAY_FILE} for the carousel job to match.")


if __name__ == "__main__":
    main()
