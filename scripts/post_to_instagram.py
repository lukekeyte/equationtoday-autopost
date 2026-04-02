import json
import os
import random
import time
from datetime import datetime, timezone
import requests

# ─── Configuration (from GitHub Secrets) ───
ACCESS_TOKEN = os.environ["IG_ACCESS_TOKEN"]
IG_USER_ID = os.environ["IG_USER_ID"]
IMAGE_BASE_URL = os.environ["IMAGE_BASE_URL"]  # e.g. https://yourusername.github.io/equationtoday-images/images
GRAPH_API_VERSION = "v25.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

# ─── Paths ───
EQUATIONS_FILE = "data/equations.json"
HISTORY_FILE = "data/post_history.json"

# How many posts before an equation can be reused
# With ~194 equations, this means roughly 6 months before a repeat
COOLDOWN = 120


def load_json(path):
    with open(path, "r") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def pick_equation(equations, history):
    """Pick a random equation that hasn't been posted recently."""
    recent_ids = [h["id"] for h in history[-COOLDOWN:]]
    available = [eid for eid in equations if eid not in recent_ids]

    if not available:
        # All equations used recently — pick the least recent
        available = [h["id"] for h in history[:10]]

    return random.choice(available)


def create_media_container(image_url, is_carousel_item=False):
    """Create a media container for a single image."""
    params = {
        "image_url": image_url,
        "access_token": ACCESS_TOKEN,
    }
    if is_carousel_item:
        params["is_carousel_item"] = "true"

    response = requests.post(f"{BASE_URL}/{IG_USER_ID}/media", params=params)
    response.raise_for_status()
    return response.json()["id"]


def create_carousel(children_ids, caption):
    """Create a carousel container from child containers."""
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


def check_container_status(container_id):
    """Check if a media container is ready to publish."""
    params = {
        "fields": "status_code",
        "access_token": ACCESS_TOKEN,
    }
    response = requests.get(f"{BASE_URL}/{container_id}", params=params)
    response.raise_for_status()
    return response.json().get("status_code")


def wait_for_container(container_id, max_wait=60):
    """Wait for a container to finish processing."""
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
    # Load data
    equations = load_json(EQUATIONS_FILE)
    history = load_json(HISTORY_FILE)

    # Pick an equation
    eq_id = pick_equation(equations, history)
    eq = equations[eq_id]
    print(f"Selected equation: {eq_id} ({eq['name']})")

    # Build image URLs
    # Images are named: equationname_1.png (equation) and equationname_2.png (definition)
    slide1_url = f"{IMAGE_BASE_URL}/{eq_id}_1.png"
    slide2_url = f"{IMAGE_BASE_URL}/{eq_id}_2.png"

    # Build caption
    caption = f"{eq['caption']}\n\n{eq['hashtags']}"

    # Step 1: Create child containers for each slide
    print(f"Creating slide 1 container: {slide1_url}")
    child1_id = create_media_container(slide1_url, is_carousel_item=True)

    print(f"Creating slide 2 container: {slide2_url}")
    child2_id = create_media_container(slide2_url, is_carousel_item=True)

    # Step 2: Wait for both to finish processing
    print("Waiting for processing...")
    wait_for_container(child1_id)
    wait_for_container(child2_id)

    # Step 3: Create the carousel container
    print("Creating carousel...")
    carousel_id = create_carousel([child1_id, child2_id], caption)
    wait_for_container(carousel_id)

    # Step 4: Publish
    print("Publishing...")
    post_id = publish(carousel_id)
    print(f"Published! Post ID: {post_id}")

    # Step 5: Update history
    history.append(
        {
            "id": eq_id,
            "name": eq["name"],
            "posted_at": datetime.now(timezone.utc).isoformat(),
            "post_id": post_id,
        }
    )
    save_json(HISTORY_FILE, history)
    print("History updated.")

    # Step 6: Refresh token
    refresh_token()


if __name__ == "__main__":
    main()
