# Judy's Kitchen — Cookbook Website

Live site: https://judyscookbook.netlify.app

## How it works

- Recipes live in Judy's iCloud folder as `.doc` files, organized by category
- `recipes/` in this repo is a symlink to that iCloud folder — no copying needed
- `build.py` reads the `.doc` files (using macOS `textutil`) and generates `index.html`
- `index.html` is committed to git and served by Netlify as a static file

## Deploying an update

When Judy says she's made changes:

```bash
cd ~/Developer/personal/judys-cookbook
python3 build.py
git add index.html && git commit -m "update recipes" && git push
```

Netlify picks up the push and the site is live within ~30 seconds.

## Adding a new recipe

1. Judy adds a new `.doc` file to the right category folder in iCloud
2. Run the 3 commands above

## Adding a new category

1. Judy creates a new subfolder in the iCloud Cookbook folder and adds `.doc` files to it
2. Optionally add an icon and description in `build.py` under `CATEGORY_ICONS` and `CATEGORY_DESCRIPTIONS`
3. Run the 3 commands above

## Previewing locally before pushing

```bash
python3 build.py
open index.html
```
