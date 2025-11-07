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
import random

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

def announce_gain(username, component):
    """Send a message to chat from any thread."""
    if bot_instance is None:
        return

    channel = bot_instance.get_channel(CHANNEL)
    if channel is None:
        # Bot hasn't joined the channel yet
        print(f"[announce_gain] Bot not ready to send message for {username}")
        return

    # Schedule the send on the bot's event loop
    coro = channel.send(f"@{username} received a {component.capitalize()} component!")
    asyncio.run_coroutine_threadsafe(coro, bot_instance.loop)

@app.route("/eventsub", methods=["POST"])
def eventsub():
    print("=== EventSub request received ===")
    print("Headers:", request.headers)
    print("Body:", request.data.decode())

    message_type = request.headers.get("Twitch-Eventsub-Message-Type")
    data = request.json

    # Handle verification first
    if message_type == "webhook_callback_verification":
        print("[EventSub] Received verification challenge")
        return data["challenge"]

    # HMAC verification for notifications
    msg_id = request.headers.get("Twitch-Eventsub-Message-Id")
    timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp")
    signature = request.headers.get("Twitch-Eventsub-Message-Signature")
    body = request.data.decode()

    computed = "sha256=" + hmac.new(EVENTSUB_SECRET, (msg_id + timestamp + body).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, computed):
        print("[EventSub] Invalid HMAC signature")
        return "Invalid", 403

    # Handle notifications
    if message_type == "notification":
        event = data["event"]
        username = event["user_name"].lower()
        reward_title = event["reward"]["title"].lower()  # lowercase for comparison
        result_text = (event.get("user_input") or "").lower().strip()

        if "daily spell component" in reward_title:
            component = random.choice(COMPONENT_TYPES)
            add_component(username, component)
            announce_gain(username, component)
            print(f"[EventSub] {username} gained {component} component from: '{result_text}'")

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
        self.ready_event = asyncio.Event()

    async def event_ready(self):
        logging.info(f"[Bot] Logged in as {self.user.name} (ready!)")
        # Signal that bot is ready
        self.ready_event.set()

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
