import subprocess
from pathlib import Path

from glossary_linker.core import compiler
from glossary_linker.core.config import LocalConfig


def test_compile_success_cleans_artifacts_and_keeps_pdf(tmp_path: Path, monkeypatch):
    tex = tmp_path / "doc.tex"
    tex.write_text(r"\begin{document}Ok\end{document}", encoding="utf-8")

    def fake_run(command, cwd, text, stdout, stderr, timeout, check):
        (Path(cwd) / "doc.aux").write_text("aux", encoding="utf-8")
        (Path(cwd) / "doc.log").write_text("log", encoding="utf-8")
        (Path(cwd) / "doc.pdf").write_text("pdf", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stdout="ok")

    monkeypatch.setattr(compiler.subprocess, "run", fake_run)

    result = compiler.compile_tex(
        tex,
        LocalConfig(preferred_compiler="pdflatex", max_compile_passes=1, clean_compile_artifacts=True),
    )

    assert result.ok is True
    assert result.pdf_path == tmp_path / "doc.pdf"
    assert (tmp_path / "doc.tex").exists()
    assert (tmp_path / "doc.pdf").exists()
    assert not (tmp_path / "doc.aux").exists()
    assert not (tmp_path / "doc.log").exists()


def test_compile_failure_cleans_artifacts_and_pdf_but_keeps_log_output(tmp_path: Path, monkeypatch):
    tex = tmp_path / "doc.tex"
    tex.write_text(r"\begin{document}Broken\end{document}", encoding="utf-8")

    def fake_run(command, cwd, text, stdout, stderr, timeout, check):
        (Path(cwd) / "doc.aux").write_text("aux", encoding="utf-8")
        (Path(cwd) / "doc.log").write_text("log", encoding="utf-8")
        (Path(cwd) / "doc.pdf").write_text("partial", encoding="utf-8")
        return subprocess.CompletedProcess(command, 1, stdout="latex error")

    monkeypatch.setattr(compiler.subprocess, "run", fake_run)

    result = compiler.compile_tex(
        tex,
        LocalConfig(preferred_compiler="pdflatex", max_compile_passes=1, clean_compile_artifacts=True),
    )

    assert result.ok is False
    assert "latex error" in result.output
    assert (tmp_path / "doc.tex").exists()
    assert not (tmp_path / "doc.pdf").exists()
    assert not (tmp_path / "doc.aux").exists()
    assert not (tmp_path / "doc.log").exists()


def test_compile_rejects_pdf_name_with_path_components(tmp_path: Path, monkeypatch):
    tex = tmp_path / "doc.tex"
    tex.write_text(r"\begin{document}Ok\end{document}", encoding="utf-8")
    calls = []

    def fake_run(*args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args[0], 0, stdout="ok")

    monkeypatch.setattr(compiler.subprocess, "run", fake_run)

    result = compiler.compile_tex(
        tex,
        LocalConfig(preferred_compiler="pdflatex", max_compile_passes=1),
        "../escape.pdf",
    )

    assert result.ok is False
    assert "Nome PDF non valido" in result.output
    assert calls == []
