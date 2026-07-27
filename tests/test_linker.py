import json
from pathlib import Path

from glossary_linker.core.config import EditorialConfig
from glossary_linker.core.linker import collect_manual_occurrences, link_file, save_report_json, save_report_markdown
from glossary_linker.core.models import GlossaryEntry, ProcessingReport


def test_link_file_links_automatic_terms_and_inserts_macro(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        r"""\documentclass{article}
\begin{document}
Accuratezza e accuratezza.
\end{document}
""",
        encoding="utf-8",
    )
    config = EditorialConfig()
    entries = [GlossaryEntry("accuratezza", "Accuratezza")]

    result = link_file(tex, entries, config)

    assert result.automatic_links == 2
    assert r"\providecommand{\glslink}" in result.linked_text
    assert r"https://alittlebyte-19.github.io/Documentazione/glossario.html\#gls-#1" in result.linked_text
    assert r"\underline{#2}\textsuperscript{\scriptsize G}" in result.linked_text
    assert result.linked_text.count(r"\glslink{accuratezza}") == 2


def test_public_links_keep_glossario_html_and_gls_anchor_format(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(r"\begin{document}Accuratezza.\end{document}", encoding="utf-8")
    config = EditorialConfig(
        glossary_html_url="https://alittlebyte-19.github.io/Documentazione/glossario.html",
        html_anchor_format="#gls-{id}",
    )
    entries = [GlossaryEntry("accuratezza", "Accuratezza")]

    result = link_file(tex, entries, config)

    assert r"\href{https://alittlebyte-19.github.io/Documentazione/glossario.html\#gls-#1}" in result.linked_text


def test_link_file_updates_previous_app_managed_macro(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        r"""\documentclass{article}
\providecommand{\glslink}[2]{\href{https://old.test/Glossario.html\#gls-#1}{#2}}
\begin{document}
Accuratezza.
\end{document}
""",
        encoding="utf-8",
    )
    config = EditorialConfig(glossary_html_url="https://docs.example.test/Glossario.html")
    entries = [GlossaryEntry("accuratezza", "Accuratezza")]

    result = link_file(tex, entries, config)

    assert result.linked_text.count(r"\providecommand{\glslink}") == 1
    assert r"https://docs.example.test/Glossario.html\#gls-#1" in result.linked_text
    assert r"\underline{#2}\textsuperscript{\scriptsize G}" in result.linked_text


def test_link_file_ignores_existing_links_and_verbatim(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        r"""\begin{document}
\href{https://example.test}{Accuratezza}
\glslink{accuratezza}{Accuratezza}
\begin{verbatim}
Accuratezza
\end{verbatim}
Accuratezza
\end{document}
""",
        encoding="utf-8",
    )
    config = EditorialConfig(glossary_html_url="https://docs.example.test/Glossario.html")
    entries = [GlossaryEntry("accuratezza", "Accuratezza")]

    result = link_file(tex, entries, config)

    assert result.automatic_links == 1
    assert result.linked_text.count(r"\glslink{accuratezza}") == 2


def test_manual_terms_are_collected_and_require_decision(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(r"\begin{document}Accuratezza.\end{document}", encoding="utf-8")
    config = EditorialConfig(glossary_html_url="https://docs.example.test/Glossario.html")
    entries = [GlossaryEntry("accuratezza", "Accuratezza", mode="manual")]

    occurrences = collect_manual_occurrences([tex], entries, config)
    skipped = link_file(tex, entries, config)
    linked = link_file(tex, entries, config, {occurrences[0].id: True})

    assert len(occurrences) == 1
    assert skipped.manual_links == 0
    assert linked.manual_links == 1


def test_link_file_matches_latex_nonbreaking_spaces(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(r"\begin{document}Analisi~Statica.\end{document}", encoding="utf-8")
    config = EditorialConfig(glossary_html_url="https://docs.example.test/Glossario.html")
    entries = [GlossaryEntry("analisi-statica", "Analisi Statica")]

    result = link_file(tex, entries, config)

    assert result.automatic_links == 1


def test_link_file_matches_case_insensitive_whole_words_only(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        r"""\begin{document}
dai requisiti tecnici, mai dentro altre parole e nemmeno aiuto.
Ai fini del test: AI, "ai", (ai...), [ai].
\end{document}""",
        encoding="utf-8",
    )
    config = EditorialConfig(glossary_html_url="https://docs.example.test/Glossario.html")
    entries = [GlossaryEntry("ai", "AI")]

    result = link_file(tex, entries, config)

    assert result.automatic_links == 5
    assert r"d\glslink{ai}{ai}" not in result.linked_text
    assert r"m\glslink{ai}{ai}" not in result.linked_text
    assert r"\glslink{ai}{ai}uto" not in result.linked_text
    assert r"\glslink{ai}{Ai}" in result.linked_text
    assert r"\glslink{ai}{AI}" in result.linked_text
    assert r'"\glslink{ai}{ai}"' in result.linked_text
    assert r"(\glslink{ai}{ai}...)" in result.linked_text
    assert r"[\glslink{ai}{ai}]" in result.linked_text


def test_link_file_skips_frontmatter_index_and_titles(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        r"""\begin{document}
Accuratezza in copertina.
\newpage
\tableofcontents
Accuratezza nell'indice.
\newpage
\section{Accuratezza nel titolo}
Accuratezza nel corpo.
\end{document}""",
        encoding="utf-8",
    )
    config = EditorialConfig(
        glossary_html_url="https://docs.example.test/Glossario.html",
        ignored_sections=["frontespizio", "indice"],
        ignored_commands=["section"],
    )
    entries = [GlossaryEntry("accuratezza", "Accuratezza")]

    result = link_file(tex, entries, config)

    assert result.automatic_links == 1
    assert r"\glslink{accuratezza}{Accuratezza} in copertina" not in result.linked_text
    assert r"\section{\glslink{accuratezza}{Accuratezza} nel titolo}" not in result.linked_text
    assert r"\glslink{accuratezza}{Accuratezza} nel corpo" in result.linked_text


def test_link_file_skips_frontmatter_without_index_and_chapter_titles(tmp_path: Path):
    tex = tmp_path / "doc.tex"
    tex.write_text(
        r"""\begin{document}
Accuratezza in frontespizio senza indice.
\chapter{Accuratezza nel capitolo}
Accuratezza nel corpo.
\end{document}""",
        encoding="utf-8",
    )
    config = EditorialConfig(
        glossary_html_url="https://docs.example.test/Glossario.html",
        ignored_sections=["frontespizio"],
        ignored_commands=["chapter"],
    )
    entries = [GlossaryEntry("accuratezza", "Accuratezza")]

    result = link_file(tex, entries, config)

    assert result.automatic_links == 1
    assert r"\glslink{accuratezza}{Accuratezza} in frontespizio" not in result.linked_text
    assert r"\chapter{\glslink{accuratezza}{Accuratezza} nel capitolo}" not in result.linked_text
    assert r"\glslink{accuratezza}{Accuratezza} nel corpo" in result.linked_text


def test_saved_reports_do_not_list_missing_term_names(tmp_path: Path):
    report = ProcessingReport(missing_terms=["Termine Assente", "Altro Termine"])
    markdown_path = tmp_path / "report.md"
    json_path = tmp_path / "report.json"

    save_report_markdown(report, markdown_path)
    save_report_json(report, json_path)

    markdown = markdown_path.read_text(encoding="utf-8")
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert "Termini non trovati: 2" in markdown
    assert "Termine Assente" not in markdown
    assert "missing_terms" not in data
    assert data["missing_terms_count"] == 2
