from fastapi.testclient import TestClient

from app.main import app
from app.pixel_emoji import PACKS, picker_catalog
from app.pixel_icons import mapped_icon_names, pixel_icon
from app.player import (
    DEFAULT_THEME,
    DEFAULT_WALLPAPER,
    THEMES,
    WALLPAPER_SPECS,
    normalize_theme,
    normalize_wallpaper,
    wallpaper_available,
    wallpaper_catalog,
    wallpaper_class,
    wallpaper_src,
    wallpaper_style,
    wallpaper_thumb_src,
)
from tests.test_app import register_active


IMAGE_PAPERS = (
    "azure-cove",
    "sunset-mirror",
    "moonlit-sea",
    "sea-stacks",
    "teal-city",
    "candy-city",
    "golden-clouds",
    "dusk-skyline",
    "sunflower-field",
    "lilac-peaks",
)


def test_palette_catalog_is_expanded_and_distinct():
    assert len(THEMES) == 22
    for key in (
        "watchclub",
        "bubblegum",
        "dreamy",
        "matcha",
        "cyber",
        "campfire",
        "piece",
        "mocha",
        "nightclub",
        "cherries",
        "cotton",
        "castle",
        "muddy",
        "lagoon",
        "frost",
        "lemon",
        "brick",
        "pine",
        "lime",
        "bluebird",
        "voltage",
        "peach",
    ):
        assert key in THEMES
    assert normalize_theme("rainbow-hacks") == DEFAULT_THEME
    css = TestClient(app).get("/static/style.css").text
    compact = css.replace(" ", "")
    for key in THEMES:
        assert f".wc-theme-{key}" in css or f"html.dark.wc-theme-{key}" in css
        assert f"--wc-window-light" in css
    assert ".wc-theme-campfire{--wc-blue:#4a2818" in compact
    assert ".wc-theme-frost{" in compact
    assert ".wc-theme-lemon{--wc-blue:#5a4010" in compact
    assert ".wc-theme-voltage{" in compact
    assert "--wc-desktop:#123050" in compact


def test_image_wallpapers_are_local_and_independent_of_palette():
    assert len(IMAGE_PAPERS) == 10
    for key in IMAGE_PAPERS:
        spec = WALLPAPER_SPECS[key]
        assert spec["kind"] == "image"
        assert wallpaper_available(spec)
        src = wallpaper_src(spec)
        thumb = wallpaper_thumb_src(spec)
        assert src.startswith("/static/wallpapers/")
        assert "://" not in src[1:]
        assert thumb.startswith("/static/wallpapers/thumbs/")
        client = TestClient(app)
        assert client.get(src).status_code == 200
        assert client.get(thumb).status_code == 200
        style = wallpaper_style(key)
        assert src in style
        assert thumb in style
        assert wallpaper_class(key) == f"wc-paper-asset wc-paper-{key}"
    assert wallpaper_class("missing-paper") == f"wc-paper-{DEFAULT_WALLPAPER}"
    assert normalize_wallpaper("missing-paper") == DEFAULT_WALLPAPER
    assert wallpaper_style("grid") == ""


def test_look_studio_can_combine_any_palette_with_image_paper():
    owner = TestClient(app)
    register_active(owner, "look_mix", "look.mix@example.com")
    saved = owner.post(
        "/u/look_mix/aparencia",
        data={"theme": "campfire", "wallpaper": "sunflower-field"},
        follow_redirects=False,
    )
    assert saved.status_code == 303
    page = owner.get("/u/look_mix?aba=aparencia")
    assert "wc-theme-campfire" in page.text
    assert "wc-paper-asset" in page.text
    assert "sunflower-field.png" in page.text
    assert "thumbs/sunflower-field.jpg" in page.text
    swapped = owner.post(
        "/u/look_mix/aparencia",
        data={"theme": "frost", "wallpaper": "sunflower-field"},
        follow_redirects=False,
    )
    assert swapped.status_code == 303
    again = owner.get("/u/look_mix?aba=aparencia")
    assert "wc-theme-frost" in again.text
    assert "sunflower-field.png" in again.text


def test_pixel_icons_map_to_local_svg_and_keep_drawn_fallbacks():
    mapped = set(mapped_icon_names())
    for name in (
        "home",
        "calendar",
        "news",
        "clubs",
        "friends",
        "messages",
        "admin",
        "settings",
        "mailbox",
        "shield",
        "search",
        "back",
        "palette",
        "bell",
        "pencil",
        "trash",
        "user",
        "group",
        "left",
        "right",
        "smile",
        "face",
    ):
        assert name in mapped
        markup = str(pixel_icon(name))
        assert 'class="wc-px' in markup or "wc-px" in markup
        assert "currentColor" in markup
        assert 'viewBox="0 0 32 32"' in markup
        assert "figma.com" not in markup
        assert "cdn." not in markup
    plus = str(pixel_icon("plus"))
    close = str(pixel_icon("close"))
    assert 'viewBox="0 0 16 16"' in plus
    assert 'viewBox="0 0 16 16"' in close
    home = TestClient(app).get("/")
    # Unauthenticated home may redirect; register for chrome icons.
    person = TestClient(app)
    register_active(person, "icon_own", "icon.own@example.com")
    page = person.get("/")
    assert "/static/icons/" not in page.text  # inlined SVGs
    assert "currentColor" in page.text
    css = person.get("/static/style.css").text
    assert "url('https://" not in css
    assert "figma.com" not in css


def test_emoji_picker_catalog_is_local_and_restores_pixelmojis():
    data = picker_catalog()
    labels = {pack["id"]: pack["label"] for pack in data["packs"]}
    assert labels["emojis"] == "Emojis"
    assert labels["reactions"] == "Reações"
    assert labels["social"] == "Social"
    assert "icons" not in labels
    assert "pixelmojis" not in labels
    assert PACKS["pixelmojis"]["picker"] is True
    assert any(item["token"].startswith(":pixelmojis-") for item in data["items"])
    for item in data["items"]:
        assert item["src"].startswith("/static/emojis/")
        assert "://" not in item["src"][1:]
    person = TestClient(app)
    register_active(person, "emoji_own", "emoji.own@example.com")
    home = person.get("/")
    assert ":joyquest-" in home.text
    assert ":pixelmojis-" in home.text
    conta = person.get("/conta")
    assert "<h2>Avatar</h2>" in conta.text
    assert "<h2>Usuário</h2>" in conta.text
    assert "Imagem de perfil" not in conta.text
    assert "account-page" in conta.text
    assert "account-avatar-frame" in conta.text
    assert "js-confirm-dialog" in home.text
    assert "Apagar mensagem?" in home.text
