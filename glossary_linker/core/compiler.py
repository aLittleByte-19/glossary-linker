from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import LocalConfig


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
    try:
        if compiler == "latexmk" and config.clean_aux_files:
            subprocess.run(
                [config.latexmk_path, "-C", tex_path.name],
                cwd=tex_path.parent,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=max(10, min(config.compile_timeout_seconds, 60)),
                check=False,
            )
        completed = subprocess.run(
            command,
            cwd=tex_path.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=config.compile_timeout_seconds,
            check=False,
        )
    except Exception as exc:
        return CompileResult(False, command, str(exc))

    pdf_path = tex_path.with_suffix(".pdf")
    if pdf_name:
        target = tex_path.parent / pdf_name
        if completed.returncode == 0 and pdf_path.exists() and target != pdf_path:
            pdf_path.replace(target)
            pdf_path = target
    return CompileResult(completed.returncode == 0, command, completed.stdout, pdf_path if pdf_path.exists() else None)


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
