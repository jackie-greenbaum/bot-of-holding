#!/usr/bin/python3
import os
import json
import hmac
import hashlib
import random
import threading
import asyncio
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

COMPONENT_TYPES = ["slow"]  # Only slow component

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
    data = load_data()
    inv = data.get(username, {})
    inv[component] = inv.get(component, 0) + 1
    data[username] = inv
    save_data(data)

# ---------------- Flask App ----------------
app = Flask(__name__)
bot_instance = None
bot_loop = None  # Background bot's event loop

@app.route("/eventsub", methods=["POST"])
def eventsub():
    """Handle Twitch EventSub notifications."""
    data = request.json
    headers = request.headers

    message_type = headers.get("Twitch-Eventsub-Message-Type")

    # Verification challenge
    if message_type == "webhook_callback_verification":
        print("[EventSub] Verification request received")
        return data["challenge"]

    # HMAC verification
    msg_id = headers.get("Twitch-Eventsub-Message-Id")
    timestamp = headers.get("Twitch-Eventsub-Message-Timestamp")
    signature = headers.get("Twitch-Eventsub-Message-Signature")
    body = request.get_data()

    computed = "sha256=" + hmac.new(
        EVENTSUB_SECRET, (msg_id + timestamp + body.decode()).encode(), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, computed):
        print("[EventSub] Invalid HMAC signature")
        return "Invalid", 403

    if message_type == "notification":
        event = data["event"]
        username = event["user_name"].lower()
        reward_title = event["reward"]["title"].lower()
        user_input = (event.get("user_input") or "").strip()

        if "daily spell component" in reward_title:
            component = random.choice(COMPONENT_TYPES)
            add_component(username, component)
            print(f"[EventSub] {username} received a {component} component")

            # Send message in Twitch chat
            if bot_instance and bot_loop and bot_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    bot_instance.send_message(f"@{username} received a {component} component!"),
                    bot_loop
                )
            else:
                print(f"[EventSub] Bot not ready to send message for {username}")

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

    async def event_ready(self):
        print(f"[Bot] Logged in as {self.user.name} (ready!)")

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

    async def send_message(self, message):
        """Send a message to the first connected channel."""
        if self.connected_channels:
            await self.connected_channels[0].send(message)
        else:
            print("[Bot] No connected channels to send message")

# ---------------- Run ----------------
def start_bot():
    global bot_instance, bot_loop
    bot_instance = SpellBot()
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    print("[Bot] Starting Twitch bot...")
    bot_loop.run_until_complete(bot_instance.start())

if __name__ == "__main__":
    # Start TwitchIO bot in background thread
    threading.Thread(target=start_bot, daemon=True).start()

    # Run Flask app in main thread
    port = int(os.environ.get("PORT", 5000))
    print(f"[Flask] Starting EventSub listener on port {port}...")
    app.run(host="0.0.0.0", port=port)
