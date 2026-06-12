import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

def test_search(query):
    print(f"Searching for: {query}")
    url_q = urllib.parse.urlencode({
        "page": "rss",
        "q": query
    })
    nyaa_url = f"https://nyaa.si/?{url_q}"
    req = urllib.request.Request(nyaa_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            xml_data = response.read()
        root = ET.fromstring(xml_data)
        items = root.findall('.//item')
        print(f"Found {len(items)} items in feed.")
        for item in items[:10]:
            title = item.find('title').text
            print(f"- {title}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_search("Summer Time Render VOSTFR")
