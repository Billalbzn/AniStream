import http.server
import socketserver
import json
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import os
import sys
import webbrowser
import subprocess
import threading
import time
import re
import http.cookiejar
import csv
import io
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone

# Avoid UnicodeEncodeError crashes when printing file paths containing accented
# characters (e.g. "Henshū") on Windows consoles using cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Keywords indicating a "Kai"/"Henshu" recap/recompilation release, whose episode
# numbering does not correspond 1:1 to the original series tracked on AniList.
KAI_KEYWORDS = ['kai', 'kaï', 'henshu', 'henshū', 'fan-kai', 'fan-kaï']

PORT = 8000
VLC_HTTP_PORT = 4212
XML_PATH = 'myanimelist.xml'
CONFIG_PATH = 'config.json'
RECOMMENDATIONS_CACHE_PATH = 'recommendations_cache.json'
ANIMEVOST_RSS_URL = 'https://tsundere.animevost.fr/rss/nyaa'
ANIMEVOST_CACHE_TTL = 600  # 10 minutes
TRAKT_API_URL = 'https://api.trakt.tv'

_animevost_cache = None
_animevost_cache_time = 0

# In-memory cache of Trakt movie search results, keyed by (title.lower(), year)
_trakt_movie_cache = {}

# In-memory cache of Letterboxd user RSS feeds, keyed by lowercase username
_letterboxd_rss_cache = {}
LETTERBOXD_RSS_CACHE_TTL = 1800  # 30 minutes

# In-memory cache of TMDB poster paths, keyed by tmdb movie id
_tmdb_poster_cache = {}

vlc_status_data = {
    "file_path": None,
    "state": "stopped",
    "time": 0,
    "length": 0,
    "remaining": 0,
    "percent": 0,
    "mal_id": None,
    "episode_number": None,
    "anilist_status": None,
    "anilist_synced": False,
    "is_movie": False,
    "movie_title": None,
    "movie_year": None,
    "movie_trakt_id": None,
    "movie_rating_prompt": False,
    "movie_rated": False
}

# Episode is considered "watched" for AniList sync once playback reaches this percent
ANILIST_SYNC_THRESHOLD = 90

def find_vlc():
    """Finds the VLC installation path on Windows."""
    paths = [
        r"C:\Program Files\VideoLAN\VLC\vlc.exe",
        r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe"
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    # Check in PATH
    from shutil import which
    vlc_in_path = which("vlc")
    if vlc_in_path:
        return vlc_in_path
    return None

def find_qbittorrent():
    """Finds the qBittorrent installation path on Windows."""
    paths = [
        r"C:\Program Files\qBittorrent\qbittorrent.exe",
        r"C:\Program Files (x86)\qBittorrent\qbittorrent.exe"
    ]
    for path in paths:
        if os.path.exists(path):
            return path
    # Check registry App Paths
    try:
        import winreg
        key_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\qbittorrent.exe"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            path, _ = winreg.QueryValueEx(key, "")
            if os.path.exists(path):
                return path
    except Exception:
        pass
    # Check in PATH
    from shutil import which
    qb_in_path = which("qbittorrent.exe") or which("qbittorrent")
    if qb_in_path:
        return qb_in_path
    # Check Windows uninstall registry entries (covers custom install locations,
    # e.g. installed on D:\ or another non-default drive)
    try:
        import winreg
        uninstall_keys = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hive, base_path in uninstall_keys:
            try:
                with winreg.OpenKey(hive, base_path) as base_key:
                    for i in range(winreg.QueryInfoKey(base_key)[0]):
                        subkey_name = winreg.EnumKey(base_key, i)
                        try:
                            with winreg.OpenKey(base_key, subkey_name) as subkey:
                                display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                                if "qbittorrent" not in display_name.lower():
                                    continue
                                install_location, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                candidate = os.path.join(install_location, "qbittorrent.exe")
                                if os.path.exists(candidate):
                                    return candidate
                        except FileNotFoundError:
                            continue
                        except OSError:
                            continue
            except FileNotFoundError:
                continue
    except Exception:
        pass
    # Last resort: if qBittorrent is already running (e.g. portable install with
    # no registry entry), ask Windows for the running process's executable path.
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='qbittorrent.exe'\" | Select-Object -First 1 -ExpandProperty ExecutablePath)"],
            capture_output=True, text=True, timeout=5
        )
        path = result.stdout.strip()
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    return None

# Words/markers allowed to immediately follow a matched title in a torrent name
# (season/episode/quality/release markers). Anything else (a plain word) is treated
# as part of an extended/sequel title (e.g. "Shippuden", "Kai", "Brotherhood") and
# causes the match to be rejected, so searching "Naruto" doesn't return
# "Naruto Shippuden" results.
_ALLOWED_FOLLOWUP_RE = re.compile(
    r'^(?:s\d+e\d+|s\d+|e\d+|ep\d*|episode|saison|season|'
    r'vostfr|vosta|vf|fr|multi|bd|web|webrip|bdrip|hdtv|'
    r'kai|kaii|'  # "Kai"/"Kaï" = condensed re-edit of the SAME series (Dragon Ball Kai, Gintama Kaï)
    r'\d{3,4}p|x264|x265|h264|h265|hevc|aac|flac|10bit|8bit)$'
)

# Query words that describe the release, not the series — ignored when matching
# a manual search query against torrent titles.
_QUERY_NOISE_WORDS = {
    'vostfr', 'vosta', 'vostf', 'vo', 'vf', 'fr', 'french', 'multi', 'sub', 'subs',
    'bd', 'bluray', 'web', 'webrip', 'bdrip', 'hdtv', 'x264', 'x265', 'h264', 'h265',
    'hevc', 'aac', 'flac', '10bit', '8bit', 'batch', 'integrale', 'intégrale',
    '1080p', '720p', '480p', '2160p', '4k',
}

def manual_title_match(query, title):
    """Recall-oriented match for MANUAL search.

    The title must (a) lead with the query's first meaningful word (after any
    "[release-group]" / "(group)" prefix) and (b) contain every meaningful word
    of the query (release/quality words ignored). Unlike check_title_match it
    does NOT reject titles where another word follows the name, so "Gintama"
    surfaces "Gintama Kaï" and "Gintama - Mr. Ginpachi's Zany Class". The leading
    check still rejects titles that merely mention the word elsewhere, e.g.
    "Boruto Naruto Next Generations" for a "Naruto" search."""
    q_tokens = [t for t in re.split(r'[^a-z0-9]+', query.lower())
                if t and t not in _QUERY_NOISE_WORDS]
    if not q_tokens:
        return False
    # Strip leading release-group tags like "[Triggerforce] " or "(ADN) ".
    cleaned = re.sub(r'^\s*(?:[\[(][^\])]*[\])]\s*)+', '', title).lower()
    title_words = [w for w in re.split(r'[^a-z0-9]+', cleaned) if w]
    if not title_words or title_words[0] != q_tokens[0]:
        return False
    title_norm = re.sub(r'[^a-z0-9]+', ' ', title.lower())
    return all(re.search(r'\b' + re.escape(t) + r'\b', title_norm) for t in q_tokens)

# Japanese ordinal "part/season" markers used by sequels of the same series
# (e.g. "Enen no Shouboutai: Ni no Shou" = Fire Force Season 2)
_JAPANESE_SEASON_WORDS = {
    "ni no shou": 2,
    "san no shou": 3,
    "yon no shou": 4,
    "go no shou": 5,
    "roku no shou": 6,
    "nana no shou": 7,
    "hachi no shou": 8,
    "kyuu no shou": 9,
    "kyu no shou": 9,
    "juu no shou": 10,
}

def extract_season_number(text):
    """Extracts a season number from a title/query, if any is indicated.

    Recognizes "S01"/"S01E05", "Season 2", "Saison 3" and Japanese ordinal
    season markers (e.g. "Ni no Shou" = part/season 2). Returns None if no
    season indicator is found (i.e. the text doesn't specify a season)."""
    text_lower = text.lower()

    m = re.search(r's(\d{1,2})e\d+', text_lower)
    if m:
        return int(m.group(1))

    m = re.search(r'\bs(\d{1,2})\b', text_lower)
    if m:
        return int(m.group(1))

    m = re.search(r'\b(?:season|saison)\s*(\d{1,2})\b', text_lower)
    if m:
        return int(m.group(1))

    for phrase, season_num in _JAPANESE_SEASON_WORDS.items():
        if phrase in text_lower:
            return season_num

    return None

# Markers that indicate a season/part within a franchise; stripped to obtain the
# stable "franchise root" name used to build reliable nyaa.si queries.
_SEASON_MARKER_RE = re.compile(
    r'\b(?:'
    r's\d{1,2}(?:e\d{1,3})?|'                       # S02, S02E05
    r'(?:season|saison)\s*\d{1,2}|'                  # Season 2, Saison 2
    r'(?:\d+(?:st|nd|rd|th)|2nd|3rd)\s+season|'      # 2nd Season
    r'part\s*\d+|cour\s*\d+|'                        # Part 2, Cour 2
    r'ni no shou|san no shou|yon no shou|go no shou|' # Japanese ordinals
    r'roku no shou|nana no shou|hachi no shou|'
    r'kyuu no shou|kyu no shou|juu no shou'
    r')\b',
    re.IGNORECASE
)

def strip_season_markers(title):
    """Returns the franchise "root" name of a title, with any season/part marker
    removed (e.g. "Enen no Shouboutai: Ni no Shou" -> "Enen no Shouboutai",
    "Fire Force Season 2" -> "Fire Force"). Used to build season-anchored
    search queries that aren't over-constrained by the AniList season title."""
    root = _SEASON_MARKER_RE.sub(' ', title)
    # Drop trailing separators left over after removing the marker (": ", " - ")
    root = re.sub(r'[\s:_\-]+$', '', root)
    root = re.sub(r'\s{2,}', ' ', root).strip(' :-_')
    return root or title.strip()

def is_season_pack(title):
    """Returns True if a torrent title looks like a whole-season pack/batch
    (covers all episodes of a season) rather than a single episode."""
    t = title.lower()
    if any(kw in t for kw in ["batch", "complete", "complète", "intégrale",
                              "integrale", "season complete"]):
        return True
    # Episode range, e.g. "(01-25)", "01~25", "1 - 12"
    if re.search(r'\b\d{1,3}\s*[-~]\s*\d{1,3}\b', t):
        return True
    # A season tag (S0X / Season X / Saison X) without a per-episode number = full season
    has_season_tag = bool(
        re.search(r'\bs\d{1,2}\b', t) or
        re.search(r'\b(?:season|saison)\s*\d{1,2}\b', t)
    )
    if has_season_tag and parse_episode_number(title) is None:
        return True
    return False

def _has_extension_after_match(title_lower, end_idx):
    """Returns True if the text right after a title match in `title_lower`
    (starting at end_idx) looks like another title word (a sequel/extension name)
    rather than an episode/season/quality marker or the end of the string."""
    rest = title_lower[end_idx:]
    # Skip leading separators (spaces, dashes, underscores, colons, dots)
    m = re.match(r'^[\s\-_:.]*(.*)$', rest)
    rest = m.group(1) if m else rest
    if not rest:
        return False
    # Grab the next "word" (letters/digits)
    word_match = re.match(r'^([A-Za-z0-9]+)', rest)
    if not word_match:
        return False
    word = word_match.group(1)
    if word.isdigit():
        return False
    if _ALLOWED_FOLLOWUP_RE.match(word):
        return False
    return True

def season_compatible(v, title, query_season=None):
    """Checks whether the title's season (if indicated) matches the requested season.

    `query_season` (derived from the full original query) takes precedence over
    the season indicator (if any) found in `v` alone, since `v` may be a
    simplified variation (e.g. "Enen no Shouboutai" from "Enen no Shouboutai:
    Ni no Shou") that lost the season information. A query without any season
    indicator defaults to season 1. A title without any season indicator is
    assumed compatible."""
    season_v = query_season if query_season is not None else (extract_season_number(v.lower()) or 1)
    season_title = extract_season_number(title.lower())
    return season_title is None or season_title == season_v

def check_title_match(v, title, query_season=None, ignore_season=False):
    """Checks if the search variation v matches the torrent title with fallback rules.

    When `ignore_season` is True, the season guard is skipped and only the
    name-matching rules apply (used to decide whether a result belongs to a
    given series regardless of which season it is, e.g. for exclusion)."""
    title_lower = title.lower()
    v_lower = v.lower()

    if not ignore_season and not season_compatible(v, title, query_season):
        return False

    # 1. Try original exact word boundary, but reject if the matched title is
    # immediately followed by another title word (sequel/extension, e.g. "Shippuden")
    pattern = r'\b' + re.escape(v_lower) + r'\b'
    m = re.search(pattern, title_lower)
    if m and not _has_extension_after_match(title_lower, m.end()):
        return True

    # 2. Try matching with optional grammatical suffixes (ing, s, ed, er, ers) at the end of the query terms
    words = re.findall(r'\b\w+\b', v_lower)
    if not words:
        return False

    pattern_parts = []
    for idx, w in enumerate(words):
        if idx == len(words) - 1:
            # Last word allows suffixes
            pattern_parts.append(re.escape(w) + r'(?:ing|s|ed|er|ers)?')
        else:
            pattern_parts.append(re.escape(w))

    pattern_str = r'\b' + r'[\s\-_.]*'.join(pattern_parts) + r'\b'
    m2 = re.search(pattern_str, title_lower)
    if m2 and not _has_extension_after_match(title_lower, m2.end()):
        return True

    # 3. Try ignoring all spaces and checking substring if query is long enough.
    # Only allowed if the match reaches (close to) the end of the title's name part,
    # i.e. not immediately followed by another title word.
    norm_v = re.sub(r'[^a-z0-9]', '', v_lower)
    norm_title = re.sub(r'[^a-z0-9]', '', title_lower)
    if len(norm_v) >= 7 and norm_v in norm_title:
        idx = norm_title.index(norm_v) + len(norm_v)
        if idx >= len(norm_title) or norm_title[idx].isdigit():
            return True

    return False

def episode_matches(title, ep_int):
    """Checks if a torrent title corresponds to the requested episode number.

    Returns True for batch/pack releases (e.g. "01-12", "Batch", "Complete")
    since those legitimately contain the requested episode. Otherwise compares
    the episode number parsed from the title against ep_int, allowing the
    result through if no episode number could be parsed at all (ambiguous).
    """
    title_lower = title.lower()

    # Batch/pack releases cover multiple episodes, including the requested one
    if re.search(r'\b\d{1,3}\s*-\s*\d{1,3}\b', title_lower):
        return True
    if any(kw in title_lower for kw in ["batch", "complete", "intégrale", "integrale", "saison complète", "season complete"]):
        return True

    parsed_ep = parse_episode_number(title)
    if parsed_ep is None:
        return True

    return parsed_ep == ep_int

def is_french_subbed(title_lower, is_kai=False):
    """Checks if a torrent title is subbed in French (VOSTFR, STFR, Sub FR, etc.)."""
    # Standard French sub indicators
    if any(x in title_lower for x in ["vostfr", "vost", "stfr", "subfr", "sub fr", "sub-fr"]):
        return True
    # Both VO (Original Version) and FR (French subtitles/audio)
    if "vo" in title_lower and "fr" in title_lower:
        if any(x in title_lower for x in ["sub", "s/t", "sous", "multi", "dub"]):
            return True
    # Multiple subtitles containing French (fr / fre / french)
    if any(x in title_lower for x in ["multiple subtitle", "multi sub", "multi-sub"]):
        if any(x in title_lower for x in ["fr", "french"]):
            return True
    # Special patterns like: [Subtitles] [FR] or (Subtitles) (FR)
    if "subtitles" in title_lower and "fr" in title_lower:
        return True
    # For Kaï versions, allow French audio/dub (FRENCH, VF) or multi-audio (MULTI) as they are fan-edits for the French public
    if is_kai:
        if re.search(r'\bfrench\b', title_lower) or re.search(r'\bvf\b', title_lower):
            return True
        if re.search(r'\bmulti\b', title_lower):
            if any(x in title_lower for x in ["fr", "french", "vf", "vostfr", "saison", "kaï", "henshū"]):
                if "english dub" not in title_lower:
                    return True
    return False

def fetch_animevost_feed():
    """Fetches and caches the latest uploads feed from tsundere.animevost.fr (Tsundere-Raws VOSTFR releases).
    The feed ignores query parameters and always returns the latest ~50 uploads, so we cache it
    and filter by title locally for each search."""
    global _animevost_cache, _animevost_cache_time

    now = time.time()
    if _animevost_cache is not None and (now - _animevost_cache_time) < ANIMEVOST_CACHE_TTL:
        return _animevost_cache

    items = []
    req = urllib.request.Request(ANIMEVOST_RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        for item in root.findall('.//item'):
            title_el = item.find('title')
            link_el = item.find('link')
            if title_el is None or link_el is None:
                continue
            title = (title_el.text or '').strip()
            link = (link_el.text or '').strip()
            if not title or not link:
                continue
            items.append({"title": title, "link": link})
        _animevost_cache = items
        _animevost_cache_time = now
        print(f"[AnimeVost] Fetched {len(items)} items from RSS feed.")
    except Exception as e:
        print(f"[AnimeVost] Error fetching RSS feed: {e}")
        if _animevost_cache is None:
            _animevost_cache = []

    return _animevost_cache

last_save_time = 0
def save_playback_progress(file_path, vlc_time, vlc_length, force=False):
    """Saves current VLC playback time to config.json periodically."""
    global last_save_time
    current_time = time.time()
    # Save to file every 4 seconds to reduce disk I/O, unless forced
    if not force and current_time - last_save_time < 4:
        return
    last_save_time = current_time
    
    config = load_config()
    if "progress" not in config:
        config["progress"] = {}
    
    # Normalize path: always use forward slashes as the canonical key
    file_path_clean = os.path.normpath(file_path).replace("\\", "/")
    percent = (vlc_time / vlc_length) * 100 if vlc_length > 0 else 0
    config["progress"][file_path_clean] = {
        "time": vlc_time,
        "length": vlc_length,
        "percent": percent,
        "timestamp": current_time
    }
    save_config(config)
    print(f"[VLC] Saved progress: {os.path.basename(file_path)} at {vlc_time}s / {vlc_length}s ({percent:.1f}%)")

def update_anilist_sync_status_for_file(file_path):
    """Resolves mal_id/episode_number for file_path and resets the AniList sync state.
    Used both when launching a file via the API and when VLC auto-advances to the
    next playlist track (so each new episode gets its own sync check)."""
    config_for_mal = load_config()
    anime_dir = config_for_mal.get("anime_dir", r"C:\Anime")
    mal_id = None
    try:
        rel = os.path.relpath(file_path, anime_dir)
        folder_name = rel.split(os.sep)[0]
        folder_path_for_mal = os.path.join(anime_dir, folder_name)
        videos_for_mal = []
        for root, dirs, files in os.walk(folder_path_for_mal):
            for f in files:
                if f.lower().endswith(('.mkv', '.mp4', '.avi', '.mov')):
                    videos_for_mal.append(os.path.join(root, f))
        folder_mappings = config_for_mal.get("folder_mappings", {})
        mal_id, _ = resolve_mal_id_for_folder(folder_name, videos_for_mal, folder_mappings)

        # "Kai"/"Henshu" recaps have different episode numbering than the
        # original series tracked on AniList - don't auto-sync these, as the
        # episode count would not correspond to real story progress.
        combined_text = (folder_name + " " + os.path.basename(file_path)).lower()
        if any(kw in combined_text for kw in KAI_KEYWORDS):
            print(f"[Launcher] '{folder_name}' looks like a Kai/Henshu recap - skipping AniList auto-sync.")
            mal_id = None
    except Exception as e:
        print(f"[Launcher] Could not resolve mal_id for AniList sync: {e}")

    vlc_status_data["mal_id"] = mal_id
    vlc_status_data["episode_number"] = parse_episode_number(os.path.basename(file_path))
    vlc_status_data["anilist_synced"] = False

def poll_vlc_status():
    """Background thread function that queries VLC's HTTP API for playback status."""
    global vlc_status_data
    while True:
        time.sleep(2)
        if vlc_status_data.get("state") == "stopped" and not vlc_status_data.get("file_path"):
            continue
            
        url = f'http://localhost:{VLC_HTTP_PORT}/requests/status.json'
        req = urllib.request.Request(url)
        # Auth header for empty username and password 'avocado' (OmF2b2NhZG8=)
        req.add_header('Authorization', 'Basic OmF2b2NhZG8=')
        
        try:
            with urllib.request.urlopen(req, timeout=1) as response:
                data = json.loads(response.read().decode('utf-8'))
                state = data.get('state')
                if state in ['playing', 'paused']:
                    vlc_time = data.get('time', 0)  # in seconds
                    vlc_length = data.get('length', 0)  # in seconds
                    
                    # Track changes in the currently playing file (autoplay next episode support)
                    meta = data.get('information', {}).get('category', {}).get('meta', {})
                    filename = meta.get('filename') or meta.get('title')
                    if filename and vlc_status_data.get("file_path"):
                        current_basename = os.path.basename(vlc_status_data["file_path"])
                        if filename != current_basename:
                            parent_dir = os.path.dirname(vlc_status_data["file_path"])
                            if os.path.exists(parent_dir):
                                try:
                                    for f in os.listdir(parent_dir):
                                        if f == filename or f.lower() == filename.lower():
                                            new_path = os.path.join(parent_dir, f).replace("\\", "/")
                                            vlc_status_data["file_path"] = new_path
                                            update_anilist_sync_status_for_file(new_path)
                                            print(f"[VLC] Auto-detected playlist track change. New active file: {f}")
                                            break
                                except Exception as e:
                                    print(f"[VLC] Error scanning directory for track change: {e}")
                    
                    if vlc_length > 0:
                        remaining = vlc_length - vlc_time
                        percent = (vlc_time / vlc_length) * 100
                        
                        vlc_status_data["state"] = state
                        vlc_status_data["time"] = vlc_time
                        vlc_status_data["length"] = vlc_length
                        vlc_status_data["remaining"] = remaining
                        vlc_status_data["percent"] = percent
                        
                        if vlc_status_data.get("file_path"):
                            save_playback_progress(vlc_status_data["file_path"], vlc_time, vlc_length)

                        # Auto-sync watched episode to AniList once the episode is mostly done
                        if (percent >= ANILIST_SYNC_THRESHOLD
                                and not vlc_status_data.get("anilist_synced")
                                and vlc_status_data.get("mal_id")
                                and vlc_status_data.get("episode_number")):
                            config = load_config()
                            token = config.get("anilist_token")
                            if token:
                                # Mark as synced immediately to avoid firing this repeatedly while the request is in flight
                                vlc_status_data["anilist_synced"] = True
                                threading.Thread(
                                    target=sync_anilist_progress,
                                    args=(token, vlc_status_data["mal_id"], vlc_status_data["episode_number"]),
                                    daemon=True
                                ).start()

                        # Trigger the rating popup once a movie is mostly done
                        if (percent >= ANILIST_SYNC_THRESHOLD
                                and vlc_status_data.get("is_movie")
                                and not vlc_status_data.get("movie_rated")
                                and not vlc_status_data.get("movie_rating_prompt")):
                            vlc_status_data["movie_rating_prompt"] = True
                else:
                    # VLC reports stopped - force save the last known position
                    if vlc_status_data.get("state") in ["playing", "paused"] and vlc_status_data.get("file_path"):
                        last_time = vlc_status_data.get("time", 0)
                        last_length = vlc_status_data.get("length", 0)
                        if last_time > 10 and last_length > 0:
                            save_playback_progress(vlc_status_data["file_path"], last_time, last_length, force=True)
                            print(f"[VLC] Playback stopped. Final progress saved at {last_time}s.")
                    vlc_status_data["state"] = "stopped"
        except Exception:
            # VLC closed or not responding - force save last known position
            if vlc_status_data.get("state") in ["playing", "paused"] and vlc_status_data.get("file_path"):
                last_time = vlc_status_data.get("time", 0)
                last_length = vlc_status_data.get("length", 0)
                if last_time > 10 and last_length > 0:
                    save_playback_progress(vlc_status_data["file_path"], last_time, last_length, force=True)
                    print(f"[VLC] VLC closed. Final progress saved at {last_time}s.")
            if vlc_status_data.get("state") != "stopped":
                vlc_status_data["state"] = "stopped"

def fetch_anilist_watchlist_ids(username):
    """Fetches all media list entries to get all cataloged MAL IDs for filtering."""
    url = 'https://graphql.anilist.co'
    query = '''
    query ($userName: String) {
      MediaListCollection (userName: $userName, type: ANIME) {
        lists {
          entries {
            media {
              idMal
              title {
                romaji
              }
            }
          }
        }
      }
    }
    '''
    variables = {'userName': username}
    data = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={
            'Content-Type': 'application/json', 
            'Accept': 'application/json', 
            'User-Agent': 'Mozilla/5.0'
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"[AniList] Error fetching watchlist IDs: {e}")
        return None

def fetch_anilist_recommendations_batch(mal_ids):
    """Queries AniList in a batch for recommendations based on a list of MAL IDs."""
    url = 'https://graphql.anilist.co'
    query = '''
    query ($idMals: [Int]) {
      Page (page: 1, perPage: 50) {
        media (idMal_in: $idMals, type: ANIME) {
          idMal
          recommendations (perPage: 5, sort: RATING_DESC) {
            nodes {
              mediaRecommendation {
                idMal
                title {
                  romaji
                  english
                }
                meanScore
                coverImage {
                  large
                }
                bannerImage
              }
            }
          }
        }
      }
    }
    '''
    variables = {'idMals': mal_ids}
    data = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={
            'Content-Type': 'application/json', 
            'Accept': 'application/json', 
            'User-Agent': 'Mozilla/5.0'
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"[AniList] Error fetching batch recommendations: {e}")
        return None

def fetch_anilist_viewer_username(token):
    """Fetches the username of the authenticated AniList user using the token."""
    url = 'https://graphql.anilist.co'
    query = '''
    query {
      Viewer {
        name
      }
    }
    '''
    data = json.dumps({'query': query}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0',
            'Authorization': f'Bearer {token}'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            return res_json.get('data', {}).get('Viewer', {}).get('name')
    except Exception as e:
        print(f"[AniList] Error fetching viewer username: {e}")
        return None

def fetch_anilist_media_status(mal_id, token):
    """Resolves the AniList media ID and the viewer's current progress/status for a MAL ID.
    Needed for SaveMediaListEntry mutations and to avoid overwriting progress with a lower value."""
    url = 'https://graphql.anilist.co'
    query = '''
    query ($idMal: Int) {
      Media (idMal: $idMal, type: ANIME) {
        id
        mediaListEntry {
          progress
          status
        }
      }
    }
    '''
    data = json.dumps({'query': query, 'variables': {'idMal': int(mal_id)}}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0',
            'Authorization': f'Bearer {token}'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            media = res_json.get('data', {}).get('Media', {}) or {}
            entry = media.get('mediaListEntry') or {}
            return {
                "id": media.get('id'),
                "progress": entry.get('progress') or 0,
                "status": entry.get('status')
            }
    except Exception as e:
        print(f"[AniList] Error resolving AniList status for MAL {mal_id}: {e}")
        return None

def update_anilist_progress(token, anilist_media_id, progress, set_status_current=False):
    """Updates the progress (and optionally status) of an entry on the user's AniList."""
    url = 'https://graphql.anilist.co'
    if set_status_current:
        query = '''
        mutation ($mediaId: Int, $progress: Int, $status: MediaListStatus) {
          SaveMediaListEntry (mediaId: $mediaId, progress: $progress, status: $status) {
            id
            progress
            status
          }
        }
        '''
        variables = {'mediaId': int(anilist_media_id), 'progress': int(progress), 'status': 'CURRENT'}
    else:
        query = '''
        mutation ($mediaId: Int, $progress: Int) {
          SaveMediaListEntry (mediaId: $mediaId, progress: $progress) {
            id
            progress
            status
          }
        }
        '''
        variables = {'mediaId': int(anilist_media_id), 'progress': int(progress)}

    data = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0',
            'Authorization': f'Bearer {token}'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            entry = res_json.get('data', {}).get('SaveMediaListEntry', {})
            print(f"[AniList] Progress updated: mediaId={anilist_media_id} -> episode {progress} (status={entry.get('status')})")
            return True
    except Exception as e:
        print(f"[AniList] Error updating progress for mediaId {anilist_media_id}: {e}")
        return False

def sync_anilist_progress(token, mal_id, episode_number):
    """Pushes the watched episode progress to AniList, unless the viewer's current progress
    is already at or beyond this episode (e.g. rewatching an old episode).
    Runs in a background thread so it doesn't block the VLC status poller."""
    status = fetch_anilist_media_status(mal_id, token)
    if not status or not status.get("id"):
        return
    if episode_number <= (status.get("progress") or 0):
        print(f"[AniList] Skipping progress sync for mediaId {status['id']}: episode {episode_number} <= current progress {status.get('progress')}")
        return
    update_anilist_progress(token, status["id"], episode_number)

def fetch_anilist_trending():
    """Queries AniList's GraphQL API for trending and popular anime."""
    url = 'https://graphql.anilist.co'
    query = '''
    query {
      Page (page: 1, perPage: 50) {
        media (sort: [TRENDING_DESC, POPULARITY_DESC], type: ANIME) {
          idMal
          title {
            romaji
            english
          }
          meanScore
        }
      }
    }
    '''
    data = json.dumps({'query': query}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            res_json = json.loads(response.read().decode('utf-8'))
            media_list = res_json.get('data', {}).get('Page', {}).get('media', [])
            results = []
            for media in media_list:
                id_mal = media.get('idMal')
                title = media.get('title', {}).get('romaji') or media.get('title', {}).get('english')
                score = media.get('meanScore', 0)
                if id_mal and title:
                    results.append({
                        "title": title,
                        "mal_id": int(id_mal),
                        "score": score
                    })
            return results
    except Exception as e:
        print(f"[AniList] Error fetching trending/popular anime: {e}")
        return []

def get_recommendations_from_anilist(username):
    """Retrieves personalized recommendations from AniList based on the user's
    CURRENT, COMPLETED and PLANNING lists. Excludes anything already in any list."""
    # Check cache first
    cache_path = RECOMMENDATIONS_CACHE_PATH
    if os.path.exists(cache_path):
        try:
            mtime = os.path.getmtime(cache_path)
            if time.time() - mtime < 900: # 15 minutes
                with open(cache_path, 'r', encoding='utf-8') as f:
                    cached_recs = json.load(f)
                if cached_recs:
                    print("[API] Using fresh recommendations cache.")
                    return cached_recs
        except Exception as e:
            print(f"[API] Error reading recommendations cache: {e}")

    config = load_config()
    anime_dir = config.get("anime_dir", r"C:\Anime")
    folder_mappings = config.get("folder_mappings", {})
    
    # Get local shows
    local_mal_ids = []
    if os.path.exists(anime_dir):
        folders = []
        try:
            for entry in os.scandir(anime_dir):
                if entry.is_dir():
                    mtime = os.path.getmtime(entry.path)
                    folders.append((entry.name, mtime))
            folders.sort(key=lambda x: x[1], reverse=True)
            
            for folder_name, mtime in folders:
                if folder_name in folder_mappings:
                    local_mal_ids.append(int(folder_mappings[folder_name]))
                    continue
                norm_folder = re.sub(r'[\s\-_.]', '', folder_name.lower())
                for title, m_id in SUGGESTIONS:
                    norm_title = re.sub(r'[\s\-_.]', '', title.lower())
                    if len(norm_title) >= 4 and len(norm_folder) >= 4 and (norm_folder in norm_title or norm_title in norm_folder):
                        local_mal_ids.append(int(m_id))
                        break
        except Exception as e:
            print(f"[API] Error scanning local library for recommendations: {e}")
                    
    # Also look at local progress
    progress_data = config.get("progress", {})
    played_shows = []
    for fpath, prog in progress_data.items():
        if isinstance(prog, dict):
            norm_path = os.path.normpath(fpath)
            parts = norm_path.split(os.sep)
            if len(parts) >= 2:
                played_shows.append((parts[-2], prog.get("timestamp", 0)))
    played_shows.sort(key=lambda x: x[1], reverse=True)
    
    played_mal_ids = []
    seen_pf = set()
    for pf, ts in played_shows:
        if pf not in seen_pf:
            seen_pf.add(pf)
            if pf in folder_mappings:
                played_mal_ids.append(int(folder_mappings[pf]))
                continue
            norm_pf = re.sub(r'[\s\-_.]', '', pf.lower())
            for title, m_id in SUGGESTIONS:
                norm_title = re.sub(r'[\s\-_.]', '', title.lower())
                if len(norm_title) >= 4 and len(norm_pf) >= 4 and (norm_pf in norm_title or norm_title in norm_pf):
                    played_mal_ids.append(int(m_id))
                    break
                    
    # Combine local priorities (played first, then recently added)
    combined_local = []
    seen = set()
    for mid in played_mal_ids:
        if mid not in seen:
            seen.add(mid)
            combined_local.append(mid)
    for mid in local_mal_ids:
        if mid not in seen:
            seen.add(mid)
            combined_local.append(mid)
            
    # Step 1: Get the full AniList list to both source recommendations AND filter results
    # Source statuses: CURRENT, COMPLETED, PLANNING  
    # Filter (exclude from recs): ALL statuses (CURRENT, COMPLETED, PLANNING, DROPPED, PAUSED)
    all_watched_mal_ids = set()   # All MAL IDs in any list → exclude from recs
    all_watched_titles = set()    # Normalized titles → exclude from recs
    source_mal_ids = []           # MAL IDs from CURRENT+COMPLETED+PLANNING → use for recommendations query
    
    progress_data_full = fetch_anilist_progress_cached(username)
    if progress_data_full:
        try:
            lists_full = progress_data_full.get('data', {}).get('MediaListCollection', {}).get('lists', [])
            # Source lists: CURRENT, COMPLETED, PLANNING
            source_statuses = {'current', 'completed', 'watching', 'plan to watch', 'planning', 'read'}
            for lst in lists_full:
                list_name = lst.get('name', '').lower()
                is_source = list_name in source_statuses
                for entry in lst.get('entries', []):
                    media = entry.get('media', {})
                    entry_status = (entry.get('status') or '').lower()
                    mal_id = media.get('idMal')
                    title_rom = media.get('title', {}).get('romaji')
                    
                    # All entries go to the exclude set
                    if mal_id:
                        all_watched_mal_ids.add(int(mal_id))
                    if title_rom:
                        all_watched_titles.add(title_rom.lower().replace(' ', '').replace('-', '').replace('_', ''))
                    
                    # Only CURRENT, COMPLETED, PLANNING entries are sources
                    if entry_status in {'current', 'completed', 'planning', 'paused'} or is_source:
                        if mal_id:
                            mid_int = int(mal_id)
                            if mid_int not in source_mal_ids:
                                source_mal_ids.append(mid_int)
        except Exception as e:
            print(f"[AniList] Error parsing full watchlist for recommendations: {e}")
    
    # Merge with local library IDs (as secondary sources)
    for mid in combined_local:
        if mid not in source_mal_ids:
            source_mal_ids.append(mid)
    
    # If no source IDs found, fallback to nothing
    if not source_mal_ids:
        print("[AniList] No source IDs found for recommendations (empty AniList?)")
        return None
    
    print(f"[AniList] Building recommendations from {len(source_mal_ids)} source anime (CURRENT+COMPLETED+PLANNING+local)")
        
    # Step 2: Query AniList for recommendations based on source IDs
    recs_data = fetch_anilist_recommendations_batch(source_mal_ids[:30])
    if not recs_data:
        return None
        
    recommendations_map = {}
    try:
        media_list = recs_data.get('data', {}).get('Page', {}).get('media', [])
        for media in media_list:
            rec_nodes = media.get('recommendations', {}).get('nodes', []) if media.get('recommendations') else []
            for node in rec_nodes:
                rec_media = node.get('mediaRecommendation')
                if rec_media:
                    r_mal_id = rec_media.get('idMal')
                    r_title = rec_media.get('title', {}).get('romaji') or rec_media.get('title', {}).get('english')
                    r_score = rec_media.get('meanScore', 0)
                    r_cover = (rec_media.get('coverImage') or {}).get('large') or ''
                    r_banner = rec_media.get('bannerImage') or ''
                    if r_mal_id and r_title:
                        r_mal_id_int = int(r_mal_id)
                        if r_mal_id_int not in recommendations_map or r_score > recommendations_map[r_mal_id_int]['score']:
                            recommendations_map[r_mal_id_int] = {
                                "title": r_title,
                                "mal_id": r_mal_id_int,
                                "score": r_score,
                                "cover_image": r_cover,
                                "banner_image": r_banner
                            }
    except Exception as e:
        print(f"[AniList] Error parsing recommendations: {e}")
        return None
        
    # Step 3: Filter — exclude anything already in any AniList list, and skipped recommendations
    skipped_recs = set(config.get("skipped_recommendations", []))
    
    filtered = []
    for k, v in recommendations_map.items():
        if k in all_watched_mal_ids or k in skipped_recs:
            continue
        title_norm = v['title'].lower().replace(' ', '').replace('-', '').replace('_', '')
        if title_norm in all_watched_titles:
            continue
        filtered.append(v)
        
    filtered.sort(key=lambda x: x['score'], reverse=True)
    print(f"[AniList] Generated {len(filtered)} personalized recommendations.")
    return filtered

def get_resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def fetch_anilist_progress(username):
    """Fetches user anime list progress from AniList using GraphQL."""
    url = 'https://graphql.anilist.co'
    query = '''
    query ($userName: String) {
      MediaListCollection (userName: $userName, type: ANIME) {
        lists {
          name
          entries {
            media {
              id
              idMal
              title {
                romaji
                english
                native
              }
              episodes
              coverImage {
                large
                medium
              }
              bannerImage
              meanScore
              genres
              seasonYear
            }
            progress
            status
          }
        }
      }
    }
    '''
    variables = {'userName': username}
    data = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    
    req = urllib.request.Request(
        url, 
        data=data, 
        headers={
            'Content-Type': 'application/json', 
            'Accept': 'application/json', 
            'User-Agent': 'Mozilla/5.0'
        }
    )
    
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"[AniList] Error fetching progress for {username}: {e}")
        return None

anilist_progress_cache = {}  # username -> {"data": ..., "timestamp": ...}
anilist_progress_fetch_lock = threading.Lock()  # Prevents concurrent AniList fetches

def fetch_anilist_progress_cached(username):
    """Thread-safe cached AniList progress fetch.
    Uses a lock so concurrent requests share one HTTP call instead of spamming AniList."""
    global anilist_progress_cache
    now = time.time()
    cache_entry = anilist_progress_cache.get(username)
    # Fast path: fresh cache, no lock needed
    if cache_entry and (now - cache_entry["timestamp"] < 300):  # 5 minutes
        print(f"[AniList] Using cached progress for {username} (age: {int(now - cache_entry['timestamp'])}s)")
        return cache_entry["data"]

    # Slow path: need to fetch — acquire lock so only one thread fetches at a time
    with anilist_progress_fetch_lock:
        # Double-check: another thread may have already fetched while we waited
        cache_entry = anilist_progress_cache.get(username)
        if cache_entry and (now - cache_entry["timestamp"] < 300):
            print(f"[AniList] Using cached progress for {username} (fetched by another thread)")
            return cache_entry["data"]

        print(f"[AniList] Fetching fresh progress for {username}...")
        data = fetch_anilist_progress(username)
        if data and "errors" not in data:
            anilist_progress_cache[username] = {
                "data": data,
                "timestamp": time.time()
            }
            return data
        # On error: return stale cache if available, but update timestamp to throttle retries
        stale = anilist_progress_cache.get(username)
        if stale:
            print(f"[AniList] Fetch failed. Using stale cached progress for {username} and throttling retries.")
            stale["timestamp"] = time.time() - 270  # Retry in 30 seconds, not immediately
            return stale["data"]
        else:
            # If no stale cache exists, cache a temporary None value for 30 seconds to throttle retries
            print(f"[AniList] Fetch failed and no stale cache. Throttling retries for 30s.")
            anilist_progress_cache[username] = {
                "data": None,
                "timestamp": time.time() - 270  # Expiry in 30s
            }
        return data

def fetch_airing_schedule(media_ids):
    """Queries AniList's GraphQL API for the airing schedule of specific AniList media IDs.
    Returns episodes airing in the past 2 days and next 7 days, with cover images."""
    url = 'https://graphql.anilist.co'
    query = '''
    query ($mediaIds: [Int], $start: Int, $end: Int) {
      Page (page: 1, perPage: 50) {
        airingSchedules (mediaId_in: $mediaIds, airingAt_greater: $start, airingAt_less: $end, sort: TIME_ASC) {
          episode
          airingAt
          timeUntilAiring
          media {
            id
            idMal
            title {
              romaji
              english
            }
            coverImage {
              large
              medium
            }
            bannerImage
          }
        }
      }
    }
    '''
    # Airing schedule for next 14 days and past 2 days
    now = int(time.time())
    start_time = now - 2 * 86400   # 2 days ago
    end_time = now + 14 * 86400    # 14 days from now
    
    variables = {
        'mediaIds': media_ids,
        'start': start_time,
        'end': end_time
    }
    data = json.dumps({'query': query, 'variables': variables}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            return json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"[AniList] Error fetching airing schedule: {e}")
        return None

def format_time_until(seconds):
    """Formats seconds into a human-readable duration (e.g. 2 jours, 3 heures)."""
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min"
    heures = minutes // 60
    if heures < 24:
        return f"{heures}h"
    jours = heures // 24
    rest_heures = heures % 24
    if rest_heures > 0:
        return f"{jours}j et {rest_heures}h"
    return f"{jours} jours"

def get_personal_fallback_suggestions(username):
    """Returns a list of shows from the user's AniList planning list or local XML plan to watch."""
    shows = []
    seen_ids = set()
    
    # 1. Try AniList progress cache if available
    try:
        data = fetch_anilist_progress_cached(username)
        if data:
            lists = data.get('data', {}).get('MediaListCollection', {}).get('lists', [])
            for lst in lists:
                if lst.get('name', '').lower() in ['planning', 'plan to watch']:
                    for entry in lst.get('entries', []):
                        media = entry.get('media', {})
                        m_id = media.get('idMal')
                        title = media.get('title', {}).get('romaji') or media.get('title', {}).get('english')
                        if m_id and title:
                            m_id_int = int(m_id)
                            if m_id_int not in seen_ids:
                                seen_ids.add(m_id_int)
                                shows.append({"title": title, "mal_id": m_id_int, "score": 80, "is_planning": True})
    except Exception as e:
        print(f"[API] Error getting planning list from AniList cache: {e}")
        
    # 2. Try XML fallback
    if len(shows) < 5 and os.path.exists(XML_PATH):
        try:
            parser = ET.XMLParser(encoding="utf-8")
            tree = ET.parse(XML_PATH, parser=parser)
            root = tree.getroot()
            for anime in root.findall('anime'):
                status_node = anime.find('my_status')
                if status_node is not None and status_node.text in ['Plan to Watch', 'p']:
                    db_id = anime.find('series_animedb_id')
                    title = anime.find('series_title')
                    if db_id is not None and title is not None and db_id.text and title.text:
                        m_id_int = int(db_id.text)
                        if m_id_int not in seen_ids:
                            seen_ids.add(m_id_int)
                            shows.append({"title": title.text, "mal_id": m_id_int, "score": 75, "is_planning": True})
        except Exception as e:
            print(f"[API] Error reading XML for planning shows: {e}")
            
    # 3. If still empty, use SUGGESTIONS
    if not shows:
        for title, m_id in SUGGESTIONS:
            shows.append({"title": title, "mal_id": int(m_id), "score": 50})
            
    return shows

# Import local suggestions list from update_list.py
try:
    from update_list import SUGGESTIONS
except ImportError:
    SUGGESTIONS = []

def load_config():
    """Loads config.json or returns default config."""
    default_config = {"anime_dir": r"C:\Anime"}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Config] Error reading config.json: {e}")
    return default_config

def save_config(config):
    """Saves configuration back to config.json."""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[Config] Error writing config.json: {e}")
        return False

def add_to_xml(title, mal_id, status):
    """Adds a new anime entry to the XML file."""
    try:
        if not os.path.exists(XML_PATH):
            root = ET.Element('myanimelist')
            myinfo = ET.SubElement(root, 'myinfo')
            export_type = ET.SubElement(myinfo, 'user_export_type')
            export_type.text = '1'
            tree = ET.ElementTree(root)
        else:
            parser = ET.XMLParser(encoding="utf-8")
            tree = ET.parse(XML_PATH, parser=parser)
            root = tree.getroot()

        # Double check if it already exists to avoid duplicates
        for anime in root.findall('anime'):
            db_id = anime.find('series_animedb_id')
            if db_id is not None and db_id.text == str(mal_id):
                return True  # Already added
                
        anime_node = ET.SubElement(root, 'anime')
        
        id_node = ET.SubElement(anime_node, 'series_animedb_id')
        id_node.text = str(mal_id)
        
        title_node = ET.SubElement(anime_node, 'series_title')
        title_node.text = title
        
        score_node = ET.SubElement(anime_node, 'my_score')
        score_node.text = '0'
        
        status_node = ET.SubElement(anime_node, 'my_status')
        if status == 'c':
            status_node.text = 'Completed'
        elif status == 'e':
            status_node.text = 'Watching'
        elif status == 'p':
            status_node.text = 'Plan to Watch'
        
        ep_node = ET.SubElement(anime_node, 'my_watched_episodes')
        ep_node.text = '0' if status in ['c', 'p'] else '1'
        
        import_node = ET.SubElement(anime_node, 'update_on_import')
        import_node.text = '1'
        
        # Save to file
        tree.write(XML_PATH, encoding='utf-8', xml_declaration=True)
        print(f"[API] Added to XML: {title} ({status_node.text})")
        return True
    except Exception as e:
        print(f"[API] Error saving to XML: {e}")
        return False

def parse_episode_number(filename):
    """Tries to extract the episode number from a filename."""
    name, _ = os.path.splitext(filename)
    
    # 1. Look for explicit Season & Episode patterns: S01E05, S1 E05, S01-E05, Season 1 Ep 05
    match_se = re.search(r'[sS]\d+\s*(?:[eE]|ep|episode)\s*[-_]*\s*(\d+)\b', name, re.IGNORECASE)
    if match_se:
        return int(match_se.group(1))
        
    # 2. Look for Season followed by separator and episode number: S01 - 05, Season 1 - 05
    match_s_ep = re.search(r'\b(?:s\d+|season\s*\d+|saison\s*\d+)\s*[-_]\s*(\d+)\b', name, re.IGNORECASE)
    if match_s_ep:
        return int(match_s_ep.group(1))

    # Clean the string for general parsing
    clean_name = re.sub(r'\[[^\]]*\]', '', name)
    clean_name = re.sub(r'\([^\)]*\)', '', clean_name)
    
    # Strip common resolutions, codecs, and audio formats to avoid them being parsed as episode numbers
    clean_name = re.sub(
        r'\b(1080p?|720p?|480p?|360p?|1080i|2160p?|4k|x264|x265|hevc|h264|h265|aac|flac|mp3|v\d+|dual\s*audio|multi|web|bdrip|webrip|hdtv)\b',
        '', clean_name, flags=re.IGNORECASE
    )
    
    # Strip season numbers
    clean_name = re.sub(r'\b(?:s\d+|season\s*\d+|saison\s*\d+)\b', '', clean_name, flags=re.IGNORECASE)

    # 3. Look for patterns like "E01", "Ep 01", "Episode 01"
    match_ep = re.search(r'\b(?:ep|episode|e)\s*[-_]*\s*(\d+)\b', clean_name, re.IGNORECASE)
    if match_ep:
        return int(match_ep.group(1))
        
    # 4. Standalone numbers
    matches = re.findall(r'\b(\d+)\b', clean_name)
    if matches:
        for num_str in reversed(matches):
            val = int(num_str)
            if 1980 <= val <= 2030 and len(matches) > 1:
                continue
            if val < 1500:
                return val
    return None
def guess_title_from_filenames(videos):
    """Tries to guess a cleaner anime title from filenames inside the folder."""
    for v in videos:
        basename = os.path.basename(v)
        # remove brackets content like [Tsundere-Raws], [1080p], etc.
        clean = re.sub(r'\[[^\]]*\]', '', basename)
        clean = re.sub(r'\([^\)]*\)', '', clean)
        # remove file extension
        clean, _ = os.path.splitext(clean)
        # remove episode patterns like " - 01", " ep 01", etc.
        match_ep = re.search(r'\s*-\s*\d+\b|\s*(?:ep|episode|e)\s*\d+\b', clean, re.IGNORECASE)
        if match_ep:
            title_part = clean[:match_ep.start()].strip(" -_")
            if len(title_part) >= 3:
                return title_part
        # Fallback split on dash
        if ' - ' in clean:
            title_part = clean.split(' - ')[0].strip(" -_")
            if len(title_part) >= 3:
                return title_part
    return None

def guess_movie_title_from_filename(filename):
    """Extracts a clean movie title (and optional release year) from a filename,
    e.g. 'Movie.Name.2018.VOSTFR.1080p.BluRay.x264-GROUP.mkv' -> ('Movie Name', 2018)."""
    name, _ = os.path.splitext(filename)
    name = re.sub(r'\[[^\]]*\]', ' ', name)
    name = re.sub(r'\([^\)]*\)', ' ', name)

    # A 4-digit year is the most reliable cut point between title and release info
    year_match = re.search(r'\b(19[0-9]{2}|20[0-9]{2})\b', name)
    year = None
    if year_match:
        year = int(year_match.group(1))
        name = name[:year_match.start()]
    else:
        # No year found - cut at the first known quality/source/lang tag
        cut_match = re.search(
            r'\b(1080p|720p|2160p|4k|bluray|brrip|webrip|web[\-.]?dl|hdtv|dvdrip|'
            r'x264|x265|hevc|vostfr|vosta|multi|french|truefrench)\b',
            name, re.IGNORECASE
        )
        if cut_match:
            name = name[:cut_match.start()]

    name = re.sub(r'[._]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip(' -_')
    return (name, year) if name else (None, None)

def search_trakt_movies(query, client_id, limit=15):
    """Searches Trakt.tv for movies matching the query, returning a list of raw 'movie' objects."""
    if not query or not client_id:
        return []

    url = f'{TRAKT_API_URL}/search/movie?query={urllib.parse.quote(query)}&limit={limit}'
    req = urllib.request.Request(url, headers={
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': client_id,
        'User-Agent': 'Mozilla/5.0'
    })
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            results = json.loads(response.read().decode('utf-8'))
            return [r.get('movie') for r in results if r.get('movie')]
    except Exception as e:
        print(f"[Trakt] Error searching movies for '{query}': {e}")
        return []

def fetch_trakt_movie(title, client_id, year=None):
    """Searches Trakt.tv for a movie matching the given title (and optional year),
    returning the raw 'movie' object (with ids/title/year) or None. Cached in memory."""
    if not title or not client_id:
        return None

    cache_key = (title.lower(), year)
    if cache_key in _trakt_movie_cache:
        return _trakt_movie_cache[cache_key]

    url = f'{TRAKT_API_URL}/search/movie?query={urllib.parse.quote(title)}'
    if year:
        url += f'&years={year}'

    req = urllib.request.Request(url, headers={
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': client_id,
        'User-Agent': 'Mozilla/5.0'
    })
    result = None
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            results = json.loads(response.read().decode('utf-8'))
            if results:
                result = results[0].get('movie')
    except Exception as e:
        print(f"[Trakt] Error searching for movie '{title}': {e}")

    _trakt_movie_cache[cache_key] = result
    return result

def fetch_letterboxd_user_rss(username):
    """Fetches and caches a Letterboxd user's public RSS feed (diary activity)."""
    cache_key = username.lower()
    now = time.time()
    cached = _letterboxd_rss_cache.get(cache_key)
    if cached and now - cached[0] < LETTERBOXD_RSS_CACHE_TTL:
        return cached[1]

    items = []
    url = f'https://letterboxd.com/{urllib.parse.quote(username)}/rss/'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            root = ET.fromstring(response.read())
        for item in root.iter('item'):
            entry = {"username": username}
            for child in item:
                tag = child.tag.split('}')[-1]
                if tag in ('title', 'link', 'pubDate'):
                    entry[tag] = child.text
                elif tag == 'memberRating':
                    entry['rating'] = child.text
                elif tag == 'filmTitle':
                    entry['film_title'] = child.text
                elif tag == 'filmYear':
                    entry['film_year'] = child.text
                elif tag == 'description' and child.text:
                    img_match = re.search(r'<img[^>]+src="([^"]+)"', child.text)
                    if img_match:
                        entry['poster_url'] = img_match.group(1)
            items.append(entry)
    except Exception as e:
        print(f"[Letterboxd] Error fetching RSS for '{username}': {e}")

    _letterboxd_rss_cache[cache_key] = (now, items)
    return items

def fetch_tmdb_poster_url(tmdb_id, api_key, size='w342'):
    """Fetches and caches a movie's poster URL from TMDB, given its TMDB id. Returns None on failure."""
    if not tmdb_id or not api_key:
        return None

    cache_key = tmdb_id
    if cache_key in _tmdb_poster_cache:
        poster_path = _tmdb_poster_cache[cache_key]
    else:
        poster_path = None
        url = f'https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={urllib.parse.quote(api_key)}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        try:
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                poster_path = data.get('poster_path')
        except Exception as e:
            print(f"[TMDB] Error fetching poster for tmdb id '{tmdb_id}': {e}")
        _tmdb_poster_cache[cache_key] = poster_path

    return f'https://image.tmdb.org/t/p/{size}{poster_path}' if poster_path else None

def trakt_request_device_code(client_id):
    """Starts the Trakt OAuth device-code flow, returning the dict with
    device_code/user_code/verification_url/interval/expires_in."""
    req = urllib.request.Request(
        f'{TRAKT_API_URL}/oauth/device/code',
        data=json.dumps({"client_id": client_id}).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
        method='POST'
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode('utf-8'))

def trakt_poll_device_token(client_id, client_secret, device_code):
    """Polls Trakt for the device-code flow result. Returns:
    - dict with access_token/refresh_token on success
    - {"pending": True} while the user hasn't authorized yet
    - {"error": "..."} on failure/expiry"""
    req = urllib.request.Request(
        f'{TRAKT_API_URL}/oauth/device/token',
        data=json.dumps({
            "code": device_code,
            "client_id": client_id,
            "client_secret": client_secret
        }).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'},
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        if e.code == 400:
            return {"pending": True}
        return {"error": f"http_{e.code}"}
    except Exception as e:
        return {"error": str(e)}

def fetch_trakt_movie_recommendations(client_id, access_token, limit=20):
    """Fetches the user's personalized movie recommendations from Trakt."""
    req = urllib.request.Request(
        f'{TRAKT_API_URL}/recommendations/movies?limit={limit}',
        headers={
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': client_id,
            'Authorization': f'Bearer {access_token}',
            'User-Agent': 'Mozilla/5.0'
        }
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode('utf-8'))

def fetch_trakt_watchlist_movies(client_id, access_token):
    """Fetches the user's movie watchlist from Trakt."""
    req = urllib.request.Request(
        f'{TRAKT_API_URL}/sync/watchlist/movies',
        headers={
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': client_id,
            'Authorization': f'Bearer {access_token}',
            'User-Agent': 'Mozilla/5.0'
        }
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return json.loads(response.read().decode('utf-8'))

def add_movie_to_trakt_watchlist(client_id, access_token, trakt_id):
    """Adds a movie to the user's Trakt watchlist. Returns True on success."""
    req = urllib.request.Request(
        f'{TRAKT_API_URL}/sync/watchlist',
        data=json.dumps({"movies": [{"ids": {"trakt": int(trakt_id)}}]}).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'trakt-api-version': '2',
            'trakt-api-key': client_id,
            'Authorization': f'Bearer {access_token}',
            'User-Agent': 'Mozilla/5.0'
        },
        method='POST'
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            response.read()
        return True
    except Exception as e:
        print(f"[Trakt] Error adding movie {trakt_id} to watchlist: {e}")
        return False

def rate_movie_on_trakt(client_id, access_token, trakt_id, rating):
    """Sends a rating (1-10) and marks a movie as watched 'now' on Trakt.tv."""
    headers = {
        'Content-Type': 'application/json',
        'trakt-api-version': '2',
        'trakt-api-key': client_id,
        'Authorization': f'Bearer {access_token}',
        'User-Agent': 'Mozilla/5.0'
    }
    watched_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.000Z')
    requests_to_send = [
        (f'{TRAKT_API_URL}/sync/ratings', {"movies": [{"ids": {"trakt": int(trakt_id)}, "rating": int(rating)}]}),
        (f'{TRAKT_API_URL}/sync/history', {"movies": [{"ids": {"trakt": int(trakt_id)}, "watched_at": watched_at}]}),
    ]
    success = True
    for url, payload in requests_to_send:
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=headers,
                method='POST'
            )
            with urllib.request.urlopen(req, timeout=5) as response:
                response.read()
        except Exception as e:
            print(f"[Trakt] Error posting to {url}: {e}")
            success = False
    return success

def resolve_mal_id_for_folder(folder_name, videos, folder_mappings):
    """Resolves a (mal_id, matched_title) pair for an anime folder, using explicit
    folder_mappings first, then guessing from filenames/folder name against SUGGESTIONS."""
    mal_id = None
    matched_title = folder_name

    if folder_name in folder_mappings:
        mal_id = int(folder_mappings[folder_name])
        for title, m_id in SUGGESTIONS:
            if int(m_id) == mal_id:
                matched_title = title
                break
    else:
        # 1. Try to guess from filenames first
        guessed = guess_title_from_filenames(videos)
        if guessed:
            norm_guessed = re.sub(r'[\s\-_.]', '', guessed.lower())
            # Try exact match
            for title, m_id in SUGGESTIONS:
                norm_title = re.sub(r'[\s\-_.]', '', title.lower())
                if norm_guessed == norm_title:
                    mal_id = m_id
                    matched_title = title
                    break
            if not mal_id:
                # Try substring match (require a minimum length to avoid short
                # titles like "K" matching as a substring of unrelated names)
                for title, m_id in SUGGESTIONS:
                    norm_title = re.sub(r'[\s\-_.]', '', title.lower())
                    if len(norm_title) >= 4 and len(norm_guessed) >= 4 and (norm_guessed in norm_title or norm_title in norm_guessed):
                        mal_id = m_id
                        matched_title = title
                        break

        if not mal_id:
            # Fallback to matching folder name
            norm_folder = re.sub(r'[\s\-_.]', '', folder_name.lower())
            for title, m_id in SUGGESTIONS:
                norm_title = re.sub(r'[\s\-_.]', '', title.lower())
                if norm_folder == norm_title:
                    mal_id = m_id
                    matched_title = title
                    break
            if not mal_id:
                for title, m_id in SUGGESTIONS:
                    norm_title = re.sub(r'[\s\-_.]', '', title.lower())
                    if len(norm_title) >= 4 and len(norm_folder) >= 4 and (norm_folder in norm_title or norm_title in norm_folder):
                        mal_id = m_id
                        matched_title = title
                        break

    return mal_id, matched_title

def get_library(anime_dir):
    """Scans configured anime_dir for folders containing video files and returns their info."""
    library = []
    print(f"[Launcher] Scanning library in {anime_dir}...")
    
    # Query AniList collection in real-time
    anilist_map = {}
    try:
        config = load_config()
        token = config.get("anilist_token")
        username = None
        if token:
            username = config.get("anilist_username")
            if not username:
                username = fetch_anilist_viewer_username(token)
                if username:
                    config["anilist_username"] = username
                    save_config(config)
        if not username:
            username = "AvocadoDeska"
            
        anilist_data = fetch_anilist_progress_cached(username)
        if anilist_data:
            lists = anilist_data.get('data', {}).get('MediaListCollection', {}).get('lists', [])
            for lst in lists:
                for entry in lst.get('entries', []):
                    media = entry.get('media', {})
                    m_id = media.get('idMal')
                    status = entry.get('status')
                    progress = entry.get('progress') or 0
                    episodes = media.get('episodes') or 0
                    
                    if status == 'COMPLETED':
                        # If completed, default to total episodes
                        progress = episodes if episodes > 0 else 9999
                        
                    if m_id:
                        anilist_map[int(m_id)] = {
                            "progress": progress,
                            "status": status,
                            "cover_image": (media.get('coverImage') or {}).get('large') or (media.get('coverImage') or {}).get('medium') or ''
                        }
            print(f"[AniList] Live sync complete: loaded {len(anilist_map)} tracked titles.")
    except Exception as e:
        print(f"[AniList] Failed to update progress from AniList (offline fallback active): {e}")

    # Loop through direct subfolders in C:\Anime
    folder_mappings = config.get("folder_mappings", {})
    for entry in os.scandir(anime_dir):
        if entry.is_dir():
            folder_name = entry.name
            folder_path = entry.path
            
            # Find all video files inside this folder
            videos = []
            for root, dirs, files in os.walk(folder_path):
                for file in files:
                    if file.lower().endswith(('.mkv', '.mp4', '.avi', '.mov')):
                        videos.append(os.path.join(root, file))
            
            if not videos:
                continue
                
            # Sort videos alphabetically
            videos.sort()
            
            # Try to match the folder name to get the mal_id from config or SUGGESTIONS (ignoring spaces/hyphens)
            mal_id, matched_title = resolve_mal_id_for_folder(folder_name, videos, folder_mappings)

            # Get watched progress (AniList first, then fallback to local XML)
            watched_episodes = 0
            found_in_anilist = False
            cover_image = ''
            
            if mal_id and int(mal_id) in anilist_map:
                watched_episodes = anilist_map[int(mal_id)]["progress"]
                cover_image = anilist_map[int(mal_id)]["cover_image"]
                found_in_anilist = True
                
            if not found_in_anilist:
                # Fallback to local XML
                if os.path.exists(XML_PATH):
                    try:
                        parser = ET.XMLParser(encoding="utf-8")
                        tree = ET.parse(XML_PATH, parser=parser)
                        root_xml = tree.getroot()
                        for anime in root_xml.findall('anime'):
                            db_id = anime.find('series_animedb_id')
                            if db_id is not None and db_id.text == str(mal_id):
                                watched_episodes = int(anime.find('my_watched_episodes').text or 0)
                                break
                            elif anime.find('series_title').text.lower() == matched_title.lower():
                                watched_episodes = int(anime.find('my_watched_episodes').text or 0)
                                break
                    except Exception as e:
                        print(f"[Launcher] Error reading progress: {e}")
            
            # Get config progress data
            config = load_config()
            progress_data = config.get("progress", {})
            if not isinstance(progress_data, dict):
                progress_data = {}
            
            # Determine next episode path
            next_episode_file = None
            next_episode_name = ""
            
            # Look for an active resume episode (started but not finished)
            active_file = None
            for f in videos:
                f_clean = f.replace("\\", "/")
                saved = progress_data.get(f_clean, {})
                if not isinstance(saved, dict):
                    saved = {}
                if saved.get("time", 0) > 10 and saved.get("percent", 0) < 95:
                    active_file = f
                    break
                    
            if active_file:
                next_episode_file = active_file
                next_episode_name = os.path.basename(next_episode_file)
            else:
                # Find the first unwatched file using parsed episode numbers
                unwatched_files = []
                for v in videos:
                    basename = os.path.basename(v)
                    ep_num = parse_episode_number(basename)
                    if ep_num is not None:
                        is_played = ep_num <= watched_episodes
                    else:
                        is_played = (videos.index(v) + 1) <= watched_episodes
                    if not is_played:
                        unwatched_files.append(v)
                
                if unwatched_files:
                    next_episode_file = unwatched_files[0]
                    next_episode_name = os.path.basename(next_episode_file)
                elif len(videos) > 0:
                    # If all episodes are watched, show the last one as placeholder/replay option
                    next_episode_file = videos[-1]
                    next_episode_name = os.path.basename(next_episode_file)
                
            # Populate files list with progress indicators
            files_list = []
            for v in videos:
                v_clean = v.replace("\\", "/")
                saved = progress_data.get(v_clean, {})
                
                basename = os.path.basename(v)
                ep_num = parse_episode_number(basename)
                if ep_num is not None:
                    is_played = ep_num <= watched_episodes
                else:
                    is_played = (videos.index(v) + 1) <= watched_episodes
                    
                files_list.append({
                    "name": basename,
                    "path": v_clean,
                    "progress_time": saved.get("time", 0),
                    "progress_length": saved.get("length", 0),
                    "progress_percent": saved.get("percent", 0),
                    "episode_number": ep_num,
                    "is_played": is_played
                })
                
            library.append({
                "folder_name": folder_name,
                "title": matched_title,
                "mal_id": mal_id,
                "total_files": len(videos),
                "watched_episodes": watched_episodes,
                "next_episode_name": next_episode_name,
                "next_episode_path": next_episode_file.replace("\\", "/") if next_episode_file else None,
                "cover_image": cover_image,
                "files": files_list
            })
            
    print(f"[Launcher] Scan complete. Found {len(library)} anime folders.")
    return library

class MyHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to suppress standard HTTP logging to keep console clean
        pass

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        
        if url.path == '/':
            # Serve the main index.html
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            with open(get_resource_path('index.html'), 'r', encoding='utf-8') as f:
                self.wfile.write(f.read().encode('utf-8'))
                
        elif url.path == '/api/torrent/search':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            # Query parameter
            query_parsed = urllib.parse.parse_qs(url.query)
            query_text = query_parsed.get('query', [''])[0]
            episode = query_parsed.get('episode', [''])[0]
            type_param = query_parsed.get('type', [''])[0]
            # season_pack=1 -> look for a whole-season pack/batch instead of a
            # single episode (used when catching up on many missing episodes).
            season_pack = query_parsed.get('season_pack', ['0'])[0] in ('1', 'true')
            # exclude=Title A|Title B -> titles of related-but-different entries
            # (sequels/spin-offs from AniList relations, e.g. "Boruto: Naruto Next
            # Generations" when searching "Naruto") whose results must be filtered out.
            exclude_text = query_parsed.get('exclude', [''])[0]
            exclude_titles = [t.strip() for t in exclude_text.split('|') if t.strip()]

            if not query_text:
                self.wfile.write(json.dumps([]).encode('utf-8'))
                return

            # Allow free-text queries like "Naruto episode 5" / "Naruto ep 5" /
            # "Naruto épisode 5" to specify the episode without a separate parameter.
            ep_text_match = None
            if type_param != 'manual':
                ep_text_match = re.search(r'\s*(?:episode|épisode|ep)\s*0*(\d+)\s*$', query_text, re.IGNORECASE)
            if ep_text_match:
                if not episode:
                    episode = ep_text_match.group(1)
                query_text = query_text[:ep_text_match.start()].strip()
                if not query_text:
                    self.wfile.write(json.dumps([]).encode('utf-8'))
                    return

            # Parse the requested episode number (if any) for precise filtering
            ep_int = None
            if episode and type_param not in ('manual', 'kai'):
                try:
                    ep_int = int(episode)
                except ValueError:
                    ep_int = None

            # Split by | to handle multiple title variations
            input_titles = [t.strip() for t in query_text.split('|') if t.strip()]
            
            # Build search queries (strictly VOSTFR as requested)
            search_queries = []
            query_seasons = {}
            for title_item in input_titles:
                variations = [title_item]
                # Also try simplified name variations by splitting on colon or dash
                for sep in [':', '-']:
                    if sep in title_item:
                        part0 = title_item.split(sep)[0].strip()
                        if len(part0) >= 3 and part0 not in variations:
                            variations.append(part0)
                # Determine the season from the full title_item so that
                # simplified variations (which may lose the season marker)
                # still get matched against the correct season.
                item_season = extract_season_number(title_item) or 1
                # The franchise "root" (without season markers) is the stable
                # anchor used by French releases, e.g. "Fire Force S02 VOSTFR".
                root = strip_season_markers(title_item)
                if root and root not in variations:
                    variations.append(root)
                    query_seasons[root] = item_season
                for v in variations:
                    query_seasons.setdefault(v, item_season)
                    v_root = strip_season_markers(v) or v
                    season_tag = f"S{item_season:02d}"
                    if type_param == 'kai':
                        # Search for specific terms first to avoid generic name flooding
                        search_queries.append((v, f"{v} Fan-Kai"))
                        search_queries.append((v, f"{v} Fan-Kaï"))
                        search_queries.append((v, f"{v} Henshu"))
                        search_queries.append((v, f"{v} Henshū"))
                        search_queries.append((v, f"{v} Kai"))
                        search_queries.append((v, f"{v} Kaï"))
                        search_queries.append((v, f"{v} intégrale"))
                        search_queries.append((v, f"{v} integrale"))
                    elif season_pack:
                        # Look for a whole-season pack: anchor on the franchise
                        # root + season tag, which is how packs are named
                        # (e.g. "Fire Force S02 VOSTFR", "Enen no Shouboutai S02").
                        search_queries.append((v, f"{v_root} {season_tag} VOSTFR"))
                        search_queries.append((v, f"{v_root} Saison {item_season} VOSTFR"))
                        search_queries.append((v, f"{v_root} {season_tag} Batch VOSTFR"))
                        search_queries.append((v, f"{v_root} intégrale VOSTFR"))
                    elif type_param == 'manual':
                        # For manual search, search exactly what the user typed
                        search_queries.append((v, v))
                        # Also try a season-anchored query on the franchise root,
                        # since the bare title alone often surfaces other-season
                        # releases (e.g. "Enen no Shouboutai" returns mostly
                        # Season 3) while the right results are tagged "S0X VOSTFR".
                        search_queries.append((v, f"{v_root} {season_tag} VOSTFR"))
                    elif episode:
                        # Format episode as 2 digits (e.g. 05)
                        try:
                            ep_int = int(episode)
                            ep_str = f"{ep_int:02d}"
                        except ValueError:
                            ep_str = episode
                        search_queries.append((v, f"{v} {ep_str} VOSTFR"))
                        # Also search for a season pack (e.g. "S02 VOSTFR"), since
                        # some seasons are only released as a single pack without
                        # per-episode numbering in the title (e.g. "Enen no
                        # Shouboutai - Ni no Shou - S02 - VOSTFR").
                        search_queries.append((v, f"{v_root} {season_tag} VOSTFR"))
                    else:
                        search_queries.append((v, f"{v} VOSTFR"))
                
            # Perform RSS fetches
            results = []
            seen_magnets = set()
            # Relaxed tier: candidates that passed the hard filters (French sub,
            # episode/pack, not an excluded related series) but failed the strict
            # name/season match. Shown only as an automatic fallback when the
            # strict results are empty (flagged "approximate" so the UI can warn).
            relaxed_results = []
            relaxed_seen = set()

            def matches_excluded(title):
                """True if the title belongs to a related-but-different entry
                (e.g. "Boruto: Naruto Next Generations" when searching "Naruto")."""
                return any(
                    check_title_match(ex, title, ignore_season=True)
                    for ex in exclude_titles
                )

            for v, q in search_queries:
                url_q = urllib.parse.urlencode({
                    "page": "rss",
                    "q": q
                })
                nyaa_url = f"https://nyaa.si/?{url_q}"
                req = urllib.request.Request(nyaa_url, headers={"User-Agent": "Mozilla/5.0"})
                try:
                    with urllib.request.urlopen(req, timeout=5) as response:
                        xml_data = response.read()
                    root = ET.fromstring(xml_data)
                    for item in root.findall('.//item'):
                        title = item.find('title').text
                        link = item.find('link').text
                        
                        magnet = None
                        info_hash = None
                        size = "Unknown"
                        seeders = "0"
                        leechers = "0"
                        
                        # Parse custom nyaa namespace tags
                        for child in item:
                            if 'magnet' in child.tag:
                                magnet = child.text
                            elif 'infohash' in child.tag.lower():
                                info_hash = child.text
                            elif 'size' in child.tag:
                                size = child.text
                            elif 'seeders' in child.tag:
                                seeders = child.text
                            elif 'leechers' in child.tag:
                                leechers = child.text
                                
                        # Construct magnet link from infoHash if direct magnet tag is missing
                        if not magnet and info_hash:
                            magnet = f"magnet:?xt=urn:btih:{info_hash}&dn={urllib.parse.quote(title)}&tr=http%3A%2F%2Ftracker.nyaa.si%3A80%2Fannounce&tr=udp%3A%2F%2Ftracker.coppersurfer.tk%3A6969%2Fannounce&tr=udp%3A%2F%2Ftracker.opentrackr.org%3A1337%2Fannounce"
                        elif not magnet and link.startswith('magnet:'):
                            magnet = link
                            
                        if not magnet:
                            continue
                            
                        if magnet in seen_magnets or magnet in relaxed_seen:
                            continue

                        # --- Hard filters (apply to strict AND relaxed tiers) ---
                        # Strictly enforce French subbed/VOSTFR (more permissive for Kaï)
                        if not is_french_subbed(title.lower(), is_kai=(type_param == 'kai')):
                            continue

                        # If type=kai is requested, enforce that the title contains Kai keywords
                        if type_param == 'kai':
                            if not any(kw in title.lower() for kw in KAI_KEYWORDS):
                                continue

                        # If a specific episode was requested, reject titles for a
                        # different episode/season (e.g. "episode 1" matching "season 4")
                        if ep_int is not None and not episode_matches(title, ep_int):
                            continue

                        # In season-pack mode, only keep whole-season packs/batches
                        if season_pack and not is_season_pack(title):
                            continue

                        # --- Name/season match against the requested series ---
                        if type_param == 'kai':
                            strict_match = True
                        elif type_param == 'manual':
                            # Manual search favours recall: any title that leads with
                            # the query (in a compatible season) is a real result; the
                            # user picks from the list.
                            strict_match = (manual_title_match(v, title)
                                            and season_compatible(v, title, query_season=query_seasons.get(v)))
                        else:
                            strict_match = check_title_match(v, title, query_season=query_seasons.get(v))

                        result_dict = {
                            "title": title,
                            "magnet": magnet,
                            "torrent_url": link,
                            "is_pack": is_season_pack(title),
                            "size": size,
                            "seeders": int(seeders) if seeders.isdigit() else 0,
                            "leechers": int(leechers) if leechers.isdigit() else 0,
                            "source": "nyaa"
                        }

                        if strict_match:
                            # A genuine match for the requested series is always kept,
                            # even if its name overlaps an excluded relative.
                            seen_magnets.add(magnet)
                            results.append(result_dict)
                        elif matches_excluded(title):
                            # Belongs to a related-but-different entry (e.g. Boruto
                            # when searching Naruto) -> drop it entirely.
                            continue
                        else:
                            # Doesn't clearly match the series nor a known relative:
                            # keep as an approximate fallback only.
                            relaxed_seen.add(magnet)
                            relaxed_results.append({**result_dict, "approximate": True})
                except Exception as e:
                    print(f"[Nyaa] Error searching for {q}: {e}")

                # If we have collected enough good matches, stop making further network requests
                if len(results) >= 5:
                    break

            # Merge in matching items from the animevost.fr (Tsundere-Raws) latest uploads feed.
            # That feed has no magnet/seeders/size, only a title and a nyaa.si .torrent link.
            seen_links = {r['torrent_url'] for r in results if r.get('torrent_url')}
            all_variations = []
            for title_item in input_titles:
                item_season = extract_season_number(title_item) or 1
                if title_item not in all_variations:
                    all_variations.append(title_item)
                    query_seasons[title_item] = item_season
                for sep in [':', '-']:
                    if sep in title_item:
                        part0 = title_item.split(sep)[0].strip()
                        if len(part0) >= 3 and part0 not in all_variations:
                            all_variations.append(part0)
                            query_seasons[part0] = item_season

            for av_item in fetch_animevost_feed():
                av_title = av_item['title']
                av_link = av_item['link']

                if av_link in seen_magnets or av_link in seen_links:
                    continue

                if not is_french_subbed(av_title.lower(), is_kai=(type_param == 'kai')):
                    continue

                if type_param == 'kai':
                    av_title_lower = av_title.lower()
                    if not any(kw in av_title_lower for kw in KAI_KEYWORDS):
                        continue

                if ep_int is not None and not episode_matches(av_title, ep_int):
                    continue

                if season_pack and not is_season_pack(av_title):
                    continue

                # The animevost feed isn't query-filtered (always the latest uploads),
                # so always match the title against the requested anime.
                if type_param == 'manual':
                    strict_match = any(
                        manual_title_match(v, av_title)
                        and season_compatible(v, av_title, query_season=query_seasons.get(v))
                        for v in all_variations
                    )
                else:
                    strict_match = any(
                        check_title_match(v, av_title, query_season=query_seasons.get(v))
                        for v in all_variations
                    )

                av_dict = {
                    "title": av_title,
                    "magnet": None,
                    "torrent_url": av_link,
                    "is_pack": is_season_pack(av_title),
                    "size": "Unknown",
                    "seeders": 0,
                    "leechers": 0,
                    "source": "animevost"
                }

                # Only keep genuine matches from the animevost feed. Its items are
                # the latest uploads regardless of the query, so a non-match here is
                # unrelated noise (Detective Conan, Iruma-kun, ...) — never surface
                # those as an "approximate" fallback.
                if strict_match:
                    seen_links.add(av_link)
                    results.append(av_dict)

            # Automatic fallback: if nothing matched strictly, surface the relaxed
            # (approximate) candidates from nyaa (query-related) rather than an empty
            # list.
            if not results and relaxed_results:
                results = relaxed_results

            # Sort by seeders descending; in season-pack mode, prefer packs first.
            if season_pack:
                results.sort(key=lambda x: (x.get('is_pack', False), x['seeders']), reverse=True)
            else:
                results.sort(key=lambda x: x['seeders'], reverse=True)
            self.wfile.write(json.dumps(results).encode('utf-8'))
            
        elif url.path == '/api/anilist/watching':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            config = load_config()
            token = config.get("anilist_token")
            username = None
            if token:
                username = config.get("anilist_username")
                if not username:
                    username = fetch_anilist_viewer_username(token)
                    if username:
                        config["anilist_username"] = username
                        save_config(config)

            if not username:
                username = "AvocadoDeska"

            watching = []
            data = fetch_anilist_progress_cached(username)
            if data:
                try:
                    lists = data.get('data', {}).get('MediaListCollection', {}).get('lists', [])
                    for lst in lists:
                        for entry in lst.get('entries', []):
                            if entry.get('status') != 'CURRENT':
                                continue
                            media = entry.get('media', {})
                            mal_id = media.get('idMal')
                            title = media.get('title', {}).get('romaji') or media.get('title', {}).get('english')
                            if not mal_id or not title:
                                continue
                            cover = (media.get('coverImage') or {}).get('large') or (media.get('coverImage') or {}).get('medium') or ''
                            watching.append({
                                "title": title,
                                "mal_id": int(mal_id),
                                "cover_image": cover,
                                "progress": entry.get('progress', 0),
                                "episodes": media.get('episodes')
                            })
                except Exception as e:
                    print(f"[API] Error parsing AniList watching list: {e}")

            self.wfile.write(json.dumps(watching).encode('utf-8'))

        elif url.path == '/api/suggestions':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            config = load_config()
            token = config.get("anilist_token")
            username = None
            if token:
                username = config.get("anilist_username")
                if not username:
                    username = fetch_anilist_viewer_username(token)
                    if username:
                        config["anilist_username"] = username
                        save_config(config)
            
            if not username:
                username = "AvocadoDeska"
                
            recs = get_recommendations_from_anilist(username)
            if recs is not None and len(recs) > 0:
                # Save to cache
                try:
                    with open(RECOMMENDATIONS_CACHE_PATH, 'w', encoding='utf-8') as f:
                        json.dump(recs, f, indent=4, ensure_ascii=False)
                except Exception as e:
                    print(f"[API] Error writing recommendations cache: {e}")
            else:
                # Fallback to cache if available
                if os.path.exists(RECOMMENDATIONS_CACHE_PATH):
                    try:
                        with open(RECOMMENDATIONS_CACHE_PATH, 'r', encoding='utf-8') as f:
                            recs = json.load(f)
                        print("[API] Loaded recommendations from local cache.")
                    except Exception as e:
                        print(f"[API] Error reading recommendations cache: {e}")
                        recs = None
            
            # Filter recommendations (either fresh or cached) on the fly
            existing_xml_ids = set()
            if os.path.exists(XML_PATH):
                try:
                    parser = ET.XMLParser(encoding="utf-8")
                    tree = ET.parse(XML_PATH, parser=parser)
                    root = tree.getroot()
                    for anime in root.findall('anime'):
                        db_id = anime.find('series_animedb_id')
                        if db_id is not None and db_id.text:
                            existing_xml_ids.add(int(db_id.text))
                except Exception as e:
                    print(f"[API] Error reading XML for filtering: {e}")
            
            skipped_recs = set(config.get("skipped_recommendations", []))
            
            local_ids_set = set()
            folder_mappings = config.get("folder_mappings", {})
            anime_dir = config.get("anime_dir", r"C:\Anime")
            if os.path.exists(anime_dir):
                try:
                    for entry in os.scandir(anime_dir):
                        if entry.is_dir():
                            if entry.name in folder_mappings:
                                local_ids_set.add(int(folder_mappings[entry.name]))
                                continue
                            norm_folder = re.sub(r'[\s\-_.]', '', entry.name.lower())
                            for title, m_id in SUGGESTIONS:
                                norm_title = re.sub(r'[\s\-_.]', '', title.lower())
                                if len(norm_title) >= 4 and len(norm_folder) >= 4 and (norm_folder in norm_title or norm_title in norm_folder):
                                    local_ids_set.add(int(m_id))
                                    break
                except Exception:
                    pass
            
            if recs is not None and len(recs) > 0:
                filtered_recs = []
                for r in recs:
                    mal_id = r.get('mal_id')
                    if mal_id:
                        mal_id_int = int(mal_id)
                        if mal_id_int in existing_xml_ids or mal_id_int in skipped_recs or mal_id_int in local_ids_set:
                            continue
                        filtered_recs.append(r)
                self.wfile.write(json.dumps(filtered_recs).encode('utf-8'))
            else:
                # If recommendations are not available, fetch trending anime dynamically via AniList!
                print("[API] No custom recommendations. Fetching live trending anime from AniList...")
                trending = fetch_anilist_trending()
                if trending:
                    filtered_trending = []
                    for t_anime in trending:
                        mal_id = t_anime.get('mal_id')
                        if mal_id:
                            mal_id_int = int(mal_id)
                            if mal_id_int in existing_xml_ids or mal_id_int in skipped_recs or mal_id_int in local_ids_set:
                                continue
                            filtered_trending.append(t_anime)
                    self.wfile.write(json.dumps(filtered_trending).encode('utf-8'))
                else:
                    # Absolute fallback to local static SUGGESTIONS
                    filtered = [
                        {"title": title, "mal_id": mal_id}
                        for title, mal_id in SUGGESTIONS
                        if mal_id not in existing_xml_ids and mal_id not in skipped_recs and mal_id not in local_ids_set
                    ]
                    self.wfile.write(json.dumps(filtered).encode('utf-8'))
            
        elif url.path == '/api/launcher/library':
            # Serve local scanned library
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            config = load_config()
            anime_dir = config.get("anime_dir", r"C:\Anime")
            
            if not os.path.exists(anime_dir):
                res = {"success": False, "anime_dir": anime_dir, "error": "directory_not_found"}
            else:
                try:
                    lib_data = get_library(anime_dir)
                    res = {"success": True, "anime_dir": anime_dir, "library": lib_data}
                except Exception as e:
                    print(f"[API] Error scanning library: {e}")
                    res = {"success": False, "anime_dir": anime_dir, "error": str(e)}
                
            self.wfile.write(json.dumps(res).encode('utf-8'))
            
        elif url.path == '/api/movies/library':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            config = load_config()
            movies_dir = config.get("movies_dir", r"C:\Films")
            trakt_client_id = config.get("trakt_client_id")
            tmdb_api_key = config.get("tmdb_api_key")

            if not os.path.exists(movies_dir):
                res = {"success": False, "movies_dir": movies_dir, "error": "directory_not_found"}
            else:
                try:
                    movies = []
                    for f in os.listdir(movies_dir):
                        full_path = os.path.join(movies_dir, f)
                        if os.path.isfile(full_path) and f.lower().endswith(('.mkv', '.mp4', '.avi', '.mov')):
                            guessed_title, guessed_year = guess_movie_title_from_filename(f)
                            trakt_movie = fetch_trakt_movie(guessed_title, trakt_client_id, guessed_year)
                            tmdb_id = trakt_movie.get("ids", {}).get("tmdb") if trakt_movie else None
                            movie_entry = {
                                "file_name": f,
                                "file_path": full_path,
                                "title": trakt_movie.get("title") if trakt_movie else guessed_title,
                                "year": trakt_movie.get("year") if trakt_movie else guessed_year,
                                "trakt_id": trakt_movie.get("ids", {}).get("trakt") if trakt_movie else None,
                                "poster_url": fetch_tmdb_poster_url(tmdb_id, tmdb_api_key),
                            }
                            movies.append(movie_entry)
                    res = {"success": True, "movies_dir": movies_dir, "movies": movies}
                except Exception as e:
                    print(f"[API] Error scanning movies library: {e}")
                    res = {"success": False, "movies_dir": movies_dir, "error": str(e)}

            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif url.path == '/api/movies/search':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            config = load_config()
            client_id = config.get("trakt_client_id")
            tmdb_api_key = config.get("tmdb_api_key")
            query_params = urllib.parse.parse_qs(url.query)
            query = query_params.get('query', [''])[0]

            if not client_id:
                res = {"success": False, "error": "trakt_not_connected"}
            else:
                try:
                    movies = search_trakt_movies(query, client_id)
                    results = [
                        {
                            "title": m.get("title"),
                            "year": m.get("year"),
                            "trakt_id": m.get("ids", {}).get("trakt"),
                            "poster_url": fetch_tmdb_poster_url(m.get("ids", {}).get("tmdb"), tmdb_api_key)
                        }
                        for m in movies
                    ]
                    res = {"success": True, "results": results}
                except Exception as e:
                    print(f"[Trakt] Error searching movies: {e}")
                    res = {"success": False, "error": str(e)}

            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif url.path == '/api/movies/export_letterboxd':
            config = load_config()
            ratings = config.get("letterboxd_ratings", [])

            output = io.StringIO()
            writer = csv.writer(output)
            writer.writerow(["Title", "Year", "Rating", "WatchedDate"])
            for r in ratings:
                writer.writerow([r.get("title", ""), r.get("year", ""), r.get("rating", ""), r.get("watched_date", "")])

            csv_data = output.getvalue()
            self.send_response(200)
            self.send_header('Content-type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="letterboxd_import.csv"')
            self.end_headers()
            self.wfile.write(csv_data.encode('utf-8'))

        elif url.path == '/api/letterboxd/friends_activity':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            config = load_config()
            friends_raw = config.get("letterboxd_friends", "")
            usernames = [u.strip() for u in re.split(r'[,\n]+', friends_raw) if u.strip()]

            activity = []
            for username in usernames:
                activity.extend(fetch_letterboxd_user_rss(username)[:10])

            def sort_key(entry):
                try:
                    return parsedate_to_datetime(entry.get("pubDate", ""))
                except Exception:
                    return datetime.min.replace(tzinfo=timezone.utc)

            activity.sort(key=sort_key, reverse=True)

            res = {"success": True, "activity": activity[:30]}
            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif url.path == '/api/movies/recommendations':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            config = load_config()
            client_id = config.get("trakt_client_id")
            access_token = config.get("trakt_access_token")
            tmdb_api_key = config.get("tmdb_api_key")

            if not (client_id and access_token):
                res = {"success": False, "error": "trakt_not_connected"}
            else:
                try:
                    movies = fetch_trakt_movie_recommendations(client_id, access_token)
                    recs = [
                        {
                            "title": m.get("title"),
                            "year": m.get("year"),
                            "trakt_id": m.get("ids", {}).get("trakt"),
                            "poster_url": fetch_tmdb_poster_url(m.get("ids", {}).get("tmdb"), tmdb_api_key)
                        }
                        for m in movies
                    ]
                    res = {"success": True, "recommendations": recs}
                except Exception as e:
                    print(f"[Trakt] Error fetching movie recommendations: {e}")
                    res = {"success": False, "error": str(e)}

            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif url.path == '/api/movies/watchlist':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            config = load_config()
            client_id = config.get("trakt_client_id")
            access_token = config.get("trakt_access_token")
            tmdb_api_key = config.get("tmdb_api_key")

            if not (client_id and access_token):
                res = {"success": False, "error": "trakt_not_connected"}
            else:
                try:
                    items = fetch_trakt_watchlist_movies(client_id, access_token)
                    watchlist = [
                        {
                            "title": item.get("movie", {}).get("title"),
                            "year": item.get("movie", {}).get("year"),
                            "trakt_id": item.get("movie", {}).get("ids", {}).get("trakt"),
                            "poster_url": fetch_tmdb_poster_url(item.get("movie", {}).get("ids", {}).get("tmdb"), tmdb_api_key)
                        }
                        for item in items
                    ]
                    res = {"success": True, "watchlist": watchlist}
                except Exception as e:
                    print(f"[Trakt] Error fetching watchlist: {e}")
                    res = {"success": False, "error": str(e)}

            self.wfile.write(json.dumps(res).encode('utf-8'))

        elif url.path == '/api/launcher/config':
            # GET current config
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(load_config()).encode('utf-8'))
            
        elif url.path == '/api/launcher/vlc_status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(vlc_status_data).encode('utf-8'))

        elif url.path == '/api/agenda':
            # Returns the airing schedule for the user's currently-watching anime
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            
            config = load_config()
            token = config.get('anilist_token')
            username = None
            if token:
                username = config.get('anilist_username')
                if not username:
                    username = fetch_anilist_viewer_username(token)
                    if username:
                        config['anilist_username'] = username
                        save_config(config)
            
            if not username:
                self.wfile.write(json.dumps([]).encode('utf-8'))
                return
            
            # Get CURRENT (watching) anime from AniList with their AniList IDs
            anilist_ids = []
            user_progress_map = {}  # anilist_id -> progress count
            
            progress_data = fetch_anilist_progress_cached(username)
            if progress_data:
                lists_all = progress_data.get('data', {}).get('MediaListCollection', {}).get('lists', [])
                for lst in lists_all:
                    for entry in lst.get('entries', []):
                        entry_status = (entry.get('status') or '').upper()
                        if entry_status == 'CURRENT':
                            media = entry.get('media', {})
                            anilist_id = media.get('id')
                            if anilist_id:
                                anilist_ids.append(int(anilist_id))
                                user_progress_map[int(anilist_id)] = entry.get('progress', 0)
            
            if not anilist_ids:
                self.wfile.write(json.dumps([]).encode('utf-8'))
                return
            
            print(f"[Agenda] Fetching airing schedule for {len(anilist_ids)} CURRENT anime...")
            # AniList airingSchedules query supports at most ~25 IDs reliably
            schedule_data = fetch_airing_schedule(anilist_ids[:25])
            
            if not schedule_data:
                self.wfile.write(json.dumps([]).encode('utf-8'))
                return
            
            # Build agenda entries
            agenda = []
            schedules = schedule_data.get('data', {}).get('Page', {}).get('airingSchedules', [])
            seen_media_episodes = set()  # deduplicate: only 1 entry per media
            
            for sched in schedules:
                media = sched.get('media', {})
                anilist_id = media.get('id')
                mal_id = media.get('idMal')
                episode = sched.get('episode')
                airing_at = sched.get('airingAt')
                time_until = sched.get('timeUntilAiring')
                
                # Skip if we already have a closer entry for this show
                dedup_key = (anilist_id)
                if dedup_key in seen_media_episodes:
                    continue
                seen_media_episodes.add(dedup_key)
                
                title_romaji = media.get('title', {}).get('romaji') or media.get('title', {}).get('english') or 'Unknown'
                cover = (media.get('coverImage') or {}).get('large') or (media.get('coverImage') or {}).get('medium') or ''
                banner = media.get('bannerImage') or ''
                user_ep_progress = user_progress_map.get(int(anilist_id) if anilist_id else -1, 0)
                
                entry = {
                    'anilist_id': anilist_id,
                    'mal_id': int(mal_id) if mal_id else None,
                    'title': title_romaji,
                    'episode': episode,
                    'airing_at': airing_at,
                    'time_until_airing': time_until,
                    'cover_image': cover,
                    'banner_image': banner,
                    'user_progress': user_ep_progress
                }
                agenda.append(entry)
            
            # Sort: already aired (timeUntil <= 0) first, then by nearest upcoming
            agenda.sort(key=lambda x: (1 if (x['time_until_airing'] or 0) > 0 else 0, abs(x['time_until_airing'] or 0)))
            
            print(f"[Agenda] Returning {len(agenda)} airing schedule entries.")
            self.wfile.write(json.dumps(agenda).encode('utf-8'))

        elif url.path == '/api/anilist/planning':
            # Returns the user's PLANNING (À Voir) list from AniList with cover images
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            config = load_config()
            token = config.get('anilist_token')
            username = None
            if token:
                username = config.get('anilist_username')
                if not username:
                    username = fetch_anilist_viewer_username(token)
                    if username:
                        config['anilist_username'] = username
                        save_config(config)

            if not username:
                self.wfile.write(json.dumps([]).encode('utf-8'))
                return

            progress_data = fetch_anilist_progress_cached(username)
            planning_list = []

            if progress_data:
                lists_all = progress_data.get('data', {}).get('MediaListCollection', {}).get('lists', [])
                for lst in lists_all:
                    for entry in lst.get('entries', []):
                        entry_status = (entry.get('status') or '').upper()
                        if entry_status == 'PLANNING':
                            media = entry.get('media', {})
                            anilist_id = media.get('id')
                            mal_id = media.get('idMal')
                            title = (media.get('title') or {}).get('romaji') or (media.get('title') or {}).get('english') or 'Unknown'
                            cover = (media.get('coverImage') or {}).get('large') or (media.get('coverImage') or {}).get('medium') or ''
                            banner = media.get('bannerImage') or ''
                            score = media.get('meanScore') or 0
                            episodes = media.get('episodes') or 0
                            genres = media.get('genres') or []
                            year = media.get('seasonYear') or ''
                            planning_list.append({
                                'anilist_id': anilist_id,
                                'mal_id': int(mal_id) if mal_id else None,
                                'title': title,
                                'cover_image': cover,
                                'banner_image': banner,
                                'score': score,
                                'episodes': episodes,
                                'genres': genres,
                                'year': year
                            })

            print(f"[Planning] Returning {len(planning_list)} PLANNING entries for {username}.")
            self.wfile.write(json.dumps(planning_list).encode('utf-8'))

        else:
            # Fallback to serving local static files if needed. Block files that
            # contain secrets or private data — the static handler serves from the
            # working directory, which holds config.json (tokens/passwords), the
            # MAL export and the recommendation caches.
            normalized = os.path.normpath(urllib.parse.unquote(url.path)).replace('\\', '/').lstrip('/')
            blocked_names = {'config.json', 'config.example.json', 'myanimelist.xml',
                             'recommendations_cache.json'}
            base = os.path.basename(normalized).lower()
            if (base in blocked_names or base.endswith('.json') or base.endswith('.xml')
                    or base.endswith('.py') or base.endswith('.log')):
                self.send_error(403, "Forbidden")
                return
            super().do_GET()

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)

        if url.path == '/api/cache/clear':
            # Force-clear all in-memory and file caches so next load fetches fresh AniList data
            global anilist_progress_cache
            # Also delete recommendations cache file
            if os.path.exists(RECOMMENDATIONS_CACHE_PATH):
                try:
                    os.remove(RECOMMENDATIONS_CACHE_PATH)
                    print("[Cache] Recommendations cache file deleted.")
                except Exception as e:
                    print(f"[Cache] Could not delete recommendations cache: {e}")
            # Mark AniList cache as stale (timestamp=0) instead of deleting it entirely.
            # This way concurrent requests get the old data as fallback if the fresh fetch fails.
            for k in list(anilist_progress_cache.keys()):
                anilist_progress_cache[k]["timestamp"] = 0
            print("[Cache] AniList progress cache marked as stale (will refresh on next request).")
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True}).encode('utf-8'))

        elif url.path == '/api/add':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            mal_id = params.get('mal_id')
            title = params.get('title')
            status = params.get('status')
            
            if mal_id and title and status:
                success = add_to_xml(title, mal_id, status)
                self.send_response(200 if success else 500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            else:
                self.send_response(400)
                self.end_headers()
                
        elif url.path == '/api/recommendations/skip':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            mal_id = params.get('mal_id')
            if mal_id:
                config = load_config()
                if "skipped_recommendations" not in config:
                    config["skipped_recommendations"] = []
                mal_id_int = int(mal_id)
                if mal_id_int not in config["skipped_recommendations"]:
                    config["skipped_recommendations"].append(mal_id_int)
                save_config(config)
                
                # Also filter out the skipped one from cache if it exists
                if os.path.exists(RECOMMENDATIONS_CACHE_PATH):
                    try:
                        with open(RECOMMENDATIONS_CACHE_PATH, 'r', encoding='utf-8') as f:
                            cached_recs = json.load(f)
                        if cached_recs:
                            filtered_cache = [r for r in cached_recs if r.get('mal_id') != mal_id_int]
                            with open(RECOMMENDATIONS_CACHE_PATH, 'w', encoding='utf-8') as f:
                                json.dump(filtered_cache, f, indent=4, ensure_ascii=False)
                    except Exception:
                        pass
                
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
            else:
                self.send_response(400)
                self.end_headers()
                
        elif url.path == '/api/launcher/map_folder':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            folder_name = params.get('folder_name')
            mal_id = params.get('mal_id')
            
            if folder_name and mal_id:
                config = load_config()
                if "folder_mappings" not in config:
                    config["folder_mappings"] = {}
                config["folder_mappings"][folder_name] = int(mal_id)
                success = save_config(config)
                
                self.send_response(200 if success else 500)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
            else:
                self.send_response(400)
                self.end_headers()
                
        elif url.path == '/api/torrent/download':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            magnet = params.get('magnet')
            torrent_url = params.get('torrent_url')
            anime_title = params.get('anime_title')

            if (not magnet and not torrent_url) or not anime_title:
                self.send_response(400)
                self.end_headers()
                return
                
            config = load_config()
            anime_dir = config.get("anime_dir", r"C:\Anime")
            
            # Sanitize folder name
            clean_title = re.sub(r'[\\/*?:"<>|]', "", anime_title).strip()
            download_path = os.path.join(anime_dir, clean_title)
            
            if not os.path.exists(download_path):
                try:
                    os.makedirs(download_path, exist_ok=True)
                except Exception as e:
                    print(f"[API] Error creating folder {download_path}: {e}")
                    
            # Try qBittorrent API integration
            qb_enabled = config.get("qbittorrent_enabled", False)
            success = False
            method = "system"
            
            if qb_enabled:
                qb_host = config.get("qbittorrent_host", "http://localhost:8080")
                qb_user = config.get("qbittorrent_username", "admin")
                qb_pass = config.get("qbittorrent_password", "adminadmin")
                
                cj = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
                
                # login
                login_url = f"{qb_host}/api/v2/auth/login"
                login_data = urllib.parse.urlencode({"username": qb_user, "password": qb_pass}).encode('utf-8')
                req_login = urllib.request.Request(login_url, data=login_data)
                
                try:
                    with opener.open(req_login, timeout=3) as resp:
                        body = resp.read().decode('utf-8')
                        if "Ok" in body or resp.status == 200:
                            # add torrent
                            add_url = f"{qb_host}/api/v2/torrents/add"
                            add_data = urllib.parse.urlencode({
                                "urls": torrent_url if torrent_url else magnet,
                                "savepath": os.path.normpath(download_path)
                            }).encode('utf-8')
                            req_add = urllib.request.Request(add_url, data=add_data)
                            with opener.open(req_add, timeout=5) as add_resp:
                                if add_resp.status == 200:
                                    success = True
                                    method = "qbittorrent"
                                    print(f"[qBittorrent] Added torrent for {clean_title} to {download_path}")
                                else:
                                    print(f"[qBittorrent] Error adding torrent: HTTP {add_resp.status}")
                        else:
                            print(f"[qBittorrent] Login failed: {body}")
                except Exception as e:
                    print(f"[qBittorrent] Connection or add failed: {e}")
                    
            if not success:
                # Fallback: try downloading direct .torrent file first, then open it (instantly loads metadata)
                torrent_downloaded = False
                if torrent_url:
                    try:
                        req = urllib.request.Request(
                            torrent_url,
                            headers={"User-Agent": "Mozilla/5.0"}
                        )
                        temp_dir = os.path.join(os.getcwd(), "scratch")
                        os.makedirs(temp_dir, exist_ok=True)
                        
                        safe_filename = re.sub(r'[\\/*?:"<>|]', "", anime_title).strip() + ".torrent"
                        temp_file_path = os.path.join(temp_dir, safe_filename)
                        
                        with urllib.request.urlopen(req, timeout=10) as response:
                            with open(temp_file_path, 'wb') as out_file:
                                out_file.write(response.read())
                                
                        os.startfile(temp_file_path)
                        success = True
                        torrent_downloaded = True
                        method = "system_torrent_file"
                        print(f"[API] Launched system torrent file: {temp_file_path}")
                    except Exception as e:
                        print(f"[API] Error downloading torrent file from {torrent_url}: {e}")
                        
                if not torrent_downloaded and magnet:
                    # Fallback to magnet link
                    try:
                        os.startfile(magnet)
                        success = True
                        method = "system_magnet"
                        print(f"[API] Launched system magnet link")
                    except Exception as e:
                        print(f"[API] Error launching system magnet link: {e}")
                    
            self.send_response(200 if success else 500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "method": method, "path": download_path}).encode('utf-8'))
            
        elif url.path == '/api/torrent/download_batch':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            torrents = params.get('torrents', [])
            anime_title = params.get('anime_title')
            start_ep = params.get('start_ep')
            end_ep = params.get('end_ep')
            
            if not torrents or not anime_title:
                self.send_response(400)
                self.end_headers()
                return
                
            config = load_config()
            anime_dir = config.get("anime_dir", r"C:\Anime")
            
            # Sanitize folder name
            clean_title = re.sub(r'[\\/*?:"<>|]', "", anime_title).strip()
            download_path = os.path.join(anime_dir, clean_title)
            
            if not os.path.exists(download_path):
                try:
                    os.makedirs(download_path, exist_ok=True)
                    print(f"[API] Created anime folder: {download_path}")
                except Exception as e:
                    print(f"[API] Error creating folder {download_path}: {e}")
                    
            qb_enabled = config.get("qbittorrent_enabled", False)
            success = False
            method = "system"
            
            if qb_enabled:
                qb_host = config.get("qbittorrent_host", "http://localhost:8080")
                qb_user = config.get("qbittorrent_username", "admin")
                qb_pass = config.get("qbittorrent_password", "adminadmin")
                
                cj = http.cookiejar.CookieJar()
                opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
                
                # login
                login_url = f"{qb_host}/api/v2/auth/login"
                login_data = urllib.parse.urlencode({"username": qb_user, "password": qb_pass}).encode('utf-8')
                req_login = urllib.request.Request(login_url, data=login_data)
                
                try:
                    with opener.open(req_login, timeout=3) as resp:
                        body = resp.read().decode('utf-8')
                        if "Ok" in body or resp.status == 200:
                            # Check if we have a single pack/batch torrent and we want to select specific files
                            magnet = torrents[0].get('magnet') or ''
                            info_hash = None
                            match_hash = re.search(r'urn:btih:([a-fA-F0-9]{40})', magnet)
                            if match_hash:
                                info_hash = match_hash.group(1).lower()
                            
                            is_pack = len(torrents) == 1 and (torrents[0].get('episode') == 'Pack' or 'pack' in (torrents[0].get('torrent_url') or '').lower() or 'batch' in (torrents[0].get('torrent_url') or '').lower())
                            
                            if is_pack and info_hash and start_ep is not None and end_ep is not None:
                                print(f"[qBittorrent] Selective batch download for pack: {info_hash}")
                                # Check if torrent already exists
                                list_url = f"{qb_host}/api/v2/torrents/info?hashes={info_hash}"
                                req_list = urllib.request.Request(list_url)
                                torrent_exists = False
                                try:
                                    with opener.open(req_list, timeout=3) as list_resp:
                                        t_info = json.loads(list_resp.read().decode('utf-8'))
                                        if t_info:
                                            torrent_exists = True
                                except Exception:
                                    pass
                                    
                                if not torrent_exists:
                                    # Add the torrent paused first
                                    add_url = f"{qb_host}/api/v2/torrents/add"
                                    add_data = urllib.parse.urlencode({
                                        "urls": torrents[0].get('torrent_url') or magnet,
                                        "savepath": os.path.normpath(download_path),
                                        "paused": "true"
                                    }).encode('utf-8')
                                    req_add = urllib.request.Request(add_url, data=add_data)
                                    with opener.open(req_add, timeout=5) as add_resp:
                                        if add_resp.status != 200:
                                            print("[qBittorrent] Failed to add paused pack")
                                            raise Exception("Failed to add paused pack")
                                            
                                # Wait for metadata to be fetched so we can see the files list
                                files = []
                                files_url = f"{qb_host}/api/v2/torrents/files?hash={info_hash}"
                                for retry in range(10):
                                    time.sleep(1)
                                    try:
                                        req_files = urllib.request.Request(files_url)
                                        with opener.open(req_files, timeout=3) as files_resp:
                                            files = json.loads(files_resp.read().decode('utf-8'))
                                            if files:
                                                break
                                    except Exception:
                                        pass
                                        
                                if files:
                                    # Select file IDs to download and files to skip
                                    download_ids = []
                                    skip_ids = []
                                    for idx, f in enumerate(files):
                                        f_name = f.get('name', '')
                                        f_id = f.get('id', idx)
                                        ep_num = parse_episode_number(os.path.basename(f_name))
                                        if ep_num is not None and start_ep <= ep_num <= end_ep:
                                            download_ids.append(str(f_id))
                                        else:
                                            skip_ids.append(str(f_id))
                                            
                                    print(f"[qBittorrent] File selection: downloading={download_ids}, skipping={skip_ids}")
                                    
                                    # Apply priorities
                                    if skip_ids:
                                        prio_url = f"{qb_host}/api/v2/torrents/filePriority"
                                        prio_data = urllib.parse.urlencode({
                                            "hash": info_hash,
                                            "id": "|".join(skip_ids),
                                            "priority": "0"
                                        }).encode('utf-8')
                                        req_prio = urllib.request.Request(prio_url, data=prio_data)
                                        opener.open(req_prio, timeout=3)
                                        
                                    if download_ids:
                                        prio_url = f"{qb_host}/api/v2/torrents/filePriority"
                                        prio_data = urllib.parse.urlencode({
                                            "hash": info_hash,
                                            "id": "|".join(download_ids),
                                            "priority": "1"
                                        }).encode('utf-8')
                                        req_prio = urllib.request.Request(prio_url, data=prio_data)
                                        opener.open(req_prio, timeout=3)
                                        
                                    # Resume torrent
                                    resume_url = f"{qb_host}/api/v2/torrents/resume"
                                    resume_data = urllib.parse.urlencode({"hashes": info_hash}).encode('utf-8')
                                    req_resume = urllib.request.Request(resume_url, data=resume_data)
                                    opener.open(req_resume, timeout=3)
                                    
                                    success = True
                                    method = "qbittorrent"
                                    print(f"[qBittorrent] Selective download complete for {clean_title}")
                                else:
                                    # Fallback: just resume it if we couldn't fetch files (maybe magnet metadata didn't download)
                                    print("[qBittorrent] Could not retrieve files list. Resuming whole torrent.")
                                    resume_url = f"{qb_host}/api/v2/torrents/resume"
                                    resume_data = urllib.parse.urlencode({"hashes": info_hash}).encode('utf-8')
                                    req_resume = urllib.request.Request(resume_url, data=resume_data)
                                    opener.open(req_resume, timeout=3)
                                    success = True
                                    method = "qbittorrent"
                            else:
                                # Normal batch add (non-pack or no hash)
                                urls_list = []
                                for t in torrents:
                                    urls_list.append(t.get('torrent_url') or t.get('magnet'))
                                urls_payload = "\n".join(urls_list)
                                
                                add_url = f"{qb_host}/api/v2/torrents/add"
                                add_data = urllib.parse.urlencode({
                                    "urls": urls_payload,
                                    "savepath": os.path.normpath(download_path)
                                }).encode('utf-8')
                                req_add = urllib.request.Request(add_url, data=add_data)
                                with opener.open(req_add, timeout=5) as add_resp:
                                    if add_resp.status == 200:
                                        success = True
                                        method = "qbittorrent"
                                        print(f"[qBittorrent] Batch added {len(torrents)} torrents for {clean_title} to {download_path}")
                                    else:
                                        print(f"[qBittorrent] Error adding batch torrents: HTTP {add_resp.status}")
                        else:
                            print(f"[qBittorrent] Login failed: {body}")
                except Exception as e:
                    print(f"[qBittorrent] Connection or batch add failed: {e}")
                    
            if not success:
                # CLI or direct system invocation fallback
                qb_path = find_qbittorrent()
                torrent_args = []
                temp_dir = os.path.join(os.getcwd(), "scratch")
                os.makedirs(temp_dir, exist_ok=True)
                
                for idx, t in enumerate(torrents):
                    torrent_url = t.get('torrent_url')
                    magnet = t.get('magnet')
                    
                    torrent_downloaded = False
                    if torrent_url:
                        try:
                            req = urllib.request.Request(
                                torrent_url,
                                headers={"User-Agent": "Mozilla/5.0"}
                            )
                            safe_filename = f"{clean_title}_ep_{t.get('episode', idx)}_{int(time.time())}.torrent"
                            temp_file_path = os.path.normpath(os.path.join(temp_dir, safe_filename))
                            
                            with urllib.request.urlopen(req, timeout=10) as response:
                                with open(temp_file_path, 'wb') as out_file:
                                    out_file.write(response.read())
                                    
                            torrent_args.append(temp_file_path)
                            torrent_downloaded = True
                            print(f"[API] Batch download: saved torrent file to {temp_file_path}")
                        except Exception as e:
                            print(f"[API] Error downloading torrent file from {torrent_url}: {e}")
                            
                    if not torrent_downloaded and magnet:
                        torrent_args.append(magnet)
                        
                if torrent_args:
                    if qb_path:
                        try:
                            cmd = [qb_path, f"--save-path={os.path.normpath(download_path)}"] + torrent_args
                            print(f"[API] Launching qBittorrent CLI: {cmd}")
                            subprocess.Popen(cmd)
                            success = True
                            method = "qbittorrent_cli"
                        except Exception as e:
                            print(f"[API] Error launching qBittorrent via CLI: {e}")
                            
                    if not success:
                        if len(torrent_args) == 1:
                            print(f"[API] qBittorrent CLI not found or failed. Falling back to system association.")
                            try:
                                os.startfile(torrent_args[0])
                                success = True
                                method = "system_association_individual"
                            except Exception as e:
                                print(f"[API] Error opening torrent: {e}")
                        else:
                            # Avoid opening one window per torrent: open the folder
                            # containing all downloaded .torrent files instead.
                            print(f"[API] qBittorrent CLI not found or failed. Opening folder with {len(torrent_args)} torrent files.")
                            try:
                                os.startfile(temp_dir)
                                success = True
                                method = "system_association_folder"
                            except Exception as e:
                                print(f"[API] Error opening torrents folder: {e}")
                            
            self.send_response(200 if success else 500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "method": method, "path": download_path}).encode('utf-8'))
            
        elif url.path == '/api/launcher/delete_episodes':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            folder_name = params.get('folder_name')
            mal_id = params.get('mal_id')
            
            if not folder_name:
                self.send_response(400)
                self.end_headers()
                return
                
            config = load_config()
            anime_dir = config.get("anime_dir", r"C:\Anime")
            folder_path = os.path.join(anime_dir, folder_name)
            
            if not os.path.exists(folder_path):
                self.send_response(404)
                self.end_headers()
                return
                
            # Get watched progress from params, then fallback to AniList or XML
            watched_episodes = params.get('watched_episodes')
            if watched_episodes is None or watched_episodes == 0:
                token = config.get("anilist_token")
                username = None
                if token:
                    username = config.get("anilist_username")
                    if not username:
                        username = fetch_anilist_viewer_username(token)
                        
                if not username:
                    username = "AvocadoDeska"
                    
                watched_episodes = 0
                try:
                    anilist_data = fetch_anilist_progress(username)
                    if anilist_data and mal_id:
                        lists = anilist_data.get('data', {}).get('MediaListCollection', {}).get('lists', [])
                        for lst in lists:
                            for entry in lst.get('entries', []):
                                media = entry.get('media', {})
                                m_id = media.get('idMal')
                                if m_id and int(m_id) == int(mal_id):
                                    watched_episodes = entry.get('progress') or 0
                                    break
                except Exception:
                    pass
                    
                # Fallback to local XML if progress is still 0
                if watched_episodes == 0 and os.path.exists(XML_PATH):
                    try:
                        parser = ET.XMLParser(encoding="utf-8")
                        tree = ET.parse(XML_PATH, parser=parser)
                        root_xml = tree.getroot()
                        for anime in root_xml.findall('anime'):
                            db_id = anime.find('series_animedb_id')
                            if db_id is not None and mal_id and db_id.text == str(mal_id):
                                watched_episodes = int(anime.find('my_watched_episodes').text or 0)
                                break
                            elif anime.find('series_title').text.lower() == folder_name.lower():
                                watched_episodes = int(anime.find('my_watched_episodes').text or 0)
                                break
                    except Exception:
                        pass
            else:
                watched_episodes = int(watched_episodes)
                    
            # Now scan and delete files in folder_path where parsed episode <= watched_episodes
            deleted_count = 0
            deleted_files = []
            
            if watched_episodes > 0:
                try:
                    for root, dirs, files in os.walk(folder_path):
                        for file in files:
                            if file.lower().endswith(('.mkv', '.mp4', '.avi', '.mov')):
                                ep_num = parse_episode_number(file)
                                if ep_num is not None and ep_num <= watched_episodes:
                                    full_path = os.path.join(root, file)
                                    os.remove(full_path)
                                    deleted_count += 1
                                    deleted_files.append(file)
                                    
                    # Clean up progress cache/config
                    progress_data = config.get("progress", {})
                    for df in deleted_files:
                        for k in list(progress_data.keys()):
                            if df in k:
                                del progress_data[k]
                    config["progress"] = progress_data
                    save_config(config)
                except Exception as e:
                    print(f"[API] Error deleting watched files in {folder_path}: {e}")
                    
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "deleted_count": deleted_count, "deleted_files": deleted_files}).encode('utf-8'))
                
        elif url.path == '/api/trakt/device_code':
            config = load_config()
            client_id = config.get("trakt_client_id")

            if not client_id:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "error": "missing_client_id"}).encode('utf-8'))
            else:
                try:
                    result = trakt_request_device_code(client_id)
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, **result}).encode('utf-8'))
                except Exception as e:
                    print(f"[Trakt] Error requesting device code: {e}")
                    self.send_response(500)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": False, "error": str(e)}).encode('utf-8'))

        elif url.path == '/api/trakt/device_token':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            device_code = params.get('device_code')

            config = load_config()
            client_id = config.get("trakt_client_id")
            client_secret = config.get("trakt_client_secret")

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            if not (client_id and client_secret and device_code):
                self.wfile.write(json.dumps({"success": False, "error": "missing_params"}).encode('utf-8'))
            else:
                result = trakt_poll_device_token(client_id, client_secret, device_code)
                if result.get("access_token"):
                    config["trakt_access_token"] = result["access_token"]
                    if result.get("refresh_token"):
                        config["trakt_refresh_token"] = result["refresh_token"]
                    save_config(config)
                    self.wfile.write(json.dumps({"success": True, "authorized": True}).encode('utf-8'))
                elif result.get("pending"):
                    self.wfile.write(json.dumps({"success": True, "authorized": False, "pending": True}).encode('utf-8'))
                else:
                    self.wfile.write(json.dumps({"success": False, "error": result.get("error", "unknown")}).encode('utf-8'))

        elif url.path == '/api/movies/rate':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))

            rating = params.get('rating')
            trakt_id = vlc_status_data.get("movie_trakt_id")

            config = load_config()
            client_id = config.get("trakt_client_id")
            access_token = config.get("trakt_access_token")

            success = False
            if rating and trakt_id and client_id and access_token:
                success = rate_movie_on_trakt(client_id, access_token, trakt_id, rating)

            if rating:
                ratings = config.get("letterboxd_ratings", [])
                ratings.append({
                    "title": vlc_status_data.get("movie_title"),
                    "year": vlc_status_data.get("movie_year"),
                    "rating": round(rating / 2, 1),  # Trakt 1-10 -> Letterboxd 0.5-5 stars
                    "watched_date": datetime.now().strftime('%Y-%m-%d')
                })
                config["letterboxd_ratings"] = ratings
                save_config(config)

            vlc_status_data["movie_rating_prompt"] = False
            vlc_status_data["movie_rated"] = True

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))

        elif url.path == '/api/movies/rate_manual':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))

            rating = params.get('rating')
            trakt_id = params.get('trakt_id')
            title = params.get('title')
            year = params.get('year')

            config = load_config()
            client_id = config.get("trakt_client_id")
            access_token = config.get("trakt_access_token")

            success = False
            if rating and trakt_id and client_id and access_token:
                success = rate_movie_on_trakt(client_id, access_token, trakt_id, rating)

            if rating:
                ratings = config.get("letterboxd_ratings", [])
                ratings.append({
                    "title": title,
                    "year": year,
                    "rating": round(rating / 2, 1),  # Trakt 1-10 -> Letterboxd 0.5-5 stars
                    "watched_date": datetime.now().strftime('%Y-%m-%d')
                })
                config["letterboxd_ratings"] = ratings
                save_config(config)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))

        elif url.path == '/api/movies/watchlist/add':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))

            trakt_id = params.get('trakt_id')

            config = load_config()
            client_id = config.get("trakt_client_id")
            access_token = config.get("trakt_access_token")

            success = False
            if trakt_id and client_id and access_token:
                success = add_movie_to_trakt_watchlist(client_id, access_token, trakt_id)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))

        elif url.path == '/api/launcher/play':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            file_path = params.get('file_path')
            if file_path:
                file_path = os.path.normpath(file_path)
            
            if file_path and os.path.exists(file_path):
                try:
                    # Launch file with Windows default player or VLC with control
                    vlc_path = find_vlc()
                    if vlc_path:
                        # Kill any existing VLC instances so our HTTP interface works
                        try:
                            subprocess.run(['taskkill', '/F', '/IM', 'vlc.exe'], 
                                         capture_output=True, timeout=5)
                            time.sleep(0.5)  # Wait for VLC to fully close
                            print("[Launcher] Killed existing VLC instances.")
                        except Exception:
                            pass
                        
                        # Clear old status
                        vlc_status_data["file_path"] = file_path
                        vlc_status_data["state"] = "playing"
                        vlc_status_data["time"] = 0
                        vlc_status_data["length"] = 0
                        vlc_status_data["remaining"] = 0
                        vlc_status_data["percent"] = 0

                        # Determine if this file lives under the configured movies directory
                        config_for_movies = load_config()
                        movies_dir = config_for_movies.get("movies_dir", r"C:\Films")
                        is_movie = False
                        try:
                            is_movie = os.path.commonpath([os.path.normpath(file_path), os.path.normpath(movies_dir)]) == os.path.normpath(movies_dir)
                        except ValueError:
                            is_movie = False

                        vlc_status_data["is_movie"] = is_movie
                        vlc_status_data["movie_rating_prompt"] = False
                        vlc_status_data["movie_rated"] = False

                        if is_movie:
                            vlc_status_data["mal_id"] = None
                            vlc_status_data["episode_number"] = None
                            vlc_status_data["anilist_synced"] = True

                            guessed_title, guessed_year = guess_movie_title_from_filename(os.path.basename(file_path))
                            trakt_movie = fetch_trakt_movie(guessed_title, config_for_movies.get("trakt_client_id"), guessed_year)
                            if trakt_movie:
                                vlc_status_data["movie_title"] = trakt_movie.get("title")
                                vlc_status_data["movie_year"] = trakt_movie.get("year")
                                vlc_status_data["movie_trakt_id"] = trakt_movie.get("ids", {}).get("trakt")
                            else:
                                vlc_status_data["movie_title"] = guessed_title
                                vlc_status_data["movie_year"] = guessed_year
                                vlc_status_data["movie_trakt_id"] = None

                            subsequent_files = [file_path]
                        else:
                            vlc_status_data["movie_title"] = None
                            vlc_status_data["movie_year"] = None
                            vlc_status_data["movie_trakt_id"] = None

                            # Resolve mal_id/episode number for automatic AniList progress sync
                            update_anilist_sync_status_for_file(file_path)

                            # Build playlist of subsequent episodes in the same folder
                            parent_dir = os.path.dirname(file_path)
                            playlist = []
                            if os.path.exists(parent_dir):
                                for f in os.listdir(parent_dir):
                                    if f.lower().endswith(('.mkv', '.mp4', '.avi', '.mov')):
                                        playlist.append(os.path.normpath(os.path.join(parent_dir, f)))
                                playlist.sort()

                            try:
                                normalized_file_path = os.path.normpath(file_path)
                                current_idx = playlist.index(normalized_file_path)
                                subsequent_files = playlist[current_idx:]
                            except ValueError:
                                subsequent_files = [file_path]

                        cmd = [vlc_path, "--extraintf=http", f"--http-port={VLC_HTTP_PORT}", "--http-password=avocado"]
                        
                        # Check if there is saved time
                        config = load_config()
                        progress_data = config.get("progress", {})
                        if not isinstance(progress_data, dict):
                            progress_data = {}
                        # Normalize the path for lookup (same as save key)
                        lookup_key = os.path.normpath(file_path).replace("\\", "/")
                        saved = progress_data.get(lookup_key, {})
                        if not isinstance(saved, dict):
                            saved = {}
                        saved_time = saved.get("time", 0)
                        percent = saved.get("percent", 0)
                        
                        print(f"[Launcher] Looking up progress for key: {lookup_key}")
                        print(f"[Launcher] Found saved data: time={saved_time}s, percent={percent:.1f}%")
                        
                        # Resume if watched more than 10s and less than 95%
                        if saved_time > 10 and percent < 95:
                            cmd.append(f"--start-time={int(saved_time)}")
                            print(f"[Launcher] Resuming {os.path.basename(file_path)} at {int(saved_time)}s")
                        else:
                            print(f"[Launcher] Launching {os.path.basename(file_path)} from start")
                            
                        # Add subsequent files in order as arguments
                        cmd.extend(subsequent_files)
                        print(f"[Launcher] Full VLC command with playlist: {cmd}")
                        subprocess.Popen(cmd)
                    else:
                        os.startfile(file_path)
                        print(f"[Launcher] Opening file with default association: {file_path}")
                        
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True}).encode('utf-8'))
                except Exception as e:
                    print(f"[Launcher] Error opening file: {e}")
                    self.send_response(500)
                    self.end_headers()
            else:
                print(f"[Launcher] File path invalid or missing: {file_path}")
                self.send_response(400)
                self.end_headers()
                
        elif url.path == '/api/launcher/config':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            params = json.loads(post_data.decode('utf-8'))
            
            config = load_config()
            if 'anime_dir' in params:
                config["anime_dir"] = params['anime_dir']
            if 'anilist_client_id' in params:
                config["anilist_client_id"] = params['anilist_client_id']
            if 'anilist_token' in params:
                config["anilist_token"] = params['anilist_token']
                # Reset cached username when token changes to force re-fetch
                if "anilist_username" in config:
                    del config["anilist_username"]
            if 'qbittorrent_enabled' in params:
                config["qbittorrent_enabled"] = params['qbittorrent_enabled']
            if 'qbittorrent_host' in params:
                config["qbittorrent_host"] = params['qbittorrent_host']
            if 'qbittorrent_username' in params:
                config["qbittorrent_username"] = params['qbittorrent_username']
            if 'qbittorrent_password' in params:
                config["qbittorrent_password"] = params['qbittorrent_password']
            if 'movies_dir' in params:
                config["movies_dir"] = params['movies_dir']
            if 'trakt_client_id' in params:
                config["trakt_client_id"] = params['trakt_client_id']
            if 'trakt_client_secret' in params:
                config["trakt_client_secret"] = params['trakt_client_secret']
            if 'trakt_access_token' in params:
                config["trakt_access_token"] = params['trakt_access_token']
            if 'trakt_refresh_token' in params:
                config["trakt_refresh_token"] = params['trakt_refresh_token']
            if 'letterboxd_friends' in params:
                config["letterboxd_friends"] = params['letterboxd_friends']
            if 'tmdb_api_key' in params:
                config["tmdb_api_key"] = params['tmdb_api_key']

            success = save_config(config)
            
            self.send_response(200 if success else 500)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": success}).encode('utf-8'))
                
        else:
            self.send_response(404)
            self.end_headers()

def main():
    socketserver.TCPServer.allow_reuse_address = True
    
    # Start VLC Status Poller Daemon Thread
    t = threading.Thread(target=poll_vlc_status, daemon=True)
    t.start()
    print("[VLC Poller] Background daemon thread started.")
    
    # Try binding to port with retries to handle TimeWait states on Windows
    httpd = None
    for attempt in range(5):
        try:
            # Bind to loopback only: the server exposes credentials (AniList
            # token, qBittorrent password) and local file access, so it must
            # never be reachable from other machines on the network.
            httpd = socketserver.TCPServer(("127.0.0.1", PORT), MyHandler)
            break
        except OSError as e:
            if attempt == 4:
                print(f"[Server] Failed to bind to port {PORT} after 5 attempts. Exiting.")
                raise e
            print(f"[Server] Port {PORT} is busy, retrying in 2 seconds... (attempt {attempt + 1}/5)")
            time.sleep(2)
            
    if httpd:
        with httpd:
            config = load_config()
            anime_dir = config.get("anime_dir", r"C:\Anime")
            
            print(f"\n=============================================")
            print(f" AvocadoList Builder (Media Server) ")
            print(f" URL d'accès : http://localhost:{PORT}")
            print(f" Dossier Anime scanné : {anime_dir}")
            print(f"=============================================\n")
            print("Ouverture automatique du navigateur...")
            webbrowser.open(f'http://localhost:{PORT}')
            
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print("\nFermeture du serveur.")
                httpd.server_close()

if __name__ == '__main__':
    main()
