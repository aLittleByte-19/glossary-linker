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
            anchor = glossary_html_anchor(entry.id)
            search_text = " ".join([entry.term, entry.definition, " ".join(entry.aliases), entry.id]).casefold()
            aliases = ""
            if entry.aliases:
                aliases = (
                    '<div class="aliases" aria-label="Alias">'
                    + "".join(f"<span>{escape(alias)}</span>" for alias in entry.aliases)
                    + "</div>"
                )
            items.append(
                f'<article class="entry" id="{escape(anchor)}" data-entry data-entry-id="{escape(entry.id)}" data-search="{escape(search_text)}">'
                '<div class="entry-head">'
                '<div class="entry-title">'
                f"<h3>{escape(entry.term)}</h3>"
                f"{aliases}"
                "</div>"
                f'<button type="button" class="copy-link" data-copy-link="#{escape(anchor)}" aria-label="Copia link a {escape(entry.term)}" title="Copia link">'
                '<span class="copy-icon" aria-hidden="true"></span>'
                '<span class="sr-only">Copia link</span>'
                "</button>"
                "</div>"
                '<div class="entry-body">'
                '<p class="entry-label">Definizione</p>'
                f'<p class="entry-definition">{escape(entry.definition or "Definizione non disponibile.")}</p>'
                "</div>"
                "</article>"
            )
        sections.append(
            f'<section id="letter-{escape(letter)}" class="letter-section">'
            f"<h2>{escape(letter)}</h2>"
            + "\n".join(items)
            + "</section>"
        )

    total_entries = len(entries)
    return f"""<!doctype html>
<html lang="it">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{ color-scheme: light; --primary-blue: #153c5e; --accent-gold: #b38b36; --bg-gray: #f0f4f8; --text-dark: #2b3035; --muted: #6b7785; --line: #dfe7ee; --white: #ffffff; }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-padding-top: 74px; scroll-behavior: smooth; }}
    body {{ margin: 0; color: var(--text-dark); background: var(--bg-gray); font-family: "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; }}
    button {{ font: inherit; }}
    .glossary-navbar {{ position: sticky; top: 0; z-index: 5; background: rgba(255, 255, 255, .97); border-bottom: 3px solid var(--accent-gold); box-shadow: 0 8px 18px rgb(21 60 94 / 8%); backdrop-filter: blur(10px); }}
    .nav-shell {{ display: flex; gap: 24px; align-items: center; justify-content: space-between; width: min(100% - 32px, 1120px); margin: 0 auto; padding: 8px 0; }}
    .brand-title {{ color: var(--primary-blue); font-size: 1.5rem; font-weight: 850; white-space: nowrap; }}
    .glossary-tools {{ display: flex; align-items: center; justify-content: flex-end; width: min(390px, 100%); min-width: 260px; }}
    .search-box {{ width: 100%; min-width: 0; }}
    .search-control {{ position: relative; }}
    .search-control input {{ width: 100%; min-height: 36px; padding: 7px 104px 7px 12px; color: var(--text-dark); font: inherit; border: 1px solid var(--line); border-radius: 6px; }}
    .search-control input:focus {{ border-color: var(--primary-blue); outline: 3px solid rgb(21 60 94 / 14%); }}
    .clear-search {{ position: absolute; top: 50%; right: 6px; display: grid; width: 26px; height: 26px; padding: 0; color: var(--muted); place-items: center; cursor: pointer; background: transparent; border: 0; border-radius: 50%; opacity: 0; transform: translateY(-50%); pointer-events: none; }}
    .clear-search:hover {{ color: var(--primary-blue); background: #eef4f9; }}
    .clear-search.is-visible {{ opacity: 1; pointer-events: auto; }}
    #result-count {{ position: absolute; top: 50%; right: 38px; color: var(--muted); font-size: .82rem; line-height: 1; white-space: nowrap; opacity: 0; transform: translateY(-50%); pointer-events: none; }}
    #result-count.is-visible {{ opacity: 1; }}
    main {{ width: min(100% - 32px, 1040px); margin: 28px auto 48px; padding: 40px; background: var(--white); border-top: 4px solid var(--accent-gold); border-radius: 8px; box-shadow: 0 5px 15px rgb(0 0 0 / 5%); }}
    .glossary-hero {{ max-width: 760px; padding-bottom: 22px; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0 0 10px; padding-bottom: 10px; color: var(--primary-blue); font-size: clamp(2rem, 4vw, 2.7rem); line-height: 1.08; border-bottom: 2px solid var(--bg-gray); }}
    h2 {{ display: inline-block; margin: 34px 0 12px; color: var(--primary-blue); font-size: 1.65rem; }}
    h3 {{ margin: 0; color: var(--primary-blue); font-size: 1.18rem; line-height: 1.25; }}
    p {{ margin: 8px 0 0; }}
    .alphabet-panel {{ margin: 24px 0 28px; padding: 16px; background: #f8fafc; border: 1px solid var(--line); border-radius: 8px; }}
    .alphabet-panel-head {{ display: flex; gap: 12px; align-items: baseline; justify-content: space-between; margin-bottom: 12px; }}
    .alphabet-panel h2 {{ margin: 0; font-size: .92rem; letter-spacing: 0; text-transform: uppercase; }}
    .alphabet-nav {{ display: flex; flex-wrap: wrap; gap: 6px; min-width: 0; }}
    .alphabet-nav a {{ min-width: 34px; padding: 6px 10px; color: var(--primary-blue); font-weight: 700; text-align: center; text-decoration: none; background: #f8fafc; border: 1px solid var(--line); border-radius: 4px; }}
    .alphabet-nav a:hover {{ color: var(--accent-gold); border-color: var(--accent-gold); background: rgba(179, 139, 54, 0.05); }}
    .letter-section h2 {{ display: flex; gap: 12px; align-items: center; width: 100%; margin-top: 30px; }}
    .letter-section h2::after {{ flex: 1; height: 1px; content: ""; background: var(--line); }}
    .entry {{ scroll-margin-top: 104px; margin: 12px 0; overflow: hidden; background: #fbfdff; border: 1px solid var(--line); border-left: 4px solid transparent; border-radius: 8px; box-shadow: 0 2px 8px rgb(21 60 94 / 4%); }}
    .entry:target {{ border-left-color: var(--accent-gold); background: rgba(179, 139, 54, 0.05); }}
    .entry-head {{ display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 16px; align-items: start; padding: 18px 20px 12px; }}
    .entry-title {{ display: grid; gap: 9px; min-width: 0; }}
    .entry-body {{ padding: 0 20px 18px; }}
    .entry-label {{ margin: 0; color: var(--muted); font-size: .74rem; font-weight: 780; text-transform: uppercase; }}
    .entry-definition {{ max-width: 76ch; margin-top: 3px; }}
    .aliases {{ display: flex; flex-wrap: wrap; gap: 6px; }}
    .aliases span {{ display: inline-flex; min-height: 26px; align-items: center; padding: 2px 8px; color: var(--primary-blue); font-size: .86rem; font-weight: 700; background: #eef4f9; border: 1px solid var(--line); border-radius: 999px; }}
    .copy-link {{ display: grid; width: 34px; height: 34px; padding: 0; color: var(--primary-blue); place-items: center; cursor: pointer; background: var(--white); border: 1px solid var(--line); border-radius: 6px; }}
    .copy-link:hover, .copy-link.is-copied {{ border-color: var(--accent-gold); background: rgba(179, 139, 54, 0.06); }}
    .copy-icon {{ position: relative; display: block; width: 16px; height: 16px; }}
    .copy-icon::before, .copy-icon::after {{ position: absolute; width: 10px; height: 12px; content: ""; border: 1.8px solid currentColor; border-radius: 3px; }}
    .copy-icon::before {{ top: 1px; left: 1px; opacity: .55; }}
    .copy-icon::after {{ top: 4px; left: 5px; background: var(--white); }}
    .empty-results {{ margin: 18px 0 0; padding: 14px 16px; color: var(--muted); background: #f8fafc; border: 1px dashed var(--line); border-radius: 8px; }}
    .back-to-top {{ position: fixed; right: 24px; bottom: 24px; z-index: 6; display: grid; width: 44px; height: 44px; color: var(--white); place-items: center; cursor: pointer; background: var(--primary-blue); border: 1px solid rgb(255 255 255 / 45%); border-radius: 50%; box-shadow: 0 8px 20px rgb(21 60 94 / 20%); opacity: 0; transform: translateY(8px); transition: opacity 140ms ease, transform 140ms ease; pointer-events: none; }}
    .back-to-top.is-visible {{ opacity: 1; transform: translateY(0); pointer-events: auto; }}
    .sr-only {{ position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; white-space: nowrap; border: 0; clip: rect(0, 0, 0, 0); }}
    .is-hidden {{ display: none !important; }}
    @media (max-width: 760px) {{ html {{ scroll-padding-top: 116px; }} .nav-shell {{ width: min(100% - 20px, 1120px); flex-direction: column; gap: 8px; align-items: stretch; }} .glossary-tools {{ align-items: stretch; width: 100%; min-width: 0; }} main {{ width: min(100% - 20px, 1040px); margin: 20px auto; padding: 24px; }} .entry-head {{ grid-template-columns: 1fr; }} .copy-link {{ justify-self: start; }} }}
  </style>
</head>
<body>
  <header class="glossary-navbar">
    <div class="nav-shell">
      <div class="brand-title">aLittleByte - Glossario</div>
      <div class="glossary-tools">
        <div class="search-box">
          <div class="search-control">
            <input id="glossary-search" type="search" placeholder="Termine, alias o definizione" autocomplete="off" aria-label="Cerca nel glossario">
            <output id="result-count" for="glossary-search"></output>
            <button id="clear-search" class="clear-search" type="button" aria-label="Cancella ricerca">&times;</button>
          </div>
        </div>
      </div>
    </div>
  </header>
  <main>
    <div class="glossary-hero">
      <h1>{escape(title)}</h1>
      <p>Versione HTML navigabile del glossario con sezioni alfabetiche e anchor stabili per ogni voce.</p>
    </div>
    <section class="alphabet-panel" aria-labelledby="alphabet-title">
      <div class="alphabet-panel-head">
        <h2 id="alphabet-title">Indice alfabetico</h2>
      </div>
      <nav class="alphabet-nav" aria-label="Indice alfabetico">
        {''.join(toc)}
      </nav>
    </section>
    <p id="empty-results" class="empty-results is-hidden">Nessuna voce corrisponde alla ricerca.</p>
    {''.join(sections)}
  </main>
  <button id="back-to-top" class="back-to-top" type="button" aria-label="Torna su">&#8593;</button>
  <script>
    const search = document.getElementById("glossary-search");
    const clearSearch = document.getElementById("clear-search");
    const resultCount = document.getElementById("result-count");
    const emptyResults = document.getElementById("empty-results");
    const backToTop = document.getElementById("back-to-top");
    const entries = [...document.querySelectorAll("[data-entry]")];
    function updateSearch() {{
      const query = search.value.trim().toLowerCase();
      let visibleCount = 0;
      entries.forEach((entry) => {{
        const visible = !query || entry.dataset.search.includes(query);
        entry.classList.toggle("is-hidden", !visible);
        if (visible) visibleCount += 1;
      }});
      document.querySelectorAll(".letter-section").forEach((section) => {{
        const visible = section.querySelector("[data-entry]:not(.is-hidden)");
        section.classList.toggle("is-hidden", Boolean(query) && !visible);
      }});
      if (resultCount) {{
        resultCount.value = `${{visibleCount}}/{total_entries}`;
        resultCount.classList.toggle("is-visible", Boolean(query));
      }}
      clearSearch?.classList.toggle("is-visible", Boolean(query));
      emptyResults?.classList.toggle("is-hidden", visibleCount !== 0);
    }}
    search?.addEventListener("input", updateSearch);
    clearSearch?.addEventListener("click", () => {{
      search.value = "";
      updateSearch();
      search.focus();
    }});
    document.querySelectorAll("[data-copy-link]").forEach((button) => {{
      const originalLabel = button.getAttribute("aria-label") || "Copia link";
      button.addEventListener("click", async () => {{
        const target = button.dataset.copyLink;
        const base = window.location.href.split("#")[0];
        const url = `${{base}}${{target}}`;
        try {{
          await navigator.clipboard.writeText(url);
          button.classList.add("is-copied");
          button.setAttribute("aria-label", "Link copiato");
          window.setTimeout(() => {{
            button.classList.remove("is-copied");
            button.setAttribute("aria-label", originalLabel);
          }}, 1200);
        }} catch {{
          window.location.hash = target;
        }}
      }});
    }});
    window.addEventListener("scroll", () => {{
      backToTop?.classList.toggle("is-visible", window.scrollY > 420);
    }}, {{ passive: true }});
    backToTop?.addEventListener("click", () => {{
      window.scrollTo({{ top: 0, behavior: "smooth" }});
    }});
    updateSearch();
  </script>
</body>
</html>
"""


def save_glossary_html(entries: list[GlossaryEntry], path: Path, title: str = "Glossario") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_glossary_html(entries, title), encoding="utf-8")
