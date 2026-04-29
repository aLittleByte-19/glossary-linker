from __future__ import annotations

import uuid
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import re
from urllib.request import urlopen

from flask import Flask, Response, flash, jsonify, redirect, render_template, request, session, url_for
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
from glossary_linker.core.html import render_glossary_html, save_glossary_html
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
GUIDE_PATH = ROOT / "docs" / "USER_GUIDE.md"
JOBS: dict[str, dict] = {}


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = "glossary-linker-local-dev"

    @app.get("/")
    def operation():
        local = _load_local()
        config = _load_editorial()
        entries = load_entries_store(ENTRIES_PATH)
        selected_operation = session.get("operation", local.last_operation)
        return render_template(
            "operation.html",
            local=local,
            config=config,
            home_status=_home_status(local, config, entries),
            selected_operation=selected_operation,
            has_operation=bool(session.get("operation")),
        )

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
        config = _load_editorial()
        tab = request.args.get("tab", "environment")
        if request.method == "POST":
            if request.form.get("settings_scope") == "rules":
                _update_rules_from_form(config)
                save_editorial_config(config, EDITORIAL_PATH)
                flash("Regole editoriali salvate in glossary-linker.yml.", "success")
                return redirect(url_for("settings", tab="rules"))
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
                clean_compile_artifacts=bool(request.form.get("clean_compile_artifacts")),
                log_level=request.form.get("log_level", "INFO"),
                preferred_browser=request.form.get("preferred_browser", ""),
            )
            save_local_config(local, LOCAL_PATH)
            flash("Impostazioni ambiente salvate in glossary-linker.local.yml.", "success")
            return redirect(url_for("settings", tab="environment"))
        tools = test_environment(local) if tab == "check" else {}
        return render_template("settings.html", local=local, config=config, tools=tools, tab=tab)

    @app.get("/help")
    def help_page():
        guide_text = GUIDE_PATH.read_text(encoding="utf-8") if GUIDE_PATH.exists() else "Guida non trovata."
        headings = _collect_markdown_headings(guide_text)
        return render_template(
            "help.html",
            guide_html=_render_markdown(guide_text, headings),
            guide_toc=_render_markdown_toc(headings),
            guide_path=GUIDE_PATH,
        )

    @app.get("/glossary-html")
    def glossary_html_page():
        config = _load_editorial()
        try:
            entries = _load_entries_from_config_path(config)
        except Exception:
            entries = load_entries_store(ENTRIES_PATH)
        return Response(render_glossary_html(entries), mimetype="text/html; charset=utf-8")

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
        config.glossary_html_url = payload.get("glossary_html_url", config.glossary_html_url) or _local_glossary_html_url(local)
        config.glossary_link_target = "html"
        config.html_anchor_format = payload.get("html_anchor_format", config.html_anchor_format)
        config.glossary_detection = payload.get("glossary_detection", config.glossary_detection)
        root = payload.get("repo_root", local.default_repo_root)
        local.default_repo_root = root or local.default_repo_root
        try:
            detected = _load_detected_entries(config, root)
            save_editorial_config(config, EDITORIAL_PATH)
            save_local_config(local, LOCAL_PATH)
            if not detected:
                return jsonify({"ok": True, "stats": _entries_stats([], 0)})
            stored = [entry for entry in load_entries_store(ENTRIES_PATH) if entry.id not in set(config.excluded_entry_ids)]
            entries, new_count = merge_detected_with_store(detected, stored)
            save_entries_store(entries, ENTRIES_PATH)
            _persist_glossary_html(config, local, entries)
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
            flash("Glossario rilevato salvato in glossary-linker.entries.yml.", "success")
            return redirect(url_for("entries"))
        return render_template("entries.html", entries=stored, entries_path=ENTRIES_PATH)

    @app.route("/glossary", methods=["GET", "POST"])
    def glossary_rules():
        if not session.get("operation"):
            flash("Scegli prima il tipo di operazione da svolgere.", "warning")
            return redirect(url_for("operation"))
        config = _load_editorial()
        local = _load_local()
        formatted_text = ""
        entries: list[GlossaryEntry] = [entry for entry in load_entries_store(ENTRIES_PATH) if entry.id not in set(config.excluded_entry_ids)]
        operation = session["operation"]

        if request.method == "POST":
            config.glossary_path = request.form.get("glossary_path", config.glossary_path)
            config.glossary_html_url = request.form.get("glossary_html_url", config.glossary_html_url) or _local_glossary_html_url(local)
            config.glossary_link_target = "html"
            config.html_anchor_format = request.form.get("html_anchor_format", config.html_anchor_format)
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
                    html_target = _default_glossary_html_path(target)
                    save_glossary_html(entries, html_target)
                    config.glossary_html_url = _local_glossary_html_url(local)
                    save_editorial_config(config, EDITORIAL_PATH)
                    flash(f"Glossario formattato salvato in {target}.", "success")
                    flash(f"Glossario HTML salvato in {html_target}.", "success")
            else:
                entries = [entry for entry in load_entries_store(ENTRIES_PATH) if entry.id not in set(config.excluded_entry_ids)]

            if action == "continue":
                detected = _load_detected_entries(config, local.default_repo_root)
                if detected:
                    stored = [entry for entry in load_entries_store(ENTRIES_PATH) if entry.id not in set(config.excluded_entry_ids)]
                    entries, _new_count = merge_detected_with_store(detected, stored)
                    save_entries_store(entries, ENTRIES_PATH)
                elif not entries:
                    entries = _load_entries_from_config_path(config)
                    save_entries_store(entries, ENTRIES_PATH)
                _persist_glossary_html(config, local, entries)
                return _start_processing(config, local, entries, operation)

        return render_template(
            "glossary.html",
            config=config,
            local=local,
            entries=entries,
            entries_path=ENTRIES_PATH,
            formatted_text=formatted_text,
            operation=operation,
            local_glossary_html_url=_local_glossary_html_url(local),
        )

    @app.route("/format-glossary", methods=["GET", "POST"])
    def format_glossary():
        config = _load_editorial()
        local = _load_local()
        formatted_text = ""
        raw_text = ""
        entries: list[GlossaryEntry] = []
        source_path = request.form.get("source_glossary_path", config.glossary_path) if request.method == "POST" else config.glossary_path
        output_path = request.form.get("output_path", "") if request.method == "POST" else ""
        if request.method == "POST":
            config.glossary_detection = request.form.get("glossary_detection", config.glossary_detection)
            save_editorial_config(config, EDITORIAL_PATH)
            action = request.form.get("action", "format")
            raw_text = request.form.get("glossary_text", "")
            formatted_text = request.form.get("formatted_text", "")
            try:
                glossary_text = formatted_text if action in {"save_formatted", "compile_formatted"} and formatted_text else _format_glossary_input(source_path, raw_text)
            except Exception as exc:
                flash(str(exc), "error")
                glossary_text = ""
            if glossary_text:
                entries = parse_glossary_text(glossary_text, config)
                formatted_text = format_glossary_text(glossary_text)
                if not entries:
                    entries = parse_glossary_text(formatted_text, EditorialConfig(glossary_detection="auto"))
            if action in {"save_formatted", "compile_formatted"} and formatted_text:
                entries = _format_entries_from_form(entries)
                save_entries_store(entries, ENTRIES_PATH)
                target = _format_output_target(request.form, source_path)
                if target is None:
                    flash("Per sovrascrivere serve un file glossario sorgente selezionato.", "error")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(formatted_text, encoding="utf-8")
                    html_target = _default_glossary_html_path(target)
                    save_glossary_html(entries, html_target)
                    config.glossary_path = str(target)
                    config.glossary_html_url = _local_glossary_html_url(local)
                    config.glossary_link_target = "html"
                    save_editorial_config(config, EDITORIAL_PATH)
                    flash(f"Glossario formattato salvato in {target}.", "success")
                    flash(f"Glossario HTML salvato in {html_target}.", "success")
                    if action == "compile_formatted":
                        pdf_name = request.form.get("pdf_name") or None
                        result = compile_tex(target, local, pdf_name)
                        category = "success" if result.ok else "error"
                        flash(("Compilazione riuscita: " if result.ok else "Compilazione fallita: ") + " ".join(result.command), category)
                        if not result.ok:
                            flash(result.output[-2000:], "error")
        return render_template(
            "format_glossary.html",
            config=config,
            local=local,
            raw_text=raw_text,
            source_path=source_path,
            output_path=output_path or _default_formatted_path(source_path),
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
        if request.form.get("include_report"):
            if request.form.get("report_format") == "json":
                save_report_json(_report_from_dict(job["report"]), ROOT / "glossary-linker-report.json")
                saved.append(str(ROOT / "glossary-linker-report.json"))
            else:
                save_report_markdown(_report_from_dict(job["report"]), ROOT / "glossary-linker-report.md")
                saved.append(str(ROOT / "glossary-linker-report.md"))
        if saved:
            flash("Salvataggio completato: " + ", ".join(saved), "success")
        else:
            flash("Nessun file salvato: controlla i risultati disponibili.", "warning")
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
                category = "success" if result.ok else "error"
                flash(("Compilazione riuscita: " if result.ok else "Compilazione fallita: ") + " ".join(result.command), category)
                if not result.ok:
                    flash(result.output[-2000:], "error")
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


def _home_status(local: LocalConfig, config: EditorialConfig, entries: list[GlossaryEntry]) -> dict[str, object]:
    root = _path_from(local.default_repo_root or ".", ".")
    glossary_is_url = config.glossary_path.startswith(("http://", "https://"))
    glossary_path = None if glossary_is_url else _path_from(config.glossary_path, root)
    manual = sum(1 for entry in entries if entry.mode == "manual")
    return {
        "root_label": str(root),
        "root_ok": root.exists() and root.is_dir(),
        "glossary_label": config.glossary_path or "Non impostato",
        "glossary_ok": glossary_is_url or bool(glossary_path and glossary_path.exists()),
        "glossary_html_ok": bool(config.glossary_html_url.strip()),
        "entries_total": len(entries),
        "entries_manual": manual,
        "entries_automatic": len(entries) - manual,
        "detection_label": {
            "auto": "Automatico",
            "structured": "Macro strutturata",
            "subsection": "Sezioni LaTeX",
        }.get(config.glossary_detection, "Automatico"),
        "rules_total": len(config.exclude_file_patterns) + len(config.ignored_environments) + len(config.ignored_commands),
    }


def _submitted_glossary_text() -> str:
    uploaded = request.files.get("glossary_file")
    if uploaded and uploaded.filename:
        return uploaded.read().decode("utf-8")
    return request.form.get("glossary_text", "")


def _collect_markdown_headings(text: str) -> list[dict[str, str | int]]:
    headings: list[dict[str, str | int]] = []
    seen: dict[str, int] = {}
    in_code = False
    for line_number, raw_line in enumerate(text.splitlines()):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if not heading:
            continue
        text_value = heading.group(2).strip()
        anchor = _markdown_anchor(text_value, seen)
        headings.append({
            "line": line_number,
            "level": len(heading.group(1)),
            "text": text_value,
            "id": anchor,
        })
    return headings


def _markdown_anchor(text: str, seen: dict[str, int]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "sezione"
    count = seen.get(base, 0)
    seen[base] = count + 1
    return base if count == 0 else f"{base}-{count + 1}"


def _render_markdown_toc(headings: list[dict[str, str | int]]) -> Markup:
    toc_items = [item for item in headings if item["level"] in {2, 3}]
    if not toc_items:
        return Markup("")
    html = ['<nav class="doc-toc" aria-label="Indice guida" data-scrollspy><strong>In questa guida</strong><ol class="toc-tree">']
    open_section = False
    for item in toc_items:
        level = int(item["level"])
        link = (
            f'<a href="#{escape(str(item["id"]))}" data-scroll-link>'
            f'{escape(str(item["text"]))}</a>'
        )
        if level == 2:
            if open_section:
                html.append("</ol></li>")
            html.append(f'<li class="level-2">{link}<ol>')
            open_section = True
        elif open_section:
            html.append(f'<li class="level-3">{link}</li>')
        else:
            html.append(f'<li class="level-2 orphan">{link}<ol></ol></li>')
    if open_section:
        html.append("</ol></li>")
    html.append("</ol></nav>")
    return Markup("\n".join(str(part) for part in html))


def _render_markdown(text: str, headings: list[dict[str, str | int]] | None = None) -> Markup:
    html: list[str] = []
    list_type: str | None = None
    in_code = False
    code_lines: list[str] = []
    headings_by_line = {int(item["line"]): item for item in (headings or _collect_markdown_headings(text))}

    def close_list() -> None:
        nonlocal list_type
        if list_type:
            html.append(f"</{list_type}>")
            list_type = None

    for line_number, raw_line in enumerate(text.splitlines()):
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                html.append(Markup('<pre tabindex="0"><code>') + escape("\n".join(code_lines)) + Markup("</code></pre>"))
                code_lines = []
                in_code = False
            else:
                close_list()
                in_code = True
            continue
        if in_code:
            code_lines.append(line)
            continue
        if not stripped:
            close_list()
            continue
        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            close_list()
            level = len(heading.group(1))
            anchor = escape(str(headings_by_line.get(line_number, {}).get("id", "")))
            anchor_attr = f' id="{anchor}"' if anchor else ""
            html.append(f"<h{level}{anchor_attr}>{_inline_markdown(heading.group(2))}</h{level}>")
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        numbered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if bullet or numbered:
            desired = "ul" if bullet else "ol"
            if list_type != desired:
                close_list()
                list_type = desired
                html.append(f"<{list_type}>")
            content = bullet.group(1) if bullet else numbered.group(1)
            html.append(f"<li>{_inline_markdown(content)}</li>")
            continue
        close_list()
        html.append(f"<p>{_inline_markdown(stripped)}</p>")

    if in_code:
        html.append(Markup('<pre tabindex="0"><code>') + escape("\n".join(code_lines)) + Markup("</code></pre>"))
    close_list()
    return Markup("\n".join(str(item) for item in html))


def _inline_markdown(text: str) -> Markup:
    escaped = str(escape(text))
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return Markup(escaped)


def _format_glossary_input(source_path: str, pasted_text: str) -> str:
    if pasted_text.strip():
        return pasted_text
    if not source_path.strip():
        return ""
    path = _path_from(source_path, ".")
    if not path.exists():
        raise FileNotFoundError(f"Glossario sorgente non trovato: {path}")
    return path.read_text(encoding="utf-8")


def _default_formatted_path(source_path: str) -> str:
    if source_path.strip():
        path = _path_from(source_path, ".")
        return str(path.with_name(path.stem + ".formatted.tex"))
    return str((ROOT / "Glossario.formatted.tex").resolve())


def _default_glossary_html_path(tex_path: Path) -> Path:
    return tex_path.with_suffix(".html")


def _local_glossary_html_url(local: LocalConfig) -> str:
    port = local.local_server_port or 8765
    return f"http://127.0.0.1:{port}/glossary-html"


def _persist_glossary_html(config: EditorialConfig, local: LocalConfig, entries: list[GlossaryEntry]) -> Path | None:
    if not entries or config.glossary_path.startswith(("http://", "https://")):
        return None
    glossary_path = _path_from(config.glossary_path, local.default_repo_root)
    if not glossary_path.parent.exists():
        return None
    html_path = _default_glossary_html_path(glossary_path)
    save_glossary_html(entries, html_path)
    return html_path


def _format_output_target(form, source_path: str) -> Path | None:
    mode = form.get("save_mode", "copy")
    if mode == "overwrite":
        if not source_path.strip():
            return None
        return _path_from(source_path, ".")
    output_path = form.get("output_path", "").strip() or _default_formatted_path(source_path)
    return _path_from(output_path, ".")


def _format_entries_from_form(fallback: list[GlossaryEntry]) -> list[GlossaryEntry]:
    by_id = {entry.id: entry for entry in fallback}
    included_ids = set(request.form.getlist("include_entry_id"))
    result: list[GlossaryEntry] = []
    for entry_id in request.form.getlist("entry_id"):
        if entry_id not in included_ids:
            continue
        base = by_id.get(entry_id, GlossaryEntry(entry_id, request.form.get(f"term_{entry_id}", entry_id)))
        definition = request.form.get(f"definition_{entry_id}", base.definition)
        aliases = [item.strip() for item in request.form.get(f"aliases_{entry_id}", "").split(",") if item.strip()]
        result.append(GlossaryEntry(base.id, base.term, definition, aliases, base.mode))
    return result


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
    config.glossary_html_url = payload.get("glossary_html_url", config.glossary_html_url)
    config.glossary_link_target = "html"
    config.html_anchor_format = payload.get("html_anchor_format", config.html_anchor_format)
    config.glossary_detection = payload.get("glossary_detection", config.glossary_detection)
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


def _entries_from_form(fallback: list[GlossaryEntry], included_ids: set[str] | None = None) -> list[GlossaryEntry]:
    by_id = {entry.id: entry for entry in fallback}
    result: list[GlossaryEntry] = []
    for entry_id in request.form.getlist("entry_id"):
        if included_ids is not None and entry_id not in included_ids:
            continue
        base = by_id.get(entry_id, GlossaryEntry(entry_id, request.form.get(f"term_{entry_id}", entry_id)))
        aliases = [item.strip() for item in request.form.get(f"aliases_{entry_id}", "").split(",") if item.strip()]
        mode = "manual" if request.form.get(f"mode_{entry_id}") == "manual" else "automatic"
        result.append(GlossaryEntry(base.id, base.term, base.definition, aliases, mode))
    return result


def _start_processing(config: EditorialConfig, local: LocalConfig, entries: list[GlossaryEntry], operation: str):
    root = _path_from(request.form.get("repo_root", local.default_repo_root), ".")
    excluded: list[Path] = []
    config.glossary_link_target = "html"
    if not config.glossary_html_url.strip():
        config.glossary_html_url = _local_glossary_html_url(local)
    _persist_glossary_html(config, local, entries)
    warnings: list[str] = _glossary_link_warnings(config, entries, root)
    if operation == "update-glossary":
        paths, excluded = discover_tex_files(root, config)
        selected_ids = {value.strip() for value in request.form.get("new_entry_ids", "").split(",") if value.strip()}
        if selected_ids:
            entries = [entry for entry in entries if entry.id in selected_ids]
    else:
        raw_paths = request.form.get("tex_paths", "")
        paths, path_warnings = _resolve_selected_tex_paths(raw_paths, root)
        warnings.extend(path_warnings)

    if not paths:
        flash("Nessun file .tex valido selezionato. Controlla root progetto e percorsi relativi.", "error")
        for warning in warnings[:5]:
            flash(warning, "warning")
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


def _glossary_link_warnings(config: EditorialConfig, entries: list[GlossaryEntry], root: Path) -> list[str]:
    warnings: list[str] = []
    if not config.glossary_html_url.strip():
        warnings.append("URL Glossario.html vuoto: i link non possono aprire la pagina HTML generata dal tool.")
    return warnings


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
