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


def read_doc(path):
    """Use macOS textutil to extract plain text from a .doc file."""
    result = subprocess.run(
        ["textutil", "-convert", "txt", "-stdout", path],
        capture_output=True, text=True
    )
    return result.stdout.strip()


def parse_doc(name, text):
    """Parse plain text extracted from a .doc file into structured recipe data."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    ing_idx = inst_idx = None
    for i, l in enumerate(lines):
        if re.match(r"^INGREDIENTS?\s*$", l, re.I):
            ing_idx = i
        if re.match(r"^INSTRUCTIONS?\s*$|^DIRECTIONS?\s*$|^METHOD\s*$", l, re.I):
            inst_idx = i

    # Meta: lines before INGREDIENTS, excluding the recipe title and padding
    meta_end = ing_idx if ing_idx is not None else (inst_idx if inst_idx is not None else len(lines))
    meta = []
    for l in lines[1:meta_end]:
        if l.lower() == name.lower(): continue
        if len(l) > 150: continue  # skip formatting padding
        meta.append(l)

    # Ingredients
    ingredients = []
    if ing_idx is not None:
        end = inst_idx if inst_idx is not None else len(lines)
        for l in lines[ing_idx + 1:end]:
            if l and len(l) < 200:
                ingredients.append(l)

    # Instructions — group consecutive non-blank lines into steps
    instructions = []
    if inst_idx is not None:
        current = []
        for l in lines[inst_idx + 1:]:
            if l:
                current.append(l)
            else:
                if current:
                    instructions.append(" ".join(current))
                    current = []
        if current:
            instructions.append(" ".join(current))

    return {
        "title": name,
        "meta": meta,
        "ingredients": ingredients,
        "instructions": instructions,
    }


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
            if not fname.endswith(".doc"):
                continue
            name = fname[:-4]
            if name in SKIP_FILES:
                continue
            text = read_doc(os.path.join(cat_path, fname))
            if text:
                recipes.append(parse_doc(name, text))
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

#recipe-view .recipe-header { margin-bottom: 32px; padding-bottom: 24px; border-bottom: 2px solid var(--cream-dark); }
#recipe-view h2 { font-family: 'Playfair Display', serif; font-size: clamp(1.6rem, 4vw, 2.4rem); color: var(--indigo); margin-bottom: 10px; line-height: 1.2; }
.recipe-meta-tags { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.meta-tag { font-size: 0.8rem; color: var(--text-light); background: var(--cream-dark); border-radius: 4px; padding: 3px 10px; line-height: 1.5; }
.recipe-body { display: grid; grid-template-columns: 1fr 2fr; gap: 40px; align-items: start; }
@media (max-width: 640px) { .recipe-body { grid-template-columns: 1fr; gap: 24px; } }
.ingredients-section h3, .instructions-section h3 { font-family: 'Playfair Display', serif; color: var(--terracotta); text-transform: uppercase; letter-spacing: 0.08em; font-size: 0.85rem; margin-bottom: 14px; padding-bottom: 6px; border-bottom: 1px solid var(--cream-dark); }
.ingredients-section ul { list-style: none; padding: 0; }
.ingredients-section li { padding: 6px 0; font-size: 0.9rem; color: var(--text); border-bottom: 1px solid var(--cream-dark); line-height: 1.5; }
.ingredients-section li:last-child { border-bottom: none; }
.instructions-section ol { padding-left: 0; list-style: none; counter-reset: step; }
.instructions-section ol li { counter-increment: step; display: flex; gap: 14px; margin-bottom: 14px; font-size: 0.92rem; line-height: 1.65; color: var(--text); }
.instructions-section ol li::before { content: counter(step); min-width: 26px; height: 26px; border-radius: 50%; background: var(--indigo); color: white; font-size: 0.72rem; font-weight: 700; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 2px; }

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
      <div class="recipe-meta-tags" id="recipe-meta"></div>
    </div>
    <div class="recipe-body" id="recipe-body"></div>
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
    const metaText = r.meta && r.meta.length > 0 ? r.meta.slice(0,2).join(' · ') : '';
    card.innerHTML = `<h3>${esc(r.title)}</h3>${metaText ? `<div class="recipe-meta-preview">${esc(metaText)}</div>` : ''}`;
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
  document.getElementById('home-view').style.display = 'none';
  document.getElementById('category-view').style.display = 'none';
  document.getElementById('recipe-view').style.display = '';
  document.getElementById('recipe-title').textContent = r.title;
  document.getElementById('back-to-cat').onclick = () => showCategory(cat);
  const metaDiv = document.getElementById('recipe-meta');
  metaDiv.innerHTML = '';
  (r.meta || []).forEach(m => {
    const tag = document.createElement('span');
    tag.className = 'meta-tag';
    tag.textContent = m;
    metaDiv.appendChild(tag);
  });
  const body = document.getElementById('recipe-body');
  body.innerHTML = '';
  let ingHtml = '';
  if (r.ingredients && r.ingredients.length) {
    ingHtml = `<div class="ingredients-section"><h3>Ingredients</h3><ul>` +
      r.ingredients.map(i => `<li>${esc(i)}</li>`).join('') + `</ul></div>`;
  }
  let instHtml = '';
  if (r.instructions && r.instructions.length) {
    instHtml = `<div class="instructions-section"><h3>Instructions</h3><ol>` +
      r.instructions.map(i => `<li><span>${esc(i)}</span></li>`).join('') + `</ol></div>`;
  }
  body.innerHTML = (ingHtml || '') + (instHtml || '');
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
