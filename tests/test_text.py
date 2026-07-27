from glossary_linker.core.text import strip_latex


def test_strip_latex_distinguishes_literal_percent_from_comments():
    assert strip_latex(r"Valore 80\%.") == "Valore 80%."
    assert strip_latex("Testo % commento") == "Testo"
    assert strip_latex(r"Valore 80\%. % commento") == "Valore 80%."
