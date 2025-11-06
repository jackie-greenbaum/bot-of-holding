#!/usr/bin/python3
import os, json, hmac, hashlib, threading, random, asyncio
from flask import Flask, request
from twitchio.ext import commands
from collections import deque

# ---------------- CONFIG ----------------
OAUTH_TOKEN = os.getenv("OAUTH_TOKEN")  # e.g. "oauth:xxxxxx"
CHANNEL = os.getenv("CHANNEL", "VahRuan")
EVENTSUB_SECRET = os.getenv("EVENTSUB_SECRET").encode()
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
BOT_ID = os.getenv("BOT_ID")

# Persistent file (Render free tier -> mounted under /disk)
DATA_FILE = os.getenv("DATA_FILE", "disk/inventory.json")
COMPONENT_TYPES = ["slow"]

# ---------------- Inventory Management ----------------
data_lock = threading.Lock()

def ensure_datafile():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w") as f:
            json.dump({}, f)

def load_data():
    ensure_datafile()
    with data_lock:
        with open(DATA_FILE, "r") as f:
            return json.load(f)

def save_data(data):
    ensure_datafile()
    with data_lock:
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
gain_queue = deque()
bot_instance = None  # Will be set later

@app.route("/eventsub", methods=["POST"])
def eventsub():
    print("=== EventSub request received ===")
    print("Headers:", dict(request.headers))
    print("Body:", request.data.decode())

    message_type = request.headers.get("Twitch-Eventsub-Message-Type")
    data = request.json

    # Verification challenge
    if message_type == "webhook_callback_verification":
        print("[EventSub] Received verification challenge")
        return data["challenge"]

    # HMAC verification
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
        reward_title = event["reward"]["title"].lower()
        result_text = (event.get("user_input") or "").lower().strip()

        if "daily spell component" in reward_title:
            component = random.choice(COMPONENT_TYPES)
            add_component(username, component)
            gain_queue.append((username, component))
            print(f"[EventSub] {username} gained {component} component from: '{result_text}'")

    return "", 200

# ---------------- TwitchIO Bot ----------------
class SpellBot(commands.Bot):
    def __init__(self):
        super().__init__(
            token=OAUTH_TOKEN,
            prefix="!",
            initial_channels=[CHANNEL],
            client_id=CLIENT_ID,
            client_secret=CLIENT_SECRET,
            bot_id=BOT_ID
        )

    async def event_ready(self):
        print(f"[Bot] Logged in as {self.user.name}")
        # Start the background task for announcing gains
        self.loop.create_task(self.announce_loop())

    async def event_message(self, message):
        if message.echo or message.author is None:
            return
        await self.handle_commands(message)

    async def announce_loop(self):
        """Continuously announce component gains in order."""
        await self.wait_for_ready()
        while True:
            if gain_queue:
                username, comp = gain_queue.popleft()
                channel = self.connected_channels[0]
                await channel.send(f"@{username} received a {comp.capitalize()} component!")
                print(f"[Bot] Announced in chat: {username} -> {comp}")
            await asyncio.sleep(1)  # prevent busy loop

    @commands.command()
    async def inventory(self, ctx):
        user = ctx.author.name.lower()
        inv = load_data().get(user, {})
        if not inv:
            await ctx.send(f"@{user}, you have no components yet.")
            return
        parts = [f"{k.capitalize()} x{v}" for k, v in inv.items()]
        await ctx.send(f"@{user}, your components: " + ", ".join(parts))

# ---------------- Run Flask + Bot ----------------
if __name__ == "__main__":
    bot_instance = SpellBot()

    # Run Flask in a background thread
    import threading
    port = int(os.environ.get("PORT", 10000))
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=port)).start()

    # Run bot in main thread
    bot_instance.run()