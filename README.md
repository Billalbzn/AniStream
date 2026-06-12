# AvocadoStream 🥑

Serveur/lanceur d'animés local et personnel. Scanne ta bibliothèque d'animés,
suit ta progression (avec sync AniList optionnelle), lance les épisodes dans
VLC (avec reprise automatique), et recherche des torrents VOSTFR (nyaa.si +
flux AnimeVost).

> ⚠️ Application **mono-utilisateur, en local uniquement** (pas d'authentification).
> Ne l'expose pas sur Internet.

---

## 🚀 Démarrage rapide

### Option A — Exécutable Windows (le plus simple)

1. Télécharge/clone le repo.
2. Va dans le dossier `dist/` et lance `AvocadoStream.exe`.
   *(Si le dossier `dist/` n'existe pas, voir Option B pour le générer, ou
   utilise directement Python.)*
3. Ton navigateur s'ouvre automatiquement sur `http://localhost:8000`.

### Option B — Avec Python (mode dev)

1. Installe Python 3.12+ :
   ```powershell
   winget install Python.Python.3.12
   ```
2. Clone le repo, puis dans le dossier du projet :
   ```powershell
   python app.py
   ```
3. Ton navigateur s'ouvre automatiquement sur `http://localhost:8000`.

### (Optionnel) Générer l'exécutable toi-même

```powershell
python build_exe.py
```
Ça installe PyInstaller si besoin et génère `dist/AvocadoStream.exe`.

---

## 🎬 Pré-requis : VLC Media Player

VLC est utilisé pour lire les épisodes et sauvegarder automatiquement la
progression de lecture.

```powershell
winget install VideoLAN.VLC
```

L'app détecte automatiquement VLC s'il est installé dans
`Program Files\VideoLAN\VLC\` ou disponible dans le PATH.

---

## ⚙️ Configuration

Au premier lancement, l'app crée/utilise un fichier `config.json` (non
inclus dans le repo, généré localement — voir `config.example.json` pour la
structure).

1. Crée un dossier pour tes animés (ex: `C:\Anime`), avec un sous-dossier par
   série (ex: `C:\Anime\OnePiece\`, `C:\Anime\Naruto\`) contenant les fichiers
   vidéo (`.mkv`, `.mp4`, `.avi`, `.mov`).
2. Dans l'app, onglet **Ma Bibliothèque Locale** → bouton **⚙️ Configurer** →
   indique le chemin de ce dossier (ex: `C:\Anime`) → **Enregistrer**.

### Sync AniList (optionnel)

Pour suivre/mettre à jour automatiquement ta progression sur AniList :

1. Crée une "API Client" sur [AniList Developer Settings](https://anilist.co/settings/developer).
2. Renseigne ton **Client ID** et ton **token** dans la fenêtre de
   configuration de l'app (⚙️ Configurer).

Sans token, l'app fonctionne quand même en local — elle utilise
`myanimelist.xml` comme fallback pour la progression (fichier vide/absent au
premier lancement).

### Téléchargement de torrents via qBittorrent (optionnel)

1. Installe [qBittorrent](https://www.qbittorrent.org/) et active son
   **Web UI** (Outils > Options > Web UI).
2. Dans la fenêtre de configuration de l'app, active **qBittorrent** et
   renseigne l'hôte/identifiants du Web UI.

Sans qBittorrent activé, les torrents trouvés s'ouvrent via l'application
torrent par défaut de Windows (`.torrent` / magnet).

---

## 🧩 Fonctionnalités principales

- **Bibliothèque locale** : scan automatique, reprise de lecture, prochaine
  épisode suggéré
- **Recherche torrent VOSTFR** : nyaa.si + flux AnimeVost (Tsundere-Raws),
  avec badges de source et filtrage Kaï
- **Recommandations & Agenda** : suggestions et planning basés sur AniList
- **Lecture VLC intégrée** : lancement automatique, playlist des épisodes
  suivants, sauvegarde de la position

---

## 🔒 Confidentialité

`config.json`, `myanimelist.xml` et `recommendations_cache.json` sont
ignorés par git (`.gitignore`) car ils contiennent tes données et identifiants
personnels (token AniList, identifiants qBittorrent, progression). Chacun
génère ses propres fichiers localement au premier lancement.
