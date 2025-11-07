import os
import json
import hmac
import hashlib
import random
from collections import deque
import asyncio

from aiohttp import web
from twitchio.ext import commands

# ---------------- CONFIG ----------------
OAUTH_TOKEN = os.getenv("OAUTH_TOKEN")
CHANNEL = os.getenv("CHANNEL", "VahRuan")
EVENTSUB_SECRET = os.getenv("EVENTSUB_SECRET").encode()
DATA_FILE = os.getenv("DATA_FILE", "disk/inventory.json")
COMPONENT_TYPES = ["slow"]

# ---------------- Inventory ----------------
gain_queue = deque()

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

# ---------------- TwitchIO Bot ----------------
class SpellBot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=OAUTH_TOKEN,
            prefix="!",
            initial_channels=[CHANNEL]
        )

    async def event_ready(self):
        print(f"[Bot] Logged in as {self.nick}")
        # Announce gains in the background
        asyncio.create_task(self.announce_loop())

    async def event_message(self, message):
        if message.echo or message.author is None:
            return
        await self.handle_commands(message)

    async def announce_loop(self):
        while True:
            if gain_queue and self.connected_channels:
                user, comp = gain_queue.popleft()
                msg = f"@{user} received a {comp.capitalize()} component!"
                for channel in self.connected_channels:
                    await channel.send(msg)
                    print(f"[Bot] {msg}")
            await asyncio.sleep(1)

    @commands.command()
    async def inventory(self, ctx):
        user = ctx.author.name.lower()
        inv = load_data().get(user, {})
        if not inv:
            await ctx.send(f"@{user}, you have no components yet.")
            return
        parts = [f"{k.capitalize()} x{v}" for k, v in inv.items()]
        await ctx.send(f"@{user}, your components: " + ", ".join(parts))

bot_instance = SpellBot()

# ---------------- EventSub server (aiohttp) ----------------
async def handle_eventsub(request):
    print("=== EventSub request received ===")
    headers = request.headers
    body = await request.text()
    print("Headers:", dict(headers))
    print("Body:", body)

    message_type = headers.get("Twitch-Eventsub-Message-Type")
    data = await request.json()

    # Verification challenge
    if message_type == "webhook_callback_verification":
        print("[EventSub] Verification challenge received")
        return web.Response(text=data["challenge"])

    # HMAC verification
    msg_id = headers.get("Twitch-Eventsub-Message-Id")
    timestamp = headers.get("Twitch-Eventsub-Message-Timestamp")
    signature = headers.get("Twitch-Eventsub-Message-Signature")

    computed = "sha256=" + hmac.new(
        EVENTSUB_SECRET, (msg_id + timestamp + body).encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, computed):
        print("[EventSub] Invalid HMAC signature")
        return web.Response(status=403, text="Invalid")

    if message_type == "notification":
        event = data["event"]
        username = event["user_name"].lower()
        reward_title = event["reward"]["title"].lower()
        if "daily spell component" in reward_title:
            comp = random.choice(COMPONENT_TYPES)
            add_component(username, comp)
            gain_queue.append((username, comp))
            print(f"[EventSub] {username} gained {comp} component")
    return web.Response(status=200)

# ---------------- Main ----------------
async def main():
    # Run Twitch bot
    asyncio.create_task(bot_instance.start())

    # Run aiohttp server
    app = web.Application()
    app.router.add_post("/eventsub", handle_eventsub)
    port = int(os.environ.get("PORT", 10000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[Server] EventSub listening on port {port}")

    # Keep running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())
