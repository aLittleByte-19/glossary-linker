from glossary_linker.core.config import EditorialConfig
from glossary_linker.core.formatter import format_glossary_text
from glossary_linker.core.glossary import merge_detected_with_store, parse_glossary_text
from glossary_linker.core.models import GlossaryEntry


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


def test_auto_detection_prefers_structured_entries_and_ignores_macro_body():
    text = r"""
\providecommand{\glossaryentry}[2]{%
  \subsection{#2}
  \label{gls:#1}
}
\begin{document}
\glossaryentry{agile-scrum}{Agile SCRUM}
Il metodo di lavoro usato dal team.
\end{document}
"""
    entries = parse_glossary_text(text, EditorialConfig(glossary_detection="auto"))

    assert [entry.id for entry in entries] == ["agile-scrum"]
    assert entries[0].term == "Agile SCRUM"
    assert "#2" not in [entry.term for entry in entries]


def test_detection_mode_can_force_subsection_entries():
    text = r"""
\begin{document}
\subsection{Accuratezza}
Misura quanto una previsione e corretta.
\end{document}
"""
    entries = parse_glossary_text(text, EditorialConfig(glossary_detection="subsection"))

    assert [entry.term for entry in entries] == ["Accuratezza"]


def test_excluded_detected_entries_are_filtered_by_config():
    text = r"\subsection{Voce Errata} Testo."
    entries = parse_glossary_text(text, EditorialConfig(glossary_detection="subsection", excluded_entry_ids=["voce-errata"]))

    assert entries == []


def test_merge_detected_entries_drops_stale_stored_terms():
    detected = [parse_glossary_text(r"\subsection{Voce Corretta} Testo.")[0]]
    stored = [
        GlossaryEntry("voce-corretta", "Voce Corretta", aliases=["alias"], mode="manual"),
        GlossaryEntry("voce-vecchia", "Voce Vecchia"),
    ]

    merged, new_count = merge_detected_with_store(detected, stored)

    assert [entry.id for entry in merged] == ["voce-corretta"]
    assert merged[0].mode == "manual"
    assert merged[0].aliases == ["alias"]
    assert new_count == 0


def test_format_glossary_converts_subsections_to_structured_entries():
    formatted = format_glossary_text(r"\begin{document}\subsection{Accuratezza}Testo\end{document}")

    assert r"\providecommand{\glossaryentry}" in formatted
    assert r"\glossaryentry{accuratezza}{Accuratezza}" in formatted


def test_format_glossary_does_not_rewrite_glossaryentry_macro_body():
    text = r"""\providecommand{\glossaryentry}[2]{\subsection{#2}\label{gls:#1}}
\begin{document}
\glossaryentry{accuratezza}{Accuratezza}
\end{document}"""

    formatted = format_glossary_text(text)

    assert r"\glossaryentry{2}{#2}" not in formatted
    assert r"\subsection{#2}" in formatted


def test_parenthetical_terms_get_useful_aliases():
    entries = parse_glossary_text(r"\subsection{Branch (Ramo)} Definizione.")

    assert entries[0].term == "Branch (Ramo)"
    assert "Branch" in entries[0].aliases
    assert "Ramo" in entries[0].aliases
