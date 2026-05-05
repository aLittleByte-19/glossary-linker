from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


EntryMode = str


@dataclass(slots=True)
class GlossaryEntry:
    id: str
    term: str
    definition: str = ""
    aliases: list[str] = field(default_factory=list)
    mode: EntryMode = "automatic"

    @property
    def search_terms(self) -> list[str]:
        values = [self.term, *self.aliases]
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            key = normalized.casefold()
            if normalized and key not in seen:
                seen.add(key)
                result.append(normalized)
        return result


@dataclass(slots=True)
class Occurrence:
    id: str
    entry_id: str
    term: str
    visible_text: str
    file_path: Path
    line_number: int
    section: str
    context: str
    start: int
    end: int


@dataclass(slots=True)
class Job:
    id: str
    config: dict
    entries: list[dict]
    paths: list[str]
    root: str
    excluded: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review_order: str = "by_term"
    occurrences: list[dict] = field(default_factory=list)
    decisions: dict[str, bool] = field(default_factory=dict)
    results: list[dict] = field(default_factory=list)
    report: dict | None = None


@dataclass(slots=True)
class FileLinkResult:
    source_path: Path
    output_path: Path
    linked_text: str
    automatic_links: int = 0
    manual_links: int = 0
    skipped: int = 0
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ProcessingReport:
    processed_files: list[Path] = field(default_factory=list)
    excluded_files: list[Path] = field(default_factory=list)
    automatic_links: int = 0
    manual_links: int = 0
    skipped_occurrences: int = 0
    missing_terms: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
