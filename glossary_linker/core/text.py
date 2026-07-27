from __future__ import annotations

import re
import unicodedata


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_value.casefold()).strip("-")
    return slug or "voce"


def strip_latex(value: str) -> str:
    value = _strip_latex_comments(value)
    value = re.sub(r"\\[a-zA-Z*]+(?:\[[^\]]*\])?", "", value)
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def _strip_latex_comments(value: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char != "%":
            result.append(char)
            index += 1
            continue

        backslashes = 0
        previous = index - 1
        while previous >= 0 and value[previous] == "\\":
            backslashes += 1
            previous -= 1

        if backslashes % 2:
            result.pop()
            result.append("%")
            index += 1
            continue

        while index < len(value) and value[index] not in "\r\n":
            index += 1

    return "".join(result)


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
