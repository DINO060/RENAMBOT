from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = int(input("📲 API_ID: "))
API_HASH = input("🔑 API_HASH: ")

print("📞 Entrez votre numéro de téléphone (ex: +336XXXXXXXX) :", flush=True)
phone = input("> ")

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    client.start(phone=phone)
    print("\n✅ SESSION_STRING générée :")
    print("👇👇👇 Copiez et collez dans config.py 👇👇👇\n")
    print(client.session.save())
