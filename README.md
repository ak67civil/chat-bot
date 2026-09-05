# Telegram Control Bot (Button-based)

A real Telegram bot (made via BotFather) that acts as a **remote control**
for your own Telegram account. You log in once with your session string
(inside the bot, privately), then everything works by **tapping buttons**
on your phone — no typing commands.

## What it can do

Covers everything your account is part of:

- 📂 **My DM Chats (people)** — every private chat with a real person
- 🤖 **My Bot Chats** — every private chat with a bot you've used
- 👥 **My Groups/Channels** — every group/channel you're a member of
- 👑 **Channels I Admin/Own** — only the ones where you have admin rights
- Per chat (people, bots, or groups):
  - 📄 **View & Download History** — sends you a `.txt` file with the full
    conversation (both sides), formatted with Name / Username / ID header
  - ✉️ **Send Message** — send a message to that chat
  - 🗑 **Delete a Message** — delete a message by its ID (for both sides,
    if within Telegram's allowed time window — this uses Telegram's normal
    "Delete for everyone", same as doing it manually in the app)
- 📥 **Export EVERYTHING** — zips every person + bot chat into one file
  each, named `Name_username_ID.txt`, and sends you the zip
  (group/channel bulk export can be added the same way if you need it too)

## Why two "accounts" are involved

- **The Bot** (BotFather) — this is what you actually chat with on your
  phone. It only understands you (`OWNER_ID`), ignores everyone else.
- **Your account (session string)** — the bot uses this in the background
  to actually read/send/delete on your real account. You never expose
  this to anyone else — you send it once, privately, to your own bot.

## Setup

### 1. Create a real Bot with BotFather
- Open Telegram, message **@BotFather**
- Send `/newbot`, follow the steps
- Copy the **bot token** it gives you

### 2. Get your API_ID / API_HASH
- Go to https://my.telegram.org → API Development Tools

### 3. Get your own numeric Telegram ID
- Message **@userinfobot** on Telegram, it replies with your ID

### 4. Get your session string (one-time)
Use the `generate_session.py` script from before (or reuse it), run it
once on your computer, save the printed string somewhere safe.

### 5. Fill in `.env`
Copy `.env.example` → `.env`:
```
API_ID=12345678
API_HASH=your_api_hash
BOT_TOKEN=123456:ABC-your-bot-token
OWNER_ID=your_numeric_id
SESSION_STRING=your_session_string   # optional, or /login inside the bot
```

### 6. Install & run
```bash
pip install -r requirements.txt
python bot.py
```

Open your bot on Telegram, send `/start`. If you didn't set
`SESSION_STRING` in `.env`, send:
```
/login your_session_string_here
```
(The bot auto-deletes that message right after, so it doesn't sit in
the chat.)

## Deploying on Heroku (so it runs 24/7 from your phone)

```bash
heroku login
heroku create your-control-bot
git init && git add . && git commit -m "control bot"
git push heroku main

heroku config:set API_ID=xxx API_HASH=xxx BOT_TOKEN=xxx OWNER_ID=xxx SESSION_STRING=xxx
heroku ps:scale web=0 worker=1
heroku logs --tail
```

After this, close your laptop — the bot keeps running on Heroku, and you
control everything from your phone by chatting with your bot.

## Important notes

- **Only you can use this bot** — it checks `OWNER_ID` on every message
  and button press, ignoring anyone else.
- **Delete** uses Telegram's real "delete for everyone" — same
  restrictions apply as doing it manually (works reliably for messages
  you sent; for messages others sent in a group where you're admin, it
  may also work depending on your rights).
- **History exports** only include chats you're already part of.
  Deleted messages that weren't previously saved can't be recovered.
- **Rate limits**: exporting a LOT of chats back-to-back can trigger
  Telegram's flood limits — the bot will just wait/retry if that happens
  (Telethon handles this automatically), so large exports can take a
  few minutes.
- Treat your session string like a password. The `/login` message is
  auto-deleted, but the string still lives in your bot's memory/config —
  keep your Heroku account secured (2FA on Heroku too, ideally).
