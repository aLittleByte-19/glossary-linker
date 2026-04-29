from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import LocalConfig


LATEX_ARTIFACT_SUFFIXES = (
    ".4ct",
    ".4tc",
    ".acn",
    ".acr",
    ".alg",
    ".aux",
    ".bbl",
    ".bcf",
    ".blg",
    ".dvi",
    ".fdb_latexmk",
    ".fls",
    ".glg",
    ".glo",
    ".gls",
    ".idx",
    ".ilg",
    ".ind",
    ".ist",
    ".lof",
    ".log",
    ".lot",
    ".nav",
    ".out",
    ".run.xml",
    ".snm",
    ".synctex.gz",
    ".toc",
    ".vrb",
    ".xdv",
)

SKIPPED_ARTIFACT_DIRS = {".git", ".hg", ".svn", ".venv", "node_modules", "__pycache__", ".pytest_cache"}


@dataclass(slots=True)
class CompileResult:
    ok: bool
    command: list[str]
    output: str
    pdf_path: Path | None = None


def test_environment(config: LocalConfig) -> dict[str, str]:
    tools = {
        "latexmk": config.latexmk_path,
        "pdflatex": config.pdflatex_path,
        "xelatex": config.xelatex_path,
        "lualatex": config.lualatex_path,
    }
    return {name: _resolve_tool(path) or "not found" for name, path in tools.items()}


def compile_tex(tex_path: Path, config: LocalConfig, pdf_name: str | None = None) -> CompileResult:
    compiler = config.preferred_compiler
    command = _command_for(tex_path, compiler, config)
    output_parts: list[str] = []
    try:
        if compiler == "latexmk" and config.clean_aux_files:
            cleanup = subprocess.run(
                [config.latexmk_path, "-C", tex_path.name],
                cwd=tex_path.parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=max(10, min(config.compile_timeout_seconds, 60)),
                check=False,
            )
            if cleanup.stdout:
                output_parts.append(cleanup.stdout)
        completed = None
        passes = 1 if compiler == "latexmk" else max(1, config.max_compile_passes)
        for _index in range(passes):
            completed = subprocess.run(
                command,
                cwd=tex_path.parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=config.compile_timeout_seconds,
                check=False,
            )
            if completed.stdout:
                output_parts.append(completed.stdout)
            if completed.returncode != 0:
                break
    except Exception as exc:
        return CompileResult(False, command, str(exc))

    if completed is None:
        return CompileResult(False, command, "Compilazione non avviata.")

    pdf_path = tex_path.with_suffix(".pdf")
    if pdf_name:
        target = tex_path.parent / pdf_name
        if completed.returncode == 0 and pdf_path.exists() and target != pdf_path:
            pdf_path.replace(target)
            pdf_path = target
    ok = completed.returncode == 0
    if config.clean_compile_artifacts:
        clean_latex_artifacts(tex_path.parent, stem=tex_path.stem, remove_pdf=not ok)
    return CompileResult(ok, command, "".join(output_parts), pdf_path if ok and pdf_path.exists() else None)


def clean_latex_artifacts(root: Path, stem: str | None = None, remove_pdf: bool = False) -> list[Path]:
    removed: list[Path] = []
    for path in iter_latex_artifacts(root, stem=stem, remove_pdf=remove_pdf):
        path.unlink()
        removed.append(path)
    if stem:
        for directory_name in (f"_minted-{stem}", f"minted-{stem}"):
            directory = root / directory_name
            if directory.is_dir():
                shutil.rmtree(directory)
                removed.append(directory)
    return removed


def iter_latex_artifacts(root: Path, stem: str | None = None, remove_pdf: bool = False) -> list[Path]:
    suffixes = LATEX_ARTIFACT_SUFFIXES + ((".pdf",) if remove_pdf else ())
    artifacts: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIPPED_ARTIFACT_DIRS for part in path.relative_to(root).parts[:-1]):
            continue
        if stem and not path.name.startswith(stem + "."):
            continue
        if path.name.endswith(suffixes):
            artifacts.append(path)
    return artifacts


def _command_for(tex_path: Path, compiler: str, config: LocalConfig) -> list[str]:
    if compiler == "latexmk":
        return [config.latexmk_path, "-g", "-pdf", "-interaction=nonstopmode", tex_path.name]
    path = {
        "pdflatex": config.pdflatex_path,
        "xelatex": config.xelatex_path,
        "lualatex": config.lualatex_path,
    }.get(compiler, config.pdflatex_path)
    return [path, "-interaction=nonstopmode", tex_path.name]


def _resolve_tool(path: str) -> str | None:
    candidate = Path(path).expanduser()
    if candidate.exists():
        return str(candidate)
    return shutil.which(path)
