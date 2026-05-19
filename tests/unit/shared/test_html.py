from shared.text import clean_text, ensure_display_html, html_to_text, sanitize_display_html


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


def test_sanitize_display_html_keeps_allowlist_without_attributes() -> None:
    raw = (
        '<p class="lead">Halo <strong onclick="x()">tim</strong></p>'
        '<ul data-x="1"><li>Item</li></ul>'
    )
    assert sanitize_display_html(raw) == "<p>Halo <strong>tim</strong></p><ul><li>Item</li></ul>"


def test_sanitize_display_html_drops_unsafe_tags_and_content() -> None:
    raw = (
        '<p>Halo</p><script>alert("x")</script>'
        '<a href="javascript:alert(1)">klik</a><img src="x" onerror="x">'
    )
    assert sanitize_display_html(raw) == "<p>Halo</p>klik"


def test_ensure_display_html_wraps_plain_text_into_paragraph() -> None:
    assert ensure_display_html("Ringkas dan jelas") == "<p>Ringkas dan jelas</p>"


def test_ensure_display_html_turns_bullets_into_list() -> None:
    raw = "- Python\n- SQL\n- Docker"
    assert ensure_display_html(raw) == "<ul><li>Python</li><li>SQL</li><li>Docker</li></ul>"
