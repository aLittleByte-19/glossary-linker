from dataclasses import asdict

import pytest

from glossary_linker.core.config import EditorialConfig, LocalConfig, save_editorial_config, save_local_config
from glossary_linker.core.glossary import load_entries_store, save_entries_store
from glossary_linker.core.linker import collect_manual_occurrences, link_file
from glossary_linker.core.models import GlossaryEntry, ProcessingReport, Job
from glossary_linker.web.app import create_app, _glossary_link_warnings, _save_job, _load_job


def test_glossary_rules_requires_current_operation_session():
    app = create_app()
    client = app.test_client()

    response = client.get("/glossary")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_operation_progress_keeps_glossary_disabled_before_choice():
    app = create_app()
    client = app.test_client()

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<span class="disabled">Glossario</span>' in html


def test_home_form_posts_to_project_step():
    app = create_app()
    client = app.test_client()

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'form method="post" action="/project"' in html


def test_root_post_supports_format_glossary_operation():
    app = create_app()
    client = app.test_client()

    response = client.post("/", data={"operation": "format-glossary"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/format-glossary")


def test_save_output_generates_report_only_when_requested(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    output = tmp_path / "doc.linked.tex"
    source.write_text("original", encoding="utf-8")
    calls = []
    job_id = "save-output"
    _save_job({
        "id": job_id,
        "results": [{"source": str(source), "output": str(output), "text": "linked"}],
        "report": asdict(ProcessingReport()),
    })
    monkeypatch.setattr("glossary_linker.web.app.save_report_markdown", lambda report, path: calls.append(("md", path)))
    monkeypatch.setattr("glossary_linker.web.app.save_report_json", lambda report, path: calls.append(("json", path)))

    response = client.post(f"/save/{job_id}", data={"mode": "linked"})

    assert response.status_code == 302
    assert output.read_text(encoding="utf-8") == "linked"
    assert calls == []

    response = client.post(f"/save/{job_id}", data={
        "mode": "overwrite",
        "include_report": "1",
        "report_format": "json",
    })

    assert response.status_code == 302
    assert source.read_text(encoding="utf-8") == "linked"
    assert calls and calls[-1][0] == "json"


def test_output_does_not_print_missing_term_names(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("\\begin{document}Nessun match.\\end{document}", encoding="utf-8")
    job_id = "missing-terms"
    _save_job({
        "id": job_id,
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-assente", "Termine Assente"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "excluded": [],
        "warnings": [],
        "occurrences": [],
        "decisions": {},
    })

    response = client.get(f"/output/{job_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Termini non trovati" in html
    assert "Termine Assente" not in html


def test_glossary_link_warning_requires_generated_html_url(tmp_path):
    config = EditorialConfig(glossary_path="Glossario.tex", glossary_html_url="")
    entries = [GlossaryEntry("accuratezza", "Accuratezza")]

    warnings = _glossary_link_warnings(config, entries, tmp_path)

    assert warnings
    assert "Glossario.html" in warnings[0]


def test_glossary_html_route_renders_entries_from_configured_tex(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    glossary = tmp_path / "Glossario.tex"
    glossary.write_text(
        r"""\begin{document}
\subsection{Accuratezza}
Definizione.
\end{document}""",
        encoding="utf-8",
    )
    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    save_editorial_config(EditorialConfig(glossary_path="Glossario.tex", glossary_detection="subsection"), editorial_path)
    save_local_config(LocalConfig(default_repo_root=str(tmp_path)), local_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    app = create_app()
    client = app.test_client()

    response = client.get("/glossary-html")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'id="gls-accuratezza"' in html
    assert 'id="glossary-search"' in html
    assert "Accuratezza" in html


def test_glossary_html_route_serves_configured_generated_file(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    html_path = tmp_path / "public" / "Glossario.html"
    html_path.parent.mkdir()
    html_path.write_text("<!doctype html><title>Generato</title><p>file corretto</p>", encoding="utf-8")
    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    save_editorial_config(EditorialConfig(glossary_html_path=str(html_path)), editorial_path)
    save_local_config(LocalConfig(default_repo_root=str(tmp_path)), local_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    app = create_app()
    client = app.test_client()

    response = client.get("/glossary-html")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "file corretto" in html
    assert "Glossario</title>" not in html


def test_entries_page_is_only_for_modes_and_aliases(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    entries_path = tmp_path / "entries.yml"
    save_entries_store([
        GlossaryEntry("voce-buona", "Voce Buona"),
    ], entries_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    app = create_app()
    client = app.test_client()

    page = client.get("/entries").get_data(as_text=True)
    assert "include_entry_id" not in page

    response = client.post("/entries", data={
        "entry_id": ["voce-buona"],
        "aliases_voce-buona": "alias",
        "mode_voce-buona": "manual",
    })

    assert response.status_code == 302
    entries = load_entries_store(entries_path)
    assert [entry.id for entry in entries] == ["voce-buona"]
    assert entries[0].aliases == ["alias"]
    assert entries[0].mode == "manual"


def test_entries_save_returns_to_glossary_and_updates_job(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    entries_path = tmp_path / "entries.yml"
    jobs_dir = tmp_path / "jobs"
    save_entries_store([GlossaryEntry("voce-buona", "Voce Buona")], entries_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    monkeypatch.setattr(webapp, "JOBS_DIR", jobs_dir)
    app = create_app()
    client = app.test_client()
    _save_job({
        "id": "wizard-entries",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("voce-buona", "Voce Buona", mode="automatic"))],
        "paths": [],
        "root": str(tmp_path),
        "review_order": "by_term",
    })

    response = client.post("/entries?job_id=wizard-entries&return_to=glossary", data={
        "job_id": "wizard-entries",
        "return_to": "glossary",
        "entry_id": ["voce-buona"],
        "aliases_voce-buona": "alias",
        "mode_voce-buona": "manual",
    }, follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Avvia elaborazione" in html
    assert 'target="_blank"' not in html
    assert 'badge manual' in html
    saved_job = _load_job("wizard-entries")
    assert saved_job is not None
    assert saved_job["entries"][0]["mode"] == "manual"
    assert saved_job["entries"][0]["aliases"] == ["alias"]


def test_entries_warns_and_locks_modes_for_started_job(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    entries_path = tmp_path / "entries.yml"
    jobs_dir = tmp_path / "jobs"
    save_entries_store([GlossaryEntry("voce-buona", "Voce Buona", mode="automatic")], entries_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    monkeypatch.setattr(webapp, "JOBS_DIR", jobs_dir)
    app = create_app()
    client = app.test_client()
    _save_job({
        "id": "started-entries",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("voce-buona", "Voce Buona", mode="automatic"))],
        "paths": [],
        "root": str(tmp_path),
        "review_order": "by_term",
        "started": True,
    })

    page = client.get("/entries?job_id=started-entries&return_to=glossary").get_data(as_text=True)

    assert "Il job corrente è già stato avviato" in page
    assert "Modalità bloccata per il job corrente" in page
    assert "disabled" in page

    response = client.post("/entries?job_id=started-entries&return_to=glossary", data={
        "job_id": "started-entries",
        "return_to": "glossary",
        "entry_id": ["voce-buona"],
        "aliases_voce-buona": "alias futuro",
        "mode_voce-buona": "manual",
    }, follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "per i prossimi processi" in html
    assert load_entries_store(entries_path)[0].mode == "automatic"
    assert load_entries_store(entries_path)[0].aliases == ["alias futuro"]
    saved_job = _load_job("started-entries")
    assert saved_job is not None
    assert saved_job["entries"][0]["mode"] == "automatic"
    assert saved_job["entries"][0]["aliases"] == []


def test_format_glossary_flow_uses_glossary_input_without_project_root():
    app = create_app()
    client = app.test_client()

    response = client.get("/format-glossary")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Root progetto" not in html
    assert "File glossario .tex" in html


def test_settings_persist_glossary_paths(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    save_editorial_config(EditorialConfig(), editorial_path)
    save_local_config(LocalConfig(), local_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/settings", data={
        "settings_scope": "environment",
        "default_repo_root": str(tmp_path),
        "temporary_directory": "",
        "latexmk_path": "latexmk",
        "pdflatex_path": "pdflatex",
        "xelatex_path": "xelatex",
        "lualatex_path": "lualatex",
        "preferred_compiler": "latexmk",
        "compile_timeout_seconds": "120",
        "max_compile_passes": "2",
        "local_server_port": "8765",
        "log_level": "INFO",
        "preferred_browser": "",
        "glossary_path": "docs/Glossario.tex",
        "glossary_html_path": "public/Glossario.html",
        "glossary_html_url": "http://127.0.0.1:8765/glossary-html",
    })

    saved = webapp.load_editorial_config(editorial_path)

    assert response.status_code == 302
    assert saved.glossary_path == "docs/Glossario.tex"
    assert saved.glossary_html_path == "public/Glossario.html"


def test_create_app_bootstraps_runtime_files(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "EDITORIAL_PATH", tmp_path / "glossary-linker.yml")
    monkeypatch.setattr(webapp, "LOCAL_PATH", tmp_path / "glossary-linker.local.yml")
    monkeypatch.setattr(webapp, "ENTRIES_PATH", tmp_path / "glossary-linker.entries.yml")
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / ".glossary-linker" / "jobs")

    create_app()

    assert webapp.EDITORIAL_PATH.exists()
    assert webapp.LOCAL_PATH.exists()
    assert webapp.ENTRIES_PATH.exists()
    assert webapp.JOBS_DIR.exists()
    assert (tmp_path / ".glossary-linker-secret").exists()
    assert load_entries_store(webapp.ENTRIES_PATH) == []


def test_output_page_no_longer_requires_overwrite_confirmation_checkbox(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("ciao", encoding="utf-8")
    _save_job({
        "id": "output-ui",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("ciao", "Ciao"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "excluded": [],
        "warnings": [],
        "occurrences": [],
        "decisions": {},
    })

    response = client.get("/output/output-ui")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "confirm_overwrite" not in html
    assert "modifica direttamente i file" in html


def test_format_glossary_preview_confirms_detected_entries(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    editorial_path = tmp_path / "glossary-linker.yml"
    save_editorial_config(EditorialConfig(), editorial_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/format-glossary", data={
        "glossary_text": r"\begin{document}\subsection{Accuratezza}Definizione.\end{document}",
        "glossary_detection": "subsection",
        "action": "format",
    })
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Revisione voci rilevate" in html
    assert "Accuratezza" in html
    assert "include_entry_id" in html


def test_format_glossary_save_excludes_unchecked_entries(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    entries_path = tmp_path / "entries.yml"
    editorial_path = tmp_path / "glossary-linker.yml"
    output_path = tmp_path / "Glossario.html"
    save_editorial_config(EditorialConfig(), editorial_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/format-glossary", data={
        "glossary_detection": "subsection",
        "glossary_text": r"\begin{document}\subsection{Voce Buona}Ok.\subsection{Voce Errata}No.\end{document}",
        "entry_id": ["voce-buona", "voce-errata"],
        "include_entry_id": ["voce-buona"],
        "term_voce-buona": "Voce Buona",
        "term_voce-errata": "Voce Errata",
        "definition_voce-buona": "Ok.",
        "definition_voce-errata": "No.",
        "aliases_voce-buona": "",
        "aliases_voce-errata": "",
        "html_output_path": str(output_path),
        "action": "save_html",
    })

    assert response.status_code == 200
    assert output_path.exists()
    assert 'id="gls-voce-buona"' in output_path.read_text(encoding="utf-8")
    assert [entry.id for entry in load_entries_store(entries_path)] == ["voce-buona"]


def test_manual_occurrence_id_matches_linking_with_spaces_in_path(tmp_path):
    root = tmp_path / "progetto con spazi"
    source_dir = root / "capitolo speciale"
    source_dir.mkdir(parents=True)
    source = source_dir / "documento prova.tex"
    source.write_text(
        "\\begin{document}\nQui compare Termine Manuale nel testo.\n\\end{document}\n",
        encoding="utf-8",
    )
    config = EditorialConfig(glossary_html_url="http://127.0.0.1:8765/glossary-html")
    entries = [GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual")]

    occurrences = collect_manual_occurrences([source], entries, config, root=root)
    result = link_file(source, entries, config, {occurrences[0].id: True}, root=root)

    assert len(occurrences) == 1
    assert result.manual_links == 1
    assert r"\glslink{termine-manuale}{Termine Manuale}" in result.linked_text


def test_review_decision_api_saves_and_returns_next_url(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("Termine Manuale", encoding="utf-8")
    occurrence_1 = {
        "id": "occ-1",
        "entry_id": "termine-manuale",
        "term": "Termine Manuale",
        "visible_text": "Termine Manuale",
        "file_path": str(source),
        "line_number": 1,
        "section": "",
        "context": "Termine Manuale",
        "start": 0,
        "end": 15,
    }
    occurrence_2 = {**occurrence_1, "id": "occ-2", "line_number": 2, "start": 16, "end": 31}
    _save_job({
        "id": "ajax-job",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [occurrence_1, occurrence_2],
        "decisions": {},
    })

    response = client.post("/api/decision/ajax-job", json={"occurrence_id": "occ-1", "value": "link"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["redirect_url"].endswith("/review/ajax-job/1")
    assert _load_job("ajax-job")["decisions"] == {"occ-1": True}


def test_review_decision_api_does_not_auto_finish_on_last_occurrence(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("Termine Manuale", encoding="utf-8")
    _save_job({
        "id": "ajax-last",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [{
            "id": "occ-1",
            "entry_id": "termine-manuale",
            "term": "Termine Manuale",
            "visible_text": "Termine Manuale",
            "file_path": str(source),
            "line_number": 1,
            "section": "",
            "context": "Termine Manuale",
            "start": 0,
            "end": 15,
        }],
        "decisions": {},
    })

    response = client.post("/api/decision/ajax-last", json={"occurrence_id": "occ-1", "occurrence_index": 0, "value": "skip"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["redirect_url"].endswith("/review/ajax-last/0")
    assert payload["done"] is True
    assert payload["message"] == "Ultima occorrenza salvata: puoi andare al report finale."
    assert payload["output_url"].endswith("/output/ajax-last")
    assert payload["pending"] == 0
    assert _load_job("ajax-last")["decisions"] == {"occ-1": False}


def test_review_decision_api_uses_page_index_when_occurrence_ids_repeat(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("Termine Manuale\nTermine Manuale\nTermine Manuale", encoding="utf-8")
    base_occurrence = {
        "id": "same-occurrence-id",
        "entry_id": "termine-manuale",
        "term": "Termine Manuale",
        "visible_text": "Termine Manuale",
        "file_path": str(source),
        "section": "",
        "context": "Termine Manuale",
        "start": 0,
        "end": 15,
    }
    _save_job({
        "id": "ajax-duplicate-id",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [
            {**base_occurrence, "line_number": 1, "start": 0, "end": 15},
            {**base_occurrence, "line_number": 2, "start": 16, "end": 31},
            {**base_occurrence, "line_number": 3, "start": 32, "end": 47},
        ],
        "decisions": {},
    })

    response = client.post(
        "/api/decision/ajax-duplicate-id",
        json={"occurrence_id": "same-occurrence-id", "occurrence_index": 1, "value": "link"},
    )
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["redirect_url"].endswith("/review/ajax-duplicate-id/2")
    assert payload["next_index"] == 2
    assert payload["done"] is False


def test_review_bulk_actions_stay_in_review(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("Termine Manuale\nTermine Manuale", encoding="utf-8")
    base_occurrence = {
        "entry_id": "termine-manuale",
        "term": "Termine Manuale",
        "visible_text": "Termine Manuale",
        "file_path": str(source),
        "section": "",
        "context": "Termine Manuale",
    }
    _save_job({
        "id": "bulk-review",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [
            {**base_occurrence, "id": "occ-1", "line_number": 1, "start": 0, "end": 15},
            {**base_occurrence, "id": "occ-2", "line_number": 2, "start": 16, "end": 31},
        ],
        "decisions": {},
    })

    response = client.post("/review/bulk-review/0", data={"action": "skip_file"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/review/bulk-review/0")
    assert _load_job("bulk-review")["decisions"] == {"occ-1": False, "occ-2": False}


def test_review_prev_button_moves_to_previous_occurrence(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("Termine Manuale\nTermine Manuale", encoding="utf-8")
    _save_job({
        "id": "prev-review",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [
            {"id": "occ-1", "entry_id": "termine-manuale", "term": "Termine Manuale", "visible_text": "Termine Manuale", "file_path": str(source), "line_number": 1, "section": "", "context": "Termine Manuale", "start": 0, "end": 15},
            {"id": "occ-2", "entry_id": "termine-manuale", "term": "Termine Manuale", "visible_text": "Termine Manuale", "file_path": str(source), "line_number": 2, "section": "", "context": "Termine Manuale", "start": 16, "end": 31},
        ],
        "decisions": {},
    })

    response = client.post("/review/prev-review/1", data={"action": "prev"})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/review/prev-review/0")


def test_review_page_shows_detected_alias_above_definition(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("AI", encoding="utf-8")
    _save_job({
        "id": "alias-review",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("intelligenza-artificiale", "Intelligenza Artificiale", "Definizione.", aliases=["AI"], mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [{
            "id": "occ-1",
            "entry_id": "intelligenza-artificiale",
            "term": "AI",
            "visible_text": "AI",
            "file_path": str(source),
            "line_number": 1,
            "section": "",
            "context": "AI",
            "start": 0,
            "end": 2,
        }],
        "decisions": {},
    })

    html = client.get("/review/alias-review/0").get_data(as_text=True)

    assert "Alias rilevato" in html
    assert "<h2>AI</h2>" in html
    assert "Voce del glossario: <strong>Intelligenza Artificiale</strong>" in html
    assert "Definizione." in html


def test_wizard_steps_resume_saved_job_from_review_back_link(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(webapp, "ENTRIES_PATH", tmp_path / "entries.yml")
    save_entries_store([GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual")], webapp.ENTRIES_PATH)
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("Termine Manuale", encoding="utf-8")
    _save_job({
        "id": "resume-job",
        "config": asdict(EditorialConfig(glossary_html_url="http://127.0.0.1:8765/glossary-html")),
        "entries": [asdict(GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [{
            "id": "occ-1",
            "entry_id": "termine-manuale",
            "term": "Termine Manuale",
            "visible_text": "Termine Manuale",
            "file_path": str(source),
            "line_number": 1,
            "section": "",
            "context": "Termine Manuale",
            "start": 0,
            "end": 15,
        }],
        "decisions": {},
    })

    review_html = client.get("/review/resume-job/0").get_data(as_text=True)
    glossary_html = client.get("/glossary?job_id=resume-job").get_data(as_text=True)

    assert 'href="/glossary?job_id=resume-job">Torna al glossario</a>' in review_html
    assert "Termine Manuale" in glossary_html
    assert _load_job("resume-job")["paths"] == [str(source)]


def test_settings_invalid_integer_shows_validation_message(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    save_editorial_config(EditorialConfig(), editorial_path)
    save_local_config(LocalConfig(compile_timeout_seconds=120), local_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/settings", data={
        "settings_scope": "environment",
        "default_repo_root": str(tmp_path),
        "temporary_directory": "",
        "latexmk_path": "latexmk",
        "pdflatex_path": "pdflatex",
        "xelatex_path": "xelatex",
        "lualatex_path": "lualatex",
        "preferred_compiler": "latexmk",
        "compile_timeout_seconds": "non-un-numero",
        "max_compile_passes": "2",
        "local_server_port": "8765",
        "log_level": "INFO",
        "preferred_browser": "",
    }, follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "compile_timeout_seconds deve essere un numero intero" in html
    assert webapp.load_local_config(local_path).compile_timeout_seconds == 120


def test_load_job_rejects_path_traversal_id(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    outside = tmp_path / "outside.json"
    outside.write_text('{"id":"outside"}', encoding="utf-8")

    assert _load_job("../outside") is None


def test_corrupt_job_redirects_instead_of_crashing(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    (jobs_dir / "broken.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(webapp, "JOBS_DIR", jobs_dir)
    app = create_app()
    client = app.test_client()

    response = client.get("/output/broken")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/project")


def test_save_output_handles_missing_report_without_crash(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    output = tmp_path / "doc.linked.tex"
    source.write_text("original", encoding="utf-8")
    _save_job({
        "id": "missing-report",
        "results": [{"source": str(source), "output": str(output), "text": "linked"}],
        "report": None,
    })

    response = client.post("/save/missing-report", data={"mode": "linked", "include_report": "1"}, follow_redirects=False)

    assert response.status_code == 302
    assert output.read_text(encoding="utf-8") == "linked"


def test_save_output_rejects_unknown_mode(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    output = tmp_path / "doc.linked.tex"
    source.write_text("original", encoding="utf-8")
    _save_job({
        "id": "bad-save-mode",
        "results": [{"source": str(source), "output": str(output), "text": "linked"}],
        "report": asdict(ProcessingReport()),
    })

    response = client.post("/save/bad-save-mode", data={"mode": "surprise"})

    assert response.status_code == 302
    assert not output.exists()


def test_save_output_rejects_tampered_linked_target(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("original", encoding="utf-8")
    tampered = tmp_path / "other.tex"
    _save_job({
        "id": "tampered-output",
        "results": [{"source": str(source), "output": str(tampered), "text": "linked"}],
        "report": asdict(ProcessingReport()),
    })

    response = client.post("/save/tampered-output", data={"mode": "linked"})

    assert response.status_code == 302
    assert not tampered.exists()


def test_compile_output_rejects_tampered_result_path(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("original", encoding="utf-8")
    tampered = tmp_path / "other.tex"
    _save_job({
        "id": "tampered-compile",
        "results": [{"source": str(source), "output": str(tampered), "text": "linked"}],
        "report": asdict(ProcessingReport()),
    })

    response = client.post("/compile/tampered-compile", data={"source": str(source)})

    assert response.status_code == 302
    assert not tampered.exists()


def test_home_survives_corrupt_entries_store(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    entries_path = tmp_path / "entries.yml"
    entries_path.write_text("- not-a-mapping", encoding="utf-8")
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    app = create_app()
    client = app.test_client()

    with pytest.warns(UserWarning, match="Glossario rilevato non leggibile"):
        response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Glossario rilevato non leggibile" in html


def test_wizard_state_uses_payload_job_id_without_session(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    _save_job({
        "id": "payload-job",
        "config": asdict(EditorialConfig()),
        "entries": [],
        "paths": [],
        "root": str(tmp_path),
        "review_order": "by_term",
    })

    response = client.post("/wizard-state", json={"job_id": "payload-job", "tex_paths": "doc.tex"})

    assert response.status_code == 200
    assert _load_job("payload-job")["paths"] == ["doc.tex"]


def test_review_decision_api_reports_malformed_occurrence(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    app = create_app()
    client = app.test_client()
    _save_job({
        "id": "bad-review-job",
        "config": asdict(EditorialConfig()),
        "entries": [],
        "paths": [],
        "root": str(tmp_path),
        "occurrences": [{"id": "occ-1"}],
        "decisions": {},
    })

    response = client.post("/api/decision/bad-review-job", json={"occurrence_id": "occ-1", "value": "link"})
    payload = response.get_json()

    assert response.status_code == 409
    assert payload["ok"] is False
    assert "occorrenza #1" in payload["error"]


def test_glossary_preview_does_not_clear_source_when_payload_omits_field(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    glossary = tmp_path / "Glossario.tex"
    glossary.write_text("\\begin{document}\\subsection{Accuratezza}Definizione.\\end{document}", encoding="utf-8")
    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    entries_path = tmp_path / "entries.yml"
    save_editorial_config(EditorialConfig(glossary_path="Glossario.tex", glossary_detection="subsection"), editorial_path)
    save_local_config(LocalConfig(default_repo_root=str(tmp_path)), local_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/glossary-preview", json={"glossary_html_url": "http://127.0.0.1:8765/glossary-html"})

    assert response.status_code == 200
    assert response.get_json()["stats"]["total"] == 1
    assert webapp.load_editorial_config(editorial_path).glossary_path == "Glossario.tex"


def test_glossary_preview_updates_active_wizard_job(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    glossary = tmp_path / "Glossario.tex"
    glossary.write_text("\\begin{document}\\subsection{Voce Nuova}Definizione.\\end{document}", encoding="utf-8")
    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    entries_path = tmp_path / "entries.yml"
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    save_editorial_config(EditorialConfig(glossary_path="Glossario.tex", glossary_detection="subsection"), editorial_path)
    save_local_config(LocalConfig(default_repo_root=str(tmp_path)), local_path)
    _save_job({
        "id": "preview-job",
        "config": asdict(EditorialConfig(glossary_path="Glossario.tex", glossary_detection="subsection")),
        "entries": [],
        "paths": [],
        "root": str(tmp_path),
        "decisions": {},
    })
    app = create_app()
    client = app.test_client()

    response = client.post("/glossary-preview", json={"job_id": "preview-job"})

    assert response.status_code == 200
    assert _load_job("preview-job")["entries"][0]["id"] == "voce-nuova"


def test_started_job_keeps_snapshot_when_glossary_store_changes(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    entries_path = tmp_path / "entries.yml"
    jobs_dir = tmp_path / "jobs"
    source = tmp_path / "doc.tex"
    source.write_text("Voce Nuova", encoding="utf-8")
    save_entries_store([GlossaryEntry("voce-nuova", "Voce Nuova", mode="manual")], entries_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    monkeypatch.setattr(webapp, "JOBS_DIR", jobs_dir)
    app = create_app()
    client = app.test_client()
    _save_job({
        "id": "rerun-job",
        "config": asdict(EditorialConfig(glossary_html_url="http://127.0.0.1:8765/glossary-html")),
        "entries": [asdict(GlossaryEntry("voce-vecchia", "Voce Vecchia", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "review_order": "by_term",
        "occurrences": [{
            "id": "old-occ",
            "entry_id": "voce-vecchia",
            "term": "Voce Vecchia",
            "visible_text": "Voce Vecchia",
            "file_path": str(source),
            "line_number": 1,
            "section": "",
            "context": "Voce Vecchia",
            "start": 0,
            "end": 11,
        }],
        "decisions": {"stale-occurrence": True},
        "results": [{"source": str(source), "output": str(tmp_path / "doc.linked.tex"), "text": "stale"}],
        "report": asdict(ProcessingReport()),
        "started": True,
    })

    response = client.post("/glossary?job_id=rerun-job", data={
        "glossary_html_url": "http://127.0.0.1:8765/glossary-html",
        "entry_id": ["voce-nuova"],
        "action": "continue",
    })
    job = _load_job("rerun-job")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/review/rerun-job/0")
    assert job["entries"][0]["id"] == "voce-vecchia"
    assert job["occurrences"][0]["entry_id"] == "voce-vecchia"
    assert job["decisions"] == {"stale-occurrence": True}
    assert job["results"] == [{"source": str(source), "output": str(tmp_path / "doc.linked.tex"), "text": "stale"}]
    assert job["report"] is not None


def test_glossary_preview_rejects_directory_source_with_clear_message(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    save_editorial_config(EditorialConfig(glossary_path=""), editorial_path)
    save_local_config(LocalConfig(default_repo_root=str(tmp_path)), local_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/glossary-preview", json={"glossary_path": str(tmp_path)})
    payload = response.get_json()

    assert response.status_code == 400
    assert payload["ok"] is False
    assert "directory" in payload["error"]


def test_glossary_step_rehydrates_empty_job_from_entries_store(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    entries_path = tmp_path / "entries.yml"
    jobs_dir = tmp_path / "jobs"
    save_entries_store([GlossaryEntry("accuratezza", "Accuratezza")], entries_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    monkeypatch.setattr(webapp, "JOBS_DIR", jobs_dir)
    app = create_app()
    client = app.test_client()
    _save_job({
        "id": "empty-job",
        "config": asdict(EditorialConfig(glossary_html_url="http://127.0.0.1:8765/glossary-html")),
        "entries": [],
        "paths": [],
        "root": str(tmp_path),
        "occurrences": [],
        "decisions": {},
    })

    html = client.get("/glossary?job_id=empty-job").get_data(as_text=True)

    assert "Accuratezza" in html
    assert _load_job("empty-job")["entries"][0]["id"] == "accuratezza"


def test_settings_rejects_glossary_source_directory(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    save_editorial_config(EditorialConfig(glossary_path="Glossario.tex"), editorial_path)
    save_local_config(LocalConfig(default_repo_root=str(tmp_path)), local_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/settings", data={
        "settings_scope": "environment",
        "default_repo_root": str(tmp_path),
        "temporary_directory": "",
        "latexmk_path": "latexmk",
        "pdflatex_path": "pdflatex",
        "xelatex_path": "xelatex",
        "lualatex_path": "lualatex",
        "preferred_compiler": "latexmk",
        "compile_timeout_seconds": "120",
        "max_compile_passes": "2",
        "local_server_port": "8765",
        "log_level": "INFO",
        "preferred_browser": "",
        "glossary_path": str(tmp_path),
        "glossary_html_path": "Glossario.html",
        "glossary_html_url": "http://127.0.0.1:8765/glossary-html",
    }, follow_redirects=True)
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "non una directory" in html
    assert webapp.load_editorial_config(editorial_path).glossary_path == "Glossario.tex"
