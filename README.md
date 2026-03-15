# Judy's Kitchen — Cookbook Website

Live site: https://judyscookbook.netlify.app

## How it works

Recipes are stored as plain `.txt` files in `recipes/<Category>/`. The `build.py` script reads them all and generates `index.html`. Netlify runs the build automatically on every push to GitHub.

## Updating a recipe

1. Open the `.txt` file in `recipes/<Category>/RecipeName.txt`
2. Edit it (see format below)
3. Run `python3 build.py` to preview locally — open `index.html` in your browser
4. Commit and push → Netlify redeploys automatically

## Adding a new recipe

1. Create a new `.txt` file in the right category folder, e.g. `recipes/Chicken/Roast Chicken.txt`
2. Use the format below
3. Run `python3 build.py`, then commit and push

## Recipe file format

```
# Recipe Name

From: Source   Prep: 30 min   Yield: 4 servings

INGREDIENTS

- 1 cup flour
- 2 eggs
- pinch of salt

INSTRUCTIONS

Mix the dry ingredients together in a bowl.

Add eggs and stir until combined.

Bake at 350°F for 30 minutes.
```

**Notes:**
- The `# Title` line at the top is the recipe name (should match the filename)
- Lines before `INGREDIENTS` appear as info tags on the recipe page
- Ingredient lines should start with `- `
- Separate instruction steps with a blank line
- Anything after `INSTRUCTIONS` that isn't a blank line becomes a numbered step

## Adding a new category

1. Create a new folder under `recipes/`, e.g. `recipes/Desserts/`
2. Add recipe `.txt` files to it
3. Optionally add an icon and description in `build.py` under `CATEGORY_ICONS` and `CATEGORY_DESCRIPTIONS`
4. Run `python3 build.py`, commit, push

## Local preview

```bash
python3 build.py
open index.html
```

## Deploying

Just push to GitHub — Netlify handles the rest.

```bash
git add .
git commit -m "Update recipes"
git push
```
