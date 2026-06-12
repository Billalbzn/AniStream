import subprocess
import sys
import os

def check_and_install_pyinstaller():
    try:
        import PyInstaller
        print("[Build] PyInstaller est déjà installé.")
    except ImportError:
        print("[Build] PyInstaller non trouvé. Installation automatique...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
            print("[Build] PyInstaller installé avec succès.")
        except Exception as e:
            print(f"[Build] Erreur lors de l'installation de PyInstaller: {e}")
            sys.exit(1)

def run_build():
    print("[Build] Commencement de la compilation de AvocadoStream.exe...")
    
    # Define files and options
    script_name = "app.py"
    exe_name = "AvocadoStream"
    
    # We add index.html as a resource. The format is: source_path;dest_dir (Windows)
    add_data_option = "index.html;."
    
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--onefile",
        f"--add-data={add_data_option}",
        f"--name={exe_name}",
        "--console",  # Console is active so the user can easily close it to stop the server
        script_name
    ]
    
    print(f"[Build] Exécution de la commande : {' '.join(cmd)}")
    try:
        # Run PyInstaller
        subprocess.check_call(cmd)
        print("\n=============================================")
        print(" Compilation Terminée avec Succès ! ")
        print(f" Votre exécutable est disponible dans le dossier : {os.path.join(os.getcwd(), 'dist', 'AvocadoStream.exe')}")
        print("=============================================\n")
    except Exception as e:
        print(f"[Build] Erreur lors de la compilation : {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_and_install_pyinstaller()
    run_build()
