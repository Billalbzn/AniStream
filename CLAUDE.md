# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

AvocadoStream is a single-user, local-only anime media server/launcher ("AvocadoList Builder"). It's a Python stdlib-only HTTP server (`app.py`) that serves a single-page frontend (`index.html`) and exposes a JSON API for:
- Scanning a local anime library folder and tracking watch progress
- Syncing watch progress/recommendations with AniList (GraphQL API)
- Searching and downloading VOSTFR (French-subbed) anime torrents via nyaa.si + qBittorrent
- Controlling VLC playback (via VLC's HTTP interface) and auto-saving resume positions

## Running the app

```powershell
python app.py
```

This starts an `http.server`-based server on port 8000 and opens `http://localhost:8000` in the browser. No dependencies beyond the Python standard library are required to run in dev mode.

## Building the Windows executable

```powershell
python build_exe.py
```

This installs PyInstaller if missing and runs it with `AvocadoStream.spec` (one-file build of `app.py`, bundling `index.html`). Output goes to `dist/AvocadoStream.exe`. The `build/` and `dist/` directories are build artifacts.

## Architecture

Everything backend lives in `app.py` (~2300 lines), structured as:

- **Module-level helper functions** (lines ~30-1166): finding VLC/qBittorrent install paths, AniList GraphQL queries (`fetch_anilist_*`), nyaa.si title-matching/filtering logic (`check_title_match`, `is_french_subbed`), config load/save, MAL XML helpers (`add_to_xml`, `myanimelist.xml`), and `get_library()` which scans the configured anime directory and merges local files with AniList progress.
- **`MyHandler(http.server.SimpleHTTPRequestHandler)`** (line 1168+): all HTTP routing happens via long `if/elif` chains on `url.path` inside `do_GET` and `do_POST`. There is no routing framework/middleware — to add an endpoint, add another `elif` branch.
- **`main()`**: starts a daemon thread (`poll_vlc_status`) that polls VLC's local HTTP API every 2s for playback state and writes resume progress to `config.json`, then serves the HTTP server with bind retries (handles Windows TCP TimeWait).

### Key API endpoints (in `app.py`)
- `GET /api/launcher/library` — scans `anime_dir`, returns folders/files/progress/AniList mapping (core logic in `get_library()`)
- `GET /api/torrent/search`, `POST /api/torrent/download[_batch]` — nyaa.si RSS search + qBittorrent download via its Web API
- `GET /api/suggestions`, `POST /api/recommendations/skip` — AniList-based recommendation engine (`get_recommendations_from_anilist`)
- `GET /api/agenda`, `GET /api/anilist/planning` — airing schedule via AniList
- `GET/POST /api/launcher/config` — read/write `config.json`
- `POST /api/launcher/play`, `GET /api/launcher/vlc_status` — launches VLC and reports live playback status
- `POST /api/launcher/map_folder`, `POST /api/launcher/delete_episodes`, `POST /api/add` — folder-to-MAL-ID mapping, episode cleanup, add anime to local MAL XML

### State / persistence
- `config.json` — anime library path, AniList token/credentials, qBittorrent credentials, per-file playback progress, folder-to-MAL-ID mappings, skipped recommendations. **Contains live credentials/tokens — treat as sensitive.**
- `myanimelist.xml` — local MAL-format export used as a fallback progress source when AniList data is unavailable.
- `recommendations_cache.json` — 15-minute cache for AniList recommendations.
- `update_list.py` — contains `SUGGESTIONS`, a static list of (title, MAL ID) pairs used for fuzzy-matching local folder names to AniList/MAL entries when no explicit `folder_mappings` entry exists.

### Frontend
- `index.html` is a single large file (~3300 lines) containing all HTML/CSS/JS for the SPA — tabs for local library, torrent search, recommendations/agenda, etc. It talks to the backend purely via the `/api/*` JSON endpoints above.
- `dashboard.html` is a separate standalone static homepage (AvocadoHub) with links to external services (AniList, comics guides); not served by `app.py`.

### Misc
- `scratch/` and root-level `test_*.py`/`debug_*.py`/`gen_sb3.py` files are ad-hoc debugging/experiment scripts, not part of the app or a test suite — there is no formal test runner configured.
- `guide_setup_pc_gamer.md` is an end-user setup guide (in French) for deploying this app on another PC, not developer documentation.
