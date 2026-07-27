import pytest

from glossary_linker.core.config import (
    EditorialConfig,
    LocalConfig,
    load_editorial_config,
    load_local_config,
    save_editorial_config,
    save_local_config,
)


def test_save_editorial_config_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "glossary-linker.yml"

    save_editorial_config(EditorialConfig(glossary_path="/tmp/Glossario.tex", glossary_detection="subsection"), path)

    assert path.exists()
    assert load_editorial_config(path).glossary_detection == "subsection"
    assert "glossary_path:" not in path.read_text(encoding="utf-8")
    assert "glossary_json_path:" not in path.read_text(encoding="utf-8")
    assert not path.with_suffix(".yml.tmp").exists()


def test_local_config_persists_glossary_paths(tmp_path):
    path = tmp_path / "glossary-linker.local.yml"

    save_local_config(LocalConfig(glossary_path="docs/Glossario.tex", glossary_json_path="public/glossary.json"), path)

    saved = load_local_config(path)
    assert saved.glossary_path == "docs/Glossario.tex"
    assert saved.glossary_json_path == "public/glossary.json"


def test_legacy_html_path_is_migrated_with_deprecation_warning(tmp_path):
    path = tmp_path / "glossary-linker.local.yml"
    path.write_text("glossary_html_path: public/Glossario.html\n", encoding="utf-8")

    with pytest.warns(FutureWarning, match="glossary_html_path.*glossary_json_path"):
        saved = load_local_config(path)

    assert saved.glossary_json_path == "public/Glossario.json"


def test_load_editorial_config_reports_invalid_yaml(tmp_path):
    path = tmp_path / "glossary-linker.yml"
    path.write_text("entries: [", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid YAML"):
        load_editorial_config(path)
