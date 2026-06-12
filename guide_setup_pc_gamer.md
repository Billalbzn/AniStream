# Guide de Configuration : PC Gamer (Ryzen 7 5800X + RX 7800 XT)

Ce guide récapitule toutes les étapes simples à effectuer sur votre tour de jeu pour y transférer et exécuter votre environnement d'animes et de comics.

---

## 📋 Étape 1 : Transférer le dossier de projet
Puisque toute votre configuration, votre historique de tri de 182 animés et vos fichiers de codes sont dans le dossier actuel :
1. Sur votre PC portable, compressez le dossier **`projet_test`** (Clic droit > *Envoyer vers > Dossier compressé* ou créez un fichier `.zip`).
2. Transférez ce fichier `.zip` sur votre PC fixe (via clé USB, Discord, Google Drive, local share, etc.).
3. Décompressez-le à l'emplacement de votre choix sur votre PC fixe (par exemple dans `Documents\projet_test`).

---

## 🎬 Étape 2 : Installer VLC Media Player (Indispensable)
VLC est le lecteur principal utilisé par l'application pour gérer la lecture et sauvegarder automatiquement votre temps restant de visionnage.
1. Ouvrez un terminal **PowerShell** (en recherchant `PowerShell` dans le menu Démarrer).
2. Lancez l'installation :
   ```powershell
   winget install VideoLAN.VLC
   ```

---

## 📂 Étape 3 : Créer et configurer votre dossier Anime
1. Créez un dossier dédié à vos animes sur le disque de votre choix (ex: `C:\Anime` ou `D:\Anime`).
2. À l'intérieur, créez des sous-dossiers pour chaque série (ex: `C:\Anime\gintama\`, `C:\Anime\fairytail\`).
3. Glissez-y vos épisodes (fichiers vidéo `.mkv`, `.mp4`, etc.).

---

## 🚀 Étape 4 : Lancer AvocadoStream
Vous avez deux options pour lancer l'application sur votre PC fixe :

### Option A : Utiliser l'exécutable direct (Recommandé & Plus simple)
1. Ouvrez le dossier `projet_test` transféré sur votre PC fixe.
2. Allez dans le sous-dossier **`dist`** et double-cliquez sur **`AvocadoStream.exe`**.
3. **C'est tout !** Aucun prérequis ou installation de Python n'est nécessaire avec cette méthode.

### Option B : Exécuter avec Python (Mode de développement)
1. Dans votre terminal PowerShell, installez Python :
   ```powershell
   winget install Python.Python.3.12
   ```
2. Fermez et rouvrez votre terminal.
3. Placez-vous dans votre dossier de projet et lancez le serveur :
   ```powershell
   python app.py
   ```
   *(Ou `py app.py` selon votre configuration).*

---

## ⚙️ Étape 5 : Configurer le dossier Anime dans l'application
1. Une fois l'application ouverte dans votre navigateur web (`http://localhost:8000`), allez dans l'onglet **Ma Bibliothèque Locale**.
2. Cliquez sur le bouton **⚙️ Configurer** en haut à droite.
3. Entrez le chemin du dossier d'animes que vous avez créé à l'Étape 3 (ex: `C:\Anime`) et cliquez sur **Enregistrer**.

---

## 🐯 Étape 6 : Installer et configurer Taiga (Suivi auto AniList)
Pour que le visionnage de vos épisodes mette à jour automatiquement votre compte AniList :
1. Dans votre PowerShell, lancez l'installation :
   ```powershell
   winget install -e --id erengy.Taiga
   ```
2. Ouvrez Taiga (installé par défaut dans `%appdata%\Taiga\Taiga.exe`).
3. Connectez votre compte AniList (`AvocadoDeska`) dans **Settings > Services > AniList > Authorize**.
4. Dans **Settings > Media Players**, cochez **VLC Media Player**.
5. Laissez Taiga tourner en arrière-plan (il se réduit dans votre barre des tâches près de l'horloge).

---

## 🔒 Étape 7 : Sécurité & Mots de passe (Bitwarden)
1. Allez sur [bitwarden.com](https://bitwarden.com) et créez votre compte gratuit.
2. Installez l'extension pour votre navigateur internet.
3. Enregistrez et synchronisez vos identifiants pour les retrouver automatiquement sur votre PC fixe.

---

## 🧭 Étape 8 : Utiliser le Tableau de bord (AvocadoHub)
1. Double-cliquez sur le fichier `dashboard.html` situé dans le dossier de projet.
2. Définissez cette page comme **page d'accueil par défaut** dans les paramètres de votre navigateur web.
3. Vous y retrouverez vos accès directs à votre profil AniList, vos guides d'ordre de lecture de comics (comme *Superboy-Prime* ou *Crisis on Infinite Earths*), et vos applications locales !
