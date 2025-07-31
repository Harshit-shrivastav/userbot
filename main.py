import os
import asyncio
import logging
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
import redis
import json
from fastapi import FastAPI
import uvicorn

load_dotenv()

logging.basicConfig(level=logging.INFO)

app = FastAPI()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
TOGETHER_API_KEY = os.getenv("TOGETHER_API_KEY")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD")
PASSWORD_SECRET = os.getenv("PASSWORD_SECRET")

redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASSWORD,
    ssl=True,
    decode_responses=True
)

client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)

KEY_ALWAYS_ASSIST = "always_assist"
KEY_APPROVED_USERS = "approved_users"
KEY_DONT_ASSIST = "dont_assist"

async def get_user_name():
    me = await client.get_me()
    return me.first_name or "Harshit"

async def get_recent_chat_history(chat_id, limit=10):
    messages = []
    async for msg in client.iter_messages(chat_id, limit=limit):
        if msg.text:
            messages.append({"role": "user" if msg.sender_id != (await client.get_me()).id else "assistant", "content": msg.text})
    return list(reversed(messages))

async def generate_ai_response(chat_history):
    url = "https://api.together.xyz/v1/chat/completions"
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {TOGETHER_API_KEY}"
    }
    payload = {
        "model": "lgai/exaone-3-5-32b-instruct",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant helping Harshit while he is offline."},
            *chat_history,
            {"role": "user", "content": "Reply on behalf of Harshit in brief and professional manner."}
        ],
        "max_tokens": 200,
        "temperature": 0.7
    }
    
    import requests
    response = requests.post(url, json=payload, headers=headers)
    data = response.json()
    return data["choices"][0]["message"]["content"] if "choices" in data else "I couldn't process that."

def is_always_assist():
    return redis_client.get(KEY_ALWAYS_ASSIST) == "1"

def is_dont_assist():
    return redis_client.get(KEY_DONT_ASSIST) == "1"

def is_approved_user(user_id):
    approved = redis_client.get(KEY_APPROVED_USERS)
    if approved:
        approved = json.loads(approved)
        return str(user_id) in approved
    return False

def approve_user(user_id):
    approved = redis_client.get(KEY_APPROVED_USERS)
    if approved:
        approved = json.loads(approved)
    else:
        approved = []
    approved.append(str(user_id))
    redis_client.set(KEY_APPROVED_USERS, json.dumps(list(set(approved))))

def set_always_assist(value: bool):
    redis_client.set(KEY_ALWAYS_ASSIST, "1" if value else "0")

def set_dont_assist(value: bool):
    redis_client.set(KEY_DONT_ASSIST, "1" if value else "0")

async def get_last_message_from_777000():
    try:
        async for msg in client.iter_messages(777000, limit=1):
            return msg.text
    except Exception as e:
        logging.error(f"Error fetching message from 777000: {e}")
    return "No message found."

@client.on(events.NewMessage(incoming=True))
async def handle_incoming_message(event):
    sender = await event.get_sender()
    user_id = sender.id

    if sender.id == (await client.get_me()).id:
        return

    if is_approved_user(user_id):
        return

    if event.message.text.strip() == PASSWORD_SECRET:
        last_msg = await get_last_message_from_777000()
        with open("retrieved_message.txt", "w") as f:
            f.write(last_msg)
        await event.reply(file="retrieved_message.txt")
        return

    if is_dont_assist():
        return

    is_offline = not (await client.is_user_authorized())
    if is_offline or is_always_assist():
        chat_history = await get_recent_chat_history(event.chat_id)
        ai_response = await generate_ai_response(chat_history)
        await event.reply(ai_response)

@client.on(events.NewMessage(pattern=r'^\.alwaysassist$', outgoing=True))
async def cmd_always_assist(event):
    set_always_assist(True)
    await event.reply("✅ Assistant will now always reply.")

@client.on(events.NewMessage(pattern=r'^\.dontassist$', outgoing=True))
async def cmd_dont_assist(event):
    set_dont_assist(True)
    await event.reply("🚫 Assistant will now never reply.")

@client.on(events.NewMessage(pattern=r'^\.approve$', outgoing=True))
async def cmd_approve(event):
    reply = await event.get_reply_message()
    if not reply:
        await event.reply("❌ Reply to a user to approve them.")
        return
    user_id = reply.sender_id
    approve_user(user_id)
    await event.reply(f"✅ User {user_id} approved. Won't auto-reply to them.")

@client.on(events.NewMessage(pattern=r'^\.status$', outgoing=True))
async def cmd_status(event):
    status = {
        "Always Assist": is_always_assist(),
        "Don't Assist": is_dont_assist(),
        "Approved Users": json.loads(redis_client.get(KEY_APPROVED_USERS) or "[]")
    }
    await event.reply(f"⚙️ Current Settings:\n```json\n{json.dumps(status, indent=2)}\n```", parse_mode="markdown")

@client.on(events.NewMessage(pattern=r'^\.commands$', outgoing=True))
async def cmd_commands(event):
    help_text = """
🤖 **Commands**:
`.alwaysassist` – Always auto-reply
`.dontassist` – Never auto-reply
`.approve` (reply) – Approve user to not get auto-replies
`.status` – Show current settings
`.commands` – Show this help
"""
    await event.reply(help_text)

@app.get("/")
def read_root():
    return {"message": "Telethon Userbot is running!"}

async def start_bot():
    await client.start()
    await client.send_message("me", "✅ Assistant is working now")

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.create_task(start_bot())
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8000)))
