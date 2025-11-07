#!/usr/bin/python3
import os
import json
import hmac
import hashlib
import threading
import asyncio
import logging
from flask import Flask, request
from twitchio.ext import commands

# ---------------- CONFIG ----------------
OAUTH_TOKEN = os.getenv("OAUTH_TOKEN")  # e.g. "oauth:xxxxxx"
CHANNEL = os.getenv("CHANNEL", "VahRuan")
EVENTSUB_SECRET = os.getenv("EVENTSUB_SECRET", "super_secret").encode()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BOT_ID = os.getenv("BOT_ID")
DATA_FILE = os.getenv("DATA_FILE", "disk/inventory.json")

COMPONENT_TYPES = ["slow"]  # Only "slow" component

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# ---------------- Inventory Management ----------------
def ensure_datafile():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)

def load_data():
    ensure_datafile()
    with open(DATA_FILE, "r") as f:
        return json.load(f)

def save_data(data):
    ensure_datafile()
    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)

def add_component(username, component):
    try:
        data = load_data()
        inv = data.get(username, {})
        inv[component] = inv.get(component, 0) + 1
        data[username] = inv
        save_data(data)
        logging.info("[Bot] Added component '%s' for user '%s'", component, username)
    except Exception as e:
        logging.error("[Bot] Error adding component: %s", e)

# ---------------- Flask App ----------------
app = Flask(__name__)
bot_instance = None  # Will be set when bot starts

@app.route("/eventsub", methods=["POST"])
def eventsub():
    """Handle Twitch EventSub notifications."""
    data = request.json
    headers = request.headers

    logging.info("[EventSub] Received request")
    logging.info("[EventSub] Headers: %s", dict(headers))
    logging.info("[EventSub] Payload: %s", json.dumps(data, indent=2))

    message_type = headers.get("Twitch-Eventsub-Message-Type")

    # Verification challenge
    if message_type == "webhook_callback_verification":
        logging.info("[EventSub] Verification challenge received: %s", data.get("challenge"))
        return data["challenge"]

    # HMAC verification
    msg_id = headers.get("Twitch-Eventsub-Message-Id")
    timestamp = headers.get("Twitch-Eventsub-Message-Timestamp")
    signature = headers.get("Twitch-Eventsub-Message-Signature")
    body = request.get_data()

    computed = "sha256=" + hmac.new(
        EVENTSUB_SECRET,
        (msg_id + timestamp + body.decode()).encode(),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, computed):
        logging.warning("[EventSub] Invalid signature!")
        return "Invalid signature", 403

    # Notification
    if message_type == "notification":
        event = data["event"]
        logging.info("[EventSub] Notification event: %s", event)

        username = event["user_name"].lower()
        reward_title = event["reward"]["title"].strip().lower()
        logging.info("[EventSub] Checking reward title: '%s'", reward_title)

        if "daily spell component" in reward_title:
            component = "slow"
            add_component(username, component)

            async def send_message():
                if bot_instance.channel_obj:
                    try:
                        await bot_instance.channel_obj.send(f"@{username} received a {component} component!")
                        logging.info("[Bot] Sent message for %s", username)
                    except Exception as e:
                        logging.error("[Bot] Error sending message: %s", e)
                else:
                    logging.error("[Bot] Channel object not ready!")

            if bot_instance:
                bot_instance.loop.create_task(send_message())

    return "", 200

# ---------------- TwitchIO Bot ----------------
class SpellBot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=OAUTH_TOKEN,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            bot_id=BOT_ID,
            prefix="!",
            initial_channels=[CHANNEL],
        )
        self.channel_obj = None  # Will store joined channel

    async def event_ready(self):
        logging.info(f"[Bot] Logged in!")
        # Store channel object for immediate sending
        self.channel_obj = self.get_channel(CHANNEL)
        if self.channel_obj:
            logging.info(f"[Bot] Channel object ready: {CHANNEL}")
        else:
            logging.warning(f"[Bot] Failed to get channel object for {CHANNEL}")

    async def event_message(self, message):
        if message.echo or message.author is None:
            return
        await self.handle_commands(message)

    @commands.command()
    async def inventory(self, ctx):
        user = ctx.author.name.lower()
        inv = load_data().get(user, {})
        if not inv:
            await ctx.send(f"@{user}, you have no components yet.")
            return
        parts = [f"{k.capitalize()} x{v}" for k, v in inv.items()]
        await ctx.send(f"@{user}, your components: " + ", ".join(parts))

# ---------------- Run Flask in Thread ----------------
def start_flask():
    port = int(os.environ.get("PORT", 5000))
    logging.info(f"[Flask] Starting server on 0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ---------------- Run ----------------
if __name__ == "__main__":
    bot_instance = SpellBot()

    # Start Flask in a background thread
    threading.Thread(target=start_flask, daemon=True).start()

    # Run Twitch bot in main thread
    bot_instance.run()
