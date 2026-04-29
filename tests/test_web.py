from dataclasses import asdict

from glossary_linker.core.config import EditorialConfig, save_editorial_config
from glossary_linker.core.glossary import load_entries_store, save_entries_store
from glossary_linker.core.models import GlossaryEntry, ProcessingReport
from glossary_linker.web.app import JOBS, create_app


def test_glossary_rules_requires_current_operation_session():
    app = create_app()
    client = app.test_client()

    response = client.get("/glossary")

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_operation_progress_keeps_rules_disabled_before_choice():
    app = create_app()
    client = app.test_client()

    response = client.get("/")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert '<span class="disabled">Regole</span>' in html


def test_save_output_generates_report_only_when_requested(monkeypatch, tmp_path):
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    output = tmp_path / "doc.linked.tex"
    source.write_text("original", encoding="utf-8")
    calls = []
    job_id = "save-output"
    JOBS[job_id] = {
        "results": [{"source": str(source), "output": str(output), "text": "linked"}],
        "report": asdict(ProcessingReport()),
    }
    monkeypatch.setattr("glossary_linker.web.app.save_report_markdown", lambda report, path: calls.append(("md", path)))
    monkeypatch.setattr("glossary_linker.web.app.save_report_json", lambda report, path: calls.append(("json", path)))

    response = client.post(f"/save/{job_id}", data={"mode": "linked"})

    assert response.status_code == 302
    assert output.read_text(encoding="utf-8") == "linked"
    assert calls == []

    response = client.post(f"/save/{job_id}", data={"mode": "overwrite", "include_report": "1", "report_format": "json"})

    assert response.status_code == 302
    assert source.read_text(encoding="utf-8") == "linked"
    assert calls and calls[-1][0] == "json"
    JOBS.pop(job_id, None)


def test_output_does_not_print_missing_term_names(tmp_path):
    app = create_app()
    client = app.test_client()
    source = tmp_path / "doc.tex"
    source.write_text("\\begin{document}Nessun match.\\end{document}", encoding="utf-8")
    job_id = "missing-terms"
    JOBS[job_id] = {
        "config": asdict(EditorialConfig()),
        "entries": [asdict(GlossaryEntry("termine-assente", "Termine Assente"))],
        "paths": [str(source)],
        "root": str(tmp_path),
        "excluded": [],
        "warnings": [],
        "occurrences": [],
        "decisions": {},
    }

    response = client.get(f"/output/{job_id}")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Termini non trovati" in html
    assert "Termine Assente" not in html
    JOBS.pop(job_id, None)


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
    output_path = tmp_path / "Glossario.formatted.tex"
    save_editorial_config(EditorialConfig(), editorial_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", entries_path)
    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    app = create_app()
    client = app.test_client()

    response = client.post("/format-glossary", data={
        "glossary_detection": "subsection",
        "formatted_text": r"\begin{document}\subsection{Voce Buona}Ok.\subsection{Voce Errata}No.\end{document}",
        "entry_id": ["voce-buona", "voce-errata"],
        "include_entry_id": ["voce-buona"],
        "term_voce-buona": "Voce Buona",
        "term_voce-errata": "Voce Errata",
        "definition_voce-buona": "Ok.",
        "definition_voce-errata": "No.",
        "aliases_voce-buona": "",
        "aliases_voce-errata": "",
        "save_mode": "copy",
        "output_path": str(output_path),
        "action": "save_formatted",
    })

    assert response.status_code == 200
    assert output_path.exists()
    assert [entry.id for entry in load_entries_store(entries_path)] == ["voce-buona"]
