"""Offline check (python batch_check.py), fake Telegram, temp dir. RENAMBOT: several files at once → one question; « Thumbnail on all » → each file back with the thumbnail,
in order, names kept, counted once in the quota. A single file: the usual question. Fake Telegram, temp dir."""
import asyncio
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

SRC = Path(__file__).resolve().parent
WORK = Path(tempfile.mkdtemp())
shutil.copy(SRC / "main.py", WORK / "main.py")
shutil.copytree(SRC / "utils", WORK / "utils", ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(WORK)
sys.path.insert(0, str(WORK))
sys.stdout.reconfigure(errors="replace")
os.environ.update(API_ID="1", API_HASH="x", TOKEN="1:x", ADMIN_IDS="42", QUOTA_DB_PATH=str(WORK / "q.db"),
                  DAILY_LIMIT="10", QUOTA_TZ="UTC")
# what an older user left on disk before this start (another user, never seen since the restart)
(WORK / "user_preferences.json").write_text('{"555": {"custom_text": "@Chan", "text_position": "end", "clean_tags": true}}')
(WORK / "user_usage.json").write_text('{"555": {"daily_bytes": 0, "last_reset": "2026-01-01T00:00:00", '
                                      '"last_file_time": "2026-01-01T00:00:00"}}')

import telethon  # noqa: E402

sent = []


class Msg(SimpleNamespace):
    async def delete(self):
        self.deleted = True

    async def edit(self, *a, **k):
        return self


class FakeClient:
    def __init__(self, *a, **k):
        pass

    def start(self, **k):
        return self

    def on(self, *a, **k):
        return lambda f: f

    async def send_message(self, chat, text="", **kw):
        sent.append(SimpleNamespace(kind="msg", chat=chat, text=text, buttons=kw.get("buttons"), reply_to=kw.get("reply_to")))
        return Msg(id=len(sent))

    async def send_file(self, chat, file, **kw):
        sent.append(SimpleNamespace(kind="file", chat=chat, name=kw.get("file_name"), thumb=kw.get("thumb"),
                                    caption=kw.get("caption")))
        return Msg(id=len(sent))

    async def edit_message(self, *a, **k):
        pass

    async def __call__(self, *a, **k):
        return None


telethon.TelegramClient = FakeClient
import datetime as _dt  # noqa: E402

import main  # noqa: E402
import utils.quota as _quota  # noqa: E402

_quota.ZoneInfo = lambda name: _dt.timezone.utc     # this Windows Python has no tz database (the VPS has)

main.BATCH_WINDOW = 0.3
ok = True


def check(name, cond, detail=""):
    global ok
    ok &= bool(cond)
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  {detail}"))


def labels(buttons):
    return [b.text for row in (buttons or []) for b in row]


def file_event(uid, msg_id, name, mime="application/pdf"):
    async def download_media(file=None, progress_callback=None):
        Path(file).write_bytes(b"%PDF fake " + name.encode())
        return file

    async def reply(text, **kw):
        return await main.bot.send_message(uid, text, **kw)

    f = SimpleNamespace(name=name, size=1000 + msg_id, mime_type=mime)
    message = SimpleNamespace(id=msg_id, file=f, media=f"MEDIA-{msg_id}", video=None, download_media=download_media)
    return SimpleNamespace(sender_id=uid, is_private=True, file=f, message=message, chat_id=uid, reply=reply)


class Callback:
    def __init__(self, uid, data):
        self.data, self.query, self.chat_id = data.encode(), SimpleNamespace(user_id=uid), uid
        self.edits, self.answers = [], []

    async def edit(self, text, **kw):
        self.edits.append(text)

    async def answer(self, text=None, **kw):
        self.answers.append(text)


def quota_used(uid):
    with sqlite3.connect(WORK / "q.db") as c:
        row = c.execute("SELECT SUM(used) FROM quotas WHERE user_id = ?", (uid,)).fetchone()
    return row[0] or 0


async def main_test():
    Path(main.THUMBNAIL_DIR).mkdir(exist_ok=True)
    Path(main.THUMBNAIL_DIR, "7.jpg").write_bytes(b"jpg")
    Path(main.THUMBNAIL_DIR, "42.jpg").write_bytes(b"jpg")

    # 1. one file alone: the usual question
    await main.file_handler(file_event(7, 10, "Alone.pdf"))
    await asyncio.sleep(0.5)
    q = sent[-1]
    check("one file: the usual question, as before", "FILE INFORMATION" in q.text and q.reply_to == 10
          and labels(q.buttons) == ["🖼️ Add Thumbnail", "✏️ Rename Only", "❌ Cancel"], str(labels(q.buttons)))

    # 2. 4 files at once: one question
    mark = len(sent)
    for i, name in enumerate(["Blue Box 01.pdf", "Blue Box 02.pdf", "Blue Box 03.pdf", "Blue Box 04.pdf"]):
        await main.file_handler(file_event(7, 20 + i, name))
        await asyncio.sleep(0.05)
    await asyncio.sleep(0.6)
    new = sent[mark:]
    check("4 files at once: one question only", len(new) == 1 and "4 FILES RECEIVED" in new[0].text
          and labels(new[0].buttons) == ["🖼️ Thumbnail on all 4", "✏️ One by one", "❌ Cancel"],
          str([(m.text[:40], labels(m.buttons)) for m in new]))
    batch_id = new[0].buttons[0][0].data.decode().split("|")[1]
    used_before = quota_used(7)

    # 3. Thumbnail on all: back one by one, in order, names kept, the thumbnail on each
    cb = Callback(7, f"bthumb|{batch_id}")
    mark = len(sent)
    await main.callback_handler(cb)
    for _ in range(50):
        await asyncio.sleep(0.1)
        if any(m.kind == "msg" and "Done" in m.text for m in sent[mark:]):
            break
    files = [m for m in sent[mark:] if m.kind == "file"]
    check("thumbnail on all: 4 files back, in order, names kept, with the thumbnail",
          [f.name for f in files] == ["Blue Box 01.pdf", "Blue Box 02.pdf", "Blue Box 03.pdf", "Blue Box 04.pdf"]
          and all(f.thumb and f.thumb.endswith("7.jpg") for f in files), str([(f.name, f.thumb) for f in files]))
    check("… progress says 1/4 … 4/4, then Done", any("(1/4)" in m.text for m in sent[mark:] if m.kind == "msg")
          and any("(4/4)" in m.text for m in sent[mark:] if m.kind == "msg")
          and any("Done:</b> 4 files" in m.text for m in sent[mark:] if m.kind == "msg"))
    check("… the button message says what happens", cb.edits and "Adding your thumbnail to 4 files" in cb.edits[-1])
    check("… counted once per file (on arrival), not again", quota_used(7) == used_before == 5,
          f"before={used_before} after={quota_used(7)}")

    # 4. One by one: the usual question for each
    mark = len(sent)
    for i in range(3):
        await main.file_handler(file_event(42, 40 + i, f"Ep{i}.pdf"))
    await asyncio.sleep(0.6)
    batch_id = sent[-1].buttons[1][0].data.decode().split("|")[1]
    await main.callback_handler(Callback(42, f"bone|{batch_id}"))
    questions = [m for m in sent[mark + 1:] if m.kind == "msg" and "FILE INFORMATION" in m.text]
    check("one by one: 3 usual questions, each under its file", [q.reply_to for q in questions] == [40, 41, 42])

    # 5. Cancel; someone else's group; an expired one
    for i in range(2):
        await main.file_handler(file_event(42, 50 + i, f"X{i}.pdf"))
    await asyncio.sleep(0.6)
    batch_id = sent[-1].buttons[2][0].data.decode().split("|")[1]
    intruder = Callback(7, f"bthumb|{batch_id}")
    await main.callback_handler(intruder)
    check("someone else's group: refused", intruder.answers and "expired" in intruder.answers[0])
    cb = Callback(42, f"bcancel|{batch_id}")
    await main.callback_handler(cb)
    check("cancel: done, files forgotten", "Cancelled" in cb.edits[-1] and (42, 50) not in main.ORIGINAL_MESSAGES)
    again = Callback(42, f"bthumb|{batch_id}")
    await main.callback_handler(again)
    check("the same group again: expired", again.answers and "expired" in again.answers[0])

    # 6. no thumbnail yet: the group question says to set one first
    os.remove(Path(main.THUMBNAIL_DIR, "42.jpg"))
    for i in range(2):
        await main.file_handler(file_event(42, 60 + i, f"Y{i}.pdf"))
    await asyncio.sleep(0.6)
    check("no thumbnail: « Set Thumbnail First (/setthumb) »", labels(sent[-1].buttons)[0].startswith("🖼️ Set Thumbnail First"))

    # 7. settings and history read at start-up, never overwritten by the first user after a restart
    check("start-up: an older user's custom text is there without any /start",
          main.sessions.get(555, {}).get("custom_text") == "@Chan")
    import json  # noqa: PLC0415
    saved = json.loads(Path("user_usage.json").read_text())
    check("… and saving another user's usage keeps it", "555" in saved and "7" in saved, str(list(saved)))

    # 8. /status: real numbers, the caller's own status
    async def status_of(uid):
        replies = []

        async def reply(text, **kw):
            replies.append(text)
        await main.status_handler(SimpleNamespace(sender_id=uid, is_private=True, reply=reply))
        return replies[-1]
    text = await status_of(7)
    print("   " + text.replace("\n", "\n   "))
    nums = {k: int(v) for k, v in __import__("re").findall(r"• (Total|Active \(7 days\)|Inactive \(7\+ days\)): (\d+)", text)}
    check("status: the users add up (active 7 days + inactive = total)",
          nums.get("Active (7 days)", -1) + nums.get("Inactive (7+ days)", -1) == nums.get("Total"), str(nums))
    check("… users who just used the bot are active", nums.get("Active (7 days)", 0) >= 2, str(nums))
    check("… the caller's own status (thumbnail, custom text, today's quota), no leftover « Captions »",
          "Thumbnail: ✅ set" in text and "Custom text: none" in text and "Today: 5 / 10 actions" in text
          and "Captions" not in text and "Aᴄᴛɪᴠᴇ Jᴏʙs" in text)
    check("… an admin: unlimited", "unlimited (admin)" in await status_of(42))
    print("\nALL OK" if ok else "\nFAILED")


asyncio.run(main_test())
