from app.markup import format_chat


def test_plain_text_is_unchanged():
    assert str(format_chat("Vamos maratonar?")) == "Vamos maratonar?"


def test_html_is_escaped():
    html = str(format_chat('<script>alert(1)</script> e <b>x</b>'))
    assert "<script>" not in html
    assert "<b>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;b&gt;" in html


def test_bold_italic_spoiler():
    html = str(format_chat("**oi** *ola* ||segredo||"))
    assert "<strong>oi</strong>" in html
    assert "<em>ola</em>" in html
    assert 'class="chat-spoiler"' in html
    assert "segredo" in html
    assert "||" not in html


def test_spoiler_does_not_keep_raw_html():
    html = str(format_chat("||<img src=x onerror=alert(1)>||"))
    assert "<img" not in html
    assert "&lt;img" in html
    assert 'class="chat-spoiler"' in html
