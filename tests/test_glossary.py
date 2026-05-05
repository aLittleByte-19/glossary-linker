from glossary_linker.core.config import EditorialConfig
from glossary_linker.core.formatter import format_glossary_text
import pytest

from glossary_linker.core.glossary import load_entries_store, merge_detected_with_store, parse_glossary_text, save_entries_store
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


def test_parser_ignores_generated_macro_body_and_reads_subsections():
    text = r"""
\providecommand{\glossaryentry}[2]{%
  \subsection{#2}
  \label{gls:#1}
}
\begin{document}
\subsection{Agile SCRUM}
Il metodo di lavoro usato dal team.
\end{document}
"""
    entries = parse_glossary_text(text, EditorialConfig(glossary_detection="subsection"))

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


def test_custom_detection_uses_user_command():
    text = r"""
\voceGlossario{Accuratezza}
Misura quanto una previsione e corretta.

\voceGlossario{Overfitting}
Adattamento eccessivo ai dati.
"""
    entries = parse_glossary_text(text, EditorialConfig(glossary_detection="custom", glossary_custom_command="voceGlossario"))

    assert [entry.id for entry in entries] == ["accuratezza", "overfitting"]
    assert "previsione" in entries[0].definition


def test_auto_detection_prefers_long_repeated_custom_command():
    text = r"""
\textbf{Titolo rumoroso}
\termineGlossario{Accuratezza}
Misura quanto una previsione e corretta.
\termineGlossario{Overfitting}
Adattamento eccessivo ai dati.
\termineGlossario{Dataset}
Insieme di dati.
"""
    entries = parse_glossary_text(text, EditorialConfig(glossary_detection="auto"))

    assert [entry.id for entry in entries] == ["accuratezza", "overfitting", "dataset"]


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


def test_format_glossary_adds_stable_anchors_to_subsections():
    formatted = format_glossary_text(r"\begin{document}\subsection{Accuratezza}Testo\end{document}")

    assert r"\providecommand{\glossaryentry}" not in formatted
    assert r"\subsection{Accuratezza}" in formatted
    assert r"\hypertarget{gls:accuratezza}{}" in formatted
    assert r"\label{gls:accuratezza}" in formatted


def test_format_glossary_converts_old_glossaryentry_calls_to_subsections():
    text = r"""\providecommand{\glossaryentry}[2]{\subsection{#2}\label{gls:#1}}
\begin{document}
\glossaryentry{accuratezza}{Accuratezza}
\end{document}"""

    formatted = format_glossary_text(text)

    assert r"\glossaryentry{accuratezza}{Accuratezza}" not in formatted
    assert r"\subsection{Accuratezza}" in formatted
    assert r"\hypertarget{gls:accuratezza}{}" in formatted


def test_parenthetical_terms_get_useful_aliases():
    entries = parse_glossary_text(r"\subsection{Branch (Ramo)} Definizione.")

    assert entries[0].term == "Branch (Ramo)"
    assert "Branch" in entries[0].aliases
    assert "Ramo" in entries[0].aliases


def test_generated_anchors_do_not_leak_into_definitions():
    text = r"""
\subsection{Capitolato}
\hypertarget{gls:capitolato}{}\label{gls:capitolato}
Documento tecnico.
"""
    entries = parse_glossary_text(text, EditorialConfig(glossary_detection="subsection"))

    assert entries[0].definition == "Documento tecnico."


def test_entries_store_coerces_string_aliases_and_rejects_bad_shape(tmp_path):
    path = tmp_path / "entries.yml"
    path.write_text(
        """
entries:
  - id: voce
    term: Voce
    aliases: alias uno, alias due
""",
        encoding="utf-8",
    )

    entries = load_entries_store(path)

    assert entries[0].aliases == ["alias uno", "alias due"]

    path.write_text("- not-a-mapping", encoding="utf-8")
    with pytest.raises(ValueError, match="must contain a mapping"):
        load_entries_store(path)


def test_save_entries_store_is_atomic_and_creates_parent(tmp_path):
    path = tmp_path / "nested" / "entries.yml"

    save_entries_store([GlossaryEntry("voce", "Voce")], path)

    assert path.exists()
    assert load_entries_store(path)[0].id == "voce"
    assert not path.with_suffix(".yml.tmp").exists()
