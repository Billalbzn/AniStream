import re

def original_match(v, title):
    pattern = r'\b' + re.escape(v.lower()) + r'\b'
    return bool(re.search(pattern, title.lower()))

def proposed_match(v, title):
    # 1. Try original word boundary first
    if original_match(v, title):
        return True
        
    # 2. Try matching with optional grammatical suffixes (ing, s, ed) at the end of the query terms
    # e.g. "render" -> "rendering"
    # We can split the query into words, and build a regex pattern where the last word can have an optional suffix
    words = re.findall(r'\b\w+\b', v.lower())
    if not words:
        return False
        
    # Build regex allowing trailing suffixes on the last word (e.g. render -> rendering, renderers, etc.)
    # and allowing spaces or no spaces between words (e.g. "summer time" -> "summertime" or "summer-time")
    pattern_parts = []
    for idx, w in enumerate(words):
        if idx == len(words) - 1:
            # Last word allows suffixes
            pattern_parts.append(re.escape(w) + r'(?:ing|s|ed|er|ers)?')
        else:
            pattern_parts.append(re.escape(w))
            
    # Join with optional whitespace/punctuation separator
    pattern_str = r'\b' + r'[\s\-_]*'.join(pattern_parts) + r'\b'
    if re.search(pattern_str, title.lower()):
        return True
        
    # 3. Try ignoring all spaces and checking substring, but ensure we don't match partial words like Kaiji vs Kaijin
    # If the query is long enough (e.g., >= 8 chars), normalized substring is very safe.
    # For example, "summertimerender" is 17 chars, so matching "summertimerendering" is extremely safe.
    # But "kaiji" is only 5 chars, so matching "kaijin" is unsafe.
    norm_v = re.sub(r'[^a-z0-9]', '', v.lower())
    norm_title = re.sub(r'[^a-z0-9]', '', title.lower())
    if len(norm_v) >= 7 and norm_v in norm_title:
        return True
        
    return False

# Test Cases
test_cases = [
    # (query, title, expected_match)
    ("Summer Time Render", "[Trix] Summer Time Rendering (COMPLETE) [Optional Dual Audio] [Multi Subs] (BD 1080p AV1) - Summertime Render (Time Shadows) - VOSTFR", True),
    ("Summer Time Render", "Summer Time Rendering - 01 ~ 25 VOSTFR / FRENCH [BD 1080p x265 10bits] -EDCPM (Time Shadows)", True),
    ("Summer Time Render", "[Pikari-Teshima] Summertime Rendering (Time Shadows) BATCH VOSTFR [Web-Rip 1080p 10bits AAC", True),
    ("Kaiji", "[Tsundere-Raws] Kaijin Kaihatsubu no Kuroitsu-san - 01 VOSTFR", False),
    ("Kaiji", "Kaiji S02 VOSTFR 1080p WEB x264 AAC -Tsundere-Raws (ADN)", True),
    ("Kaiji", "Kaiji.S01.VOSTFR.480p.WEBRip.x264-NoTag", True),
    ("Fairy Tail", "[Tsundere-Raws] Fairy Tail S1 VOSTFR", True)
]

print("Running tests:")
for q, t, expected in test_cases:
    orig = original_match(q, t)
    prop = proposed_match(q, t)
    print(f"Query: {q:<20} | Title: {t[:40]:<40} | Expected: {expected} | Orig: {orig:<5} | Prop: {prop:<5} | {'PASS' if prop == expected else 'FAIL'}")
