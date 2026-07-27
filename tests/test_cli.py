import sys
import json

from glossary_linker.cli import main
from glossary_linker.core.config import EditorialConfig, LocalConfig, save_editorial_config, save_local_config


def test_cli_reads_glossary_path_from_local_config(monkeypatch, tmp_path):
    glossary_path = tmp_path / "Glossario.tex"
    document_path = tmp_path / "documento.tex"
    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    json_path = tmp_path / "site" / "glossary.json"
    glossary_path.write_text(r"\subsection{Accuratezza} Definizione.", encoding="utf-8")
    document_path.write_text("Accuratezza", encoding="utf-8")
    save_editorial_config(EditorialConfig(glossary_detection="subsection"), editorial_path)
    save_local_config(LocalConfig(glossary_path=str(glossary_path), glossary_json_path=str(json_path)), local_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "glossary-linker-cli",
            str(document_path),
            "--config",
            str(editorial_path),
            "--local-config",
            str(local_path),
        ],
    )

    main()

    linked_path = tmp_path / "documento.linked.tex"
    assert linked_path.exists()
    assert r"\glslink{accuratezza}{Accuratezza}" in linked_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["entries"][0]["id"] == "accuratezza"


def test_cli_can_export_json_without_linking_documents(monkeypatch, tmp_path):
    glossary_path = tmp_path / "Glossario.tex"
    editorial_path = tmp_path / "glossary-linker.yml"
    output_path = tmp_path / "glossary.json"
    glossary_path.write_text(r"\subsection{Ètà} Definizione con accento.", encoding="utf-8")
    save_editorial_config(EditorialConfig(glossary_detection="subsection"), editorial_path)
    monkeypatch.setattr(sys, "argv", [
        "glossary-linker-cli",
        "--config", str(editorial_path),
        "--glossary", str(glossary_path),
        "--glossary-json", str(output_path),
    ])

    main()

    assert json.loads(output_path.read_text(encoding="utf-8")) == {
        "title": "Glossario",
        "entries": [{
            "id": "eta",
            "term": "Ètà",
            "definition": "Definizione con accento.",
            "aliases": [],
        }],
    }


def test_cli_and_web_download_produce_identical_bytes(monkeypatch, tmp_path):
    import glossary_linker.web.app as webapp

    glossary_path = tmp_path / "Glossario.tex"
    editorial_path = tmp_path / "glossary-linker.yml"
    local_path = tmp_path / "glossary-linker.local.yml"
    output_path = tmp_path / "site" / "glossary.json"
    glossary_path.write_text(
        "\\subsection{Ètà}\nDefinizione.\n\\subsection{API}\nInterfaccia applicativa.\n",
        encoding="utf-8",
    )
    save_editorial_config(EditorialConfig(glossary_detection="subsection"), editorial_path)
    save_local_config(LocalConfig(
        default_repo_root=str(tmp_path),
        glossary_path=str(glossary_path),
        glossary_json_path=str(output_path),
    ), local_path)
    monkeypatch.setattr(sys, "argv", [
        "glossary-linker-cli",
        "--config", str(editorial_path),
        "--local-config", str(local_path),
    ])

    main()

    monkeypatch.setattr(webapp, "EDITORIAL_PATH", editorial_path)
    monkeypatch.setattr(webapp, "LOCAL_PATH", local_path)
    monkeypatch.setattr(webapp, "ENTRIES_PATH", tmp_path / "entries.yml")
    monkeypatch.setattr(webapp, "JOBS_DIR", tmp_path / "jobs")
    response = webapp.create_app().test_client().get("/glossary-json")

    assert response.status_code == 200
    assert response.data == output_path.read_bytes()
