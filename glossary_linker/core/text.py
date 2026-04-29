from __future__ import annotations

import re
import unicodedata


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug or "voce"


def strip_latex(value: str) -> str:
    value = re.sub(r"%.*", "", value)
    value = re.sub(r"\\[a-zA-Z*]+(?:\[[^\]]*\])?", "", value)
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def parse_braced_argument(text: str, open_brace: int) -> tuple[str, int] | None:
    if open_brace >= len(text) or text[open_brace] != "{":
        return None
    depth = 0
    start = open_brace + 1
    index = open_brace
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index], index + 1
        index += 1
    return None
