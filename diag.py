import urllib.request, json, subprocess

# Check AvocadoStream server status
try:
    with urllib.request.urlopen('http://localhost:8000/api/launcher/vlc_status', timeout=2) as r:
        data = json.loads(r.read().decode('utf-8'))
        print('=== AvocadoStream Server ===')
        print(json.dumps(data, indent=2))
except Exception as e:
    print(f'Server not reachable: {e}')

# Check VLC on port 4212 (new port)
print()
print('=== VLC Port 4212 (new) ===')
req = urllib.request.Request('http://localhost:4212/requests/status.json')
req.add_header('Authorization', 'Basic OmF2b2NhZG8=')
try:
    with urllib.request.urlopen(req, timeout=2) as r:
        data = json.loads(r.read().decode('utf-8'))
        state = data.get('state')
        t = data.get('time')
        l = data.get('length')
        print(f'State: {state}')
        print(f'Time: {t}s / Length: {l}s')
except Exception as e:
    print(f'FAIL: {e}')

# Check VLC on port 8080 (old port)
print()
print('=== VLC Port 8080 (old) ===')
req2 = urllib.request.Request('http://localhost:8080/requests/status.json')
req2.add_header('Authorization', 'Basic OmF2b2NhZG8=')
try:
    with urllib.request.urlopen(req2, timeout=2) as r:
        data = json.loads(r.read().decode('utf-8'))
        state = data.get('state')
        t = data.get('time')
        l = data.get('length')
        print(f'State: {state}')
        print(f'Time: {t}s / Length: {l}s')
except Exception as e:
    print(f'FAIL: {e}')

# Check VLC process
print()
print('=== VLC Process ===')
result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq vlc.exe'], capture_output=True, text=True)
print(result.stdout.strip())

# Check AvocadoStream process
print()
print('=== AvocadoStream Process ===')
result2 = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq AvocadoStream.exe'], capture_output=True, text=True)
print(result2.stdout.strip())

# Check config.json
print()
print('=== config.json ===')
try:
    with open('config.json', 'r') as f:
        cfg = json.load(f)
    print(json.dumps(cfg, indent=2))
except Exception as e:
    print(f'Error: {e}')
