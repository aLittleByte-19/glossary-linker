from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import re
from urllib.request import urlopen

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from markupsafe import Markup, escape

from glossary_linker.core.compiler import compile_tex, test_environment
from glossary_linker.core.config import (
    EditorialConfig,
    LocalConfig,
    load_editorial_config,
    load_local_config,
    save_editorial_config,
    save_local_config,
)
from glossary_linker.core.formatter import format_glossary_text
from glossary_linker.core.glossary import parse_glossary_file, parse_glossary_text
from glossary_linker.core.glossary import (
    load_entries_store,
    merge_detected_with_store,
    save_entries_store,
)
from glossary_linker.core.linker import (
    collect_manual_occurrences,
    discover_tex_files,
    process_files,
    save_report_json,
    save_report_markdown,
)
from glossary_linker.core.models import GlossaryEntry, Occurrence


ROOT = Path.cwd()
EDITORIAL_PATH = ROOT / "glossary-linker.yml"
LOCAL_PATH = ROOT / "glossary-linker.local.yml"
ENTRIES_PATH = ROOT / "glossary-linker.entries.yml"
JOBS: dict[str, dict] = {}


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "glossary-linker-local-dev"

    @app.get("/")
    def operation():
        local = _load_local()
        selected_operation = session.get("operation", local.last_operation)
        return render_template("operation.html", local=local, selected_operation=selected_operation)

    @app.post("/operation")
    def set_operation():
        session["operation"] = request.form.get("operation", "link-documents")
        local = _load_local()
        local.last_operation = session["operation"]
        save_local_config(local, LOCAL_PATH)
        if session["operation"] == "format-glossary":
            return redirect(url_for("format_glossary"))
        return redirect(url_for("glossary_rules"))

    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        local = _load_local()
        tab = request.args.get("tab", "environment")
        if request.method == "POST":
            local = LocalConfig(
                default_repo_root=request.form.get("default_repo_root", "."),
                last_operation=local.last_operation,
                last_source_dir=local.last_source_dir,
                last_review_order=local.last_review_order,
                last_new_entry_ids=local.last_new_entry_ids,
                latexmk_path=request.form.get("latexmk_path", "latexmk"),
                pdflatex_path=request.form.get("pdflatex_path", "pdflatex"),
                xelatex_path=request.form.get("xelatex_path", "xelatex"),
                lualatex_path=request.form.get("lualatex_path", "lualatex"),
                preferred_compiler=request.form.get("preferred_compiler", "latexmk"),
                compile_timeout_seconds=int(request.form.get("compile_timeout_seconds", "120") or 120),
                max_compile_passes=int(request.form.get("max_compile_passes", "2") or 2),
                temporary_directory=request.form.get("temporary_directory", ""),
                local_server_port=int(request.form.get("local_server_port", "8765") or 8765),
                auto_open_pdf=bool(request.form.get("auto_open_pdf")),
                clean_aux_files=bool(request.form.get("clean_aux_files")),
                log_level=request.form.get("log_level", "INFO"),
                preferred_browser=request.form.get("preferred_browser", ""),
            )
            save_local_config(local, LOCAL_PATH)
            flash("Impostazioni ambiente salvate in glossary-linker.local.yml.")
            return redirect(url_for("settings"))
        tools = test_environment(local) if tab == "check" else {}
        return render_template("settings.html", local=local, tools=tools, tab=tab)

    @app.get("/environment")
    def environment():
        return redirect(url_for("settings", tab="check"))

    @app.post("/pick-path")
    def pick_path():
        payload = request.get_json(silent=True) or {}
        try:
            paths = _open_native_picker(
                kind=payload.get("kind", "file"),
                multiple=bool(payload.get("multiple")),
                initial=payload.get("initial", ""),
            )
            root = payload.get("root", "")
            if root:
                paths = [_relative_to_root(Path(path), root) for path in paths]
        except Exception as exc:  # pragma: no cover - depends on local desktop session
            return jsonify({"ok": False, "error": str(exc), "paths": []}), 500
        return jsonify({"ok": True, "paths": paths})

    @app.post("/glossary-preview")
    def glossary_preview():
        payload = request.get_json(silent=True) or {}
        config = _load_editorial()
        local = _load_local()
        config.glossary_path = payload.get("glossary_path", config.glossary_path)
        config.glossary_pdf_url = payload.get("glossary_pdf_url", config.glossary_pdf_url)
        config.anchor_format = payload.get("anchor_format", config.anchor_format)
        root = payload.get("repo_root", local.default_repo_root)
        local.default_repo_root = root or local.default_repo_root
        try:
            detected = _load_detected_entries(config, root)
            stored = load_entries_store(ENTRIES_PATH)
            entries, new_count = merge_detected_with_store(detected, stored)
            save_entries_store(entries, ENTRIES_PATH)
            save_editorial_config(config, EDITORIAL_PATH)
            save_local_config(local, LOCAL_PATH)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc), "stats": {}}), 400
        return jsonify({"ok": True, "stats": _entries_stats(entries, new_count)})

    @app.post("/wizard-state")
    def wizard_state():
        payload = request.get_json(silent=True) or {}
        config = _load_editorial()
        local = _load_local()
        _update_config_from_payload(config, payload)
        _update_local_from_payload(local, payload)
        save_editorial_config(config, EDITORIAL_PATH)
        save_local_config(local, LOCAL_PATH)
        return jsonify({"ok": True})

    @app.post("/discover-tex")
    def discover_tex():
        payload = request.get_json(silent=True) or {}
        config = _load_editorial()
        local = _load_local()
        _update_config_from_payload(config, payload)
        _update_local_from_payload(local, payload)
        root = _path_from(local.default_repo_root, ".")
        source_dir = _path_from(payload.get("source_dir", local.last_source_dir), root)
        try:
            files, excluded = _discover_tex_under(root, source_dir, config)
            save_editorial_config(config, EDITORIAL_PATH)
            save_local_config(local, LOCAL_PATH)
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc), "files": [], "excluded": []}), 400
        return jsonify({
            "ok": True,
            "files": [_relative_to_root(path, str(root)) for path in files],
            "excluded": [_relative_to_root(path, str(root)) for path in excluded],
        })

    @app.route("/entries", methods=["GET", "POST"])
    def entries():
        stored = load_entries_store(ENTRIES_PATH)
        if request.method == "POST":
            updated = _entries_from_form(stored)
            save_entries_store(updated, ENTRIES_PATH)
            flash("Glossario rilevato salvato in glossary-linker.entries.yml.")
            return redirect(url_for("entries"))
        return render_template("entries.html", entries=stored, entries_path=ENTRIES_PATH)

    @app.route("/glossary", methods=["GET", "POST"])
    def glossary_rules():
        config = _load_editorial()
        local = _load_local()
        formatted_text = ""
        entries: list[GlossaryEntry] = load_entries_store(ENTRIES_PATH)
        operation = session.get("operation", local.last_operation)

        if request.method == "POST":
            config.glossary_path = request.form.get("glossary_path", config.glossary_path)
            config.glossary_pdf_url = request.form.get("glossary_pdf_url", config.glossary_pdf_url)
            config.anchor_format = request.form.get("anchor_format", config.anchor_format)
            _update_rules_from_form(config)
            _update_local_from_form(local)
            save_editorial_config(config, EDITORIAL_PATH)
            save_local_config(local, LOCAL_PATH)
            action = request.form.get("action", "preview")

            glossary_text = _submitted_glossary_text()
            if action in {"format", "save_formatted"} and glossary_text:
                formatted_text = format_glossary_text(glossary_text)
                entries = parse_glossary_text(formatted_text, config)
                if action == "save_formatted":
                    target = _path_from(config.glossary_path, local.default_repo_root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(formatted_text, encoding="utf-8")
                    flash(f"Glossario formattato salvato in {target}.")
            else:
                entries = load_entries_store(ENTRIES_PATH)

            if action == "continue":
                if not entries:
                    entries = _load_entries_from_config_path(config)
                    save_entries_store(entries, ENTRIES_PATH)
                return _start_processing(config, local, entries, operation)

        return render_template(
            "glossary.html",
            config=config,
            local=local,
            entries=entries,
            entries_path=ENTRIES_PATH,
            formatted_text=formatted_text,
            operation=operation,
        )

    @app.route("/format-glossary", methods=["GET", "POST"])
    def format_glossary():
        config = _load_editorial()
        local = _load_local()
        formatted_text = ""
        entries: list[GlossaryEntry] = []
        if request.method == "POST":
            config.glossary_path = request.form.get("glossary_path", config.glossary_path)
            glossary_text = _submitted_glossary_text()
            action = request.form.get("action", "format")
            if glossary_text:
                formatted_text = format_glossary_text(glossary_text)
                entries = parse_glossary_text(formatted_text, config)
            if action == "save_formatted" and formatted_text:
                target = _path_from(config.glossary_path, request.form.get("repo_root", local.default_repo_root))
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(formatted_text, encoding="utf-8")
                flash(f"Glossario formattato salvato in {target}.")
        return render_template(
            "format_glossary.html",
            config=config,
            local=local,
            formatted_text=formatted_text,
            entries=entries,
        )

    @app.route("/review/<job_id>/<int:index>", methods=["GET", "POST"])
    def review(job_id: str, index: int):
        job = JOBS[job_id]
        occurrences = [_occurrence_from_dict(item) for item in job["occurrences"]]
        if request.method == "POST":
            action = request.form.get("action", "next")
            current = occurrences[index]
            _apply_review_action(job, occurrences, current, action)
            if action == "prev":
                index = max(0, index - 1)
            elif action == "finish":
                return redirect(url_for("output", job_id=job_id))
            elif action in _decision_actions():
                next_index = _next_pending_index(occurrences, job["decisions"], index)
                if next_index is None:
                    return redirect(url_for("output", job_id=job_id))
                index = next_index
            elif index + 1 >= len(occurrences):
                return redirect(url_for("output", job_id=job_id))
            else:
                index += 1
            return redirect(url_for("review", job_id=job_id, index=index))

        occurrence = occurrences[index]
        decision = job["decisions"].get(occurrence.id)
        entries = [_entry_from_dict(item) for item in job["entries"]]
        entry = next((item for item in entries if item.id == occurrence.entry_id), GlossaryEntry(occurrence.entry_id, occurrence.term))
        same_term = [item for item in occurrences if item.entry_id == occurrence.entry_id]
        term_ids = list(dict.fromkeys(item.entry_id for item in occurrences))
        return render_template(
            "review.html",
            job_id=job_id,
            occurrence=occurrence,
            entry=entry,
            highlighted_context=_highlight_context(occurrence.context, occurrence.visible_text),
            index=index,
            total=len(occurrences),
            same_term_index=same_term.index(occurrence) + 1,
            same_term_total=len(same_term),
            term_index=term_ids.index(occurrence.entry_id) + 1,
            term_total=len(term_ids),
            decision=decision,
        )

    @app.get("/output/<job_id>")
    def output(job_id: str):
        job = JOBS[job_id]
        config = _editorial_from_dict(job["config"])
        entries = [_entry_from_dict(item) for item in job["entries"]]
        paths = [Path(value) for value in job["paths"]]
        decisions = job.get("decisions", {})
        results, report = process_files(paths, entries, config, decisions)
        report.excluded_files = [Path(value) for value in job.get("excluded", [])]
        report.warnings.extend(job.get("warnings", []))
        job["results"] = [{"source": str(item.source_path), "output": str(item.output_path), "text": item.linked_text} for item in results]
        job["report"] = asdict(report)
        root = Path(job.get("root", ROOT))
        output_items = [_output_item(result, root) for result in results]
        return render_template(
            "output.html",
            job_id=job_id,
            results=output_items,
            report=report,
            has_review=bool(job.get("occurrences")),
        )

    @app.post("/save/<job_id>")
    def save_output(job_id: str):
        job = JOBS[job_id]
        mode = request.form.get("mode", "linked")
        source = request.form.get("source", "")
        saved: list[str] = []
        for item in job.get("results", []):
            if source and item["source"] != source:
                continue
            target = Path(item["source"]) if mode == "overwrite" else Path(item["output"])
            target.write_text(item["text"], encoding="utf-8")
            saved.append(str(target))
        if request.form.get("report_format") == "json":
            save_report_json(_report_from_dict(job["report"]), ROOT / "glossary-linker-report.json")
        else:
            save_report_markdown(_report_from_dict(job["report"]), ROOT / "glossary-linker-report.md")
        flash("Salvati: " + ", ".join(saved))
        return redirect(url_for("output", job_id=job_id))

    @app.post("/compile/<job_id>")
    def compile_output(job_id: str):
        local = _load_local()
        source = request.form.get("source", "")
        pdf_name = request.form.get("pdf_name") or None
        job = JOBS[job_id]
        for item in job.get("results", []):
            if item["source"] == source:
                target = Path(item["output"])
                target.write_text(item["text"], encoding="utf-8")
                result = compile_tex(target, local, pdf_name)
                flash(("Compilazione riuscita: " if result.ok else "Compilazione fallita: ") + " ".join(result.command))
                if not result.ok:
                    flash(result.output[-2000:])
                break
        return redirect(url_for("output", job_id=job_id))

    return app


def main() -> None:
    local = _load_local()
    app = create_app()
    app.run(host="127.0.0.1", port=local.local_server_port, debug=False)


def _load_editorial() -> EditorialConfig:
    return load_editorial_config(EDITORIAL_PATH)


def _load_local() -> LocalConfig:
    if LOCAL_PATH.exists():
        return load_local_config(LOCAL_PATH)
    return LocalConfig()


def _submitted_glossary_text() -> str:
    uploaded = request.files.get("glossary_file")
    if uploaded and uploaded.filename:
        return uploaded.read().decode("utf-8")
    return request.form.get("glossary_text", "")


def _open_native_picker(kind: str, multiple: bool = False, initial: str = "") -> list[str]:
    if sys.platform == "darwin":
        return _open_macos_picker(kind, multiple, initial)

    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    initial_path = Path(initial).expanduser() if initial else Path.cwd()
    initial_dir = initial_path if initial_path.is_dir() else initial_path.parent
    options = {"initialdir": str(initial_dir)}
    try:
        if kind == "directory":
            selected = filedialog.askdirectory(**options)
            return [selected] if selected else []
        if multiple:
            selected_many = filedialog.askopenfilenames(**options)
            return [str(path) for path in selected_many]
        selected_one = filedialog.askopenfilename(**options)
        return [selected_one] if selected_one else []
    finally:
        root.destroy()


def _open_macos_picker(kind: str, multiple: bool = False, initial: str = "") -> list[str]:
    initial_dir = _picker_initial_dir(initial)
    prompt = "Seleziona una cartella" if kind == "directory" else "Seleziona uno o piu file"
    if kind == "directory":
        script = (
            f'set selectedPath to choose folder with prompt {_as_applescript_string(prompt)} '
            f'default location POSIX file {_as_applescript_string(str(initial_dir))}\n'
            "return POSIX path of selectedPath"
        )
    elif multiple:
        script = (
            f'set selectedFiles to choose file with prompt {_as_applescript_string(prompt)} '
            f'default location POSIX file {_as_applescript_string(str(initial_dir))} '
            "with multiple selections allowed\n"
            "set oldDelimiters to AppleScript's text item delimiters\n"
            "set AppleScript's text item delimiters to linefeed\n"
            "set outputPaths to {}\n"
            "repeat with selectedFile in selectedFiles\n"
            "  set end of outputPaths to POSIX path of selectedFile\n"
            "end repeat\n"
            "set outputText to outputPaths as text\n"
            "set AppleScript's text item delimiters to oldDelimiters\n"
            "return outputText"
        )
    else:
        script = (
            f'set selectedPath to choose file with prompt {_as_applescript_string(prompt)} '
            f'default location POSIX file {_as_applescript_string(str(initial_dir))}\n'
            "return POSIX path of selectedPath"
        )
    completed = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        if "User canceled" in completed.stderr:
            return []
        raise RuntimeError(completed.stderr.strip() or "Selezione non disponibile")
    return [line for line in completed.stdout.splitlines() if line.strip()]


def _picker_initial_dir(initial: str) -> Path:
    path = Path(initial).expanduser() if initial else Path.cwd()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if path.is_file():
        return path.parent
    if path.is_dir():
        return path
    return Path.cwd()


def _as_applescript_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _load_entries_from_config_path(config: EditorialConfig) -> list[GlossaryEntry]:
    return _load_detected_entries(config, _load_local().default_repo_root)


def _load_detected_entries(config: EditorialConfig, root: str | Path) -> list[GlossaryEntry]:
    if config.glossary_path.startswith(("http://", "https://")):
        with urlopen(config.glossary_path, timeout=10) as response:
            text = response.read().decode("utf-8")
        return parse_glossary_text(text, config)
    path = _path_from(config.glossary_path, root)
    if not path.exists():
        return []
    return parse_glossary_file(path, config)


def _discover_tex_under(root: Path, source_dir: Path, config: EditorialConfig) -> tuple[list[Path], list[Path]]:
    import fnmatch

    root = root.expanduser().resolve()
    source_dir = source_dir.expanduser().resolve()
    if not source_dir.exists() or not source_dir.is_dir():
        raise ValueError(f"La directory sorgente non esiste: {source_dir}")
    glossary = _path_from(config.glossary_path, root) if not config.glossary_path.startswith(("http://", "https://")) else None
    included: list[Path] = []
    excluded: list[Path] = []
    for path in sorted(source_dir.rglob("*.tex")):
        try:
            rel = path.resolve().relative_to(root).as_posix()
        except ValueError:
            rel = path.name
        should_exclude = (
            path.name.endswith(".linked.tex")
            or (glossary is not None and path.resolve() == glossary.resolve())
            or any(fnmatch.fnmatch(rel, pattern) for pattern in config.exclude_file_patterns)
        )
        if should_exclude:
            excluded.append(path)
        else:
            included.append(path)
    return included, excluded


def _entry_payload(entry: GlossaryEntry) -> dict[str, object]:
    return {
        "id": entry.id,
        "term": entry.term,
        "definition": entry.definition,
        "aliases": entry.aliases,
        "mode": entry.mode,
    }


def _entries_stats(entries: list[GlossaryEntry], new_count: int = 0) -> dict[str, int]:
    manual = sum(1 for entry in entries if entry.mode == "manual")
    return {
        "total": len(entries),
        "manual": manual,
        "automatic": len(entries) - manual,
        "new": new_count,
    }


def _entries_config(entries: list[GlossaryEntry]) -> dict[str, dict[str, object]]:
    return {
        entry.id: {"mode": entry.mode, "aliases": entry.aliases}
        for entry in entries
    }


def _update_rules_from_form(config: EditorialConfig) -> None:
    config.exclude_file_patterns = _lines_from_form("exclude_file_patterns", config.exclude_file_patterns)
    config.ignored_environments = _lines_from_form("ignored_environments", config.ignored_environments)
    config.ignored_commands = _lines_from_form("ignored_commands", config.ignored_commands)
    sections = request.form.getlist("ignored_sections")
    config.ignored_sections = sections if sections else []
    skip_titles = bool(request.form.get("skip_titles"))
    title_commands = ["part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph", "title", "caption"]
    commands = [command for command in config.ignored_commands if command not in title_commands]
    if skip_titles:
        commands.extend(title_commands)
    config.ignored_commands = list(dict.fromkeys(commands))


def _update_local_from_form(local: LocalConfig) -> None:
    local.default_repo_root = request.form.get("repo_root", local.default_repo_root)
    local.last_operation = session.get("operation", local.last_operation)
    local.last_source_dir = request.form.get("source_dir", local.last_source_dir)
    local.last_review_order = request.form.get("review_order", local.last_review_order)
    local.last_new_entry_ids = request.form.get("new_entry_ids", local.last_new_entry_ids)


def _update_config_from_payload(config: EditorialConfig, payload: dict) -> None:
    config.glossary_path = payload.get("glossary_path", config.glossary_path)
    config.glossary_pdf_url = payload.get("glossary_pdf_url", config.glossary_pdf_url)
    config.anchor_format = payload.get("anchor_format", config.anchor_format)
    config.exclude_file_patterns = _list_from_payload(payload, "exclude_file_patterns", config.exclude_file_patterns)
    config.ignored_environments = _list_from_payload(payload, "ignored_environments", config.ignored_environments)
    config.ignored_commands = _list_from_payload(payload, "ignored_commands", config.ignored_commands)
    config.ignored_sections = _list_from_payload(payload, "ignored_sections", config.ignored_sections)
    if "skip_titles" in payload:
        skip_titles = bool(payload.get("skip_titles"))
        title_commands = ["part", "chapter", "section", "subsection", "subsubsection", "paragraph", "subparagraph", "title", "caption"]
        commands = [command for command in config.ignored_commands if command not in title_commands]
        if skip_titles:
            commands.extend(title_commands)
        config.ignored_commands = list(dict.fromkeys(commands))


def _update_local_from_payload(local: LocalConfig, payload: dict) -> None:
    local.default_repo_root = payload.get("repo_root", local.default_repo_root) or local.default_repo_root
    local.last_operation = payload.get("operation", local.last_operation) or local.last_operation
    local.last_source_dir = payload.get("source_dir", local.last_source_dir) or local.last_source_dir
    local.last_review_order = payload.get("review_order", local.last_review_order) or local.last_review_order
    local.last_new_entry_ids = payload.get("new_entry_ids", local.last_new_entry_ids)


def _list_from_payload(payload: dict, name: str, fallback: list[str]) -> list[str]:
    value = payload.get(name)
    if value is None:
        return fallback
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [line.strip() for line in str(value).splitlines() if line.strip()]


def _lines_from_form(name: str, fallback: list[str]) -> list[str]:
    raw = request.form.get(name)
    if raw is None:
        return fallback
    return [line.strip() for line in raw.splitlines() if line.strip()]


def _entries_from_form(fallback: list[GlossaryEntry]) -> list[GlossaryEntry]:
    by_id = {entry.id: entry for entry in fallback}
    result: list[GlossaryEntry] = []
    for entry_id in request.form.getlist("entry_id"):
        base = by_id.get(entry_id, GlossaryEntry(entry_id, request.form.get(f"term_{entry_id}", entry_id)))
        aliases = [item.strip() for item in request.form.get(f"aliases_{entry_id}", "").split(",") if item.strip()]
        mode = "manual" if request.form.get(f"mode_{entry_id}") == "manual" else "automatic"
        result.append(GlossaryEntry(base.id, base.term, base.definition, aliases, mode))
    return result


def _start_processing(config: EditorialConfig, local: LocalConfig, entries: list[GlossaryEntry], operation: str):
    root = _path_from(request.form.get("repo_root", local.default_repo_root), ".")
    excluded: list[Path] = []
    warnings: list[str] = []
    if operation == "update-glossary":
        paths, excluded = discover_tex_files(root, config)
        selected_ids = {value.strip() for value in request.form.get("new_entry_ids", "").split(",") if value.strip()}
        if selected_ids:
            entries = [entry for entry in entries if entry.id in selected_ids]
    else:
        raw_paths = request.form.get("tex_paths", "")
        paths, warnings = _resolve_selected_tex_paths(raw_paths, root)

    if not paths:
        flash("Nessun file .tex valido selezionato. Controlla root progetto e percorsi relativi.")
        for warning in warnings[:5]:
            flash(warning)
        return redirect(url_for("glossary_rules"))

    occurrences = collect_manual_occurrences(paths, entries, config)
    occurrences = _sort_occurrences(occurrences, entries, request.form.get("review_order", "by_term"))
    job_id = uuid.uuid4().hex
    JOBS[job_id] = {
        "config": asdict(config),
        "entries": [asdict(entry) for entry in entries],
        "paths": [str(path) for path in paths],
        "root": str(root),
        "excluded": [str(path) for path in excluded],
        "warnings": warnings,
        "review_order": request.form.get("review_order", "by_term"),
        "occurrences": [asdict(item) for item in occurrences],
        "decisions": {},
    }
    if occurrences:
        return redirect(url_for("review", job_id=job_id, index=0))
    return redirect(url_for("output", job_id=job_id))


def _resolve_selected_tex_paths(raw_paths: str, root: Path) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    for raw in [line.strip() for line in raw_paths.splitlines() if line.strip()]:
        path = _path_from(raw, root)
        if path.exists() and path.is_file():
            resolved = path.resolve()
            if resolved not in seen:
                paths.append(resolved)
                seen.add(resolved)
            continue

        recovered = _recover_tex_path(raw, root)
        if recovered:
            if recovered not in seen:
                paths.append(recovered)
                seen.add(recovered)
            warnings.append(f"Percorso corretto automaticamente: {raw} -> {_relative_to_root(recovered, str(root))}")
            continue

        warnings.append(f"File ignorato perché non trovato: {raw}")
    return paths, warnings


def _recover_tex_path(raw: str, root: Path) -> Path | None:
    candidate = Path(raw)
    if candidate.is_absolute() or candidate.name != raw:
        return None
    matches = sorted(path.resolve() for path in root.rglob(candidate.name) if path.is_file())
    if len(matches) == 1:
        return matches[0]
    return None


def _sort_occurrences(occurrences: list[Occurrence], entries: list[GlossaryEntry], order: str) -> list[Occurrence]:
    terms = {entry.id: entry.term.casefold() for entry in entries}
    if order == "by_file":
        return sorted(occurrences, key=lambda item: (str(item.file_path).casefold(), item.line_number, item.start, terms.get(item.entry_id, item.term.casefold())))
    return sorted(occurrences, key=lambda item: (terms.get(item.entry_id, item.term.casefold()), str(item.file_path).casefold(), item.line_number, item.start))


def _output_item(result, root: Path) -> dict[str, object]:
    return {
        "source": result.source_path,
        "output": result.output_path,
        "source_label": _relative_to_root(result.source_path, str(root)),
        "output_label": _relative_to_root(result.output_path, str(root)),
        "default_pdf_name": result.source_path.with_suffix(".pdf").name,
    }


def _apply_review_action(job: dict, occurrences: list[Occurrence], current: Occurrence, action: str) -> None:
    decisions = job["decisions"]
    if action == "link":
        decisions[current.id] = True
    elif action == "skip":
        decisions[current.id] = False
    elif action in {"link_file_term", "skip_file_term", "link_term_all", "skip_term_all", "skip_file"}:
        value = action.startswith("link")
        for occurrence in occurrences:
            same_term = occurrence.entry_id == current.entry_id
            same_file = occurrence.file_path == current.file_path
            if action in {"link_file_term", "skip_file_term"} and same_term and same_file:
                decisions[occurrence.id] = value
            elif action in {"link_term_all", "skip_term_all"} and same_term:
                decisions[occurrence.id] = value
            elif action == "skip_file" and same_file:
                decisions[occurrence.id] = False


def _decision_actions() -> set[str]:
    return {"link", "skip", "link_file_term", "skip_file_term", "link_term_all", "skip_term_all", "skip_file"}


def _next_pending_index(occurrences: list[Occurrence], decisions: dict[str, bool], current_index: int) -> int | None:
    for index in range(current_index + 1, len(occurrences)):
        if occurrences[index].id not in decisions:
            return index
    for index in range(0, current_index):
        if occurrences[index].id not in decisions:
            return index
    return None


def _highlight_context(context: str, visible_text: str) -> Markup:
    escaped_context = escape(context)
    escaped_word = escape(visible_text)
    pattern = re.compile(re.escape(str(escaped_word)), re.IGNORECASE)
    highlighted = pattern.sub(lambda match: f"<mark>{match.group(0)}</mark>", str(escaped_context), count=1)
    return Markup(highlighted)


def _path_from(value: str, base: str | Path) -> Path:
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return (Path(base).expanduser() / path).resolve()


def _relative_to_root(path: Path, root: str) -> str:
    root_path = _path_from(root, ".")
    resolved = path.expanduser().resolve()
    try:
        return resolved.relative_to(root_path).as_posix()
    except ValueError:
        return str(resolved)


def _entry_from_dict(data: dict) -> GlossaryEntry:
    return GlossaryEntry(**data)


def _occurrence_from_dict(data: dict) -> Occurrence:
    data = dict(data)
    data["file_path"] = Path(data["file_path"])
    return Occurrence(**data)


def _editorial_from_dict(data: dict) -> EditorialConfig:
    return EditorialConfig(**data)


def _report_from_dict(data: dict):
    from glossary_linker.core.models import ProcessingReport

    data = dict(data)
    data["processed_files"] = [Path(value) for value in data.get("processed_files", [])]
    data["excluded_files"] = [Path(value) for value in data.get("excluded_files", [])]
    return ProcessingReport(**data)


if __name__ == "__main__":
    main()
