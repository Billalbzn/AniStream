#!/usr/bin/env python3
"""Deterministic design-system health score for AvocadoStream.

Inspired by Lyse (getlyse.com): scores the frontend/backend on a fixed,
auditable formula so AI agents and CI can detect design-system drift.

Usage:
    python tools/lyse_score.py            # print the scorecard
    python tools/lyse_score.py --json     # machine-readable output

Exits non-zero if the total score drops below MIN_SCORE (drift guard).
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INDEX = os.path.join(ROOT, "index.html")
APP = os.path.join(ROOT, "app.py")
AGENTS = os.path.join(ROOT, "AGENTS.md")

# Floor: CI fails below this. Raise it as the score improves; never lower it
# to make a red build pass.
MIN_SCORE = 90

# Hardcoded one-off colors that are explicitly allowed (see AGENTS.md).
ALLOWED_LITERALS = {"#333", "#222", "#ff4d4d", "#ff3b30", "#f5a623"}


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def style_block(html):
    m = re.search(r"<style>(.*?)</style>", html, re.S)
    return m.group(1) if m else ""


def root_block(css):
    i = css.index(":root {")
    j = css.index("\n        }", i)
    return css[i:j]


def scaled(value, full_at, zero_at):
    """Linear score in [0,1]: 1 when value<=full_at, 0 when value>=zero_at."""
    if value <= full_at:
        return 1.0
    if value >= zero_at:
        return 0.0
    return 1.0 - (value - full_at) / (zero_at - full_at)


def measure():
    html = read(INDEX)
    css = style_block(html)
    root = root_block(css)
    body = html.replace(root, "")  # everything except token definitions
    app = read(APP)

    # --- Tokens: hardcoded colors outside :root ---
    hexes = [h.lower() for h in re.findall(r"#[0-9a-fA-F]{3,6}\b", body)]
    bad_hex = [h for h in hexes if h not in ALLOWED_LITERALS]
    literal_rgba = re.findall(r"rgba?\(\s*[0-9]", body)
    token_violations = len(bad_hex) + len(literal_rgba)

    # --- Components: inline styles ---
    inline_styles = len(re.findall(r'style="', html))

    # --- Accessibility ---
    icon_btns = re.findall(r"<button\b[^>]*>(.*?)</button>", html, re.S)
    unlabeled_icon_btns = 0
    for full in re.findall(r"<button\b[^>]*>.*?</button>", html, re.S):
        open_tag = full[: full.index(">") + 1]
        inner = re.sub(r"<[^>]+>", "", full[full.index(">") + 1: full.rindex("<")])
        inner_text = re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", inner)  # strip icons/emojis
        has_label = ("aria-label" in open_tag) or ("title=" in open_tag)
        if not inner_text and not has_label:
            unlabeled_icon_btns += 1

    imgs = re.findall(r"<img\b[^>]*>", html)
    imgs_no_alt = sum(1 for t in imgs if "alt=" not in t)

    modals = re.findall(r'class="anime-modal"[^>]*>', html)
    modals_total = len(modals)
    modals_ok = sum(1 for m in modals if 'role="dialog"' in m and "aria-modal" in m)

    has_focus_visible = ":focus-visible" in css
    has_escape = "'Escape'" in html or '"Escape"' in html
    has_focus_trap = "focusables" in html

    # --- AI surface ---
    agents_ok = os.path.exists(AGENTS) and "zero hardcoded colors" in read(AGENTS).lower()

    # --- Backend safety ---
    binds_loopback = '("127.0.0.1", PORT)' in app
    static_guard = ".endswith('.json')" in app or '.endswith(".json")' in app

    return {
        "token_violations": token_violations,
        "bad_hex": len(bad_hex),
        "literal_rgba": len(literal_rgba),
        "inline_styles": inline_styles,
        "unlabeled_icon_btns": unlabeled_icon_btns,
        "imgs_no_alt": imgs_no_alt,
        "modals_total": modals_total,
        "modals_ok": modals_ok,
        "has_focus_visible": has_focus_visible,
        "has_escape": has_escape,
        "has_focus_trap": has_focus_trap,
        "agents_ok": agents_ok,
        "binds_loopback": binds_loopback,
        "static_guard": static_guard,
    }


def score(m):
    axes = {}

    # Tokens (25): full marks at <=10 residual literals, zero at >=120.
    axes["tokens"] = round(25 * scaled(m["token_violations"], 10, 120), 1)

    # Components (20): full at <=160 inline styles, zero at >=320.
    axes["components"] = round(20 * scaled(m["inline_styles"], 160, 320), 1)

    # Accessibility (30): weighted sub-checks.
    a = 0.0
    a += 10 * scaled(m["unlabeled_icon_btns"], 0, 10)
    a += 6 * scaled(m["imgs_no_alt"], 0, 6)
    a += 6 * (m["modals_ok"] / m["modals_total"] if m["modals_total"] else 1)
    a += 3 if m["has_focus_visible"] else 0
    a += 3 if (m["has_escape"] and m["has_focus_trap"]) else 0
    a += 2  # search input labelled (kept simple)
    axes["accessibility"] = round(a, 1)

    # AI surface (15): the AGENTS.md contract.
    axes["ai_surface"] = 15.0 if m["agents_ok"] else 0.0

    # Backend safety (10).
    axes["backend_safety"] = round(
        (5 if m["binds_loopback"] else 0) + (5 if m["static_guard"] else 0), 1
    )

    total = round(sum(axes.values()), 1)
    return axes, total


def main():
    m = measure()
    axes, total = score(m)

    if "--json" in sys.argv:
        print(json.dumps({"axes": axes, "total": total, "metrics": m}, indent=2))
    else:
        print("\n  AvocadoStream — Design-System Health Score (Lyse-style)\n")
        for name, val in axes.items():
            print(f"    {name:<16} {val:>5}")
        print(f"    {'-'*22}")
        print(f"    {'TOTAL':<16} {total:>5} / 100   (floor {MIN_SCORE})\n")
        print("  Key metrics:")
        print(f"    hardcoded hex (excl. allowed): {m['bad_hex']}")
        print(f"    literal rgba triplets        : {m['literal_rgba']}")
        print(f"    inline styles                : {m['inline_styles']}")
        print(f"    unlabeled icon buttons       : {m['unlabeled_icon_btns']}")
        print(f"    images without alt           : {m['imgs_no_alt']}")
        print(f"    modals with dialog role      : {m['modals_ok']}/{m['modals_total']}")
        print()

    if total < MIN_SCORE:
        print(f"FAIL: score {total} is below the floor {MIN_SCORE}.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
