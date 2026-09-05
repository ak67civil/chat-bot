"""
bot.py — Telegram Control Bot
------------------------------
A normal Telegram BOT (made via BotFather) that acts as a remote control
for YOUR account. You send it your session string once; after that you
control everything with buttons — no typing commands needed.

Two clients run inside this one script:
  1. bot_client  -> the actual Bot (BotFather token), talks to YOU with menus/buttons
  2. user_client -> Telethon client logged in with YOUR session string,
                     does the real work (reading/sending/deleting your messages)

Only the Telegram user ID set as OWNER_ID can use this bot — everyone
else is ignored, so nobody can hijack your control bot.

SETUP:
    pip install -r requirements.txt

    .env needs:
        API_ID=...
        API_HASH=...
        BOT_TOKEN=...      (from @BotFather)
        OWNER_ID=...       (your own numeric Telegram user ID)
        SESSION_STRING=... (optional — can also /login inside the bot)
"""
print(">>> bot.py file loaded — version: v2-debug", flush=True)

import asyncio
import os
import sys
import zipfile
from datetime import datetime

from dotenv import load_dotenv
from telethon import TelegramClient, events, Button
from telethon.sessions import StringSession
from telethon.tl.types import User, Chat, Channel

# Force unbuffered stdout so print() shows up immediately in Heroku logs
# (Heroku/Python can buffer stdout and lose lines if the process exits fast)
sys.stdout.reconfigure(line_buffering=True)

load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
SAVED_SESSION = os.getenv("SESSION_STRING")  # optional, can also /login

WORKDIR = "/tmp/control_bot_exports"
os.makedirs(WORKDIR, exist_ok=True)

PAGE_SIZE = 8

bot = TelegramClient("bot_session", API_ID, API_HASH)
user_client: TelegramClient | None = None  # created after login

# per-user conversation state, e.g. waiting for a message to send/delete
state: dict[int, dict] = {}


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------

def owner_only(func):
    async def wrapper(event):
        if event.sender_id != OWNER_ID:
            return  # silently ignore anyone else
        return await func(event)
    return wrapper


def logged_in():
    return user_client is not None and user_client.is_connected()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def display_name(entity):
    if isinstance(entity, User):
        name = " ".join(filter(None, [entity.first_name, entity.last_name])) or "Unknown"
    else:
        name = getattr(entity, "title", "Unknown")
    return name


async def fmt_chat_header(entity):
    name = display_name(entity)
    username = f"@{entity.username}" if getattr(entity, "username", None) else "no_username"
    return f"Name: {name}\nUsername: {username}\nID: {entity.id}\n{'-'*30}\n"


async def export_single_chat(entity, limit=None):
    """Returns (filepath, message_count) for one chat's full export."""
    name = display_name(entity)
    username = getattr(entity, "username", None) or "no_username"
    safe_name = "".join(c for c in name if c.isalnum() or c in " _-").strip() or "chat"
    filename = f"{safe_name}_{username}_{entity.id}.txt"
    filepath = os.path.join(WORKDIR, filename)

    lines = [await fmt_chat_header(entity)]
    count = 0
    async for msg in user_client.iter_messages(entity, limit=limit, reverse=True):
        sender_label = "You" if msg.out else name
        ts = msg.date.strftime("%Y-%m-%d %H:%M")
        text = msg.text or "[media/no text]"
        lines.append(f"[{ts}] {sender_label}: {text}")
        count += 1

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return filepath, count


def chunk_buttons(items, page, prefix, per_page=PAGE_SIZE):
    """items: list of (label, callback_data). Returns button rows + nav row."""
    start = page * per_page
    page_items = items[start:start + per_page]
    rows = [[Button.inline(label, data)] for label, data in page_items]

    nav = []
    if page > 0:
        nav.append(Button.inline("⬅️ Prev", f"{prefix}:{page-1}"))
    if start + per_page < len(items):
        nav.append(Button.inline("Next ➡️", f"{prefix}:{page+1}"))
    if nav:
        rows.append(nav)
    rows.append([Button.inline("🔙 Main Menu", "menu")])
    return rows


async def get_dialog_lists():
    """Returns (dm_list, bot_list, group_channel_list, admin_list) as (label, id) tuples."""
    dms, bots, groups, admin = [], [], [], []
    async for dialog in user_client.iter_dialogs():
        entity = dialog.entity
        if isinstance(entity, User):
            if entity.bot:
                bots.append((display_name(entity), entity.id))
            else:
                dms.append((display_name(entity), entity.id))
        elif isinstance(entity, (Chat, Channel)):
            groups.append((display_name(entity), entity.id))
            try:
                perms = await user_client.get_permissions(entity, "me")
                if perms.is_admin or perms.is_creator:
                    admin.append((display_name(entity), entity.id))
            except Exception:
                pass
    return dms, bots, groups, admin


# ---------------------------------------------------------------------------
# Menus
# ---------------------------------------------------------------------------

MAIN_MENU = [
    [Button.inline("📂 My DM Chats (people)", "dm:0")],
    [Button.inline("🤖 My Bot Chats", "bot:0")],
    [Button.inline("👥 My Groups/Channels", "grp:0")],
    [Button.inline("👑 Channels I Admin/Own", "adm:0")],
    [Button.inline("📥 Export EVERYTHING (zip)", "exportall")],
    [Button.inline("ℹ️ Status", "status")],
]


async def show_main_menu(event):
    text = "🤖 **Control Bot Menu**\n\nChoose what you want to do:"
    if event.original_update and hasattr(event, "edit"):
        try:
            await event.edit(text, buttons=MAIN_MENU)
            return
        except Exception:
            pass
    await event.respond(text, buttons=MAIN_MENU)


def chat_action_menu(chat_id):
    return [
        [Button.inline("📄 View & Download History", f"hist:{chat_id}")],
        [Button.inline("✉️ Send Message", f"send:{chat_id}")],
        [Button.inline("🗑 Delete a Message", f"del:{chat_id}")],
        [Button.inline("🔙 Back", "menu")],
    ]


# ---------------------------------------------------------------------------
# Bot command handlers
# ---------------------------------------------------------------------------

@bot.on(events.NewMessage(pattern="/start"))
@owner_only
async def start_handler(event):
    if not logged_in():
        state[event.sender_id] = {"action": "awaiting_session"}
        await event.respond(
            "👋 Welcome. You're not logged in yet.\n\n"
            "🔑 Send your session string now (just paste it as a normal message).\n\n"
            "Don't have one? Generate it with `generate_session.py`, or use the "
            "separate Session Generator Bot."
        )
        return
    await show_main_menu(event)


async def do_login(event, session_str):
    global user_client
    msg = await event.respond("🔐 Logging in...")
    try:
        uc = TelegramClient(StringSession(session_str), API_ID, API_HASH)
        await uc.connect()
        if not await uc.is_user_authorized():
            await msg.edit("❌ Invalid or expired session string. Send /start to try again.")
            return
        me = await uc.get_me()
        user_client = uc
        await msg.edit(f"✅ Logged in as **{display_name(me)}** (@{me.username})")
        await show_main_menu(event)
    except Exception as e:
        await msg.edit(f"❌ Login failed: `{e}`\nSend /start to try again.")

    # 🔒 delete the message containing the session string for safety
    try:
        await event.delete()
    except Exception:
        pass


@bot.on(events.NewMessage(pattern=r"/login (.+)"))
@owner_only
async def login_handler(event):
    session_str = event.pattern_match.group(1).strip()
    await do_login(event, session_str)


@bot.on(events.NewMessage)
@owner_only
async def free_text_handler(event):
    """Handles replies when bot is waiting for session login, message-to-send, or ID-to-delete."""
    if event.raw_text.startswith("/"):
        return
    if event.sender_id not in state:
        return

    st = state[event.sender_id]

    if st.get("action") == "awaiting_session":
        state.pop(event.sender_id)
        await do_login(event, event.raw_text.strip())
        return

    st = state.pop(event.sender_id)
    chat_id = st["chat_id"]

    if st["action"] == "send":
        try:
            await user_client.send_message(chat_id, event.raw_text)
            await event.respond("✅ Message sent.", buttons=chat_action_menu(chat_id))
        except Exception as e:
            await event.respond(f"❌ Failed to send: `{e}`")

    elif st["action"] == "delete":
        try:
            msg_id = int(event.raw_text.strip())
            await user_client.delete_messages(chat_id, [msg_id], revoke=True)
            await event.respond(
                "✅ Message deleted (for both sides, if within Telegram's allowed window).",
                buttons=chat_action_menu(chat_id),
            )
        except Exception as e:
            await event.respond(f"❌ Failed to delete: `{e}`")


# ---------------------------------------------------------------------------
# Callback (button click) handlers
# ---------------------------------------------------------------------------

@bot.on(events.CallbackQuery)
@owner_only
async def callback_handler(event):
    data = event.data.decode()

    if not logged_in() and data != "menu":
        await event.answer("Please /login first.", alert=True)
        return

    if data == "menu":
        await show_main_menu(event)

    elif data == "status":
        me = await user_client.get_me()
        await event.edit(
            f"✅ Logged in as **{display_name(me)}**\nID: `{me.id}`",
            buttons=MAIN_MENU,
        )

    elif data.startswith("dm:"):
        page = int(data.split(":")[1])
        dms, _, _, _ = await get_dialog_lists()
        buttons = chunk_buttons(
            [(name, f"chat:{cid}") for name, cid in dms], page, "dm"
        )
        await event.edit(f"📂 **Your DM chats** ({len(dms)} total):", buttons=buttons)

    elif data.startswith("bot:"):
        page = int(data.split(":")[1])
        _, bots, _, _ = await get_dialog_lists()
        buttons = chunk_buttons(
            [(name, f"chat:{cid}") for name, cid in bots], page, "bot"
        )
        await event.edit(f"🤖 **Your bot chats** ({len(bots)} total):", buttons=buttons)

    elif data.startswith("grp:"):
        page = int(data.split(":")[1])
        _, _, groups, _ = await get_dialog_lists()
        buttons = chunk_buttons(
            [(name, f"chat:{cid}") for name, cid in groups], page, "grp"
        )
        await event.edit(f"👥 **Your groups/channels** ({len(groups)} total):", buttons=buttons)

    elif data.startswith("adm:"):
        page = int(data.split(":")[1])
        _, _, _, admin = await get_dialog_lists()
        buttons = chunk_buttons(
            [(name, f"chat:{cid}") for name, cid in admin], page, "adm"
        )
        await event.edit(f"👑 **Where you're admin/owner** ({len(admin)} total):", buttons=buttons)

    elif data.startswith("chat:"):
        chat_id = int(data.split(":")[1])
        entity = await user_client.get_entity(chat_id)
        await event.edit(
            f"**{display_name(entity)}**\nWhat do you want to do?",
            buttons=chat_action_menu(chat_id),
        )

    elif data.startswith("hist:"):
        chat_id = int(data.split(":")[1])
        await event.answer("Fetching history...")
        await event.edit("📄 Fetching full chat history, please wait...")
        entity = await user_client.get_entity(chat_id)
        filepath, count = await export_single_chat(entity)
        await bot.send_file(
            event.chat_id, filepath,
            caption=f"📄 {display_name(entity)} — {count} messages",
        )
        await event.edit(f"**{display_name(entity)}**", buttons=chat_action_menu(chat_id))

    elif data.startswith("send:"):
        chat_id = int(data.split(":")[1])
        state[event.sender_id] = {"action": "send", "chat_id": chat_id}
        await event.edit("✉️ Send me the message text now (as a normal reply).")

    elif data.startswith("del:"):
        chat_id = int(data.split(":")[1])
        state[event.sender_id] = {"action": "delete", "chat_id": chat_id}
        await event.edit(
            "🗑 Send me the **message ID** to delete.\n"
            "(Tip: forward the message to @ShowJsonBot or check history export "
            "to find the ID, or reply with the ID shown in `.history`.)"
        )

    elif data == "exportall":
        await event.edit("📥 Exporting everything (people + bots), this may take a while...")
        dms, bots_list, _, _ = await get_dialog_lists()
        all_private = dms + bots_list
        zip_path = os.path.join(WORKDIR, f"all_chats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip")

        with zipfile.ZipFile(zip_path, "w") as zf:
            for name, cid in all_private:
                entity = await user_client.get_entity(cid)
                filepath, _ = await export_single_chat(entity)
                zf.write(filepath, arcname=os.path.basename(filepath))

        await bot.send_file(
            event.chat_id, zip_path,
            caption=f"📥 Exported {len(dms)} people chats + {len(bots_list)} bot chats.",
        )
        await show_main_menu(event)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def main():
    global user_client

    # 🔍 Diagnostic: confirm BOT_TOKEN actually reached this process before
    # calling start() — if this print doesn't show a masked token, the
    # problem is env vars not reaching the worker dyno, not the code.
    print(">>> main() started, checking env vars...", flush=True)
    if not BOT_TOKEN:
        print("❌ FATAL: BOT_TOKEN is missing/empty in this process's environment.", flush=True)
        print("Check: heroku config:get BOT_TOKEN", flush=True)
        raise SystemExit(1)
    print(f"✅ BOT_TOKEN loaded (length={len(BOT_TOKEN)}, starts with '{BOT_TOKEN[:6]}...')", flush=True)

    await bot.start(bot_token=BOT_TOKEN)
    print("Bot started.", flush=True)

    if SAVED_SESSION:
        uc = TelegramClient(StringSession(SAVED_SESSION), API_ID, API_HASH)
        await uc.connect()
        if await uc.is_user_authorized():
            user_client = uc
            me = await uc.get_me()
            print(f"Auto-logged in as {display_name(me)}")

    await bot.run_until_disconnected()


if __name__ == "__main__":
    bot.loop.run_until_complete(main())
