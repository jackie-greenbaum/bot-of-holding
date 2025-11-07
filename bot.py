#!/usr/bin/env python3
import os
import json
import hmac
import hashlib
import random
import asyncio
from collections import deque
from flask import Flask, request
from twitchio.ext import commands

# ---------------- CONFIG ----------------
OAUTH_TOKEN = os.getenv("OAUTH_TOKEN")  # e.g., "oauth:xxxx"
CHANNEL = os.getenv("CHANNEL", "VahRuan")
EVENTSUB_SECRET = os.getenv("EVENTSUB_SECRET").encode()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BOT_ID = os.getenv("BOT_ID")
DATA_FILE = os.getenv("DATA_FILE", "disk/inventory.json")

COMPONENT_TYPES = ["slow", "fast", "fire", "ice"]

# ---------------- Inventory ----------------
data_lock = asyncio.Lock()
gain_queue = deque()

async def ensure_datafile():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        async with aiofiles.open(DATA_FILE, "w") as f:
            await f.write("{}")

async def load_data():
    await ensure_datafile()
    async with data_lock:
        async with aiofiles.open(DATA_FILE, "r") as f:
            return json.loads(await f.read())

async def save_data(data):
    await ensure_datafile()
    async with data_lock:
        async with aiofiles.open(DATA_FILE, "w") as f:
            await f.write(json.dumps(data, indent=2))

async def add_component(username, component):
    data = await load_data()
    inv = data.get(username, {})
    inv[component] = inv.get(component, 0) + 1
    data[username] = inv
    await save_data(data)

# ---------------- Flask ----------------
app = Flask(__name__)
bot_instance = None  # Set later

@app.route("/eventsub", methods=["POST"])
async def eventsub():
    message_type = request.headers.get("Twitch-Eventsub-Message-Type")
    data = request.json

    if message_type == "webhook_callback_verification":
        return data["challenge"]

    # HMAC verification
    msg_id = request.headers.get("Twitch-Eventsub-Message-Id")
    timestamp = request.headers.get("Twitch-Eventsub-Message-Timestamp")
    signature = request.headers.get("Twitch-Eventsub-Message-Signature")
    body = request.data.decode()

    computed = "sha256=" + hmac.new(EVENTSUB_SECRET, (msg_id + timestamp + body).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, computed):
        return "Invalid", 403

    if message_type == "notification":
        event = data["event"]
        username = event["user_name"].lower()
        reward_title = event["reward"]["title"].lower()
        result_text = (event.get("user_input") or "").lower().strip()

        if "daily spell component" in reward_title:
            component = random.choice(COMPONENT_TYPES)
            await add_component(username, component)
            gain_queue.append((username, component))
            await announce_gain(username, component)

    return "", 200

async def announce_gain(username, component):
    if bot_instance and bot_instance.connected_channels:
        channel = bot_instance.connected_channels[0]
        await channel.send(f"@{username} received a {component.capitalize()} component!")

# ---------------- Twitch Bot ----------------
class SpellBot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=OAUTH_TOKEN,
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            bot_id=BOT_ID,
            prefix="!",
            initial_channels=[CHANNEL]
        )

    async def event_ready(self):
        print(f"[Bot] Logged in as {self.user.name}")

    async def event_message(self, message):
        if message.echo or message.author is None:
            return
        await self.handle_commands(message)

    @commands.command()
    async def inventory(self, ctx):
        user = ctx.author.name.lower()
        data = await load_data()
        inv = data.get(user, {})
        if not inv:
            await ctx.send(f"@{user}, you have no components yet.")
            return
        parts = [f"{k.capitalize()} x{v}" for k, v in inv.items()]
        await ctx.send(f"@{user}, your components: " + ", ".join(parts))

# ---------------- Run everything ----------------
async def main():
    global bot_instance
    bot_instance = SpellBot()
    # Start bot and Flask concurrently
    import hypercorn.asyncio
    from hypercorn.config import Config

    port = int(os.environ.get("PORT", 10000))
    config = Config()
    config.bind = [f"0.0.0.0:{port}"]

    await asyncio.gather(
        bot_instance.start(),
        hypercorn.asyncio.serve(app, config)
    )

if __name__ == "__main__":
    import aiofiles
    asyncio.run(main())
