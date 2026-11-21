#!/usr/bin/env python3
"""
Judy's Cookbook — Site Builder
================================
Generates index.html from either the iCloud recipe files or the Notion database.

Usage:
    python3 build.py                  # reads from iCloud files (default)
    python3 build.py --source notion  # reads from Notion database

── Notion source ──────────────────────────────────────────────────────────────
Requires a NOTION_TOKEN environment variable (an internal integration token).

Setup (one-time):
  1. Go to https://www.notion.so/my-integrations → New integration → copy token
  2. In Notion, open Family Cookbook → Share → Connect to → your integration
  3. export NOTION_TOKEN=secret_xxxx   (add to ~/.zshrc to make permanent)

Then run:
    python3 build.py --source notion
    git add index.html && git commit -m "update from Notion" && git push

── File source (original workflow) ────────────────────────────────────────────
  1. Judy edits recipes in iCloud
  2. python3 build.py
  3. git add index.html && git commit -m "update recipes" && git push

Note: file source requires macOS (uses textutil for .doc files).
"""

import argparse, os, json, re, subprocess

_ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_ENV_FILE):
    with open(_ENV_FILE) as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

NOTION_DB_ID = "324eef28a6748022b6c1e63b297bd8f5"
NOTION_OPTIONS = {}  # select options from the Notion schema, filled by load_from_notion()

RECIPES_DIR     = os.path.join(os.path.dirname(__file__), "recipes")
RECIPES_NEW_DIR = os.path.join(os.path.dirname(__file__), "recipes_new")
OUTPUT_FILE     = os.path.join(os.path.dirname(__file__), "index.html")

CATEGORY_ICONS = {
    "Appetizers": "🫒",
    "Chicken": "🍗",
    "Cookies & Cakes": "🍰",
    "Fish": "🐟",
    "Meat": "🥩",
    "Muffins & Breads": "🍞",
    "Passover": "✡️",
    "Potatoes & Pasta": "🥔",
    "Salads & Vegetables": "🥗",
    "Soups & Stews": "🍲",
    "Special": "⭐",
}
CATEGORY_DESCRIPTIONS = {
    "Appetizers": "Starters & small bites",
    "Chicken": "Roasts, curries & more",
    "Cookies & Cakes": "Sweets & baked treats",
    "Fish": "Salmon, tuna & seafood",
    "Meat": "Briskets, chicken & mains",
    "Muffins & Breads": "Loaves, challah & muffins",
    "Passover": "Holiday recipes & traditions",
    "Potatoes & Pasta": "Kugel, pasta & sides",
    "Salads & Vegetables": "Fresh sides & salads",
    "Soups & Stews": "Warming bowls & broth",
    "Special": "Judy's signature recipes",
}

CATEGORY_ORDER = [
    "Appetizers", "Chicken", "Fish", "Meat", "Soups & Stews",
    "Salads & Vegetables", "Potatoes & Pasta", "Muffins & Breads",
    "Cookies & Cakes", "Passover", "Special",
]


SKIP_FILES = {
    "Cover Sheet", "Doc1", "Labels - Cookbook", "Label for Spices",
    "Label for Spices 2", "Side tabs", "Spices - Aaron", "Spices - Another",
    "Spices - Camila", "Spices - Camila 1", "Spices - Camila 2", "Buttercup Icing",
}


RECIPE_EXTENSIONS = {".doc", ".docx", ".odt", ".rtf"}


def empty_recipe(name):
    """Return a blank recipe dict with all expected keys."""
    return {
        "title": name,
        "cuisine": None,       # "Sephardi" or "Ashkenazi" → drives page theme
        "from": None,
        "prep_time": None,
        "cook_time": None,
        "yields": None,
        "kashrut": None,
        "description": None,
        "ingredients": [],
        "steps": [],
        "notes": [],
        # Legacy fields kept for old-format recipes
        "meta": [],
    }


def parse_docx_structured(name, path):
    """
    Parse a .docx file written using the new recipe template.
    Expected structure (by paragraph style):
      Title           → recipe title
      normal          → metadata lines before first Heading 1:
                        "Cuisine: Sephardi"
                        "From: Grandma's Kitchen"
                        "Prep Time: ...\nCook Time: ...\nYields: ...\nKashrut: ..."
      Heading 1       → section name: Description / Ingredients /
                        Preparation Steps / Chef's Notes
      normal (after)  → section content
    """
    from docx import Document
    r = empty_recipe(name)
    doc = Document(path)
    current_section = None

    for para in doc.paragraphs:
        style = para.style.name
        text = para.text.strip()

        if style == "Title":
            if text:
                r["title"] = text
            continue

        if style == "Heading 1":
            current_section = text.lower()
            continue

        if not text:
            continue

        if current_section is None:
            # Metadata block — lines before the first heading
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.lower().startswith("cuisine:"):
                    r["cuisine"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("from:"):
                    r["from"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("prep time:"):
                    r["prep_time"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("cook time:"):
                    r["cook_time"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("yields:"):
                    r["yields"] = line.split(":", 1)[1].strip()
                elif line.lower().startswith("kashrut:"):
                    r["kashrut"] = line.split(":", 1)[1].strip()

        elif "description" in current_section:
            r["description"] = ((r["description"] or "") + " " + text).strip()

        elif "ingredient" in current_section:
            r["ingredients"].append(text)

        elif "preparation" in current_section or "step" in current_section:
            r["steps"].append(text)

        elif "note" in current_section or "chef" in current_section:
            r["notes"].append(text)

    return r


def extract_meta_fields(line, r):
    """
    Parse a single metadata line from a legacy .doc file into known fields.
    Old docs often cram multiple fields onto one line with tab separation, e.g.:
      "From: Grandma's Kitchen          Number of servings: 6-8"
      "From Leslie's Kitchen            Prep. Time: 1½ hr    Yield: 48+"
    We split on two-or-more spaces (tab boundaries) and try each chunk.
    """
    # Split on 2+ consecutive spaces (tab-separated fields in the original doc)
    chunks = [c.strip() for c in re.split(r' {2,}|\t', line) if c.strip()]
    for chunk in chunks:
        cl = chunk.lower()
        if cl.startswith("from"):
            val = re.split(r"from[:\s]+", chunk, flags=re.I, maxsplit=1)[-1].strip()
            if val and not r["from"]:
                r["from"] = val
        elif re.search(r"prep(?:aration)?\.?\s*time", cl):
            val = re.split(r"prep(?:aration)?\.?\s*time[:\s]+", chunk, flags=re.I, maxsplit=1)[-1].strip()
            if val and not r["prep_time"]:
                r["prep_time"] = val
        elif re.search(r"cook\.?\s*time", cl):
            val = re.split(r"cook\.?\s*time[:\s]+", chunk, flags=re.I, maxsplit=1)[-1].strip()
            if val and not r["cook_time"]:
                r["cook_time"] = val
        elif re.search(r"yield|serves|servings|number of", cl):
            val = re.split(r"(yields?|serves?|servings?|number of\s+servings?)[:\s]*", chunk, flags=re.I, maxsplit=1)[-1].strip()
            if val and not r["yields"]:
                r["yields"] = val
        else:
            r["meta"].append(chunk)


def read_and_parse_legacy(name, path):
    """
    For old .doc/.odt/.rtf files: convert to plain text via textutil,
    then extract what we can into the standard recipe dict shape.
    """
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", path],
        capture_output=True, text=True
    )
    text = result.stdout.strip()
    if not text:
        return None

    r = empty_recipe(name)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    ing_idx = inst_idx = None
    for i, l in enumerate(lines):
        if re.match(r"^INGREDIENTS?\s*$", l, re.I):
            ing_idx = i
        if re.match(r"^INSTRUCTIONS?\s*$|^DIRECTIONS?\s*$|^METHOD\s*$|^PREPARATION\s*$", l, re.I):
            inst_idx = i

    meta_end = ing_idx if ing_idx is not None else (inst_idx if inst_idx is not None else len(lines))
    for l in lines[1:meta_end]:
        if l.lower() == name.lower(): continue
        if len(l) > 150: continue
        # Try to pick out known fields
        ll = l.lower()
        extract_meta_fields(l, r)

    if ing_idx is not None:
        end = inst_idx if inst_idx is not None else len(lines)
        for l in lines[ing_idx + 1:end]:
            if l and len(l) < 200:
                r["ingredients"].append(l)

    if inst_idx is not None:
        current = []
        for l in lines[inst_idx + 1:]:
            if l:
                current.append(l)
            else:
                if current:
                    r["steps"].append(" ".join(current))
                    current = []
        if current:
            r["steps"].append(" ".join(current))

    return r


def load_cookbook():
    cookbook = {}
    available = [d for d in os.listdir(RECIPES_DIR)
                 if os.path.isdir(os.path.join(RECIPES_DIR, d))
                 and not d.startswith(".")]
    ordered = [c for c in CATEGORY_ORDER if c in available]
    ordered += sorted([c for c in available if c not in CATEGORY_ORDER])

    for cat in ordered:
        cat_path = os.path.join(RECIPES_DIR, cat)
        new_cat_path = os.path.join(RECIPES_NEW_DIR, cat)

        # Index any staged .docx files in recipes_new for this category
        staged = {}
        if os.path.isdir(new_cat_path):
            for f in os.listdir(new_cat_path):
                if f.lower().endswith(".docx"):
                    staged[os.path.splitext(f)[0]] = os.path.join(new_cat_path, f)

        seen = set()
        recipes = []
        for fname in sorted(os.listdir(cat_path)):
            root, ext = os.path.splitext(fname)
            if ext.lower() not in RECIPE_EXTENSIONS:
                continue
            if root in SKIP_FILES:
                continue
            if root in seen:
                continue
            seen.add(root)

            fpath = os.path.join(cat_path, fname)
            if ext.lower() == ".docx":
                # iCloud already has a hand-edited .docx — use it
                recipe = parse_docx_structured(root, fpath)
            elif root in staged:
                # Generated template in recipes_new — use that over legacy .doc
                recipe = parse_docx_structured(root, staged[root])
            else:
                recipe = read_and_parse_legacy(root, fpath)

            if recipe:
                recipes.append(recipe)
        if recipes:
            cookbook[cat] = recipes

    return cookbook


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Judy's Kitchen — A Family Cookbook</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,400;0,600;0,700;1,400&family=Lato:wght@300;400;700&display=swap" rel="stylesheet">
<style>
:root {
  --cream: #F7F2E8;
  --cream-dark: #EDE6D6;
  --indigo: #1E3A5F;
  --indigo-light: #2C5282;
  --terracotta: #B85C38;
  --terracotta-light: #D4714A;
  --gold: #C4973F;
  --gold-light: #DDB96A;
  --text: #2D2D2D;
  --text-light: #666;
  --white: #FFFFFF;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Lato', sans-serif; background: var(--cream); color: var(--text); min-height: 100vh; }

.tile-bg {
  background-color: var(--indigo);
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='56' height='100'%3E%3Crect width='56' height='100' fill='%231E3A5F'/%3E%3Cpath d='M28 66L0 50V18L28 2l28 16v32z' fill='none' stroke='%23C4973F' stroke-width='1' opacity='0.35'/%3E%3Cpath d='M28 66l28-16V18L28 34z' fill='none' stroke='%23C4973F' stroke-width='1' opacity='0.2'/%3E%3Ccircle cx='28' cy='34' r='4' fill='%23C4973F' opacity='0.25'/%3E%3Ccircle cx='0' cy='18' r='2.5' fill='%23C4973F' opacity='0.2'/%3E%3Ccircle cx='56' cy='18' r='2.5' fill='%23C4973F' opacity='0.2'/%3E%3Ccircle cx='28' cy='2' r='2.5' fill='%23C4973F' opacity='0.2'/%3E%3Ccircle cx='28' cy='66' r='2.5' fill='%23C4973F' opacity='0.2'/%3E%3C/svg%3E");
}

header { position: relative; text-align: center; padding: 64px 24px 56px; overflow: hidden; }
header.tile-bg::after { content: ''; position: absolute; inset: 0; background: linear-gradient(to bottom, rgba(30,58,95,0.3) 0%, rgba(30,58,95,0.85) 100%); pointer-events: none; }
header * { position: relative; z-index: 1; }
.header-ornament { font-size: 13px; letter-spacing: 0.35em; text-transform: uppercase; color: var(--gold-light); margin-bottom: 16px; opacity: 0.9; }
header h1 { font-family: 'Playfair Display', serif; font-size: clamp(2.4rem, 6vw, 4rem); color: var(--white); line-height: 1.15; margin-bottom: 12px; }
header h1 em { font-style: italic; color: var(--gold-light); }
.header-subtitle { font-size: 1rem; color: rgba(255,255,255,0.75); letter-spacing: 0.05em; font-weight: 300; max-width: 480px; margin: 0 auto; line-height: 1.6; }
.header-divider { width: 60px; height: 2px; background: var(--gold); margin: 20px auto 0; opacity: 0.7; }

#breadcrumb { display: none; align-items: center; gap: 8px; padding: 14px 32px; background: var(--indigo); font-size: 0.85rem; color: rgba(255,255,255,0.65); }
#breadcrumb.visible { display: flex; }
#breadcrumb a { color: var(--gold-light); text-decoration: none; cursor: pointer; }
#breadcrumb a:hover { text-decoration: underline; }
#breadcrumb span { color: rgba(255,255,255,0.4); }

main { max-width: 1100px; margin: 0 auto; padding: 48px 24px 80px; }

#home-view h2 { font-family: 'Playfair Display', serif; font-size: 1.5rem; color: var(--indigo); margin-bottom: 8px; text-align: center; }
.home-intro { text-align: center; color: var(--text-light); font-size: 0.95rem; margin-bottom: 40px; line-height: 1.6; }
.category-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 20px; }
.category-card { background: var(--white); border-radius: 12px; padding: 28px 20px 22px; cursor: pointer; transition: transform 0.18s, box-shadow 0.18s; border: 1px solid rgba(0,0,0,0.06); display: flex; flex-direction: column; align-items: center; text-align: center; gap: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
.category-card:hover { transform: translateY(-4px); box-shadow: 0 8px 24px rgba(30,58,95,0.12); border-color: var(--gold); }
.cat-icon { font-size: 2.2rem; line-height: 1; margin-bottom: 2px; }
.cat-name { font-family: 'Playfair Display', serif; font-size: 1.1rem; color: var(--indigo); font-weight: 600; }
.cat-desc { font-size: 0.8rem; color: var(--text-light); line-height: 1.4; }
.cat-count { font-size: 0.75rem; color: var(--white); background: var(--terracotta); border-radius: 20px; padding: 2px 10px; font-weight: 700; letter-spacing: 0.03em; }

#category-view h2 { font-family: 'Playfair Display', serif; font-size: 2rem; color: var(--indigo); margin-bottom: 6px; }
.cat-view-meta { color: var(--text-light); font-size: 0.9rem; margin-bottom: 32px; }
.recipe-list { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 16px; }
.recipe-card { background: var(--white); border-radius: 10px; padding: 20px 22px; cursor: pointer; transition: transform 0.15s, box-shadow 0.15s; border: 1px solid rgba(0,0,0,0.07); border-left: 4px solid var(--gold); box-shadow: 0 1px 6px rgba(0,0,0,0.05); }
.recipe-card:hover { transform: translateX(3px); box-shadow: 0 4px 16px rgba(30,58,95,0.1); border-left-color: var(--terracotta); }
.recipe-card h3 { font-family: 'Playfair Display', serif; font-size: 1.05rem; color: var(--indigo); margin-bottom: 4px; }
.recipe-card .recipe-meta-preview { font-size: 0.78rem; color: var(--text-light); line-height: 1.5; }

/* ── Recipe page — cuisine themes ── */
/* Sephardi (Moroccan): default indigo/terracotta/gold palette */
/* Ashkenazi (European): forest green + burgundy */
#recipe-view.cuisine-ashkenazi {
  --r-accent: #1F4225;
  --r-accent2: #7A1E3E;
  --r-step-bg: #1F4225;
  --r-pill-cuisine: #1F4225;
}
#recipe-view.cuisine-sephardi,
#recipe-view {
  --r-accent: var(--terracotta);
  --r-accent2: var(--indigo);
  --r-step-bg: var(--indigo);
  --r-pill-cuisine: #8B4513;
}

/* ── Recipe header ── */
#recipe-view .recipe-header { margin-bottom: 28px; padding-bottom: 22px; border-bottom: 2px solid var(--cream-dark); }
#recipe-view h2 { font-family: 'Playfair Display', serif; font-size: clamp(1.6rem, 4vw, 2.4rem); color: var(--indigo); margin-bottom: 14px; line-height: 1.2; }

/* ── Pills ── */
.recipe-pills { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 4px; }
.pill { display: inline-flex; align-items: center; gap: 5px; font-size: 0.78rem; font-weight: 700; border-radius: 20px; padding: 4px 12px; letter-spacing: 0.02em; white-space: nowrap; }
.pill-cuisine { background: var(--r-pill-cuisine, #8B4513); color: #fff; }
.pill-from    { background: var(--cream-dark); color: var(--text-light); }
.pill-time    { background: var(--cream-dark); color: var(--text-light); }
.pill-yields  { background: var(--cream-dark); color: var(--text-light); }
.pill-kashrut { background: #2C5F2E; color: #fff; }
.pill-cuisine { padding-left: 4px; }
.pill-cuisine.c-sephardi  { background: #F3E3D6; color: #7A3A12; }
.pill-cuisine.c-ashkenazi { background: #E2EBE0; color: #1F4225; }
.pill-cuisine.c-israeli   { background: #E1E8F2; color: #1E3A5F; }
.pill-cuisine.c-yemeni    { background: #F2E0E3; color: #7A2E3A; }
.pill-cuisine.c-other     { background: #ECE7DF; color: #5A4A3A; }
.pill-cuisine .pill-ico   { background: #fff; }
.pill-trad { background: #F4ECD8; color: #6E5214; padding-left: 4px; }
.pill-trad .pill-ico { background: #fff; }
.recipe-card { border-left-width: 5px; }
.pill-ico { display: inline-flex; align-items: center; justify-content: center; width: 20px; height: 20px; border-radius: 50%; background: #FBF6EC; flex: none; font-size: 11px; line-height: 1; }
.pill-ico svg { width: 16px; height: 16px; display: block; }
.kbadge { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%; border: 2px solid; background: #fff; flex: none; font-size: 13px; font-weight: 800; line-height: 1; }
.k-meat   { border-color: #A23B2A; }
.k-dairy  { border-color: #2F6DB5; }
.k-fish   { border-color: #1E7F86; }
.k-pareve { border-color: #C4973F; color: #7A5A1A; font-family: Georgia, 'Times New Roman', serif; font-size: 14px; }
.k-vegan  { border-color: #2E8B3E; background: #2E8B3E; color: #fff; font-family: Georgia, 'Times New Roman', serif; font-size: 14px; }
.recipe-pills { align-items: center; }
.search-wrap { max-width: 560px; margin: 0 auto 32px; position: relative; }
.search-input { width: 100%; padding: 14px 44px 14px 48px; border-radius: 30px; border: 1px solid rgba(0,0,0,0.12); font-family: 'Lato', sans-serif; font-size: 1rem; background: #fff; color: var(--text); box-shadow: 0 2px 8px rgba(0,0,0,0.05); -webkit-appearance: none; }
.search-input:focus { outline: none; border-color: var(--gold); box-shadow: 0 0 0 3px rgba(196,151,63,0.2); }
.search-icon { position: absolute; left: 18px; top: 50%; transform: translateY(-50%); width: 18px; height: 18px; color: var(--text-light); pointer-events: none; }
.search-clear { position: absolute; right: 10px; top: 50%; transform: translateY(-50%); border: none; background: none; font-size: 1.4rem; line-height: 1; padding: 4px 8px; color: var(--text-light); cursor: pointer; display: none; }
.search-clear:hover { color: var(--terracotta); }
.search-meta { text-align: center; color: var(--text-light); font-size: 0.88rem; margin-bottom: 18px; }
.card-cat { font-size: 0.66rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--terracotta); font-weight: 700; margin-bottom: 3px; }
.match-note { font-size: 0.78rem; color: var(--text-light); margin-top: 6px; line-height: 1.45; }
.match-note mark, .recipe-card h3 mark { background: rgba(196,151,63,0.28); color: inherit; padding: 0 1px; border-radius: 2px; }
.add-btn { display: block; margin: -14px auto 30px; background: none; border: 1px dashed var(--gold); color: var(--indigo); border-radius: 20px; padding: 8px 18px; font-family: 'Lato', sans-serif; font-weight: 700; font-size: 0.85rem; cursor: pointer; }
.add-btn:hover { background: #fff; border-style: solid; }
.recipe-top { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.edit-btn { margin-bottom: 28px; background: none; border: 1px solid var(--gold); color: var(--indigo); border-radius: 18px; padding: 6px 14px; font-family: 'Lato', sans-serif; font-weight: 700; font-size: 0.8rem; cursor: pointer; }
.edit-btn:hover { background: #fff; }
.form-card { background: #fff; max-width: 640px; margin: 0 auto; padding: 28px 32px; border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.06); }
.form-card h2 { font-family: 'Playfair Display', serif; font-size: 1.8rem; color: var(--indigo); margin-bottom: 4px; }
.form-sub { color: var(--text-light); font-size: 0.9rem; margin-bottom: 24px; }
.ff { margin-bottom: 22px; }
.fl { display: block; font-weight: 700; color: var(--indigo); font-size: 0.95rem; margin-bottom: 8px; }
.fl .hint { font-weight: 400; color: #888; font-size: 0.8rem; margin-left: 6px; }
.ff input[type=text], .ff input[type=password], .ff textarea { width: 100%; box-sizing: border-box; border: 1px solid #d9d2c3; border-radius: 8px; padding: 12px 14px; font-size: 16px; font-family: 'Lato', sans-serif; background: #FDFBF7; color: var(--text); }
.ff textarea { min-height: 130px; line-height: 1.6; resize: vertical; }
.ff input:focus, .ff textarea:focus { outline: none; border-color: var(--gold); box-shadow: 0 0 0 3px rgba(196,151,63,0.2); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { border: 1px solid #d9d2c3; background: #fff; border-radius: 22px; padding: 8px 15px; font-size: 0.9rem; cursor: pointer; font-family: 'Lato', sans-serif; color: var(--text); display: inline-flex; align-items: center; gap: 7px; }
.chip.on { background: var(--indigo); border-color: var(--indigo); color: #fff; }
.chip .pill-ico { background: #F4EFE4; }
.kchips { gap: 20px; }
.kchip { display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 0.82rem; color: #666; cursor: pointer; background: none; border: none; font-family: 'Lato', sans-serif; padding: 2px; }
.kchip .kbadge { width: 48px; height: 48px; font-size: 21px; }
.kchip.on { color: var(--indigo); font-weight: 700; }
.kchip.on .kbadge { box-shadow: 0 0 0 3px var(--gold); }
.toggle { display: inline-flex; align-items: center; gap: 12px; cursor: pointer; font-size: 0.95rem; color: var(--text); }
.toggle input { position: absolute; opacity: 0; width: 1px; height: 1px; }
.switch { width: 46px; height: 26px; border-radius: 13px; background: #d9d2c3; position: relative; transition: background 0.15s; flex: none; }
.switch::after { content: ""; position: absolute; left: 3px; top: 3px; width: 20px; height: 20px; border-radius: 50%; background: #fff; transition: left 0.15s; }
.toggle input:checked + .switch { background: #2E8B3E; }
.toggle input:checked + .switch::after { left: 23px; }
.toggle input:focus-visible + .switch { box-shadow: 0 0 0 3px rgba(196,151,63,0.35); }
.grid3 { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
@media (max-width: 520px) { .grid3 { grid-template-columns: 1fr; } .form-card { padding: 22px 18px; } }
.form-error { color: #A32D2D; font-size: 0.92rem; min-height: 1.2em; margin-bottom: 10px; }
.save-btn { width: 100%; background: var(--terracotta); color: #fff; border: none; border-radius: 10px; padding: 16px; font-size: 1.05rem; font-weight: 700; font-family: 'Lato', sans-serif; cursor: pointer; }
.save-btn:hover { background: var(--terracotta-light); }
.save-btn:disabled { opacity: 0.6; cursor: default; }
.toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%); background: var(--indigo); color: #fff; padding: 12px 20px; border-radius: 10px; font-size: 0.92rem; box-shadow: 0 6px 20px rgba(0,0,0,0.2); z-index: 50; display: none; max-width: 90vw; text-align: center; }
.legend { display: flex; flex-wrap: wrap; justify-content: center; gap: 10px 22px; margin: 0 auto 18px; color: rgba(255,255,255,0.85); font-size: 0.82rem; letter-spacing: 0.02em; }
.legend-item { display: inline-flex; align-items: center; gap: 7px; }
.card-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin: 8px 0 4px; }
.card-tags .pill { font-size: 0.72rem; padding: 2px 10px 2px 3px; }
.card-tags .kbadge { width: 22px; height: 22px; font-size: 11px; }
.card-tags .k-pareve, .card-tags .k-vegan { font-size: 12px; }

/* ── Description ── */
.recipe-description { font-family: 'Playfair Display', serif; font-style: italic; font-size: 1rem; color: var(--text-light); line-height: 1.7; margin-bottom: 32px; border-left: 3px solid var(--gold); padding-left: 14px; }

/* ── Main body grid ── */
.recipe-body { display: grid; grid-template-columns: 1fr 2fr; gap: 40px; align-items: start; margin-bottom: 36px; }
@media (max-width: 640px) { .recipe-body { grid-template-columns: 1fr; gap: 24px; } }

/* ── Section headings ── */
.recipe-section-heading { font-family: 'Playfair Display', serif; color: var(--r-accent); text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.8rem; font-weight: 700; margin-bottom: 14px; padding-bottom: 6px; border-bottom: 1px solid var(--cream-dark); }

/* ── Ingredients ── */
.ingredients-section ul { list-style: none; padding: 0; }
.ingredients-section li { padding: 6px 0; font-size: 0.9rem; color: var(--text); border-bottom: 1px solid var(--cream-dark); line-height: 1.5; }
.ingredients-section li:last-child { border-bottom: none; }
.ingredients-section li::before { content: "·"; color: var(--r-accent); font-weight: 700; margin-right: 6px; }

/* ── Steps ── */
.steps-section ol { padding-left: 0; list-style: none; counter-reset: step; }
.steps-section ol li { counter-increment: step; display: flex; gap: 14px; margin-bottom: 16px; font-size: 0.92rem; line-height: 1.7; color: var(--text); }
.steps-section ol li::before { content: counter(step); min-width: 26px; height: 26px; border-radius: 50%; background: var(--r-step-bg); color: white; font-size: 0.72rem; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px; }

/* ── Chef's Notes ── */
.notes-section { background: var(--cream-dark); border-radius: 10px; padding: 20px 24px; }
.notes-section ul { list-style: none; padding: 0; }
.notes-section li { font-size: 0.88rem; color: var(--text); line-height: 1.6; padding: 5px 0; border-bottom: 1px solid rgba(0,0,0,0.07); }
.notes-section li:last-child { border-bottom: none; }
.notes-section li::before { content: "✦"; color: var(--gold); margin-right: 8px; font-size: 0.65rem; }

/* ── Legacy fallback for old-format meta tags ── */
.legacy-meta { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 4px; }
.legacy-tag { font-size: 0.78rem; color: var(--text-light); background: var(--cream-dark); border-radius: 4px; padding: 3px 10px; }

.back-btn { display: inline-flex; align-items: center; gap: 6px; margin-bottom: 28px; font-size: 0.85rem; color: var(--indigo-light); cursor: pointer; background: none; border: none; padding: 0; font-family: 'Lato', sans-serif; font-weight: 700; letter-spacing: 0.02em; text-transform: uppercase; transition: color 0.15s; }
.back-btn:hover { color: var(--terracotta); }
.geo-divider { text-align: center; color: var(--gold); font-size: 1.1rem; opacity: 0.5; margin: 10px 0 32px; letter-spacing: 0.5em; }

footer { text-align: center; padding: 32px 24px; font-size: 0.8rem; color: rgba(255,255,255,0.5); letter-spacing: 0.05em; margin-top: 40px; }
</style>
</head>
<body>
<header class="tile-bg">
  <div class="header-ornament">✦ Sephardic &amp; Ashkenazi Traditions ✦</div>
  <h1>Judy's<br><em>Kitchen</em></h1>
  <p class="header-subtitle">A family cookbook by Judy Goldberg-Hazan — recipes passed down, collected, and loved across generations.</p>
  <div class="header-divider"></div>
</header>
<div id="breadcrumb">
  <a onclick="showHome()">Home</a>
  <span>›</span>
  <span id="bc-category" style="color:rgba(255,255,255,0.85)"></span>
  <span id="bc-arrow" style="display:none">›</span>
  <span id="bc-recipe" style="color:rgba(255,255,255,0.85)"></span>
</div>
<main>
  <div id="home-view">
    <h2>The Cookbook</h2>
    <p class="home-intro">From Moroccan boregas and preserved lemons to brisket, kugel, and challah —<br>these are the recipes that made our family table.</p>
    <div class="geo-divider">◆ ◇ ◆</div>
    <div class="search-wrap">
      <svg class="search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></svg>
      <input id="search-input" class="search-input" type="text" placeholder="Search by recipe name or ingredient…" autocomplete="off" spellcheck="false" aria-label="Search recipes by name or ingredient">
      <button class="search-clear" id="search-clear" aria-label="Clear search">×</button>
    </div>
    <button class="add-btn" onclick="showEditor()">＋ Add a recipe</button>
    <div id="search-results" style="display:none">
      <p class="search-meta" id="search-meta"></p>
      <div class="recipe-list" id="search-list"></div>
    </div>
    <div class="category-grid" id="category-grid"></div>
  </div>
  <div id="category-view" style="display:none">
    <button class="back-btn" onclick="showHome()">← All Categories</button>
    <h2 id="cat-title"></h2>
    <p class="cat-view-meta" id="cat-meta"></p>
    <div class="recipe-list" id="recipe-list"></div>
  </div>
  <div id="recipe-view" style="display:none">
    <div class="recipe-top">
      <button class="back-btn" id="back-to-cat">← Back to Category</button>
      <button class="edit-btn" id="edit-recipe-btn">✎ Edit recipe</button>
    </div>
    <div class="recipe-header">
      <h2 id="recipe-title"></h2>
      <div class="recipe-pills" id="recipe-pills"></div>
    </div>
    <div class="recipe-description" id="recipe-description" style="display:none"></div>
    <div class="recipe-body" id="recipe-body"></div>
    <div class="notes-section" id="recipe-notes" style="display:none">
      <div class="recipe-section-heading">Chef's Notes</div>
      <ul id="recipe-notes-list"></ul>
    </div>
  </div>
  <div id="edit-view" style="display:none">
    <button class="back-btn" id="edit-back">← Cancel</button>
    <div class="form-card">
      <h2 id="edit-heading">Add a recipe</h2>
      <p class="form-sub">Only the name, category and ingredients are required.</p>
      <div class="ff"><label class="fl" for="f-name">Recipe name</label><input type="text" id="f-name" autocomplete="off"></div>
      <div class="ff"><span class="fl">Category</span><div class="chips" id="f-folder"></div></div>
      <div class="ff"><span class="fl">Cuisine</span><div class="chips" id="f-cuisine"></div></div>
      <div class="ff"><span class="fl">Tradition<span class="hint">optional — when is it usually made?</span></span><div class="chips" id="f-tradition"></div></div>
      <div class="ff"><span class="fl">Kashrut</span><div class="chips kchips" id="f-kashrut"></div></div>
      <div class="ff"><label class="toggle"><input type="checkbox" id="f-vegan"><span class="switch"></span>Can be made vegan</label></div>
      <div class="ff"><label class="fl" for="f-description">Description<span class="hint">optional</span></label><textarea id="f-description" style="min-height:70px"></textarea></div>
      <div class="ff"><label class="fl" for="f-ingredients">Ingredients<span class="hint">one per line</span></label><textarea id="f-ingredients"></textarea></div>
      <div class="ff"><label class="fl" for="f-steps">Steps<span class="hint">one step per line</span></label><textarea id="f-steps"></textarea></div>
      <div class="ff grid3">
        <div><label class="fl" for="f-prep">Prep time</label><input type="text" id="f-prep" placeholder="20 min"></div>
        <div><label class="fl" for="f-cook">Cook time</label><input type="text" id="f-cook" placeholder="45 min"></div>
        <div><label class="fl" for="f-yields">Serves</label><input type="text" id="f-yields" placeholder="8"></div>
      </div>
      <div class="ff"><label class="fl" for="f-from">From<span class="hint">whose recipe is it?</span></label><input type="text" id="f-from"></div>
      <div class="ff"><label class="fl" for="f-notes">Notes<span class="hint">optional</span></label><textarea id="f-notes" style="min-height:70px"></textarea></div>
      <div class="ff"><label class="fl" for="f-password">Family password</label><input type="password" id="f-password" autocomplete="current-password"></div>
      <div class="form-error" id="form-error" role="alert"></div>
      <button class="save-btn" id="save-btn" onclick="saveRecipe()">Save recipe</button>
    </div>
  </div>
</main>
<div class="toast" id="toast" role="status"></div>
<footer class="tile-bg">
  <div class="legend" aria-label="Kashrut symbols">
    <span class="legend-item"><span class="kbadge k-meat">🥩</span>Meat</span>
    <span class="legend-item"><span class="kbadge k-dairy">🥛</span>Dairy</span>
    <span class="legend-item"><span class="kbadge k-fish">🐟</span>Fish</span>
    <span class="legend-item"><span class="kbadge k-pareve">U</span>Pareve</span>
    <span class="legend-item"><span class="kbadge k-vegan">V</span>Vegan option</span>
  </div>
  <p>Made with love for Judy Goldberg-Hazan &nbsp;·&nbsp; A Family Heirloom</p>
</footer>
<script>
const COOKBOOK = __COOKBOOK_DATA__;
const ICONS = __ICONS_DATA__;
const CATEGORY_COLORS = {
  'Appetizers': '#7A8B3C', 'Chicken': '#D9A21B', 'Fish': '#2A7F86', 'Meat': '#8E2C3A',
  'Soups & Stews': '#C0532E', 'Salads & Vegetables': '#4E8A47', 'Potatoes & Pasta': '#C9A35B',
  'Muffins & Breads': '#8B5E3C', 'Desserts': '#C0607A', 'Cookies & Cakes': '#C0607A',
  'Passover': '#5B4B8A', 'Special': '#4A5A6A',
};
function catColor(cat) { return CATEGORY_COLORS[cat] || '#C4973F'; }
const TRADITION_ICONS = {
  candles: '<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="#C4973F"><rect x="6" y="10" width="3.5" height="11" rx=".6"/><rect x="14.5" y="10" width="3.5" height="11" rx=".6"/></g><g fill="#E0702A"><path d="M7.75 3.5C9 5.5 9.3 6.8 7.75 8.6C6.2 6.8 6.5 5.5 7.75 3.5Z"/><path d="M16.25 3.5C17.5 5.5 17.8 6.8 16.25 8.6C14.7 6.8 15 5.5 16.25 3.5Z"/></g></svg>',
  matzah: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="3.5" width="17" height="17" rx="1.5" fill="#E8C98A" stroke="#B8862B" stroke-width=".8"/><g stroke="#C9A35B" stroke-width=".7"><path d="M3.5 8.5H20.5"/><path d="M3.5 13.5H20.5"/><path d="M3.5 18H20.5"/></g><g fill="#8B5E1E"><circle cx="7" cy="6" r=".7"/><circle cx="12" cy="6" r=".7"/><circle cx="17" cy="6" r=".7"/><circle cx="9.5" cy="11" r=".7"/><circle cx="14.5" cy="11" r=".7"/><circle cx="7" cy="15.8" r=".7"/><circle cx="12" cy="15.8" r=".7"/><circle cx="17" cy="15.8" r=".7"/></g></svg>',
  sun: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.6" fill="#E3A21A"/><g stroke="#E3A21A" stroke-width="1.8" stroke-linecap="round"><path d="M12 2.5V5"/><path d="M12 19V21.5"/><path d="M2.5 12H5"/><path d="M19 12H21.5"/><path d="M5.3 5.3L7 7"/><path d="M17 17L18.7 18.7"/><path d="M5.3 18.7L7 17"/><path d="M17 7L18.7 5.3"/></g></svg>',
  star: '<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="none" stroke="#1E3A5F" stroke-width="1.6" stroke-linejoin="round"><path d="M12 3L19.8 16.5H4.2Z"/><path d="M12 21L4.2 7.5H19.8Z"/></g></svg>',
};
function traditionIcon(t) {
  const k = String(t).toLowerCase();
  return TRADITION_ICONS[/friday|erev|candle/.test(k) ? 'candles' : /passover|pesach/.test(k) ? 'matzah' : /shabbat|seudah|lunch/.test(k) ? 'sun' : 'star'];
}
function traditionPillHTML(t) {
  if (!t) return '';
  return `<span class="pill pill-trad" title="Traditionally made for ${esc(t)}"><span class="pill-ico">${traditionIcon(t)}</span>${esc(t)}</span>`;
}
const CUISINE_ICONS = {
  sephardi: '<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="#8B4513"><rect x="7.3" y="4" width="2.6" height="9" rx="1.3"/><rect x="10.7" y="2.2" width="2.6" height="10" rx="1.3"/><rect x="14.1" y="4" width="2.6" height="9" rx="1.3"/><path d="M6.6 10.5H17.4V16A5.4 5.4 0 0 1 6.6 16Z"/><path d="M7 15.6C5 14.8 3.6 13.2 3.1 11.2C2.9 10.2 4 9.7 4.7 10.5L7 13Z"/><path d="M17 15.6C19 14.8 20.4 13.2 20.9 11.2C21.1 10.2 20 9.7 19.3 10.5L17 13Z"/></g><ellipse cx="12" cy="15.6" rx="2.7" ry="1.6" fill="#fff"/><circle cx="12" cy="15.6" r="1.05" fill="#1E5AA8"/></svg>',
  ashkenazi: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6.8 16.2C6.6 12 7.2 8.6 8.6 7.4C9.8 6.4 10.9 7.6 12 7.6C13.1 7.6 14.2 6.4 15.4 7.4C16.8 8.6 17.4 12 17.2 16.2Z" fill="#111"/><rect x="6.8" y="13.4" width="10.4" height="1.8" fill="#444"/><ellipse cx="12" cy="16.8" rx="10.2" ry="2.3" fill="#111"/></svg>',
  israeli: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="1.5" y="5" width="21" height="14" rx="1" fill="#fff" stroke="#c9ccd6" stroke-width=".6"/><rect x="1.5" y="6.4" width="21" height="2" fill="#0038B8"/><rect x="1.5" y="15.6" width="21" height="2" fill="#0038B8"/><g fill="none" stroke="#0038B8" stroke-width=".8"><path d="M12 9.2L14.5 13.5H9.5Z"/><path d="M12 14.8L14.5 10.5H9.5Z"/></g></svg>',
  yemeni: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.12 5.39A8 8 0 0 0 19.88 5.39" fill="none" stroke="#9A7420" stroke-width=".7"/><g stroke="#B8862B" stroke-width=".8"><path d="M6.86 10.13V14"/><path d="M12 12V16.2"/><path d="M17.14 10.13V14"/></g><g fill="#C8962E"><circle cx="4.12" cy="5.39" r="1.1"/><circle cx="6.86" cy="10.13" r="1.1"/><circle cx="12" cy="12" r="1.2"/><circle cx="17.14" cy="10.13" r="1.1"/><circle cx="19.88" cy="5.39" r="1.1"/><circle cx="6.86" cy="15.1" r="1.4"/><circle cx="17.14" cy="15.1" r="1.4"/><path d="M12 15.8L14.2 19.2L12 22.6L9.8 19.2Z"/></g><g fill="#B8323A"><circle cx="5.07" cy="8" r="1"/><circle cx="9.26" cy="11.52" r="1"/><circle cx="14.74" cy="11.52" r="1"/><circle cx="18.93" cy="8" r="1"/><circle cx="12" cy="19.2" r=".9"/></g></svg>',
  other: '<svg viewBox="0 0 24 24" aria-hidden="true"><g fill="#5A4A3A"><path d="M6 3h1v6h1V3h1v6h1V3h1v7a2.5 2.5 0 0 1-2 2.45V21a1 1 0 0 1-2 0v-8.55A2.5 2.5 0 0 1 6 10Z"/><path d="M18.2 3C16 3.8 14.6 7 14.6 11.2h2.4V21a1 1 0 0 0 2 0V3.2Z"/></g></svg>',
};
function cuisineKey(c) { return (c || '').toLowerCase().split('/')[0].trim(); }
function cuisinePillHTML(c) {
  if (!c) return '';
  const k = cuisineKey(c);
  const cls = CUISINE_ICONS[k] ? k : 'other';
  return `<span class="pill pill-cuisine c-${cls}"><span class="pill-ico">${CUISINE_ICONS[cls]}</span>${esc(c)}</span>`;
}
const KASHRUT_BADGES = {
  meat:   { cls: 'k-meat',   sym: '🥩', title: 'Meat' },
  dairy:  { cls: 'k-dairy',  sym: '🥛', title: 'Dairy' },
  milk:   { cls: 'k-dairy',  sym: '🥛', title: 'Dairy' },
  fish:   { cls: 'k-fish',   sym: '🐟', title: 'Fish' },
  pareve: { cls: 'k-pareve', sym: 'U',  title: 'Pareve' },
  vegan:  { cls: 'k-pareve', sym: 'U',  title: 'Pareve' },
};
function dietBadgesHTML(r) {
  const k = (r.kashrut || '').toLowerCase().trim();
  let h = '';
  const b = KASHRUT_BADGES[k];
  if (b) h += `<span class="kbadge ${b.cls}" title="${b.title}" aria-label="${b.title}">${b.sym}</span>`;
  if (r.vegan_option || k === 'vegan') h += `<span class="kbadge k-vegan" title="Vegan option" aria-label="Vegan option">V</span>`;
  return h;
}
const DESCS = __DESCS_DATA__;

function showHome(keepSearch) {
  document.getElementById('edit-view').style.display = 'none';
  if (!keepSearch) clearSearch();
  document.getElementById('home-view').style.display = '';
  document.getElementById('category-view').style.display = 'none';
  document.getElementById('recipe-view').style.display = 'none';
  document.getElementById('breadcrumb').classList.remove('visible');
  window.scrollTo(0, 0);
}
function showCategory(cat) {
  document.getElementById('edit-view').style.display = 'none';
  const recipes = COOKBOOK[cat];
  document.getElementById('home-view').style.display = 'none';
  document.getElementById('category-view').style.display = '';
  document.getElementById('recipe-view').style.display = 'none';
  document.getElementById('cat-title').textContent = cat;
  document.getElementById('cat-meta').textContent = recipes.length + ' recipes';
  const list = document.getElementById('recipe-list');
  list.innerHTML = '';
  recipes.forEach((r, i) => {
    const card = document.createElement('div');
    card.className = 'recipe-card';
    card.style.borderLeftColor = catColor(cat);
    const tags = cuisinePillHTML(r.cuisine) + traditionPillHTML(r.tradition) + dietBadgesHTML(r);
    const cuisineBadge = tags ? `<div class="card-tags">${tags}</div>` : '';
    const fromText = r.from ? `<div class="recipe-meta-preview">From: ${esc(r.from)}</div>` : (r.meta && r.meta.length ? `<div class="recipe-meta-preview">${esc(r.meta[0])}</div>` : '');
    card.innerHTML = `<h3>${esc(r.title)}</h3>${cuisineBadge}${fromText}`;
    card.onclick = () => showRecipe(cat, i);
    list.appendChild(card);
  });
  document.getElementById('breadcrumb').classList.add('visible');
  document.getElementById('bc-category').textContent = cat;
  document.getElementById('bc-arrow').style.display = 'none';
  document.getElementById('bc-recipe').textContent = '';
  window.scrollTo(0, 0);
}

function showRecipe(cat, idx) {
  document.getElementById('edit-view').style.display = 'none';
  document.getElementById('edit-recipe-btn').onclick = () => showEditor(cat, idx);
  const r = COOKBOOK[cat][idx];
  const view = document.getElementById('recipe-view');
  document.getElementById('home-view').style.display = 'none';
  document.getElementById('category-view').style.display = 'none';
  view.style.display = '';

  // Apply cuisine theme class
  view.className = '';
  if (r.cuisine) {
    const c = r.cuisine.toLowerCase();
    if (c.includes('sephardi') || c.includes('moroccan')) view.classList.add('cuisine-sephardi');
    else if (c.includes('ashkenazi') || c.includes('european') || c.includes('russian')) view.classList.add('cuisine-ashkenazi');
  }

  document.getElementById('recipe-title').textContent = r.title;
  document.getElementById('back-to-cat').onclick = () => showCategory(cat);
  document.getElementById('back-to-cat').textContent = '← Back to Category';

  // Pills
  const pillsDiv = document.getElementById('recipe-pills');
  pillsDiv.innerHTML = '';
  pillsDiv.className = 'recipe-pills';
  const cuisineHTML = cuisinePillHTML(r.cuisine) + traditionPillHTML(r.tradition);
  const badgesHTML = dietBadgesHTML(r);
  const pills = [
    r.from      && { cls: 'pill-from',    icon: '📖', text: 'From: ' + r.from },
    r.prep_time && { cls: 'pill-time',    icon: '⏱', text: 'Prep: ' + r.prep_time },
    r.cook_time && { cls: 'pill-time',    icon: '🍳', text: 'Cook: ' + r.cook_time },
    r.yields    && { cls: 'pill-yields',  icon: '🍽', text: r.yields },
  ].filter(Boolean);
  if (pills.length || cuisineHTML || badgesHTML) {
    pillsDiv.insertAdjacentHTML('beforeend', cuisineHTML);
    pills.forEach(p => {
      const span = document.createElement('span');
      span.className = `pill ${p.cls}`;
      span.innerHTML = `${p.icon} ${esc(p.text)}`;
      pillsDiv.appendChild(span);
    });
    pillsDiv.insertAdjacentHTML('beforeend', badgesHTML);
  } else if (r.meta && r.meta.length) {
    // Legacy fallback: show old-style meta tags
    pillsDiv.className = 'legacy-meta';
    r.meta.forEach(m => {
      const span = document.createElement('span');
      span.className = 'legacy-tag';
      span.textContent = m;
      pillsDiv.appendChild(span);
    });
  }

  // Description
  const descEl = document.getElementById('recipe-description');
  if (r.description) {
    descEl.textContent = r.description;
    descEl.style.display = '';
  } else {
    descEl.style.display = 'none';
  }

  // Ingredients + Steps
  const body = document.getElementById('recipe-body');
  body.innerHTML = '';
  body.style.gridTemplateColumns = '';
  let ingHtml = '';
  if (r.ingredients && r.ingredients.length) {
    ingHtml = `<div class="ingredients-section"><div class="recipe-section-heading">Ingredients</div><ul>` +
      r.ingredients.map(i => `<li>${esc(i)}</li>`).join('') + `</ul></div>`;
  }
  const stepsArr = r.steps && r.steps.length ? r.steps : [];
  let stepsHtml = '';
  if (stepsArr.length) {
    stepsHtml = `<div class="steps-section"><div class="recipe-section-heading">Preparation Steps</div><ol>` +
      stepsArr.map(s => `<li><span>${esc(s)}</span></li>`).join('') + `</ol></div>`;
  }
  if (!ingHtml && !stepsHtml) {
    body.style.gridTemplateColumns = '1fr';
    body.innerHTML = '<p style="color:var(--text-light);font-style:italic">Recipe details coming soon.</p>';
  } else {
    body.innerHTML = (ingHtml || '') + (stepsHtml || '');
    if (!ingHtml || !stepsHtml) body.style.gridTemplateColumns = '1fr';
  }

  // Chef's Notes
  const notesEl = document.getElementById('recipe-notes');
  const notesList = document.getElementById('recipe-notes-list');
  if (r.notes && r.notes.length) {
    notesList.innerHTML = r.notes.map(n => `<li>${esc(n)}</li>`).join('');
    notesEl.style.display = '';
  } else {
    notesEl.style.display = 'none';
  }

  // Breadcrumb
  document.getElementById('breadcrumb').classList.add('visible');
  document.getElementById('bc-category').textContent = cat;
  document.getElementById('bc-category').onclick = () => showCategory(cat);
  document.getElementById('bc-category').style.cursor = 'pointer';
  document.getElementById('bc-arrow').style.display = '';
  document.getElementById('bc-recipe').textContent = r.title;
  window.scrollTo(0, 0);
}
function esc(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
function buildHome() {
  const grid = document.getElementById('category-grid');
  Object.keys(COOKBOOK).forEach(cat => {
    const count = COOKBOOK[cat].length;
    const card = document.createElement('div');
    card.className = 'category-card';
    card.innerHTML = `<div class="cat-icon">${ICONS[cat] || '🍽️'}</div><div class="cat-name">${esc(cat)}</div><div class="cat-desc">${esc(DESCS[cat] || '')}</div><div class="cat-count">${count} recipes</div>`;
    card.onclick = () => showCategory(cat);
    grid.appendChild(card);
  });
}
buildHome();

// ── Search ──
const DIACRITICS = new RegExp('[' + String.fromCharCode(0x300) + '-' + String.fromCharCode(0x36f) + ']', 'g');
function norm(s) { return String(s || '').toLowerCase().normalize('NFD').replace(DIACRITICS, ''); }
const SEARCH_INDEX = [];
function rebuildSearchIndex() {
SEARCH_INDEX.length = 0;
Object.keys(COOKBOOK).forEach(cat => COOKBOOK[cat].forEach((r, i) => {
  const ings = r.ingredients || [];
  SEARCH_INDEX.push({ cat, i, r, title: norm(r.title), trad: norm(r.tradition), ings: ings.map(norm), ingsRaw: ings });
}));
}
rebuildSearchIndex();
function highlight(text, terms) {
  // Highlight terms when normalizing didn't change the string length (keeps indexes aligned)
  const n = norm(text);
  if (n.length !== text.length) return esc(text);
  const marks = new Array(text.length).fill(false);
  terms.forEach(t => { let k = n.indexOf(t); while (k !== -1) { for (let j = k; j < k + t.length; j++) marks[j] = true; k = n.indexOf(t, k + t.length); } });
  let out = '', open = false;
  for (let j = 0; j < text.length; j++) {
    if (marks[j] && !open) { out += '<mark>'; open = true; }
    if (!marks[j] && open) { out += '</mark>'; open = false; }
    out += esc(text[j]);
  }
  return out + (open ? '</mark>' : '');
}
function clearSearch() {
  const input = document.getElementById('search-input');
  if (input) input.value = '';
  runSearch('');
}
function runSearch(q) {
  const terms = norm(q).trim().split(' ').filter(Boolean);
  const results = document.getElementById('search-results');
  const grid = document.getElementById('category-grid');
  document.getElementById('search-clear').style.display = q ? 'block' : 'none';
  if (!terms.length) { results.style.display = 'none'; grid.style.display = ''; return; }
  const hits = [];
  SEARCH_INDEX.forEach(e => {
    let score = 0;
    const ok = terms.every(t => {
      const inTitle = e.title.includes(t);
      const inIng = e.ings.some(l => l.includes(t));
      const inTrad = !!e.trad && e.trad.includes(t);
      if (inTrad) score += 5;
      if (inTitle) score += e.title.startsWith(t) ? 20 : 10;
      if (inIng) score += 1;
      return inTitle || inIng || inTrad;
    });
    if (!ok) return;
    const lines = [];
    e.ings.forEach((l, k) => { if (lines.length < 2 && terms.some(t => l.includes(t))) lines.push(e.ingsRaw[k]); });
    hits.push({ e, score, lines });
  });
  hits.sort((a, b) => b.score - a.score || a.e.title.localeCompare(b.e.title));
  const list = document.getElementById('search-list');
  list.innerHTML = '';
  hits.forEach(({ e, lines }) => {
    const r = e.r;
    const card = document.createElement('div');
    card.className = 'recipe-card';
    const tags = cuisinePillHTML(r.cuisine) + traditionPillHTML(r.tradition) + dietBadgesHTML(r);
    const note = lines.length ? `<div class="match-note">Uses: ${lines.map(l => highlight(l, terms)).join(' · ')}</div>` : '';
    card.style.borderLeftColor = catColor(e.cat);
    card.innerHTML = `<div class="card-cat" style="color:${catColor(e.cat)}">${esc(e.cat)}</div><h3>${highlight(r.title, terms)}</h3>${tags ? `<div class="card-tags">${tags}</div>` : ''}${note}`;
    card.onclick = () => {
      showRecipe(e.cat, e.i);
      const back = document.getElementById('back-to-cat');
      back.textContent = '← Back to Search Results';
      back.onclick = () => showHome(true);
    };
    list.appendChild(card);
  });
  const n = hits.length;
  document.getElementById('search-meta').textContent = n
    ? `${n} recipe${n === 1 ? '' : 's'} matching “${q.trim()}”`
    : `No recipes found for “${q.trim()}” — try a single ingredient, like “lemon”.`;
  grid.style.display = 'none';
  results.style.display = '';
}
(function initSearch() {
  const input = document.getElementById('search-input');
  let timer;
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(() => runSearch(input.value), 120); });
  input.addEventListener('keydown', ev => { if (ev.key === 'Escape') clearSearch(); });
  document.getElementById('search-clear').onclick = () => { clearSearch(); input.focus(); };
})();

// ── Add / edit recipes ──
const OPTIONS = __OPTIONS_DATA__;
const NL = String.fromCharCode(10);
let editCtx = null;
const OPTION_ORDER = {
  Cuisine: ['Sephardi', 'Ashkenazi', 'Israeli', 'Yemeni', 'Other'],
  Kashrut: ['Meat', 'Dairy', 'Fish', 'Pareve'],
  Tradition: ['Friday Night', 'Shabbat Lunch', 'Holidays', 'Passover'],
};
const OPTION_HIDE = ['Uh Oh', 'Vegan'];
function optList(name, fallback, keep) {
  let o = (OPTIONS[name] || []).filter(v => !(name === 'Kashrut' && OPTION_HIDE.includes(v)) && v !== 'Uh Oh');
  if (!o.length) o = fallback.slice();
  const order = OPTION_ORDER[name] || [];
  const rank = v => { const k = order.indexOf(v); return k === -1 ? (v === 'Other' ? 999 : 500) : k; };
  o.sort((a, b) => rank(a) - rank(b));
  if (keep && !o.includes(keep)) o.push(keep);
  return o;
}
function renderChips(id, values, selected, opts) {
  opts = opts || {};
  const el = document.getElementById(id);
  el.innerHTML = '';
  el.dataset.value = selected || '';
  values.forEach(v => {
    const b = document.createElement('button');
    b.type = 'button';
    b.className = opts.kashrut ? 'kchip' : 'chip';
    b.innerHTML = opts.html ? opts.html(v) : esc(v);
    b.setAttribute('aria-pressed', v === selected ? 'true' : 'false');
    if (v === selected) b.classList.add('on');
    b.onclick = () => {
      const next = (el.dataset.value === v && !opts.required) ? '' : v;
      el.dataset.value = next;
      Array.from(el.children).forEach(c => { const on = (c === b && next === v); c.classList.toggle('on', on); c.setAttribute('aria-pressed', on ? 'true' : 'false'); });
      document.getElementById('form-error').textContent = '';
    };
    el.appendChild(b);
  });
}
const cuisineChip = v => `<span class="pill-ico">${CUISINE_ICONS[cuisineKey(v)] || CUISINE_ICONS.other}</span>${esc(v)}`;
const tradChip = v => `<span class="pill-ico">${traditionIcon(v)}</span>${esc(v)}`;
const kashrutChip = v => { const b = KASHRUT_BADGES[v.toLowerCase()]; return `<span class="kbadge ${b ? b.cls : 'k-pareve'}">${b ? b.sym : esc(v.charAt(0))}</span>${esc(v)}`; };
function showEditor(cat, i) {
  const r = (cat !== undefined && cat !== null) ? COOKBOOK[cat][i] : null;
  editCtx = r ? { cat, i, id: r.id } : null;
  ['home-view', 'category-view', 'recipe-view'].forEach(v => document.getElementById(v).style.display = 'none');
  document.getElementById('edit-view').style.display = '';
  document.getElementById('breadcrumb').classList.remove('visible');
  document.getElementById('edit-heading').textContent = r ? 'Edit recipe' : 'Add a recipe';
  const set = (id, v) => { document.getElementById(id).value = v || ''; };
  const join = a => (a || []).join(NL);
  set('f-name', r && r.title);
  set('f-description', r && r.description);
  set('f-ingredients', r && join(r.ingredients));
  set('f-steps', r && join(r.steps));
  set('f-notes', r && join(r.notes));
  set('f-prep', r && r.prep_time);
  set('f-cook', r && r.cook_time);
  set('f-yields', r && r.yields);
  set('f-from', r && r.from);
  document.getElementById('f-vegan').checked = !!(r && r.vegan_option);
  const folders = Object.keys(COOKBOOK).concat((OPTIONS.Folder || []).filter(f => !(f in COOKBOOK)));
  renderChips('f-folder', folders, r ? cat : '', { required: true });
  renderChips('f-cuisine', optList('Cuisine', ['Sephardi', 'Ashkenazi', 'Israeli', 'Other'], r && r.cuisine), r && r.cuisine, { html: cuisineChip });
  renderChips('f-tradition', optList('Tradition', [], r && r.tradition), r && r.tradition, { html: tradChip });
  renderChips('f-kashrut', optList('Kashrut', ['Meat', 'Dairy', 'Pareve'], r && r.kashrut), r && r.kashrut, { kashrut: true, html: kashrutChip });
  try { document.getElementById('f-password').value = localStorage.getItem('cookbook-pw') || ''; } catch (e) {}
  document.getElementById('form-error').textContent = '';
  document.getElementById('edit-back').onclick = () => r ? showRecipe(cat, i) : showHome(true);
  window.scrollTo(0, 0);
}
function formError(msg, focusId) {
  document.getElementById('form-error').textContent = msg;
  if (focusId) document.getElementById(focusId).focus();
}
async function saveRecipe() {
  const g = id => document.getElementById(id).value.trim();
  const chip = id => document.getElementById(id).dataset.value || null;
  const fields = {
    name: g('f-name'), folder: chip('f-folder'), cuisine: chip('f-cuisine'), tradition: chip('f-tradition'),
    kashrut: chip('f-kashrut'), vegan_option: document.getElementById('f-vegan').checked,
    description: g('f-description'), ingredients: g('f-ingredients'), steps: g('f-steps'), notes: g('f-notes'),
    from: g('f-from'), prep_time: g('f-prep'), cook_time: g('f-cook'), yields: g('f-yields'),
  };
  const pw = document.getElementById('f-password').value;
  if (!fields.name) return formError('Give the recipe a name.', 'f-name');
  if (!fields.folder) return formError('Pick a category.');
  if (!fields.ingredients) return formError('Add at least one ingredient.', 'f-ingredients');
  if (!pw) return formError('Enter the family password.', 'f-password');
  if (editCtx && !editCtx.id) return formError("This recipe can't be edited here yet. Please edit it in Notion.");
  const btn = document.getElementById('save-btn');
  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const res = await fetch('/.netlify/functions/recipe', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ password: pw, id: editCtx ? editCtx.id : null, fields }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Something went wrong. Try again.');
    try { localStorage.setItem('cookbook-pw', pw); } catch (e) {}
    applyLocal(fields, data.id);
  } catch (e) {
    formError(e instanceof TypeError ? "Couldn't reach the site. Check your connection and try again." : e.message);
  } finally {
    btn.disabled = false; btn.textContent = 'Save recipe';
  }
}
function applyLocal(f, id) {
  const lines = s => s ? s.split(NL).map(x => x.trim()).filter(Boolean) : [];
  const rec = editCtx ? COOKBOOK[editCtx.cat][editCtx.i] : {};
  Object.assign(rec, {
    id: id || rec.id, title: f.name, cuisine: f.cuisine, tradition: f.tradition, kashrut: f.kashrut,
    vegan_option: f.vegan_option, description: f.description || null, ingredients: lines(f.ingredients),
    steps: lines(f.steps), notes: lines(f.notes), from: f.from || null, prep_time: f.prep_time || null,
    cook_time: f.cook_time || null, yields: f.yields || null, meta: [],
  });
  if (editCtx) COOKBOOK[editCtx.cat].splice(editCtx.i, 1);
  if (!COOKBOOK[f.folder]) COOKBOOK[f.folder] = [];
  COOKBOOK[f.folder].push(rec);
  COOKBOOK[f.folder].sort((a, b) => a.title.toLowerCase().localeCompare(b.title.toLowerCase()));
  rebuildSearchIndex();
  showRecipe(f.folder, COOKBOOK[f.folder].indexOf(rec));
  toast('Saved! Everyone will see it on the site in about a minute.');
}
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.style.display = 'block';
  clearTimeout(toast._t); toast._t = setTimeout(() => { t.style.display = 'none'; }, 6000);
}
document.getElementById('edit-view').addEventListener('input', () => { document.getElementById('form-error').textContent = ''; });
</script>
</body>
</html>'''


def load_from_notion():
    """
    Fetch all recipes from the Notion database and return the same
    {category: [recipe, ...]} structure that load_cookbook() produces.

    Requires: NOTION_TOKEN env var (internal integration token).
    """
    try:
        import requests
    except ImportError:
        raise SystemExit("requests not installed — run: pip3 install requests")

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise SystemExit(
            "NOTION_TOKEN not set.\n"
            "  1. Create an integration at https://www.notion.so/my-integrations\n"
            "  2. Share the Family Cookbook DB with that integration\n"
            "  3. export NOTION_TOKEN=secret_xxxx"
        )

    headers = {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }

    # Paginate through all pages in the database
    pages, cursor = [], None
    while True:
        payload = {"page_size": 100}
        if cursor:
            payload["start_cursor"] = cursor
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
            headers=headers, json=payload
        )
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data["results"])
        if not data.get("has_more"):
            break
        cursor = data["next_cursor"]

    # Select options (for the add/edit form)
    schema = requests.get(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}", headers=headers)
    schema.raise_for_status()
    for prop in ("Folder", "Cuisine", "Kashrut", "Tradition"):
        p = schema.json()["properties"].get(prop, {})
        if p.get("type") == "select":
            NOTION_OPTIONS[prop] = [o["name"] for o in p["select"]["options"]]

    def get_text(props, name):
        p = props.get(name, {})
        t = p.get("type")
        if t == "title":
            return "".join(r["plain_text"] for r in p.get("title", []))
        if t == "rich_text":
            return "".join(r["plain_text"] for r in p.get("rich_text", []))
        return ""

    def get_select(props, name):
        p = props.get(name, {})
        if p.get("type") == "select" and p.get("select"):
            return p["select"]["name"]
        return None

    cookbook = {}
    for page in pages:
        if page.get("archived") or page.get("in_trash"):
            continue
        props = page["properties"]
        name = get_text(props, "Name")
        if not name:
            continue

        category = get_select(props, "Folder") or "Special"
        ingredients_raw = get_text(props, "Ingredients")
        steps_raw       = get_text(props, "Preparation Steps")
        notes_raw       = get_text(props, "Chef's Notes")

        recipe = {
            "id":          page["id"],
            "title":       name,
            "cuisine":     get_select(props, "Cuisine"),
            "from":        get_text(props, "From") or None,
            "prep_time":   get_text(props, "Preparation Time") or None,
            "cook_time":   get_text(props, "Cook Time") or None,
            "yields":      get_text(props, "Yields") or None,
            "kashrut":     get_select(props, "Kashrut"),
            "tradition":   get_select(props, "Tradition"),
            "vegan_option": bool(props.get("Vegan Option?", {}).get("checkbox")),
            "description": get_text(props, "Description") or None,
            "ingredients": [l for l in ingredients_raw.splitlines() if l.strip()],
            "steps":       [l for l in steps_raw.splitlines() if l.strip()],
            "notes":       [l for l in notes_raw.splitlines() if l.strip()],
            "meta":        [],
        }
        cookbook.setdefault(category, []).append(recipe)

    # Sort each category alphabetically by title
    for cat in cookbook:
        cookbook[cat].sort(key=lambda r: r["title"].lower())

    # Order categories
    available = list(cookbook.keys())
    ordered = [c for c in CATEGORY_ORDER if c in available]
    ordered += sorted([c for c in available if c not in CATEGORY_ORDER])
    return {c: cookbook[c] for c in ordered}


def build(source="files"):
    if source == "notion":
        print("Fetching recipes from Notion...")
        cookbook = load_from_notion()
    else:
        cookbook = load_cookbook()

    total = sum(len(v) for v in cookbook.values())
    print(f"Loaded {total} recipes across {len(cookbook)} categories")

    html = HTML_TEMPLATE
    html = html.replace("__COOKBOOK_DATA__", json.dumps(cookbook, ensure_ascii=False))
    html = html.replace("__ICONS_DATA__", json.dumps(CATEGORY_ICONS, ensure_ascii=False))
    html = html.replace("__DESCS_DATA__", json.dumps(CATEGORY_DESCRIPTIONS, ensure_ascii=False))
    html = html.replace("__OPTIONS_DATA__", json.dumps(NOTION_OPTIONS, ensure_ascii=False))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ Built index.html ({round(os.path.getsize(OUTPUT_FILE) / 1024)}KB)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Judy's Cookbook site builder")
    parser.add_argument(
        "--source",
        choices=["files", "notion"],
        default="files",
        help="Data source: 'files' (iCloud, default) or 'notion'",
    )
    args = parser.parse_args()
    build(source=args.source)
