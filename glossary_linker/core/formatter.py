from __future__ import annotations

import re

from .text import parse_braced_argument, slugify, strip_latex


GLOSSARYENTRY_MACRO = r"\providecommand{\glossaryentry}[2]{\subsection{#2}\label{gls:#1}}"


def format_glossary_text(text: str) -> str:
    """Normalize a LaTeX glossary so the app can read stable entry IDs."""
    normalized = _replace_subsections_with_entries(text)
    if r"\newcommand{\glossaryentry}" not in normalized and r"\providecommand{\glossaryentry}" not in normalized:
        normalized = _insert_macro(normalized, GLOSSARYENTRY_MACRO)
    return normalized


def _replace_subsections_with_entries(text: str) -> str:
    pattern = re.compile(r"\\subsection\*?\s*")
    parts: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        first = text.find("{", match.end())
        parsed = parse_braced_argument(text, first)
        if not parsed:
            continue
        between = text[match.start():parsed[1]]
        if "\\glossaryentry" in between:
            continue
        term = strip_latex(parsed[0])
        if not term:
            continue
        parts.append(text[cursor:match.start()])
        parts.append(rf"\glossaryentry{{{slugify(term)}}}{{{parsed[0].strip()}}}")
        cursor = parsed[1]
    parts.append(text[cursor:])
    return "".join(parts)


def _insert_macro(text: str, macro: str) -> str:
    document_start = text.find(r"\begin{document}")
    if document_start >= 0:
        return text[:document_start].rstrip() + "\n\n" + macro + "\n\n" + text[document_start:]
    return macro + "\n\n" + text
