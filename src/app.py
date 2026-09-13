from __future__ import annotations

import asyncio
import json
import os
import importlib.util
from importlib import metadata as importlib_metadata
import site
import re
import shutil
import queue
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

APP_NAME = "Chartshunter Media Studio v41"
APP_VERSION = "v41"

MEDIA_EXTENSIONS = {
    ".mp4", ".mkv", ".webm", ".mov", ".avi",
    ".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg"
}
TEXT_EXTENSIONS = {".srt", ".txt"}
MP3_EXTENSIONS = {".mp3"}

UK_VOICES = {
    "Sonia - UK kadın": "en-GB-SoniaNeural",
    "Libby - UK kadın": "en-GB-LibbyNeural",
    "Ryan - UK erkek": "en-GB-RyanNeural",
    "Thomas - UK erkek": "en-GB-ThomasNeural",
    "Maisie - UK kadın": "en-GB-MaisieNeural",
}

DOWNLOAD_QUALITY_OPTIONS = [
    "MP4 2160p / 4K",
    "MP4 1440p / 2K",
    "MP4 1080p",
    "MP4 720p",
    "MP4 480p",
    "MP4 360p",
    "MP4 en iyi",
    "MP3 320 kbps",
    "MP3 192 kbps",
    "MP3 128 kbps",
    "En iyi orijinal",
]

# Kapalı web servislerini motor gibi gömmek yerine güvenli “köprü” olarak açıyoruz.
# Cobalt zaten API fallback olarak uygulamaya entegre. SaveFrom/VDownloader/VDH tarafında
# herkese açık stabil bir API olmadığı için linki panoya kopyalayıp ilgili aracı açmak en temiz yöntem.
EXTERNAL_HELPERS = {
    "SaveFrom.net": "https://en.savefrom.net/",
    "VDownloader": "https://vdownloader.com/download",
    "Video DownloadHelper": "https://www.downloadhelper.net/",
    "Video DownloadHelper Chrome": "https://chromewebstore.google.com/detail/video-downloadhelper/lmjnegcaeklhafolokijcfjliaokphfk",
    "Cobalt Web": "https://cobalt.tools/",
}


def is_mp3_download_mode(mode: str) -> bool:
    return (mode or "").startswith("MP3")


def mp3_quality_for_mode(mode: str) -> str:
    if "320" in (mode or ""):
        return "320"
    if "128" in (mode or ""):
        return "128"
    return "192"


def is_mp4_download_mode(mode: str) -> bool:
    return (mode or "").startswith("MP4")


class UserCancelled(Exception):
    """Kullanıcı işlemi iptal ettiğinde kullanılır."""
    pass


class FatalDownloadError(Exception):
    """Aynı linkte denemeyi sürdürmenin anlamsız olduğu net indirme hataları."""
    pass


# ============================================================
# WINDOWS / EXE ALT SUREC YARDIMCILARI
# ============================================================

def app_base_dir() -> Path:
    """Uygulamanın kullanıcıya görünen ana klasörünü döndürür."""
    env_dir = os.environ.get("CHARTSHUNTER_APP_DIR")
    if env_dir:
        try:
            return Path(env_dir).resolve()
        except Exception:
            pass
    try:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
    except Exception:
        pass
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    """Sürümler arasında ortak runtime/cache klasörü."""
    env_dir = os.environ.get("CHARTSHUNTER_DATA_DIR")
    if env_dir:
        root = Path(env_dir)
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / "ChartshunterMediaStudio"
    else:
        root = app_base_dir() / ".chartshunter_data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def whisper_cache_dir() -> Path:
    env_dir = os.environ.get("CHARTSHUNTER_WHISPER_CACHE")
    root = Path(env_dir) if env_dir else user_data_dir() / "cache" / "whisper"
    root.mkdir(parents=True, exist_ok=True)
    return root


def shared_runtime_venv_dir() -> Path:
    """Tüm sürümlerin paylaştığı hafif Python çalışma ortamı. Normal açılışta oluşturulmaz."""
    return user_data_dir() / "runtime" / ".venv"


def shared_runtime_python() -> Path:
    root = shared_runtime_venv_dir()
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def shared_runtime_site_packages() -> Path:
    root = shared_runtime_venv_dir()
    if os.name == "nt":
        return root / "Lib" / "site-packages"
    major, minor = sys.version_info[:2]
    return root / "lib" / f"python{major}.{minor}" / "site-packages"


def activate_shared_site_packages() -> None:
    """Daha önce kurulmuş isteğe bağlı paketleri mevcut GUI sürecine görünür yapar."""
    try:
        sp = shared_runtime_site_packages()
        if sp.exists():
            site.addsitedir(str(sp))
            importlib.invalidate_caches()
        py = shared_runtime_python()
        if py.exists():
            os.environ["CHARTSHUNTER_TOOL_PYTHON"] = str(py)
    except Exception:
        pass


def lazy_component_state_file() -> Path:
    return user_data_dir() / "lazy_components.json"


def setup_status_file() -> Path:
    return user_data_dir() / "setup_status.json"


def update_catalog_file() -> Path:
    """İlk oturumda yalnızca sürüm bilgisinin saklandığı küçük katalog."""
    return user_data_dir() / "update_catalog.json"


UPDATE_PACKAGE_MAP = {
    "yt_dlp": "yt-dlp",
    "requests": "requests",
    "whisper_pkg": "faster-whisper",
    "edge_tts": "edge-tts",
    "browser_pkg": "playwright",
    "gallery_dl": "gallery-dl",
    "streamlink": "streamlink",
    "you_get": "you-get",
    "curl_cffi": "curl-cffi",
}

WHISPER_REPOS = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
}


def mark_runtime_usage(feature: str, detail: str | None = None) -> None:
    """Bakımın sadece gerçekten kullanılan büyük bileşenleri kontrol etmesi için işaret bırakır."""
    try:
        path = user_data_dir() / "usage.json"
        data = {}
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        now = time.time()
        item = data.get(feature, {}) if isinstance(data.get(feature), dict) else {}
        item["last_used"] = now
        if detail:
            details = item.get("details", {}) if isinstance(item.get("details"), dict) else {}
            details[detail] = now
            item["details"] = details
        data[feature] = item
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def subprocess_hidden_kwargs() -> dict:
    """Windows'ta yt-dlp/ffmpeg gibi alt işlemler yeni CMD/PowerShell penceresi açmasın."""
    if os.name != "nt":
        return {}
    kwargs = {}
    try:
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    except Exception:
        pass
    try:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    except Exception:
        pass
    return kwargs


def tool_python_executable() -> str:
    """
    yt-dlp/playwright gibi modülleri çalıştırmak için doğru Python'u bulur.

    Neden gerekli?
    - Uygulama PyInstaller EXE olarak açıldığında sys.executable uygulamanın EXE'sidir.
      Bunu 'sys.executable -m yt_dlp' diye çağırırsak uygulama kendini tekrar açabilir.
    - pythonw.exe ile açıldığında da konsol görünmez ama bazı CLI araçlarda çıktı yakalama
      naz yapabilir. Bu yüzden aynı venv içindeki python.exe tercih edilir.
    """
    env_py = os.environ.get("CHARTSHUNTER_TOOL_PYTHON")
    if env_py and Path(env_py).exists():
        return env_py

    base = app_base_dir()
    candidates = [shared_runtime_python()]
    if os.name == "nt":
        candidates += [
            base / ".venv" / "Scripts" / "python.exe",
            Path.cwd() / ".venv" / "Scripts" / "python.exe",
        ]
        try:
            exe = Path(sys.executable)
            if exe.name.lower() == "pythonw.exe":
                candidates.append(exe.with_name("python.exe"))
        except Exception:
            pass
    else:
        candidates += [base / ".venv" / "bin" / "python", Path.cwd() / ".venv" / "bin" / "python"]

    for candidate in candidates:
        try:
            if candidate.exists():
                return str(candidate)
        except Exception:
            pass

    # Frozen EXE ise sys.executable'i geri döndürme; bu uygulamayı yeniden açabilir.
    if not getattr(sys, "frozen", False):
        return sys.executable

    found = shutil.which("python") or shutil.which("py")
    if found:
        return found
    return sys.executable


def python_module_command(module_name: str) -> list[str]:
    py = tool_python_executable()
    if Path(py).name.lower() == "py.exe" or Path(py).name.lower() == "py":
        return [py, "-m", module_name]
    return [py, "-m", module_name]


# ============================================================
# ORTAK YARDIMCI FONKSIYONLAR
# ============================================================

def now_text() -> str:
    return datetime.now().strftime("%H:%M:%S")


def normal_time(seconds: float) -> str:
    seconds = int(seconds)
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02}:{m:02}:{s:02}"


def format_download_speed(bytes_per_second: float | int | None) -> str:
    """İndirme hızını okunabilir hale getirir: KB/s, MB/s, GB/s."""
    try:
        value = float(bytes_per_second or 0)
    except Exception:
        value = 0.0

    if value <= 0:
        return "-"

    units = ["B/s", "KB/s", "MB/s", "GB/s"]
    unit_index = 0
    while value >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1

    return f"{value:.2f} {units[unit_index]}"


def extract_speed_from_line(line: str) -> str | None:
    """yt-dlp/aria2/ffmpeg çıktı satırlarından hız bilgisini yakalamaya çalışır."""
    patterns = [
        r"(?i)(\d+(?:[.,]\d+)?)\s*(B/s|KB/s|MB/s|GB/s|KiB/s|MiB/s|GiB/s)",
        r"(?i)DL[:=]\s*(\d+(?:[.,]\d+)?)\s*(B|KB|MB|GB|KiB|MiB|GiB)",
    ]
    for pattern in patterns:
        m = re.search(pattern, line)
        if not m:
            continue
        number = m.group(1).replace(",", ".")
        unit = m.group(2)
        if not unit.lower().endswith("/s"):
            unit = f"{unit}/s"
        return f"{number} {unit}"
    return None


def is_fatal_download_error_text(text: str) -> bool:
    """
    Aynı linkte denemeye devam etmenin anlamsız olduğu net bağlantı/DNS hatalarını yakalar.

    Amaç:
    - streamlink/yt-dlp/ffmpeg aynı bozuk linki tekrar tekrar denemesin.
    - Örnek: NameResolutionError, Max retries exceeded, Could not resolve host.

    Bu DRM/koruma ile ilgili değildir; sadece geçersiz/çözülemeyen/ulaşılamayan URL
    durumunda işlemi erken kesmek içindir.
    """
    low = (text or "").lower()
    fatal_tokens = [
        "nameresolutionerror",
        "name resolution error",
        "failed to resolve",
        "could not resolve host",
        "temporary failure in name resolution",
        "getaddrinfo failed",
        "nodename nor servname provided",
        "no address associated with hostname",
        "max retries exceeded with url",
        "unable to open url",
        "error opening input file",
        "server returned 404",
        "http error 404",
        "404 not found",
        "403 forbidden",
        "http error 403",
        "certificate verify failed",
        "ssl: certificate_verify_failed",
        "video is not available",
        "this video is not available",
        "video unavailable",
        "this video is private",
        "access denied",
        "access to this video is denied",
        "login required",
        "requires login",
        "sign in to confirm",
        "not available in your country",
        "not available in your region",
        "content is unavailable",
    ]
    return any(token in low for token in fatal_tokens)


def is_vk_url(url: str) -> bool:
    """VK / VK Video alan adlarını güvenli biçimde tanır."""
    try:
        host = (urlparse(url).hostname or "").lower().strip(".")
    except Exception:
        host = ""
    return host in {"vk.com", "www.vk.com", "m.vk.com", "vkvideo.ru", "www.vkvideo.ru"} or host.endswith(".vk.com") or host.endswith(".vkvideo.ru")


COOKIE_BROWSER_AUTO = "Otomatik (Brave öncelikli)"
COOKIE_BROWSER_CHOICES = [COOKIE_BROWSER_AUTO, "Brave", "Chrome", "Edge", "Firefox", "Yok"]


def _browser_cookie_profile_exists(browser: str) -> bool:
    """Standart Windows profil klasörlerinden tarayıcının kullanılmış olup olmadığını tahmin eder."""
    browser = (browser or "").strip().lower()
    env = os.environ
    candidates: list[Path] = []
    local = Path(env.get("LOCALAPPDATA", "")) if env.get("LOCALAPPDATA") else None
    roaming = Path(env.get("APPDATA", "")) if env.get("APPDATA") else None

    if browser == "brave" and local:
        candidates.append(local / "BraveSoftware" / "Brave-Browser" / "User Data")
    elif browser == "chrome" and local:
        candidates.append(local / "Google" / "Chrome" / "User Data")
    elif browser == "edge" and local:
        candidates.append(local / "Microsoft" / "Edge" / "User Data")
    elif browser == "firefox" and roaming:
        candidates.append(roaming / "Mozilla" / "Firefox" / "Profiles")

    return any(p.exists() for p in candidates)


def resolve_cookie_browser_choice(choice: str) -> str | None:
    """
    GUI seçimini yt-dlp'nin beklediği tarayıcı adına çevirir.
    Otomatik mod Brave -> Chrome -> Edge -> Firefox sırasıyla mevcut profili seçer.
    """
    raw = (choice or "").strip()
    if not raw or raw == "Yok":
        return None
    if raw == COOKIE_BROWSER_AUTO:
        for browser in ("brave", "chrome", "edge", "firefox"):
            if _browser_cookie_profile_exists(browser):
                return browser
        return None
    low = raw.lower()
    return low if low in {"brave", "chrome", "edge", "firefox"} else None


def stop_process_quietly(process: subprocess.Popen) -> None:
    """Alt işlemi temiz şekilde durdurur; gerekirse kill eder."""
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
    except Exception:
        pass


def srt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))

    if millis == 1000:
        secs += 1
        millis = 0

    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def clean_text(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def sanitize_file_base(text: str) -> str:
    """
    Kullanıcının verdiği dosya adı kökünü Windows için güvenli, kısa ve temiz hale getirir.
    Örnek: chart hunter: 2026!* -> chart_hunter_2026
    """
    text = clean_text(text)
    # Windows'un izin vermediği karakterler ve kontrol karakterleri temizlenir.
    text = text.replace("\\", "_")
    text = re.sub(r'[<>:"/|?*]+', "_", text)
    text = "".join(ch if ord(ch) >= 32 else "_" for ch in text)
    # Türkçe karakterler kalsın; emoji, ünlem vb. gereksiz karakterler temizlensin.
    text = re.sub(r"[^\w\s.-]+", "_", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "_", text)
    text = re.sub(r"_+", "_", text)
    text = text.strip(" ._-")
    text = text[:60].strip(" ._-")
    return text or "download"


def parse_named_url_line(line: str) -> tuple[str | None, str | None, str | None]:
    """
    Link kutusundaki tek satırı çözer.

    Desteklenen biçimler:
      chartshunter https://site/video
      chartshunter: https://site/video
      chartshunter - https://site/video
      chartshunter | https://site/video
      https://site/video
      https://stream/site.m3u8 # referer=https://sayfa/video

    Satırda URL'den önce gerçek bir ad varsa bu ad klasör ve dosya adı kökü olur.
    Satırda referer= veya page= varsa, o bilgi FFmpeg/yt-dlp denemelerinde kullanılır.
    """
    original = line.strip()
    if not original:
        return None, None, None
    if original.lower().startswith("her satıra") or original.lower().startswith("her satira"):
        return None, None, None
    if original.startswith("#"):
        return None, None, None

    url_matches = list(re.finditer(r"(?i)\b(?:https?://|www\.)\S+", original))
    if not url_matches:
        return None, None, None

    match = url_matches[0]
    raw_name = original[:match.start()].strip()
    url = match.group(0).strip().rstrip(".,;)]}")
    if url.lower().startswith("www."):
        url = "https://" + url

    referer = None
    ref_match = re.search(r"(?i)\b(?:referer|referrer|ref|page|source)\s*[:=]\s*((?:https?://|www\.)\S+)", original)
    if ref_match:
        referer = ref_match.group(1).strip().rstrip(".,;)]}")
        if referer.lower().startswith("www."):
            referer = "https://" + referer
    elif len(url_matches) >= 2:
        # Eğer satırda ikinci bir URL varsa ve ilki stream linkiyse, ikincisini kaynak sayfa olarak kullanabiliriz.
        second = url_matches[1].group(0).strip().rstrip(".,;)]}")
        if second != url:
            referer = "https://" + second if second.lower().startswith("www.") else second

    # İsim ile link arasındaki ayırıcıları temizle.
    raw_name = re.sub(r"[\s:：|>\-–—_]+$", "", raw_name).strip()

    # Sadece madde işareti / sıra numarasıysa ad kabul etme.
    if re.fullmatch(r"(?:[-*•]|\d+[.)]|\(?\d+\)?|[A-Za-z][.)])", raw_name):
        raw_name = ""

    safe_name = sanitize_file_base(raw_name) if raw_name else None
    return safe_name, url, referer


def line_has_named_url(line: str) -> bool:
    name, url, _referer = parse_named_url_line(line)
    return bool(name and url)


def parse_group_header_line(line: str) -> str | None:
    """
    Link kutusunda URL icermeyen satiri grup/klasor basligi olarak algilar.

    Ornek kullanim:
      chartshunter
      https://site/video1
      https://site/video2

      anothername
      https://site/video3

    Bu durumda ilk iki link chartshunter klasorune, ucuncu link anothername
    klasorune iner.
    """
    text = clean_text(line)
    if not text:
        return None
    if text.lower().startswith("her satıra") or text.lower().startswith("her satira"):
        return None
    if text.startswith("#"):
        return None
    if re.search(r"(?i)\b(?:https?://|www\.)\S+", text):
        return None
    # Sadece ayirici, madde isareti veya numara ise baslik sayma.
    if re.fullmatch(r"[-_*•=.\s]+", text):
        return None
    if re.fullmatch(r"(?:[-*•]|\d+[.)]|\(?\d+\)?|[A-Za-z][.)])", text):
        return None
    return sanitize_file_base(text)


def parse_download_input_grouped(raw_text: str) -> list[dict[str, str | int | None]]:
    """
    Link kutusunu grup mantigiyla okur.

    Desteklenen bicimler:
      https://site/video
      chartshunter https://site/video
      chartshunter:
      https://site/video1
      https://site/video2
      othername
      https://site/video3

    URL'den once ad varsa veya URL'siz bir grup basligi varsa, o andan sonraki
    adsiz linkler yeni baslik gelene kadar ayni klasor/dosya kokunu kullanir.
    """
    items: list[dict[str, str | int | None]] = []
    current_group: str | None = None

    for line_no, line in enumerate(raw_text.splitlines(), start=1):
        raw = line.strip()
        if not raw:
            continue

        name, url, referer = parse_named_url_line(raw)
        if url:
            if name:
                current_group = name
            items.append({
                "name": name or current_group,
                "url": url,
                "referer": referer,
                "line": line_no,
            })
            continue

        header = parse_group_header_line(raw)
        if header:
            current_group = header

    return items



def extract_media_candidates_from_text(text: str, base_url: str | None = None) -> list[str]:
    """
    HTML/JS/HAR metni icinden dogrudan medya veya stream adaylarini cikarir.
    Bu islem koruma asmaz; sadece sayfa kaynaginda gorunen .m3u8/.mpd/.mp4/.webm
    baglantilarini bulmaya calisir.
    """
    if not text:
        return []

    candidates: list[str] = []
    seen: set[str] = set()

    patterns = [
        r"(?i)(?:https?:)?//[^\s'\"<>]+?\.(?:m3u8|mpd|mp4|webm)(?:\?[^\s'\"<>]*)?",
        r"(?i)['\"]([^'\"]+?\.(?:m3u8|mpd|mp4|webm)(?:\?[^'\"]*)?)['\"]",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw = match.group(1) if match.lastindex else match.group(0)
            raw = raw.strip().replace('\\/', '/')
            raw = raw.rstrip('.,;)]}')
            if raw.startswith('//'):
                raw = 'https:' + raw
            if base_url and not re.match(r'(?i)^https?://', raw):
                raw = urljoin(base_url, raw)
            if not re.match(r'(?i)^https?://', raw):
                continue
            low = raw.lower()
            if any(bad in low for bad in ['doubleclick', 'googlesyndication', 'googleads', '/ads?', 'advertis']):
                continue
            if raw not in seen:
                seen.add(raw)
                candidates.append(raw)

    return candidates


def make_stream_line(url: str, referer: str | None = None) -> str:
    """Indirme kutusunun anlayacagi stream + referer satirini uretir."""
    if referer:
        return f"{url} # referer={referer}"
    return url


def stream_candidate_rank(item: tuple[str, str | None]) -> tuple[int, int, str]:
    """Yakalanan medya adaylarını en muhtemel ana stream önce gelecek şekilde sıralar."""
    url = item[0]
    low = url.lower()

    # Segment/parça dosyalarını sona at. Bunlar tek tek video değil, akışın küçük parçalarıdır.
    segment_penalty = 10 if any(tok in low for tok in [".ts?", ".m4s?", "/seg-", "segment", "fragment"]) else 0

    # Master/manifest linkleri genelde en iyi adaydır.
    if ".m3u8" in low or ".mpd" in low:
        if any(tok in low for tok in ["master", "playlist", "manifest", "index"]):
            return (0 + segment_penalty, len(url), low)
        return (1 + segment_penalty, len(url), low)

    # Direkt video dosyaları ikinci güçlü adaydır.
    if any(tok in low for tok in [".mp4", ".webm", ".mkv", ".mov", "videoplayback"]):
        return (2 + segment_penalty, len(url), low)

    return (9 + segment_penalty, len(url), low)


def sort_stream_candidates(captured: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """Yakalanan streamleri tekrarları azaltarak sıralar."""
    seen: set[str] = set()
    result: list[tuple[str, str | None]] = []
    for url, referer in sorted(captured, key=stream_candidate_rank):
        key = url.split("#", 1)[0]
        if key in seen:
            continue
        seen.add(key)
        result.append((url, referer))
    return result


def parse_har_media_candidates(path: Path) -> list[tuple[str, str | None]]:
    """
    Chrome/Edge DevTools HAR dosyasindan medya/manifest adaylarini cikarir.
    Sonuc: [(stream_url, referer), ...]
    """
    data = json.loads(path.read_text(encoding='utf-8', errors='ignore'))
    entries = data.get('log', {}).get('entries', []) if isinstance(data, dict) else []
    results: list[tuple[str, str | None]] = []
    seen: set[str] = set()

    for entry in entries:
        try:
            request = entry.get('request', {}) or {}
            url = str(request.get('url') or '').strip()
            headers = request.get('headers', []) or []
            referer = None
            for h in headers:
                name = str(h.get('name') or '').lower()
                if name in {'referer', 'referrer'}:
                    referer = str(h.get('value') or '').strip() or None
                    break

            response = entry.get('response', {}) or {}
            mime = str(response.get('content', {}).get('mimeType') or '').lower()
            low = url.lower()
            looks_media = (
                any(token in low for token in ['.m3u8', '.mpd', '.mp4', '.webm', 'videoplayback'])
                or any(token in mime for token in ['mpegurl', 'dash+xml', 'mp4', 'webm', 'video/'])
            )
            if looks_media and url and url not in seen:
                seen.add(url)
                results.append((url, referer))

            # Bazen manifest response content icinde saklidir.
            content_text = entry.get('response', {}).get('content', {}).get('text')
            if content_text:
                for candidate in extract_media_candidates_from_text(str(content_text), referer or url):
                    if candidate not in seen:
                        seen.add(candidate)
                        results.append((candidate, referer or url))
        except Exception:
            continue

    return results



def next_number_index(folder: Path, base: str) -> int:
    """
    Verilen klasorde base0001.*, base0002.* gibi dosyalara bakip
    sonraki bos numarayi dondurur.

    Neden gerekli?
    - yt-dlp her linkte %(autonumber) degerini yeniden 1'den baslatabiliyor.
    - Bu da ikinci videoda ayni dosya adina takilip indirmeyi atlamaya sebep olabiliyordu.
    - Bu fonksiyon her yeni linkte mevcut dosyalara bakar ve siradaki numaradan baslatir.
    """
    folder.mkdir(parents=True, exist_ok=True)
    safe_base = sanitize_file_base(base)
    pattern = re.compile(r"^" + re.escape(safe_base) + r"(\d{4,})\.", re.IGNORECASE)
    used = set()
    try:
        for path in folder.iterdir():
            if not path.is_file():
                continue
            m = pattern.match(path.name)
            if m:
                try:
                    used.add(int(m.group(1)))
                except Exception:
                    pass
    except Exception:
        return 1

    i = 1
    while i in used:
        i += 1
    return i

def next_numbered_path(folder: Path, base: str, suffix: str) -> Path:
    """
    chartshunter0001.mp4, chartshunter0002.mp4 gibi boş olan ilk dosya adını bulur.
    Numara seçerken aynı kökteki tüm uzantıları dikkate alır; böylece chartshunter0002.mp3
    varken yeni MP4 yanlışlıkla chartshunter0002.mp4 diye başlamaz.
    """
    folder.mkdir(parents=True, exist_ok=True)
    safe_base = sanitize_file_base(base)
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    i = next_number_index(folder, safe_base)
    for _ in range(1_000_000):
        candidate = folder / f"{safe_base}{i:04d}{suffix}"
        if not candidate.exists():
            return candidate
        i += 1
    raise RuntimeError("Boş dosya adı bulunamadı.")


def quality_to_streamlink(mode: str) -> str:
    """Streamlink kalite yazımını indirici seçiminden üretir."""
    if "2160" in mode or "4K" in mode:
        return "2160p,1440p,1080p,best"
    if "1440" in mode or "2K" in mode:
        return "1440p,1080p,best"
    if "1080" in mode:
        return "1080p,best"
    if "720" in mode:
        return "720p,best"
    if "480" in mode:
        return "480p,best"
    if "360" in mode:
        return "360p,best"
    return "best"


def is_probable_direct_media_url(url: str) -> bool:
    low = url.lower().split("?", 1)[0]
    return low.endswith((".m3u8", ".mpd", ".mp4", ".mkv", ".webm", ".mov", ".mp3", ".m4a", ".wav", ".aac"))


def is_browser_capture_candidate_url(url: str) -> bool:
    """
    Dahili tarayıcı ağ trafiğinden indirilebilir medya/manifest adaylarını ayıklar.

    Bu fonksiyon koruma aşmaz; sadece tarayıcıda zaten oynayan sayfanın çağırdığı
    açık medya bağlantılarını süzer. Reklam/CDN gürültüsünü azaltmaya çalışır.
    """
    if not url:
        return False
    low = url.lower()
    if low.startswith(("blob:", "data:", "about:")):
        return False

    bad_tokens = [
        "doubleclick", "googlesyndication", "googleads", "adservice",
        "/ads?", "/ad/", "advertis", "analytics", "tracking",
        ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp",
        ".css", ".js", ".woff", ".woff2", ".ttf", ".ico",
    ]
    if any(token in low for token in bad_tokens):
        return False

    good_tokens = [
        ".m3u8", ".mpd", ".mp4", ".webm", ".mkv", ".mov",
        ".mp3", ".m4a", ".aac", ".ts?", ".m4s?",
        "videoplayback", "/hls/", "/dash/", "manifest", "playlist",
        "master.m3u8", "index.m3u8", "chunklist", "seg-", "fragment",
    ]
    return any(token in low for token in good_tokens)




def is_adult_video_host_url(url: str) -> bool:
    """
    Yetiskin video hostlarini sadece uyum profilini otomatik acmak icin tanir.
    Bu liste teknik ayar secimi icindir; koruma/DRM asma yapmaz.
    """
    try:
        host = (urlparse(url if re.match(r"(?i)^https?://", url) else "https://" + url).netloc or "").lower()
    except Exception:
        host = (url or "").lower()
    adult_tokens = [
        "pornhub", "thumbzilla", "redtube", "youporn", "tube8",
        "xvideos", "xnxx", "xhamster", "spankbang", "eporner",
        "tnaflix", "motherless", "drtuber", "nuvid", "noodlemagazine",
        "beeg", "thisvid", "gotporn", "pornone", "pornzog",
    ]
    return any(token in host for token in adult_tokens)


def has_adult_video_host_url(items: list[dict]) -> bool:
    for item in items:
        try:
            if is_adult_video_host_url(str(item.get("url") or "")):
                return True
        except Exception:
            pass
    return False

def get_first_url_from_text(text: str) -> str | None:
    """Metin içindeki ilk URL'yi döndürür."""
    m = re.search(r"(?i)\b(?:https?://|www\.)\S+", text or "")
    if not m:
        return None
    url = m.group(0).strip().rstrip(".,;)]}")
    if url.lower().startswith("www."):
        url = "https://" + url
    return url


def python_module_or_exe(module_name: str, exe_name: str) -> list[str]:
    """
    Komut satırı aracı PATH'te varsa onu kullanır; yoksa doğru Python ile modül olarak çalıştırır.

    Kritik düzeltme:
    PyInstaller EXE içinde sys.executable uygulamanın kendisi olur. Bu yüzden
    [sys.executable, '-m', ...] kullanmak uygulamayı her linkte yeniden açabilir.
    """
    exe = shutil.which(exe_name)
    if exe:
        return [exe]
    return python_module_command(module_name)


def quote_concat_path(path: Path) -> str:
    # FFmpeg concat listesi icin Windows yollarini guvenli yazar.
    safe = str(path.resolve()).replace("\\", "/").replace("'", "'\\''")
    return f"file '{safe}'"


def run_ffmpeg(args: list[str], cancel_event: threading.Event | None = None) -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg bulunamadi. Once 'winget install Gyan.FFmpeg' komutuyla kurmalisin.")

    process = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        **subprocess_hidden_kwargs(),
    )

    output_lines: list[str] = []

    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise UserCancelled("İşlem kullanıcı tarafından iptal edildi.")

            line = process.stdout.readline() if process.stdout is not None else ""
            if line:
                clean_line = line.strip()
                output_lines.append(clean_line)
                if is_fatal_download_error_text(clean_line):
                    stop_process_quietly(process)
                    raise FatalDownloadError(clean_line)
            elif process.poll() is not None:
                break
            else:
                time.sleep(0.1)

        if process.returncode != 0:
            raise RuntimeError("\n".join(output_lines[-120:]))
    finally:
        if process.poll() is None and cancel_event is not None and cancel_event.is_set():
            process.terminate()


def get_media_duration_seconds(path: Path) -> float:
    """
    FFprobe ile ses/video suresini saniye olarak okur.
    Yuzde ilerleme gostermek icin kullanilir.
    FFprobe bulunamazsa 0 doner; islem yine devam eder ama yuzde daha sinirli gosterilir.
    """
    if shutil.which("ffprobe") is None:
        return 0.0

    try:
        process = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore",
            **subprocess_hidden_kwargs(),
        )

        if process.returncode != 0:
            return 0.0

        return max(0.0, float(process.stdout.strip()))
    except Exception:
        return 0.0


def run_ffmpeg_with_progress(
    args: list[str],
    total_duration: float,
    progress_callback=None,
    cancel_event: threading.Event | None = None,
) -> None:
    """
    FFmpeg islemlerinde yuzdesel ilerleme okumaya calisir.
    total_duration biliniyorsa -progress pipe:1 ciktisindaki out_time_ms degeriyle yuzde hesaplar.
    cancel_event set edilirse FFmpeg islemini durdurur.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("FFmpeg bulunamadi. Once 'winget install Gyan.FFmpeg' komutuyla kurmalisin.")

    progress_args = ["ffmpeg", "-y", "-nostats", "-progress", "pipe:1"] + args[2:]

    process = subprocess.Popen(
        progress_args,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1,
        **subprocess_hidden_kwargs(),
    )

    output_lines: list[str] = []

    assert process.stdout is not None
    try:
        for line in process.stdout:
            if cancel_event is not None and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise UserCancelled("İşlem kullanıcı tarafından iptal edildi.")

            line = line.strip()
            if line:
                output_lines.append(line)
                if is_fatal_download_error_text(line):
                    stop_process_quietly(process)
                    raise FatalDownloadError(line)

            if total_duration > 0 and line.startswith("out_time_ms="):
                try:
                    out_ms = int(line.split("=", 1)[1])
                    current_seconds = out_ms / 1_000_000
                    percent = min(99.0, max(0.0, current_seconds / total_duration * 100))
                    if progress_callback:
                        progress_callback(percent, current_seconds)
                except Exception:
                    pass

        returncode = process.wait()
        if returncode != 0:
            raise RuntimeError("\n".join(output_lines[-120:]))
    finally:
        if process.poll() is None and cancel_event is not None and cancel_event.is_set():
            process.terminate()


# ============================================================
# SRT PARSE / GRUPLAMA
# ============================================================

def srt_time_to_seconds(time_text: str) -> float:
    h, m, rest = time_text.strip().split(":")
    s, ms = rest.split(",")
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def parse_srt_entries(content: str) -> list[dict]:
    entries: list[dict] = []
    blocks = re.split(r"\n\s*\n", content.strip())

    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) < 2:
            continue

        time_line = None
        text_lines = []

        for line in lines:
            if "-->" in line:
                time_line = line
            elif not line.isdigit():
                text_lines.append(line)

        if not time_line:
            continue

        try:
            start_text, end_text = [x.strip() for x in time_line.split("-->")]
            start_seconds = srt_time_to_seconds(start_text)
            end_seconds = srt_time_to_seconds(end_text)
            text = clean_text(" ".join(text_lines))

            if text:
                entries.append({"start": start_seconds, "end": end_seconds, "text": text})
        except Exception:
            continue

    return entries


def group_srt_entries_by_time(entries: list[dict], chunk_seconds: int) -> list[dict]:
    chunks: list[dict] = []
    current_texts: list[str] = []
    current_chunk_start = 0
    current_chunk_index = 1

    for entry in entries:
        entry_start = entry["start"]

        if entry_start >= current_chunk_start + chunk_seconds and current_texts:
            chunks.append({
                "index": current_chunk_index,
                "source_start": current_chunk_start,
                "source_end": current_chunk_start + chunk_seconds,
                "text": clean_text(" ".join(current_texts)),
            })
            current_chunk_index += 1
            current_chunk_start += chunk_seconds
            current_texts = []

            while entry_start >= current_chunk_start + chunk_seconds:
                current_chunk_start += chunk_seconds
                current_chunk_index += 1

        current_texts.append(entry["text"])

    if current_texts:
        chunks.append({
            "index": current_chunk_index,
            "source_start": current_chunk_start,
            "source_end": current_chunk_start + chunk_seconds,
            "text": clean_text(" ".join(current_texts)),
        })

    return chunks


def split_text_by_sentences(text: str, max_chars: int = 3500) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if len(sentence) > max_chars:
            # Cok uzun cumle varsa kaba bolmekten cekinme; yoksa TTS patlayabilir.
            for i in range(0, len(sentence), max_chars):
                part = sentence[i:i + max_chars].strip()
                if part:
                    if current.strip():
                        chunks.append(clean_text(current))
                        current = ""
                    chunks.append(part)
            continue

        if len(current) + len(sentence) + 1 <= max_chars:
            current += " " + sentence
        else:
            if current.strip():
                chunks.append(clean_text(current))
            current = sentence

    if current.strip():
        chunks.append(clean_text(current))

    return chunks


# ============================================================
# GUI APP
# ============================================================

class App(tk.Tk):
    def __init__(self) -> None:
        activate_shared_site_packages()
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1220x790")
        self.minsize(900, 590)
        self._configure_style()

        self.current_thread: threading.Thread | None = None
        self.cancel_event = threading.Event()
        # Bileşen hazırlıkları tekilleştirilir. Açılışta hiçbir büyük paket/model kurulmaz.
        self._component_install_lock = threading.RLock()
        self._session_component_prompts: set[str] = set()
        self._session_model_prompts: set[str] = set()
        self._update_catalog: dict = {}
        self._update_check_thread: threading.Thread | None = None
        self._build_ui()
        self.after(250, self._startup_light_validation)
        # İlk oturumda yalnızca çevrimiçi sürüm METADATA'sı kontrol edilir.
        # Kurulum/güncelleme yok; seçenek ilgili özellik ilk kullanıldığında çıkar.
        self.after(1400, self._start_first_session_update_check)

    def _configure_style(self) -> None:
        """Bağımlılık eklemeden daha modern, temiz ve kompakt Windows görünümü."""
        self._ui = {
            "bg": "#F4F7FB",
            "card": "#FFFFFF",
            "text": "#172033",
            "muted": "#667085",
            "accent": "#2563EB",
            "accent_hover": "#1D4ED8",
            "border": "#DCE3ED",
            "ok": "#15803D",
            "warning": "#B45309",
            "danger": "#B42318",
            "log_bg": "#101827",
            "log_fg": "#DCE7F7",
        }
        self.configure(bg=self._ui["bg"])
        self.option_add("*Font", "{Segoe UI} 9")

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        bg, card, text, muted = self._ui["bg"], self._ui["card"], self._ui["text"], self._ui["muted"]
        accent, border = self._ui["accent"], self._ui["border"]
        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=card)
        style.configure("Header.TFrame", background=card)
        style.configure("TLabel", background=bg, foreground=text, font=("Segoe UI", 9))
        style.configure("Card.TLabel", background=card, foreground=text, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=card, foreground=text, font=("Segoe UI Semibold", 18))
        style.configure("Subtitle.TLabel", background=card, foreground=muted, font=("Segoe UI", 9))
        style.configure("Status.TLabel", background=card, foreground=self._ui["ok"], font=("Segoe UI Semibold", 9))
        style.configure("Update.TLabel", background=card, foreground=muted, font=("Segoe UI", 8))
        style.configure("TButton", font=("Segoe UI", 9), padding=(9, 5), relief="flat")
        style.map("TButton", background=[("active", "#E9EEF7")])
        style.configure("Accent.TButton", font=("Segoe UI Semibold", 9), padding=(12, 7), foreground="white", background=accent, bordercolor=accent)
        style.map("Accent.TButton", background=[("active", self._ui["accent_hover"]), ("pressed", self._ui["accent_hover"])], foreground=[("disabled", "#E5E7EB")])
        style.configure("Danger.TButton", font=("Segoe UI Semibold", 9), padding=(10, 6), foreground=self._ui["danger"], background="#FEE4E2", bordercolor="#FECDCA")
        style.map("Danger.TButton", background=[("active", "#FECDCA")])
        style.configure("TEntry", padding=5, fieldbackground=card, bordercolor=border, lightcolor=border, darkcolor=border)
        style.configure("TCombobox", padding=5, fieldbackground=card, bordercolor=border, arrowcolor=muted)
        style.configure("TCheckbutton", background=bg, foreground=text, padding=(2, 2))
        style.configure("TLabelframe", background=card, bordercolor=border, relief="solid", borderwidth=1)
        style.configure("TLabelframe.Label", background=card, foreground=text, font=("Segoe UI Semibold", 9))
        style.configure("Section.TLabelframe", background=card, bordercolor=border, relief="solid", borderwidth=1)
        style.configure("Section.TLabelframe.Label", background=card, foreground=text, font=("Segoe UI Semibold", 9))
        style.configure("TNotebook", background=bg, borderwidth=0, tabmargins=(2, 6, 2, 0))
        style.configure("TNotebook.Tab", font=("Segoe UI Semibold", 9), padding=(13, 7), background="#EAF0F8", foreground=muted, borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", card), ("active", "#F7F9FC")], foreground=[("selected", accent), ("active", text)])
        style.configure("Horizontal.TProgressbar", troughcolor="#E8EEF6", background=accent, bordercolor="#E8EEF6", lightcolor=accent, darkcolor=accent)
    def _make_scrollable_tab(self, outer: ttk.Frame) -> ttk.Frame:
        """Sekme içeriği küçük ekranda taşarsa sağdan kaydırılabilir alan oluşturur."""
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        inner = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=inner, anchor="nw")

        def _on_inner_configure(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_configure(event) -> None:
            canvas.itemconfigure(window_id, width=event.width)

        def _on_mousewheel(event) -> None:
            # Windows: event.delta 120'lik adımlarla gelir.
            if event.delta:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _bind_mousewheel(_event=None) -> None:
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(_event=None) -> None:
            canvas.unbind_all("<MouseWheel>")

        inner.bind("<Configure>", _on_inner_configure)
        canvas.bind("<Configure>", _on_canvas_configure)
        outer.bind("<Enter>", _bind_mousewheel)
        outer.bind("<Leave>", _unbind_mousewheel)

        return inner

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        header = ttk.Frame(self, style="Header.TFrame", padding=(16, 12))
        header.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        header.columnconfigure(0, weight=1)

        ttk.Label(header, text=APP_NAME, style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="İndir → altyazı çıkar → UK ses üret → MP3 birleştir → YouTube MP4 hazırla",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(1, 0))

        # Kullanıcı uygulamanın gerçekten hazır olup olmadığını açılışta anında görsün.
        self.health_text = tk.StringVar(value="Başlangıç kontrolü yapılıyor…")
        self.update_text = tk.StringVar(value="Güncelleme verileri: ilk oturumda kontrol edilecek")
        ttk.Label(header, textvariable=self.health_text, style="Status.TLabel").grid(
            row=0, column=1, sticky="e", padx=(18, 0)
        )
        ttk.Label(header, textvariable=self.update_text, style="Update.TLabel").grid(
            row=1, column=1, sticky="e", padx=(18, 0), pady=(2, 0)
        )

        # Ana ekran iki parçalıdır: üstte sekmeler, altta ilerleme + işlem geçmişi.
        # Aradaki çizgiyi fareyle yukarı/aşağı sürükleyebilirsin.
        self.main_pane = ttk.PanedWindow(self, orient=tk.VERTICAL)
        self.main_pane.grid(row=1, column=0, sticky="nsew", padx=10, pady=(5, 8))

        self.top_area = ttk.Frame(self.main_pane)
        self.bottom_area = ttk.Frame(self.main_pane)
        self.top_area.columnconfigure(0, weight=1)
        self.top_area.rowconfigure(0, weight=1)
        self.bottom_area.columnconfigure(0, weight=1)
        self.bottom_area.rowconfigure(1, weight=1)

        self.notebook = ttk.Notebook(self.top_area)
        self.notebook.grid(row=0, column=0, sticky="nsew")

        # Her sekme kaydırılabilir yapıldı. Küçük ekranda alan yetmezse mouse tekerleğiyle aşağı inebilirsin.
        self.tab_download_outer = ttk.Frame(self.notebook)
        self.tab_transcribe_outer = ttk.Frame(self.notebook)
        self.tab_tts_outer = ttk.Frame(self.notebook)
        self.tab_merge_outer = ttk.Frame(self.notebook)
        self.tab_video_outer = ttk.Frame(self.notebook)
        self.tab_check_outer = ttk.Frame(self.notebook)

        self.tab_download = self._make_scrollable_tab(self.tab_download_outer)
        self.tab_transcribe = self._make_scrollable_tab(self.tab_transcribe_outer)
        self.tab_tts = self._make_scrollable_tab(self.tab_tts_outer)
        self.tab_merge = self._make_scrollable_tab(self.tab_merge_outer)
        self.tab_video = self._make_scrollable_tab(self.tab_video_outer)
        self.tab_check = self._make_scrollable_tab(self.tab_check_outer)

        self.notebook.add(self.tab_download_outer, text="0  İndir")
        self.notebook.add(self.tab_transcribe_outer, text="1  Altyazı")
        self.notebook.add(self.tab_tts_outer, text="2  UK Ses")
        self.notebook.add(self.tab_merge_outer, text="3  MP3 Birleştir")
        self.notebook.add(self.tab_video_outer, text="4  Video Oluştur")
        self.notebook.add(self.tab_check_outer, text="Kontrol")

        self._build_download_tab()
        self._build_transcribe_tab()
        self._build_tts_tab()
        self._build_merge_tab()
        self._build_video_tab()
        self._build_check_tab()

        bottom_top = ttk.Frame(self.bottom_area)
        bottom_top.grid(row=0, column=0, sticky="ew")
        bottom_top.columnconfigure(0, weight=1)

        progress_frame = ttk.LabelFrame(bottom_top, text="İlerleme / hız", style="Section.TLabelframe")
        progress_frame.grid(row=0, column=0, sticky="ew", padx=0, pady=(0, 6))
        progress_frame.columnconfigure(0, weight=1)

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_text = tk.StringVar(value="Hazır - %0")
        self.download_speed_text = tk.StringVar(value="İndirme hızı: -")
        self.batch_progress_text = tk.StringVar(value="Video: -")

        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=100,
            mode="determinate"
        )
        self.progress_bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(7, 3))
        ttk.Button(
            progress_frame,
            text="İptal Et / Durdur",
            command=self.request_cancel,
            style="Danger.TButton"
        ).grid(row=0, column=1, sticky="e", padx=8, pady=(7, 3))

        ttk.Label(
            progress_frame,
            textvariable=self.batch_progress_text,
            font=("Segoe UI Semibold", 10),
        ).grid(row=1, column=0, sticky="w", padx=8, pady=(2, 2))
        ttk.Label(progress_frame, textvariable=self.download_speed_text).grid(row=1, column=1, sticky="e", padx=8, pady=(2, 2))
        ttk.Label(progress_frame, textvariable=self.progress_text).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 6))

        log_frame = ttk.LabelFrame(self.bottom_area, text="İşlem geçmişi - alt paneli yukarı/aşağı sürükleyebilirsin", style="Section.TLabelframe")
        log_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=(0, 0))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_box = ScrolledText(
            log_frame, height=8, font=("Cascadia Mono", 8), wrap="word",
            bg=self._ui["log_bg"], fg=self._ui["log_fg"], insertbackground="white",
            relief="flat", borderwidth=0, padx=8, pady=6
        )
        self.log_box.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

        self.main_pane.add(self.top_area, weight=4)
        self.main_pane.add(self.bottom_area, weight=2)

        # Açılışta alt paneli görünür bırak. Ekran küçükse kullanıcı çizgiyi sürükleyebilir.
        self.after(500, self._set_initial_pane_position)

        self._last_setup_status = None
        self.log("Hazır. v40: açılışta yalnızca hafif doğrulama ve sürüm bilgisi kontrolü yapılır; hiçbir büyük bileşen kurulmaz.")
        self.log(f"Whisper ortak cache: {whisper_cache_dir()}")
        self.after(700, self._poll_setup_status)
        self.log("Alt işlem geçmişi panelini büyütmek/küçültmek için sekmelerle geçmiş arasındaki çizgiyi sürükleyebilirsin.")

    def show_toast(self, title: str, message: str, kind: str = "info", duration_ms: int = 4200) -> None:
        """Ana pencereyi bloke etmeyen küçük bildirim. Worker thread'lerden güvenle çağrılabilir."""
        def _show() -> None:
            try:
                toast = tk.Toplevel(self)
                toast.title(title)
                toast.resizable(False, False)
                toast.attributes("-topmost", True)
                frame = ttk.Frame(toast, padding=10)
                frame.grid(row=0, column=0, sticky="nsew")
                prefix = {"ok": "✓", "warning": "!", "error": "×"}.get(kind, "i")
                ttk.Label(frame, text=f"{prefix}  {title}", font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
                ttk.Label(frame, text=message, wraplength=360, justify="left").grid(row=1, column=0, sticky="w", pady=(5, 0))
                toast.update_idletasks()
                x = self.winfo_rootx() + max(10, self.winfo_width() - toast.winfo_width() - 22)
                y = self.winfo_rooty() + 52
                toast.geometry(f"+{x}+{y}")
                toast.after(max(1800, int(duration_ms)), toast.destroy)
            except Exception:
                pass
        try:
            self.after(0, _show)
        except Exception:
            pass

    def _startup_light_validation(self) -> None:
        """Açılışı yavaşlatmadan kritik yerel koşulları doğrular; paket indirme veya ağ isteği yapmaz."""
        issues: list[str] = []
        notes: list[str] = []
        try:
            if sys.version_info < (3, 10):
                issues.append(f"Python {sys.version_info.major}.{sys.version_info.minor} eski")
            else:
                notes.append(f"Python {sys.version_info.major}.{sys.version_info.minor}")
            data = user_data_dir()
            probe = data / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            notes.append("cache yazılabilir")
            py = shared_runtime_python()
            notes.append("ortak runtime hazır" if py.exists() else "runtime gerektiğinde hazırlanacak")
        except Exception as e:
            issues.append(str(e))

        if issues:
            self.health_text.set("⚠ Başlangıç kontrolü: dikkat")
            self.log("Başlangıç doğrulaması uyarı verdi: " + " | ".join(issues))
            self.show_toast("Başlangıç kontrolü", " • ".join(issues), "warning", 6000)
        else:
            self.health_text.set("✓ Hazır • ağır bileşen yüklenmedi")
            self.log("Hızlı başlangıç doğrulaması tamam: " + " | ".join(notes))

    def _load_update_catalog(self) -> dict:
        try:
            path = update_catalog_file()
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            return {}

    def _save_update_catalog(self, data: dict) -> None:
        try:
            path = update_catalog_file()
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass

    def _installed_distribution_version(self, package: str) -> str:
        try:
            activate_shared_site_packages()
            return str(importlib_metadata.version(package))
        except Exception:
            return ""

    def _fetch_json_light(self, url: str, timeout: float = 4.0) -> dict:
        req = Request(url, headers={"User-Agent": f"{APP_NAME}/update-check"})
        with urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", errors="replace"))

    def _start_first_session_update_check(self, force: bool = False) -> None:
        """İlk oturumda sadece güncelleme metadata'sını kontrol eder; kurulum/güncelleme yapmaz."""
        if self._update_check_thread and self._update_check_thread.is_alive():
            return
        cached = self._load_update_catalog()
        if not force and cached.get("app_version") == APP_VERSION and cached.get("checked_at"):
            self._update_catalog = cached
            count = sum(1 for x in (cached.get("packages") or {}).values() if isinstance(x, dict) and x.get("update_available"))
            model_count = sum(1 for x in (cached.get("models") or {}).values() if isinstance(x, dict) and x.get("update_available"))
            total = count + model_count
            self.update_text.set(f"Güncelleme verileri hazır • {total} seçenek" if total else "Güncelleme verileri hazır • mevcutlar güncel")
            return

        def _worker() -> None:
            try:
                self.after(0, lambda: self.update_text.set("Güncelleme verileri kontrol ediliyor…"))
                self.log("İlk oturum güncelleme kontrolü: yalnızca sürüm bilgileri okunuyor; hiçbir şey kurulmayacak.")
                packages: dict[str, dict] = {}
                for key, pkg in UPDATE_PACKAGE_MAP.items():
                    item = {"package": pkg, "installed": self._installed_distribution_version(pkg), "latest": "", "update_available": False}
                    try:
                        data = self._fetch_json_light(f"https://pypi.org/pypi/{pkg}/json", timeout=4.0)
                        item["latest"] = str((data.get("info") or {}).get("version") or "")
                        if item["installed"] and item["latest"] and item["installed"] != item["latest"]:
                            item["update_available"] = True
                    except Exception as e:
                        item["error"] = str(e)[:180]
                    packages[key] = item

                # Sadece daha önce kullanılmış/cached Whisper modellerinin revision verisi okunur.
                models: dict[str, dict] = {}
                lazy = self._load_lazy_component_state()
                cached_models = lazy.get("whisper_models", {}) if isinstance(lazy.get("whisper_models"), dict) else {}
                for model_size, info in cached_models.items():
                    if not isinstance(info, dict):
                        continue
                    repo = WHISPER_REPOS.get(model_size)
                    if not repo:
                        continue
                    local_rev = str(info.get("revision") or "")
                    item = {"repo": repo, "local_revision": local_rev, "remote_revision": "", "update_available": False}
                    try:
                        data = self._fetch_json_light(f"https://huggingface.co/api/models/{repo}", timeout=4.0)
                        remote = str(data.get("sha") or "")
                        item["remote_revision"] = remote
                        item["update_available"] = bool(local_rev and remote and local_rev != remote)
                    except Exception as e:
                        item["error"] = str(e)[:180]
                    models[model_size] = item

                catalog = {"app_version": APP_VERSION, "checked_at": time.time(), "packages": packages, "models": models}
                self._save_update_catalog(catalog)
                self._update_catalog = catalog
                updates = [x for x in packages.values() if x.get("update_available")]
                updates += [x for x in models.values() if x.get("update_available")]
                if updates:
                    self.after(0, lambda n=len(updates): self.update_text.set(f"Güncelleme verileri hazır • {n} seçenek kullanımda sorulacak"))
                    self.log(f"Güncelleme metadata kontrolü tamamlandı: {len(updates)} güncelleme seçeneği bulundu. Otomatik güncelleme yapılmadı.")
                else:
                    self.after(0, lambda: self.update_text.set("Güncelleme verileri hazır • otomatik işlem yok"))
                    self.log("Güncelleme metadata kontrolü tamamlandı. Otomatik kurulum/güncelleme yapılmadı.")
            except Exception as e:
                self.log(f"Güncelleme verileri kontrol edilemedi: {e}")
                self.after(0, lambda: self.update_text.set("Güncelleme verileri: çevrimdışı / sonra denenebilir"))

        self._update_check_thread = threading.Thread(target=_worker, name="update-metadata-check", daemon=True)
        self._update_check_thread.start()

    def _ask_yes_no_threadsafe(self, title: str, message: str, default: bool = True) -> bool:
        """Worker thread'den güvenli biçimde kullanıcı seçimi alır."""
        if threading.current_thread() is threading.main_thread():
            try:
                return bool(messagebox.askyesno(title, message, default=(messagebox.YES if default else messagebox.NO)))
            except Exception:
                return default
        event = threading.Event()
        result = {"value": default}
        def _ask() -> None:
            try:
                result["value"] = bool(messagebox.askyesno(title, message, default=(messagebox.YES if default else messagebox.NO)))
            except Exception:
                result["value"] = default
            finally:
                event.set()
        self.after(0, _ask)
        event.wait()
        return bool(result["value"])

    def _package_update_info(self, key: str) -> dict:
        catalog = self._update_catalog or self._load_update_catalog()
        packages = catalog.get("packages", {}) if isinstance(catalog.get("packages"), dict) else {}
        return packages.get(key, {}) if isinstance(packages.get(key), dict) else {}

    def _set_initial_pane_position(self) -> None:
        try:
            h = max(650, self.winfo_height())
            self.main_pane.sashpos(0, int(h * 0.63))
        except Exception:
            pass

    def _poll_setup_status(self) -> None:
        """İlk kurulum/güncelleme arka planda sürüyorsa kullanıcıya canlı durum gösterir."""
        try:
            path = setup_status_file()
            if path.exists():
                data = json.loads(path.read_text(encoding="utf-8"))
                status = str(data.get("status") or "")
                detail = str(data.get("detail") or "")
                pct = float(data.get("percent") or 0)
                running = bool(data.get("running"))
                token = (status, detail, int(pct), running)
                if token != self._last_setup_status:
                    self._last_setup_status = token
                    if running:
                        # Kullanıcı aktif bir işlem başlatmadıysa üst ilerleme alanında kurulum durumunu göster.
                        if not (self.current_thread and self.current_thread.is_alive()):
                            self.set_progress(pct, f"Hazırlık: {status}")
                            self.set_download_speed(detail or "arka planda")
                        self.log(f"Arka plan hazırlığı: {status}" + (f" | {detail}" if detail else ""))
                    else:
                        if status:
                            self.log(f"Sistem durumu: {status}" + (f" | {detail}" if detail else ""))
                            if not (self.current_thread and self.current_thread.is_alive()):
                                self.set_progress(100, status)
                                self.set_download_speed("-")
        except Exception:
            pass
        self.after(1500, self._poll_setup_status)

    def log(self, message: str) -> None:
        def _append() -> None:
            self.log_box.insert("end", f"[{now_text()}] {message}\n")
            self.log_box.see("end")
        self.after(0, _append)

    def set_progress(self, percent: float, text: str | None = None) -> None:
        """
        Ustteki yuzde cubugunu guvenli sekilde gunceller.
        Thread icinden cagrilabilir; arayuz guncellemesi after ile ana threade aktarilir.
        """
        percent = max(0.0, min(100.0, float(percent)))

        def _update() -> None:
            self.progress_var.set(percent)
            if text is None:
                self.progress_text.set(f"%{percent:.1f}")
            else:
                self.progress_text.set(f"{text} - %{percent:.1f}")

        self.after(0, _update)

    def set_download_speed(self, text: str | None = None) -> None:
        """İndirme hızını ilerleme bölümünün altında/yanında gösterir."""
        display = text or "-"

        def _update() -> None:
            self.download_speed_text.set(f"İndirme hızı: {display}")

        self.after(0, _update)

    def set_batch_progress(self, current: int | None = None, total: int | None = None, label: str | None = None) -> None:
        """Çoklu indirmede hangi videonun işlendiğini ayrı ve belirgin gösterir."""
        def _update() -> None:
            if current and total:
                text = f"Video {current}/{total}"
                if label:
                    text += f" • {label}"
                self.batch_progress_text.set(text)
            else:
                self.batch_progress_text.set("Video: -")
        self.after(0, _update)

    def request_cancel(self) -> None:
        if self.current_thread and self.current_thread.is_alive():
            self.cancel_event.set()
            self.log("İptal isteği alındı. Devam eden adım güvenli noktada durdurulacak.")
            self.set_progress(self.progress_var.get(), "İptal ediliyor")
        else:
            self.log("İptal edilecek aktif işlem yok.")

    def is_cancelled(self) -> bool:
        return self.cancel_event.is_set()

    def _load_lazy_component_state(self) -> dict:
        path = lazy_component_state_file()
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            return {}

    def _save_lazy_component_state(self, data: dict) -> None:
        try:
            path = lazy_component_state_file()
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(path)
        except Exception:
            pass

    def _module_available(self, module_name: str) -> bool:
        try:
            importlib.invalidate_caches()
            return importlib.util.find_spec(module_name) is not None
        except Exception:
            return False

    def _base_console_python(self) -> str:
        exe = Path(sys.executable)
        if os.name == "nt" and exe.name.lower() == "pythonw.exe":
            console = exe.with_name("python.exe")
            if console.exists():
                return str(console)
        return str(exe)

    def _ensure_shared_runtime(self) -> bool:
        """Ortak runtime hazırlığını tekilleştirir; paralel warm-up/ilk tıklama çakışmaz."""
        with self._component_install_lock:
            return self._ensure_shared_runtime_locked()

    def _ensure_shared_runtime_locked(self) -> bool:
        """İlk isteğe bağlı özellik kullanılınca ortak venv oluşturur."""
        py = shared_runtime_python()
        if py.exists():
            activate_shared_site_packages()
            return True
        try:
            self.log("İlk özellik kullanımı: ortak çalışma ortamı bir kez oluşturuluyor...")
            self.set_progress(2, "İlk kullanım hazırlığı")
            shared_runtime_venv_dir().parent.mkdir(parents=True, exist_ok=True)
            proc = subprocess.run(
                [self._base_console_python(), "-m", "venv", str(shared_runtime_venv_dir())],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                **subprocess_hidden_kwargs(),
            )
            if proc.returncode != 0 or not py.exists():
                self.log("Çalışma ortamı oluşturulamadı: " + (proc.stdout or "")[-800:])
                return False
            activate_shared_site_packages()
            self.log("Ortak çalışma ortamı hazır. Sonraki açılışlarda bu adım tekrarlanmaz.")
            return True
        except Exception as e:
            self.log(f"Çalışma ortamı hazırlama hatası: {e}")
            return False

    def _ensure_python_component(self, key: str, label: str, packages: list[str], imports: list[str], *, weekly_update: bool = True) -> bool:
        """Bileşeni yalnızca kullanıldığı anda hazırlar; update varsa seçim kullanıcıya bırakılır."""
        with self._component_install_lock:
            return self._ensure_python_component_locked(key, label, packages, imports, weekly_update=weekly_update)

    def _ensure_python_component_locked(self, key: str, label: str, packages: list[str], imports: list[str], *, weekly_update: bool = True) -> bool:
        activate_shared_site_packages()
        installed = all(self._module_available(name) for name in imports)
        update_info = self._package_update_info(key)

        if installed:
            # Açılışta bulunan metadata yalnızca burada, bileşen gerçekten kullanılacağı zaman sunulur.
            if update_info.get("update_available") and key not in self._session_component_prompts:
                self._session_component_prompts.add(key)
                current = str(update_info.get("installed") or "mevcut")
                latest = str(update_info.get("latest") or "yeni")
                do_update = self._ask_yes_no_threadsafe(
                    f"{label} güncellemesi",
                    f"{label} için yeni sürüm bilgisi bulundu.\n\nMevcut: {current}\nYeni: {latest}\n\nŞimdi güncelle ve devam et?\nHayır dersen mevcut sürümle devam edilir.",
                    default=False,
                )
                if do_update:
                    if not self._ensure_shared_runtime():
                        return False
                    self.log(f"{label}: kullanıcı güncellemeyi seçti ({current} → {latest}).")
                    self.set_progress(4, f"{label} güncelleniyor")
                    cmd = [str(shared_runtime_python()), "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary", "--upgrade", "--upgrade-strategy", "only-if-needed", *packages]
                    ok, out = self._run_simple_command_with_log(cmd, log_prefix=f"guncelle:{key}")
                    if not ok:
                        self.log(f"{label} güncellenemedi; mevcut sürümle devam denenecek: {(out or '')[-700:]}")
                        self.show_toast("Güncelleme başarısız", f"{label} güncellenemedi. Mevcut sürüm korunuyor.", "warning", 6000)
                    else:
                        activate_shared_site_packages(); importlib.invalidate_caches()
                        self.show_toast("Güncelleme tamamlandı", f"{label} güncellendi.", "ok", 3500)
                else:
                    self.log(f"{label}: güncelleme ertelendi; mevcut sürüm kullanılacak.")
            return True

        # Kurulu değilse o özellik ilk kez kullanılacağı anda seçenek göster.
        prompt_key = f"install:{key}"
        if prompt_key not in self._session_component_prompts:
            self._session_component_prompts.add(prompt_key)
            if not self._ask_yes_no_threadsafe(
                f"{label} gerekiyor",
                f"Bu özellik için {label} henüz kurulu değil.\n\nŞimdi hazırlansın mı?\nYalnızca ortak runtime/cache'e kurulur ve sonraki kullanımlarda tekrar indirilmez.",
                default=True,
            ):
                self.log(f"{label}: kullanıcı kurulumu şimdilik erteledi.")
                self.show_toast("İşlem ertelendi", f"{label} kurulmadığı için bu işlem başlatılmadı.", "info", 4500)
                return False

        if not self._ensure_shared_runtime():
            return False
        self.log(f"{label}: ilk kullanım kurulumu başlıyor.")
        self.set_progress(4, f"{label} hazırlanıyor")
        self.show_toast("İlk kullanım hazırlığı", f"{label} şimdi kuruluyor. Bu kurulum bir kez yapılır.", "info", 6500)
        cmd = [str(shared_runtime_python()), "-m", "pip", "install", "--disable-pip-version-check", "--prefer-binary", *packages]
        ok, out = self._run_simple_command_with_log(cmd, log_prefix=f"paket:{key}")
        if not ok:
            self.log(f"{label} hazırlanamadı: {(out or '')[-800:]}")
            self.show_toast("Bileşen hazırlanamadı", f"{label} kurulamadı. İşlem geçmişindeki hata ayrıntısına bak.", "error", 7000)
            return False
        activate_shared_site_packages(); importlib.invalidate_caches()
        installed = all(self._module_available(name) for name in imports)
        if not installed:
            self.log(f"{label} kuruldu ama mevcut oturum paketi göremedi. Uygulamayı bir kez kapatıp açmak gerekebilir.")
            return False
        state = self._load_lazy_component_state()
        state[key] = {"checked_at": time.time(), "packages": packages}
        self._save_lazy_component_state(state)
        self.log(f"{label} hazır ve doğrulandı.")
        self.show_toast("Bileşen hazır", f"{label} kullanıma hazır.", "ok", 3500)
        return True

    def _refresh_windows_path(self) -> None:
        if os.name != "nt":
            return
        try:
            import winreg
            paths = []
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                    if val:
                        paths.append(str(val))
            except Exception:
                pass
            try:
                key = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                    val, _ = winreg.QueryValueEx(k, "Path")
                    if val:
                        paths.append(str(val))
            except Exception:
                pass
            current = os.environ.get("PATH", "")
            os.environ["PATH"] = ";".join(paths + [current])
        except Exception:
            pass

    def _ensure_system_tool(self, exe_name: str, winget_id: str, label: str, *, required: bool = True) -> bool:
        if shutil.which(exe_name):
            return True
        if os.name != "nt" or not shutil.which("winget"):
            self.log(f"{label} bulunamadı. Otomatik kurulum için winget gerekli.")
            return not required
        if not self._ask_yes_no_threadsafe(
            f"{label} gerekiyor",
            f"Bu işlem için {label} gerekli fakat bilgisayarda bulunamadı.\n\nWinget ile şimdi kurulsun mu?",
            default=True,
        ):
            self.log(f"{label}: kullanıcı kurulumu erteledi.")
            return not required
        self.log(f"{label} bu işlem için gerekli; kullanıcı onayıyla kuruluyor...")
        self.set_progress(3, f"{label} kuruluyor")
        self.show_toast("Sistem aracı hazırlanıyor", f"{label} kuruluyor. Sonraki kullanımlarda tekrar kurulmaz.", "info", 6500)
        args = [
            "winget", "install", "--id", winget_id, "-e", "--silent",
            "--accept-package-agreements", "--accept-source-agreements",
        ]
        ok, out = self._run_simple_command_with_log(args, log_prefix=f"sistem:{exe_name}")
        self._refresh_windows_path()
        if shutil.which(exe_name):
            self.log(f"{label} hazır.")
            return True
        if not ok:
            self.log(f"{label} otomatik kurulamadı: {(out or '')[-600:]}")
        else:
            self.log(f"{label} kuruldu fakat PATH bu oturumda yenilenemedi; uygulamayı bir kez yeniden açmak gerekebilir.")
        return not required

    def _ensure_whisper_model(self, model_size: str) -> str | None:
        """Modeli sadece gerektiğinde indirir; açılışta bulunan update bilgisini kullanım anında sunar."""
        if not self._ensure_python_component(
            "whisper_pkg", "Whisper altyazı motoru", ["faster-whisper"], ["faster_whisper"], weekly_update=False
        ):
            return None
        repo = WHISPER_REPOS.get(model_size)
        if not repo:
            return model_size
        state = self._load_lazy_component_state()
        models = state.get("whisper_models", {}) if isinstance(state.get("whisper_models"), dict) else {}
        info = models.get(model_size, {}) if isinstance(models.get(model_size), dict) else {}
        cached_path = Path(str(info.get("snapshot_path") or "")) if info.get("snapshot_path") else None

        catalog = self._update_catalog or self._load_update_catalog()
        model_catalog = catalog.get("models", {}) if isinstance(catalog.get("models"), dict) else {}
        update_info = model_catalog.get(model_size, {}) if isinstance(model_catalog.get(model_size), dict) else {}

        if cached_path and cached_path.exists():
            if update_info.get("update_available") and model_size not in self._session_model_prompts:
                self._session_model_prompts.add(model_size)
                if not self._ask_yes_no_threadsafe(
                    f"Whisper {model_size} güncellemesi",
                    f"{model_size} modeli için yeni revision bilgisi bulundu.\n\nŞimdi yeni modeli indir?\nHayır dersen mevcut cache ile devam edilir.",
                    default=False,
                ):
                    self.log(f"Whisper {model_size}: model güncellemesi ertelendi, cache kullanılacak.")
                    return str(cached_path)
            else:
                self.log(f"Whisper {model_size}: ortak cache kullanılacak; indirme yok.")
                return str(cached_path)
        else:
            prompt_key = f"first:{model_size}"
            if prompt_key not in self._session_model_prompts:
                self._session_model_prompts.add(prompt_key)
                if not self._ask_yes_no_threadsafe(
                    f"Whisper {model_size} modeli",
                    f"Altyazı için {model_size} modeli henüz cache'te değil.\n\nŞimdi indirilsin mı? Model bir kez indirilecek ve sonraki kullanımlarda ortak cache'ten açılacak.",
                    default=True,
                ):
                    self.log(f"Whisper {model_size}: model indirme ertelendi.")
                    return None

        try:
            from huggingface_hub import model_info, snapshot_download
            self.log(f"Whisper {model_size}: model indiriliyor/güncelleniyor...")
            self.set_progress(6, f"Whisper {model_size} modeli hazırlanıyor")
            self.show_toast("Whisper modeli hazırlanıyor", f"{model_size} modeli ortak cache'e alınıyor.", "info", 7000)
            snapshot = snapshot_download(repo_id=repo, cache_dir=str(whisper_cache_dir()))
            try:
                sha = str(model_info(repo).sha or "")
            except Exception:
                sha = ""
            info = {"snapshot_path": str(snapshot), "revision": sha, "checked_at": time.time()}
            models[model_size] = info
            state["whisper_models"] = models
            self._save_lazy_component_state(state)
            self.log(f"Whisper {model_size} modeli hazır ve cache doğrulandı.")
            self.show_toast("Whisper hazır", f"{model_size} modeli kullanıma hazır.", "ok", 3500)
            return str(snapshot)
        except Exception as e:
            if cached_path and cached_path.exists():
                self.log(f"Whisper model güncellemesi başarısız; mevcut cache kullanılacak: {e}")
                return str(cached_path)
            self.log(f"Whisper modeli hazırlanamadı: {e}")
            self.show_toast("Whisper modeli hazırlanamadı", str(e)[:280], "error", 6500)
            return None

    def run_in_thread(self, target, *args) -> None:
        if self.current_thread and self.current_thread.is_alive():
            messagebox.showwarning("İşlem devam ediyor", "Önce mevcut işlemi iptal et veya bitmesini bekle.")
            return

        self.cancel_event.clear()
        try:
            self.set_download_speed("-")
        except Exception:
            pass

        def _runner() -> None:
            try:
                target(*args)
            except UserCancelled:
                self.log("İşlem kullanıcı tarafından iptal edildi.")
                self.set_progress(self.progress_var.get(), "İptal edildi")
            except Exception as e:
                self.log(f"Beklenmeyen hata: {e}")
                self.show_toast("İşlem hatası", str(e)[:320], "error", 7000)

        self.current_thread = threading.Thread(target=_runner, daemon=True)
        self.current_thread.start()

    def choose_dir(self, var: tk.StringVar) -> None:
        selected = filedialog.askdirectory()
        if selected:
            var.set(selected)

    def choose_file(self, var: tk.StringVar, filetypes) -> None:
        selected = filedialog.askopenfilename(filetypes=filetypes)
        if selected:
            var.set(selected)

    def choose_save_file(self, var: tk.StringVar, defaultextension: str, filetypes) -> None:
        selected = filedialog.asksaveasfilename(defaultextension=defaultextension, filetypes=filetypes)
        if selected:
            var.set(selected)

    def open_folder_path(self, path: Path) -> None:
        """Seçilen klasörü Windows Explorer'da açar."""
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(str(path))  # type: ignore[attr-defined]
            else:
                subprocess.Popen(["xdg-open", str(path)], **subprocess_hidden_kwargs())
        except Exception as e:
            self.log(f"Klasör açılamadı: {e}")

    def _download_lines_with_names(self) -> list[tuple[str | None, str]]:
        """
        Link kutusundaki satırları grup mantığıyla (ad, url) olarak döndürür.

        Örnek:
          chartshunter
          https://site/video1
          https://site/video2

        Sonuç:
          [(chartshunter, url1), (chartshunter, url2)]
        """
        try:
            raw_text = self.dl_url_text.get("1.0", "end")
        except Exception:
            return []

        parsed = parse_download_input_grouped(raw_text)
        return [(item.get("name"), item.get("url")) for item in parsed if item.get("url")]  # type: ignore[list-item]

    def has_named_download_lines(self) -> bool:
        """En az bir link grup/başlık adıyla ilişkilendirildi mi?"""
        return any(name for name, _url in self._download_lines_with_names())

    def get_download_target_dir(self) -> Path:
        """
        Link indirme için hedef klasörü döndürür.

        Öncelik:
        1) Link kutusunda grup/başlık adı varsa: Ana çıktı / ilk_grup_adı
        2) Grup yoksa ve dosya adı kökü varsa: Ana çıktı / kök
        3) Hiçbiri yoksa: Ana çıktı klasörü
        """
        root = Path(self.dl_output_dir.get()).expanduser()
        named_items = [(name, url) for name, url in self._download_lines_with_names() if name]
        if named_items:
            # Önizleme/klasör açma için ilk satır adını gösterir/açar.
            return root / named_items[0][0]

        manual_base = self.dl_filename_base.get().strip()
        safe_base = sanitize_file_base(manual_base) if manual_base else ""
        return root / safe_base if safe_base else root

    def update_download_preview(self, *_args) -> None:
        """Link kutusu veya dosya adı kökü değişince hedef klasör önizlemesini günceller."""
        try:
            named_items = [(name, url) for name, url in self._download_lines_with_names() if name]

            if named_items:
                if hasattr(self, "dl_filename_base_entry"):
                    self.dl_filename_base_entry.configure(state="disabled")
                if hasattr(self, "dl_name_mode_text"):
                    self.dl_name_mode_text.set("Grup/başlık adı algılandı: dosya adı kökü bu indirmede devre dışı kalır.")

                root = Path(self.dl_output_dir.get()).expanduser()
                unique_names = []
                for name, _url in named_items:
                    if name not in unique_names:
                        unique_names.append(name)
                sample = ", ".join(unique_names[:3])
                more = " ..." if len(unique_names) > 3 else ""
                self.dl_target_preview.set(f"{root}\\[{sample}{more}]")
                return

            if hasattr(self, "dl_filename_base_entry"):
                self.dl_filename_base_entry.configure(state="normal")
            if hasattr(self, "dl_name_mode_text"):
                self.dl_name_mode_text.set("Başlık/grup yazarsan o başlığın altındaki linkler aynı klasöre iner. Örn: chartshunter")

            target = self.get_download_target_dir()
            self.dl_target_preview.set(str(target))
        except Exception:
            pass

    def open_download_target_folder(self) -> None:
        self.open_folder_path(self.get_download_target_dir())

    # --------------------------------------------------------
    # DOSYA LISTESI YARDIMCILARI
    # --------------------------------------------------------
    def refresh_path_listbox(self, listbox: tk.Listbox, paths: list[Path]) -> None:
        listbox.delete(0, "end")
        for i, path in enumerate(paths, start=1):
            listbox.insert("end", f"{i:02d}. {path.name}  —  {path.parent}")

    def add_files_to_path_list(self, paths: list[Path], listbox: tk.Listbox, filetypes, title: str) -> None:
        selected = filedialog.askopenfilenames(title=title, filetypes=filetypes)
        if not selected:
            return

        added = 0
        existing = {p.resolve() for p in paths if p.exists()}

        for item in selected:
            path = Path(item)
            if path.is_file() and path.resolve() not in existing:
                paths.append(path)
                existing.add(path.resolve())
                added += 1

        self.refresh_path_listbox(listbox, paths)
        self.log(f"Listeye eklenen dosya sayısı: {added}")

    def add_folder_files_to_path_list(self, paths: list[Path], listbox: tk.Listbox, extensions: set[str], title: str) -> None:
        selected = filedialog.askdirectory(title=title)
        if not selected:
            return

        folder = Path(selected)
        files = sorted([
            p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in extensions
        ])

        added = 0
        existing = {p.resolve() for p in paths if p.exists()}

        for path in files:
            if path.resolve() not in existing:
                paths.append(path)
                existing.add(path.resolve())
                added += 1

        self.refresh_path_listbox(listbox, paths)
        self.log(f"Klasörden listeye eklenen dosya sayısı: {added}")

    def remove_selected_from_path_list(self, paths: list[Path], listbox: tk.Listbox) -> None:
        indices = list(listbox.curselection())
        if not indices:
            return

        for idx in reversed(indices):
            if 0 <= idx < len(paths):
                paths.pop(idx)

        self.refresh_path_listbox(listbox, paths)

    def clear_path_list(self, paths: list[Path], listbox: tk.Listbox) -> None:
        paths.clear()
        self.refresh_path_listbox(listbox, paths)

    def move_selected_in_path_list(self, paths: list[Path], listbox: tk.Listbox, direction: int) -> None:
        indices = list(listbox.curselection())
        if not indices:
            return

        if direction < 0:
            new_indices = []
            for idx in indices:
                if idx > 0:
                    paths[idx - 1], paths[idx] = paths[idx], paths[idx - 1]
                    new_indices.append(idx - 1)
                else:
                    new_indices.append(idx)
        else:
            new_indices = []
            for idx in reversed(indices):
                if idx < len(paths) - 1:
                    paths[idx + 1], paths[idx] = paths[idx], paths[idx + 1]
                    new_indices.append(idx + 1)
                else:
                    new_indices.append(idx)
            new_indices.reverse()

        self.refresh_path_listbox(listbox, paths)
        for idx in new_indices:
            listbox.selection_set(idx)
        if new_indices:
            listbox.see(new_indices[0])

    # --------------------------------------------------------
    # TAB 0: LINK -> MP4/MP3
    # --------------------------------------------------------
    def open_capture_extension_folder(self) -> None:
        """Yerel Chrome yakalama uzantısı klasörünü açar."""
        ext_dir = app_base_dir() / "chrome_capture_extension"
        self.open_folder_path(ext_dir)

    def show_capture_help(self) -> None:
        """UniTube tarzı tarayıcıdan stream link yakalama için kısa rehber."""
        messagebox.showinfo(
            "Chrome Stream Capture",
            "1) Chrome/Edge adres çubuğuna chrome://extensions yaz.\n"
            "2) Developer mode / Geliştirici modu aç.\n"
            "3) Load unpacked / Paketlenmemiş yükle de.\n"
            "4) Bu klasördeki chrome_capture_extension klasörünü seç.\n"
            "5) Video sayfasını aç, videoyu oynat. Reklam/intro geçtikten sonra gerçek video akışı başlayınca uzantı .m3u8/.mpd/.mp4 linklerini yakalar.\n"
            "6) Uzantıda Copy for Chartshunter düğmesine bas.\n"
            "7) Uygulamada Panodan Ekle düğmesine bas veya link kutusuna yapıştır.\n\n"
            "Not: Bu yöntem yalnızca erişim hakkın olan ve tarayıcıda zaten oynayan akış URL'lerini yakalamaya yarar. DRM/ödeme duvarı/özel hesap/teknik koruma aşmaz."
        )

    def paste_clipboard_to_download_box(self) -> None:
        """Panodaki yakalanan linkleri indirme kutusuna ekler."""
        try:
            text = self.clipboard_get()
        except Exception:
            self.log("Panoda metin bulunamadı.")
            return
        text = text.strip()
        if not text:
            self.log("Pano boş.")
            return
        current = self.dl_url_text.get("1.0", "end").strip()
        if current:
            self.dl_url_text.insert("end", "\n" + text + "\n")
        else:
            self.dl_url_text.insert("end", text + "\n")
        self.update_download_preview()
        self.log("Panodaki linkler indirme listesine eklendi.")


    def get_selected_or_first_download_url(self) -> tuple[str | None, str | None]:
        """Link kutusunda seçili metindeki veya listedeki ilk URL'yi döndürür."""
        selected_text = ""
        try:
            selected_text = self.dl_url_text.get("sel.first", "sel.last").strip()
        except Exception:
            selected_text = ""

        for raw in [selected_text, self.dl_url_text.get("1.0", "end")]:
            parsed = parse_download_input_grouped(raw or "")
            for item in parsed:
                url = item.get("url")
                if url:
                    return item.get("name"), str(url)
        return None, None

    def copy_selected_or_first_link(self) -> None:
        """Seçili/ilk URL'yi panoya kopyalar."""
        _name, url = self.get_selected_or_first_download_url()
        if not url:
            self.log("Kopyalanacak link bulunamadı.")
            messagebox.showwarning("Link yok", "Önce link kutusuna en az bir URL ekle.")
            return
        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.update()
            self.log(f"Link panoya kopyalandı: {url[:120]}")
        except Exception as e:
            self.log(f"Pano kopyalama hatası: {e}")

    def open_web_safely(self, url: str) -> None:
        """Varsayılan tarayıcıda URL açar."""
        try:
            webbrowser.open(url)
        except Exception as e:
            self.log(f"Tarayıcı açılamadı: {e}")
            messagebox.showerror("Tarayıcı açılamadı", str(e))

    def open_external_helper_home(self) -> None:
        """Seçili dış yardımcı aracın ana sayfasını açar."""
        helper = self.external_helper.get()
        helper_url = EXTERNAL_HELPERS.get(helper)
        if not helper_url:
            self.log("Yardımcı araç bulunamadı.")
            return
        self.open_web_safely(helper_url)
        self.log(f"Yardımcı açıldı: {helper}")

    def open_external_helper_with_link(self) -> None:
        """
        Seçili/ilk linki panoya kopyalar ve seçili dış yardımcıyı açar.

        Not:
        SaveFrom, VDownloader ve Video DownloadHelper kapalı/harici araçlardır; stabil bir
        public API vermedikleri için bunları uygulama içinde motor gibi taklit etmiyoruz.
        En sağlam entegrasyon: linki panoya almak + ilgili yardımcıyı açmak + gerekirse
        dönen gerçek medya linkini tekrar Chartshunter'a yapıştırmak.
        """
        helper = self.external_helper.get()
        helper_url = EXTERNAL_HELPERS.get(helper)
        if not helper_url:
            self.log("Yardımcı araç seçimi geçersiz.")
            return

        _name, url = self.get_selected_or_first_download_url()
        if not url:
            self.log("Yardımcıda açılacak link bulunamadı.")
            messagebox.showwarning("Link yok", "Önce link kutusuna en az bir URL ekle.")
            return

        try:
            self.clipboard_clear()
            self.clipboard_append(url)
            self.update()
        except Exception:
            pass

        self.open_web_safely(helper_url)
        self.log(f"{helper} açıldı; seçili/ilk link panoya kopyalandı.")
        messagebox.showinfo(
            "Yardımcı açıldı",
            f"{helper} açıldı.\n\nLink panoya kopyalandı; yardımcı sayfaya yapıştırabilirsin. "
            "Eğer yardımcı araç gerçek .m3u8/.mp4 linki verirse onu tekrar Link kutusuna ekleyip indirebilirsin."
        )

    def show_external_helpers_help(self) -> None:
        messagebox.showinfo(
            "Dış yardımcılar",
            "Bu bölüm SaveFrom, VDownloader ve Video DownloadHelper gibi harici araçlara hızlı köprü sağlar.\n\n"
            "Mantık:\n"
            "1) Link kutusundaki seçili/ilk URL panoya kopyalanır.\n"
            "2) Seçtiğin yardımcı araç açılır.\n"
            "3) Yardımcı araç gerçek medya/stream linki üretirse onu Chartshunter'a geri yapıştırabilirsin.\n\n"
            "Cobalt ayrı: Auto+ motorunda zaten API fallback olarak denenir.\n"
            "SaveFrom/VDownloader/VDH tarafında stabil public API olmadığı için doğrudan motor gibi gömmek yerine köprü modu daha güvenli ve bakımı kolaydır."
        )


    def append_lines_to_download_box_threadsafe(self, lines: list[str]) -> None:
        """Arka thread içinden indirme kutusuna güvenli şekilde satır ekler."""
        def _append() -> None:
            current = self.dl_url_text.get("1.0", "end").strip()
            text = "\n".join(lines).strip()
            if not text:
                return
            if current:
                self.dl_url_text.insert("end", "\n" + text + "\n")
            else:
                self.dl_url_text.insert("end", text + "\n")
            self.update_download_preview()
        self.after(0, _append)

    def pick_browser_url_from_download_box(self) -> None:
        """Seçili metinden veya listedeki ilk linkten dahili browser URL/grup alanını doldurur."""
        selected_text = ""
        try:
            selected_text = self.dl_url_text.get("sel.first", "sel.last")
        except Exception:
            selected_text = ""

        candidate_url = get_first_url_from_text(selected_text)
        candidate_group = None

        if candidate_url:
            # Seçili satırdaki adı yakalamaya çalış.
            for line in selected_text.splitlines():
                name, url, _ref = parse_named_url_line(line)
                if url == candidate_url and name:
                    candidate_group = name
                    break
        else:
            items = parse_download_input_grouped(self.dl_url_text.get("1.0", "end"))
            for item in items:
                url = str(item.get("url") or "").strip()
                if url:
                    candidate_url = url
                    name = item.get("name")
                    candidate_group = str(name).strip() if name else None
                    break

        if not candidate_url:
            messagebox.showinfo("Dahili Browser", "Önce link kutusuna bir sayfa linki ekle veya linki seç.")
            return

        self.browser_url.set(candidate_url)
        if candidate_group:
            self.browser_group.set(sanitize_file_base(candidate_group))
        elif not self.browser_group.get().strip():
            self.browser_group.set("browser_capture")
        self.log(f"Dahili browser hedefi alındı: {candidate_url}")

    def task_install_browser_engine(self) -> None:
        """Playwright/Chromium'u yalnızca browser özelliği kullanıldığında hazırlar."""
        if not self._ensure_python_component("browser_pkg", "Dahili browser", ["playwright"], ["playwright"], weekly_update=True):
            return
        self.set_progress(0, "Dahili browser motoru kuruluyor")
        self.log("Playwright Chromium kurulumu başlıyor. İlk kurulum birkaç dakika sürebilir.")
        args = python_module_command("playwright") + ["install", "chromium"]
        try:
            ok, out = self._run_simple_command_with_log(args, log_prefix="browser-install")
            if ok:
                self.set_progress(100, "Dahili browser motoru hazır")
                self.log("Dahili browser motoru kuruldu.")
            else:
                self.log("Dahili browser motoru kurulamadı. Çıktı: " + (out[-800:] if out else "yok"))
        except Exception as e:
            self.log(f"Dahili browser motoru kurulum hatası: {e}")

    def _run_simple_command_with_log(self, args: list[str], log_prefix: str = "cmd") -> tuple[bool, str]:
        """Uzun komutları loglayarak çalıştırır; iptal düğmesine saygı duyar."""
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="ignore",
            **subprocess_hidden_kwargs(),
        )
        lines: list[str] = []
        last_log = 0.0
        try:
            while True:
                if self.is_cancelled():
                    stop_process_quietly(process)
                    raise UserCancelled("İşlem kullanıcı tarafından iptal edildi.")
                line = process.stdout.readline() if process.stdout is not None else ""
                if line:
                    clean = line.strip()
                    lines.append(clean)
                    if clean and time.time() - last_log >= 5:
                        self.log(f"{log_prefix}: {clean[:240]}")
                        last_log = time.time()
                elif process.poll() is not None:
                    break
                else:
                    time.sleep(0.1)
            return process.returncode == 0, "\n".join(lines[-120:])
        finally:
            if process.poll() is None and self.is_cancelled():
                stop_process_quietly(process)

    def _install_playwright_chromium_if_needed(self) -> bool:
        """
        Playwright paketi kurulu ama Chromium indirilmemişse otomatik kurar.
        Dönüş: Chromium ile tekrar denemek mantıklı mı?
        """
        if not self._ensure_python_component("browser_pkg", "Dahili browser", ["playwright"], ["playwright"], weekly_update=True):
            return False
        self.log("Playwright Chromium eksik görünüyor; otomatik kurulum deneniyor.")
        args = python_module_command("playwright") + ["install", "chromium"]
        ok, out = self._run_simple_command_with_log(args, log_prefix="browser-install")
        if not ok:
            self.log("Chromium kurulumu başarısız: " + (out[-800:] if out else "çıktı yok"))
        return ok

    def _get_browser_capture_minutes(self) -> int:
        """Yakalama süresini güvenli aralıkta döndürür."""
        try:
            return max(1, min(60, int(float(self.browser_minutes.get().strip() or "5"))))
        except Exception:
            return 5

    def _capture_stream_candidates(
        self,
        page_url: str,
        group: str,
        capture_minutes: int,
        headless: bool,
    ) -> list[tuple[str, str | None]]:
        """
        Playwright Chromium ile sayfayı açar ve tarayıcının çağırdığı açık medya/stream
        adaylarını yakalar.

        v25: Kalıcı browser profili kullanır. Görünür browser ile bir siteye normal giriş
        yaparsan oturum/cookie bu uygulama klasöründeki browser_profile içinde kalır.
        Sonraki arka plan yakalamalarında aynı profil kullanılmaya çalışılır.
        """
        if page_url.lower().startswith("www."):
            page_url = "https://" + page_url

        if not self._ensure_python_component("browser_pkg", "Dahili browser", ["playwright"], ["playwright"], weekly_update=True):
            return []
        mark_runtime_usage("browser", "chromium")
        self.log(f"Dahili browser hedefi: {page_url}")
        self.log(f"Mod: {'arka plan/headless' if headless else 'görünür tarayıcı'} | Grup: {group} | Süre: {capture_minutes} dk")
        self.set_progress(0, "Dahili browser hazırlanıyor")

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:
            self.log(f"Playwright yüklenemedi: {e}")
            self.log("requirements kurulumu eksik olabilir. run_app.bat ile tekrar aç.")
            return []

        captured: list[tuple[str, str | None]] = []
        seen: set[str] = set()
        browser_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )

        def add_candidate(url: str, referer: str | None = None) -> None:
            if not is_browser_capture_candidate_url(url):
                return
            key = url.split("#", 1)[0]
            if key in seen:
                return
            seen.add(key)
            captured.append((url, referer or page_url))
            self.log(f"Stream adayı yakalandı [{len(captured)}]: {url[:180]}")

        def run_capture_once(install_retry: bool = True) -> None:
            with sync_playwright() as p:
                profile_dir = app_base_dir() / "browser_profile"
                profile_dir.mkdir(exist_ok=True)

                def launch_context():
                    return p.chromium.launch_persistent_context(
                        user_data_dir=str(profile_dir),
                        headless=headless,
                        user_agent=browser_user_agent,
                        viewport={"width": 1366, "height": 768},
                        locale="tr-TR",
                        ignore_https_errors=True,
                        extra_http_headers={"Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"},
                    )

                try:
                    context = launch_context()
                except Exception as e:
                    msg = str(e)
                    if install_retry and ("Executable doesn't exist" in msg or "playwright install" in msg.lower() or "browser" in msg.lower()):
                        if self._install_playwright_chromium_if_needed():
                            context = launch_context()
                        else:
                            raise
                    else:
                        raise

                self.log(f"Browser profili: {profile_dir}")
                page = context.new_page()

                def on_request(req):
                    try:
                        headers = req.headers or {}
                        add_candidate(req.url, headers.get("referer") or page_url)
                    except Exception:
                        pass

                def on_response(resp):
                    try:
                        headers = resp.request.headers or {}
                        add_candidate(resp.url, headers.get("referer") or page_url)
                    except Exception:
                        pass

                page.on("request", on_request)
                page.on("response", on_response)

                try:
                    page.goto(page_url, wait_until="domcontentloaded", timeout=60_000)
                except Exception as e:
                    self.log(f"Sayfa açılırken uyarı: {str(e)[:300]}")

                def try_normal_page_actions() -> None:
                    """
                    Arka plan modunda video tetiklenebilsin diye normal kullanıcı aksiyonlarını taklit eder.
                    v20: Görünür ve etkin "Skip Ad / Reklamı Geç" düğmelerini de periyodik dener.
                    Unskippable/disable durumdaki reklamı zorlamaz; sadece kullanıcının basabileceği butona basar.
                    """
                    try:
                        page.evaluate(
                            """() => {
                                for (const v of document.querySelectorAll('video')) {
                                    try {
                                        v.muted = true;
                                        v.autoplay = true;
                                        v.play().catch(() => {});
                                    } catch(e) {}
                                }
                            }"""
                        )
                    except Exception:
                        pass

                    try:
                        auto_skip_ads = bool(self.browser_auto_skip_ads.get())
                    except Exception:
                        auto_skip_ads = True

                    # Çerez/izin/oynatma butonları. Bunlar sayfanın normal erişilebilir butonlarıdır.
                    base_button_texts = [
                        "Accept", "Accept all", "I agree", "Agree", "Allow",
                        "Kabul", "Tümünü kabul et", "İzin ver", "Tamam",
                        "Play", "Oynat", "Continue", "Devam",
                        # Adult/video-host sitelerinde görünen normal yaş/consent butonları.
                        # Bu yalnızca kullanıcının zaten basabileceği görünen butonu dener; koruma aşmaz.
                        "I am 18", "I am over 18", "I am 18 or older", "I am over 18 years old",
                        "Yes, I am 18", "Enter", "Enter site", "Enter Site", "Start watching",
                        "I consent", "Consent", "Confirm", "Confirm age", "Age verification",
                        "18+", "Devam et", "Giriş", "Gir", "18 yaşından büyüğüm", "18 yaş ve üzeriyim"
                    ]

                    skip_button_texts = [
                        "Skip Ad", "Skip Ads", "Skip ad", "Skip ads", "Skip",
                        "Atla", "Reklamı geç", "Reklamı Geç", "Reklami gec",
                        "Geç", "Gec", "Skip intro", "Intro'yu geç",
                        "Close ad", "Close Ads", "Close", "No thanks", "Not now",
                        "Kapat", "Reklamı kapat", "Sonra", "Şimdi değil"
                    ]

                    def click_text_candidates(frame, labels, timeout_ms=500) -> int:
                        clicked = 0
                        for label in labels:
                            try:
                                loc = frame.get_by_text(label, exact=False).first
                                if loc.count() > 0:
                                    loc.click(timeout=timeout_ms)
                                    clicked += 1
                                    page.wait_for_timeout(250)
                            except Exception:
                                pass
                        return clicked

                    def click_skip_by_selectors(frame) -> int:
                        """Yaygın player skip/reklam butonlarını görünür ve etkinse tıklar."""
                        clicked = 0
                        selectors = [
                            "button:has-text('Skip')",
                            "button:has-text('Atla')",
                            "button:has-text('Reklam')",
                            "[aria-label*='Skip' i]",
                            "[aria-label*='Atla' i]",
                            "[aria-label*='Reklam' i]",
                            ".ytp-ad-skip-button",
                            ".ytp-ad-skip-button-modern",
                            ".videoAdUiSkipButton",
                            ".skip-ad",
                            ".skipAd",
                            ".ad-skip",
                            "[class*='skip' i]",
                            "[id*='skip' i]",
                            "[class*='close' i]",
                            "[id*='close' i]",
                            "[aria-label*='Close' i]",
                            "button:has-text('18')",
                            "button:has-text('Enter')",
                            "button:has-text('Continue')",
                        ]
                        for selector in selectors:
                            try:
                                loc = frame.locator(selector).first
                                if loc.count() > 0 and loc.is_visible(timeout=300) and loc.is_enabled(timeout=300):
                                    loc.click(timeout=600)
                                    clicked += 1
                                    page.wait_for_timeout(250)
                            except Exception:
                                pass
                        return clicked

                    def js_click_visible_skip(frame) -> int:
                        """Metin/class/aria içinde skip-ad geçen görünür ve etkin elementleri tıklar."""
                        try:
                            return int(frame.evaluate(
                                """() => {
                                    const words = [
                                        'skip ad', 'skip ads', 'skip',
                                        'reklamı geç', 'reklami gec', 'reklam geç',
                                        'atla', 'geç', 'gec', 'skip intro',
                                        'close ad', 'close ads', 'close', 'no thanks', 'not now',
                                        'i am 18', 'over 18', '18 or older', 'enter site',
                                        'enter', 'continue', 'i consent', 'confirm age',
                                        '18 yaş', '18 yas', 'giriş', 'gir'
                                    ];
                                    function visible(el) {
                                        const r = el.getBoundingClientRect();
                                        const s = window.getComputedStyle(el);
                                        return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
                                    }
                                    let clicked = 0;
                                    const els = Array.from(document.querySelectorAll('button, [role=button], a, div, span'));
                                    for (const el of els) {
                                        const txt = ((el.innerText || '') + ' ' + (el.getAttribute('aria-label') || '') + ' ' + (el.className || '') + ' ' + (el.id || '')).toLowerCase();
                                        if (!words.some(w => txt.includes(w))) continue;
                                        if (!visible(el)) continue;
                                        if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
                                        try { el.click(); clicked += 1; } catch(e) {}
                                    }
                                    return clicked;
                                }"""
                            ))
                        except Exception:
                            return 0

                    total_clicked = 0
                    for frame in page.frames:
                        total_clicked += click_text_candidates(frame, base_button_texts)
                        if auto_skip_ads:
                            total_clicked += click_text_candidates(frame, skip_button_texts, timeout_ms=450)
                            total_clicked += click_skip_by_selectors(frame)
                            total_clicked += js_click_visible_skip(frame)

                    if total_clicked:
                        self.log(f"Browser otomatik buton denemesi: {total_clicked} tıklama")

                    try:
                        page.mouse.wheel(0, 500)
                    except Exception:
                        pass

                # İlk hamle: sayfa yüklenince bir dene.
                try_normal_page_actions()

                start = time.time()
                total = capture_minutes * 60
                last_status = 0.0
                last_action = 0.0
                self.log("Yakalama aktif. Skip Ad otomatik dene açıksa görünür/etkin reklam geç butonları periyodik tıklanır. Arka planda uygulama normal oynatma tetiklemeyi dener.")

                while True:
                    if self.is_cancelled():
                        raise UserCancelled("Dahili browser yakalama iptal edildi.")
                    elapsed = time.time() - start
                    percent = min(99.0, max(0.0, elapsed / total * 100))
                    if elapsed - last_status >= 3:
                        self.set_progress(percent, f"Browser yakalıyor | Aday: {len(captured)}")
                        last_status = elapsed
                    if elapsed - last_action >= 8:
                        try_normal_page_actions()
                        last_action = elapsed
                    if elapsed >= total:
                        break
                    try:
                        if page.is_closed():
                            self.log("Tarayıcı sayfası kapandı; yakalama bitiriliyor.")
                            break
                        page.wait_for_timeout(500)
                    except Exception:
                        break
                try:
                    context.close()
                except Exception:
                    pass

        try:
            run_capture_once()
        except UserCancelled:
            raise
        except Exception as e:
            self.log(f"Dahili browser yakalama hatası: {e}")
            self.log("Not: Görünür browser ile açıp videoyu başlatarak tekrar dene; yakalanan stream adayları loga düşer.")
            return []

        return sort_stream_candidates(captured)

    def _captured_lines(self, group: str, page_url: str, captured_sorted: list[tuple[str, str | None]], limit: int | None = None) -> list[str]:
        """Yakalanan stream adaylarını indirme kutusu formatına çevirir."""
        lines = ["", group]
        selected = captured_sorted if limit is None else captured_sorted[:limit]
        for url, referer in selected:
            lines.append(make_stream_line(url, referer or page_url))
        return lines

    def _write_capture_backup(self, group: str, lines: list[str]) -> None:
        """Yakalanan stream listesini yedek TXT olarak kaydeder."""
        try:
            cap_dir = Path(self.dl_output_dir.get()).expanduser() / group
            cap_dir.mkdir(parents=True, exist_ok=True)
            cap_file = cap_dir / f"{group}_captured_streams_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            cap_file.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
            self.log(f"Yakalanan stream listesi kaydedildi: {cap_file}")
        except Exception as e:
            self.log(f"Yakalama listesi dosyaya yazılamadı: {e}")

    def _run_download_override(self, raw_text: str) -> None:
        """Geçici metinle indirme çalıştırır; asıl link kutusu içeriğini değiştirmez."""
        old_override = getattr(self, "_download_raw_text_override", None)
        self._download_raw_text_override = raw_text
        try:
            self.task_download_url()
        finally:
            self._download_raw_text_override = old_override

    def _snapshot_files_for_group(self, group: str) -> set[Path]:
        root = Path(self.dl_output_dir.get()).expanduser() / group
        try:
            return {p.resolve() for p in root.rglob("*") if p.is_file()}
        except Exception:
            return set()

    def task_browser_capture(self) -> None:
        """
        Dahili browser: tek sayfada stream adaylarını yakalar. İster görünür, ister arka plan modunda çalışır.
        Otomatik indir seçiliyse yakalanan adayları tek tek dener.
        """
        page_url = self.browser_url.get().strip()
        if not page_url:
            self.log("Dahili browser için URL boş. Önce link al/seç.")
            self.set_progress(0, "Browser URL yok")
            return
        if page_url.lower().startswith("www."):
            page_url = "https://" + page_url

        group = sanitize_file_base(self.browser_group.get().strip() or self.dl_filename_base.get().strip() or "browser_capture")
        capture_minutes = self._get_browser_capture_minutes()
        headless = bool(self.browser_headless.get())

        try:
            captured_sorted = self._capture_stream_candidates(page_url, group, capture_minutes, headless)
        except UserCancelled:
            self.log("Dahili browser yakalama iptal edildi.")
            self.set_progress(self.progress_var.get(), "Browser yakalama iptal edildi")
            return

        if not captured_sorted:
            self.log("Dahili browser açık medya/stream adayı yakalayamadı.")
            if bool(self.browser_auto_download.get()):
                self.log("Otomatik indirme açık: son şans olarak orijinal sayfa linki normal motor zinciriyle denenecek.")
                before = self._snapshot_files_for_group(group)
                one = f"{group}\n{page_url}\n"
                try:
                    self._run_download_override(one)
                except Exception as e:
                    self.log(f"Orijinal sayfa linki denemesi hata verdi: {e}")
                after = self._snapshot_files_for_group(group)
                if len(after - before) > 0:
                    self.set_progress(100, "Orijinal linkle başarılı")
                    self.log("Orijinal sayfa linkiyle başarılı dosya oluştu.")
                    return
            self.log("Aday bulunamadı. Görünür modda açıp videoyu elle oynatmayı veya HAR içe aktarmayı deneyebilirsin.")
            self.set_progress(100, "Aday bulunamadı")
            return

        lines = self._captured_lines(group, page_url, captured_sorted)
        self.append_lines_to_download_box_threadsafe(lines)
        self._write_capture_backup(group, lines)

        self.set_progress(100, f"Browser yakalama bitti | Aday: {len(captured_sorted)}")
        self.log(f"Dahili browser yakalama bitti. Aday sayısı: {len(captured_sorted)} | Grup: {group}")

        if bool(self.browser_auto_download.get()):
            self.log("Otomatik indirme açık: yakalanan adaylar sırayla denenecek. İlk başarılı indirmeden sonra bu sayfa tamam sayılır.")
            downloaded_this_page = False
            for i, (url, referer) in enumerate(captured_sorted[:10], start=1):
                if self.is_cancelled():
                    self.log("Otomatik indirme iptal edildi.")
                    return
                before = self._snapshot_files_for_group(group)
                one = f"{group}\n{make_stream_line(url, referer or page_url)}\n"
                self.log(f"Aday {i}/{min(len(captured_sorted), 10)} deneniyor: {url[:180]}")
                self._run_download_override(one)
                after = self._snapshot_files_for_group(group)
                if len(after - before) > 0:
                    downloaded_this_page = True
                    self.log("Bu sayfa için başarılı dosya oluştu; diğer adaylara geçmiyorum.")
                    break
            if not downloaded_this_page:
                self.log("Yakalanan adaylar indirilemedi. Son şans olarak orijinal sayfa linki normal motor zinciriyle denenecek.")
                before = self._snapshot_files_for_group(group)
                one = f"{group}\n{page_url}\n"
                try:
                    self._run_download_override(one)
                except Exception as e:
                    self.log(f"Orijinal sayfa linki denemesi hata verdi: {e}")
                after = self._snapshot_files_for_group(group)
                if len(after - before) > 0:
                    self.log("Orijinal sayfa linkiyle başarılı dosya oluştu.")
                else:
                    self.log("Bu sayfa hiçbir aday/orijinal link denemesiyle indirilemedi.")
            self.set_progress(100, "Yakalama + indirme bitti")
        else:
            self.log("Şimdi Linklerden İndir'e bas. Yakalanan adaylardan biri ölüyse diğer adaylara geçmeye devam eder.")

    def task_browser_batch_capture_download(self) -> None:
        """
        Link listesindeki sayfaları arka planda açıp stream yakalar ve yakaladığı adayları indirir.
        Grup başlıklarını korur: chartshunter altındaki linkler chartshunter klasörüne iner.
        """
        raw_text = self.dl_url_text.get("1.0", "end")
        items = parse_download_input_grouped(raw_text)
        page_items = []
        for item in items:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            name_value = item.get("name")
            group = sanitize_file_base(str(name_value).strip()) if name_value else sanitize_file_base(self.dl_filename_base.get().strip() or "browser_capture")
            page_items.append({"url": url, "group": group})

        if not page_items:
            self.log("Arka plan yakalama için link yok.")
            self.set_progress(0, "Link yok")
            return

        capture_minutes = self._get_browser_capture_minutes()
        # Bu buton bilinçli olarak arka plan çalışır; manuel izleme gerekirse tek sayfa Browser Aç + Yakala kullanılmalı.
        headless = True
        total = len(page_items)
        success = 0
        failed = 0
        failed_pages: list[str] = []

        self.log(f"Arka planda yakala + indir başladı. Sayfa sayısı: {total} | Her sayfa en fazla {capture_minutes} dk")
        self.log("Not: Site etkileşim istiyorsa arka plan modunda stream çıkmayabilir; o linki görünür browser ile dene.")

        for idx, item in enumerate(page_items, start=1):
            if self.is_cancelled():
                self.log("Arka plan yakalama kullanıcı tarafından iptal edildi.")
                self.set_progress(self.progress_var.get(), "İptal edildi")
                return

            page_url = str(item["url"])
            group = str(item["group"])
            base_percent = (idx - 1) / total * 100
            self.set_progress(base_percent, f"Browser {idx}/{total} yakalıyor")
            self.log(f"[{idx}/{total}] Arka planda sayfa açılıyor: {page_url}")

            try:
                captured_sorted = self._capture_stream_candidates(page_url, group, capture_minutes, headless)
            except UserCancelled:
                self.log("Arka plan yakalama iptal edildi.")
                self.set_progress(self.progress_var.get(), "İptal edildi")
                return
            except Exception as e:
                self.log(f"Bu sayfada browser yakalama hatası: {e}")
                captured_sorted = []

            if not captured_sorted:
                self.log("Bu sayfada stream adayı bulunamadı. Son şans olarak orijinal sayfa linki normal motor zinciriyle denenecek.")
                before = self._snapshot_files_for_group(group)
                one = f"{group}\n{page_url}\n"
                try:
                    self._run_download_override(one)
                except Exception as e:
                    self.log(f"Orijinal sayfa linki denemesi hata verdi: {e}")
                after = self._snapshot_files_for_group(group)
                if len(after - before) > 0:
                    success += 1
                    self.log(f"[{idx}/{total}] Orijinal sayfa linkiyle başarılı.")
                    self.set_progress(idx / total * 100, f"Browser {idx}/{total} tamam")
                    continue
                self.log("Bu sayfada stream adayı bulunamadı ve orijinal link de indirilemedi; sıradaki sayfaya geçiliyor.")
                failed += 1
                failed_pages.append(page_url)
                continue

            all_lines = self._captured_lines(group, page_url, captured_sorted)
            self.append_lines_to_download_box_threadsafe(all_lines)
            self._write_capture_backup(group, all_lines)

            downloaded_this_page = False
            for cand_idx, (url, referer) in enumerate(captured_sorted[:10], start=1):
                if self.is_cancelled():
                    self.log("Otomatik indirme iptal edildi.")
                    self.set_progress(self.progress_var.get(), "İptal edildi")
                    return
                before = self._snapshot_files_for_group(group)
                one = f"{group}\n{make_stream_line(url, referer or page_url)}\n"
                self.log(f"[{idx}/{total}] Aday {cand_idx}/{min(len(captured_sorted), 10)} indiriliyor/deneniyor.")
                self._run_download_override(one)
                after = self._snapshot_files_for_group(group)
                if len(after - before) > 0:
                    downloaded_this_page = True
                    self.log(f"[{idx}/{total}] Başarılı. Diğer adayları denemiyorum.")
                    break

            if downloaded_this_page:
                success += 1
            else:
                self.log(f"[{idx}/{total}] Yakalandı ama indirilemedi. Son şans olarak orijinal sayfa linki normal motor zinciriyle denenecek.")
                before = self._snapshot_files_for_group(group)
                one = f"{group}\n{page_url}\n"
                try:
                    self._run_download_override(one)
                except Exception as e:
                    self.log(f"Orijinal sayfa linki denemesi hata verdi: {e}")
                after = self._snapshot_files_for_group(group)
                if len(after - before) > 0:
                    success += 1
                    self.log(f"[{idx}/{total}] Orijinal sayfa linkiyle başarılı.")
                else:
                    failed += 1
                    failed_pages.append(page_url)
                    self.log(f"[{idx}/{total}] Yakalandı ama indirilemedi; sıradaki sayfaya geçiliyor.")

            self.set_progress(idx / total * 100, f"Browser {idx}/{total} tamam")

        self.set_progress(100, "Arka plan yakalama + indirme bitti")
        if failed_pages:
            try:
                report_dir = Path(self.dl_output_dir.get()).expanduser()
                report_dir.mkdir(parents=True, exist_ok=True)
                failed_path = report_dir / f"failed_browser_pages_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                failed_path.write_text("\n".join(failed_pages) + "\n", encoding="utf-8")
                self.log(f"Başarısız browser sayfa raporu yazıldı: {failed_path}")
            except Exception as e:
                self.log(f"Başarısız browser raporu yazılamadı: {e}")
        self.log(f"Arka plan yakalama + indirme bitti. Başarılı: {success} | Başarısız: {failed}")


    def source_scan_current_links(self) -> None:
        """Link kutusundaki sayfa URL'lerinin kaynak kodunda medya linki arar."""
        raw_text = self.dl_url_text.get("1.0", "end")
        items = parse_download_input_grouped(raw_text)
        page_items = []
        for item in items:
            url = str(item.get("url") or "").strip()
            name_value = item.get("name")
            name = str(name_value).strip() if name_value else None
            if url and not is_probable_direct_media_url(url):
                page_items.append((name, url))

        if not page_items:
            self.log("Kaynak tarama icin sayfa linki bulunamadi. Direkt .m3u8/.mp4 linkleri zaten indirilebilir adaydir.")
            messagebox.showinfo("Kaynak Tara", "Kaynak kodu taranacak normal sayfa linki bulunamadı.")
            return

        browser_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )

        appended_lines: list[str] = []
        total_found = 0

        for name, page_url in page_items:
            self.log(f"Kaynak taranıyor: {page_url}")
            try:
                req = Request(page_url, headers={
                    "User-Agent": browser_user_agent,
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": page_url,
                })
                with urlopen(req, timeout=20) as resp:
                    charset = resp.headers.get_content_charset() or "utf-8"
                    html = resp.read(5_000_000).decode(charset, errors="ignore")
                candidates = extract_media_candidates_from_text(html, page_url)
            except Exception as e:
                self.log(f"Kaynak tarama başarısız: {e}")
                candidates = []

            if not candidates:
                self.log("Kaynakta açık medya linki bulunamadı. Bu durumda Chrome yakalama uzantısı veya HAR içe aktarma daha iyi yöntemdir.")
                continue

            total_found += len(candidates)
            group_name = name or sanitize_file_base("source_scan")
            appended_lines.append("")
            appended_lines.append(group_name)
            for candidate in candidates:
                appended_lines.append(make_stream_line(candidate, page_url))
            self.log(f"Bulunan medya adayı: {len(candidates)}")

        if appended_lines:
            self.dl_url_text.insert("end", "\n" + "\n".join(appended_lines) + "\n")
            self.update_download_preview()
            self.log(f"Kaynak tarama sonucu indirme kutusuna eklendi. Toplam aday: {total_found}")
            messagebox.showinfo("Kaynak Tara", f"{total_found} medya/stream adayı eklendi.")
        else:
            messagebox.showinfo("Kaynak Tara", "Açık medya/stream adayı bulunamadı.")

    def import_har_to_download_box(self) -> None:
        """DevTools HAR dosyasindan m3u8/mpd/mp4 adaylarini alir ve kutuya ekler."""
        selected = filedialog.askopenfilename(
            title="HAR dosyası seç",
            filetypes=[("HAR / JSON", "*.har *.json"), ("Tüm dosyalar", "*.*")],
        )
        if not selected:
            return
        path = Path(selected)
        try:
            candidates = parse_har_media_candidates(path)
        except Exception as e:
            self.log(f"HAR okunamadı: {e}")
            messagebox.showerror("HAR İçe Aktar", f"HAR dosyası okunamadı:\n{e}")
            return

        if not candidates:
            self.log("HAR içinde medya/manifest adayı bulunamadı.")
            messagebox.showinfo("HAR İçe Aktar", "HAR içinde .m3u8/.mpd/.mp4/.webm adayı bulunamadı.")
            return

        group = sanitize_file_base(path.stem or "har_capture")
        lines = ["", group]
        for url, referer in candidates:
            lines.append(make_stream_line(url, referer))

        self.dl_url_text.insert("end", "\n" + "\n".join(lines) + "\n")
        self.update_download_preview()
        self.log(f"HAR içe aktarıldı. Aday sayısı: {len(candidates)} | Grup: {group}")
        messagebox.showinfo("HAR İçe Aktar", f"{len(candidates)} medya/stream adayı eklendi.")

    def show_advanced_download_help(self) -> None:
        """En güçlü yasal indirme akışı için kısa rehber."""
        messagebox.showinfo(
            "Gelişmiş indirme akışı",
            "En güçlü sıra şudur:\n\n"
            "1) Normal linki Auto + Çok Hızlı + Zorlayıcı mod ile dene.\n"
            "2) Olmazsa Kaynak Tara ile sayfa HTML/JS içindeki açık .m3u8/.mpd/.mp4 linklerini ara.\n"
            "3) Hâlâ olmazsa Chrome yakalama uzantısını kullan: video oynarken gerçek stream linkini yakala.\n"
            "4) En son DevTools > Network > Export HAR yapıp HAR İçe Aktar düğmesiyle stream adaylarını ekle.\n\n"
            "Bu akış tarayıcıda erişebildiğin açık streamleri bulmaya çalışır. DRM, ödeme duvarı, özel hesap veya erişim kontrolü aşma amacıyla kullanılmaz."
        )

    def _build_download_tab(self) -> None:
        f = self.tab_download
        f.columnconfigure(0, weight=1)
        f.rowconfigure(1, weight=1)

        self.dl_output_dir = tk.StringVar(value=str(app_base_dir() / "outputs" / "downloads"))
        self.dl_mode = tk.StringVar(value="MP4 1080p")
        self.dl_engine = tk.StringVar(value="Auto+: yt-dlp -> Cobalt -> gallery-dl -> streamlink -> direct")
        self.dl_speed_mode = tk.StringVar(value="Hızlı")
        self.dl_cookies_browser = tk.StringVar(value=COOKIE_BROWSER_AUTO)
        self.dl_cobalt_api_url = tk.StringVar(value="https://api.cobalt.tools")
        self.dl_cobalt_api_key = tk.StringVar(value="")
        self.dl_hard_mode = tk.BooleanVar(value=True)
        self.dl_adult_profile = tk.BooleanVar(value=True)
        self.dl_playlist = tk.BooleanVar(value=False)
        self.dl_filename_base = tk.StringVar(value="")
        self.dl_target_preview = tk.StringVar(value="")
        self.browser_url = tk.StringVar(value="")
        self.browser_group = tk.StringVar(value="browser_capture")
        self.browser_minutes = tk.StringVar(value="5")
        self.browser_headless = tk.BooleanVar(value=True)
        self.browser_auto_skip_ads = tk.BooleanVar(value=True)
        self.browser_auto_download = tk.BooleanVar(value=False)
        self.dl_name_mode_text = tk.StringVar(
            value="Başlık/grup yazarsan dosya adı kökü devre dışı kalır. Örn: chartshunter satırı altındaki linkler aynı klasöre iner."
        )
        self.external_helper = tk.StringVar(value="SaveFrom.net")

        intro = ttk.LabelFrame(f, text="1) Linkleri yapıştır", style="Section.TLabelframe")
        intro.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 6))
        intro.columnconfigure(0, weight=1)
        ttk.Label(
            intro,
            text=(
                "Her satıra bir link koy. Grup başlığı yazarsan altındaki linkler o klasöre iner. "
                "Yakalanmış stream linklerinde referer= bilgisi varsa uygulama onu da kullanır. Görünür Skip Ad düğmeleri otomatik geçilebilir."
            ),
            wraplength=980,
        ).grid(row=0, column=0, sticky="w", padx=10, pady=(8, 4))

        self.dl_url_text = ScrolledText(intro, height=6, font=("Consolas", 9))
        self.dl_url_text.grid(row=1, column=0, sticky="ew", padx=10, pady=(4, 10))
        self.dl_url_text.insert("end", "# Örnek kullanım:\n# chartshunter\n# https://site.com/video1\n# https://site.com/video2\n#\n# othername\n# https://site.com/video3\n")
        self.dl_url_text.bind("<KeyRelease>", self.update_download_preview)

        capture = ttk.LabelFrame(f, text="1B) Dahili Browser / UniTube tarzı stream yakalama", style="Section.TLabelframe")
        capture.grid(row=1, column=0, sticky="ew", padx=12, pady=6)
        capture.columnconfigure(1, weight=1)
        capture.columnconfigure(3, weight=1)
        ttk.Label(
            capture,
            text=(
                "Normal link indirme bazı sayfalarda yetmez. Bu mod kontrollü Chromium açar; video oynarken çıkan gerçek "
                ".m3u8/.mpd/.mp4 stream adaylarını yakalayıp indirme kutusuna ekler. Reklam/intro varsa görünür Skip Ad düğmesini otomatik denebilir."
            ),
            wraplength=980,
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=10, pady=(8, 4))

        ttk.Label(capture, text="Browser URL").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        ttk.Entry(capture, textvariable=self.browser_url).grid(row=1, column=1, columnspan=3, sticky="ew", padx=8, pady=5)
        ttk.Button(capture, text="Seçili/İlk Linki Al", command=self.pick_browser_url_from_download_box).grid(row=1, column=4, sticky="ew", padx=8, pady=5)

        ttk.Label(capture, text="Grup adı").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        ttk.Entry(capture, textvariable=self.browser_group, width=22).grid(row=2, column=1, sticky="w", padx=8, pady=5)
        ttk.Label(capture, text="Yakalama süresi dk").grid(row=2, column=2, sticky="e", padx=8, pady=5)
        ttk.Entry(capture, textvariable=self.browser_minutes, width=6).grid(row=2, column=3, sticky="w", padx=8, pady=5)
        ttk.Button(capture, text="Browser Aç + Yakala", command=lambda: self.run_in_thread(self.task_browser_capture), style="Accent.TButton").grid(row=2, column=4, sticky="ew", padx=8, pady=5)

        ttk.Checkbutton(capture, text="Arka planda aç", variable=self.browser_headless).grid(row=3, column=0, sticky="w", padx=10, pady=(4, 4))
        ttk.Checkbutton(capture, text="Skip Ad otomatik dene", variable=self.browser_auto_skip_ads).grid(row=3, column=1, sticky="w", padx=8, pady=(4, 4))
        ttk.Checkbutton(capture, text="Yakalayınca otomatik indir", variable=self.browser_auto_download).grid(row=3, column=2, sticky="w", padx=8, pady=(4, 4))
        ttk.Button(capture, text="Listeyi Arka Planda Yakala + İndir", command=lambda: self.run_in_thread(self.task_browser_batch_capture_download), style="Accent.TButton").grid(row=3, column=3, sticky="ew", padx=8, pady=(4, 4))
        ttk.Button(capture, text="Browser Motorunu Kur", command=lambda: self.run_in_thread(self.task_install_browser_engine)).grid(row=3, column=4, sticky="ew", padx=8, pady=(4, 4))

        ttk.Button(capture, text="Yakalama Uzantısı Klasörünü Aç", command=self.open_capture_extension_folder).grid(row=4, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Button(capture, text="Kısa Rehber", command=self.show_capture_help).grid(row=4, column=1, sticky="w", padx=8, pady=(0, 10))
        ttk.Button(capture, text="Panodan Ekle", command=self.paste_clipboard_to_download_box).grid(row=4, column=2, sticky="w", padx=8, pady=(0, 10))
        ttk.Button(capture, text="Kaynak Tara", command=self.source_scan_current_links).grid(row=5, column=0, sticky="w", padx=10, pady=(0, 10))
        ttk.Button(capture, text="HAR İçe Aktar", command=self.import_har_to_download_box).grid(row=5, column=1, sticky="w", padx=8, pady=(0, 10))
        ttk.Button(capture, text="Gelişmiş Rehber", command=self.show_advanced_download_help).grid(row=5, column=2, sticky="w", padx=8, pady=(0, 10))

        helpers = ttk.LabelFrame(f, text="1C) Dış yardımcı siteler / eklentiler", style="Section.TLabelframe")
        helpers.grid(row=2, column=0, sticky="ew", padx=12, pady=6)
        helpers.columnconfigure(1, weight=1)
        ttk.Label(
            helpers,
            text=(
                "SaveFrom, VDownloader, Video DownloadHelper ve Cobalt Web gibi harici yardımcıları hızlı açar. "
                "Seçili/ilk linki panoya kopyalar; yardımcıda çıkan gerçek medya linkini tekrar buraya yapıştırabilirsin."
            ),
            wraplength=980,
        ).grid(row=0, column=0, columnspan=5, sticky="w", padx=10, pady=(8, 4))

        ttk.Label(helpers, text="Yardımcı").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        ttk.Combobox(
            helpers,
            textvariable=self.external_helper,
            values=list(EXTERNAL_HELPERS.keys()),
            state="readonly",
            width=28,
        ).grid(row=1, column=1, sticky="w", padx=8, pady=7)
        ttk.Button(helpers, text="Linki Kopyala + Aç", command=self.open_external_helper_with_link).grid(row=1, column=2, sticky="ew", padx=8, pady=7)
        ttk.Button(helpers, text="Sadece Yardımcıyı Aç", command=self.open_external_helper_home).grid(row=1, column=3, sticky="ew", padx=8, pady=7)
        ttk.Button(helpers, text="Yardımcı Rehberi", command=self.show_external_helpers_help).grid(row=1, column=4, sticky="ew", padx=8, pady=7)

        settings = ttk.LabelFrame(f, text="2) İndirme ayarları", style="Section.TLabelframe")
        settings.grid(row=3, column=0, sticky="nsew", padx=12, pady=6)
        settings.columnconfigure(1, weight=1)
        settings.columnconfigure(3, weight=1)

        ttk.Label(settings, text="Ana çıktı klasörü").grid(row=0, column=0, sticky="w", padx=10, pady=7)
        ttk.Entry(settings, textvariable=self.dl_output_dir).grid(row=0, column=1, columnspan=2, sticky="ew", padx=8, pady=7)
        ttk.Button(settings, text="Seç", command=lambda: self.choose_dir(self.dl_output_dir)).grid(row=0, column=3, sticky="w", padx=8, pady=7)

        ttk.Label(settings, text="Dosya adı kökü").grid(row=1, column=0, sticky="w", padx=10, pady=7)
        self.dl_filename_base_entry = ttk.Entry(settings, textvariable=self.dl_filename_base)
        self.dl_filename_base_entry.grid(row=1, column=1, sticky="ew", padx=8, pady=7)
        ttk.Label(
            settings,
            textvariable=self.dl_name_mode_text,
            wraplength=480,
        ).grid(row=1, column=2, columnspan=2, sticky="w", padx=8, pady=7)

        ttk.Label(settings, text="Gerçek indirme klasörü").grid(row=2, column=0, sticky="w", padx=10, pady=7)
        ttk.Entry(settings, textvariable=self.dl_target_preview, state="readonly").grid(row=2, column=1, columnspan=2, sticky="ew", padx=8, pady=7)
        ttk.Button(settings, text="Klasörü Aç", command=self.open_download_target_folder).grid(row=2, column=3, sticky="w", padx=8, pady=7)

        ttk.Label(settings, text="İndirme türü / kalite").grid(row=3, column=0, sticky="w", padx=10, pady=7)
        ttk.Combobox(
            settings,
            textvariable=self.dl_mode,
            values=DOWNLOAD_QUALITY_OPTIONS,
            state="readonly",
            width=22,
        ).grid(row=3, column=1, sticky="w", padx=8, pady=7)

        ttk.Label(settings, text="İndirme motoru").grid(row=4, column=0, sticky="w", padx=10, pady=7)
        ttk.Combobox(
            settings,
            textvariable=self.dl_engine,
            values=[
                "Auto+: yt-dlp -> Cobalt -> gallery-dl -> streamlink -> direct",
                "Auto: yt-dlp -> gallery-dl -> streamlink -> direct",
                "Sadece yt-dlp",
                "Sadece Cobalt API",
                "Sadece gallery-dl",
                "Sadece streamlink",
                "Sadece you-get",
                "Sadece direct FFmpeg",
            ],
            state="readonly",
            width=42,
        ).grid(row=4, column=1, sticky="w", padx=8, pady=7)

        ttk.Label(settings, text="Hız modu").grid(row=4, column=2, sticky="e", padx=10, pady=7)
        ttk.Combobox(
            settings,
            textvariable=self.dl_speed_mode,
            values=["Normal", "Hızlı", "Agresif", "Çok Hızlı (aria2c varsa)"],
            state="readonly",
            width=15,
        ).grid(row=4, column=3, sticky="w", padx=8, pady=7)

        ttk.Label(settings, text="Cobalt API").grid(row=5, column=0, sticky="w", padx=10, pady=7)
        ttk.Entry(settings, textvariable=self.dl_cobalt_api_url).grid(row=5, column=1, sticky="ew", padx=8, pady=7)
        ttk.Entry(settings, textvariable=self.dl_cobalt_api_key, show="*").grid(row=5, column=2, sticky="ew", padx=8, pady=7)
        ttk.Label(
            settings,
            text="Cobalt ek fallback. API anahtarı gerekiyorsa sağ kutuya yaz. Boş kalırsa anahtarsız dener.",
            wraplength=300,
        ).grid(row=5, column=3, sticky="w", padx=8, pady=7)

        ttk.Checkbutton(
            settings,
            text="Zorlayıcı mod: Chrome gibi davran + header/referer dene + ek fallback motorları kullan",
            variable=self.dl_hard_mode,
        ).grid(row=6, column=1, columnspan=3, sticky="w", padx=8, pady=5)

        ttk.Checkbutton(
            settings,
            text="Adult/video-host uyum modu: yaş/consent butonlarını dene + yt-dlp age/cookie/header ayarlarını güçlendir",
            variable=self.dl_adult_profile,
        ).grid(row=7, column=1, columnspan=3, sticky="w", padx=8, pady=5)

        ttk.Checkbutton(
            settings,
            text="Playlist / seri linklerini de indir; hatalı videoyu atla, sonrakine geç",
            variable=self.dl_playlist,
        ).grid(row=8, column=1, columnspan=3, sticky="w", padx=8, pady=7)

        cookies_box = ttk.LabelFrame(f, text="2B) Tarayıcı çerezleri / oturum", style="Section.TLabelframe")
        cookies_box.grid(row=4, column=0, sticky="ew", padx=12, pady=6)
        cookies_box.columnconfigure(2, weight=1)
        ttk.Label(
            cookies_box,
            text="Tarayıcı",
            font=("Segoe UI Semibold", 10),
        ).grid(row=0, column=0, sticky="w", padx=10, pady=9)
        ttk.Combobox(
            cookies_box,
            textvariable=self.dl_cookies_browser,
            values=COOKIE_BROWSER_CHOICES,
            state="readonly",
            width=28,
        ).grid(row=0, column=1, sticky="w", padx=8, pady=9)
        ttk.Label(
            cookies_box,
            text="Varsayılan otomatik seçim Brave’i önceliklendirir; Brave profili yoksa Chrome → Edge → Firefox denenir. Yalnız kendi oturum/çerezlerin kullanılır.",
            wraplength=650,
        ).grid(row=0, column=2, sticky="w", padx=8, pady=9)

        action = ttk.Frame(f)
        action.grid(row=5, column=0, sticky="ew", padx=12, pady=(6, 12))
        action.columnconfigure(0, weight=1)

        ttk.Button(
            action,
            text="İndirmeyi Başlat",
            command=lambda: self.run_in_thread(self.task_download_url),
            style="Accent.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8), pady=8)
        ttk.Button(
            action,
            text="Hedef Klasörü Aç",
            command=self.open_download_target_folder,
        ).grid(row=0, column=1, sticky="e", padx=(8, 0), pady=8)

        note = (
            "Not: Auto+ motor önce yt-dlp, sonra Cobalt API ve diğer açık kaynak fallbackleri dener. "
            "Zorlayıcı mod bazı skip-ad/referer isteyen sayfalarda şansı artırır; DRM, ödeme duvarı, özel hesap ve teknik koruma aşmaz. "
            "Çok Hızlı modu, aria2c kuruluysa yt-dlp altında harici çok bağlantılı indirici kullanır; "
            "UniTube benzeri hız hissi en çok burada gelir. Site hız kısıyorsa mucize bekleme. v41 varsayılan olarak Hızlı modu kullanır; Zorlayıcı mod ve Adult/video-host uyum modu açık gelir. Tarayıcı çerezlerinde Brave öncelikli otomatik seçim kullanılır. aria2 yalnızca Çok Hızlı seçilirse devreye girer."
        )
        ttk.Label(f, text=note, wraplength=980).grid(row=6, column=0, sticky="w", padx=12, pady=(0, 10))

        self.dl_output_dir.trace_add("write", self.update_download_preview)
        self.dl_filename_base.trace_add("write", self.update_download_preview)
        self.update_download_preview()

    def _download_format_for_mode(self, mode: str) -> tuple[str, str | None]:
        """yt-dlp format string ve merge output format döndürür."""
        if is_mp3_download_mode(mode):
            return "bestaudio/best", None

        height_match = re.search(r"(2160|1440|1080|720|480|360)", mode or "")
        if height_match:
            h = height_match.group(1)
            # MP4 uyumlu çıktı hedeflenir; ayrı video+ses gelirse FFmpeg MP4'e birleştirir.
            return (
                f"bv*[height<={h}][vcodec^=avc1][ext=mp4]+ba[acodec^=mp4a][ext=m4a]/"
                f"bv*[height<={h}][ext=mp4]+ba[ext=m4a]/"
                f"b[height<={h}][ext=mp4]/"
                f"bv*[height<={h}]+ba/b[height<={h}]/best",
                "mp4",
            )

        if mode == "MP4 en iyi":
            return (
                "bv*[vcodec^=avc1][ext=mp4]+ba[acodec^=mp4a][ext=m4a]/"
                "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/best",
                "mp4",
            )

        return "bestvideo*+bestaudio/best", None

    def _yt_dlp_speed_opts(self) -> dict:
        """yt-dlp hız ayarları. En çok HLS/DASH parça indirmelerinde fark eder."""
        mode = self.dl_speed_mode.get()

        # UniTube benzeri hız için ana fark: aria2c harici indirici.
        # aria2c tek dosyada çok bağlantı/parça deneyebilir. Her sitede fark yaratmaz;
        # özellikle HLS/DASH veya çok parçalı kaynaklarda daha iyi çalışır.
        if mode == "Çok Hızlı (aria2c varsa)":
            opts = {
                "concurrent_fragment_downloads": 16,
                "buffersize": 1024 * 1024,
                "http_chunk_size": 10 * 1024 * 1024,
                "retries": 10,
                "fragment_retries": 10,
                "extractor_retries": 5,
                "file_access_retries": 5,
                "throttledratelimit": 100 * 1024,
            }
            if shutil.which("aria2c"):
                opts.update({
                    "external_downloader": "aria2c",
                    "external_downloader_args": {
                        "aria2c": [
                            "-x", "16",
                            "-s", "16",
                            "-k", "1M",
                            "--max-connection-per-server=16",
                            "--min-split-size=1M",
                            "--summary-interval=0",
                            "--console-log-level=warn",
                            "--allow-overwrite=true",
                            "--auto-file-renaming=false",
                        ]
                    },
                })
            else:
                self.log("aria2c bulunamadı; Çok Hızlı mod yt-dlp dahili agresif ayarlarla çalışacak.")
                self.log("aria2c kurmak için: install_aria2.bat veya PowerShell: winget install aria2")
            return opts

        if mode == "Agresif":
            return {
                "concurrent_fragment_downloads": 16,
                "buffersize": 1024 * 1024,
                "http_chunk_size": 10 * 1024 * 1024,
                "retries": 10,
                "fragment_retries": 10,
                "extractor_retries": 5,
                "file_access_retries": 5,
                "throttledratelimit": 100 * 1024,
            }
        if mode == "Hızlı":
            return {
                "concurrent_fragment_downloads": 8,
                "buffersize": 512 * 1024,
                "http_chunk_size": 5 * 1024 * 1024,
                "retries": 7,
                "fragment_retries": 7,
                "extractor_retries": 3,
                "file_access_retries": 3,
            }
        return {
            "concurrent_fragment_downloads": 3,
            "retries": 5,
            "fragment_retries": 5,
            "extractor_retries": 2,
            "file_access_retries": 2,
        }

    def task_download_url(self) -> None:
        # Normalde ekrandaki link kutusu okunur.
        # Dahili browser otomatik akışında ise geçici override metni kullanılır;
        # böylece orijinal sayfa linkleri yerine yakalanan gerçek stream adayları denenir.
        raw_override = getattr(self, "_download_raw_text_override", None)
        if raw_override is not None:
            raw_text = str(raw_override)
        else:
            raw_text = self.dl_url_text.get("1.0", "end")

        # Link kutusu grup mantığıyla okunur.
        #
        # Kullanım 1:
        #   https://site/video
        #
        # Kullanım 2:
        #   chartshunter https://site/video
        #
        # Kullanım 3:
        #   chartshunter
        #   https://site/video1
        #   https://site/video2
        #   anothername
        #   https://site/video3
        #
        # 3. kullanımda chartshunter altındaki bütün adsız linkler chartshunter
        # klasörüne iner. anothername gelince yeni klasöre geçilir.
        download_items_raw = parse_download_input_grouped(raw_text)
        download_items: list[dict[str, str | None]] = []
        for item in download_items_raw:
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            name_value = item.get("name")
            name = str(name_value).strip() if name_value else None
            ref_value = item.get("referer")
            referer = str(ref_value).strip() if ref_value else None
            download_items.append({"name": name, "url": url, "referer": referer})

        if not download_items:
            self.log("İndirilecek link yok. Linkleri kutuya yapıştır.")
            self.set_progress(0, "Link yok")
            return

        base_output_dir = Path(self.dl_output_dir.get()).expanduser()
        mode = self.dl_mode.get()
        engine_choice = self.dl_engine.get()
        speed_mode = self.dl_speed_mode.get()
        cookies_browser_choice = self.dl_cookies_browser.get()
        cookies_browser = resolve_cookie_browser_choice(cookies_browser_choice)
        hard_mode = bool(self.dl_hard_mode.get())
        adult_profile = bool(getattr(self, "dl_adult_profile", tk.BooleanVar(value=True)).get())
        adult_detected = has_adult_video_host_url(download_items)
        allow_playlist = bool(self.dl_playlist.get())
        manual_base = self.dl_filename_base.get().strip()

        has_line_names = any(item.get("name") for item in download_items)
        manual_safe_base = "" if has_line_names else (sanitize_file_base(manual_base) if manual_base else "")

        # Bu değişkenler aşağıdaki iç fonksiyonlar tarafından kullanılır.
        # Her linke geçerken güncellenir; böylece satır adlarına göre farklı klasör/prefix çalışır.
        output_dir = base_output_dir / manual_safe_base if manual_safe_base else base_output_dir
        prefix = manual_safe_base or "download"
        safe_base = manual_safe_base

        self.after(0, self.update_download_preview)

        self.log(f"Link indirme başladı. Link sayısı: {len(download_items)} | Tür: {mode}")
        cookie_display = cookies_browser.title() if cookies_browser else "Yok"
        self.log(f"Motor: {engine_choice} | Hız modu: {speed_mode} | Çerez seçimi: {cookies_browser_choice} -> {cookie_display} | Zorlayıcı mod: {'Açık' if hard_mode else 'Kapalı'} | Adult/video-host uyum: {'Açık' if adult_profile else 'Kapalı'}")
        if cookies_browser_choice == COOKIE_BROWSER_AUTO and not cookies_browser:
            self.log("Tarayıcı çerezi otomatik seçiminde kullanılabilir profil bulunamadı; çerezsiz devam edilecek.")
        self.log(f"Cobalt API: {self.dl_cobalt_api_url.get().strip() or 'Kapalı'}")
        if adult_detected:
            self.log("Adult/video-host alan adı algılandı. Uyum profili aktif: age-limit/header/referer/consent yakalama ayarları güçlendirilecek.")
            if not cookies_browser:
                self.log("Not: Bazı sitelerde yaş/giriş onayı için Brave/Chrome/Edge/Firefox oturum çerezleri gerekebilir.")
        if speed_mode == "Çok Hızlı (aria2c varsa)":
            if not shutil.which("aria2c"):
                self._ensure_system_tool("aria2c", "aria2.aria2", "aria2c hızlandırıcı", required=False)
            if shutil.which("aria2c"):
                self.log("aria2c hazır: yt-dlp harici hızlandırıcı olarak kullanılacak.")
            else:
                self.log("aria2c hazır değil; indirme yt-dlp dahili hızlı moduyla devam edecek.")

        if has_line_names:
            names = []
            for item in download_items:
                name = item.get("name")
                if name and name not in names:
                    names.append(name)
            self.log("Grup/başlık adı algılandı. Dosya adı kökü kutusu bu indirmede devre dışı kalacak.")
            self.log("Otomatik klasör/ad kökleri: " + ", ".join(names[:8]) + (" ..." if len(names) > 8 else ""))
            self.log(r"Örnek: chartshunter satırının altındaki linkler -> chartshunter\chartshunter0001.mp4")
        elif manual_safe_base:
            self.log(f"Dosya adı kökü: {manual_safe_base}")
            self.log(f"Otomatik klasör: {(base_output_dir / manual_safe_base).name}")
            self.log(f"Dosya adlandırma: {manual_safe_base}0001, {manual_safe_base}0002 ...")
        else:
            self.log("Dosya adı kökü boş. yt-dlp kaynak başlığına göre adlandırır; fallback motorlar download0001 diye adlandırır.")

        self.log("Hatalı link/playlist öğesi olursa atlanacak ve sıradakine geçilecek.")
        self.set_progress(0, "Link indirme başladı")
        self.set_download_speed("-")

        if (is_mp4_download_mode(mode) or is_mp3_download_mode(mode)) and shutil.which("ffmpeg") is None:
            self.log("FFmpeg şu anda kurulu değil. Yalnızca indirme gerçekten FFmpeg gerektirirse otomatik hazırlanacak.")

        total_urls = max(1, len(download_items))
        format_string, merge_format = self._download_format_for_mode(mode)
        browser_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/121.0.0.0 Safari/537.36"
        )
        current_link_context = {"referer": None, "index": 0, "total": total_urls, "label": ""}

        def current_referer(default_url: str) -> str:
            return str(current_link_context.get("referer") or default_url)

        def current_adult_profile(url: str) -> bool:
            return bool(adult_profile or is_adult_video_host_url(url))

        def current_hard_mode(url: str) -> bool:
            # Adult/video-host profili açıksa hard davranışı otomatik kullanılır.
            return bool(hard_mode or current_adult_profile(url))

        def progress_prefix() -> str:
            idx = int(current_link_context.get("index") or 0)
            total = int(current_link_context.get("total") or total_urls)
            return f"Video {idx}/{total}" if idx > 0 else "Video"

        def engine_timeout(url: str, normal: float = 180.0) -> float:
            # VK erişilemez linklerde motor zincirinin dakikalarca takılmasını engeller.
            return 75.0 if is_vk_url(url) else normal

        def existing_files_snapshot() -> set[Path]:
            try:
                return {p.resolve() for p in output_dir.rglob("*") if p.is_file()}
            except Exception:
                return set()

        def new_files_since(before: set[Path]) -> list[Path]:
            try:
                after = [p for p in output_dir.rglob("*") if p.is_file() and p.resolve() not in before]
                return sorted(after, key=lambda x: str(x).lower())
            except Exception:
                return []

        def make_final_path(ext: str) -> Path:
            return next_numbered_path(output_dir, prefix, ext)

        def convert_to_mp3(src: Path) -> Path | None:
            if not self._ensure_system_tool("ffmpeg", "Gyan.FFmpeg", "FFmpeg", required=True):
                return None
            dst = make_final_path(".mp3")
            try:
                run_ffmpeg(["ffmpeg", "-y", "-i", str(src), "-vn", "-codec:a", "libmp3lame", "-b:a", f"{mp3_quality_for_mode(mode)}k", str(dst)], self.cancel_event)
                return dst if dst.exists() else None
            except Exception as e:
                self.log(f"MP3 dönüştürme hatası: {e}")
                return None

        def run_process_capture(args: list[str], timeout: float | None = None) -> tuple[bool, str]:
            """
            CLI motorlarını çıktı gelmese bile gerçek zaman aşımıyla durdurur.
            Eski readline() akışı bazı VK/host hatalarında satır üretmeyip uzun süre bekleyebiliyordu.
            """
            process = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
                bufsize=1,
                **subprocess_hidden_kwargs(),
            )
            output_lines: list[str] = []
            start_time = time.time()
            last_log = 0.0
            line_queue: queue.Queue = queue.Queue()

            def _reader() -> None:
                try:
                    if process.stdout is not None:
                        for line in iter(process.stdout.readline, ""):
                            line_queue.put(line)
                finally:
                    line_queue.put(None)

            threading.Thread(target=_reader, daemon=True).start()

            try:
                reader_done = False
                while True:
                    if self.is_cancelled():
                        stop_process_quietly(process)
                        raise UserCancelled("İndirme kullanıcı tarafından iptal edildi.")

                    if timeout is not None and time.time() - start_time > timeout:
                        stop_process_quietly(process)
                        msg = f"Zaman aşımı ({int(timeout)} sn)"
                        self.log(msg + "; sıradaki motor/link denenecek.")
                        return False, msg

                    try:
                        line = line_queue.get(timeout=0.20)
                    except queue.Empty:
                        line = ""

                    if line is None:
                        reader_done = True
                    elif line:
                        clean = line.strip()
                        if clean:
                            output_lines.append(clean)
                            if is_fatal_download_error_text(clean):
                                stop_process_quietly(process)
                                raise FatalDownloadError(clean)

                            speed_text = extract_speed_from_line(clean)
                            if speed_text:
                                self.set_download_speed(speed_text)

                            if time.time() - last_log >= 8:
                                self.log(clean[:220])
                                last_log = time.time()

                    if process.poll() is not None and (reader_done or line_queue.empty()):
                        break

                return process.returncode == 0, "\n".join(output_lines[-80:])
            finally:
                if process.poll() is None:
                    stop_process_quietly(process)

        def is_intermediate_download_file(path: Path) -> bool:
            low = path.name.lower()
            return (
                low.endswith((".part", ".ytdl", ".temp", ".tmp"))
                or bool(re.search(r"\.f\d+\.[^.]+$", low))
                or ".part-" in low
            )

        def complete_media_files(paths: list[Path]) -> list[Path]:
            result: list[Path] = []
            for path in paths:
                try:
                    if (
                        path.is_file()
                        and path.stat().st_size > 0
                        and path.suffix.lower() in MEDIA_EXTENSIONS
                        and not is_intermediate_download_file(path)
                    ):
                        result.append(path)
                except Exception:
                    continue
            return result

        def probe_stream_types(path: Path) -> set[str]:
            ffprobe = shutil.which("ffprobe")
            if not ffprobe:
                return set()
            try:
                cp = subprocess.run(
                    [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    timeout=15,
                    **subprocess_hidden_kwargs(),
                )
                data = json.loads(cp.stdout or "{}") if cp.returncode == 0 else {}
                return {
                    str(item.get("codec_type") or "").lower()
                    for item in data.get("streams", [])
                    if isinstance(item, dict)
                }
            except Exception:
                return set()

        def recover_split_media_parts(before: set[Path]) -> Path | None:
            """
            yt-dlp video ve sesi indirmiş ama FFmpeg birleşimi yarıda kalmışsa
            .fXXX video/ses parçalarını tek MP4 olarak toparlamayı dener.
            """
            created = new_files_since(before)
            part_files = [
                p for p in created
                if p.suffix.lower() in MEDIA_EXTENSIONS and is_intermediate_download_file(p)
            ]
            if len(part_files) < 2:
                return None
            if not self._ensure_system_tool("ffmpeg", "Gyan.FFmpeg", "FFmpeg", required=True):
                return None

            groups: dict[str, list[Path]] = {}
            for path in part_files:
                base = re.sub(r"\.f\d+$", "", path.stem, flags=re.IGNORECASE)
                groups.setdefault(base, []).append(path)

            for base, files in groups.items():
                typed = [(p, probe_stream_types(p)) for p in files]
                video = next((p for p, kinds in typed if "video" in kinds), None)
                audio = next((p for p, kinds in typed if "audio" in kinds and "video" not in kinds), None)
                if video is None or audio is None:
                    continue

                target = output_dir / f"{base}.mp4"
                if target.exists():
                    target = make_final_path(".mp4")

                attempts = [
                    [
                        "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
                        "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
                        "-movflags", "+faststart", str(target),
                    ],
                    [
                        "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(target),
                    ],
                    [
                        "ffmpeg", "-y", "-i", str(video), "-i", str(audio),
                        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "20", "-c:a", "aac",
                        "-b:a", "192k", "-movflags", "+faststart", str(target),
                    ],
                ]

                for attempt_no, args in enumerate(attempts, start=1):
                    try:
                        self.set_progress(94, f"{progress_prefix()} • parçalar birleştiriliyor ({attempt_no}/3)")
                        self.set_download_speed("birleştiriliyor")
                        run_ffmpeg(args, self.cancel_event)
                        if target.exists() and target.stat().st_size > 0:
                            self.log(f"Parça kurtarma başarılı: {target.name}")
                            for part in files:
                                try:
                                    part.unlink(missing_ok=True)
                                except Exception:
                                    pass
                            return target
                    except UserCancelled:
                        raise
                    except Exception as e:
                        self.log(f"Parça birleştirme denemesi {attempt_no}/3 başarısız: {str(e)[:220]}")
                        try:
                            target.unlink(missing_ok=True)
                        except Exception:
                            pass

            return None

        def try_ytdlp(url: str) -> bool:
            if not self._ensure_python_component("yt_dlp", "yt-dlp indirme motoru", ["yt-dlp"], ["yt_dlp"], weekly_update=True):
                return False
            try:
                import yt_dlp
            except Exception as e:
                self.log(f"yt-dlp yüklenemedi: {e}")
                return False

            self.log("Motor denemesi: yt-dlp")
            before = existing_files_snapshot()
            last_log_time = 0.0
            last_speed_sample = {"time": time.time(), "bytes": 0.0}
            ydl_errors: list[str] = []

            class _YDLLogger:
                def debug(_self, msg):
                    return None
                def info(_self, msg):
                    return None
                def warning(_self, msg):
                    if is_fatal_download_error_text(str(msg)):
                        ydl_errors.append(str(msg))
                def error(_self, msg):
                    ydl_errors.append(str(msg))

            autonumber_start = next_number_index(output_dir, safe_base) if safe_base else 1
            if safe_base:
                outtmpl = str(output_dir / f"{safe_base}%(autonumber)04d.%(ext)s")
                self.log(f"Dosya numarası bu link için {autonumber_start:04d} değerinden başlayacak.")
            else:
                outtmpl = str(output_dir / "%(title).160B [%(id)s].%(ext)s")

            def _hook(d):
                nonlocal last_log_time
                if self.is_cancelled():
                    raise UserCancelled("İndirme kullanıcı tarafından iptal edildi.")

                status = d.get("status")
                current_time = time.time()
                if status == "downloading":
                    downloaded = float(d.get("downloaded_bytes") or 0)
                    total = float(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                    file_percent = max(0.0, min(100.0, downloaded / total * 100)) if total > 0 else 0.0
                    self.set_progress(file_percent, f"{progress_prefix()} • yt-dlp indiriyor | Dosya %{file_percent:.1f}")

                    if current_time - last_log_time >= 5:
                        extra = "boyut bilinmiyor"
                        if total > 0:
                            extra = f"{downloaded / (1024 * 1024):.1f}/{total / (1024 * 1024):.1f} MB"
                        speed = d.get("speed") or 0
                        eta = d.get("eta")

                        # Bazı kaynaklarda yt-dlp hız bilgisini doğrudan vermez.
                        # O durumda son ölçümden hesaplayıp ekranda gösteriyoruz.
                        if not speed:
                            dt = current_time - float(last_speed_sample["time"])
                            db = downloaded - float(last_speed_sample["bytes"])
                            if dt > 0.5 and db > 0:
                                speed = db / dt

                        if speed:
                            speed_readable = format_download_speed(speed)
                            speed_line = speed_readable
                            if eta is not None:
                                speed_line += f" | kalan {normal_time(float(eta))}"
                            self.set_download_speed(speed_line)
                            extra += f" | hız {speed_readable}"

                        if eta is not None:
                            extra += f" | kalan {normal_time(float(eta))}"

                        self.log(f"yt-dlp durum: %{file_percent:.1f} | {extra}")
                        last_log_time = current_time
                        last_speed_sample["time"] = current_time
                        last_speed_sample["bytes"] = downloaded

                elif status == "finished":
                    filename = d.get("filename") or "dosya"
                    self.set_progress(90, f"{progress_prefix()} • indirme bitti, dönüştürme/birleştirme")
                    self.set_download_speed("işleniyor")
                    self.log(f"yt-dlp indirme tamamlandı, işleniyor: {Path(filename).name}")

            ydl_opts = {
                "outtmpl": outtmpl,
                "windowsfilenames": True,
                "noplaylist": not allow_playlist,
                "progress_hooks": [_hook],
                "logger": _YDLLogger(),
                "ignoreerrors": bool(allow_playlist),
                "continuedl": True,
                "skip_unavailable_fragments": True,
                "autonumber_start": autonumber_start,
                "overwrites": False,
                "restrictfilenames": False,
                "verbose": False,
                "format": format_string,
                "socket_timeout": 20,
                **self._yt_dlp_speed_opts(),
            }

            # VK erişilemez/private linklerde uzun retry zinciri yerine hızla sıradaki videoya geç.
            if is_vk_url(url):
                ydl_opts.update({
                    "socket_timeout": 15,
                    "retries": 2,
                    "fragment_retries": 3,
                    "extractor_retries": 1,
                    "file_access_retries": 1,
                })

            if merge_format or is_mp3_download_mode(mode):
                if not self._ensure_system_tool("ffmpeg", "Gyan.FFmpeg", "FFmpeg", required=True):
                    self.log("FFmpeg hazırlanamadığı için video/ses parçaları birleştirilemedi.")
                    return False
                ffmpeg_bin = shutil.which("ffmpeg")
                if ffmpeg_bin:
                    ydl_opts["ffmpeg_location"] = str(Path(ffmpeg_bin).parent)

            if merge_format:
                ydl_opts["merge_output_format"] = merge_format

            if is_mp3_download_mode(mode):
                ydl_opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": mp3_quality_for_mode(mode),
                }]

            if current_hard_mode(url):
                # Bazı sayfalar medya isteğinde tarayıcı başlığı/referer bekler.
                # Bu DRM/koruma aşmaz; sadece erişilebilir sayfaya daha gerçekçi HTTP isteği gönderir.
                ydl_opts["http_headers"] = {
                    "User-Agent": browser_user_agent,
                    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
                    "Referer": current_referer(url),
                }

            if current_adult_profile(url):
                # Adult/video-host uyum profili: public ve erişilebilir videolarda
                # yaş/ülke/consent kaynaklı extractor nazlarını azaltmaya çalışır.
                # Bu DRM/ödeme duvarı/özel hesap aşmaz.
                ydl_opts["age_limit"] = 18
                ydl_opts["geo_bypass"] = True
                ydl_opts["http_headers"] = {
                    **ydl_opts.get("http_headers", {}),
                    "User-Agent": browser_user_agent,
                    "Accept-Language": "en-US,en;q=0.9,tr-TR;q=0.8,tr;q=0.7",
                    "Referer": current_referer(url),
                }

            if cookies_browser:
                self.log(f"yt-dlp tarayıcı çerezleri kullanılacak: {cookies_browser.title()}")
                ydl_opts["cookiesfrombrowser"] = (cookies_browser,)

            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])

                created = new_files_since(before)
                finals = complete_media_files(created)
                if finals:
                    for f in finals[:10]:
                        self.log(f"Yeni dosya: {f.name}")
                    return True

                fatal_msg = next((msg for msg in ydl_errors if is_fatal_download_error_text(msg)), None)
                if fatal_msg:
                    raise FatalDownloadError(fatal_msg)

                recovered = recover_split_media_parts(before)
                if recovered is not None:
                    return True

                if created:
                    self.log("yt-dlp dosya/parça üretti ancak tamamlanmış medya bulunamadı; fallback motora geçiliyor.")
                return False
            except UserCancelled:
                raise
            except FatalDownloadError:
                raise
            except Exception as e:
                fatal_msg = next((msg for msg in ydl_errors if is_fatal_download_error_text(msg)), None)
                if fatal_msg or is_fatal_download_error_text(str(e)):
                    raise FatalDownloadError(fatal_msg or str(e))

                recovered = recover_split_media_parts(before)
                if recovered is not None:
                    return True

                self.log(f"yt-dlp başarısız: {e}")
                return False

        def try_ytdlp_cli_hard(url: str) -> bool:
            """yt-dlp komut satırıyla daha zorlayıcı deneme: Chrome impersonation + header/referer.

            Bu, özellikle bazı sitelerde tarayıcı TLS/HTTP imzası veya referer bekleyen
            erişilebilir videolarda şansı artırır. DRM, ödeme duvarı veya özel hesap aşmaz.
            """
            if not current_hard_mode(url):
                return False
            if not self._ensure_python_component("yt_dlp", "yt-dlp indirme motoru", ["yt-dlp"], ["yt_dlp"], weekly_update=True):
                return False
            self._ensure_python_component("curl_cffi", "Tarayıcı uyumluluk katmanı", ["curl_cffi"], ["curl_cffi"], weekly_update=True)

            self.log("Motor denemesi: yt-dlp zorlayıcı CLI")
            before = existing_files_snapshot()

            autonumber_start = next_number_index(output_dir, safe_base) if safe_base else 1
            if safe_base:
                outtmpl = str(output_dir / f"{safe_base}%(autonumber)04d.%(ext)s")
                self.log(f"Zorlayıcı CLI dosya numarası {autonumber_start:04d} değerinden başlayacak.")
            else:
                outtmpl = str(output_dir / "%(title).160B [%(id)s].%(ext)s")

            args = python_module_or_exe("yt_dlp", "yt-dlp")
            args += ["--ignore-errors", "--continue", "--no-overwrites", "--windows-filenames"]
            if safe_base:
                args += ["--autonumber-start", str(autonumber_start)]
            args += ["--no-playlist"] if not allow_playlist else ["--yes-playlist"]
            args += ["-f", format_string, "-o", outtmpl]

            if merge_format:
                args += ["--merge-output-format", merge_format]
            if is_mp3_download_mode(mode):
                args += ["-x", "--audio-format", "mp3", "--audio-quality", f"{mp3_quality_for_mode(mode)}K"]

            # Hız: yt-dlp tarafında parça sayısını artır; aria2c varsa dış indirici olarak dene.
            if speed_mode in {"Agresif", "Çok Hızlı (aria2c varsa)"}:
                args += ["-N", "16"]
            elif speed_mode == "Hızlı":
                args += ["-N", "8"]
            else:
                args += ["-N", "3"]

            if speed_mode == "Çok Hızlı (aria2c varsa)" and shutil.which("aria2c"):
                args += [
                    "--downloader", "aria2c",
                    "--downloader-args", "aria2c:-x 16 -s 16 -k 1M --max-connection-per-server=16 --min-split-size=1M --summary-interval=0 --console-log-level=warn"
                ]

            # Tarayıcı gibi davranma. curl_cffi yüklüyse --impersonate chrome çalışır; değilse yt-dlp uyarı verir.
            args += ["--impersonate", "chrome"]
            args += ["--add-header", f"User-Agent:{browser_user_agent}"]
            args += ["--add-header", "Accept-Language:tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"]
            args += ["--referer", current_referer(url)]

            if current_adult_profile(url):
                args += ["--age-limit", "18", "--geo-bypass"]

            if cookies_browser != "Yok":
                args += ["--cookies-from-browser", cookies_browser.lower()]

            args.append(url)

            ok, out = run_process_capture(args)
            created = new_files_since(before)
            if created:
                for f in created[:10]:
                    self.log(f"yt-dlp zorlayıcı yeni dosya: {f.name}")
                return True
            if not ok:
                self.log(f"yt-dlp zorlayıcı başarısız: {out[-700:] if out else 'çıktı yok'}")
            return False

        def try_cobalt_api(url: str) -> bool:
            """Cobalt API fallback.

            Cobalt, public ve erişilebilir sosyal medya/video linkleri için ek bir motor gibi denenir.
            API instance adresi ayarlardan alınır. Eğer instance bot koruması, rate limit veya
            API anahtarı isterse temiz şekilde başarısız sayılır ve sonraki motora geçilir.
            """
            api_base = self.dl_cobalt_api_url.get().strip().rstrip("/")
            if not api_base:
                self.log("Cobalt API adresi boş; Cobalt atlandı.")
                return False

            self.log("Motor denemesi: Cobalt API")
            before = existing_files_snapshot()

            if not self._ensure_python_component("requests", "Cobalt bağlantı bileşeni", ["requests"], ["requests"], weekly_update=True):
                return False
            try:
                import requests
            except Exception as e:
                self.log(f"requests yüklenemedi, Cobalt atlandı: {e}")
                return False

            quality = "1080"
            hmatch = re.search(r"(2160|1440|1080|720|480|360)", mode or "")
            if hmatch:
                quality = hmatch.group(1)
            elif "en iyi" in (mode or "").lower() or "orijinal" in (mode or "").lower():
                quality = "max"

            payload = {
                "url": url,
                "downloadMode": "audio" if is_mp3_download_mode(mode) else "auto",
                "audioFormat": "mp3",
                "audioBitrate": mp3_quality_for_mode(mode),
                "filenameStyle": "basic",
                "videoQuality": quality,
                "youtubeVideoContainer": "mp4" if is_mp4_download_mode(mode) else "auto",
                "youtubeVideoCodec": "h264",
                "disableMetadata": True,
                "alwaysProxy": False,
                "localProcessing": "disabled",
            }
            headers = {"Accept": "application/json", "Content-Type": "application/json", "User-Agent": browser_user_agent}
            key = self.dl_cobalt_api_key.get().strip()
            if key:
                # Cobalt instance'ları genelde Authorization: Api-Key <key> kabul eder.
                # Kullanıcı Bearer ile vermek isterse tamamını yazabilir.
                if key.lower().startswith(("api-key ", "bearer ")):
                    headers["Authorization"] = key
                else:
                    headers["Authorization"] = f"Api-Key {key}"

            def post_endpoint(endpoint: str):
                return requests.post(api_base + endpoint, json=payload, headers=headers, timeout=45)

            try:
                resp = post_endpoint("/")
                if resp.status_code in {404, 405}:
                    # Eski/fork Cobalt API'lerinde endpoint /api/json olabilir.
                    resp = post_endpoint("/api/json")
                if resp.status_code in {401, 403, 429}:
                    self.log(f"Cobalt API erişim/rate-limit döndürdü: HTTP {resp.status_code}")
                    return False
                if resp.status_code >= 400:
                    self.log(f"Cobalt API HTTP hatası: {resp.status_code}")
                    return False
                data = resp.json()
            except Exception as e:
                self.log(f"Cobalt API isteği başarısız: {e}")
                return False

            status = str(data.get("status") or data.get("type") or "").lower()
            if status == "error":
                err = data.get("error") or {}
                self.log(f"Cobalt API hata: {err.get('code') or err}")
                return False

            candidate_urls: list[str] = []
            for keyname in ["url", "audio", "stream", "download", "redirect"]:
                val = data.get(keyname)
                if isinstance(val, str) and val.startswith(("http://", "https://")):
                    candidate_urls.append(val)
            tunnels = data.get("tunnel")
            if isinstance(tunnels, list):
                for t in tunnels:
                    if isinstance(t, str):
                        candidate_urls.append(t if t.startswith(("http://", "https://")) else api_base + t)
            picker = data.get("picker")
            if isinstance(picker, list):
                # Video öncelikli; yoksa ilk medya linki.
                sorted_picker = sorted(picker, key=lambda x: 0 if str(x.get("type", "")).lower() == "video" else 1) if all(isinstance(x, dict) for x in picker) else []
                for item in sorted_picker:
                    val = item.get("url")
                    if isinstance(val, str) and val.startswith(("http://", "https://")):
                        candidate_urls.append(val)

            # Aynı linkleri teke indir.
            seen = set()
            candidate_urls = [x for x in candidate_urls if not (x in seen or seen.add(x))]
            if not candidate_urls:
                self.log(f"Cobalt API medya linki döndürmedi. Durum: {status or data}")
                return False

            def ext_from_response_url(media_url: str, r=None) -> str:
                if is_mp3_download_mode(mode):
                    return ".mp3"
                if is_mp4_download_mode(mode):
                    return ".mp4"
                ctype = ""
                if r is not None:
                    ctype = (r.headers.get("Content-Type") or "").lower()
                if "audio" in ctype:
                    return ".mp3"
                if "webm" in ctype or media_url.lower().split("?")[0].endswith(".webm"):
                    return ".webm"
                if "mpegurl" in ctype or media_url.lower().split("?")[0].endswith(".m3u8"):
                    return ".mp4"
                return ".mp4"

            for media_url in candidate_urls[:4]:
                if self.is_cancelled():
                    raise UserCancelled("İndirme kullanıcı tarafından iptal edildi.")
                try:
                    # HLS/DASH gibi doğrudan FFmpeg isteyen linkse mevcut FFmpeg motoruna devret.
                    if media_url.lower().split("?")[0].endswith((".m3u8", ".mpd")):
                        old_ref = current_link_context.get("referer")
                        current_link_context["referer"] = current_referer(url)
                        ok = try_direct_ffmpeg(media_url)
                        current_link_context["referer"] = old_ref
                        if ok:
                            return True
                        continue

                    with requests.get(media_url, headers={"User-Agent": browser_user_agent, "Referer": current_referer(url)}, stream=True, timeout=45) as r:
                        if r.status_code >= 400:
                            self.log(f"Cobalt çıktı linki HTTP {r.status_code}: {media_url[:120]}")
                            continue
                        ext = ext_from_response_url(media_url, r)
                        out = make_final_path(ext)
                        total = int(r.headers.get("Content-Length") or r.headers.get("Estimated-Content-Length") or 0)
                        downloaded = 0
                        started = time.time()
                        last_log = 0.0
                        with open(out, "wb") as f:
                            for chunk in r.iter_content(chunk_size=1024 * 512):
                                if self.is_cancelled():
                                    raise UserCancelled("İndirme kullanıcı tarafından iptal edildi.")
                                if not chunk:
                                    continue
                                f.write(chunk)
                                downloaded += len(chunk)
                                now = time.time()
                                if total > 0:
                                    pct = downloaded / total * 100
                                    self.set_progress(pct, f"Cobalt indiriyor | Dosya %{pct:.1f}")
                                if now - last_log >= 5:
                                    dt = max(0.1, now - started)
                                    self.set_download_speed(format_download_speed(downloaded / dt))
                                    last_log = now
                        if out.exists() and out.stat().st_size > 0:
                            self.log(f"Cobalt API kaydedildi: {out.name}")
                            return True
                except UserCancelled:
                    raise
                except Exception as e:
                    self.log(f"Cobalt çıktı indirme başarısız: {e}")
                    continue

            created = new_files_since(before)
            return bool(created)

        def try_you_get(url: str) -> bool:
            """Ek açık kaynak fallback: you-get.

            Bazı sitelerde yt-dlp'nin yakalayamadığı basit embed/medya sayfalarında işe yarayabilir.
            Çalışırsa çıkan dosyayı bizim klasör/ad sistemimize taşır veya MP3'e çevirir.
            """
            if not self._ensure_python_component("you_get", "you-get fallback motoru", ["you-get"], ["you_get"], weekly_update=True):
                return False
            self.log("Motor denemesi: you-get")
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                tmp_name = f"_youget_{int(time.time())}"
                args = python_module_or_exe("you_get", "you-get") + ["-o", str(tmp), "-O", tmp_name]
                if allow_playlist:
                    args += ["--playlist"]
                args.append(url)

                ok, out = run_process_capture(args)
                if not ok:
                    self.log(f"you-get başarısız: {out[-500:] if out else 'çıktı yok'}")
                    return False

                files = [p for p in tmp.rglob("*") if p.is_file()]
                if not files:
                    self.log("you-get dosya üretmedi.")
                    return False

                moved = 0
                for src in files:
                    ext = src.suffix.lower() or ".bin"
                    if is_mp3_download_mode(mode):
                        if ext in MEDIA_EXTENSIONS:
                            dst = convert_to_mp3(src)
                            if dst:
                                moved += 1
                                self.log(f"you-get -> MP3: {dst.name}")
                        continue

                    if mode.startswith("MP4"):
                        if ext not in MEDIA_EXTENSIONS:
                            continue
                        # Video ise mp4 hedefle; ses dosyası geldiyse uzantısını koru.
                        final_ext = ".mp4" if ext not in {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"} else ext
                        dst = make_final_path(final_ext)
                    else:
                        dst = make_final_path(ext)

                    try:
                        shutil.move(str(src), str(dst))
                        moved += 1
                        self.log(f"you-get dosyası kaydedildi: {dst.name}")
                    except Exception as e:
                        self.log(f"you-get taşıma hatası: {e}")

                return moved > 0

        def try_gallery_dl(url: str) -> bool:
            if not self._ensure_python_component("gallery_dl", "gallery-dl fallback motoru", ["gallery-dl"], ["gallery_dl"], weekly_update=True):
                return False
            self.log("Motor denemesi: gallery-dl")
            with tempfile.TemporaryDirectory() as td:
                tmp = Path(td)
                args = python_module_or_exe("gallery_dl", "gallery-dl") + ["-D", str(tmp), url]
                ok, out = run_process_capture(args)
                if not ok:
                    self.log(f"gallery-dl başarısız: {out[-500:] if out else 'çıktı yok'}")
                    return False

                files = [p for p in tmp.rglob("*") if p.is_file()]
                if not files:
                    self.log("gallery-dl dosya üretmedi.")
                    return False

                moved = 0
                for src in files:
                    ext = src.suffix.lower() or ".bin"
                    if is_mp3_download_mode(mode):
                        if ext in MEDIA_EXTENSIONS:
                            dst = convert_to_mp3(src)
                            if dst:
                                moved += 1
                                self.log(f"gallery-dl -> MP3: {dst.name}")
                        continue

                    if mode.startswith("MP4"):
                        if ext not in MEDIA_EXTENSIONS:
                            continue
                        final_ext = ".mp4" if ext not in {".mp3", ".m4a", ".wav", ".aac", ".flac", ".ogg"} else ext
                        dst = make_final_path(final_ext)
                    else:
                        dst = make_final_path(ext)

                    try:
                        shutil.move(str(src), str(dst))
                        moved += 1
                        self.log(f"gallery-dl dosyası kaydedildi: {dst.name}")
                    except Exception as e:
                        self.log(f"gallery-dl taşıma hatası: {e}")

                return moved > 0

        def try_streamlink(url: str) -> bool:
            if not self._ensure_python_component("streamlink", "streamlink fallback motoru", ["streamlink"], ["streamlink"], weekly_update=True):
                return False
            self.log("Motor denemesi: streamlink")
            if is_mp3_download_mode(mode):
                if shutil.which("ffmpeg") is None:
                    self.log("streamlink sonrası MP3 için FFmpeg gerekli.")
                    return False
                temp_out = output_dir / f"_temp_streamlink_{int(time.time())}.ts"
                quality = quality_to_streamlink(mode)
                args = python_module_or_exe("streamlink", "streamlink") + ["--force", "--retry-streams", "3"]
                if current_hard_mode(url):
                    args += ["--http-header", f"Referer={current_referer(url)}", "--http-header", f"User-Agent={browser_user_agent}"]
                args += ["-o", str(temp_out), url, quality]
                ok, out = run_process_capture(args)
                if not ok or not temp_out.exists():
                    self.log(f"streamlink başarısız: {out[-500:] if out else 'çıktı yok'}")
                    return False
                dst = convert_to_mp3(temp_out)
                try:
                    temp_out.unlink(missing_ok=True)
                except Exception:
                    pass
                if dst:
                    self.log(f"streamlink -> MP3 kaydedildi: {dst.name}")
                    return True
                return False

            out = make_final_path(".mp4")
            quality = quality_to_streamlink(mode)
            args = python_module_or_exe("streamlink", "streamlink") + ["--force", "--retry-streams", "3"]
            if current_hard_mode(url):
                args += ["--http-header", f"Referer={current_referer(url)}", "--http-header", f"User-Agent={browser_user_agent}"]
            args += ["-o", str(out), url, quality]
            ok, out_text = run_process_capture(args)
            if ok and out.exists() and out.stat().st_size > 0:
                self.log(f"streamlink kaydedildi: {out.name}")
                return True
            self.log(f"streamlink başarısız: {out_text[-500:] if out_text else 'çıktı yok'}")
            try:
                if out.exists() and out.stat().st_size == 0:
                    out.unlink()
            except Exception:
                pass
            return False

        def try_direct_ffmpeg(url: str) -> bool:
            self.log("Motor denemesi: direct FFmpeg")
            if not self._ensure_system_tool("ffmpeg", "Gyan.FFmpeg", "FFmpeg", required=True):
                return False
            if not is_probable_direct_media_url(url):
                self.log("Bu link doğrudan medya/m3u8/mpd gibi görünmüyor; FFmpeg denemesi yine yapılacak.")

            ffmpeg_headers = (
                f"Referer: {current_referer(url)}\r\n"
                f"User-Agent: {browser_user_agent}\r\n"
                "Accept-Language: tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7\r\n"
            )
            header_args = ["-headers", ffmpeg_headers] if current_hard_mode(url) else []

            if is_mp3_download_mode(mode):
                out = make_final_path(".mp3")
                args = ["ffmpeg", "-y", *header_args, "-i", url, "-vn", "-codec:a", "libmp3lame", "-b:a", f"{mp3_quality_for_mode(mode)}k", str(out)]
            else:
                out = make_final_path(".mp4")
                args = ["ffmpeg", "-y", *header_args, "-i", url, "-c", "copy", str(out)]
            try:
                run_ffmpeg(args, self.cancel_event)
                if out.exists() and out.stat().st_size > 0:
                    self.log(f"direct FFmpeg kaydedildi: {out.name}")
                    return True
            except UserCancelled:
                raise
            except Exception as e:
                self.log(f"direct FFmpeg başarısız: {e}")
            try:
                if out.exists() and out.stat().st_size == 0:
                    out.unlink()
            except Exception:
                pass
            return False

        def engines_for_choice() -> list:
            if engine_choice == "Sadece yt-dlp":
                return [try_ytdlp, try_ytdlp_cli_hard] if (hard_mode or adult_profile or adult_detected) else [try_ytdlp]
            if engine_choice == "Sadece Cobalt API":
                return [try_cobalt_api]
            if engine_choice == "Sadece gallery-dl":
                return [try_gallery_dl]
            if engine_choice == "Sadece streamlink":
                return [try_streamlink]
            if engine_choice == "Sadece you-get":
                return [try_you_get]
            if engine_choice == "Sadece direct FFmpeg":
                return [try_direct_ffmpeg]
            if engine_choice.startswith("Auto+:"):
                if hard_mode or adult_profile or adult_detected:
                    return [try_ytdlp, try_ytdlp_cli_hard, try_cobalt_api, try_you_get, try_gallery_dl, try_streamlink, try_direct_ffmpeg]
                return [try_ytdlp, try_cobalt_api, try_gallery_dl, try_streamlink, try_direct_ffmpeg]
            if hard_mode or adult_profile or adult_detected:
                return [try_ytdlp, try_ytdlp_cli_hard, try_you_get, try_gallery_dl, try_streamlink, try_direct_ffmpeg]
            return [try_ytdlp, try_gallery_dl, try_streamlink, try_direct_ffmpeg]

        success_count = 0
        failed_count = 0
        failed_links: list[str] = []

        try:
            for url_index, item in enumerate(download_items, start=1):
                if self.is_cancelled():
                    raise UserCancelled("İndirme kullanıcı tarafından iptal edildi.")

                url = str(item.get("url") or "").strip()
                line_name = str(item.get("name") or "").strip()
                link_referer = str(item.get("referer") or "").strip() or None
                current_link_context["referer"] = link_referer

                # Link grup/başlık adıyla eşleştiyse o ad mutlak önceliklidir.
                # Dosya adı kökü kutusu bu senaryoda yok sayılır.
                if line_name:
                    safe_base = line_name
                    prefix = line_name
                    output_dir = base_output_dir / line_name
                elif manual_safe_base:
                    safe_base = manual_safe_base
                    prefix = manual_safe_base
                    output_dir = base_output_dir / manual_safe_base
                else:
                    safe_base = ""
                    prefix = "download"
                    output_dir = base_output_dir

                output_dir.mkdir(parents=True, exist_ok=True)

                base_percent = (url_index - 1) / total_urls * 100
                self.set_progress(base_percent, f"Link {url_index}/{total_urls} başlıyor")
                self.log(f"Link işleniyor {url_index}/{total_urls}: {url}")
                if link_referer:
                    self.log(f"Kaynak sayfa/referer kullanılacak: {link_referer}")
                if line_name:
                    next_no = next_number_index(output_dir, line_name)
                    self.log(f"Grup adı: {line_name} | Klasör: {output_dir} | Sıradaki dosya: {line_name}{next_no:04d}...")
                elif manual_safe_base:
                    next_no = next_number_index(output_dir, manual_safe_base)
                    self.log(f"Global kök: {manual_safe_base} | Klasör: {output_dir} | Sıradaki dosya: {manual_safe_base}{next_no:04d}...")
                else:
                    self.log(f"Klasör: {output_dir}")

                ok = False
                fatal_stop = False
                for engine_func in engines_for_choice():
                    if self.is_cancelled():
                        raise UserCancelled("İndirme kullanıcı tarafından iptal edildi.")
                    try:
                        if engine_func(url):
                            ok = True
                            break
                    except UserCancelled:
                        raise
                    except FatalDownloadError as e:
                        fatal_stop = True
                        self.log(f"Net bağlantı/URL hatası yakalandı. Bu linkte denemeler durduruldu: {str(e)[:260]}")
                        self.log("Aynı bozuk stream linkini tekrar tekrar zorlamayacağım; varsa sıradaki linke geçilecek.")
                        break
                    except Exception as e:
                        if is_fatal_download_error_text(str(e)):
                            fatal_stop = True
                            self.log(f"Net bağlantı/URL hatası yakalandı. Bu linkte denemeler durduruldu: {str(e)[:260]}")
                            break
                        self.log(f"Motor hatası, sıradaki motora geçiliyor: {e}")

                if ok:
                    success_count += 1
                    self.log(f"Link tamamlandı: {url}")
                else:
                    failed_count += 1
                    failed_links.append(url)
                    if fatal_stop:
                        self.log("UYARI: Bu link net URL/DNS/erişim hatası verdi; bu link atlandı.")
                    else:
                        self.log("UYARI: Bu link hiçbir motorla indirilemedi, sıradakine geçiliyor.")

                self.set_progress(url_index / total_urls * 100, f"Link {url_index}/{total_urls} tamam")

            self.set_progress(100, "Link indirme işlemi bitti")
            self.set_download_speed("-")
            if failed_links:
                try:
                    base_output_dir.mkdir(parents=True, exist_ok=True)
                    failed_path = base_output_dir / f"failed_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    failed_path.write_text("\n".join(failed_links) + "\n", encoding="utf-8")
                    self.log(f"Başarısız link raporu yazıldı: {failed_path}")
                except Exception as e:
                    self.log(f"Başarısız link raporu yazılamadı: {e}")
            self.log(f"Link indirme bitti. Başarılı: {success_count} | Başarısız: {failed_count} | Ana çıktı: {base_output_dir}")

        except UserCancelled:
            self.set_progress(self.progress_var.get(), "İndirme iptal edildi")
            self.log("İndirme kullanıcı tarafından iptal edildi.")
        except Exception as e:
            self.log(f"HATA: Link indirme başarısız: {e}")
            self.log("Not: Her site desteklenmez; DRM/ödeme duvarı/özel hesap/teknik koruma aşılmaz.")

    # --------------------------------------------------------
    # TAB 1: VIDEO/SES -> SRT/TXT
    # --------------------------------------------------------
    def _build_transcribe_tab(self) -> None:
        f = self.tab_transcribe
        f.columnconfigure(1, weight=1)
        f.rowconfigure(1, weight=1)

        self.tr_media_files: list[Path] = []
        self.tr_output_dir = tk.StringVar(value=str(app_base_dir() / "outputs" / "transcripts"))
        self.tr_model = tk.StringVar(value="small")
        self.tr_language = tk.StringVar(value="auto")
        self.tr_progress = tk.StringVar(value="3")

        ttk.Label(f, text="İşlenecek video/ses dosyaları").grid(row=0, column=0, sticky="nw", padx=12, pady=10)

        list_frame = ttk.Frame(f)
        list_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=10)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.tr_listbox = tk.Listbox(list_frame, height=10, selectmode="extended")
        self.tr_listbox.grid(row=0, column=0, sticky="nsew")
        tr_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tr_listbox.yview)
        tr_scroll.grid(row=0, column=1, sticky="ns")
        self.tr_listbox.configure(yscrollcommand=tr_scroll.set)

        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=0, column=2, rowspan=2, sticky="ns", padx=12, pady=10)
        ttk.Button(btn_frame, text="Dosya ekle", command=lambda: self.add_files_to_path_list(
            self.tr_media_files,
            self.tr_listbox,
            [("Medya", "*.mp4 *.mkv *.webm *.mov *.avi *.m4a *.mp3 *.wav *.aac *.flac *.ogg"), ("Tüm dosyalar", "*.*")],
            "Video/ses dosyası seç"
        )).grid(row=0, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Klasörden ekle", command=lambda: self.add_folder_files_to_path_list(
            self.tr_media_files, self.tr_listbox, MEDIA_EXTENSIONS, "Video/ses klasörü seç"
        )).grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Yukarı", command=lambda: self.move_selected_in_path_list(
            self.tr_media_files, self.tr_listbox, -1
        )).grid(row=2, column=0, sticky="ew", pady=(14, 3))
        ttk.Button(btn_frame, text="Aşağı", command=lambda: self.move_selected_in_path_list(
            self.tr_media_files, self.tr_listbox, 1
        )).grid(row=3, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Seçileni sil", command=lambda: self.remove_selected_from_path_list(
            self.tr_media_files, self.tr_listbox
        )).grid(row=4, column=0, sticky="ew", pady=(14, 3))
        ttk.Button(btn_frame, text="Listeyi temizle", command=lambda: self.clear_path_list(
            self.tr_media_files, self.tr_listbox
        )).grid(row=5, column=0, sticky="ew", pady=3)

        ttk.Label(f, text="Çıktı klasörü").grid(row=2, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.tr_output_dir).grid(row=2, column=1, sticky="ew", padx=8, pady=10)
        ttk.Button(f, text="Seç", command=lambda: self.choose_dir(self.tr_output_dir)).grid(row=2, column=2, padx=12, pady=10)

        ttk.Label(f, text="Model").grid(row=3, column=0, sticky="w", padx=12, pady=10)
        ttk.Combobox(f, textvariable=self.tr_model, values=["tiny", "base", "small", "medium"], state="readonly", width=20).grid(row=3, column=1, sticky="w", padx=8, pady=10)

        ttk.Label(f, text="Dil").grid(row=4, column=0, sticky="w", padx=12, pady=10)
        ttk.Combobox(f, textvariable=self.tr_language, values=["auto", "tr", "en"], state="readonly", width=20).grid(row=4, column=1, sticky="w", padx=8, pady=10)

        ttk.Label(f, text="Durum bildirimi / dakika").grid(row=5, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.tr_progress, width=10).grid(row=5, column=1, sticky="w", padx=8, pady=10)

        ttk.Button(f, text="Listedeki Dosyalardan SRT + TXT Üret", command=lambda: self.run_in_thread(self.task_transcribe)).grid(row=6, column=0, columnspan=3, sticky="ew", padx=12, pady=18)

        note = (
            "Dosyaları tek tek ekleyebilir, yukarı/aşağı ile sırayı değiştirebilirsin. "
            "Dil 'auto' karışık klasörler için pratik; sadece Türkçe için 'tr', sadece İngilizce için 'en' daha kontrollüdür."
        )
        ttk.Label(f, text=note, wraplength=830).grid(row=7, column=0, columnspan=3, sticky="w", padx=12, pady=10)

    def task_transcribe(self) -> None:
        model_size = self.tr_model.get()
        model_path = self._ensure_whisper_model(model_size)
        if not model_path:
            return
        try:
            from faster_whisper import WhisperModel
        except Exception as e:
            self.log(f"HATA: faster-whisper yüklenemedi: {e}")
            return

        output_dir = Path(self.tr_output_dir.get())
        output_dir.mkdir(parents=True, exist_ok=True)

        language_value = self.tr_language.get()
        language = None if language_value == "auto" else language_value

        try:
            progress_interval = max(1, int(float(self.tr_progress.get()) * 60))
        except Exception:
            progress_interval = 180

        media_files = [p for p in self.tr_media_files if p.is_file() and p.suffix.lower() in MEDIA_EXTENSIONS]
        self.log(f"Listedeki medya dosyası sayısı: {len(media_files)}")

        if not media_files:
            self.log("İşlenecek medya dosyası seçilmedi. 'Dosya ekle' ile video/ses ekle.")
            self.set_progress(0, "Dosya seçilmedi")
            return

        self.set_progress(0, "Whisper modeli yükleniyor")
        self.log(f"Whisper modeli yükleniyor: {model_size}")
        model_start = time.time()
        model = WhisperModel(model_path, device="cpu", compute_type="int8")
        mark_runtime_usage("whisper", model_size)
        self.log(f"Model hazır. Yükleme süresi: {normal_time(time.time() - model_start)}")
        self.set_progress(0, "Model hazır")

        if self.is_cancelled():
            self.log("İşlem iptal edildi.")
            self.set_progress(0, "İptal edildi")
            return

        total_files = len(media_files)

        for file_no, media_file in enumerate(media_files, start=1):
            if self.is_cancelled():
                self.log("Video/Ses -> SRT işlemi iptal edildi.")
                self.set_progress(base_percent if 'base_percent' in locals() else 0, "İptal edildi")
                return
            base_percent = (file_no - 1) / total_files * 100
            self.set_progress(base_percent, f"{file_no}/{total_files} başlıyor: {media_file.name}")
            self.log(f"İşleniyor: {media_file.name}")
            file_start = time.time()

            try:
                segments, info = model.transcribe(
                    str(media_file),
                    language=language,
                    beam_size=5,
                    vad_filter=True,
                )

                total_duration = float(getattr(info, "duration", 0.0) or 0.0)
                if total_duration <= 0:
                    total_duration = get_media_duration_seconds(media_file)

                if total_duration > 0:
                    self.log(
                        f"Algılanan dil: {info.language} | Olasılık: {info.language_probability:.2f} | "
                        f"Kaynak süre: {normal_time(total_duration)}"
                    )
                else:
                    self.log(f"Algılanan dil: {info.language} | Olasılık: {info.language_probability:.2f}")
                    self.log("Kaynak süre okunamadı; yüzde yaklaşık gösterilecek.")

                srt_lines: list[str] = []
                txt_lines: list[str] = []
                segment_count = 0
                last_progress = time.time()
                last_audio_time = 0.0
                last_ui_update = 0.0

                for segment in segments:
                    if self.is_cancelled():
                        self.log("Video/Ses -> SRT işlemi iptal edildi. Mevcut dosya tamamlanmadan durdu.")
                        self.set_progress(total_percent if 'total_percent' in locals() else base_percent, "İptal edildi")
                        return

                    text = segment.text.strip()
                    if not text:
                        continue

                    segment_count += 1
                    last_audio_time = segment.end

                    srt_lines.append(str(segment_count))
                    srt_lines.append(f"{srt_time(segment.start)} --> {srt_time(segment.end)}")
                    srt_lines.append(text)
                    srt_lines.append("")
                    txt_lines.append(text)

                    current = time.time()

                    if total_duration > 0:
                        file_percent = min(100.0, max(0.0, last_audio_time / total_duration * 100))
                    else:
                        file_percent = 0.0

                    total_percent = base_percent + (file_percent / total_files)

                    # Progress bar her segmentte degil, yaklasik saniyede bir guncellenir.
                    # Boylece arayuz akici kalir, log da sismez.
                    if current - last_ui_update >= 1:
                        self.set_progress(
                            total_percent,
                            f"Toplam {file_no}/{total_files} | Dosya %{file_percent:.1f} | {media_file.name}"
                        )
                        last_ui_update = current

                    if current - last_progress >= progress_interval:
                        self.log(
                            f"Durum: {media_file.name} | %{file_percent:.1f} | "
                            f"Ses zamanı {normal_time(last_audio_time)} / {normal_time(total_duration)} | "
                            f"Geçen {normal_time(current - file_start)} | Parça {segment_count}"
                        )
                        last_progress = current

                srt_path = output_dir / f"{media_file.stem}.srt"
                txt_path = output_dir / f"{media_file.stem}.txt"
                srt_path.write_text("\n".join(srt_lines), encoding="utf-8")
                txt_path.write_text("\n".join(txt_lines), encoding="utf-8")

                done_percent = file_no / total_files * 100
                self.set_progress(done_percent, f"Tamamlandı: {media_file.name}")
                self.log(f"Tamamlandı: {media_file.name} | %100.0 | Süre: {normal_time(time.time() - file_start)}")
                self.log(f"Kaydedildi: {srt_path.name}, {txt_path.name}")

            except Exception as e:
                self.log(f"HATA: {media_file.name} işlenemedi: {e}")

        self.set_progress(100, "Video/Ses -> SRT işlemi bitti")
        self.log("Video/Ses -> SRT işlemi bitti.")

    # --------------------------------------------------------
    # TAB 2: SRT/TXT -> UK MP3
    # --------------------------------------------------------
    def _build_tts_tab(self) -> None:
        f = self.tab_tts
        f.columnconfigure(1, weight=1)
        f.rowconfigure(1, weight=1)

        self.tts_input_files: list[Path] = []
        self.tts_output_dir = tk.StringVar(value=str(app_base_dir() / "outputs" / "voice_outputs"))
        self.tts_voice_label = tk.StringVar(value="Sonia - UK kadın")
        self.tts_rate = tk.StringVar(value="-5%")
        self.tts_chunk_minutes = tk.StringVar(value="20")

        ttk.Label(f, text="İşlenecek SRT/TXT dosyaları").grid(row=0, column=0, sticky="nw", padx=12, pady=10)

        list_frame = ttk.Frame(f)
        list_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=10)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.tts_listbox = tk.Listbox(list_frame, height=10, selectmode="extended")
        self.tts_listbox.grid(row=0, column=0, sticky="nsew")
        tts_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tts_listbox.yview)
        tts_scroll.grid(row=0, column=1, sticky="ns")
        self.tts_listbox.configure(yscrollcommand=tts_scroll.set)

        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=0, column=2, rowspan=2, sticky="ns", padx=12, pady=10)
        ttk.Button(btn_frame, text="Dosya ekle", command=lambda: self.add_files_to_path_list(
            self.tts_input_files,
            self.tts_listbox,
            [("SRT/TXT", "*.srt *.txt"), ("Tüm dosyalar", "*.*")],
            "SRT/TXT dosyası seç"
        )).grid(row=0, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Klasörden ekle", command=lambda: self.add_folder_files_to_path_list(
            self.tts_input_files, self.tts_listbox, TEXT_EXTENSIONS, "SRT/TXT klasörü seç"
        )).grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Yukarı", command=lambda: self.move_selected_in_path_list(
            self.tts_input_files, self.tts_listbox, -1
        )).grid(row=2, column=0, sticky="ew", pady=(14, 3))
        ttk.Button(btn_frame, text="Aşağı", command=lambda: self.move_selected_in_path_list(
            self.tts_input_files, self.tts_listbox, 1
        )).grid(row=3, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Seçileni sil", command=lambda: self.remove_selected_from_path_list(
            self.tts_input_files, self.tts_listbox
        )).grid(row=4, column=0, sticky="ew", pady=(14, 3))
        ttk.Button(btn_frame, text="Listeyi temizle", command=lambda: self.clear_path_list(
            self.tts_input_files, self.tts_listbox
        )).grid(row=5, column=0, sticky="ew", pady=3)

        ttk.Label(f, text="Çıktı klasörü").grid(row=2, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.tts_output_dir).grid(row=2, column=1, sticky="ew", padx=8, pady=10)
        ttk.Button(f, text="Seç", command=lambda: self.choose_dir(self.tts_output_dir)).grid(row=2, column=2, padx=12, pady=10)

        ttk.Label(f, text="British UK ses").grid(row=3, column=0, sticky="w", padx=12, pady=10)
        ttk.Combobox(f, textvariable=self.tts_voice_label, values=list(UK_VOICES.keys()), state="readonly", width=24).grid(row=3, column=1, sticky="w", padx=8, pady=10)

        ttk.Label(f, text="Hız").grid(row=4, column=0, sticky="w", padx=12, pady=10)
        ttk.Combobox(f, textvariable=self.tts_rate, values=["-15%", "-10%", "-5%", "+0%", "+5%", "+10%"], state="readonly", width=12).grid(row=4, column=1, sticky="w", padx=8, pady=10)

        ttk.Label(f, text="Parça süresi / dakika").grid(row=5, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.tts_chunk_minutes, width=10).grid(row=5, column=1, sticky="w", padx=8, pady=10)

        ttk.Button(f, text="Listedeki Dosyalardan British UK MP3 Üret", command=lambda: self.run_in_thread(self.task_tts)).grid(row=6, column=0, columnspan=3, sticky="ew", padx=12, pady=18)

        note = (
            "Dosyaları tek tek seçebilir veya klasörden topluca ekleyebilirsin. Bu işlem internet ister. "
            "Uzun SRT dosyalarını kaynak zamana göre seçtiğin dakika uzunluğunda parçalara böler."
        )
        ttk.Label(f, text=note, wraplength=830).grid(row=7, column=0, columnspan=3, sticky="w", padx=12, pady=10)

    def task_tts(self) -> None:
        if not self._ensure_python_component("edge_tts", "British UK ses motoru", ["edge-tts"], ["edge_tts"], weekly_update=True):
            return
        try:
            import edge_tts
        except Exception as e:
            self.log(f"HATA: edge-tts yüklenemedi: {e}")
            return

        async def _run() -> None:
            output_dir = Path(self.tts_output_dir.get())
            output_dir.mkdir(parents=True, exist_ok=True)

            voice = UK_VOICES.get(self.tts_voice_label.get(), "en-GB-SoniaNeural")
            rate = self.tts_rate.get()
            volume = "+0%"

            try:
                chunk_minutes = max(1, int(self.tts_chunk_minutes.get()))
            except Exception:
                chunk_minutes = 20
            chunk_seconds = chunk_minutes * 60

            files = [p for p in self.tts_input_files if p.is_file() and p.suffix.lower() in TEXT_EXTENSIONS]
            self.log(f"Listedeki SRT/TXT dosyası sayısı: {len(files)}")

            if not files:
                self.log("İşlenecek SRT/TXT dosyası seçilmedi. 'Dosya ekle' ile dosya ekle.")
                self.set_progress(0, "SRT/TXT dosyası seçilmedi")
                return

            self.set_progress(0, "SRT/TXT -> UK MP3 başladı")
            total_files = len(files)

            for file_no, file in enumerate(files, start=1):
                if self.is_cancelled():
                    self.log("SRT/TXT -> UK MP3 işlemi iptal edildi.")
                    self.set_progress(0, "İptal edildi")
                    return

                base_percent = (file_no - 1) / total_files * 100
                self.set_progress(base_percent, f"{file_no}/{total_files} hazırlanıyor: {file.name}")
                self.log(f"İşleniyor: {file.name}")
                content = file.read_text(encoding="utf-8", errors="ignore")

                if file.suffix.lower() == ".srt":
                    entries = parse_srt_entries(content)
                    if not entries:
                        self.log(f"SRT okunamadı veya boş: {file.name}")
                        continue
                    text_chunks = group_srt_entries_by_time(entries, chunk_seconds)
                    self.log(f"SRT kaynak zamana göre {len(text_chunks)} parçaya bölündü.")
                else:
                    text = clean_text(content)
                    max_chars = max(3500, chunk_minutes * 750)
                    raw_chunks = split_text_by_sentences(text, max_chars=max_chars)
                    text_chunks = [
                        {"index": i, "source_start": 0, "source_end": 0, "text": chunk}
                        for i, chunk in enumerate(raw_chunks, start=1)
                    ]
                    self.log(f"TXT karaktere göre {len(text_chunks)} parçaya bölündü.")

                chunk_total = max(1, len(text_chunks))

                for chunk_no, chunk in enumerate(text_chunks, start=1):
                    if self.is_cancelled():
                        self.log("SRT/TXT -> UK MP3 işlemi iptal edildi.")
                        self.set_progress(base_percent, "İptal edildi")
                        return

                    part_no = int(chunk["index"])
                    text = clean_text(chunk["text"])
                    if not text:
                        continue

                    chunk_percent = (chunk_no - 1) / chunk_total * 100
                    total_percent = base_percent + (chunk_percent / total_files)

                    output_path = output_dir / f"{file.stem}_part_{part_no:03}_british_uk.mp3"
                    self.set_progress(
                        total_percent,
                        f"UK MP3 | Dosya {file_no}/{total_files} | Parça {chunk_no}/{chunk_total}"
                    )
                    self.log(
                        f"MP3 üretiliyor: {output_path.name} | "
                        f"Dosya %{chunk_percent:.1f} | Toplam %{total_percent:.1f}"
                    )

                    subchunks = split_text_by_sentences(text, max_chars=3500)
                    sub_total = max(1, len(subchunks))

                    if len(subchunks) == 1:
                        communicate = edge_tts.Communicate(subchunks[0], voice=voice, rate=rate, volume=volume)
                        await communicate.save(str(output_path))
                    else:
                        with tempfile.TemporaryDirectory() as tmp_dir_str:
                            tmp_dir = Path(tmp_dir_str)
                            temp_files: list[Path] = []

                            for i, sub in enumerate(subchunks, start=1):
                                if self.is_cancelled():
                                    self.log("SRT/TXT -> UK MP3 işlemi iptal edildi.")
                                    self.set_progress(total_percent, "İptal edildi")
                                    return

                                sub_percent = ((chunk_no - 1) + (i - 1) / sub_total) / chunk_total * 100
                                total_percent = base_percent + (sub_percent / total_files)
                                self.set_progress(
                                    total_percent,
                                    f"UK MP3 | Dosya {file_no}/{total_files} | Parça {chunk_no}/{chunk_total} | Alt {i}/{sub_total}"
                                )
                                temp_mp3 = tmp_dir / f"sub_{i:03}.mp3"
                                communicate = edge_tts.Communicate(sub, voice=voice, rate=rate, volume=volume)
                                await communicate.save(str(temp_mp3))
                                temp_files.append(temp_mp3)

                            if self._ensure_system_tool("ffmpeg", "Gyan.FFmpeg", "FFmpeg", required=False) and shutil.which("ffmpeg"):
                                list_file = tmp_dir / "concat.txt"
                                list_file.write_text("\n".join(quote_concat_path(p) for p in temp_files), encoding="utf-8")
                                run_ffmpeg(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output_path)], self.cancel_event)
                            else:
                                self.log("FFmpeg yok. Büyük TTS parçası tekleştirilemedi; alt parçalar ayrı kaydediliyor.")
                                for i, temp_mp3 in enumerate(temp_files, start=1):
                                    fallback = output_dir / f"{file.stem}_part_{part_no:03}_sub_{i:03}_british_uk.mp3"
                                    shutil.copy2(temp_mp3, fallback)

                    done_file_percent = chunk_no / chunk_total * 100
                    done_total_percent = base_percent + (done_file_percent / total_files)
                    self.set_progress(
                        done_total_percent,
                        f"UK MP3 | Dosya {file_no}/{total_files} | Parça {chunk_no}/{chunk_total} tamam"
                    )
                    self.log(f"Kaydedildi: {output_path.name} | Dosya %{done_file_percent:.1f} | Toplam %{done_total_percent:.1f}")

            self.set_progress(100, "SRT/TXT -> UK MP3 işlemi bitti")
            self.log("SRT/TXT -> UK MP3 işlemi bitti.")

        try:
            asyncio.run(_run())
        except Exception as e:
            self.log(f"HATA: TTS işlemi durdu: {e}")

    # --------------------------------------------------------
    # TAB 3: MP3 BIRLESTIR
    # --------------------------------------------------------
    def _build_merge_tab(self) -> None:
        f = self.tab_merge
        f.columnconfigure(1, weight=1)
        f.rowconfigure(1, weight=1)

        self.merge_mp3_files: list[Path] = []
        self.merge_output_file = tk.StringVar(value=str(app_base_dir() / "outputs" / "birlesik_ses.mp3"))

        ttk.Label(f, text="Birleştirilecek MP3 dosyaları").grid(row=0, column=0, sticky="nw", padx=12, pady=10)

        list_frame = ttk.Frame(f)
        list_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=8, pady=10)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.merge_listbox = tk.Listbox(list_frame, height=12, selectmode="extended")
        self.merge_listbox.grid(row=0, column=0, sticky="nsew")
        merge_scroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.merge_listbox.yview)
        merge_scroll.grid(row=0, column=1, sticky="ns")
        self.merge_listbox.configure(yscrollcommand=merge_scroll.set)

        btn_frame = ttk.Frame(f)
        btn_frame.grid(row=0, column=2, rowspan=2, sticky="ns", padx=12, pady=10)
        ttk.Button(btn_frame, text="MP3 ekle", command=lambda: self.add_files_to_path_list(
            self.merge_mp3_files,
            self.merge_listbox,
            [("MP3", "*.mp3"), ("Tüm dosyalar", "*.*")],
            "Birleştirilecek MP3 dosyalarını seç"
        )).grid(row=0, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Klasörden ekle", command=lambda: self.add_folder_files_to_path_list(
            self.merge_mp3_files, self.merge_listbox, MP3_EXTENSIONS, "MP3 klasörü seç"
        )).grid(row=1, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Yukarı", command=lambda: self.move_selected_in_path_list(
            self.merge_mp3_files, self.merge_listbox, -1
        )).grid(row=2, column=0, sticky="ew", pady=(14, 3))
        ttk.Button(btn_frame, text="Aşağı", command=lambda: self.move_selected_in_path_list(
            self.merge_mp3_files, self.merge_listbox, 1
        )).grid(row=3, column=0, sticky="ew", pady=3)
        ttk.Button(btn_frame, text="Seçileni sil", command=lambda: self.remove_selected_from_path_list(
            self.merge_mp3_files, self.merge_listbox
        )).grid(row=4, column=0, sticky="ew", pady=(14, 3))
        ttk.Button(btn_frame, text="Listeyi temizle", command=lambda: self.clear_path_list(
            self.merge_mp3_files, self.merge_listbox
        )).grid(row=5, column=0, sticky="ew", pady=3)

        ttk.Label(f, text="Çıktı MP3").grid(row=2, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.merge_output_file).grid(row=2, column=1, sticky="ew", padx=8, pady=10)
        ttk.Button(f, text="Seç", command=lambda: self.choose_save_file(self.merge_output_file, ".mp3", [("MP3", "*.mp3")])).grid(row=2, column=2, padx=12, pady=10)

        ttk.Button(f, text="Listedeki Sıraya Göre MP3'leri Birleştir", command=lambda: self.run_in_thread(self.task_merge_mp3)).grid(row=3, column=0, columnspan=3, sticky="ew", padx=12, pady=18)

        note = (
            "Bu sekmede sıra artık alfabetik değil, ekrandaki liste sırasıdır. "
            "MP3'leri ekle, gerekiyorsa Yukarı/Aşağı ile sırala, sonra birleştir."
        )
        ttk.Label(f, text=note, wraplength=830).grid(row=4, column=0, columnspan=3, sticky="w", padx=12, pady=10)

    def task_merge_mp3(self) -> None:
        if not self._ensure_system_tool("ffmpeg", "Gyan.FFmpeg", "FFmpeg", required=True):
            return
        output_file = Path(self.merge_output_file.get())
        if not output_file.suffix:
            output_file = output_file.with_suffix(".mp3")
        output_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            mp3_files = [
                p for p in self.merge_mp3_files
                if p.is_file() and p.suffix.lower() == ".mp3" and p.resolve() != output_file.resolve()
            ]

            self.log(f"Birleştirilecek MP3 sayısı: {len(mp3_files)}")
            if not mp3_files:
                self.log("MP3 dosyası seçilmedi. 'MP3 ekle' ile dosyaları listeye ekle.")
                self.set_progress(0, "MP3 dosyası seçilmedi")
                return

            self.log("Birleştirme sırası:")
            for i, path in enumerate(mp3_files, start=1):
                self.log(f"{i:02d}. {path.name}")

            total_duration = sum(get_media_duration_seconds(p) for p in mp3_files)
            if total_duration > 0:
                self.log(f"Toplam kaynak süre: {normal_time(total_duration)}")

            self.set_progress(0, "MP3 birleştirme başladı")

            with tempfile.TemporaryDirectory() as tmp_dir_str:
                list_file = Path(tmp_dir_str) / "mp3_concat_list.txt"
                list_file.write_text("\n".join(quote_concat_path(p) for p in mp3_files), encoding="utf-8")

                def _merge_progress(percent: float, current_seconds: float) -> None:
                    self.set_progress(
                        percent,
                        f"MP3 birleştiriliyor | {normal_time(current_seconds)} / {normal_time(total_duration)}"
                    )

                run_ffmpeg_with_progress(
                    ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", str(output_file)],
                    total_duration,
                    _merge_progress,
                    self.cancel_event,
                )

            self.set_progress(100, "MP3 birleştirme bitti")
            self.log(f"Birleşik MP3 kaydedildi: {output_file}")

        except UserCancelled:
            self.log("MP3 birleştirme kullanıcı tarafından iptal edildi.")
            self.set_progress(self.progress_var.get(), "İptal edildi")
        except Exception as e:
            self.log(f"HATA: MP3 birleştirme başarısız: {e}")

    # --------------------------------------------------------
    # TAB 4: MP3 + KAPAK -> VIDEO
    # --------------------------------------------------------
    def _build_video_tab(self) -> None:
        f = self.tab_video
        f.columnconfigure(1, weight=1)

        self.video_mp3_file = tk.StringVar(value="")
        self.video_image_file = tk.StringVar(value="")
        self.video_srt_file = tk.StringVar(value="")
        self.video_output_file = tk.StringVar(value=str(app_base_dir() / "outputs" / "youtube_video.mp4"))
        self.video_burn_srt = tk.BooleanVar(value=False)

        ttk.Label(f, text="MP3 dosyası").grid(row=0, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.video_mp3_file).grid(row=0, column=1, sticky="ew", padx=8, pady=10)
        ttk.Button(f, text="Seç", command=lambda: self.choose_file(self.video_mp3_file, [("MP3", "*.mp3")])).grid(row=0, column=2, padx=12, pady=10)

        ttk.Label(f, text="Kapak görseli").grid(row=1, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.video_image_file).grid(row=1, column=1, sticky="ew", padx=8, pady=10)
        ttk.Button(f, text="Seç", command=lambda: self.choose_file(self.video_image_file, [("Image", "*.jpg *.jpeg *.png *.webp")])).grid(row=1, column=2, padx=12, pady=10)

        ttk.Label(f, text="SRT dosyası opsiyonel").grid(row=2, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.video_srt_file).grid(row=2, column=1, sticky="ew", padx=8, pady=10)
        ttk.Button(f, text="Seç", command=lambda: self.choose_file(self.video_srt_file, [("SRT", "*.srt")])).grid(row=2, column=2, padx=12, pady=10)

        ttk.Checkbutton(f, text="SRT'yi videoya yak / sabit göm", variable=self.video_burn_srt).grid(row=3, column=1, sticky="w", padx=8, pady=10)

        ttk.Label(f, text="Çıktı MP4").grid(row=4, column=0, sticky="w", padx=12, pady=10)
        ttk.Entry(f, textvariable=self.video_output_file).grid(row=4, column=1, sticky="ew", padx=8, pady=10)
        ttk.Button(f, text="Seç", command=lambda: self.choose_save_file(self.video_output_file, ".mp4", [("MP4", "*.mp4")])).grid(row=4, column=2, padx=12, pady=10)

        ttk.Button(f, text="YouTube Videosu Oluştur", command=lambda: self.run_in_thread(self.task_make_video)).grid(row=5, column=0, columnspan=3, sticky="ew", padx=12, pady=18)

        note = (
            "YouTube için en temiz yöntem: SRT'yi videoya yakmadan MP4 üret, sonra YouTube Studio'da SRT'yi ayrı yükle. "
            "Yakma seçeneği altyazıyı görüntünün parçası yapar; düzeltmesi daha zordur."
        )
        ttk.Label(f, text=note, wraplength=830).grid(row=6, column=0, columnspan=3, sticky="w", padx=12, pady=10)

    def task_make_video(self) -> None:
        if not self._ensure_system_tool("ffmpeg", "Gyan.FFmpeg", "FFmpeg", required=True):
            return
        # ----------------------------------------------------
        # MP3 + kapak gorseli ile YouTube icin MP4 uretir.
        #
        # V2 duzeltmesi:
        # - Kapak gorseli secilmezse hata vermek yerine siyah 1920x1080 arka plan uretir.
        # - Bos path veya klasor path'i yanlislikla dosya gibi FFmpeg'e verilmez.
        # - Permission denied hatalarini azaltmak icin dosya/klasor kontrolleri sertlestirildi.
        # ----------------------------------------------------
        mp3_text = self.video_mp3_file.get().strip()
        image_text = self.video_image_file.get().strip()
        srt_file_text = self.video_srt_file.get().strip()
        output_text = self.video_output_file.get().strip()

        if not mp3_text:
            self.log("HATA: MP3 dosyası seçilmedi.")
            self.set_progress(0, "MP3 dosyası seçilmedi")
            return

        if not output_text:
            self.log("HATA: Çıktı MP4 dosya adı boş olamaz.")
            self.set_progress(0, "Çıktı MP4 boş")
            return

        mp3_file = Path(mp3_text)
        image_file = Path(image_text) if image_text else None
        srt_file = Path(srt_file_text) if srt_file_text else None
        output_file = Path(output_text)

        if not output_file.suffix:
            output_file = output_file.with_suffix(".mp4")

        output_file.parent.mkdir(parents=True, exist_ok=True)

        # exists() tek başına yetmez; klasor de exists() der.
        # Eski surumde kapak bos kalinca Path("") mevcut klasor gibi algilanabiliyordu.
        if not mp3_file.is_file():
            self.log(f"HATA: MP3 dosyası bulunamadı veya dosya değil: {mp3_file}")
            return

        if image_file is not None and not image_file.is_file():
            self.log(f"HATA: Kapak görseli bulunamadı veya dosya değil: {image_file}")
            self.log("Kapak seçmek istemiyorsan kapak alanını tamamen boş bırak; uygulama siyah arka plan kullanır.")
            return

        if self.video_burn_srt.get():
            if not srt_file or not srt_file.is_file():
                self.log("HATA: SRT yakmak seçildi ama geçerli bir SRT dosyası seçilmedi.")
                return

        try:
            args = ["ffmpeg", "-y"]

            if image_file is None:
                # Kapak secilmezse FFmpeg ile sabit siyah 1920x1080 video kaynagi uret.
                self.log("Kapak görseli seçilmedi. Siyah 1920x1080 arka plan kullanılacak.")
                args.extend([
                    "-f", "lavfi",
                    "-i", "color=c=black:s=1920x1080:r=2",
                    "-i", str(mp3_file),
                ])
            else:
                args.extend([
                    "-loop", "1",
                    "-framerate", "2",
                    "-i", str(image_file),
                    "-i", str(mp3_file),
                ])

            if self.video_burn_srt.get():
                # FFmpeg subtitles filtresi Windows yolunda hassas olabilir.
                # Sorun olursa SRT'yi videoya yakmadan YouTube'a ayrica yuklemek daha temizdir.
                filter_path = str(srt_file.resolve()).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
                args.extend(["-vf", f"subtitles='{filter_path}'"])

            args.extend([
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-tune", "stillimage",
                "-c:a", "aac",
                "-b:a", "192k",
                "-pix_fmt", "yuv420p",
                "-shortest",
                str(output_file),
            ])

            audio_duration = get_media_duration_seconds(mp3_file)
            if audio_duration > 0:
                self.log(f"MP3 süresi: {normal_time(audio_duration)}")

            self.set_progress(0, "Video oluşturma başladı")
            self.log("Video oluşturuluyor...")
            self.log(f"MP3: {mp3_file}")
            if image_file is not None:
                self.log(f"Kapak: {image_file}")
            self.log(f"Çıktı: {output_file}")

            def _video_progress(percent: float, current_seconds: float) -> None:
                self.set_progress(
                    percent,
                    f"Video oluşturuluyor | {normal_time(current_seconds)} / {normal_time(audio_duration)}"
                )

            run_ffmpeg_with_progress(args, audio_duration, _video_progress, self.cancel_event)
            self.set_progress(100, "Video oluşturma bitti")
            self.log(f"MP4 kaydedildi: {output_file}")

            if srt_file and srt_file.is_file() and not self.video_burn_srt.get():
                self.log("SRT videoya gömülmedi. YouTube Studio'da ayrıca altyazı olarak yükle.")

        except UserCancelled:
            self.log("Video oluşturma kullanıcı tarafından iptal edildi.")
            self.set_progress(self.progress_var.get(), "İptal edildi")
        except Exception as e:
            self.log(f"HATA: Video oluşturma başarısız: {e}")

    # --------------------------------------------------------
    # TAB 5: KONTROL
    # --------------------------------------------------------
    def _build_check_tab(self) -> None:
        f = self.tab_check
        f.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)

        ttk.Label(f, text="Sistem ve güncelleme", font=("Segoe UI Semibold", 13)).grid(row=0, column=0, columnspan=2, sticky="w", padx=14, pady=(16, 4))
        ttk.Label(
            f, text="Kontroller hiçbir büyük bileşeni otomatik kurmaz. Güncelleme bilgileri okunur; seçim ilgili özellik kullanıldığında sana sorulur.",
            wraplength=920
        ).grid(row=1, column=0, columnspan=2, sticky="w", padx=14, pady=(0, 12))

        ttk.Button(f, text="Sistem Kontrolü Yap", command=lambda: self.run_in_thread(self.task_system_check), style="Accent.TButton").grid(row=2, column=0, sticky="ew", padx=(14, 7), pady=8)
        ttk.Button(f, text="Güncelleme Verilerini Yenile", command=lambda: self._start_first_session_update_check(force=True)).grid(row=2, column=1, sticky="ew", padx=(7, 14), pady=8)

        text = (
            "Çalışma mantığı:\n"
            "• Açılış: yalnızca hafif sistem doğrulaması + ilk oturumda sürüm metadata kontrolü.\n"
            "• Kullanım anı: eksik bileşen varsa kurulum seçeneği çıkar.\n"
            "• Update varsa: güncelle / mevcut sürümle devam et seçeneği çıkar.\n"
            "• Whisper modeli, Chromium, TTS ve fallback motorları açılışta indirilmez.\n\n"
            "FFmpeg: MP3/video işlemleri için • aria2c: Çok Hızlı indirme modu için opsiyonel."
        )
        ttk.Label(f, text=text, justify="left", wraplength=900).grid(row=3, column=0, columnspan=2, sticky="w", padx=14, pady=12)

    def task_system_check(self) -> None:
        """Ağır kurulum yapmadan mevcut durumu doğrular ve kısa bir özet verir."""
        self.log("Sistem kontrolü başladı. Bu kontrol paket indirmez.")
        checks: list[tuple[str, bool, str]] = []

        checks.append(("Python", sys.version_info >= (3, 10), os.sys.version.split()[0]))
        checks.append(("FFmpeg", bool(shutil.which("ffmpeg")), "gerektiğinde otomatik hazırlanır"))
        checks.append(("aria2c", bool(shutil.which("aria2c")), "opsiyonel hızlı indirme"))

        for label, module in [
            ("faster-whisper", "faster_whisper"),
            ("edge-tts", "edge_tts"),
            ("yt-dlp", "yt_dlp"),
            ("gallery-dl", "gallery_dl"),
            ("streamlink", "streamlink"),
            ("Playwright", "playwright"),
        ]:
            checks.append((label, self._module_available(module), "kullanım anında seçenek olarak hazırlanır"))

        # Kullanıcı verisi/cache yazma testi
        writable = False
        try:
            probe = user_data_dir() / ".system_check"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            writable = True
        except Exception:
            pass
        checks.append(("Ortak cache", writable, str(user_data_dir())))

        required_ok = checks[0][1] and writable
        ready_count = 0
        for label, ok, detail in checks:
            ready_count += int(ok)
            self.log(f"{'OK' if ok else 'Beklemede'}: {label} | {detail}")

        self.set_progress(100, f"Kontrol tamamlandı: {ready_count}/{len(checks)} hazır")
        if required_ok:
            self.show_toast(
                "Sistem doğrulandı",
                f"Temel yapı hazır. {ready_count}/{len(checks)} bileşen şu anda mevcut; diğerleri gerektiğinde hazırlanır.",
                "ok", 5500
            )
        else:
            self.show_toast("Sistem kontrolü", "Temel doğrulamada uyarı var. İşlem geçmişini kontrol et.", "warning", 6500)
        self.log("Sistem kontrolü bitti.")


if __name__ == "__main__":
    app = App()
    app.mainloop()
