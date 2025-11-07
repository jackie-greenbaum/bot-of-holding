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
OAUTH_TOKEN = os.getenv("OAUTH_TOKEN")  # e.g., "oauth:xxxxxx"
CHANNEL = os.getenv("CHANNEL", "VahRuan")
EVENTSUB_SECRET = os.getenv("EVENTSUB_SECRET").encode()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BOT_ID = os.getenv("BOT_ID")
DATA_FILE = os.getenv("DATA_FILE", "disk/inventory.json")

COMPONENT_TYPES = ["slow"]  # only "slow" component

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
bot_instance = None  # will be set in main thread

@app.route("/eventsub", methods=["POST"])
def eventsub():
    data = request.json
    headers = request.headers

    message_type = headers.get("Twitch-Eventsub-Message-Type")

    if message_type == "webhook_callback_verification":
        return data["challenge"]

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
        return "Invalid signature", 403

    if message_type == "notification":
        event = data["event"]
        username = event["user_name"].lower()
        reward_title = event["reward"]["title"].lower()

        if "daily spell component" in reward_title:
            component = "slow"  # only slow
            add_component(username, component)

            # Send message in Twitch chat
            if bot_instance and bot_instance.is_ready:
                channel = bot_instance.get_channel(CHANNEL)
                if channel:
                    asyncio.run_coroutine_threadsafe(
                        channel.send(f"@{username} received a {component} component!"),
                        bot_instance.loop
                    )
                else:
                    print("[Bot] Channel not ready yet")

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
def start_flask():
    port = int(os.environ.get("PORT", 5000))
    print(f"[Flask] Starting EventSub listener on port {port}...")
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Start Flask in a background thread
    threading.Thread(target=start_flask, daemon=True).start()

    # Run Twitch bot in main thread
    bot_instance = SpellBot()
    bot_instance.run()  # safe in main thread
