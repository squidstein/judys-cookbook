"""
Generates a blank Google Docs-friendly recipe template (.docx) that mirrors
the Notion "Recipes" database fields. Family fills it out, sends it back,
and the fields drop straight into Notion.
"""

from docx import Document
from docx.shared import Pt, RGBColor, Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH

OUT = "Recipe Template.docx"

CATEGORIES = [
    "Appetizers", "Chicken", "Fish", "Meat", "Soups & Stews",
    "Salads & Vegetables", "Potatoes & Pasta", "Muffins & Breads",
    "Cookies & Cakes", "Passover", "Special",
]
KASHRUT = ["Meat", "Dairy", "Pareve"]
CUISINES = ["Sephardi", "Ashkenazi", "Other"]


def add_label(doc, label, hint=None):
    p = doc.add_paragraph()
    run = p.add_run(label)
    run.bold = True
    if hint:
        h = p.add_run(f"  ({hint})")
        h.italic = True
        h.font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    p.paragraph_format.space_after = Pt(2)
    val = doc.add_paragraph("")
    val.paragraph_format.space_after = Pt(10)


def add_section(doc, heading, instructions=None):
    h = doc.add_paragraph(heading)
    h.style = doc.styles["Heading 1"]
    if instructions:
        i = doc.add_paragraph(instructions)
        i.runs[0].italic = True
        i.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    doc.add_paragraph("")


def main():
    doc = Document()

    for section in doc.sections:
        section.top_margin = Inches(0.8)
        section.bottom_margin = Inches(0.8)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)

    title = doc.add_paragraph("Recipe Name Goes Here")
    title.style = doc.styles["Title"]
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER

    intro = doc.add_paragraph(
        "Fill in the fields below. Skip anything you don't know, "
        "leave it blank and we'll figure it out. When you're done, "
        "share the doc back or email it."
    )
    intro.runs[0].italic = True
    intro.runs[0].font.color.rgb = RGBColor(0x80, 0x80, 0x80)
    intro.alignment = WD_ALIGN_PARAGRAPH.CENTER

    doc.add_paragraph("")

    # ── The basics ────────────────────────────────────────────────
    h = doc.add_paragraph("The basics")
    h.style = doc.styles["Heading 1"]

    add_label(doc, "Folder", f"pick one: {', '.join(CATEGORIES)}")
    add_label(doc, "Kashrut", f"pick one: {', '.join(KASHRUT)}")
    add_label(doc, "Cuisine", f"pick one: {', '.join(CUISINES)}")
    add_label(doc, "From", "who gave you this recipe? e.g. Aunt Sarah, NYT Cooking")
    add_label(doc, "Yields", "how many it serves, e.g. 6 servings, 12 cookies")
    add_label(doc, "Preparation Time", "e.g. 20 min")
    add_label(doc, "Cook Time", "e.g. 1 hour")

    # ── Description ───────────────────────────────────────────────
    add_section(
        doc,
        "Description",
        "A sentence or two about the dish. When do you make it? What's special about it?",
    )

    # ── Ingredients ───────────────────────────────────────────────
    add_section(
        doc,
        "Ingredients",
        "One ingredient per line, with quantities. e.g. 2 cups flour",
    )
    doc.add_paragraph("")
    doc.add_paragraph("")
    doc.add_paragraph("")

    # ── Preparation Steps ─────────────────────────────────────────
    add_section(
        doc,
        "Preparation Steps",
        "Number the steps 1, 2, 3... one step per line.",
    )
    doc.add_paragraph("")
    doc.add_paragraph("")
    doc.add_paragraph("")

    # ── Chef's Notes ──────────────────────────────────────────────
    add_section(
        doc,
        "Chef's Notes",
        "Storage tips, substitutions, what to serve it with, anything you want to remember.",
    )
    doc.add_paragraph("Storage: ")
    doc.add_paragraph("Substitutions: ")
    doc.add_paragraph("Can you freeze it: ")
    doc.add_paragraph("Other notes: ")

    doc.save(OUT)
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
