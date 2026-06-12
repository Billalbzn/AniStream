import urllib.request
import json

try:
    url = "http://localhost:8000/api/torrent/search?query=Summer+Time+Render"
    with urllib.request.urlopen(url, timeout=5) as response:
        content = response.read().decode('utf-8')
        data = json.loads(content)
        print(f"Success! Found {len(data)} items:")
        for item in data[:3]:
            print(f"- {item['title']} (Seeders: {item['seeders']})")
except Exception as e:
    print(f"Error querying server: {e}")
