"""Builds the pictures of the Telegraph guide (python guide/build_guide.py): Telegram-like screens with the bot's
real messages and buttons, animated GIFs of each flow, and a short explainer video in English and French.
Needs Playwright (Chromium), Pillow and ffmpeg. Everything lands in guide/img/."""
import html
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "img"
WORK = Path(tempfile.mkdtemp())
BOT = "RƐNAM BOT"
FONT_BOLD = "C:/Windows/Fonts/segoeuib.ttf"

# ---------------------------------------------------------------------------------------------- demo pictures
def poster(path, size, title, sub):
    """A made-up episode cover (no real artwork): gradient, title, episode."""
    w, h = size
    img = Image.new("RGB", size)
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(20 + 60 * t), int(60 + 40 * (1 - t)), int(140 + 80 * (1 - t))))
    for i in range(6):                                  # soft circles
        r = int(w * (0.12 + 0.05 * i))
        layer = Image.new("RGBA", size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([w * 0.62 - r, h * 0.35 - r, w * 0.62 + r, h * 0.35 + r],
                                      outline=(255, 255, 255, 40 - 5 * i), width=max(2, w // 160))
        img.paste(layer, (0, 0), layer)
    big = ImageFont.truetype(FONT_BOLD, int(h * 0.34))
    small = ImageFont.truetype(FONT_BOLD, int(h * 0.1))
    for text, font, y, colour in ((title, small, 0.2, (255, 255, 255)), (sub, big, 0.36, (255, 214, 102))):
        width = d.textlength(text, font=font)       # centred: Telegram shows a square crop of the middle
        d.text(((w - width) / 2, int(h * y)), text, font=font, fill=colour)
    img.filter(ImageFilter.SMOOTH).save(path, quality=92)
    return path


# ---------------------------------------------------------------------------------------------- chat screens
CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: transparent; font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; }
.phone { width: 420px; background: #0e1621; border-radius: 22px; overflow: hidden; border: 1px solid #22303f; }
.top { display: flex; align-items: center; gap: 12px; padding: 12px 16px; background: #17212b; }
.ava { width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg, #5fb3ff, #7d5fff);
       color: #fff; font: 700 19px 'Segoe UI'; display: flex; align-items: center; justify-content: center; }
.name { color: #f5f5f5; font: 600 16px 'Segoe UI'; } .sub { color: #708499; font-size: 13px; }
.chat { padding: 14px 10px 10px; display: flex; flex-direction: column; gap: 6px; min-height: 120px; }
.row { display: flex; flex-direction: column; } .row.out { align-items: flex-end; } .row.in { align-items: flex-start; }
.b { max-width: 330px; padding: 8px 11px 6px; border-radius: 14px; color: #f5f5f5; font-size: 14.5px; line-height: 1.38;
     white-space: pre-wrap; word-wrap: break-word; }
.in .b { background: #182533; border-bottom-left-radius: 5px; } .out .b { background: #2b5278; border-bottom-right-radius: 5px; }
.t { float: right; font-size: 11px; color: #6d7f8f; margin: 6px 0 0 10px; } .out .t { color: #7da8d3; }
b, strong { font-weight: 700; } code { font-family: Consolas, monospace; color: #9cd3ff; font-size: 13.5px; }
a { color: #6ab3f3; text-decoration: none; }
.kb { width: 330px; display: flex; flex-direction: column; gap: 4px; margin-top: 4px; }
.kr { display: flex; gap: 4px; }
.k { flex: 1; text-align: center; padding: 9px 6px; border-radius: 9px; color: #fff; font: 600 13.5px 'Segoe UI';
     background: rgba(48, 70, 92, .85); }
.k.success { background: #2e9c4f; } .k.primary { background: #2f6fd8; } .k.danger { background: #d0453f; }
.k.url::after { content: ' ↗'; font-size: 11px; opacity: .8; }
.q { border-left: 3px solid #6ab3f3; padding: 1px 0 1px 8px; margin-bottom: 5px; border-radius: 2px; }
.q .qn { color: #6ab3f3; font-weight: 600; font-size: 13px; } .q .qt { color: #aab8c5; font-size: 13px; }
.file { display: flex; gap: 11px; align-items: center; min-width: 250px; }
.ico { width: 46px; height: 46px; border-radius: 50%; background: #4a90d9; display: flex; align-items: center;
       justify-content: center; font-size: 22px; flex: none; }
.thumb { width: 54px; height: 54px; border-radius: 8px; object-fit: cover; flex: none; }
.fn { color: #f5f5f5; font-weight: 600; font-size: 14px; word-break: break-all; } .fs { color: #7f95a8; font-size: 12.5px; }
.out .fs { color: #9cc1e6; }
.ph { width: 260px; border-radius: 12px; display: block; }
.bar { height: 8px; background: #22303f; border-radius: 4px; overflow: hidden; margin: 6px 0 4px; width: 250px; }
.bar i { display: block; height: 100%; background: linear-gradient(90deg, #4a90d9, #6ab3f3); }
.input { margin: 6px 10px 12px; padding: 10px 14px; background: #17212b; border-radius: 18px; color: #6d7f8f;
         font-size: 14px; }
"""


def esc(s):
    return html.escape(s, quote=False)


def uri(path):
    """An image inside the page itself (a page made with set_content can't load local files)."""
    import base64
    data = Path(path).read_bytes()
    kind = "png" if str(path).endswith(".png") else "jpeg"
    return f"data:image/{kind};base64," + base64.b64encode(data).decode()


def bubble(m):
    side = m.get("side", "in")
    inner = ""
    if m.get("reply"):
        inner += f'<div class="q"><div class="qn">{esc(m["reply"][0])}</div><div class="qt">{esc(m["reply"][1])}</div></div>'
    if m.get("photo"):
        inner += f'<img class="ph" src="{uri(m["photo"])}">'
    if m.get("file"):
        f = m["file"]
        icon = (f'<img class="thumb" src="{uri(f["thumb"])}">' if f.get("thumb")
                else f'<div class="ico">{"🎬" if f.get("video") else "📄"}</div>')
        inner += f'<div class="file">{icon}<div><div class="fn">{esc(f["name"])}</div><div class="fs">{esc(f["size"])}</div></div></div>'
    if m.get("progress") is not None:
        inner += f'{m["html"]}<div class="bar"><i style="width:{m["progress"]}%"></i></div>'
    elif m.get("html"):
        inner += ("<div style='margin-top:6px'>" if m.get("file") or m.get("photo") else "<div>") + m["html"] + "</div>"
    inner += f'<span class="t">{m.get("time", "14:02")}</span>'
    out = f'<div class="row {side}"><div class="b">{inner}</div>'
    if m.get("buttons"):
        out += '<div class="kb">' + "".join(
            '<div class="kr">' + "".join(f'<div class="k {style or ""}">{esc(text)}</div>' for text, style in row) + "</div>"
            for row in m["buttons"]) + "</div>"
    return out + "</div>"


def chat(messages):
    return (f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body><div class='phone'>"
            f"<div class='top'><div class='ava'>R</div><div><div class='name'>{BOT}</div><div class='sub'>bot</div></div></div>"
            f"<div class='chat'>{''.join(bubble(m) for m in messages)}</div><div class='input'>Message</div></div></body></html>")


SLIDE_CSS = """
* { margin: 0; padding: 0; box-sizing: border-box; }
body { width: 1280px; height: 720px; font-family: 'Segoe UI', 'Segoe UI Emoji', sans-serif; overflow: hidden;
       background: radial-gradient(circle at 20% 20%, #1e3a5f 0%, #0b1320 60%); color: #fff; display: flex;
       align-items: center; padding: 0 70px; gap: 60px; }
.txt { flex: 1; } .step { color: #6ab3f3; font: 700 22px 'Segoe UI'; letter-spacing: 1px; margin-bottom: 14px; }
h1 { font: 800 50px 'Segoe UI'; line-height: 1.1; margin-bottom: 20px; } p { font-size: 25px; color: #c6d4e1; line-height: 1.45; }
.shot { height: 640px; display: flex; align-items: center; } .shot img { max-height: 640px; max-width: 520px; border-radius: 22px;
       box-shadow: 0 20px 60px rgba(0,0,0,.5); }
.center { flex-direction: column; justify-content: center; text-align: center; padding: 0 140px; gap: 0; }
.center h1 { font-size: 64px; } .center p { font-size: 28px; }
.logo { width: 120px; height: 120px; border-radius: 50%; margin: 0 auto 30px; background: linear-gradient(135deg, #5fb3ff, #7d5fff);
        display: flex; align-items: center; justify-content: center; font: 800 58px 'Segoe UI'; }
"""


def slide(step, title, text, shot=None):
    body = (f"<div class='txt'><div class='step'>{esc(step)}</div><h1>{esc(title)}</h1><p>{esc(text)}</p></div>"
            + (f"<div class='shot'><img src='{uri(shot)}'></div>" if shot else ""))
    return f"<html><head><meta charset='utf-8'><style>{SLIDE_CSS}</style></head><body>{body}</body></html>"


def title_slide(title, text, cta=""):
    return (f"<html><head><meta charset='utf-8'><style>{SLIDE_CSS}</style></head><body class='center'>"
            f"<div class='logo'>R</div><h1>{esc(title)}</h1><p>{esc(text)}</p>"
            + (f"<p style='margin-top:26px;color:#6ab3f3;font-weight:700'>{esc(cta)}</p>" if cta else "") + "</body></html>")


# ---------------------------------------------------------------------------------------------- the content
def screens(thumb, cover):
    T = "14:02"
    file_mkv = {"name": "[SubsPlease] Blue Horizon - 05 (1080p) @OldTeam.mkv", "size": "1.2 GB", "video": True}
    info = ("📁 <b>FILE INFORMATION</b>\n\n◆ <b>Name:</b> <code>[SubsPlease] Blue Horizon - 05 (1080p) @OldTeam.mkv</code>\n"
            "◆ <b>Size:</b> 1.20 GB\n◆ <b>Type:</b> video/x-matroska 🎬\n\n❓ <b>What do you want to do?</b>")
    ask = [[("🖼️ Add Thumbnail", "success")], [("✏️ Rename Only", "primary")], [("❌ Cancel", "danger")]]
    media_info = ("ᴍᴇᴅɪᴀ ɪɴꜰᴏ\n\n◈ ꜰɪʟᴇ ɴᴀᴍᴇ: [SubsPlease] Blue Horizon - 05 (1080p) @OldTeam.mkv\n\n◈ ᴇxᴛᴇɴꜱɪᴏɴ: MKV\n"
                  "◈ ꜰɪʟᴇ ꜱɪᴢᴇ: 1.20 ɢʙ\n\nᴘʟᴇᴀsᴇ ᴇɴᴛᴇʀ ᴛʜᴇ ɴᴇᴡ ғɪʟᴇɴᴀᴍᴇ ᴡɪᴛʜ ᴇxᴛᴇɴsɪᴏɴ ᴀɴᴅ ʀᴇᴘʟʏ ᴛʜɪs ᴍᴇssᴀɢᴇ..")
    done_file = {"name": "Blue Horizon - 05 @MyChannel.mkv", "size": "1.2 GB", "thumb": thumb}
    four = [f"Blue Horizon - 0{i}.mkv" for i in range(1, 5)]
    return {
        "start": [
            {"side": "out", "html": "/start", "time": T},
            {"html": "👋 <b>Welcome to RƐNAM BOT!</b>\n\nSend me any file and I'll help you rename it.\n\n"
                     "<b>📋 Features:</b>\n• Support all file types (up to 2 GB)\n• Custom text/username addition\n"
                     "• Fast thumbnail processing ⚡\n• Send many files at once: one tap puts your thumbnail on all of them 📦\n"
                     "• Auto-cleanup of @tags and #hashtags\n• Video streaming support 🎬\n\n<b>📤 Just send me a file to get started!</b>",
             "buttons": [[("⚙️ Settings", "primary"), ("📖 Guide", None)]], "time": T},
        ],
        "file_question": [
            {"side": "out", "file": file_mkv, "time": T},
            {"html": info, "buttons": ask, "time": T, "reply": ("You", file_mkv["name"])},
        ],
        "rename_prompt": [
            {"html": media_info, "time": "14:03", "reply": ("You", file_mkv["name"])},
            {"side": "out", "html": "Blue Horizon - 05", "reply": (BOT, "ᴍᴇᴅɪᴀ ɪɴꜰᴏ"), "time": "14:03"},
        ],
        "progress": [
            {"side": "out", "html": "Blue Horizon - 05", "reply": (BOT, "ᴍᴇᴅɪᴀ ɪɴꜰᴏ"), "time": "14:03"},
            {"html": "📤 <b>Uploading...</b>\n<code>Blue Horizon - 05 @MyChannel.mkv</code>", "progress": 64, "time": "14:04"},
        ],
        "result": [
            {"side": "out", "html": "Blue Horizon - 05", "reply": (BOT, "ᴍᴇᴅɪᴀ ɪɴꜰᴏ"), "time": "14:03"},
            {"file": done_file, "html": "<code>Blue Horizon - 05 @MyChannel.mkv</code>", "time": "14:05"},
        ],
        "batch_question": [
            *[{"side": "out", "file": {"name": n, "size": "350 MB", "video": True}, "time": "15:10"} for n in four],
            {"html": "📦 <b>4 FILES RECEIVED</b>\n\n◆ <b>Total size:</b> 1.37 GB\n◆ <b>Videos:</b> 4 🎬\n\n❓ <b>What do you want to do?</b>\n"
                     "🖼️ <b>Thumbnail on all</b>: your thumbnail goes on every file, names kept, sent back in order.\n"
                     "✏️ <b>One by one</b>: I ask you for each file, as usual.",
             "buttons": [[("🖼️ Thumbnail on all 4", "success")], [("✏️ One by one", "primary")], [("❌ Cancel", "danger")]],
             "time": "15:10"},
        ],
        "batch_progress": [
            {"file": {"name": four[0].replace(".mkv", " @MyChannel.mkv"), "size": "350 MB", "thumb": thumb}, "time": "15:11"},
            {"html": "Processing with thumbnail... (2/4)\n📥 <b>Downloading...</b>", "progress": 38, "time": "15:11"},
        ],
        "batch_done": [
            *[{"file": {"name": n.replace(".mkv", " @MyChannel.mkv"), "size": "350 MB", "thumb": thumb}, "time": "15:12"}
              for n in four],
            {"html": "✅ <b>Done:</b> 4 files with your thumbnail.", "time": "15:13"},
        ],
        "setthumb": [
            {"side": "out", "html": "/setthumb", "time": "16:20"},
            {"html": "🖼️ <b>Send me a photo to set as thumbnail</b>\n\nRequirements:\n- Must be a photo (not document)\n"
                     "- Any size: it is resized the way Telegram wants thumbnails (320 px)\n\nSend /cancel to abort.", "time": "16:20"},
        ],
        "thumb_saved": [
            {"side": "out", "photo": cover, "time": "16:21"},
            {"html": "✅ <b>Thumbnail saved successfully!</b>\n\nThis thumbnail will be used for all your renamed files.\n"
                     "Use /delthumb to remove it.", "time": "16:21"},
        ],
        "settings": [
            {"side": "out", "html": "/settings", "time": "17:00"},
            {"html": "⚙️ <b>Bot Settings</b>\n\n📝 Custom text: <code>@MyChannel</code>\n📍 Position: end\n"
                     "🧹 Auto-clean tags: Yes\n\nChoose an option:",
             "buttons": [[("➕ Add/Edit Custom Text", "success")], [("📍 Change Position", "primary")],
                         [("🗑️ Remove Custom Text", "danger")], [("🧹 Toggle Clean Tags", "primary")], [("❌ Close", None)]],
             "time": "17:00"},
        ],
        "usage": [
            {"side": "out", "html": "/usage", "time": "18:00"},
            {"html": "📊 <b>Your Usage Statistics</b>\n\n<b>Used Today:</b> 3 of your daily actions\n"
                     "<b>Next Reset:</b> Tomorrow at 00:00\n\n<i>Keep track of your usage!</i>", "time": "18:00"},
        ],
    }


NAMES_CARD = """<html><head><meta charset='utf-8'><style>
body { margin: 0; font-family: 'Segoe UI', 'Segoe UI Emoji'; background: transparent; }
.c { width: 640px; background: #0e1621; border: 1px solid #22303f; border-radius: 20px; padding: 26px 28px; color: #f5f5f5; }
h3 { font-size: 19px; margin-bottom: 16px; } .l { color: #7f95a8; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; }
.n { font: 15px Consolas, monospace; background: #17212b; border-radius: 10px; padding: 10px 12px; margin: 6px 0 14px; color: #9cd3ff; }
.x { color: #ff7b72; text-decoration: line-through; } .a { color: #7ee787; } .ar { text-align: center; font-size: 22px; margin: -6px 0 6px; }
.s { color: #aab8c5; font-size: 13.5px; line-height: 1.5; }
</style></head><body><div class='c'><h3>✨ What the settings do to a name</h3>
<div class='l'>You type</div><div class='n'>[SubsPlease] Blue Horizon - 05 (1080p) <span class='x'>@OldTeam #anime</span></div>
<div class='ar'>⬇️</div>
<div class='l'>You get (Clean Tags on, custom text « @MyChannel » at the end)</div>
<div class='n'>[SubsPlease] Blue Horizon - 05 (1080p) <span class='a'>@MyChannel</span>.mkv</div>
<div class='s'>🧹 <b>Clean Tags</b> removes the other @names and #hashtags · 📝 <b>Custom text</b> adds yours, at the start or
at the end · the extension (.mkv) is kept for you.</div></div></body></html>"""

FLOWS = {"rename": ["file_question", "rename_prompt", "progress", "result"],
         "batch": ["batch_question", "batch_progress", "batch_done"],
         "thumbnail": ["setthumb", "thumb_saved"]}

VIDEO = {
    "en": [("title", "RƐNAM BOT", "Rename any file up to 2 GB, put your own thumbnail on it — one file or a whole batch.",
            "Open the bot and send a file"),
           ("file_question", "STEP 1", "Send a file", "Any file, up to 2 GB. The bot shows what it is and asks what to do."),
           ("rename_prompt", "STEP 2", "Type the new name", "Reply to the bot's message with the name. No extension? It keeps the file's."),
           ("result", "STEP 3", "Get it back, renamed", "With your thumbnail and your custom text. Videos stay playable."),
           ("batch_question", "MANY FILES", "A whole season at once", "Send several files together: one tap puts your thumbnail on all of them."),
           ("batch_done", "MANY FILES", "Back in order", "Every file comes back with your thumbnail, in the order you sent them."),
           ("thumb_saved", "THUMBNAIL", "Your own thumbnail", "/setthumb, then any photo. It is resized the way Telegram wants it."),
           ("settings", "SETTINGS", "Your channel's name on every file", "Add a custom text, choose start or end, clean the old @tags."),
           ("title", "RƐNAM BOT", "Faster uploads, clean names, your brand on every file.", "Send /start to begin")],
    "fr": [("title", "RƐNAM BOT", "Renomme n'importe quel fichier jusqu'à 2 Go et mets-y ta miniature — un fichier ou toute une série.",
            "Ouvre le bot et envoie un fichier"),
           ("file_question", "ÉTAPE 1", "Envoie un fichier", "N'importe quel fichier, jusqu'à 2 Go. Le bot te le décrit et te demande quoi faire."),
           ("rename_prompt", "ÉTAPE 2", "Tape le nouveau nom", "Réponds au message du bot avec le nom. Sans extension ? Il garde celle du fichier."),
           ("result", "ÉTAPE 3", "Récupère-le, renommé", "Avec ta miniature et ton texte perso. Les vidéos restent lisibles."),
           ("batch_question", "PLUSIEURS FICHIERS", "Toute une saison d'un coup", "Envoie plusieurs fichiers ensemble : un seul bouton met ta miniature sur tous."),
           ("batch_done", "PLUSIEURS FICHIERS", "Dans l'ordre", "Chaque fichier revient avec ta miniature, dans l'ordre où tu les as envoyés."),
           ("thumb_saved", "MINIATURE", "Ta propre miniature", "/setthumb, puis n'importe quelle photo. Elle est redimensionnée comme Telegram le veut."),
           ("settings", "RÉGLAGES", "Le nom de ta chaîne sur chaque fichier", "Ajoute un texte perso, au début ou à la fin, et nettoie les anciens @tags."),
           ("title", "RƐNAM BOT", "Des envois plus rapides, des noms propres, ta marque sur chaque fichier.", "Envoie /start pour commencer")],
}


def ffmpeg(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def main():
    OUT.mkdir(exist_ok=True)
    thumb = poster(WORK / "thumb.jpg", (320, 180), "BLUE HORIZON", "EP 05")
    cover = poster(WORK / "cover.jpg", (640, 360), "BLUE HORIZON", "EP 05")
    shots = {}
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=2, viewport={"width": 700, "height": 900})
        for name, messages in screens(str(thumb), str(cover)).items():
            page.set_content(chat(messages))
            page.wait_for_timeout(150)
            path = OUT / f"{name}.png"
            page.locator(".phone").screenshot(path=str(path), omit_background=True)
            shots[name] = path
        page.set_content(NAMES_CARD)
        page.locator(".c").screenshot(path=str(OUT / "names.png"), omit_background=True)

        # the animated flows (GIF: plays inline on Telegraph and in Telegram)
        for flow, names in FLOWS.items():
            frames = WORK / flow
            frames.mkdir(exist_ok=True)
            big = max(Image.open(shots[n]).size[1] for n in names)
            for i, n in enumerate(names):          # same canvas for every frame: no jumping
                im = Image.open(shots[n]).convert("RGBA")
                canvas = Image.new("RGBA", (im.size[0], big), (14, 22, 33, 255))
                canvas.paste(im, (0, big - im.size[1]), im)
                canvas.convert("RGB").save(frames / f"{i:02d}.png")
            lst = frames / "list.txt"
            lst.write_text("".join(f"file '{(frames / f'{i:02d}.png').as_posix()}'\nduration 2.2\n" for i in range(len(names)))
                           + f"file '{(frames / f'{len(names) - 1:02d}.png').as_posix()}'\n")
            ffmpeg("-f", "concat", "-safe", "0", "-i", str(lst), "-vf",
                   "fps=8,scale=420:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=160[p];[b][p]paletteuse=dither=bayer",
                   "-loop", "0", str(OUT / f"flow_{flow}.gif"))

        # the explainer videos: slides, crossfaded
        for lang, slides in VIDEO.items():
            paths = []
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            for i, s in enumerate(slides):
                page.set_content(title_slide(*s[1:]) if s[0] == "title" else slide(s[1], s[2], s[3], shots[s[0]]))
                page.wait_for_timeout(120)
                path = WORK / f"{lang}_{i:02d}.png"
                page.screenshot(path=str(path))
                paths.append(path)
            page.close()
            dur, fade = 3.6, 0.6
            inputs = []
            for path in paths:
                inputs += ["-loop", "1", "-t", str(dur), "-i", str(path)]
            chain, last = [], "[0:v]"
            for i in range(1, len(paths)):
                out = f"[v{i}]"
                chain.append(f"{last}[{i}:v]xfade=transition=fade:duration={fade}:offset={i * (dur - fade):.2f}{out}")
                last = out
            ffmpeg(*inputs, "-filter_complex", ";".join(chain) + f";{last}format=yuv420p[out]", "-map", "[out]",
                   "-r", "30", "-c:v", "libx264", "-crf", "24", "-movflags", "+faststart", str(OUT / f"explainer_{lang}.mp4"))
        browser.close()
    shutil.rmtree(WORK, ignore_errors=True)
    for f in sorted(OUT.iterdir()):
        print(f"{f.name:28} {f.stat().st_size // 1024:6} KB")


if __name__ == "__main__":
    main()
