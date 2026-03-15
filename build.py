#!/usr/bin/env python3
"""
Judy's Cookbook — Site Builder
================================
Reads .doc recipe files from the recipes/ folder (symlinked to iCloud)
and generates index.html.

recipes/ is a symlink to:
  ~/Library/Mobile Documents/com~apple~CloudDocs/Documents/
  Personal - Reading and Interests/Mom's Cookbook/Cookbook

Usage:
    python3 build.py

Workflow:
    1. Judy edits a recipe in Google Docs → it syncs to iCloud automatically
    2. Run: python3 build.py
    3. Run: git add index.html && git commit -m "update recipes" && git push
    4. Netlify serves the updated site within ~30 seconds

Note: build.py requires macOS (uses textutil to read .doc files).
      index.html is committed to git so Netlify just serves it as a static file.
"""

import os, json, re, subprocess
from docx import Document

RECIPES_DIR = os.path.join(os.path.dirname(__file__), "recipes")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "index.html")

CATEGORY_ICONS = {
    "Appetizers": "🫒",
    "Chicken": "🍗",
    "Cookies & Cakes": "🍰",
    "Fish": "🐟",
    "Meat": "🥩",
    "Muffins & Breads": "🍞",
    "Potatoes & Pasta": "🥔",
    "Salads & Vegetables": "🥗",
    "Soups & Stews": "🍲",
}
CATEGORY_DESCRIPTIONS = {
    "Appetizers": "Starters & small bites",
    "Chicken": "Roasts, curries & more",
    "Cookies & Cakes": "Sweets & baked treats",
    "Fish": "Salmon, shrimp & seafood",
    "Meat": "Briskets, ribs & mains",
    "Muffins & Breads": "Loaves, challah & muffins",
    "Potatoes & Pasta": "Kugel, pasta & sides",
    "Salads & Vegetables": "Fresh sides & salads",
    "Soups & Stews": "Warming bowls & broth",
}

CATEGORY_ORDER = [
    "Appetizers", "Chicken", "Fish", "Meat", "Soups & Stews",
    "Salads & Vegetables", "Potatoes & Pasta", "Muffins & Breads", "Cookies & Cakes"
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
        elif re.search(r"prep\.?\s*time", cl):
            val = re.split(r"prep\.?\s*time[:\s]+", chunk, flags=re.I, maxsplit=1)[-1].strip()
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
        recipes = []
        for fname in sorted(os.listdir(cat_path)):
            root, ext = os.path.splitext(fname)
            if ext.lower() not in RECIPE_EXTENSIONS:
                continue
            name = root
            if name in SKIP_FILES:
                continue
            fpath = os.path.join(cat_path, fname)
            if ext.lower() == ".docx":
                recipe = parse_docx_structured(name, fpath)
            else:
                recipe = read_and_parse_legacy(name, fpath)
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
    <div class="category-grid" id="category-grid"></div>
  </div>
  <div id="category-view" style="display:none">
    <button class="back-btn" onclick="showHome()">← All Categories</button>
    <h2 id="cat-title"></h2>
    <p class="cat-view-meta" id="cat-meta"></p>
    <div class="recipe-list" id="recipe-list"></div>
  </div>
  <div id="recipe-view" style="display:none">
    <button class="back-btn" id="back-to-cat">← Back to Category</button>
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
</main>
<footer class="tile-bg">
  <p>Made with love for Judy Goldberg-Hazan &nbsp;·&nbsp; A Family Heirloom</p>
</footer>
<script>
const COOKBOOK = __COOKBOOK_DATA__;
const ICONS = __ICONS_DATA__;
const DESCS = __DESCS_DATA__;

function showHome() {
  document.getElementById('home-view').style.display = '';
  document.getElementById('category-view').style.display = 'none';
  document.getElementById('recipe-view').style.display = 'none';
  document.getElementById('breadcrumb').classList.remove('visible');
  window.scrollTo(0, 0);
}
function showCategory(cat) {
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
    const cuisineBadge = r.cuisine ? `<span style="font-size:0.7rem;font-weight:700;color:var(--terracotta);text-transform:uppercase;letter-spacing:0.05em">${esc(r.cuisine)}</span>` : '';
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

  // Pills
  const pillsDiv = document.getElementById('recipe-pills');
  pillsDiv.innerHTML = '';
  const pills = [
    r.cuisine   && { cls: 'pill-cuisine', icon: ({'sephardi':'🌶️','ashkenazi':'🥯','israeli':'🇮🇱'}[r.cuisine.toLowerCase().split('/')[0].trim()] || '🍽️'), text: r.cuisine },
    r.from      && { cls: 'pill-from',    icon: '📖', text: 'From: ' + r.from },
    r.prep_time && { cls: 'pill-time',    icon: '⏱', text: 'Prep: ' + r.prep_time },
    r.cook_time && { cls: 'pill-time',    icon: '🍳', text: 'Cook: ' + r.cook_time },
    r.yields    && { cls: 'pill-yields',  icon: '🍽', text: r.yields },
    r.kashrut   && { cls: 'pill-kashrut', icon: '✡', text: r.kashrut },
  ].filter(Boolean);
  if (pills.length) {
    pills.forEach(p => {
      const span = document.createElement('span');
      span.className = `pill ${p.cls}`;
      span.innerHTML = `${p.icon} ${esc(p.text)}`;
      pillsDiv.appendChild(span);
    });
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
</script>
</body>
</html>'''


def build():
    cookbook = load_cookbook()
    total = sum(len(v) for v in cookbook.values())
    print(f"Loaded {total} recipes across {len(cookbook)} categories")

    html = HTML_TEMPLATE
    html = html.replace("__COOKBOOK_DATA__", json.dumps(cookbook, ensure_ascii=False))
    html = html.replace("__ICONS_DATA__", json.dumps(CATEGORY_ICONS, ensure_ascii=False))
    html = html.replace("__DESCS_DATA__", json.dumps(CATEGORY_DESCRIPTIONS, ensure_ascii=False))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"✓ Built index.html ({round(os.path.getsize(OUTPUT_FILE) / 1024)}KB)")


if __name__ == "__main__":
    build()
