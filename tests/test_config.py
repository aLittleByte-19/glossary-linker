import pytest

from glossary_linker.core.config import EditorialConfig, load_editorial_config, save_editorial_config


def test_save_editorial_config_creates_parent_directories(tmp_path):
    path = tmp_path / "nested" / "glossary-linker.yml"

    save_editorial_config(EditorialConfig(glossary_path="Glossario.tex"), path)

    assert path.exists()
    assert load_editorial_config(path).glossary_path == "Glossario.tex"
    assert not path.with_suffix(".yml.tmp").exists()


def test_load_editorial_config_reports_invalid_yaml(tmp_path):
    path = tmp_path / "glossary-linker.yml"
    path.write_text("entries: [", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid YAML"):
        load_editorial_config(path)
