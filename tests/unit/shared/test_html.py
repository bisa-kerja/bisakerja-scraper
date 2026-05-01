from shared.text import clean_text, html_to_text


def test_html_to_text_removes_noise_and_normalizes_whitespace() -> None:
    html = """
    <section>
      <style>.x { color: red; }</style>
      <script>window.token = "secret";</script>
      <p><strong>Build</strong>&amp; ship</p>
      <ul><li>Clean text</li></ul>
    </section>
    """

    assert html_to_text(html) == "Build & ship Clean text"


def test_html_to_text_handles_empty_input() -> None:
    assert html_to_text("") is None
    assert html_to_text(None) is None


def test_clean_text_normalizes_plain_text() -> None:
    assert clean_text("  one\n\n two\tthree  ") == "one two three"
