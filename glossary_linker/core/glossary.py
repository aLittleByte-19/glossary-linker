from __future__ import annotations

import re
from pathlib import Path
from dataclasses import asdict
from typing import Any

import yaml

from .config import EditorialConfig
from .models import GlossaryEntry
from .text import parse_braced_argument, slugify, strip_latex


STRUCTURED_RE = re.compile(r"\\glossaryentry\s*")
SUBSECTION_RE = re.compile(r"\\subsection\*?\s*")


def parse_glossary_text(text: str, config: EditorialConfig | None = None) -> list[GlossaryEntry]:
    mode = (config.glossary_detection if config else "auto") or "auto"
    source = _document_body(_strip_glossary_command_definitions(text))
    structured = _parse_structured_entries(source)

    if mode == "structured":
        entries = structured
    elif mode == "subsection":
        entries = _parse_subsection_entries(source)
    else:
        entries = structured if structured else _parse_subsection_entries(source)

    entries = _deduplicate_entries(entries)
    if config:
        excluded = set(config.excluded_entry_ids)
        entries = [entry for entry in entries if entry.id not in excluded]
        return merge_config(entries, config)
    return entries


def parse_glossary_file(path: Path, config: EditorialConfig | None = None) -> list[GlossaryEntry]:
    return parse_glossary_text(path.read_text(encoding="utf-8"), config)


def merge_config(entries: list[GlossaryEntry], config: EditorialConfig) -> list[GlossaryEntry]:
    merged: list[GlossaryEntry] = []
    for entry in entries:
        overrides = config.entries.get(entry.id, {})
        aliases = _merge_aliases(entry.aliases, overrides.get("aliases", []))
        mode = overrides.get("mode", entry.mode)
        merged.append(GlossaryEntry(
            id=entry.id,
            term=entry.term,
            definition=entry.definition,
            aliases=list(aliases or []),
            mode="manual" if mode == "manual" else "automatic",
        ))
    return merged


def load_entries_store(path: Path) -> list[GlossaryEntry]:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw_entries = data.get("entries", [])
    entries: list[GlossaryEntry] = []
    for item in raw_entries:
        if not isinstance(item, dict) or not item.get("id") or not item.get("term"):
            continue
        entries.append(GlossaryEntry(
            id=str(item["id"]),
            term=str(item["term"]),
            definition=str(item.get("definition", "")),
            aliases=list(item.get("aliases") or []),
            mode="manual" if item.get("mode") == "manual" else "automatic",
        ))
    return entries


def save_entries_store(entries: list[GlossaryEntry], path: Path) -> None:
    cleaned = [
        GlossaryEntry(
            id=entry.id,
            term=entry.term,
            definition=entry.definition,
            aliases=_clean_aliases(entry),
            mode=entry.mode,
        )
        for entry in entries
    ]
    payload: dict[str, Any] = {
        "entries": [asdict(entry) for entry in sorted(cleaned, key=lambda item: item.term.casefold())]
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")


def merge_detected_with_store(detected: list[GlossaryEntry], stored: list[GlossaryEntry]) -> tuple[list[GlossaryEntry], int]:
    by_id = {entry.id: entry for entry in stored}
    new_count = 0
    merged: list[GlossaryEntry] = []
    for entry in detected:
        previous = by_id.get(entry.id)
        if previous:
            merged.append(GlossaryEntry(
                id=entry.id,
                term=entry.term,
                definition=entry.definition or previous.definition,
                aliases=_clean_aliases(GlossaryEntry(entry.id, entry.term, aliases=_merge_aliases(entry.aliases, previous.aliases))),
                mode=previous.mode,
            ))
        else:
            new_count += 1
            merged.append(entry)
    return merged, new_count


def _parse_structured_entries(text: str) -> list[GlossaryEntry]:
    matches: list[tuple[int, int, str, str]] = []
    for match in STRUCTURED_RE.finditer(text):
        first = text.find("{", match.end())
        parsed_id = parse_braced_argument(text, first)
        if not parsed_id:
            continue
        parsed_term = parse_braced_argument(text, parsed_id[1])
        if not parsed_term:
            continue
        entry_id = slugify(parsed_id[0].strip())
        term = strip_latex(parsed_term[0])
        if not entry_id or not _valid_detected_term(term):
            continue
        matches.append((match.start(), parsed_term[1], entry_id, term))

    entries: list[GlossaryEntry] = []
    for index, (start, end, entry_id, term) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        definition = _definition_after(text[end:next_start])
        entries.append(GlossaryEntry(id=entry_id, term=term, definition=definition, aliases=_suggest_aliases(term)))
    return entries


def _parse_subsection_entries(text: str) -> list[GlossaryEntry]:
    matches: list[tuple[int, int, str]] = []
    for match in SUBSECTION_RE.finditer(text):
        first = text.find("{", match.end())
        parsed = parse_braced_argument(text, first)
        if not parsed:
            continue
        term = strip_latex(parsed[0])
        if _valid_detected_term(term):
            matches.append((match.start(), parsed[1], term))

    entries: list[GlossaryEntry] = []
    for index, (start, end, term) in enumerate(matches):
        next_start = matches[index + 1][0] if index + 1 < len(matches) else len(text)
        definition = _definition_after(text[end:next_start])
        entries.append(GlossaryEntry(id=slugify(term), term=term, definition=definition, aliases=_suggest_aliases(term)))
    return entries


def _definition_after(block: str) -> str:
    lines = []
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("%") or stripped.startswith("\\label"):
            continue
        lines.append(strip_latex(stripped))
        if len(" ".join(lines)) > 260:
            break
    return " ".join(lines)[:320]


def _document_body(text: str) -> str:
    start = text.find(r"\begin{document}")
    if start < 0:
        return text
    start += len(r"\begin{document}")
    end = text.find(r"\end{document}", start)
    return text[start:end] if end >= 0 else text[start:]


def _strip_glossary_command_definitions(text: str) -> str:
    patterns = [
        (re.compile(r"\\(?:providecommand|newcommand|renewcommand)\s*\{\\glossaryentry\}"), 1),
        (re.compile(r"\\NewDocumentCommand\s*\{\\glossaryentry\}"), 2),
    ]
    ranges: list[tuple[int, int]] = []
    for pattern, braced_arguments in patterns:
        for match in pattern.finditer(text):
            end = _command_definition_end(text, match.end(), braced_arguments)
            ranges.append((match.start(), end))
    if not ranges:
        return text
    cleaned = list(text)
    for start, end in ranges:
        cleaned[start:end] = " " * (end - start)
    return "".join(cleaned)


def _command_definition_end(text: str, index: int, braced_arguments: int) -> int:
    cursor = index
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    while cursor < len(text) and text[cursor] == "[":
        close = text.find("]", cursor + 1)
        if close < 0:
            return cursor
        cursor = close + 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    for _ in range(braced_arguments):
        parsed = parse_braced_argument(text, cursor)
        if not parsed:
            return cursor
        cursor = parsed[1]
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    return cursor


def _valid_detected_term(term: str) -> bool:
    normalized = re.sub(r"\s+", " ", term).strip()
    if not normalized or len(normalized) > 120:
        return False
    if re.fullmatch(r"#\d+", normalized):
        return False
    if "\\" in normalized or "{" in normalized or "}" in normalized:
        return False
    return bool(re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", normalized))


def _deduplicate_entries(entries: list[GlossaryEntry]) -> list[GlossaryEntry]:
    result: list[GlossaryEntry] = []
    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            continue
        seen.add(entry.id)
        result.append(entry)
    return result


def _suggest_aliases(term: str) -> list[str]:
    aliases: list[str] = []
    parenthetical = re.fullmatch(r"\s*(.*?)\s*\((.*?)\)\s*", term)
    if parenthetical:
        aliases.extend([parenthetical.group(1), parenthetical.group(2)])
    for separator in [" / ", " - "]:
        if separator in term:
            aliases.extend(part.strip() for part in term.split(separator))
    term_key = term.casefold()
    return [alias for alias in _merge_aliases([], aliases) if alias.casefold() != term_key]


def _merge_aliases(*groups: list[str] | tuple[str, ...] | str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for group in groups:
        values = [group] if isinstance(group, str) else list(group or [])
        for value in values:
            normalized = re.sub(r"\s+", " ", value).strip()
            if not normalized:
                continue
            key = normalized.casefold()
            if key not in seen:
                seen.add(key)
                result.append(normalized)
    return result


def _clean_aliases(entry: GlossaryEntry) -> list[str]:
    term_key = entry.term.casefold()
    return [alias for alias in _merge_aliases(entry.aliases) if alias.casefold() != term_key]
