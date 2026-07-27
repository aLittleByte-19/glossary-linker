from __future__ import annotations

import json
import os
import re
import stat
import tempfile
import unicodedata
from pathlib import Path

from .models import GlossaryEntry


GLOSSARY_TITLE = "Glossario"
ENTRY_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_HTML_MARKUP_PATTERN = re.compile(r"<!--|</?[A-Za-z][^>]*>")
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class GlossaryJSONError(ValueError):
    """Raised when glossary data cannot satisfy the public JSON contract."""


def serialize_glossary_json(entries: list[GlossaryEntry]) -> bytes:
    """Validate and serialize entries using the public, deterministic contract."""
    normalized_entries = _normalize_entries(entries)
    payload = {
        "title": GLOSSARY_TITLE,
        "entries": normalized_entries,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    return text.encode("utf-8")


def save_glossary_json(entries: list[GlossaryEntry], path: Path) -> bytes:
    """Atomically save the glossary, leaving an existing target intact on failure."""
    data = serialize_glossary_json(entries)
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise GlossaryJSONError(f"Il percorso di output deve avere estensione .json: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        mode = stat.S_IMODE(path.stat().st_mode) if path.exists() else 0o644
        os.chmod(temporary_path, mode)
        os.replace(temporary_path, path)
    except OSError:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return data


def _normalize_entries(entries: list[GlossaryEntry]) -> list[dict[str, object]]:
    if not isinstance(entries, list):
        raise GlossaryJSONError("Le voci del glossario devono essere fornite come lista.")

    normalized: list[dict[str, object]] = []
    seen_ids: set[str] = set()
    seen_terms: dict[str, str] = {}
    for index, entry in enumerate(entries, start=1):
        if not isinstance(entry, GlossaryEntry):
            raise GlossaryJSONError(f"Voce #{index} non valida: atteso GlossaryEntry.")

        entry_id = _required_text(entry.id, "id", index)
        if not ENTRY_ID_PATTERN.fullmatch(entry_id):
            raise GlossaryJSONError(
                f"Voce #{index}: ID '{entry_id}' non valido; deve rispettare {ENTRY_ID_PATTERN.pattern}."
            )
        if entry_id in seen_ids:
            raise GlossaryJSONError(f"ID duplicato nel glossario: '{entry_id}'.")
        seen_ids.add(entry_id)

        term = _required_text(entry.term, "term", index)
        definition = _required_text(entry.definition, "definition", index)
        term_key = _comparison_key(term)
        if term_key in seen_terms:
            raise GlossaryJSONError(
                f"Termine duplicato nel glossario: '{term}' collide con '{seen_terms[term_key]}'."
            )
        seen_terms[term_key] = term

        aliases = _normalize_aliases(entry.aliases, term, index)
        normalized.append({
            "id": entry_id,
            "term": term,
            "definition": definition,
            "aliases": aliases,
        })

    normalized.sort(key=lambda item: _italian_sort_key(str(item["term"]), str(item["id"])))
    return normalized


def _required_text(value: object, field: str, index: int) -> str:
    if not isinstance(value, str):
        raise GlossaryJSONError(f"Voce #{index}: il campo '{field}' deve essere una stringa.")
    normalized = _normalize_text(value)
    if not normalized:
        raise GlossaryJSONError(f"Voce #{index}: il campo '{field}' non può essere vuoto.")
    _validate_plain_text(normalized, f"Voce #{index}, campo '{field}'")
    return normalized


def _normalize_aliases(value: object, term: str, index: int) -> list[str]:
    if not isinstance(value, list):
        raise GlossaryJSONError(f"Voce #{index}: il campo 'aliases' deve essere un array.")
    aliases: list[str] = []
    seen = {_comparison_key(term)}
    for alias_index, alias in enumerate(value, start=1):
        if not isinstance(alias, str):
            raise GlossaryJSONError(
                f"Voce #{index}: l'alias #{alias_index} deve essere una stringa."
            )
        normalized = _normalize_text(alias)
        if not normalized:
            continue
        _validate_plain_text(normalized, f"Voce #{index}, alias #{alias_index}")
        key = _comparison_key(normalized)
        if key in seen:
            continue
        seen.add(key)
        aliases.append(normalized)
    return aliases


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value)).strip()


def _validate_plain_text(value: str, location: str) -> None:
    if _CONTROL_CHARACTER_PATTERN.search(value):
        raise GlossaryJSONError(f"{location}: sono presenti caratteri di controllo non validi.")
    if _HTML_MARKUP_PATTERN.search(value):
        raise GlossaryJSONError(f"{location}: il markup HTML non è consentito.")


def _comparison_key(value: str) -> str:
    return _normalize_text(value).casefold()


def _italian_sort_key(term: str, entry_id: str) -> tuple[str, str, str]:
    decomposed = unicodedata.normalize("NFKD", term.casefold())
    without_accents = "".join(char for char in decomposed if not unicodedata.combining(char))
    return without_accents, unicodedata.normalize("NFC", term).casefold(), entry_id
