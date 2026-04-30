from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class EditorialConfig:
    glossary_html_url: str = ""
    glossary_html_path: str = "Glossario.html"
    glossary_path: str = "Glossario.tex"
    html_anchor_format: str = "#gls-{id}"
    glossary_detection: str = "auto"
    glossary_custom_command: str = ""
    glossary_structure_description: str = r"Rileva automaticamente il comando LaTeX piu probabile oppure usa \subsection{Termine}."
    excluded_entry_ids: list[str] = field(default_factory=list)
    exclude_file_patterns: list[str] = field(default_factory=lambda: [
        "*.linked.tex",
        "**/build/**",
        "**/output/**",
        "**/dist/**",
        "**/tmp/**",
        "**/prove/**",
        "**/bozze/**",
        "**/prompt/**",
        "**/prompt.tex",
        "**/*prompt*.tex",
        "**/*prova*.tex",
        "**/*bozza*.tex",
    ])
    ignored_environments: list[str] = field(default_factory=lambda: [
        "verbatim",
        "lstlisting",
        "minted",
        "listing",
        "code",
    ])
    ignored_commands: list[str] = field(default_factory=lambda: [
        "href",
        "url",
        "glslink",
        "part",
        "chapter",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
        "title",
        "author",
        "date",
        "caption",
    ])
    ignored_sections: list[str] = field(default_factory=lambda: ["indice", "frontespizio"])
    entries: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass(slots=True)
class LocalConfig:
    default_repo_root: str = "."
    last_operation: str = "link-documents"
    last_source_dir: str = "."
    last_review_order: str = "by_term"
    last_new_entry_ids: str = ""
    latexmk_path: str = "latexmk"
    pdflatex_path: str = "pdflatex"
    xelatex_path: str = "xelatex"
    lualatex_path: str = "lualatex"
    preferred_compiler: str = "latexmk"
    compile_timeout_seconds: int = 120
    max_compile_passes: int = 2
    temporary_directory: str = ""
    local_server_port: int = 8765
    auto_open_pdf: bool = True
    clean_aux_files: bool = True
    clean_compile_artifacts: bool = True
    log_level: str = "INFO"
    preferred_browser: str = ""


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Configuration file {path} must contain a mapping.")
    return data


def _coerce_dataclass(cls: type[EditorialConfig] | type[LocalConfig], data: dict[str, Any]):
    allowed = cls.__dataclass_fields__.keys()  # type: ignore[attr-defined]
    filtered = {key: value for key, value in data.items() if key in allowed}
    return cls(**filtered)


def load_editorial_config(path: Path) -> EditorialConfig:
    return _coerce_dataclass(EditorialConfig, _load_yaml(path))


def load_local_config(path: Path) -> LocalConfig:
    return _coerce_dataclass(LocalConfig, _load_yaml(path))


def save_editorial_config(config: EditorialConfig, path: Path) -> None:
    path.write_text(yaml.safe_dump(asdict(config), sort_keys=False, allow_unicode=True), encoding="utf-8")


def save_local_config(config: LocalConfig, path: Path) -> None:
    path.write_text(yaml.safe_dump(asdict(config), sort_keys=False, allow_unicode=True), encoding="utf-8")
