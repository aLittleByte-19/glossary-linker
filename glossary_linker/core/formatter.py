from __future__ import annotations

import re

from .text import parse_braced_argument, slugify, strip_latex


SUBSECTION_RE = re.compile(r"\\subsection\*?\s*")
GLOSSARYENTRY_RE = re.compile(r"\\glossaryentry\s*")


def format_glossary_text(text: str) -> str:
    """Normalize a LaTeX glossary while keeping subsection-based parsing."""
    normalized = _strip_glossaryentry_macro_definitions(text)
    normalized = _replace_glossaryentry_calls(normalized)
    return _ensure_subsection_anchors(normalized)


def _replace_glossaryentry_calls(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    for match in GLOSSARYENTRY_RE.finditer(text):
        parsed_id = parse_braced_argument(text, text.find("{", match.end()))
        if not parsed_id:
            continue
        parsed_term = parse_braced_argument(text, parsed_id[1])
        if not parsed_term:
            continue
        entry_id = slugify(parsed_id[0].strip())
        term = parsed_term[0].strip()
        if not entry_id or not strip_latex(term):
            continue
        parts.append(text[cursor:match.start()])
        parts.append(_subsection_with_anchor(term, entry_id))
        cursor = parsed_term[1]
    parts.append(text[cursor:])
    return "".join(parts)


def _ensure_subsection_anchors(text: str) -> str:
    parts: list[str] = []
    cursor = 0
    matches = list(SUBSECTION_RE.finditer(text))
    for index, match in enumerate(matches):
        parsed = parse_braced_argument(text, text.find("{", match.end()))
        if not parsed:
            continue
        term = strip_latex(parsed[0])
        entry_id = slugify(term)
        if not term or not entry_id or re.fullmatch(r"#\d+", term.strip()):
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        following = text[parsed[1]:next_start]
        if rf"\hypertarget{{gls:{entry_id}}}" in following and rf"\label{{gls:{entry_id}}}" in following:
            continue
        parts.append(text[cursor:parsed[1]])
        parts.append("\n")
        if rf"\hypertarget{{gls:{entry_id}}}" not in following:
            parts.append(rf"\hypertarget{{gls:{entry_id}}}{{}}")
        if rf"\label{{gls:{entry_id}}}" not in following:
            parts.append(rf"\label{{gls:{entry_id}}}")
        cursor = parsed[1]
    parts.append(text[cursor:])
    return "".join(parts)


def _subsection_with_anchor(term: str, entry_id: str) -> str:
    return rf"\subsection{{{term}}}" + "\n" + rf"\hypertarget{{gls:{entry_id}}}{{}}\label{{gls:{entry_id}}}"


def _strip_glossaryentry_macro_definitions(text: str) -> str:
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
