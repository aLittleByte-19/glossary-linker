from __future__ import annotations

import argparse
from pathlib import Path

from .core.config import load_editorial_config
from .core.glossary import parse_glossary_file
from .core.linker import link_file


def main() -> None:
    parser = argparse.ArgumentParser(description="Link LaTeX documents to glossary entries.")
    parser.add_argument("tex", nargs="+", type=Path)
    parser.add_argument("--config", type=Path, default=Path("glossary-linker.yml"))
    args = parser.parse_args()

    config = load_editorial_config(args.config)
    glossary_path = Path(config.glossary_path)
    entries = parse_glossary_file(glossary_path, config)
    for tex_path in args.tex:
        result = link_file(tex_path, entries, config)
        result.output_path.write_text(result.linked_text, encoding="utf-8")
        print(f"{tex_path} -> {result.output_path} ({result.automatic_links} automatic links)")
