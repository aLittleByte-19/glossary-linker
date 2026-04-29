from pathlib import Path
import re

import pytest

from glossary_linker.core.config import EditorialConfig
from glossary_linker.core.formatter import format_glossary_text
from glossary_linker.core.glossary import merge_detected_with_store, parse_glossary_file, parse_glossary_text
from glossary_linker.core.html import render_glossary_html
from glossary_linker.core.linker import link_file


VENDOR = Path("vendor")
GLOSSARY_TEX = VENDOR / "documentazione-glossario" / "RTB" / "Glossario" / "Glossario.tex"
GLOSSARY_PDF = GLOSSARY_TEX.with_suffix(".pdf")
SOURCE_DOCS = [
    VENDOR / "documentazione-source" / "candidatura" / "analisi capitolati" / "Analisi dei Capitolati.tex",
    VENDOR / "documentazione-source" / "candidatura" / "verbali" / "Verbali Esterni" / "Verbale_Esterno_2026-03-11.tex",
    VENDOR / "documentazione-source" / "RTB" / "Verbali" / "Verbali Esterni" / "Verbale_Esterno_2026_04_20.tex",
]
LOCAL_GLOSSARY_URL = "http://127.0.0.1:8765/glossary-html"
PAGES_GLOSSARY_URL = "https://alittlebyte-19.github.io/Documentazione/RTB/Glossario/Glossario.html"
LINK_RE = re.compile(r"\\glslink\{([^{}]+)\}\{")


pytestmark = pytest.mark.skipif(
    not GLOSSARY_TEX.exists() or not all(path.exists() for path in SOURCE_DOCS),
    reason="Vendor documentation fixtures are not available.",
)


def test_vendor_glossary_is_parsed_and_formatter_generates_pdf_anchors():
    config = EditorialConfig(
        glossary_detection="auto",
    )
    entries = parse_glossary_file(GLOSSARY_TEX, config)
    original = GLOSSARY_TEX.read_text(encoding="utf-8")
    formatted = format_glossary_text(original)
    without_macro = original.replace(
        r"\providecommand{\glossaryentry}[2]{\subsection{#2}\label{gls:#1}}",
        "",
    )
    formatted_without_macro = format_glossary_text(without_macro)

    assert len(entries) >= 90
    assert {"capitolato", "dashboard-amministrativa", "llm-large-language-model"} <= {entry.id for entry in entries}
    assert r"\hypertarget{gls:#1}" in formatted
    assert r"\hypertarget{gls:#1}" in formatted_without_macro

    html = render_glossary_html(entries)
    assert 'id="gls-capitolato"' in html
    assert 'id="gls-metadati-documento"' in html


def test_vendor_documents_link_only_existing_glossary_entries():
    config = EditorialConfig(
        glossary_path=str(GLOSSARY_TEX),
        glossary_link_target="pdf",
        glossary_pdf_url=str(GLOSSARY_PDF.resolve()),
        anchor_format="#nameddest=gls:{id}",
        glossary_detection="auto",
    )
    entries = parse_glossary_file(GLOSSARY_TEX, config)
    entry_ids = {entry.id for entry in entries}
    formatted_glossary = format_glossary_text(GLOSSARY_TEX.read_text(encoding="utf-8"))

    linked_ids: set[str] = set()
    for source in SOURCE_DOCS:
        result = link_file(source, entries, config)
        document_ids = set(LINK_RE.findall(result.linked_text))
        assert document_ids, f"Nessun link generato o presente in {source}"
        assert document_ids <= entry_ids
        linked_ids.update(document_ids)

    assert {"capitolato", "dashboard-amministrativa", "llm-large-language-model", "ai-intelligenza-artificiale"} <= linked_ids
    for entry_id in linked_ids:
        assert rf"\glossaryentry{{{entry_id}}}" in formatted_glossary


def test_vendor_document_links_are_ready_for_generated_html_local_and_pages_url():
    entries = parse_glossary_file(GLOSSARY_TEX, EditorialConfig(glossary_detection="auto"))
    source = SOURCE_DOCS[0]

    for html_url in (LOCAL_GLOSSARY_URL, PAGES_GLOSSARY_URL):
        config = EditorialConfig(
            glossary_path=str(GLOSSARY_TEX),
            glossary_html_url=html_url,
            html_anchor_format="#gls-{id}",
            glossary_detection="auto",
        )
        result = link_file(source, entries, config)

        assert rf"\href{{{html_url}\#gls-#1}}" in result.linked_text
        assert r"\underline{#2}\textsuperscript{\scriptsize G}" in result.linked_text


def test_vendor_document_links_have_matching_generated_html_anchors(tmp_path: Path):
    entries = parse_glossary_file(GLOSSARY_TEX, EditorialConfig(glossary_detection="auto"))
    source = SOURCE_DOCS[0]
    local_html = tmp_path / "Glossario.html"
    local_html.write_text(render_glossary_html(entries), encoding="utf-8")
    generated_html = local_html.read_text(encoding="utf-8")

    for html_url in (LOCAL_GLOSSARY_URL, PAGES_GLOSSARY_URL):
        config = EditorialConfig(
            glossary_path=str(GLOSSARY_TEX),
            glossary_html_url=html_url,
            html_anchor_format="#gls-{id}",
            glossary_detection="auto",
        )
        result = link_file(source, entries, config)
        linked_ids = set(LINK_RE.findall(result.linked_text))

        assert rf"\href{{{html_url}\#gls-#1}}" in result.linked_text
        assert r"\glslink{metadati-documento}{documento}" in result.linked_text
        for entry_id in linked_ids:
            assert f'id="gls-{entry_id}"' in generated_html


def test_new_glossary_entries_are_detected_and_linked_in_already_linked_documents(tmp_path: Path):
    base_text = GLOSSARY_TEX.read_text(encoding="utf-8")
    updated_text = base_text.replace(
        r"\end{document}",
        "\n\\glossaryentry{nuova-entry-test}{Nuova Entry Test}\nDefinizione di prova.\n\n\\end{document}",
    )
    config = EditorialConfig(
        glossary_path=str(GLOSSARY_TEX),
        glossary_html_url=LOCAL_GLOSSARY_URL,
        html_anchor_format="#gls-{id}",
        glossary_detection="auto",
    )
    stored_entries = parse_glossary_text(base_text, config)
    detected_entries = parse_glossary_text(updated_text, config)
    merged, new_count = merge_detected_with_store(detected_entries, stored_entries)
    new_ids = {entry.id for entry in merged} - {entry.id for entry in stored_entries}
    new_entries = [entry for entry in merged if entry.id in new_ids]

    assert new_count == 1
    assert [entry.id for entry in new_entries] == ["nuova-entry-test"]

    already_linked = tmp_path / "gia_linkato.tex"
    already_linked.write_text(
        r"""\documentclass{article}
\providecommand{\glslink}[2]{\href{Glossario.pdf\#nameddest=gls:#1}{#2\textsuperscript{\scriptsize G}}}
\begin{document}
Un \glslink{capitolato}{capitolato} gia collegato. Nuova Entry Test da collegare.
\end{document}
""",
        encoding="utf-8",
    )

    result = link_file(already_linked, new_entries, config)

    assert result.linked_text.count(r"\glslink{capitolato}{capitolato}") == 1
    assert r"\glslink{nuova-entry-test}{Nuova Entry Test}" in result.linked_text
    assert r"\glslink{nuova-entry-test}{\glslink" not in result.linked_text
