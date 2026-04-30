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
            search_text = " ".join([entry.term, entry.definition, " ".join(entry.aliases), entry.id]).casefold()
            aliases = ""
            if entry.aliases:
                aliases = (
                    '<p class="aliases"><span>Alias:</span> '
                    + escape(", ".join(entry.aliases))
                    + "</p>"
                )
            items.append(
                f'<article class="entry" id="{escape(glossary_html_anchor(entry.id))}" data-entry data-search="{escape(search_text)}">'
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
    :root {{ color-scheme: light; --primary-blue: #153c5e; --accent-gold: #b38b36; --bg-gray: #f0f4f8; --text-dark: #2b3035; --muted: #6b7785; --line: #dfe7ee; --white: #ffffff; }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-padding-top: 92px; }}
    body {{ margin: 0; color: var(--text-dark); background: var(--bg-gray); font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; }}
    main {{ width: min(100% - 32px, 980px); margin: 40px auto; padding: 40px; background: var(--white); border-top: 4px solid var(--accent-gold); border-radius: 8px; box-shadow: 0 5px 15px rgb(0 0 0 / 5%); }}
    .glossary-header {{ display: block; max-width: 680px; }}
    .search-box {{ position: fixed; top: 20px; right: 20px; z-index: 5; display: grid; gap: 6px; width: min(340px, calc(100vw - 40px)); padding: 10px; background: rgba(255,255,255,.97); border: 1px solid var(--line); border-radius: 6px; box-shadow: 0 8px 24px rgb(0 0 0 / 8%); }}
    .search-box label {{ color: var(--muted); font-size: .78rem; font-weight: 700; text-transform: uppercase; }}
    .search-box input {{ width: 100%; min-height: 38px; padding: 8px 10px; color: var(--text-dark); font: inherit; border: 1px solid var(--line); border-radius: 4px; }}
    h1 {{ margin: 0 0 10px; padding-bottom: 10px; color: var(--primary-blue); font-size: clamp(2rem, 4vw, 2.7rem); line-height: 1.08; border-bottom: 2px solid var(--bg-gray); }}
    h2 {{ display: inline-block; margin: 34px 0 12px; color: var(--primary-blue); font-size: 1.65rem; }}
    h3 {{ margin: 0; color: var(--primary-blue); font-size: 1.14rem; }}
    p {{ margin: 8px 0 0; }}
    nav {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 22px 0 10px; }}
    nav a {{ min-width: 34px; padding: 6px 10px; color: var(--primary-blue); font-weight: 700; text-align: center; text-decoration: none; background: #f8fafc; border: 1px solid var(--line); border-radius: 4px; }}
    nav a:hover {{ color: var(--accent-gold); border-color: var(--accent-gold); background: rgba(179, 139, 54, 0.05); }}
    .entry {{ scroll-margin-top: 92px; margin: 8px 0; padding: 16px 18px; background: #fbfdff; border: 1px solid var(--line); border-left: 3px solid transparent; border-radius: 6px; }}
    .entry:target {{ border-left-color: var(--accent-gold); background: rgba(179, 139, 54, 0.05); }}
    .entry-id, .aliases {{ color: var(--muted); font-size: 0.92rem; }}
    .aliases span {{ font-weight: 750; }}
    .is-hidden {{ display: none; }}
    @media (max-width: 760px) {{ main {{ width: min(100% - 20px, 980px); margin: 96px auto 20px; padding: 24px; }} .search-box {{ top: 8px; right: 10px; width: calc(100vw - 20px); }} }}
  </style>
</head>
<body>
  <main>
    <div class="glossary-header">
      <div>
        <h1>{escape(title)}</h1>
        <p>Versione HTML navigabile del glossario con anchor stabili per ogni voce.</p>
      </div>
      <div class="search-box">
        <label for="glossary-search">Cerca nel glossario</label>
        <input id="glossary-search" type="search" placeholder="Termine, alias, definizione">
      </div>
    </div>
    <nav aria-label="Indice alfabetico">
      {''.join(toc)}
    </nav>
    {''.join(sections)}
  </main>
  <script>
    const search = document.getElementById("glossary-search");
    const entries = [...document.querySelectorAll("[data-entry]")];
    search?.addEventListener("input", () => {{
      const query = search.value.trim().toLowerCase();
      entries.forEach((entry) => {{
        entry.classList.toggle("is-hidden", query && !entry.dataset.search.includes(query));
      }});
      document.querySelectorAll(".letter-section").forEach((section) => {{
        const visible = section.querySelector("[data-entry]:not(.is-hidden)");
        section.classList.toggle("is-hidden", Boolean(query) && !visible);
      }});
    }});
  </script>
</body>
</html>
"""


def save_glossary_html(entries: list[GlossaryEntry], path: Path, title: str = "Glossario") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_glossary_html(entries, title), encoding="utf-8")
