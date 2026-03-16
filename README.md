# Judy's Kitchen — Cookbook Website

Live site: https://judyscookbook.netlify.app

---

## How it works

Recipes live in a **Notion database** (Family Cookbook → Recipes). Judy edits them there directly. When you want to publish her changes to the website:

1. Judy edits recipes in Notion
2. You run the deploy commands below
3. Netlify picks up the push and the site is live within ~30 seconds

The site is a single `index.html` file committed to this repo. Netlify just serves it statically — no server needed.

---

## Deploying an update (normal workflow)

```bash
cd ~/Developer/personal/judys-cookbook
python3 build.py --source notion
git add index.html && git commit -m "update recipes" && git push
```

---

## One-time setup: Notion token

`build.py --source notion` needs a Notion API token to read the database.

**You only need to do this once** (already done on this machine, but here's how to redo it on a new machine):

1. Go to https://www.notion.so/my-integrations → **New integration** → name it "Cookbook Builder" → copy the token
2. In Notion, open **Family Cookbook** → **Share** → **Connections** → connect your integration
3. Add the token to your shell:
   ```bash
   echo 'export NOTION_TOKEN=secret_xxxx' >> ~/.zshrc
   source ~/.zshrc
   ```
   (replace `secret_xxxx` with your actual token)

---

## Adding or editing a recipe

Judy does this directly in Notion — no involvement from you unless she wants the site updated. When she's done, run the deploy commands above.

## Adding a new category

1. Judy adds a new **Folder** option to the Recipes database in Notion (click any Folder field → Edit options)
2. Optionally add an icon/description for it in `build.py` under `CATEGORY_ICONS` and `CATEGORY_DESCRIPTIONS`
3. Deploy as normal

---

## Fallback: build from iCloud files (original workflow)

If Notion is unavailable or you want to build from the raw `.doc` files in iCloud:

```bash
python3 build.py          # reads from recipes/ symlink (iCloud)
git add index.html && git commit -m "update recipes" && git push
```

The `recipes/` folder in this repo is a symlink to:
```
~/Library/Mobile Documents/com~apple~CloudDocs/Documents/
Personal - Reading and Interests/Mom's Cookbook/Cookbook
```

Note: the file-based build requires macOS (uses `textutil` to read `.doc` files).

---

## Previewing locally before pushing

```bash
python3 build.py --source notion   # or without --source for file-based
open index.html
```

---

## Project structure

```
judys-cookbook/
├── build.py              # site builder — run this to regenerate index.html
├── generate_templates.py # one-time tool: converts old .doc files to .docx templates
├── index.html            # the built site — committed to git, served by Netlify
├── recipes/              # symlink → iCloud Cookbook folder (fallback source)
├── recipes_new/          # staging area for generated .docx templates (gitignored)
├── netlify.toml          # tells Netlify to serve . (no build command)
└── README.md             # this file
```
