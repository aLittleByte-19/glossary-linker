from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import asdict
from pathlib import Path

from .config import EditorialConfig
from .models import FileLinkResult, GlossaryEntry, Occurrence, ProcessingReport


def discover_tex_files(root: Path, config: EditorialConfig) -> tuple[list[Path], list[Path]]:
    root = root.expanduser().resolve()
    glossary = (root / config.glossary_path).resolve() if config.glossary_path else None
    included: list[Path] = []
    excluded: list[Path] = []
    for path in sorted(root.rglob("*.tex")):
        rel = path.relative_to(root)
        reason = (
            path.name.endswith(".linked.tex")
            or (glossary is not None and path.resolve() == glossary)
            or any(fnmatch.fnmatch(rel.as_posix(), pattern) for pattern in config.exclude_file_patterns)
        )
        if reason:
            excluded.append(path)
        else:
            included.append(path)
    return included, excluded


def collect_manual_occurrences(paths: list[Path], entries: list[GlossaryEntry], config: EditorialConfig) -> list[Occurrence]:
    manual_entries = [entry for entry in entries if entry.mode == "manual"]
    occurrences: list[Occurrence] = []
    for path in paths:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in _find_matches(text, manual_entries, config):
            occurrences.append(_to_occurrence(text, path, match))
    return occurrences


def link_file(
    path: Path,
    entries: list[GlossaryEntry],
    config: EditorialConfig,
    manual_decisions: dict[str, bool] | None = None,
    only_entry_ids: set[str] | None = None,
) -> FileLinkResult:
    manual_decisions = manual_decisions or {}
    original = path.read_text(encoding="utf-8")
    selected_entries = [entry for entry in entries if only_entry_ids is None or entry.id in only_entry_ids]
    matches = _find_matches(original, selected_entries, config)
    replacements: list[tuple[int, int, str, str]] = []
    automatic = 0
    manual = 0
    skipped = 0

    occupied: list[tuple[int, int]] = []
    for match in matches:
        entry = match["entry"]
        occurrence = _to_occurrence(original, path, match)
        should_link = entry.mode == "automatic" or manual_decisions.get(occurrence.id, False)
        if entry.mode == "manual" and occurrence.id not in manual_decisions:
            skipped += 1
            continue
        if not should_link:
            skipped += 1
            continue
        if any(not (match["end"] <= start or match["start"] >= end) for start, end in occupied):
            continue
        visible = original[match["start"]:match["end"]]
        replacements.append((match["start"], match["end"], rf"\glslink{{{entry.id}}}{{{visible}}}", entry.mode))
        occupied.append((match["start"], match["end"]))
        if entry.mode == "automatic":
            automatic += 1
        else:
            manual += 1

    linked = _apply_replacements(original, replacements)
    linked = ensure_glslink_macro(linked, config)
    return FileLinkResult(
        source_path=path,
        output_path=path.with_name(path.stem + ".linked.tex"),
        linked_text=linked,
        automatic_links=automatic,
        manual_links=manual,
        skipped=skipped,
    )


def process_files(
    paths: list[Path],
    entries: list[GlossaryEntry],
    config: EditorialConfig,
    manual_decisions: dict[str, bool] | None = None,
    only_entry_ids: set[str] | None = None,
) -> tuple[list[FileLinkResult], ProcessingReport]:
    results: list[FileLinkResult] = []
    report = ProcessingReport()
    found_terms: set[str] = set()
    for path in paths:
        try:
            result = link_file(path, entries, config, manual_decisions, only_entry_ids)
            results.append(result)
            report.processed_files.append(path)
            report.automatic_links += result.automatic_links
            report.manual_links += result.manual_links
            report.skipped_occurrences += result.skipped
            for entry in entries:
                if rf"\glslink{{{entry.id}}}" in result.linked_text:
                    found_terms.add(entry.id)
        except Exception as exc:  # pragma: no cover - reported to UI
            report.errors.append(f"{path}: {exc}")
    report.missing_terms = [entry.term for entry in entries if entry.id not in found_terms]
    return results, report


def save_report_json(report: ProcessingReport, path: Path) -> None:
    data = _jsonable(asdict(report))
    data["missing_terms_count"] = len(report.missing_terms)
    data.pop("missing_terms", None)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def save_report_markdown(report: ProcessingReport, path: Path) -> None:
    lines = [
        "# Glossary Linker Report",
        "",
        f"- File processati: {len(report.processed_files)}",
        f"- File esclusi: {len(report.excluded_files)}",
        f"- Link automatici inseriti: {report.automatic_links}",
        f"- Link approvati manualmente: {report.manual_links}",
        f"- Occorrenze saltate: {report.skipped_occurrences}",
        f"- Termini non trovati: {len(report.missing_terms)}",
        "",
        "## Warning",
        *[f"- {warning}" for warning in report.warnings],
        "",
        "## Errori",
        *[f"- {error}" for error in report.errors],
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def ensure_glslink_macro(text: str, config: EditorialConfig) -> str:
    macro = _glslink_macro(config)
    existing_app_macro = re.compile(
        r"\\providecommand\{\\glslink\}\[2\]\{\\href\{.*?\}\{(?:\\underline\{#2\}|#2)(?:\\textsuperscript\{\\scriptsize G\})?\}\}",
        re.DOTALL,
    )
    if existing_app_macro.search(text):
        return existing_app_macro.sub(lambda _match: macro, text, count=1)
    if r"\newcommand{\glslink}" in text or r"\providecommand{\glslink}" in text:
        return text
    document_start = text.find(r"\begin{document}")
    if document_start >= 0:
        return text[:document_start].rstrip() + "\n\n" + macro + "\n\n" + text[document_start:]
    return macro + "\n\n" + text


def _glslink_macro(config: EditorialConfig) -> str:
    target = _latex_href_target(config)
    return rf"\providecommand{{\glslink}}[2]{{\href{{{target}}}{{\underline{{#2}}\textsuperscript{{\scriptsize G}}}}}}"


def _latex_href_target(config: EditorialConfig) -> str:
    target_url = _target_url(config)
    anchor = _effective_anchor_format(config, target_url)
    if "{id}" not in anchor:
        anchor = anchor.rstrip("#") + "{id}"
    return (target_url + anchor).replace("#", r"\#").replace("{id}", "#1")


def _target_url(config: EditorialConfig) -> str:
    if config.glossary_link_target == "html":
        return (config.glossary_html_url or "").strip().rstrip()
    return (config.glossary_pdf_url or "").rstrip()


def _effective_anchor_format(config: EditorialConfig, target_url: str) -> str:
    if config.glossary_link_target == "html":
        return config.html_anchor_format or "#gls-{id}"
    anchor = config.anchor_format or "#gls:{id}"
    url = target_url.strip().lower()
    if not url.startswith(("http://", "https://")) and anchor.startswith("#nameddest="):
        return "#" + anchor.removeprefix("#nameddest=")
    return anchor


def _find_matches(text: str, entries: list[GlossaryEntry], config: EditorialConfig) -> list[dict]:
    body_start = text.find(r"\begin{document}")
    if body_start < 0:
        body_start = 0
    else:
        body_start += len(r"\begin{document}")
    mask = _masked_ranges(text, config)
    matches: list[dict] = []
    sorted_entries = sorted(entries, key=lambda item: max((len(term) for term in item.search_terms), default=0), reverse=True)
    for entry in sorted_entries:
        for term in sorted(entry.search_terms, key=len, reverse=True):
            pattern = _term_pattern(term)
            for match in pattern.finditer(text, body_start):
                if _is_masked(match.start(), match.end(), mask):
                    continue
                matches.append({"entry": entry, "term": term, "start": match.start(), "end": match.end()})
    return sorted(matches, key=lambda item: (item["start"], -(item["end"] - item["start"])))


def _term_pattern(term: str) -> re.Pattern:
    escaped = re.escape(term.strip())
    escaped = escaped.replace(r"\ ", r"(?:\s|~|\\ |-)+")
    letter_or_digit = r"A-Za-zÀ-ÖØ-öø-ÿ0-9_"
    return re.compile(rf"(?<![{letter_or_digit}\\]){escaped}(?![{letter_or_digit}-])", re.IGNORECASE | re.UNICODE)


def _masked_ranges(text: str, config: EditorialConfig) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    document_start = text.find(r"\begin{document}")
    if document_start > 0:
        ranges.append((0, document_start))
    ranges.extend((match.start(), match.end()) for match in re.finditer(r"https?://[^\s}]+", text))
    ranges.extend(_structural_ranges(text, config))
    ranges.extend(_environment_ranges(text, config.ignored_environments))
    ranges.extend(_command_argument_ranges(text, config.ignored_commands))
    ranges.extend((match.start(), match.end()) for match in re.finditer(r"\\[a-zA-Z@]+\*?", text))
    return sorted(ranges)


def _structural_ranges(text: str, config: EditorialConfig) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    ignored = {section.casefold() for section in config.ignored_sections}
    body_start = _document_body_start(text)
    if "indice" in ignored:
        for match in re.finditer(r"\\(?:tableofcontents|listoffigures|listoftables)\b", text):
            ranges.append((match.start(), _page_or_line_end(text, match.end())))
    if "frontespizio" in ignored:
        ranges.extend((match.start(), match.end()) for match in re.finditer(r"\\begin\{titlepage\}.*?\\end\{titlepage\}", text, re.DOTALL))
        for match in re.finditer(r"\\maketitle\b", text):
            line_end = text.find("\n", match.end())
            ranges.append((match.start(), len(text) if line_end < 0 else line_end))
        frontmatter_end = _frontmatter_end(text, body_start)
        if frontmatter_end > body_start:
            ranges.append((body_start, frontmatter_end))
    return ranges


def _document_body_start(text: str) -> int:
    document_start = text.find(r"\begin{document}")
    if document_start < 0:
        return 0
    return document_start + len(r"\begin{document}")


def _frontmatter_end(text: str, body_start: int) -> int:
    body = text[body_start:]
    toc = re.search(r"\\(?:tableofcontents|listoffigures|listoftables)\b", body)
    if toc:
        return body_start + toc.start()
    section = re.search(r"\\(?:part|chapter|section|subsection|subsubsection|paragraph|subparagraph)\*?\s*\{", body)
    if section:
        return body_start + section.start()
    return body_start


def _page_or_line_end(text: str, start: int) -> int:
    page_break = re.search(r"\\(?:newpage|clearpage|pagebreak)\b", text[start:])
    if page_break:
        return start + page_break.end()
    line_end = text.find("\n", start)
    return len(text) if line_end < 0 else line_end


def _environment_ranges(text: str, names: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for name in names:
        pattern = re.compile(rf"\\begin\{{{re.escape(name)}\}}.*?\\end\{{{re.escape(name)}\}}", re.DOTALL)
        ranges.extend((match.start(), match.end()) for match in pattern.finditer(text))
    return ranges


def _command_argument_ranges(text: str, names: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for name in names:
        pattern = re.compile(rf"\\{re.escape(name)}\*?\s*")
        for match in pattern.finditer(text):
            cursor = match.end()
            if cursor < len(text) and text[cursor] == "[":
                close = text.find("]", cursor)
                cursor = close + 1 if close >= 0 else cursor
            for _ in range(2 if name in {"href", "glslink"} else 1):
                while cursor < len(text) and text[cursor].isspace():
                    cursor += 1
                if cursor >= len(text) or text[cursor] != "{":
                    break
                end = _balanced_end(text, cursor)
                if end is None:
                    break
                cursor = end
            ranges.append((match.start(), cursor))
    return ranges


def _balanced_end(text: str, start: int) -> int | None:
    depth = 0
    index = start
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
                return index + 1
        index += 1
    return None


def _is_masked(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(not (end <= range_start or start >= range_end) for range_start, range_end in ranges)


def _to_occurrence(text: str, path: Path, match: dict) -> Occurrence:
    start = match["start"]
    end = match["end"]
    line_number = text.count("\n", 0, start) + 1
    lines = text.splitlines()
    context_start = max(0, line_number - 4)
    context_end = min(len(lines), line_number + 3)
    section = _current_section(text[:start])
    visible = text[start:end]
    entry = match["entry"]
    occurrence_id = f"{path.resolve()}::{entry.id}::{start}:{end}"
    return Occurrence(
        id=occurrence_id,
        entry_id=entry.id,
        term=match["term"],
        visible_text=visible,
        file_path=path,
        line_number=line_number,
        section=section,
        context="\n".join(lines[context_start:context_end]),
        start=start,
        end=end,
    )


def _current_section(prefix: str) -> str:
    matches = list(re.finditer(r"\\(?:section|subsection|subsubsection)\*?\{([^{}]+)\}", prefix))
    return matches[-1].group(1) if matches else ""


def _apply_replacements(text: str, replacements: list[tuple[int, int, str, str]]) -> str:
    output = text
    for start, end, replacement, _mode in sorted(replacements, key=lambda item: item[0], reverse=True):
        output = output[:start] + replacement + output[end:]
    return output


def _jsonable(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value
