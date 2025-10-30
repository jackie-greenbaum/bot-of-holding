#!/usr/bin/python3

import json, os, hmac, hashlib, threading, random, asyncio
from flask import Flask, request
from twitchio.ext import commands

# ---------------- CONFIG ----------------
OAUTH_TOKEN = os.environ.get("OAUTH_TOKEN")
CHANNEL = os.environ.get("CHANNEL", "VahRuan")
EVENTSUB_SECRET = os.environ.get("EVENTSUB_SECRET").encode()
DATA_FILE = os.environ.get("DATA_FILE", "disk/inventory.json")
CLIENT_ID = os.environ.get("CLIENT_ID")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
BOT_ID = os.environ.get("BOT_ID")

COMPONENT_TYPES = ["slow", "fast", "fire", "ice"]  # example component types

# ------------- Inventory Management -------------
data_lock = threading.Lock()

def load_data():
    with data_lock:
        if os.path.exists(DATA_FILE):
            with open(DATA_FILE, "r") as f:
                return json.load(f)
        return {}

def save_data(data):
    with data_lock:
        with open(DATA_FILE, "w") as f:
            json.dump(data, f, indent=2)

def add_component(username, component):
    data = load_data()
    inv = data.get(username, {})
    inv[component] = inv.get(component, 0) + 1
    data[username] = inv
    save_data(data)

# ------------- Flask App -------------
app = Flask(__name__)
bot_instance = None  # Will be set after bot creation

def announce_gain(username, component):
    """Send a message to chat from any thread."""
    if bot_instance is None:
        return

    channel = bot_instance.get_channel(CHANNEL)
    if channel is None:
        # Bot hasn't joined the channel yet
        print(f"[announce_gain] Bot not ready to send message for {username}")
        return

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

# ------------- TwitchIO Bot -------------
class SpellBot(commands.Bot):
    def __init__(self):
        super().__init__(
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            bot_id=BOT_ID,
            token=OAUTH_TOKEN,
            prefix="!",
            initial_channels=[CHANNEL]
        )

    async def event_ready(self):
        print(f"[Bot] Logged in and ready!")

    async def event_message(self, message):
        # Ignore echoes or system messages
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

# ------------- Run Flask and Bot -------------
def run_flask():
    app.run(host="0.0.0.0", port=5000)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()

    bot_instance = SpellBot()
    bot_instance.run()
