from app.pixel_icons import pixel_icon


def test_lucide_star_is_inline_theme_aware_and_uses_lucide_geometry():
    markup = str(pixel_icon("lucide-star"))

    assert 'class="wc-px lucide lucide-star wc-lucide-star"' in markup
    assert 'fill="currentColor"' in markup
    assert 'stroke="currentColor"' in markup
    assert 'stroke-width="1.5"' in markup
    assert 'viewBox="0 0 24 24"' in markup
    assert "M11.525 2.295" in markup
