# AGENTS.md — Design & code contract for AI agents

This file is the **contract any AI agent (Claude Code, Cursor, Codex, …) must
follow before editing this repository.** It exists to stop design-system drift:
agents tend to invent ad-hoc colors, duplicate markup, and skip accessibility.
Read this first; it complements `CLAUDE.md` (which describes the architecture).

The project is a single-user, local anime media server: a Python stdlib HTTP
server (`app.py`) serving one single-page frontend (`index.html`).

---

## 1. Design tokens — **zero hardcoded colors**

All colors live as CSS custom properties in the `:root` block at the top of
`index.html`. **Never introduce a raw hex (`#abc`) or numeric `rgb()/rgba()`
color in new code.** Use a token. If a shade genuinely doesn't exist, add a
token to `:root` first, then reference it.

### Color tokens
| Token | Use |
|---|---|
| `--bg-color`, `--bg-secondary`, `--card-bg` | page / section / card backgrounds |
| `--surface-1`, `--surface-2`, `--surface-modal` | raised panels, shimmer, modal bg |
| `--accent-red`, `--accent-red-hover`, `--accent-red-soft` | primary brand / CTAs |
| `--accent-green`, `--accent-green-hover` | success / "completed" |
| `--accent-blue`, `--accent-blue-soft` | info / secondary |
| `--accent-gold` | ratings |
| `--white`, `--black` | pure white / black |
| `--text-color`, `--text-bright`, `--text-muted` | body / emphasized / secondary text |

### Alpha (translucent) colors — use the RGB-triplet tokens
For any translucent color, compose with a `*-rgb` triplet token:
```css
background: rgba(var(--accent-red-rgb), 0.15);   /* ✅ */
background: rgba(229, 9, 20, 0.15);               /* ❌ never */
```
Available triplets: `--accent-red-rgb`, `--accent-green-rgb`,
`--accent-blue-rgb`, `--white-rgb`, `--black-rgb`, `--bg-rgb`, `--grey-rgb`.

### Other tokens
Radii: `--radius-sm|md|lg`. Motion: `--transition-smooth`. Shadows:
`--shadow-card`, `--shadow-card-hover`. Focus: `--focus-ring`.

**Known exceptions** (allowed literals, do not "fix"): a handful of one-off
decorative values remain (`#333` scrollbar, `#222`, `#ff4d4d`, `#ff3b30`,
`#f5a623`, and a few one-off dark greys / the ambient-glow `rgba(100,0,0,…)`).
Don't add new ones.

---

## 2. Components over inline styles

Prefer a CSS class to a repeated `style="..."`. If you write the same inline
style **twice**, extract a class instead. Reusable classes already exist:
`.modal-sep`, `.form-section-title`, `.hint`, `.field-hint`, `.btn-action`,
`.btn-hero`, `.btn-suggest`, `.poster-card`, `.card-badge`, `.source-badge`.

One-off positioning (`style="display:none"`, absolute offsets toggled by JS)
may stay inline — **do not** convert JS-toggled `style.display` to a class, the
scripts read/write it directly.

---

## 3. Accessibility checklist (required for any UI change)

- **Icon-only buttons** need `aria-label` (text-bearing buttons don't).
- **Images**: meaningful `alt` (the title), or `alt=""` if decorative with
  adjacent text.
- **Modals**: `role="dialog"` + `aria-modal="true"` + an `aria-label`. The
  global modal layer (search `MODAL_OVERLAY_IDS` in `index.html`) already gives
  Escape-to-close, a Tab focus-trap, and focus move/restore — **register any new
  modal there** (add its overlay id + a closer).
- **Focus**: never remove the `:focus-visible` ring; rely on `--focus-ring`.
- **Inputs**: a `placeholder` is not a label — add `aria-label`.

---

## 4. Backend safety (`app.py`)

- The server **must bind to `127.0.0.1` only** — it exposes credentials and
  local file access. Never change the bind back to `("", PORT)` / `0.0.0.0`.
- `config.json` holds live secrets (AniList token, qBittorrent password). The
  `do_GET` static fallback **blocks** `*.json`, `*.xml`, `*.py`, `*.log` — keep
  that guard when touching routing.
- Routing is a manual `if/elif` chain on `url.path`; add endpoints there.

---

## 5. Run, test, score

```bash
python app.py                 # serves http://localhost:8000 (loopback only)
python tools/lyse_score.py     # deterministic design-system health score /100
```
Before committing a UI change, run `lyse_score.py` — **the score must not go
down.** CI runs it on every PR (`.github/workflows/lyse.yml`).

There is no formal test suite; `scratch/` and root `test_*.py` are ad-hoc and
git-ignored. Verify UI changes by running the app and looking at it.

---

## 6. Naming & conventions

- CSS classes: kebab-case, BEM-ish (`poster-card`, `source-badge--nyaa`).
- User-facing text is **French**; code identifiers/comments are English.
- Keep `index.html` self-contained (no build step, no external CSS/JS bundler).
