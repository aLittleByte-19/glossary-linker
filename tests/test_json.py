import json
import importlib.util

import pytest

from glossary_linker.core.json import GlossaryJSONError, save_glossary_json, serialize_glossary_json
from glossary_linker.core.models import GlossaryEntry


def test_html_renderer_module_is_absent():
    assert importlib.util.find_spec("glossary_linker.core.html") is None


def test_json_contract_is_exact_and_entries_without_aliases_use_an_array():
    data = serialize_glossary_json([
        GlossaryEntry(
            "continuous-integration",
            "Continuous Integration",
            "Definizione del termine.",
        )
    ])

    assert json.loads(data) == {
        "title": "Glossario",
        "entries": [{
            "id": "continuous-integration",
            "term": "Continuous Integration",
            "definition": "Definizione del termine.",
            "aliases": [],
        }],
    }
    assert list(json.loads(data)) == ["title", "entries"]
    assert list(json.loads(data)["entries"][0]) == ["id", "term", "definition", "aliases"]
    assert data.endswith(b"\n")


def test_empty_glossary_still_has_the_exact_contract():
    assert json.loads(serialize_glossary_json([])) == {"title": "Glossario", "entries": []}


def test_aliases_are_trimmed_collapsed_and_deduplicated():
    data = serialize_glossary_json([
        GlossaryEntry(
            "continuous-integration",
            "Continuous Integration",
            "Definizione.",
            [" CI ", "Integrazione   continua", "ci", "Continuous Integration", ""],
        )
    ])

    assert json.loads(data)["entries"][0]["aliases"] == ["CI", "Integrazione continua"]


def test_unicode_italian_sorting_and_output_are_deterministic():
    entries = [
        GlossaryEntry("zaino", "Zaino", "Definizione."),
        GlossaryEntry("eta", "Ètà", "Definizione con accento."),
        GlossaryEntry("albero", "Albero", "Definizione."),
    ]

    first = serialize_glossary_json(entries)
    second = serialize_glossary_json(list(reversed(entries)))

    assert first == second
    assert [entry["term"] for entry in json.loads(first)["entries"]] == ["Albero", "Ètà", "Zaino"]
    assert "Ètà" in first.decode("utf-8")


def test_ids_are_preserved_and_must_be_valid_and_unique():
    stable = serialize_glossary_json([GlossaryEntry("id-stabile-42", "Voce", "Definizione.")])
    assert json.loads(stable)["entries"][0]["id"] == "id-stabile-42"

    with pytest.raises(GlossaryJSONError, match="ID .* non valido"):
        serialize_glossary_json([GlossaryEntry("ID non valido", "Voce", "Definizione.")])
    with pytest.raises(GlossaryJSONError, match="ID duplicato"):
        serialize_glossary_json([
            GlossaryEntry("duplicato", "Prima", "Definizione."),
            GlossaryEntry("duplicato", "Seconda", "Definizione."),
        ])


def test_duplicate_terms_are_rejected():
    with pytest.raises(GlossaryJSONError, match="Termine duplicato"):
        serialize_glossary_json([
            GlossaryEntry("prima", "Integrazione Continua", "Definizione."),
            GlossaryEntry("seconda", "integrazione continua", "Altra definizione."),
        ])


@pytest.mark.parametrize(
    "entry, message",
    [
        (GlossaryEntry("", "Voce", "Definizione."), "campo 'id' non può essere vuoto"),
        (GlossaryEntry("voce", "", "Definizione."), "campo 'term' non può essere vuoto"),
        (GlossaryEntry("voce", "Voce", ""), "campo 'definition' non può essere vuoto"),
        (GlossaryEntry("voce", "Voce", "Definizione.", "alias"), "'aliases' deve essere un array"),
    ],
)
def test_missing_empty_or_invalid_fields_are_rejected(entry, message):
    with pytest.raises(GlossaryJSONError, match=message):
        serialize_glossary_json([entry])


def test_html_markup_is_rejected_from_public_text():
    with pytest.raises(GlossaryJSONError, match="markup HTML non è consentito"):
        serialize_glossary_json([
            GlossaryEntry("voce", "Voce", "Definizione <strong>marcata</strong>.")
        ])


def test_validation_failure_does_not_create_or_replace_target(tmp_path):
    target = tmp_path / "glossary.json"
    target.write_bytes(b"contenuto precedente\n")

    with pytest.raises(GlossaryJSONError):
        save_glossary_json([GlossaryEntry("voce", "Voce", "")], target)

    assert target.read_bytes() == b"contenuto precedente\n"
    assert list(tmp_path.iterdir()) == [target]


def test_output_path_must_have_json_extension(tmp_path):
    target = tmp_path / "Glossario.html"

    with pytest.raises(GlossaryJSONError, match="estensione \\.json"):
        save_glossary_json([GlossaryEntry("voce", "Voce", "Definizione.")], target)

    assert not target.exists()


def test_atomic_replace_failure_leaves_existing_target_and_no_temporary_file(monkeypatch, tmp_path):
    import glossary_linker.core.json as glossary_json

    target = tmp_path / "glossary.json"
    target.write_bytes(b"contenuto precedente\n")

    def fail_replace(source, destination):
        raise OSError("replace non disponibile")

    monkeypatch.setattr(glossary_json.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace non disponibile"):
        save_glossary_json([GlossaryEntry("voce", "Voce", "Definizione.")], target)

    assert target.read_bytes() == b"contenuto precedente\n"
    assert list(tmp_path.iterdir()) == [target]
