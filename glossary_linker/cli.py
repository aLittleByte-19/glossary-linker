from __future__ import annotations

import argparse
from pathlib import Path

from .core.config import load_editorial_config, load_local_config
from .core.glossary import parse_glossary_file
from .core.json import GlossaryJSONError, save_glossary_json
from .core.linker import link_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Export the glossary JSON and link LaTeX documents.")
    parser.add_argument("tex", nargs="*", type=Path)
    parser.add_argument("--config", type=Path, default=Path("glossary-linker.yml"))
    parser.add_argument("--local-config", type=Path, default=Path("glossary-linker.local.yml"))
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--glossary-json", type=Path, help="Override glossary_json_path for this run.")
    args = parser.parse_args()

    config = load_editorial_config(args.config)
    local = load_local_config(args.local_config) if args.local_config.exists() else None
    glossary_path = args.glossary or Path(local.glossary_path if local and local.glossary_path else config.glossary_path)
    config.glossary_path = str(glossary_path)
    try:
        entries = parse_glossary_file(glossary_path, config)
    except (OSError, ValueError) as exc:
        parser.error(f"Impossibile leggere il glossario: {exc}")
    configured_output = local.glossary_json_path if local and local.glossary_json_path else config.glossary_json_path
    output_path = args.glossary_json or Path(configured_output)
    try:
        save_glossary_json(entries, output_path)
    except (GlossaryJSONError, OSError) as exc:
        parser.error(f"Impossibile esportare il glossario JSON: {exc}")
    print(f"Glossario JSON -> {output_path}")
    for tex_path in args.tex:
        result = link_file(tex_path, entries, config)
        result.output_path.write_text(result.linked_text, encoding="utf-8")
        print(f"{tex_path} -> {result.output_path} ({result.automatic_links} automatic links)")
