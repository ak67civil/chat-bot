"""
generate_session.py
--------------------
One-time script to log in with your phone number and generate a
Telethon session string. Run this ONCE, save the string safely
(e.g. in a .env file), then use it in userbot.py.

NEVER share this string with anyone or commit it to git/GitHub.
Anyone who has it has full access to your Telegram account.
"""

from telethon.sync import TelegramClient
from telethon.sessions import StringSession

# Get these from https://my.telegram.org -> API Development Tools
API_ID = int(input("Enter your API_ID: ").strip())
API_HASH = input("Enter your API_HASH: ").strip()

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    session_string = client.session.save()
    print("\n✅ Login successful!\n")
    print("Your session string (KEEP THIS SECRET):\n")
    print(session_string)
    print("\nSave it in a .env file as SESSION_STRING=... (see .env.example)")
