from dataclasses import asdict

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

    response = client.post(f"/save/{job_id}", data={"mode": "overwrite", "include_report": "1", "report_format": "json"})

    assert response.status_code == 302
    assert source.read_text(encoding="utf-8") == "original"
    assert calls == []

    response = client.post(f"/save/{job_id}", data={
        "mode": "overwrite",
        "confirm_overwrite": "1",
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
    occurrence = {
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
    _save_job({
        "id": "ajax-job",
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-manuale", "Termine Manuale", mode="manual"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "occurrences": [occurrence],
        "decisions": {},
    })

    response = client.post("/api/decision/ajax-job", json={"occurrence_id": "occ-1", "value": "link"})
    payload = response.get_json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["redirect_url"].endswith("/output/ajax-job")
    assert _load_job("ajax-job")["decisions"] == {"occ-1": True}


def test_wizard_steps_resume_saved_job_from_review_back_link(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
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

    assert 'href="/glossary?job_id=resume-job">Indietro</a>' in review_html
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
