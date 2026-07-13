"""
Post the afternoon equation carousel for @equationtoday.

The carousel now has FOUR slides (hook / explainer / term definitions / CTA),
named <slug>_slide1.png … <slug>_slide4.png.

Which equation? The morning story job (scripts/post_story.py) chooses the day's
equation and records it in data/today_equation.json. This job posts the
carousel for that same equation so the two match. If that file is missing or
stale (e.g. the story job didn't run today), it falls back to a random pick
with the usual cooldown, so the carousel still goes out.
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
IMAGE_BASE_URL = os.environ["IMAGE_BASE_URL"]  # …/images
GRAPH_API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# ─── Paths ───
EQUATIONS_FILE = "data/equations.json"
HISTORY_FILE = "data/post_history.json"
TODAY_FILE = "data/today_equation.json"

# Number of slides in a carousel.
NUM_SLIDES = 4

# How many posts before an equation can be reused (fallback path only).
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


def pick_equation_random(equations, history):
    """Fallback: pick a random equation not posted in the last COOLDOWN."""
    recent_ids = [h["id"] for h in history[-COOLDOWN:]]
    available = [eid for eid in equations if eid not in recent_ids]
    if not available:
        available = [h["id"] for h in history[:10]] or list(equations)
    return random.choice(available)


def resolve_equation(equations, history):
    """Use the equation the morning story chose, if it's for today.

    Returns (eq_id, matched_story) where matched_story is True when we're
    following today's story and False when we fell back to a random pick.
    """
    today = load_json(TODAY_FILE, {}) or {}
    today_date = datetime.now(timezone.utc).date().isoformat()

    if today.get("date") == today_date and today.get("id") in equations:
        return today["id"], True

    if today:
        print(
            "today_equation.json missing/stale "
            f"(got date={today.get('date')!r}, id={today.get('id')!r}); "
            "falling back to a random pick."
        )
    return pick_equation_random(equations, history), False


def create_media_container(image_url, is_carousel_item=False):
    params = {"image_url": image_url, "access_token": ACCESS_TOKEN}
    if is_carousel_item:
        params["is_carousel_item"] = "true"
    response = requests.post(f"{BASE_URL}/{IG_USER_ID}/media", params=params)
    response.raise_for_status()
    return response.json()["id"]


def create_carousel(children_ids, caption):
    params = {
        "media_type": "CAROUSEL",
        "children": ",".join(children_ids),
        "caption": caption,
        "access_token": ACCESS_TOKEN,
    }
    response = requests.post(f"{BASE_URL}/{IG_USER_ID}/media", params=params)
    response.raise_for_status()
    return response.json()["id"]


def publish(container_id):
    params = {"creation_id": container_id, "access_token": ACCESS_TOKEN}
    response = requests.post(
        f"{BASE_URL}/{IG_USER_ID}/media_publish", params=params
    )
    response.raise_for_status()
    return response.json()["id"]


def check_container_status(container_id):
    params = {"fields": "status_code", "access_token": ACCESS_TOKEN}
    response = requests.get(f"{BASE_URL}/{container_id}", params=params)
    response.raise_for_status()
    return response.json().get("status_code")


def wait_for_container(container_id, max_wait=90):
    for _ in range(max_wait // 5):
        status = check_container_status(container_id)
        if status == "FINISHED":
            return True
        if status == "ERROR":
            raise Exception(f"Container {container_id} failed processing")
        time.sleep(5)
    raise Exception(f"Container {container_id} timed out")


def refresh_token():
    """Refresh the long-lived token to reset the 60-day expiry."""
    response = requests.get(
        f"{BASE_URL}/oauth/access_token",
        params={
            "grant_type": "fb_exchange_token",
            "client_id": os.environ.get("FB_APP_ID", ""),
            "client_secret": os.environ.get("FB_APP_SECRET", ""),
            "fb_exchange_token": ACCESS_TOKEN,
        },
    )
    if response.ok:
        new_token = response.json().get("access_token")
        if new_token:
            print("Token refreshed successfully")
            return new_token
    else:
        print(f"Token refresh failed: {response.text}")
    return None


def main():
    equations = load_json(EQUATIONS_FILE, {})
    history = load_json(HISTORY_FILE, [])

    eq_id, matched = resolve_equation(equations, history)
    eq = equations[eq_id]
    tag = "matches today's story" if matched else "random fallback"
    print(f"Selected equation: {eq_id} ({eq['name']}) — {tag}")

    # Build the four slide URLs: <slug>_slide1.png … _slide4.png
    slide_urls = [
        f"{IMAGE_BASE_URL}/{eq_id}_slide{n}.png"
        for n in range(1, NUM_SLIDES + 1)
    ]

    caption = f"{eq['caption']}\n\n{eq['hashtags']}"

    # Step 1: create a child container for each slide.
    child_ids = []
    for i, url in enumerate(slide_urls, start=1):
        print(f"Creating slide {i} container: {url}")
        child_ids.append(create_media_container(url, is_carousel_item=True))

    # Step 2: wait for all children to finish processing.
    print("Waiting for slide processing...")
    for cid in child_ids:
        wait_for_container(cid)

    # Step 3: create the carousel container.
    print("Creating carousel...")
    carousel_id = create_carousel(child_ids, caption)
    wait_for_container(carousel_id)

    # Step 4: publish.
    print("Publishing...")
    post_id = publish(carousel_id)
    print(f"Published! Post ID: {post_id}")

    # Step 5: update history.
    history.append(
        {
            "id": eq_id,
            "name": eq["name"],
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "post_id": post_id,
            "matched_story": matched,
        }
    )
    save_json(HISTORY_FILE, history)
    print("History updated.")

    # Step 6: refresh token.
    refresh_token()


if __name__ == "__main__":
    main()
