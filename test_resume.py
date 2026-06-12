"""Test script to verify VLC resume flow works end-to-end."""
import json
import os
import urllib.request
import time

CONFIG_PATH = 'config.json'

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# Step 1: Check if VLC HTTP interface is reachable
print("=" * 50)
print("TEST 1: VLC HTTP Interface")
print("=" * 50)

url = 'http://localhost:8080/requests/status.json'
req = urllib.request.Request(url)
req.add_header('Authorization', 'Basic OmF2b2NhZG8=')

try:
    with urllib.request.urlopen(req, timeout=2) as response:
        data = json.loads(response.read().decode('utf-8'))
        state = data.get('state', 'unknown')
        vlc_time = data.get('time', 0)
        vlc_length = data.get('length', 0)
        print(f"  VLC State: {state}")
        print(f"  Current Time: {vlc_time}s")
        print(f"  Total Length: {vlc_length}s")
        if vlc_length > 0:
            remaining = vlc_length - vlc_time
            percent = (vlc_time / vlc_length) * 100
            print(f"  Remaining: {remaining}s ({remaining/60:.1f} min)")
            print(f"  Percent: {percent:.1f}%")
        print("  [OK] VLC HTTP interface is accessible!")
except Exception as e:
    print(f"  [FAIL] Cannot reach VLC HTTP interface: {e}")
    print("  -> VLC might not be running, or not launched with --extraintf=http --http-password=avocado")

# Step 2: Check config.json progress data
print()
print("=" * 50)
print("TEST 2: Config.json Progress Data")
print("=" * 50)

config = load_config()
progress = config.get("progress", {})

if not progress:
    print("  [WARN] No progress data found in config.json!")
    print("  -> The VLC poller has never saved any progress.")
    print("  -> Make sure you're running app.py (not just opening VLC manually)")
else:
    print(f"  Found {len(progress)} tracked files:")
    for path, info in progress.items():
        if isinstance(info, dict):
            t = info.get('time', 0)
            l = info.get('length', 0)
            p = info.get('percent', 0)
            print(f"  - {os.path.basename(path)}")
            print(f"    Time: {t}s, Length: {l}s, Percent: {p:.1f}%")
        else:
            print(f"  - {path}: {info} (NOT a dict - corrupted data)")

# Step 3: Check if AvocadoStream server is running  
print()
print("=" * 50)
print("TEST 3: AvocadoStream Server")
print("=" * 50)

try:
    with urllib.request.urlopen('http://localhost:8000/api/launcher/vlc_status', timeout=2) as response:
        status = json.loads(response.read().decode('utf-8'))
        print(f"  Server is running!")
        print(f"  VLC status from server: {json.dumps(status, indent=4)}")
except Exception as e:
    print(f"  [FAIL] Server not running: {e}")
    print("  -> Launch AvocadoStream.exe or run app.py first")
