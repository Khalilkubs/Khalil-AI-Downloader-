"""App code. Started by main.py (which shows startup errors on screen)."""
import os, re, sys, json, shutil, mimetypes, threading, zipfile, hashlib, ssl, urllib.request
from datetime import datetime

import os as _os
if sys.stdout is None:
    sys.stdout = open(_os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(_os.devnull, "w")

import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from kivy.app import App
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.core.clipboard import Clipboard
from kivy.properties import StringProperty, NumericProperty, BooleanProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.utils import platform

# --- yt-dlp self-update support: a downloaded copy (if any) takes priority over the bundled one ---
DATA_DIR = os.environ.get("ANDROID_PRIVATE") or os.path.join(os.path.expanduser("~"), ".khalil_downloader")
UPDATE_ZIP = os.path.join(DATA_DIR, "ytdlp_update", "yt_dlp.zip")
COOKIES_PATH = os.path.join(DATA_DIR, "cookies.txt")
if os.path.isfile(UPDATE_ZIP) and zipfile.is_zipfile(UPDATE_ZIP):
    sys.path.insert(0, UPDATE_ZIP)
try:
    import yt_dlp
except Exception:  # broken update -> drop it and use the bundled version
    sys.path[:] = [p for p in sys.path if p != UPDATE_ZIP]
    for _m in [k for k in sys.modules if k.startswith("yt_dlp")]:
        del sys.modules[_m]
    try:
        os.remove(UPDATE_ZIP)
    except OSError:
        pass
    import yt_dlp
from yt_dlp.version import __version__ as YTDLP_VERSION

Window.softinput_mode = "below_target"
HERE = os.path.dirname(os.path.abspath(globals().get("__file__", "app_main.py")))
OK, ERR = (0.2, 0.85, 0.3, 1), (1, 0.3, 0.3, 1)
MUTED = (0.5, 0.5, 0.5, 1)

# Android has no ffmpeg -> single-file formats only (no merging / mp3 conversion).
FORMATS = {
    "Best": "best[ext=mp4]/best",
    "720p": "best[height<=720][ext=mp4]/best[height<=720]/best",
    "480p": "best[height<=480][ext=mp4]/best[height<=480]/best",
    "360p": "best[height<=360][ext=mp4]/best[height<=360]/best",
    "Audio (m4a)": "bestaudio[ext=m4a]/bestaudio",
}
YT_CLIENTS = [None, ["tv"], ["android_vr"], ["mweb"]]  # fallbacks if default YouTube client fails


class QuietLogger:
    def debug(self, msg): pass
    def info(self, msg): pass
    def warning(self, msg): pass
    def error(self, msg): pass


def clean(msg):
    return re.sub(r"\x1b\[[0-9;]*m", "", str(msg)).replace("ERROR: ", "").strip()[:300]


def export_to_downloads(path):
    """Move finished file to public Downloads/KhalilDownloader (works on Android 10+)."""
    name = os.path.basename(path)
    if platform != "android":
        dest = os.path.join(os.path.expanduser("~"), "Downloads", "KhalilDownloader")
        os.makedirs(dest, exist_ok=True)
        shutil.move(path, os.path.join(dest, name))
        return "Downloads/KhalilDownloader/" + name
    from jnius import autoclass
    if autoclass("android.os.Build$VERSION").SDK_INT >= 29:
        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        resolver = activity.getContentResolver()
        values = autoclass("android.content.ContentValues")()
        cols = autoclass("android.provider.MediaStore$MediaColumns")
        values.put(cols.DISPLAY_NAME, name)
        values.put(cols.MIME_TYPE, mimetypes.guess_type(name)[0] or "application/octet-stream")
        values.put(cols.RELATIVE_PATH, "Download/KhalilDownloader")
        uri = resolver.insert(autoclass("android.provider.MediaStore$Downloads").EXTERNAL_CONTENT_URI, values)
        out = resolver.openOutputStream(uri)
        inp = autoclass("java.io.FileInputStream")(path)
        autoclass("android.os.FileUtils").copy(inp, out)
        inp.close()
        out.close()
        os.remove(path)
    else:
        env = autoclass("android.os.Environment")
        base = env.getExternalStoragePublicDirectory(env.DIRECTORY_DOWNLOADS).getAbsolutePath()
        dest = os.path.join(base, "KhalilDownloader")
        os.makedirs(dest, exist_ok=True)
        shutil.move(path, os.path.join(dest, name))
    return "Download/KhalilDownloader/" + name


def history_file():
    return os.path.join(App.get_running_app().user_data_dir, "history.json")


def load_history():
    try:
        with open(history_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def save_history(entry):
    with open(history_file(), "w", encoding="utf-8") as f:
        json.dump(([entry] + load_history())[:100], f, ensure_ascii=False, indent=1)


class HistoryItem(BoxLayout):          # declared here so the kv rule's properties exist
    title = StringProperty("")
    date = StringProperty("")
    quality = StringProperty("")


class DownloadScreen(Screen):
    video_title = StringProperty("")
    video_uploader = StringProperty("")
    video_duration = StringProperty("")
    video_views = StringProperty("")
    progress = NumericProperty(0)
    status_text = StringProperty("Ready")
    speed_text = StringProperty("")
    eta_text = StringProperty("")
    has_video_info = BooleanProperty(False)
    is_downloading = BooleanProperty(False)

    def ui(self, fn):
        Clock.schedule_once(lambda dt: fn())

    def show(self, msg, color=MUTED):
        def f():
            self.ids.status_label.text = msg
            self.ids.status_label.color = color
        self.ui(f)

    def _opts(self):
        o = {"logger": QuietLogger(), "quiet": True, "no_warnings": True, "noplaylist": True, "no_color": True,
             "socket_timeout": 30, "retries": 5, "noprogress": True}
        if os.path.isfile(COOKIES_PATH):
            o["cookiefile"] = COOKIES_PATH
        return o

    def _run(self, url, opts, download):
        last = None
        for client in (YT_CLIENTS if "youtu" in url else [None]):
            o = dict(opts)
            if client:
                o["extractor_args"] = {"youtube": {"player_client": client}}
            try:
                with yt_dlp.YoutubeDL(o) as ydl:
                    return ydl.extract_info(url, download=download)
            except Exception as e:
                last = e
        raise last

    def on_kv_post(self, base_widget):
        self.show("yt-dlp %s | cookies: %s" % (YTDLP_VERSION, "on" if os.path.isfile(COOKIES_PATH) else "off"))

    def paste_cookies(self):
        """Save cookies copied to the clipboard (Netscape cookies.txt format) for yt-dlp."""
        try:
            text = (Clipboard.paste() or "").replace("\r", "")
            lines, domains = [], set()
            for raw in text.split("\n"):
                line = raw.strip()
                if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
                    continue
                parts = line.split("\t") if line.count("\t") >= 6 else line.split()
                if len(parts) == 7:
                    lines.append("\t".join(parts))
                    domains.add(parts[0].lstrip("#").replace("HttpOnly_", "").lstrip("."))
            if len(lines) < 3:
                return self.show("No cookies found in the clipboard. Copy the whole cookies.txt text first, "
                                 "then tap Paste cookies.", ERR)
            os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)
            with open(COOKIES_PATH, "w", encoding="utf-8") as f:
                f.write("# Netscape HTTP Cookie File\n" + "\n".join(lines) + "\n")
            has_yt = any("youtube.com" in d or "google.com" in d for d in domains)
            msg = "Cookies saved (%d entries)." % len(lines)
            if not has_yt:
                msg += " Warning: no youtube.com or google.com cookies found."
            self.show(msg + " Try your link again.", OK if has_yt else ERR)
        except Exception as e:
            self.show("Cookie error: " + clean(e), ERR)

    def clear_cookies(self):
        try:
            if os.path.isfile(COOKIES_PATH):
                os.remove(COOKIES_PATH)
            self.show("Cookies deleted.", OK)
        except Exception as e:
            self.show("Cookie error: " + clean(e), ERR)

    def update_ytdlp(self):
        """Download the latest yt-dlp release (checksum-verified); applies after app restart."""
        if self.is_downloading:
            return
        self.show("Checking for yt-dlp update...")

        def work():
            try:
                ctx = ssl.create_default_context(cafile=certifi.where())
                base = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/"

                def get(name):
                    req = urllib.request.Request(base + name, headers={"User-Agent": "KhalilDownloader"})
                    with urllib.request.urlopen(req, timeout=60, context=ctx) as r:
                        return r.read()

                want = None
                for line in get("SHA2-256SUMS").decode().splitlines():
                    parts = line.split()
                    if len(parts) >= 2 and parts[-1].lstrip("*") == "yt-dlp":
                        want = parts[0]
                if not want:
                    raise RuntimeError("Could not verify update (no checksum)")
                data = get("yt-dlp")
                if hashlib.sha256(data).hexdigest() != want:
                    raise RuntimeError("Checksum mismatch - update cancelled")
                os.makedirs(os.path.dirname(UPDATE_ZIP), exist_ok=True)
                tmp = UPDATE_ZIP + ".new"
                with open(tmp, "wb") as f:
                    f.write(data)
                with zipfile.ZipFile(tmp) as z:
                    ver = re.search(r"__version__\s*=\s*'([^']+)'", z.read("yt_dlp/version.py").decode()).group(1)
                if ver == YTDLP_VERSION:
                    os.remove(tmp)
                    return self.show("Already up to date (yt-dlp %s)" % ver, OK)
                os.replace(tmp, UPDATE_ZIP)
                self.show("Updated to yt-dlp %s. Close and reopen the app." % ver, OK)
            except Exception as e:
                self.show("Update failed: " + clean(e), ERR)
        threading.Thread(target=work, daemon=True).start()

    def fetch_video_info(self):
        url = self.ids.url_input.text.strip()
        if not url:
            return self.show("Please enter a URL", ERR)
        self.ids.fetch_btn.disabled = True
        self.ids.fetch_btn.text = "Fetching..."

        def work():
            try:
                info = self._run(url, self._opts(), False)
                dur = int(info.get("duration") or 0)
                views = info.get("view_count")

                def apply():
                    self.video_title = info.get("title") or "Unknown"
                    self.video_uploader = info.get("uploader") or "Unknown"
                    self.video_duration = "%d:%02d" % (dur // 60, dur % 60)
                    self.video_views = "{:,} views".format(views) if views else ""
                    self.has_video_info = True
                self.ui(apply)
                self.show("")
            except Exception as e:
                self.show(clean(e), ERR)
            finally:
                def reset():
                    self.ids.fetch_btn.disabled = False
                    self.ids.fetch_btn.text = "Fetch Info"
                self.ui(reset)
        threading.Thread(target=work, daemon=True).start()

    def start_download(self):
        if self.is_downloading:
            return
        url = self.ids.url_input.text.strip()
        quality = self.ids.quality_spinner.text
        if not url:
            return self.show("Please enter a URL", ERR)
        self.is_downloading = True
        self.progress = 0
        self.status_text = "Starting..."
        self.speed_text = self.eta_text = ""
        self.ids.download_btn.disabled = True
        self.ids.download_btn.text = "Downloading..."
        tmp = os.path.join(App.get_running_app().user_data_dir, "dl")
        os.makedirs(tmp, exist_ok=True)

        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                pct = d.get("downloaded_bytes", 0) / total * 100 if total else 0
                spd, eta = d.get("speed"), d.get("eta")

                def f():
                    self.progress = pct
                    self.status_text = "Downloading %.0f%%" % pct
                    self.speed_text = ("%.1f MB/s" % (spd / 1e6)) if spd else ""
                    self.eta_text = ("ETA %d:%02d" % (eta // 60, eta % 60)) if eta else ""
                self.ui(f)

        def finish():
            self.is_downloading = False
            self.ids.download_btn.disabled = False
            self.ids.download_btn.text = "Download"

        def work():
            try:
                opts = self._opts()
                opts.update({"format": FORMATS.get(quality, FORMATS["Best"]),
                             "outtmpl": os.path.join(tmp, "%(title).80s [%(id)s].%(ext)s"),
                             "restrictfilenames": True, "progress_hooks": [hook]})
                info = self._run(url, opts, True)
                path = (info.get("requested_downloads") or [{}])[0].get("filepath")
                if not path or not os.path.exists(path):
                    raise RuntimeError("Downloaded file not found")
                shown = export_to_downloads(path)
                save_history({"title": info.get("title") or "Video", "quality": quality, "url": url,
                              "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
                self.ui(lambda: setattr(self, "progress", 100))
                self.ui(lambda: setattr(self, "status_text", "Download complete"))
                self.show("Saved to " + shown, OK)
            except Exception as e:
                self.ui(lambda: setattr(self, "status_text", "Failed"))
                self.show(clean(e), ERR)
            finally:
                self.ui(finish)
        threading.Thread(target=work, daemon=True).start()


class HistoryScreen(Screen):
    def on_enter(self):
        self.ids.history_rv.data = [
            {"title": i.get("title", "Unknown"), "date": i.get("date", ""), "quality": i.get("quality", "")}
            for i in load_history()]


class KhalilDownloaderApp(App):
    title = "Khalil Video Downloader"

    def build(self):
        Window.clearcolor = (0.055, 0.067, 0.09, 1)
        Builder.load_file(os.path.join(HERE, "khalil_downloader.kv"))  # file name != auto-load name
        sm = ScreenManager()
        sm.add_widget(DownloadScreen(name="download"))
        sm.add_widget(HistoryScreen(name="history"))
        return sm

    def on_start(self):
        if platform == "android":
            from jnius import autoclass
            if autoclass("android.os.Build$VERSION").SDK_INT < 29:
                from android.permissions import request_permissions, Permission
                request_permissions([Permission.WRITE_EXTERNAL_STORAGE])


if __name__ == "__main__":
    KhalilDownloaderApp().run()
