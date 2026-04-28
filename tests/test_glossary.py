from glossary_linker.core.config import EditorialConfig
from glossary_linker.core.formatter import format_glossary_text
from glossary_linker.core.glossary import parse_glossary_text


def test_parse_subsection_entries():
    text = r"""
\subsection{Accuratezza}
Misura quanto una previsione e corretta.

\subsection{Overfitting}
Adattamento eccessivo ai dati.
"""
    entries = parse_glossary_text(text)

    assert [entry.id for entry in entries] == ["accuratezza", "overfitting"]
    assert entries[0].term == "Accuratezza"
    assert "previsione" in entries[0].definition


def test_parse_structured_entries_with_config():
    config = EditorialConfig(entries={"accuratezza": {"mode": "manual", "aliases": ["accuracy"]}})
    entries = parse_glossary_text(r"\glossaryentry{accuratezza}{Accuratezza} Definizione.", config)

    assert entries[0].id == "accuratezza"
    assert entries[0].mode == "manual"
    assert entries[0].aliases == ["accuracy"]


def test_format_glossary_converts_subsections_to_structured_entries():
    formatted = format_glossary_text(r"\begin{document}\subsection{Accuratezza}Testo\end{document}")

    assert r"\providecommand{\glossaryentry}" in formatted
    assert r"\glossaryentry{accuratezza}{Accuratezza}" in formatted


def test_parenthetical_terms_get_useful_aliases():
    entries = parse_glossary_text(r"\subsection{Branch (Ramo)} Definizione.")

    assert entries[0].term == "Branch (Ramo)"
    assert "Branch" in entries[0].aliases
    assert "Ramo" in entries[0].aliases
