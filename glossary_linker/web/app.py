from __future__ import annotations

import os
import secrets
import uuid
import json
import warnings
from dataclasses import asdict
from pathlib import Path
import subprocess
import sys
import re
from urllib.request import urlopen

from flask import Flask, Response, flash, has_request_context, jsonify, redirect, render_template, request, send_from_directory, session, url_for
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
from glossary_linker.core.glossary import parse_glossary_file, parse_glossary_text
from glossary_linker.core.glossary import (
    load_entries_store,
    merge_detected_with_store,
    save_entries_store,
)
from glossary_linker.core.json import GlossaryJSONError, save_glossary_json, serialize_glossary_json
from glossary_linker.core.linker import (
    collect_manual_occurrences,
    discover_tex_files,
    process_files,
    read_text_safe,
    save_report_json,
    save_report_markdown,
)
from glossary_linker.core.models import GlossaryEntry, Job, Occurrence


ROOT = Path.cwd()
EDITORIAL_PATH = ROOT / "glossary-linker.yml"
LOCAL_PATH = ROOT / "glossary-linker.local.yml"
STATE_DIR = ROOT / ".glossary-linker"
ENTRIES_PATH = STATE_DIR / "entries.yml"

# La guida è parte del repository e deve essere cercata rispetto alla posizione del codice
# e non rispetto alla cartella di lavoro corrente (CWD).
APP_DIR = Path(__file__).resolve().parent.parent.parent
GUIDE_PATH = APP_DIR / "docs" / "USER_GUIDE.md"

JOBS_DIR = STATE_DIR / "jobs"


class UserVisibleError(ValueError):
    """Errore mostrabile all'utente senza esporre dettagli interni."""


def _job_path(job_id: str | None) -> Path:
    if not job_id:
        raise UserVisibleError("ID job mancante.")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", str(job_id)):
        raise UserVisibleError(f"ID job non valido: {job_id}")
    return JOBS_DIR / f"{job_id}.json"


def _save_job(job_data: dict) -> None:
    def _json_serializable(obj):
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"Type {type(obj)} not serializable")

    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    path = _job_path(str(job_data.get("id", "")))
    try:
        payload = json.dumps(job_data, indent=2, ensure_ascii=False, default=_json_serializable)
        tmp_path = path.with_suffix(".json.tmp")
        tmp_path.write_text(payload, encoding="utf-8")
        tmp_path.replace(path)
    except (OSError, TypeError) as exc:
        raise UserVisibleError(f"Impossibile salvare lo stato del job {job_data.get('id')}: {exc}") from exc


def _load_job(job_id: str | None) -> dict | None:
    try:
        path = _job_path(job_id)
        if not path.exists():
            return None
        return _normalize_job(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, TypeError, UserVisibleError, ValueError):
        return None


def _get_or_create_wizard_job() -> dict:
    requested_job_id = request.values.get("job_id")
    job = _load_job(requested_job_id)
    if job:
        if not _job_has_started(job) and _refresh_job_from_store(job):
            _save_job(job)
        if _job_has_started(job):
            session.pop("wizard_job_id", None)
        else:
            session["wizard_job_id"] = job["id"]
        session["active_job_id"] = job["id"]
        return job

    job_id = session.get("wizard_job_id")
    job = _load_job(job_id)
    if job and _job_has_started(job):
        session.pop("wizard_job_id", None)
        job = None
    if not job:
        job_id = uuid.uuid4().hex
        session["wizard_job_id"] = job_id
        config = _load_editorial()
        local = _load_local()
        job = asdict(Job(
            id=job_id,
            config=asdict(config),
            entries=[asdict(e) for e in _load_entries_store_safe()],
            paths=[],
            root=str(_path_from(local.default_repo_root or ".", ".")),
            review_order=local.last_review_order or "by_term",
        ))
        _save_job(job)
    if _refresh_job_from_store(job):
        _save_job(job)
    return job


def _job_has_started(job: dict | None) -> bool:
    if not job:
        return False
    return bool(job.get("started") or job.get("occurrences") or job.get("results") or job.get("report"))


def _refresh_job_from_store(job: dict) -> bool:
    if _job_has_started(job):
        return False
    changed = False
    stored_entries = _load_entries_store_safe()
    stored_payload = [asdict(entry) for entry in stored_entries]
    if stored_entries and job.get("entries") != stored_payload:
        job["entries"] = stored_payload
        changed = True
    current_config = job.get("config") if isinstance(job.get("config"), dict) else {}
    disk_config = _load_editorial()
    if not str(current_config.get("glossary_path", "")).strip() and disk_config.glossary_path.strip():
        job["config"] = asdict(disk_config)
        changed = True
    return changed


def _normalize_job(job: dict) -> dict:
    if not isinstance(job, dict):
        raise UserVisibleError("Job salvato non valido: il file JSON non contiene un oggetto.")
    job_id = str(job.get("id", ""))
    _job_path(job_id)
    job["id"] = job_id
    if not isinstance(job.get("config"), dict):
        job["config"] = asdict(_load_editorial())
    if not isinstance(job.get("entries"), list):
        job["entries"] = []
    if not isinstance(job.get("paths"), list):
        job["paths"] = []
    job["root"] = str(job.get("root") or ROOT)
    job.setdefault("excluded", [])
    job.setdefault("warnings", [])
    job.setdefault("review_order", "by_term")
    job.setdefault("occurrences", [])
    job.setdefault("started", bool(job.get("occurrences") or job.get("results") or job.get("report")))
    if job["review_order"] not in {"by_term", "by_file"}:
        job["review_order"] = "by_term"
    if not isinstance(job.get("occurrences"), list):
        job["occurrences"] = []
    if not isinstance(job.get("decisions"), dict):
        job["decisions"] = {}
    job.setdefault("results", [])
    if not isinstance(job.get("results"), list):
        job["results"] = []
    job.setdefault("report", None)
    return job


def _can_open_wizard_step() -> bool:
    return bool(session.get("operation") or session.get("wizard_job_id") or request.values.get("job_id"))


def _entries_return_endpoint(target: str | None) -> str:
    normalized = (target or "").strip()
    return {
        "glossary": "glossary_step",
        "rules": "rules_step",
        "files": "files_step",
        "project": "project_step",
    }.get(normalized, "entries")


def _resolve_related_job(job_id: str | None = None) -> dict | None:
    for candidate in (job_id, request.values.get("job_id"), session.get("wizard_job_id"), session.get("active_job_id")):
        job = _load_job(candidate)
        if job:
            if _job_has_started(job):
                session.pop("wizard_job_id", None)
            else:
                session["wizard_job_id"] = job["id"]
            session["active_job_id"] = job["id"]
            return job
    return None


def _ensure_runtime_files() -> None:
    try:
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        if not EDITORIAL_PATH.exists():
            save_editorial_config(EditorialConfig(), EDITORIAL_PATH)
        editorial = load_editorial_config(EDITORIAL_PATH)
        local = load_local_config(LOCAL_PATH) if LOCAL_PATH.exists() else LocalConfig()
        local_text = LOCAL_PATH.read_text(encoding="utf-8") if LOCAL_PATH.exists() else ""
        local_changed = not LOCAL_PATH.exists() or bool(re.search(r"(?m)^glossary_html_path\s*:", local_text))
        if not local.glossary_path:
            local.glossary_path = editorial.glossary_path
            local_changed = True
        if not local.glossary_json_path:
            local.glossary_json_path = editorial.glossary_json_path
            local_changed = True
        if local_changed:
            save_local_config(local, LOCAL_PATH)
        editorial_text = EDITORIAL_PATH.read_text(encoding="utf-8")
        if re.search(r"(?m)^(?:glossary_path|glossary_html_path|glossary_json_path)\s*:", editorial_text):
            save_editorial_config(editorial, EDITORIAL_PATH)
        if not ENTRIES_PATH.exists():
            legacy_entries_path = ROOT / "glossary-linker.entries.yml"
            legacy_entries = load_entries_store(legacy_entries_path) if legacy_entries_path.exists() else []
            save_entries_store(legacy_entries, ENTRIES_PATH)
    except (OSError, TypeError, ValueError) as exc:
        warnings.warn(
            f"Impossibile inizializzare i file locali di Glossary Linker: {exc}. "
            "L'app proverà comunque a usare i default in memoria.",
            stacklevel=2,
        )


def create_app() -> Flask:
    _ensure_runtime_files()
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY") or _load_or_generate_secret_key()

    @app.errorhandler(UserVisibleError)
    def handle_user_visible_error(error: UserVisibleError):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": str(error)}), 400
        flash(str(error), "error")
        return redirect(url_for("project_step"))

    @app.route("/", methods=["GET", "POST"])
    def index():
        return project_step()

    @app.route("/project", methods=["GET", "POST"])
    def project_step():
        job = _get_or_create_wizard_job()
        local = _load_local()
        try:
            config = _config_from_job(job)
            entries = _entries_from_job(job)
        except UserVisibleError as exc:
            flash(str(exc), "error")
            session.pop("wizard_job_id", None)
            return redirect(url_for("project_step"))

        if request.method == "POST":
            operation = request.form.get("operation", "link-documents")
            session["operation"] = operation
            job["root"] = request.form.get("repo_root", job["root"])
            local.default_repo_root = job["root"]
            local.last_operation = operation
            save_local_config(local, LOCAL_PATH)
            _save_job(job)
            if operation == "format-glossary":
                return redirect(url_for("format_glossary"))
            return redirect(url_for("files_step"))

        return render_template(
            "operation.html",
            local=local,
            config=config,
            home_status=_home_status(local, config, entries),
            selected_operation=session.get("operation", local.last_operation),
            has_operation=bool(session.get("operation")),
            job_id=job["id"],
        )

    @app.route("/files", methods=["GET", "POST"])
    def files_step():
        if not _can_open_wizard_step():
            return redirect(url_for("index"))
        job = _get_or_create_wizard_job()
        if request.method == "POST":
            job["root"] = request.form.get("repo_root", job["root"])
            raw_paths = request.form.get("tex_paths", "")
            root = _path_from(job["root"], ".")
            paths, warnings = _resolve_selected_tex_paths(raw_paths, root)
            job["paths"] = [str(p) for p in paths]
            job["warnings"] = warnings
            job["review_order"] = request.form.get("review_order", job["review_order"])
            local = _load_local()
            local.default_repo_root = job["root"]
            local.last_source_dir = request.form.get("source_dir", local.last_source_dir)
            local.last_review_order = job["review_order"]
            save_local_config(local, LOCAL_PATH)
            _save_job(job)
            return redirect(url_for("rules_step"))

        local = _load_local()
        return render_template(
            "files.html",
            job=job,
            local=local,
            config=_config_from_job(job),
        )

    @app.route("/rules", methods=["GET", "POST"])
    def rules_step():
        if not _can_open_wizard_step():
            return redirect(url_for("index"))
        job = _get_or_create_wizard_job()
        config = _config_from_job(job)
        if request.method == "POST":
            _update_rules_from_form(config)
            job["config"] = asdict(config)
            _save_job(job)
            return redirect(url_for("glossary_step"))

        return render_template("rules.html", job=job, config=config)

    @app.route("/glossary", methods=["GET", "POST"])
    def glossary_step():
        if not _can_open_wizard_step():
            return redirect(url_for("index"))
        job = _get_or_create_wizard_job()
        job_locked = _job_has_started(job)
        config = _config_from_job(job)
        local = _load_local()
        entries = _entries_from_job(job)

        if request.method == "POST":
            if job_locked:
                flash("Il job è già stato avviato: la rilevazione automatico/manuale è fissata nello snapshot corrente. Per cambiarla, chiudi questo job e avvia un nuovo processo.", "warning")
                if job.get("occurrences"):
                    return redirect(url_for("review", job_id=job["id"], index=0))
                return redirect(url_for("output", job_id=job["id"]))

            config.glossary_html_url = request.form.get("glossary_html_url", config.glossary_html_url)
            config.html_anchor_format = request.form.get("html_anchor_format", config.html_anchor_format)
            job["config"] = asdict(config)

            if request.form.getlist("entry_id"):
                entries = _entries_from_form(entries)
                job["entries"] = [asdict(e) for e in entries]

            _save_job(job)

            action = request.form.get("action", "preview")
            if action == "continue":
                return _start_job_processing(job)

        return render_template(
            "glossary.html",
            job=job,
            config=config,
            local=local,
            entries=entries,
            entries_path=ENTRIES_PATH,
            job_locked=job_locked,
        )

    @app.post("/api/decision/<job_id>")
    def api_decision(job_id: str):
        job = _load_job(job_id)
        if not job:
            return jsonify({"ok": False, "error": "Job not found"}), 404

        payload = request.get_json(silent=True) or {}
        occurrence_id = payload.get("occurrence_id")
        value = payload.get("value")

        if not occurrence_id:
            return jsonify({"ok": False, "error": "Missing occurrence_id"}), 400
        if value not in _decision_actions():
            return jsonify({"ok": False, "error": "Invalid decision"}), 400

        try:
            occurrences = _occurrences_from_job(job)
        except UserVisibleError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 409
        current_index = _requested_occurrence_index(payload.get("occurrence_index"), len(occurrences))
        current = occurrences[current_index] if current_index is not None and occurrences[current_index].id == occurrence_id else None
        if current is None:
            current_index = next((idx for idx, item in enumerate(occurrences) if item.id == occurrence_id), None)
            current = occurrences[current_index] if current_index is not None else None
        if not current:
            return jsonify({"ok": False, "error": "Occurrence not found"}), 404

        affected = _apply_review_action(job, occurrences, current, value)
        _save_job(job)
        review_finished = current_index >= len(occurrences) - 1
        next_index = current_index if review_finished else current_index + 1
        message = "Scelta salvata."
        if review_finished:
            message = "Ultima occorrenza salvata: puoi andare al report finale."
            flash("Hai raggiunto l'ultima occorrenza. Puoi andare al report finale.", "info")
        redirect_url = url_for("review", job_id=job_id, index=next_index)
        review_state = _review_state(occurrences, job["decisions"])
        return jsonify({
            "ok": True,
            "affected": affected,
            "done": review_finished,
            "message": message,
            "decisions": job["decisions"],
            "next_index": next_index,
            "redirect_url": redirect_url,
            "output_url": url_for("output", job_id=job_id),
            "decided": review_state["decided"],
            "pending": review_state["pending"],
        })

    @app.post("/operation")
    def set_operation():
        session["operation"] = request.form.get("operation", "link-documents")
        local = _load_local()
        local.last_operation = session["operation"]
        save_local_config(local, LOCAL_PATH)
        if session["operation"] == "format-glossary":
            return redirect(url_for("format_glossary"))
        return redirect(url_for("files_step"))

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
            try:
                local = LocalConfig(
                    default_repo_root=request.form.get("default_repo_root", "."),
                    glossary_path=request.form.get("glossary_path", local.glossary_path).strip(),
                    glossary_json_path=request.form.get("glossary_json_path", local.glossary_json_path).strip(),
                    last_operation=local.last_operation,
                    last_source_dir=local.last_source_dir,
                    last_review_order=local.last_review_order,
                    last_new_entry_ids=local.last_new_entry_ids,
                    latexmk_path=request.form.get("latexmk_path", "latexmk"),
                    pdflatex_path=request.form.get("pdflatex_path", "pdflatex"),
                    xelatex_path=request.form.get("xelatex_path", "xelatex"),
                    lualatex_path=request.form.get("lualatex_path", "lualatex"),
                    preferred_compiler=request.form.get("preferred_compiler", "latexmk"),
                    compile_timeout_seconds=_int_from_form("compile_timeout_seconds", local.compile_timeout_seconds, minimum=1),
                    max_compile_passes=_int_from_form("max_compile_passes", local.max_compile_passes, minimum=1),
                    temporary_directory=request.form.get("temporary_directory", ""),
                    local_server_port=_int_from_form("local_server_port", local.local_server_port, minimum=1, maximum=65535),
                    auto_open_pdf=bool(request.form.get("auto_open_pdf")),
                    clean_aux_files=bool(request.form.get("clean_aux_files")),
                    clean_compile_artifacts=bool(request.form.get("clean_compile_artifacts")),
                    log_level=request.form.get("log_level", "INFO"),
                    preferred_browser=request.form.get("preferred_browser", ""),
                )
            except UserVisibleError as exc:
                flash(str(exc), "error")
                return redirect(url_for("settings", tab="environment"))
            if local.glossary_path:
                try:
                    _validate_glossary_source_value(local.glossary_path, local.default_repo_root)
                except UserVisibleError as exc:
                    flash(str(exc), "error")
                    return redirect(url_for("settings", tab="environment"))
                config.glossary_path = local.glossary_path
            if local.glossary_json_path:
                config.glossary_json_path = local.glossary_json_path
            config.glossary_html_url = request.form.get("glossary_html_url", config.glossary_html_url)
            save_local_config(local, LOCAL_PATH)
            save_editorial_config(config, EDITORIAL_PATH)
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

    @app.get("/help/static/<path:filename>")
    def help_static(filename: str):
        # Serve i file (immagini) dalla cartella docs per la guida
        return send_from_directory(GUIDE_PATH.parent, filename)

    @app.get("/glossary-json")
    def glossary_json_download():
        config = _load_editorial()
        local = _load_local()
        try:
            entries = _load_entries_from_config_path(config)
            data = serialize_glossary_json(entries)
        except (GlossaryJSONError, OSError, UserVisibleError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        target = _configured_glossary_json_path(config, local)
        filename = target.name if target else "glossary.json"
        if not filename.lower().endswith(".json"):
            filename += ".json"
        return Response(
            data,
            mimetype="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

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
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc), "paths": []}), 500
        return jsonify({"ok": True, "paths": paths})

    @app.post("/glossary-preview")
    def glossary_preview():
        payload = request.get_json(silent=True) or {}
        config = _load_editorial()
        local = _load_local()
        _update_config_from_payload(config, payload)
        _update_local_from_payload(local, payload)
        _apply_local_glossary_paths(config, local)
        root = payload.get("repo_root", local.default_repo_root)
        local.default_repo_root = root or local.default_repo_root
        try:
            detected = _load_detected_entries(config, root)
            save_editorial_config(config, EDITORIAL_PATH)
            if not detected:
                _persist_glossary_json(config, local, [])
                save_local_config(local, LOCAL_PATH)
                return jsonify({"ok": True, "stats": _entries_stats([], 0), "entries": []})
            stored = [entry for entry in _load_entries_store_safe() if entry.id not in set(config.excluded_entry_ids)]
            entries, new_count = merge_detected_with_store(detected, stored)
            serialize_glossary_json(entries)
            save_entries_store(entries, ENTRIES_PATH)
            _persist_glossary_json(config, local, entries)
            save_local_config(local, LOCAL_PATH)
            job = _load_job(payload.get("job_id") or session.get("wizard_job_id"))
            if job and not _job_has_started(job):
                job["entries"] = [asdict(entry) for entry in entries]
                job["config"] = asdict(config)
                _save_job(job)
        except (OSError, UserVisibleError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc), "stats": {}}), 400
        return jsonify({"ok": True, "stats": _entries_stats(entries, new_count), "entries": [_entry_payload(entry) for entry in entries]})

    @app.post("/wizard-state")
    def wizard_state():
        payload = request.get_json(silent=True) or {}
        config = _load_editorial()
        local = _load_local()
        _update_config_from_payload(config, payload)
        _update_local_from_payload(local, payload)
        _apply_local_glossary_paths(config, local)
        save_editorial_config(config, EDITORIAL_PATH)
        save_local_config(local, LOCAL_PATH)
        job = _load_job(payload.get("job_id") or session.get("wizard_job_id"))
        if job:
            job["config"] = asdict(config)
            job["root"] = local.default_repo_root
            job["review_order"] = local.last_review_order
            if "tex_paths" in payload:
                job["paths"] = [line.strip() for line in str(payload["tex_paths"]).splitlines() if line.strip()]
            _save_job(job)
        return jsonify({"ok": True})

    @app.post("/discover-tex")
    def discover_tex():
        payload = request.get_json(silent=True) or {}
        config = _load_editorial()
        local = _load_local()
        _update_config_from_payload(config, payload)
        _update_local_from_payload(local, payload)
        _apply_local_glossary_paths(config, local)
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
        stored = _load_entries_store_safe()
        return_to = request.values.get("return_to", "")
        job = _resolve_related_job()
        job_locked = _job_has_started(job)
        if request.method == "POST":
            updated = _entries_from_form(stored, lock_modes=job_locked)
            save_entries_store(updated, ENTRIES_PATH)
            if job and not job_locked:
                job["entries"] = [asdict(entry) for entry in updated]
                _save_job(job)
            if job_locked:
                flash("Glossario salvato per i prossimi processi. Il job corrente è già avviato: per modificare la rilevazione automatico/manuale devi chiuderlo e rifare il processo.", "warning")
            else:
                flash("Glossario rilevato salvato nello stato locale dell'app.", "success")
            return_endpoint = _entries_return_endpoint(return_to)
            if job and return_endpoint != "entries":
                return redirect(url_for(return_endpoint, job_id=job["id"]))
            params = {"return_to": return_to} if return_to else {}
            if job:
                params["job_id"] = job["id"]
            return redirect(url_for("entries", **params))
        wizard_return_url = None
        return_endpoint = _entries_return_endpoint(return_to)
        if job and return_endpoint != "entries":
            wizard_return_url = url_for(return_endpoint, job_id=job["id"])
        return render_template(
            "entries.html",
            entries=stored,
            entries_path=ENTRIES_PATH,
            job_id=job["id"] if job else "",
            return_to=return_to,
            wizard_return_url=wizard_return_url,
            job_locked=job_locked,
        )

    @app.route("/format-glossary", methods=["GET", "POST"])
    def format_glossary():
        config = _load_editorial()
        local = _load_local()
        raw_text = ""
        entries: list[GlossaryEntry] = []
        source_path = request.form.get("source_glossary_path", config.glossary_path) if request.method == "POST" else config.glossary_path
        json_output_path = request.form.get("json_output_path", config.glossary_json_path) if request.method == "POST" else (config.glossary_json_path or _default_json_output_path(source_path, local.default_repo_root))
        if request.method == "POST":
            config.glossary_path = source_path.strip() or config.glossary_path
            config.glossary_json_path = json_output_path.strip() or _default_json_output_path(source_path, local.default_repo_root)
            local.glossary_path = config.glossary_path
            local.glossary_json_path = config.glossary_json_path
            config.glossary_detection = _clean_detection_mode(request.form.get("glossary_detection", config.glossary_detection))
            config.glossary_custom_command = request.form.get("glossary_custom_command", config.glossary_custom_command)
            config.glossary_structure_description = request.form.get("glossary_structure_description", config.glossary_structure_description)
            save_editorial_config(config, EDITORIAL_PATH)
            save_local_config(local, LOCAL_PATH)
            action = request.form.get("action", "format")
            raw_text = request.form.get("glossary_text", "")
            try:
                glossary_text = _format_glossary_input(source_path, raw_text, local.default_repo_root)
            except Exception as exc:
                flash(str(exc), "error")
                glossary_text = ""
            if glossary_text:
                try:
                    entries = parse_glossary_text(glossary_text, config)
                except ValueError as exc:
                    flash(f"Glossario non valido: {exc}", "error")
                    entries = []
            if action == "export_json" and entries:
                entries = _format_entries_from_form(entries)
                try:
                    serialize_glossary_json(entries)
                    save_entries_store(entries, ENTRIES_PATH)
                    json_target = _format_json_output_target(request.form, source_path, local.default_repo_root)
                    save_glossary_json(entries, json_target)
                    config.glossary_json_path = str(json_target)
                    local.glossary_json_path = str(json_target)
                    save_editorial_config(config, EDITORIAL_PATH)
                    save_local_config(local, LOCAL_PATH)
                    flash(f"Glossario JSON salvato in {json_target}.", "success")
                except (GlossaryJSONError, OSError) as exc:
                    flash(f"Impossibile salvare il glossario JSON: {exc}", "error")
        return render_template(
            "format_glossary.html",
            config=config,
            local=local,
            raw_text=raw_text,
            source_path=source_path,
            json_output_path=json_output_path or _default_json_output_path(source_path, local.default_repo_root),
            entries=entries,
        )

    @app.route("/review/<job_id>/<int:index>", methods=["GET", "POST"])
    def review(job_id: str, index: int):
        job = _load_job(job_id)
        if job is None:
            flash("Sessione di revisione non trovata o scaduta.", "error")
            return redirect(url_for("project_step"))
        try:
            occurrences = _occurrences_from_job(job)
        except UserVisibleError as exc:
            flash(str(exc), "error")
            return redirect(url_for("glossary_step", job_id=job_id))
        if not occurrences:
            return redirect(url_for("output", job_id=job_id))
        index = min(max(index, 0), len(occurrences) - 1)
        if request.method == "POST":
            action = request.form.get("action", "next")
            if action == "prev":
                index = max(0, index - 1)
            elif action == "next":
                index = min(len(occurrences) - 1, index + 1)
            elif action == "next_pending":
                next_index = _next_pending_index(occurrences, job["decisions"], index)
                if next_index is None and occurrences[index].id not in job["decisions"]:
                    next_index = index
                if next_index is None:
                    flash("Tutte le occorrenze hanno già una scelta. Puoi rivederle o andare al report.", "info")
                else:
                    index = next_index
            elif action == "finish":
                return redirect(url_for("output", job_id=job_id))
            elif action in _decision_actions():
                current = occurrences[index]
                affected = _apply_review_action(job, occurrences, current, action)
                _save_job(job)
                if action in _bulk_decision_actions():
                    flash(f"Scelte aggiornate: {affected} occorrenze.", "success")
                else:
                    if index + 1 < len(occurrences):
                        index += 1
                    else:
                        flash("Hai raggiunto l'ultima occorrenza. Puoi andare al report finale.", "info")
            return redirect(url_for("review", job_id=job_id, index=index))

        occurrence = occurrences[index]
        decision = job["decisions"].get(occurrence.id)
        try:
            entries = _entries_from_job(job)
        except UserVisibleError as exc:
            flash(str(exc), "error")
            return redirect(url_for("glossary_step", job_id=job_id))
        entry = next((item for item in entries if item.id == occurrence.entry_id), GlossaryEntry(occurrence.entry_id, occurrence.term))
        same_term = [item for item in occurrences if item.entry_id == occurrence.entry_id]
        term_ids = list(dict.fromkeys(item.entry_id for item in occurrences))
        review_state = _review_state(occurrences, job["decisions"])
        detected_label = occurrence.visible_text.strip() or occurrence.term
        canonical_label = entry.term.strip() or occurrence.term
        is_alias_match = detected_label.casefold() != canonical_label.casefold()
        return render_template(
            "review.html",
            job_id=job_id,
            occurrence=occurrence,
            entry=entry,
            detected_label=detected_label,
            canonical_label=canonical_label,
            is_alias_match=is_alias_match,
            highlighted_context=_highlight_context(occurrence.context, occurrence.visible_text),
            index=index,
            total=len(occurrences),
            same_term_index=same_term.index(occurrence) + 1,
            same_term_total=len(same_term),
            term_index=term_ids.index(occurrence.entry_id) + 1,
            term_total=len(term_ids),
            decision=decision,
            decided_count=review_state["decided"],
            pending_count=review_state["pending"],
            summary_items=_review_summary_items(occurrences, job["decisions"], index),
            previous_step_url=url_for("glossary_step", job_id=job_id),
        )

    @app.get("/output/<job_id>")
    def output(job_id: str):
        job = _load_job(job_id)
        if job is None:
            flash("Sessione di elaborazione non trovata o scaduta.", "error")
            return redirect(url_for("project_step"))
        try:
            config = _config_from_job(job)
            entries = _entries_from_job(job)
            paths = _paths_from_job(job)
            root = _root_from_job(job)
        except UserVisibleError as exc:
            flash(str(exc), "error")
            return redirect(url_for("glossary_step", job_id=job_id))
        decisions = job.get("decisions", {})
        results, report = process_files(paths, entries, config, decisions, root=root)
        report.excluded_files = [Path(value) for value in job.get("excluded", [])]
        report.warnings.extend(job.get("warnings", []))
        job["results"] = [{"source": str(item.source_path), "output": str(item.output_path), "text": item.linked_text} for item in results]
        job["report"] = asdict(report)
        _save_job(job)
        output_items = [_output_item(result, root) for result in results]
        return render_template(
            "output.html",
            job_id=job_id,
            results=output_items,
            report=report,
            has_review=bool(job.get("occurrences")),
            previous_step_url=url_for("glossary_step", job_id=job_id),
        )

    @app.post("/save/<job_id>")
    def save_output(job_id: str):
        job = _load_job(job_id)
        if job is None:
            flash("Sessione di salvataggio non trovata o scaduta.", "error")
            return redirect(url_for("project_step"))
        mode = request.form.get("mode", "linked")
        if mode not in {"linked", "overwrite"}:
            flash(f"Modalità di salvataggio non valida: {mode}.", "error")
            return redirect(url_for("output", job_id=job_id))
        source = request.form.get("source", "")
        saved: list[str] = []
        errors: list[str] = []
        for item in job.get("results", []):
            if not isinstance(item, dict):
                errors.append("Risultato ignorato perché il job contiene dati corrotti.")
                continue
            try:
                source_path, output_path = _validated_result_paths(item)
                if source and str(source_path) != source:
                    continue
                target = source_path if mode == "overwrite" else output_path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(str(item.get("text", "")), encoding="utf-8")
                saved.append(str(target))
            except (KeyError, OSError, UserVisibleError) as exc:
                errors.append(f"Impossibile salvare {item.get('output') or item.get('source') or 'risultato'}: {exc}")
        if request.form.get("include_report"):
            if not job.get("report"):
                errors.append("Report non disponibile: apri prima la schermata Output per rigenerarlo.")
            else:
                try:
                    if request.form.get("report_format") == "json":
                        save_report_json(_report_from_dict(job["report"]), ROOT / "glossary-linker-report.json")
                        saved.append(str(ROOT / "glossary-linker-report.json"))
                    else:
                        save_report_markdown(_report_from_dict(job["report"]), ROOT / "glossary-linker-report.md")
                        saved.append(str(ROOT / "glossary-linker-report.md"))
                except (OSError, TypeError, ValueError) as exc:
                    errors.append(f"Impossibile salvare il report: {exc}")
        if saved:
            flash("Salvataggio completato: " + ", ".join(saved), "success")
        if errors:
            flash(" ".join(errors), "error")
        if not saved:
            flash("Nessun file salvato: controlla i risultati disponibili.", "warning")
        return redirect(url_for("output", job_id=job_id))

    @app.post("/compile/<job_id>")
    def compile_output(job_id: str):
        local = _load_local()
        source = request.form.get("source", "")
        pdf_name = request.form.get("pdf_name") or None
        job = _load_job(job_id)
        if job is None:
            flash("Sessione di compilazione non trovata o scaduta.", "error")
            return redirect(url_for("project_step"))
        matched = False
        for item in job.get("results", []):
            if not isinstance(item, dict):
                continue
            try:
                source_path, output_path = _validated_result_paths(item)
            except UserVisibleError as exc:
                flash(str(exc), "error")
                continue
            if str(source_path) == source:
                matched = True
                target = output_path
                try:
                    target.write_text(str(item.get("text", "")), encoding="utf-8")
                except OSError as exc:
                    flash(f"Impossibile preparare il file per la compilazione: {exc}", "error")
                    return redirect(url_for("output", job_id=job_id))
                result = compile_tex(target, local, pdf_name)
                category = "success" if result.ok else "error"
                flash(("Compilazione riuscita: " if result.ok else "Compilazione fallita: ") + " ".join(result.command), category)
                if not result.ok:
                    flash(result.output[-2000:], "error")
                break
        if not matched:
            flash("File da compilare non trovato nei risultati del job.", "warning")
        return redirect(url_for("output", job_id=job_id))

    return app


def main() -> None:
    local = _load_local()
    app = create_app()
    app.run(host="127.0.0.1", port=local.local_server_port, debug=False)


def _load_or_generate_secret_key() -> str:
    key_path = LOCAL_PATH.parent / ".glossary-linker-secret"
    if key_path.exists():
        return key_path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(32)
    try:
        key_path.write_text(key, encoding="utf-8")
        key_path.chmod(0o600)
    except OSError as exc:
        warnings.warn(
            f"Impossibile salvare la chiave segreta in {key_path}: {exc}. "
            "Le sessioni non sopravviveranno al riavvio del server.",
            stacklevel=2,
        )
    return key


def _load_editorial() -> EditorialConfig:
    try:
        config = load_editorial_config(EDITORIAL_PATH)
        local = _load_local()
        if local.glossary_path:
            config.glossary_path = local.glossary_path
        if local.glossary_json_path:
            config.glossary_json_path = local.glossary_json_path
        return config
    except (OSError, ValueError, TypeError) as exc:
        _surface_local_state_warning(f"Configurazione editoriale non leggibile: {exc}. Uso i default in memoria.")
        return EditorialConfig()


def _load_local() -> LocalConfig:
    try:
        if LOCAL_PATH.exists():
            return load_local_config(LOCAL_PATH)
    except (OSError, ValueError, TypeError) as exc:
        _surface_local_state_warning(f"Configurazione locale non leggibile: {exc}. Uso i default in memoria.")
    return LocalConfig()


def _load_entries_store_safe() -> list[GlossaryEntry]:
    try:
        return load_entries_store(ENTRIES_PATH)
    except (OSError, ValueError, TypeError) as exc:
        _surface_local_state_warning(f"Glossario rilevato non leggibile: {exc}. La lista viene trattata come vuota.")
        return []


def _surface_local_state_warning(message: str) -> None:
    warnings.warn(message, stacklevel=2)
    if has_request_context():
        flash(message, "warning")


def _int_from_form(name: str, fallback: int, minimum: int | None = None, maximum: int | None = None) -> int:
    raw = (request.form.get(name, "") or "").strip()
    if not raw:
        return fallback
    try:
        value = int(raw)
    except ValueError as exc:
        raise UserVisibleError(f"Il campo {name} deve essere un numero intero.") from exc
    if minimum is not None and value < minimum:
        raise UserVisibleError(f"Il campo {name} deve essere almeno {minimum}.")
    if maximum is not None and value > maximum:
        raise UserVisibleError(f"Il campo {name} deve essere al massimo {maximum}.")
    return value


def _home_status(local: LocalConfig, config: EditorialConfig, entries: list[GlossaryEntry]) -> dict[str, object]:
    root = _path_from(local.default_repo_root or ".", ".")
    glossary_is_url = config.glossary_path.startswith(("http://", "https://"))
    glossary_path = None if glossary_is_url else _path_from(config.glossary_path, root)
    glossary_json_path = _configured_glossary_json_path(config, local)
    manual = sum(1 for entry in entries if entry.mode == "manual")
    return {
        "root_label": str(root),
        "root_ok": root.exists() and root.is_dir(),
        "glossary_label": config.glossary_path or "Non impostato",
        "glossary_ok": glossary_is_url or bool(glossary_path and glossary_path.exists()),
        "glossary_json_label": str(glossary_json_path) if glossary_json_path else "Non impostato",
        "glossary_json_ok": bool(glossary_json_path and glossary_json_path.exists()),
        "entries_total": len(entries),
        "entries_manual": manual,
        "entries_automatic": len(entries) - manual,
        "entries_new": 0,
        "detection_label": _detection_label(config),
        "rules_total": len(config.exclude_file_patterns) + len(config.ignored_environments) + len(config.ignored_commands),
    }


def _detection_label(config: EditorialConfig) -> str:
    if config.glossary_detection == "custom" and config.glossary_custom_command:
        return f"\\{config.glossary_custom_command}{{Termine}}"
    if config.glossary_detection == "subsection":
        return r"\subsection{Termine}"
    return "Auto"


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
        
        # Gestione speciale per righe che contengono SOLO un'immagine (comune per gli screenshot)
        image_match = re.match(r"^!\[([^\]]*)\]\(([^\)]+)\)$", stripped)
        if image_match:
            content = _inline_markdown(stripped)
            html.append(Markup('<p class="doc-img-wrapper">') + content + Markup("</p>"))
            continue

        content = _inline_markdown(stripped)
        
        # Se il paragrafo precedente era un'immagine e questo è interamente corsivo, è una didascalia
        is_caption = False
        if html and 'class="doc-img-wrapper"' in str(html[-1]):
            # Se stripped inizia con * o _ e finisce con lo stesso, ed è l'unica enfasi
            if (stripped.startswith("*") and stripped.endswith("*")) or \
               (stripped.startswith("_") and stripped.endswith("_")):
                is_caption = True
        
        class_attr = ' class="doc-caption"' if is_caption else ""
        html.append(Markup(f"<p{class_attr}>") + content + Markup("</p>"))

    if in_code:
        html.append(Markup('<pre tabindex="0"><code>') + escape("\n".join(code_lines)) + Markup("</code></pre>"))
    close_list()
    return Markup("\n".join(str(item) for item in html))


def _inline_markdown(text: str) -> Markup:
    # Usiamo Markup.escape per il testo base e poi sostituiamo i tag necessari
    m = Markup.escape(text)
    
    # Immagini: ![alt](path) -> <img src="/docs/path" alt="alt">
    m = re.sub(
        r"!\[([^\]]*)\]\(([^\)]+)\)",
        r'<img src="/help/static/\2" alt="\1" class="doc-img">',
        m
    )
    m = re.sub(r"`([^`]+)`", r"<code>\1</code>", m)
    m = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", m)
    m = re.sub(r"\*([^*]+)\*", r"<em>\1</em>", m)
    m = re.sub(r"_([^_]+)_", r"<em>\1</em>", m)
    
    return Markup(m)


def _format_glossary_input(source_path: str, pasted_text: str, base: str | Path = ".") -> str:
    if pasted_text.strip():
        return pasted_text
    if not source_path.strip():
        return ""
    path = _path_from(source_path, base)
    if not path.exists():
        raise FileNotFoundError(f"Glossario sorgente non trovato: {path}")
    if not path.is_file():
        raise FileNotFoundError(f"Il glossario sorgente non è un file: {path}")
    return read_text_safe(path)


def _default_glossary_json_path(tex_path: Path) -> Path:
    return tex_path.with_suffix(".json")


def _default_json_output_path(source_path: str, base: str | Path = ".") -> str:
    if source_path.strip():
        path = _path_from(source_path, base)
        return str(path.with_suffix(".json"))
    return str((ROOT / "glossary.json").resolve())


def _configured_glossary_json_path(config: EditorialConfig, local: LocalConfig) -> Path | None:
    if not config.glossary_json_path.strip():
        return None
    return _path_from(config.glossary_json_path, local.default_repo_root)


def _persist_glossary_json(config: EditorialConfig, local: LocalConfig, entries: list[GlossaryEntry]) -> Path | None:
    json_path = _configured_glossary_json_path(config, local)
    if json_path is None:
        glossary_source = config.glossary_path.strip()
        if glossary_source.startswith(("http://", "https://")):
            return None
        glossary_path = _path_from(glossary_source, local.default_repo_root) if glossary_source else Path(local.default_repo_root) / "Glossario.tex"
        json_path = _default_glossary_json_path(glossary_path)
        config.glossary_json_path = str(json_path)
        local.glossary_json_path = str(json_path)
    save_glossary_json(entries, json_path)
    return json_path


def _format_json_output_target(form, source_path: str, base: str | Path = ".") -> Path:
    output_path = form.get("json_output_path", "").strip() or _default_json_output_path(source_path, base)
    return _path_from(output_path, base)


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
    glossary_path = _effective_glossary_source_path(config, root)
    if glossary_path.startswith(("http://", "https://")):
        with urlopen(glossary_path, timeout=10) as response:
            text = response.read().decode("utf-8")
        return parse_glossary_text(text, config)
    path = _path_from(glossary_path, root)
    if not path.exists():
        raise UserVisibleError(f"Glossario sorgente .tex non trovato: {path}")
    if path.is_dir():
        raise UserVisibleError(f"Il glossario sorgente punta a una directory, non a un file .tex: {path}")
    if path.suffix.lower() != ".tex":
        raise UserVisibleError(f"Il glossario sorgente deve essere un file .tex: {path}")
    return parse_glossary_file(path, config)


def _effective_glossary_source_path(config: EditorialConfig, root: str | Path) -> str:
    configured = config.glossary_path.strip()
    if configured:
        return configured
    inferred = _infer_glossary_source_from_json(config, root)
    if inferred:
        config.glossary_path = str(inferred)
        return str(inferred)
    raise UserVisibleError(
        "Glossario sorgente .tex non impostato. Se hai già formattato il glossario, "
        "apri Impostazioni e seleziona il file .tex sorgente, non la cartella del progetto."
    )


def _infer_glossary_source_from_json(config: EditorialConfig, root: str | Path) -> Path | None:
    if not config.glossary_json_path.strip():
        return None
    json_path = _path_from(config.glossary_json_path, root)
    candidate = json_path.with_suffix(".tex")
    return candidate if candidate.exists() and candidate.is_file() else None


def _validate_glossary_source_value(value: str, root: str | Path) -> None:
    if value.startswith(("http://", "https://")):
        return
    path = _path_from(value, root)
    if path.exists() and path.is_dir():
        raise UserVisibleError(f"Il glossario sorgente deve essere un file .tex, non una directory: {path}")
    if path.exists() and path.suffix.lower() != ".tex":
        raise UserVisibleError(f"Il glossario sorgente deve essere un file .tex: {path}")


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


def _update_config_from_payload(config: EditorialConfig, payload: dict) -> None:
    if "glossary_html_url" in payload:
        config.glossary_html_url = str(payload.get("glossary_html_url") or "")
    if "html_anchor_format" in payload and str(payload.get("html_anchor_format", "")).strip():
        config.html_anchor_format = str(payload["html_anchor_format"]).strip()
    if "glossary_detection" in payload:
        config.glossary_detection = _clean_detection_mode(str(payload.get("glossary_detection") or config.glossary_detection))
    if "glossary_custom_command" in payload:
        config.glossary_custom_command = str(payload.get("glossary_custom_command") or "")
    if "glossary_structure_description" in payload:
        config.glossary_structure_description = str(payload.get("glossary_structure_description") or "")
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
    if "glossary_path" in payload and str(payload.get("glossary_path", "")).strip():
        local.glossary_path = str(payload["glossary_path"]).strip()
    if "glossary_json_path" in payload and str(payload.get("glossary_json_path", "")).strip():
        local.glossary_json_path = str(payload["glossary_json_path"]).strip()
    local.last_operation = payload.get("operation", local.last_operation) or local.last_operation
    local.last_source_dir = payload.get("source_dir", local.last_source_dir) or local.last_source_dir
    local.last_review_order = payload.get("review_order", local.last_review_order) or local.last_review_order
    local.last_new_entry_ids = payload.get("new_entry_ids", local.last_new_entry_ids)


def _apply_local_glossary_paths(config: EditorialConfig, local: LocalConfig) -> None:
    if local.glossary_path:
        config.glossary_path = local.glossary_path
    if local.glossary_json_path:
        config.glossary_json_path = local.glossary_json_path


def _clean_detection_mode(value: str) -> str:
    return value if value in {"auto", "subsection", "custom"} else "auto"


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


def _entries_from_form(
    fallback: list[GlossaryEntry],
    included_ids: set[str] | None = None,
    lock_modes: bool = False,
) -> list[GlossaryEntry]:
    by_id = {entry.id: entry for entry in fallback}
    result: list[GlossaryEntry] = []
    for entry_id in request.form.getlist("entry_id"):
        if included_ids is not None and entry_id not in included_ids:
            continue
        base = by_id.get(entry_id, GlossaryEntry(entry_id, request.form.get(f"term_{entry_id}", entry_id)))
        term = request.form.get(f"term_{entry_id}", base.term)
        definition = request.form.get(f"definition_{entry_id}", base.definition)
        aliases_raw = request.form.get(f"aliases_{entry_id}")
        aliases = base.aliases if aliases_raw is None else [item.strip() for item in aliases_raw.split(",") if item.strip()]
        mode_raw = request.form.get(f"mode_{entry_id}")
        mode = base.mode if lock_modes or mode_raw is None else ("manual" if mode_raw == "manual" else "automatic")
        result.append(GlossaryEntry(base.id, term, definition, aliases, mode))
    return result


def _entries_from_job(job: dict) -> list[GlossaryEntry]:
    entries: list[GlossaryEntry] = []
    for index, item in enumerate(job.get("entries", []), start=1):
        if not isinstance(item, dict):
            raise UserVisibleError(f"Job non valido: la voce glossario #{index} non è un oggetto.")
        try:
            entries.append(_entry_from_dict(item))
        except TypeError as exc:
            raise UserVisibleError(f"Job non valido: voce glossario #{index} incompleta o corrotta.") from exc
    return entries


def _config_from_job(job: dict) -> EditorialConfig:
    data = job.get("config")
    if not isinstance(data, dict):
        raise UserVisibleError("Job non valido: configurazione editoriale mancante o corrotta.")
    try:
        return _editorial_from_dict(data)
    except TypeError as exc:
        raise UserVisibleError("Job non valido: configurazione editoriale incompatibile.") from exc


def _occurrences_from_job(job: dict) -> list[Occurrence]:
    occurrences: list[Occurrence] = []
    for index, item in enumerate(job.get("occurrences", []), start=1):
        if not isinstance(item, dict):
            raise UserVisibleError(f"Job di revisione non valido: occorrenza #{index} non è un oggetto.")
        try:
            occurrences.append(_occurrence_from_dict(item))
        except (KeyError, TypeError) as exc:
            raise UserVisibleError(f"Job di revisione non valido: occorrenza #{index} incompleta o corrotta.") from exc
    return occurrences


def _paths_from_job(job: dict) -> list[Path]:
    paths: list[Path] = []
    for index, value in enumerate(job.get("paths", []), start=1):
        raw = str(value).strip()
        if not raw:
            continue
        try:
            paths.append(Path(raw))
        except TypeError as exc:
            raise UserVisibleError(f"Job non valido: percorso sorgente #{index} non leggibile.") from exc
    return paths


def _root_from_job(job: dict) -> Path:
    root = _path_from(str(job.get("root") or ROOT), ".")
    if not root.exists():
        raise UserVisibleError(f"Root progetto non trovata: {root}")
    if not root.is_dir():
        raise UserVisibleError(f"Root progetto non valida, non è una directory: {root}")
    return root


def _start_job_processing(job: dict):
    try:
        config = _config_from_job(job)
        entries = _entries_from_job(job)
        paths = _paths_from_job(job)
        root = _root_from_job(job)
    except UserVisibleError as exc:
        flash(str(exc), "error")
        return redirect(url_for("glossary_step", job_id=job.get("id")))
    stored_entries = _load_entries_store_safe()
    if stored_entries:
        entries = stored_entries
    local = _load_local()
    operation = session.get("operation", "link-documents")
    
    try:
        _persist_glossary_json(config, local, entries)
    except (GlossaryJSONError, OSError) as exc:
        flash(f"Impossibile preparare il glossario JSON: {exc}", "error")
        return redirect(url_for("glossary_step", job_id=job.get("id")))
    
    if operation == "update-glossary":
        try:
            all_paths, excluded = discover_tex_files(root, config)
        except OSError as exc:
            flash(f"Impossibile scansionare i file .tex: {exc}", "error")
            return redirect(url_for("files_step", job_id=job.get("id")))
        job["excluded"] = [str(p) for p in excluded]
        paths = all_paths
        selected_ids = {v.strip() for v in job.get("new_entry_ids", "").split(",") if v.strip()}
        if selected_ids:
            entries = [e for e in entries if e.id in selected_ids]

    if not paths:
        flash("Nessun file .tex valido selezionato.", "error")
        return redirect(url_for("files_step"))

    occurrences = collect_manual_occurrences(paths, entries, config, root=root)
    occurrences = _sort_occurrences(occurrences, entries, job["review_order"])
    
    job["occurrences"] = [asdict(o) for o in occurrences]
    job["entries"] = [asdict(e) for e in entries]
    job["config"] = asdict(config)
    job["decisions"] = {}
    job["results"] = []
    job["report"] = None
    job["started"] = True
    
    _save_job(job)
    
    session.pop("wizard_job_id", None)
    session["active_job_id"] = job["id"]
    
    if occurrences:
        return redirect(url_for("review", job_id=job["id"], index=0))
    return redirect(url_for("output", job_id=job["id"]))


def _glossary_link_warnings(config: EditorialConfig, entries: list[GlossaryEntry], root: Path) -> list[str]:
    if not entries or config.glossary_html_url.strip():
        return []
    return ["URL pubblico del glossario non configurato: i link nei documenti non avranno una destinazione valida."]


def _resolve_selected_tex_paths(raw_paths: str, root: Path) -> tuple[list[Path], list[str]]:
    paths: list[Path] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    for raw in [line.strip().strip('"').strip("'") for line in raw_paths.splitlines() if line.strip()]:
        path = _path_from(raw, root)
        try:
            if path.exists() and path.is_file():
                resolved = path.resolve()
                if resolved not in seen:
                    paths.append(resolved)
                    seen.add(resolved)
                continue
        except Exception:
            pass

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


def _validated_result_paths(item: dict) -> tuple[Path, Path]:
    source_raw = str(item.get("source") or "").strip()
    output_raw = str(item.get("output") or "").strip()
    if not source_raw or not output_raw:
        raise UserVisibleError("Risultato incompleto: sorgente o output mancante.")
    source_path = Path(source_raw).expanduser().resolve()
    output_path = Path(output_raw).expanduser().resolve()
    expected_output = source_path.with_name(source_path.stem + ".linked.tex")
    if output_path != expected_output:
        raise UserVisibleError(
            f"Target output inatteso per {source_path.name}: atteso {expected_output.name}, trovato {output_path.name}."
        )
    return source_path, output_path


def _apply_review_action(job: dict, occurrences: list[Occurrence], current: Occurrence, action: str) -> int:
    decisions = job["decisions"]
    affected = 0

    def set_decision(occurrence: Occurrence, value: bool) -> None:
        nonlocal affected
        if decisions.get(occurrence.id) != value:
            affected += 1
        decisions[occurrence.id] = value

    if action == "link":
        set_decision(current, True)
    elif action == "skip":
        set_decision(current, False)
    elif action in {"link_file_term", "skip_file_term", "link_term_all", "skip_term_all", "skip_file"}:
        value = action.startswith("link")
        for occurrence in occurrences:
            same_term = occurrence.entry_id == current.entry_id
            same_file = occurrence.file_path == current.file_path
            if action in {"link_file_term", "skip_file_term"} and same_term and same_file:
                set_decision(occurrence, value)
            elif action in {"link_term_all", "skip_term_all"} and same_term:
                set_decision(occurrence, value)
            elif action == "skip_file" and same_file:
                set_decision(occurrence, False)
    return affected


def _decision_actions() -> set[str]:
    return {"link", "skip"} | _bulk_decision_actions()


def _bulk_decision_actions() -> set[str]:
    return {"link_file_term", "skip_file_term", "link_term_all", "skip_term_all", "skip_file"}


def _requested_occurrence_index(value: object, total: int) -> int | None:
    try:
        index = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= index < total:
        return index
    return None


def _review_state(occurrences: list[Occurrence], decisions: dict[str, bool]) -> dict[str, int]:
    decided = sum(1 for occurrence in occurrences if occurrence.id in decisions)
    return {"decided": decided, "pending": max(0, len(occurrences) - decided)}


def _review_summary_items(occurrences: list[Occurrence], decisions: dict[str, bool], current_index: int) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for index, occurrence in enumerate(occurrences):
        decision = decisions.get(occurrence.id)
        items.append({
            "index": index,
            "term": occurrence.term,
            "file": occurrence.file_path.name,
            "line": occurrence.line_number,
            "decision": "Collega" if decision is True else "Salta" if decision is False else "Da decidere",
            "decision_class": "linked" if decision is True else "skipped" if decision is False else "pending",
            "current": index == current_index,
        })
    return items


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
