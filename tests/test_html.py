from glossary_linker.core.html import render_glossary_html
from glossary_linker.core.models import GlossaryEntry


def test_render_glossary_html_keeps_section_anchors_and_adds_tools():
    html = render_glossary_html([
        GlossaryEntry("accuratezza", "Accuratezza", "Definizione.", aliases=["precisione"], mode="manual"),
    ])

    assert 'id="gls-accuratezza"' in html
    assert 'href="#letter-A"' in html
    assert 'class="glossary-tools"' in html
    assert 'id="glossary-search"' in html
    assert 'id="result-count"' in html
    assert 'id="clear-search"' in html
    assert 'data-copy-link="#gls-accuratezza"' in html
    assert 'class="copy-icon"' in html
    assert 'id="back-to-top"' in html
    assert "aLittleByte - Glossario" in html
    assert "Pulisci" not in html
    assert "<label" not in html
    assert 'aria-label="Cerca nel glossario"' in html
    assert "<output id=\"result-count\" for=\"glossary-search\"></output>" in html
    assert 'resultCount.classList.toggle("is-visible", Boolean(query));' in html
    assert "Termine, alias o definizione" in html
    assert 'class="entry-id"' not in html
    assert "Manuale" not in html
    assert "Automatico" not in html
    assert "mode-badge" not in html
    assert ".search-box {{ position: fixed" not in html
