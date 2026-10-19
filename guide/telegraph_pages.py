"""Publishes, or updates, the bot's Telegraph guide in English and French: python guide/telegraph_pages.py <commit>.
The pictures are served by jsDelivr from this public repo at that commit (guide/img, made by build_guide.py).
The Telegraph token stays out of every repo (~/.telegraph_accounts.json): it can edit the pages."""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ACCOUNTS = Path.home() / ".telegraph_accounts.json"     # never in a repo: the token edits the pages
KEY = "renambot"
BOT_URL = ""                     # https://t.me/<the bot> once known: shown under the title and at the end
COMMIT = sys.argv[1] if len(sys.argv) > 1 else "main"
IMG = f"https://cdn.jsdelivr.net/gh/DINO060/RENAMBOT@{COMMIT}/guide/img/"


def api(method, **params):
    data = urllib.parse.urlencode({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else v
                                   for k, v in params.items()}).encode()
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegra.ph/{method}", data=data), timeout=30) as r:
        res = json.load(r)
    if not res.get("ok"):
        raise RuntimeError(f"{method}: {res.get('error')}")
    return res["result"]


# --- Telegraph nodes
def node(tag, *children, **attrs):
    n = {"tag": tag, "children": [c for c in children if c not in (None, "")]}
    if attrs:
        n["attrs"] = attrs
    return n


def p(*c): return node("p", *c)
def h3(t): return node("h3", t)
def b(t): return node("b", t)
def code(t): return node("code", t)
def a(t, href): return node("a", t, href=href)
def ul(*items): return node("ul", *[node("li", *(i if isinstance(i, tuple) else (i,))) for i in items])
def ol(*items): return node("ol", *[node("li", *(i if isinstance(i, tuple) else (i,))) for i in items])
def fig(name, caption): return node("figure", node("img", src=IMG + name), node("figcaption", caption))
def video(name, caption): return node("figure", node("video", src=IMG + name), node("figcaption", caption))


def english(other_url):
    return [
        p("RƐNAM BOT ", b("renames your files"), " (up to 2 GB), puts ", b("your own thumbnail"), " on them and adds ",
          b("your channel's name"), " — one file or a whole season at once. Here is everything it does, step by step."),
        video("explainer_en.mp4", "The bot in 30 seconds"),
        p(a("🇫🇷 Version française", other_url)) if other_url else None,
        h3("1. Rename a file"),
        ol(("Send the bot a file: any type, up to 2 GB.",),
           ("Choose: ", b("🖼️ Add Thumbnail"), " (new name + your thumbnail) or ", b("✏️ Rename Only"),
            " (new name, the file keeps its own thumbnail)."),
           ("Reply to the bot's message with the new name. No extension? The file's own is kept (.mkv, .mp4…).",),
           ("The renamed file comes back. Videos stay playable right in Telegram.",)),
        fig("flow_rename.gif", "Send → choose → type the name → done"),
        fig("file_question.png", "What the bot asks when a file arrives"),
        h3("2. Many files at once"),
        p("Send several files together (an album, or forward them all at once). The bot asks ", b("one"),
          " question for all of them:"),
        ul((b("🖼️ Thumbnail on all"), " — your thumbnail goes on every file, names kept, sent back in the order you sent them."),
           (b("✏️ One by one"), " — the bot asks you for each file, as for a single one.")),
        fig("flow_batch.gif", "A whole season with your thumbnail, in one tap"),
        h3("3. Your thumbnail"),
        ul((code("/setthumb"), " then send a photo. Any size: it is resized the way Telegram wants thumbnails."),
           (code("/showthumb"), " shows it, ", code("/delthumb"), " removes it.")),
        fig("flow_thumbnail.gif", "/setthumb, a photo, saved"),
        h3("4. Settings: your name on every file"),
        p("Open them with ", code("/settings"), " or the ⚙️ Settings button:"),
        ul((b("➕ Custom text"), " — for example @MyChannel, added to every file name."),
           (b("📍 Position"), " — your text at the start or at the end of the name."),
           (b("🗑️ Remove"), " — no more custom text."),
           (b("🧹 Clean Tags"), " — removes the other @names and #hashtags from the names (on by default).")),
        fig("settings.png", "The settings menu"),
        fig("names.png", "What the settings do to a name"),
        h3("5. Limits"),
        ul("Files up to 2 GB.",
           ("A number of files per day for each user (", code("/usage"), " shows yours). A file counts once, whatever you do with it."),
           "One file at a time for each user: the others wait in line and come back in order."),
        h3("Commands"),
        ul((code("/start"), " — welcome and buttons"), (code("/help"), " — this guide"),
           (code("/settings"), " — custom text, position, clean tags"), (code("/setthumb"), " · ", code("/showthumb"), " · ",
            code("/delthumb"), " — your thumbnail"), (code("/usage"), " — what you used today"),
           (code("/status"), " — the bot's status"), (code("/cancel"), " — stop what you are doing")),
        h3("Good to know"),
        ul("If the bot asks you to join a channel first, join it and tap ✅ I have joined.",
           "When the bot gets new features, it tells you what's new — once."),
        p(a("👉 Open the bot", BOT_URL)) if BOT_URL else None,
    ]


def french(other_url):
    return [
        p("RƐNAM BOT ", b("renomme tes fichiers"), " (jusqu'à 2 Go), y met ", b("ta propre miniature"), " et ajoute ",
          b("le nom de ta chaîne"), " — un fichier ou toute une saison d'un coup. Voici tout ce qu'il fait, étape par étape."),
        video("explainer_fr.mp4", "Le bot en 30 secondes"),
        p(a("🇬🇧 English version", other_url)) if other_url else None,
        h3("1. Renommer un fichier"),
        ol(("Envoie un fichier au bot : n'importe quel type, jusqu'à 2 Go.",),
           ("Choisis : ", b("🖼️ Add Thumbnail"), " (nouveau nom + ta miniature) ou ", b("✏️ Rename Only"),
            " (nouveau nom, le fichier garde sa propre miniature)."),
           ("Réponds au message du bot avec le nouveau nom. Sans extension ? Celle du fichier est gardée (.mkv, .mp4…).",),
           ("Le fichier renommé revient. Les vidéos restent lisibles directement dans Telegram.",)),
        fig("flow_rename.gif", "Envoyer → choisir → taper le nom → c'est fait"),
        fig("file_question.png", "Ce que le bot demande quand un fichier arrive"),
        h3("2. Plusieurs fichiers d'un coup"),
        p("Envoie plusieurs fichiers ensemble (un album, ou transfère-les tous d'un coup). Le bot pose ", b("une seule"),
          " question pour tous :"),
        ul((b("🖼️ Thumbnail on all"), " — ta miniature sur chaque fichier, noms gardés, renvoyés dans l'ordre où tu les as envoyés."),
           (b("✏️ One by one"), " — le bot te demande pour chaque fichier, comme pour un seul.")),
        fig("flow_batch.gif", "Toute une saison avec ta miniature, en un seul bouton"),
        h3("3. Ta miniature"),
        ul((code("/setthumb"), " puis envoie une photo. N'importe quelle taille : elle est redimensionnée comme Telegram le veut."),
           (code("/showthumb"), " l'affiche, ", code("/delthumb"), " la supprime.")),
        fig("flow_thumbnail.gif", "/setthumb, une photo, enregistrée"),
        h3("4. Réglages : ton nom sur chaque fichier"),
        p("Ouvre-les avec ", code("/settings"), " ou le bouton ⚙️ Settings :"),
        ul((b("➕ Texte perso"), " — par exemple @MaChaine, ajouté au nom de chaque fichier."),
           (b("📍 Position"), " — ton texte au début ou à la fin du nom."),
           (b("🗑️ Supprimer"), " — plus de texte perso."),
           (b("🧹 Clean Tags"), " — enlève les autres @noms et #hashtags des noms (activé par défaut).")),
        fig("settings.png", "Le menu des réglages"),
        fig("names.png", "Ce que les réglages font à un nom"),
        h3("5. Limites"),
        ul("Fichiers jusqu'à 2 Go.",
           ("Un nombre de fichiers par jour pour chaque utilisateur (", code("/usage"), " affiche le tien). Un fichier compte une fois, quoi que tu en fasses."),
           "Un fichier à la fois par utilisateur : les autres attendent leur tour et reviennent dans l'ordre."),
        h3("Commandes"),
        ul((code("/start"), " — accueil et boutons"), (code("/help"), " — ce guide"),
           (code("/settings"), " — texte perso, position, nettoyage"), (code("/setthumb"), " · ", code("/showthumb"), " · ",
            code("/delthumb"), " — ta miniature"), (code("/usage"), " — ce que tu as utilisé aujourd'hui"),
           (code("/status"), " — l'état du bot"), (code("/cancel"), " — arrêter ce que tu fais")),
        h3("Bon à savoir"),
        ul("Si le bot te demande de rejoindre une chaîne d'abord, rejoins-la puis appuie sur ✅ I have joined.",
           "Quand le bot reçoit de nouvelles fonctions, il te dit ce qui change — une seule fois."),
        p(a("👉 Ouvrir le bot", BOT_URL)) if BOT_URL else None,
    ]


def clean(nodes):
    return [n for n in nodes if n]


def main():
    accounts = json.loads(ACCOUNTS.read_text(encoding="utf-8")) if ACCOUNTS.exists() else {}
    acc = accounts.get(KEY) or {}
    if not acc.get("token"):
        acc["token"] = api("createAccount", short_name="RƐNAM BOT", author_name="RƐNAM BOT",
                           author_url=BOT_URL)["access_token"]
    common = {"access_token": acc["token"], "author_name": "RƐNAM BOT", "author_url": BOT_URL}
    titles = {"en": "RƐNAM BOT — How to use it", "fr": "RƐNAM BOT — Mode d'emploi"}

    def publish(lang, content):
        if acc.get(lang):
            return api(f"editPage/{acc[lang]}", title=titles[lang], content=clean(content), **common)
        return api("createPage", title=titles[lang], content=clean(content), **common)

    en = publish("en", english(None) if not acc.get("fr") else english(f"https://telegra.ph/{acc['fr']}"))
    acc["en"] = en["path"]
    fr = publish("fr", french(en["url"]))
    acc["fr"] = fr["path"]
    en = publish("en", english(fr["url"]))           # now with the link to the French page
    accounts[KEY] = acc
    ACCOUNTS.write_text(json.dumps(accounts, indent=2), encoding="utf-8")
    print("EN", en["url"])
    print("FR", fr["url"])


if __name__ == "__main__":
    main()
