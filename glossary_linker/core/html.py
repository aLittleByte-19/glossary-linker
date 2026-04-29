from __future__ import annotations

from html import escape
from pathlib import Path

from .models import GlossaryEntry


def glossary_html_anchor(entry_id: str) -> str:
    return f"gls-{entry_id}"


def render_glossary_html(entries: list[GlossaryEntry], title: str = "Glossario") -> str:
    grouped: dict[str, list[GlossaryEntry]] = {}
    for entry in sorted(entries, key=lambda item: item.term.casefold()):
        letter = (entry.term[:1] or "#").upper()
        if not letter.isalpha():
            letter = "#"
        grouped.setdefault(letter, []).append(entry)

    sections: list[str] = []
    toc = []
    for letter, letter_entries in grouped.items():
        toc.append(f'<a href="#letter-{escape(letter)}">{escape(letter)}</a>')
        items = []
        for entry in letter_entries:
            aliases = ""
            if entry.aliases:
                aliases = (
                    '<p class="aliases"><span>Alias:</span> '
                    + escape(", ".join(entry.aliases))
                    + "</p>"
                )
            items.append(
                f'<article class="entry" id="{escape(glossary_html_anchor(entry.id))}">'
                f"<h3>{escape(entry.term)}</h3>"
                f'<p class="entry-id">{escape(entry.id)}</p>'
                f"<p>{escape(entry.definition or 'Definizione non disponibile.')}</p>"
                f"{aliases}"
                "</article>"
            )
        sections.append(
            f'<section id="letter-{escape(letter)}" class="letter-section">'
            f"<h2>{escape(letter)}</h2>"
            + "\n".join(items)
            + "</section>"
        )

    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --ink: #1f1f1f; --muted: #666; --line: #ddd; --bg: #f6f6f4; --surface: #fff; }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-padding-top: 24px; }}
    body {{ margin: 0; color: var(--ink); background: var(--bg); font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; line-height: 1.55; }}
    main {{ width: min(100% - 32px, 980px); margin: 32px auto; padding: 28px; background: var(--surface); border: 1px solid var(--line); border-radius: 10px; }}
    h1 {{ margin: 0 0 8px; font-size: clamp(2rem, 4vw, 3rem); line-height: 1.05; }}
    h2 {{ margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 1px solid var(--line); }}
    h3 {{ margin: 0; font-size: 1.1rem; }}
    p {{ margin: 8px 0 0; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 22px 0 10px; }}
    nav a {{ min-width: 34px; padding: 6px 10px; color: var(--ink); text-align: center; text-decoration: none; background: #f2f2f0; border: 1px solid var(--line); border-radius: 7px; }}
    .entry {{ scroll-margin-top: 24px; padding: 14px 0; border-bottom: 1px solid var(--line); }}
    .entry-id, .aliases {{ color: var(--muted); font-size: 0.92rem; }}
    .aliases span {{ font-weight: 750; }}
  </style>
</head>
<body>
  <main>
    <h1>{escape(title)}</h1>
    <p>Versione HTML navigabile del glossario con anchor stabili per ogni voce.</p>
    <nav aria-label="Indice alfabetico">
      {''.join(toc)}
    </nav>
    {''.join(sections)}
  </main>
</body>
</html>
"""


def save_glossary_html(entries: list[GlossaryEntry], path: Path, title: str = "Glossario") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_glossary_html(entries, title), encoding="utf-8")
