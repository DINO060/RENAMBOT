"""Offline check of the fixes (python fixes_check.py): fake Telegram, temp dir, and every message given to EVERY
handler whose filter matches it, the way Telethon does.

- /settings shows its menu once (it came twice); /cancel answers once; a command or a file is never taken as the
  custom text; a custom text with « < » doesn't break the menu; « Clean Tags » off really keeps the @names;
- a file costs one action, whatever is done with it (it was up to 4: arrival, button, reply, upload); buttons and
  photos cost nothing;
- « Rename Only » really renames: the file is sent again under its new name, with its own thumbnail (the same
  Telegram file used to come back, only the caption changed);
- a thumbnail is saved Telegram-sized (≤ 320 px, ≤ 200 KB) from any photo, and used that way;
- a queued file that fails doesn't wipe the prompt of the next file.
"""
import asyncio
import time
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
shutil.copy(SRC / "whatsnew.txt", WORK / "whatsnew.txt")
shutil.copytree(SRC / "utils", WORK / "utils", ignore=shutil.ignore_patterns("__pycache__"))
os.chdir(WORK)
sys.path.insert(0, str(WORK))
sys.stdout.reconfigure(errors="replace")
os.environ.update(API_ID="1", API_HASH="x", TOKEN="1:x", ADMIN_IDS="42", QUOTA_DB_PATH=str(WORK / "q.db"),
                  DAILY_LIMIT="10", QUOTA_TZ="UTC")

import telethon  # noqa: E402
from telethon import events  # noqa: E402
from PIL import Image  # noqa: E402

HANDLERS = []
sent = []


class Msg(SimpleNamespace):
    async def delete(self):
        self.deleted = True

    async def edit(self, text="", *a, **k):
        sent.append(SimpleNamespace(kind="edit", chat=None, text=text, buttons=None, reply_to=None))
        return self


class FakeClient:
    def __init__(self, *a, **k):
        pass

    def start(self, **k):
        return self

    def on(self, builder):
        def register(fn):
            HANDLERS.append((builder, fn))
            return fn
        return register

    async def send_message(self, chat, text="", **kw):
        sent.append(SimpleNamespace(kind="msg", chat=chat, text=text, buttons=kw.get("buttons"), reply_to=kw.get("reply_to")))
        return Msg(id=1000 + len(sent))

    async def send_file(self, chat, file, **kw):
        thumb = kw.get("thumb")
        size = Image.open(thumb).size if thumb and os.path.exists(thumb) else None
        sent.append(SimpleNamespace(kind="file", chat=chat, file=file, name=kw.get("file_name"), thumb=thumb,
                                    thumb_size=size, thumb_bytes=thumb and os.path.exists(thumb) and os.path.getsize(thumb),
                                    caption=kw.get("caption")))
        return Msg(id=1000 + len(sent))

    async def edit_message(self, *a, **k):
        pass

    async def delete_messages(self, chat, ids, **k):
        sent.append(SimpleNamespace(kind="deleted", chat=chat, ids=list(ids), text="", buttons=None, reply_to=None))

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


def quota_used(uid):
    with sqlite3.connect(WORK / "q.db") as c:
        row = c.execute("SELECT SUM(used) FROM quotas WHERE user_id = ?", (uid,)).fetchone()
    return row[0] or 0


def jpeg(path, size=(1280, 720)):
    Image.effect_noise(size, 60).convert("RGB").save(path, "JPEG", quality=95)
    return path


ids = iter(range(1, 10_000))


def message_event(uid, text="", file=None, photo=False, reply_to=None, fail_download=False):
    msg_id = next(ids)

    async def download_media(file=None, progress_callback=None, thumb=None):
        if fail_download:
            raise RuntimeError("download failed")
        if thumb is not None:                       # the file's own thumbnail
            return jpeg(file, (320, 180))
        if photo:
            path = file if str(file).endswith(".jpg") else str(file) + ".jpg"
            return jpeg(path)
        Path(file).write_bytes(b"content of " + (fobj.name or "").encode())
        return file

    async def reply(text, **kw):
        return await main.bot.send_message(uid, text, **kw)

    async def edit(text, **kw):
        return await main.bot.send_message(uid, text, **kw)

    fobj = SimpleNamespace(name=file, size=5000 + msg_id, mime_type="application/pdf") if file else None
    if photo:
        fobj = SimpleNamespace(name=None, size=900_000, mime_type="image/jpeg")
    message = SimpleNamespace(id=msg_id, message=text, media=f"MEDIA-{msg_id}" if fobj else None, file=fobj,
                              video=None, sender_id=uid, reply_to_msg_id=reply_to, download_media=download_media)
    return SimpleNamespace(sender_id=uid, chat_id=uid, is_private=True, raw_text=text, text=text, message=message,
                           is_reply=bool(reply_to), reply_to_msg_id=reply_to, photo=photo or None,
                           file=fobj, reply=reply, edit=edit, download_media=download_media)


class Callback:
    def __init__(self, uid, data):
        self.data, self.query, self.chat_id = data.encode(), SimpleNamespace(user_id=uid), uid
        self.answers = []

    async def edit(self, text, **kw):
        sent.append(SimpleNamespace(kind="edit", chat=self.chat_id, text=text, buttons=kw.get("buttons"), reply_to=None))

    async def answer(self, text=None, **kw):
        self.answers.append(text)

    async def delete(self):
        pass


async def dispatch(event):
    """Every handler whose filter matches, like Telethon."""
    for builder, fn in HANDLERS:
        if isinstance(event, Callback):
            if builder is events.CallbackQuery or (isinstance(builder, events.CallbackQuery)
                                                   and builder.match in (None, event.data)):
                await fn(event)
            continue
        if not isinstance(builder, events.NewMessage):
            continue
        if builder.pattern and not builder.pattern(event.raw_text or ""):
            continue
        if builder.func and not builder.func(event):
            continue
        await fn(event)


def since(mark, kind=None):
    return [s for s in sent[mark:] if kind is None or s.kind == kind]


async def file_with_question(uid, name, **kw):
    """A file arrives; returns (its event, the question's buttons)."""
    ev = message_event(uid, file=name, **kw)
    mark = len(sent)
    await dispatch(ev)
    await asyncio.sleep(0.8)                     # the grouping window
    question = [s for s in since(mark) if s.buttons][-1]
    return ev, {b.text: b.data.decode() for row in question.buttons for b in row}


async def answer_name(uid, button_data, new_name):
    mark = len(sent)
    await dispatch(Callback(uid, button_data))
    prompt = [s for s in since(mark, "msg") if s.reply_to][-1]
    prompt_id = 1000 + sent.index(prompt) + 1
    await dispatch(message_event(uid, new_name, reply_to=prompt_id))
    for _ in range(60):                           # the per-user queue
        await asyncio.sleep(0.05)
        if not main.THUMB_WORKERS.get(uid):
            break
    return [s for s in since(mark, "file")]


async def main_test():
    Path(main.THUMBNAIL_DIR).mkdir(exist_ok=True)
    Path(main.TEMP_DIR).mkdir(exist_ok=True)

    # 1. /settings, /cancel, custom text
    mark = len(sent)
    await dispatch(message_event(7, "/settings"))
    menus = [s for s in since(mark) if "Bot Settings" in s.text]
    check("/settings: the menu once (it came twice)", len(menus) == 1, str(len(menus)))

    await dispatch(Callback(7, "add_custom_text"))
    mark = len(sent)
    await dispatch(message_event(7, "/cancel"))
    replies = since(mark)
    check("/cancel while typing a custom text: one answer, nothing saved",
          len([s for s in replies if "cancel" in s.text.lower()]) == 1 and not main.sessions[7].get('custom_text')
          and not main.sessions[7].get('awaiting_custom_text'), str([s.text[:40] for s in replies]))

    await dispatch(Callback(7, "add_custom_text"))
    await dispatch(message_event(7, "/start"))
    check("… another command: not taken as the custom text", not main.sessions[7].get('custom_text')
          and not main.sessions[7].get('awaiting_custom_text'))

    await dispatch(Callback(7, "add_custom_text"))
    await dispatch(message_event(7, file="some.pdf"))
    check("… a file: not taken as the custom text (it still waits for one)",
          not main.sessions[7].get('custom_text') and main.sessions[7].get('awaiting_custom_text'))
    await asyncio.sleep(0.8)                      # (the file's own question)
    mark = len(sent)
    await dispatch(message_event(7, "[My <Group>]"))
    menu = [s for s in since(mark) if "Bot Settings" in s.text]
    check("… a text: saved, and a « < » in it doesn't break the menu (escaped)",
          main.sessions[7]['custom_text'] == "[My <Group>]" and menu and "&lt;Group&gt;" in menu[-1].text,
          menu and menu[-1].text)

    # 2. quota: one action per file
    Path(main.THUMBNAIL_DIR, "7.jpg").unlink(missing_ok=True)
    jpeg(Path(main.THUMBNAIL_DIR, "7.jpg"))       # an old 1280 px thumbnail, saved before this update
    main.sessions[7]['custom_text'] = ''
    before = quota_used(7)
    ev, buttons = await file_with_question(7, "Blue Box 05.pdf")
    files = await answer_name(7, buttons["🖼️ Add Thumbnail"], "Blue Box - 05")
    check("a file with « Add Thumbnail »: 1 action (it was 4: arrival, button, reply, upload)",
          quota_used(7) - before == 1, str(quota_used(7) - before))
    f = files[-1] if files else None
    check("… sent with the extension and the thumbnail made Telegram-sized (an old 1280 px one too)",
          f and f.name == "Blue Box - 05.pdf" and f.thumb_size and max(f.thumb_size) <= 320
          and f.thumb_bytes <= 200 * 1024, f and (f.name, f.thumb_size, f.thumb_bytes))

    before = quota_used(7)
    await dispatch(Callback(7, "check_joined"))
    await dispatch(Callback(7, "change_text_position"))
    check("buttons cost nothing (« I have joined », settings)", quota_used(7) == before)

    # 3. Rename Only
    ev, buttons = await file_with_question(7, "old name.pdf")
    files = await answer_name(7, buttons["✏️ Rename Only"], "Episode 02")
    f = files[-1] if files else None
    check("« Rename Only »: the file itself sent again under the new name (not the same Telegram file)",
          f and f.name == "Episode 02.pdf" and isinstance(f.file, str) and Path(f.file).name != f"MEDIA-{ev.message.id}",
          f and (f.name, f.file))
    check("… with the file's own thumbnail, not the user's", f and f.thumb_size == (320, 180), f and f.thumb_size)
    check("… and one action for it", quota_used(7) - before == 1, str(quota_used(7) - before))

    # 4. Clean Tags off keeps the @names
    main.sessions[7].update(clean_tags=False, custom_text="@MyChan", text_position="end")
    ev, buttons = await file_with_question(7, "x.pdf")
    files = await answer_name(7, buttons["✏️ Rename Only"], "Show @Other #tag")
    f = files[-1] if files else None
    check("« Clean Tags » off: the @names and #tags stay, the custom text added once",
          f and f.name == "Show @Other #tag @MyChan.pdf", f and f.name)
    main.sessions[7].update(clean_tags=True, custom_text="")

    # 5. photos and thumbnails
    before = quota_used(8)
    mark = len(sent)
    await dispatch(message_event(8, photo=True))
    check("a photo without /setthumb: a hint, no action counted",
          quota_used(8) == before and any("/setthumb" in s.text for s in since(mark)))
    await dispatch(message_event(8, "/setthumb"))
    await dispatch(message_event(8, photo=True))
    saved = Path(main.THUMBNAIL_DIR, "8.jpg")
    size = Image.open(saved).size if saved.exists() else None
    check("/setthumb then a big photo (900 KB, 1280 px): saved at ≤ 320 px and ≤ 200 KB, nothing counted",
          size and max(size) <= 320 and saved.stat().st_size <= 200 * 1024 and quota_used(8) == before, str(size))

    # 6. a queued file that fails doesn't wipe the next prompt
    ev1, b1 = await file_with_question(9, "first.pdf", fail_download=True)
    ev2, b2 = await file_with_question(9, "second.pdf")
    mark = len(sent)
    await dispatch(Callback(9, b1["✏️ Rename Only"]))
    prompt1 = 1000 + sent.index([s for s in since(mark, "msg") if s.reply_to][-1]) + 1
    await dispatch(message_event(9, "First", reply_to=prompt1))
    await dispatch(Callback(9, b2["✏️ Rename Only"]))   # the second prompt, while the first one is processed
    for _ in range(60):
        await asyncio.sleep(0.05)
        if not main.THUMB_WORKERS.get(9):
            break
    check("a queued file that fails: its error shown, the next file's prompt still waiting",
          any("download failed" in s.text for s in since(mark) if s.kind in ("msg", "edit"))
          and main.user_sessions.get(9, {}).get('action') == 'rename_stateless', str(main.user_sessions.get(9)))

    # 7. a file sent as a reply to a prompt is a new file, not a name
    ev, buttons = await file_with_question(10, "a.pdf")
    mark = len(sent)
    await dispatch(Callback(10, buttons["✏️ Rename Only"]))
    prompt = 1000 + sent.index([s for s in since(mark, "msg") if s.reply_to][-1]) + 1
    await dispatch(message_event(10, "caption", file="other.pdf", reply_to=prompt))
    await asyncio.sleep(0.8)
    check("a file sent in reply to the prompt: a new file (its question), not a rename",
          main.user_sessions.get(10, {}).get('action') == 'rename_stateless' and not since(mark, "file"))

    # 8. the update message, the guide, the colours
    real_sleep = asyncio.sleep
    waits = []

    async def quick_sleep(s, *a, **k):
        waits.append(s)
        await real_sleep(0)
    main.asyncio.sleep = quick_sleep
    mark = len(sent)
    await main.announce_update()
    news = [s for s in since(mark) if "has been updated" in s.text]
    users = await main.all_user_ids()
    check("a new version: every user told once, with what's new and the guide (EN + FR)",
          len(news) == len(users) >= 3 and {s.chat for s in news} == users and "Rename Only" in news[0].text
          and main.GUIDE_EN in news[0].text and main.GUIDE_FR in news[0].text, f"{len(news)} / {users}")
    note = [s for s in since(mark) if s.chat == 42 and "restarted" in s.text]
    check("… the admin told of the restart, with the count",
          note and f"{len(users)} sent" in note[-1].text, note and note[-1].text)
    mark = len(sent)
    await main.announce_update()
    check("… restarted again with no new version: users told nothing, the admin still told",
          not [s for s in since(mark) if "has been updated" in s.text]
          and any(s.chat == 42 and "No new version" in s.text for s in since(mark)))
    pending = main._pending_updates()
    check("the update notice: each one due for deletion in 6 h (kept on disk, a restart doesn't lose it)",
          sorted(r[0] for r in pending) == sorted(users) and all(5.9 * 3600 < r[2] - time.time() <= 6 * 3600 for r in pending)
          and "disappears in 6 h" in news[0].text, str(pending))
    check("… not deleted before its time", await main.delete_due_updates() == 0)
    main._save_pending_updates([[c, m, time.time() - 1] for c, m, _ in pending])      # 6 h later
    mark = len(sent)
    n = await main.delete_due_updates()
    gone = sorted(s.chat for s in since(mark) if s.kind == "deleted")
    check("… after 6 h: deleted for every user, nothing left to do", n == len(users) and gone == sorted(users)
          and main._pending_updates() == [], f"{n} {gone}")

    from telethon.errors import FloodWaitError  # noqa: PLC0415
    tries = {"n": 0}
    real_send = main.bot.send_message

    async def flood_once(chat, text="", **kw):
        tries["n"] += 1
        if tries["n"] == 1:
            raise FloodWaitError(None, capture=7)
        return await real_send(chat, text, **kw)
    main.bot.send_message = flood_once
    waits.clear()
    counts = await main.send_to_all([7], "hello")
    main.bot.send_message = real_send
    main.asyncio.sleep = real_sleep
    check("a flood wait while sending to everyone: waited for, then sent (it counted the user as failed)",
          counts["sent"] == 1 and 8 in waits, f"{counts} {waits}")

    mark = len(sent)
    await dispatch(message_event(7, "/help"))
    helps = [s for s in since(mark) if isinstance(getattr(s, "buttons", None), list)]
    urls = [getattr(b, "url", "") for s in helps for row in s.buttons for b in row]
    check("/help: the guide in English and French", main.GUIDE_EN in urls and main.GUIDE_FR in urls, str(urls))
    mark = len(sent)
    await dispatch(message_event(7, "/start"))
    starts = [s for s in since(mark) if isinstance(getattr(s, "buttons", None), list)]
    check("/start: a « 📖 Guide » button", starts and any(getattr(b, "url", "") == main.GUIDE_EN
                                                      for row in starts[-1].buttons for b in row))
    ev, buttons = await file_with_question(7, "colours.pdf")
    question = [s for s in sent if isinstance(getattr(s, "buttons", None), list) and any(getattr(b, "text", "") == "🖼️ Add Thumbnail" for row in s.buttons for b in row)][-1]
    styles = {b.text: b.style.to_dict() if getattr(b, "style", None) else None for row in question.buttons for b in row}
    check("coloured buttons: Add Thumbnail green, Rename Only blue, Cancel red",
          styles["🖼️ Add Thumbnail"]["bg_success"] and styles["✏️ Rename Only"]["bg_primary"]
          and styles["❌ Cancel"]["bg_danger"], str(styles))

    # 9. force join (last: from here on, channels are required)
    import json  # noqa: PLC0415
    from telethon.errors import ChatAdminRequiredError, UserNotParticipantError  # noqa: PLC0415
    from telethon.tl.functions.channels import GetParticipantRequest  # noqa: PLC0415
    from telethon.tl.types import InputUserSelf  # noqa: PLC0415
    fj = {"members": set(), "not_admin": set(), "asked": 0}

    async def telegram(self, req, *a, **k):
        if isinstance(req, GetParticipantRequest):
            fj["asked"] += 1
            if req.channel in fj["not_admin"]:
                raise ChatAdminRequiredError(None)
            if isinstance(req.participant, InputUserSelf) or (req.channel, req.participant) in fj["members"]:
                return SimpleNamespace(participant=None)
            raise UserNotParticipantError(None)
        return None
    FakeClient.__call__ = telegram
    channels = ["@chanA", "-100123", {"id": -100777, "title": "Private club", "invite": "https://t.me/+abc"}]
    main.FJ_PATH.write_text(json.dumps({"channels": channels}))
    main._joined_until.clear()
    refs = [e[0] for e in main.forced_channel_entries()]
    check("channels: @name, a -100 id (as a number, else nobody could pass), a private one with its invite",
          refs == ["chanA", -100123, -100777], str(refs))

    before = quota_used(50)
    mark = len(sent)
    await dispatch(message_event(50, file="x.pdf"))
    denied = [s for s in since(mark) if "Access Denied" in s.text]
    urls = [getattr(b, "url", None) for row in (denied[-1].buttons if denied else []) for b in row]
    check("not a member: refused, Join buttons for @chanA and the private invite, the file costs nothing",
          denied and "https://t.me/chanA" in urls and "https://t.me/+abc" in urls and quota_used(50) == before,
          f"{urls} {quota_used(50) - before}")

    fj["members"] |= {("chanA", 50), (-100123, 50), (-100777, 50)}
    mark = len(sent)
    await dispatch(Callback(50, "check_joined"))
    check("« I have joined » after joining: a real welcome (it sent the text « /start »)",
          any("You're in" in s.text for s in since(mark)) and not any(s.text == "/start" for s in since(mark)))
    asked = fj["asked"]
    await dispatch(message_event(50, file="y.pdf"))
    await dispatch(message_event(50, file="z.pdf"))
    check("a member: remembered, Telegram not asked again for each file", fj["asked"] == asked)
    await asyncio.sleep(0.8)

    fj["not_admin"].add(-100123)
    fj["members"] |= {(ch, u) for ch in ("chanA", -100777) for u in (51, 52)}   # members of the checkable ones
    main._joined_until.clear()
    mark = len(sent)
    await dispatch(message_event(51, "/settings"))
    await dispatch(message_event(52, "/settings"))
    alerts = [s for s in since(mark) if s.chat == 42 and "can't check" in s.text]
    check("bot not admin of a channel: users not locked out (they ALL were), the admin alerted once",
          len(alerts) == 1 and not [s for s in since(mark) if "Access Denied" in s.text]
          and len([s for s in since(mark) if "Bot Settings" in s.text]) == 2, str([s.text[:50] for s in since(mark)]))
    mark = len(sent)
    await dispatch(message_event(42, "/channels"))
    report = [s.text for s in since(mark) if "Forced-sub" in s.text]
    check("/channels: which ones are really checked", report and "@chanA — ✅" in report[-1]
          and "-100123 — ❌ NOT checked" in report[-1], report and report[-1])
    check("the channel list on disk is left as written (a private channel's details kept)",
          json.loads(main.FJ_PATH.read_text())["channels"] == channels)
    await dispatch(message_event(42, "/addfsub -100555 t.me/chanB"))
    check("/addfsub with a -100 id and a t.me link", [e[0] for e in main.forced_channel_entries()][-2:] == [-100555, "chanB"],
          str(main.forced_channel_entries()))


asyncio.run(main_test())
print("\nALL OK" if ok else "\nFAILED")
