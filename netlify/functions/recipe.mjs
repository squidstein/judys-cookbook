// Add or edit a recipe in the Notion "Recipes" database, then trigger a site rebuild.
//
// Netlify environment variables (Site configuration → Environment variables):
//   NOTION_TOKEN     – the Notion integration token (same one build.py uses)
//   RECIPE_PASSWORD  – the shared family password
//   BUILD_HOOK_URL   – a Netlify build hook, so saves go live automatically
import crypto from "node:crypto";

const NOTION = "https://api.notion.com/v1";
const DB_ID = (process.env.NOTION_DB_ID || "324eef28a6748022b6c1e63b297bd8f5").replace(/-/g, "");

const notionHeaders = () => ({
  Authorization: `Bearer ${process.env.NOTION_TOKEN}`,
  "Notion-Version": "2022-06-28",
  "Content-Type": "application/json",
});
const reply = (status, body) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function passwordOk(given) {
  const want = process.env.RECIPE_PASSWORD || "";
  if (!want) return false;
  const a = crypto.createHash("sha256").update(String(given || "")).digest();
  const b = crypto.createHash("sha256").update(want).digest();
  return crypto.timingSafeEqual(a, b);
}

// Notion caps each text chunk at 2,000 characters
const richText = (value, max = 20000) => {
  const s = String(value || "").slice(0, max);
  const out = [];
  for (let i = 0; i < s.length; i += 2000) out.push({ type: "text", text: { content: s.slice(i, i + 2000) } });
  return out;
};
const select = (v) => ({ select: v ? { name: String(v).replace(/,/g, " ").slice(0, 100) } : null });

export default async (req) => {
  if (req.method !== "POST") return reply(405, { error: "Use POST." });
  let body;
  try { body = await req.json(); } catch { return reply(400, { error: "Bad request." }); }

  if (!passwordOk(body.password)) {
    await new Promise((r) => setTimeout(r, 800)); // slow down guessing
    return reply(401, { error: "That password didn't work." });
  }
  if (!process.env.NOTION_TOKEN) return reply(500, { error: "The site isn't connected to Notion yet." });

  const f = body.fields || {};
  const name = String(f.name || "").trim();
  if (!name || !f.folder) return reply(400, { error: "A name and a category are required." });

  const properties = {
    Name: { title: richText(name, 200) },
    Folder: select(f.folder),
    Cuisine: select(f.cuisine),
    Kashrut: select(f.kashrut),
    Tradition: select(f.tradition),
    "Vegan Option?": { checkbox: !!f.vegan_option },
    Description: { rich_text: richText(f.description) },
    Ingredients: { rich_text: richText(f.ingredients) },
    "Preparation Steps": { rich_text: richText(f.steps) },
    "Chef's Notes": { rich_text: richText(f.notes) },
    From: { rich_text: richText(f.from, 300) },
    "Preparation Time": { rich_text: richText(f.prep_time, 100) },
    "Cook Time": { rich_text: richText(f.cook_time, 100) },
    Yields: { rich_text: richText(f.yields, 100) },
  };

  let res;
  if (body.id) {
    const id = String(body.id);
    if (!/^[0-9a-f-]{32,36}$/i.test(id)) return reply(400, { error: "Unknown recipe." });
    // Only allow editing pages that belong to the Recipes database
    const existing = await fetch(`${NOTION}/pages/${id}`, { headers: notionHeaders() });
    const page = existing.ok ? await existing.json() : null;
    if (!page || (page.parent?.database_id || "").replace(/-/g, "") !== DB_ID) {
      return reply(404, { error: "That recipe couldn't be found." });
    }
    res = await fetch(`${NOTION}/pages/${id}`, {
      method: "PATCH", headers: notionHeaders(), body: JSON.stringify({ properties }),
    });
  } else {
    res = await fetch(`${NOTION}/pages`, {
      method: "POST", headers: notionHeaders(),
      body: JSON.stringify({ parent: { database_id: DB_ID }, properties }),
    });
  }
  if (!res.ok) {
    console.error("Notion error", res.status, await res.text());
    return reply(502, { error: "The recipe couldn't be saved. Try again in a minute." });
  }
  const saved = await res.json();

  if (process.env.BUILD_HOOK_URL) {
    try { await fetch(process.env.BUILD_HOOK_URL, { method: "POST" }); }
    catch (e) { console.error("Build hook failed", e); }
  }
  return reply(200, { ok: true, id: saved.id });
};
