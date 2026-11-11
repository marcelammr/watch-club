from __future__ import annotations

import io
import secrets
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

STYLE_ORIGINAL = "original"
STYLE_PIXEL = "pixel"  # legado: tratado como Faithful Colors
STYLE_FAITHFUL = "faithful"
STYLE_PICO8 = "pico8"
STYLE_GAMEBOY = "gameboy"
STYLE_1BIT = "1bit"
STYLE_CGA = "cga"

PRESETS = (
    STYLE_ORIGINAL,
    STYLE_FAITHFUL,
    STYLE_PICO8,
    STYLE_GAMEBOY,
    STYLE_1BIT,
    STYLE_CGA,
)
STYLES = PRESETS  # compatível com testes/rotas antigas
STATUS_NONE = "none"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
STATUSES = (STATUS_NONE, STATUS_READY, STATUS_FAILED)

PRESET_CHOICES = (
    (STYLE_ORIGINAL, "Original"),
    (STYLE_FAITHFUL, "Faithful"),
    (STYLE_PICO8, "PICO-8"),
    (STYLE_GAMEBOY, "Game Boy"),
    (STYLE_1BIT, "1-bit"),
    (STYLE_CGA, "CGA"),
)

# Paleta PICO-8 pública (16 cores). Valores de cor, não código de terceiros.
PICO8_PALETTE = (
    (0, 0, 0),
    (29, 43, 83),
    (126, 37, 83),
    (0, 135, 81),
    (171, 82, 54),
    (95, 87, 79),
    (194, 195, 199),
    (255, 241, 232),
    (255, 0, 77),
    (255, 163, 0),
    (255, 236, 39),
    (0, 228, 54),
    (41, 173, 255),
    (131, 118, 156),
    (255, 119, 168),
    (255, 204, 170),
)

# LCD clássico do Game Boy (DMG).
GAMEBOY_PALETTE = (
    (15, 56, 15),
    (48, 98, 48),
    (139, 172, 15),
    (155, 188, 15),
)

# CGA modo 1, intensidade alta (ciano / magenta / branco).
CGA_PALETTE = (
    (0, 0, 0),
    (85, 255, 255),
    (255, 85, 255),
    (255, 255, 255),
)

ONE_BIT_PALETTE = (
    (18, 42, 74),
    (247, 238, 248),
)

MAX_IMAGE_PIXELS = 8_000_000
MAX_EDGE = 2048
PIXEL_LONG_SIDE = 64
UPSCALE = 4
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS


class PixelArtError(Exception):
    """Raised when stylized pixel art cannot be produced."""


class PixelArtProvider:
    """Compatibilidade: o processamento agora é local, sem gerador externo."""

    def generate(self, source: Path) -> bytes:
        return render_preset(source, STYLE_FAITHFUL)


def get_provider() -> PixelArtProvider:
    return PixelArtProvider()


def normalize_style(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key == STYLE_PIXEL:
        return STYLE_FAITHFUL
    return key if key in PRESETS else STYLE_ORIGINAL


def require_style(value: str | None) -> str:
    key = (value or "").strip().lower()
    if key == STYLE_PIXEL:
        return STYLE_FAITHFUL
    if key not in PRESETS:
        raise PixelArtError("Estilo de imagem inválido.")
    return key


def is_styled(value: str | None) -> bool:
    return normalize_style(value) != STYLE_ORIGINAL


def generate_derivative(source: Path, dest: Path, *, provider: PixelArtProvider | None = None, preset: str = STYLE_FAITHFUL) -> Path:
    if provider is not None:
        data = provider.generate(source)
        chosen = STYLE_FAITHFUL
    else:
        chosen = normalize_style(preset)
        if chosen == STYLE_ORIGINAL:
            raise PixelArtError("Original não gera derivada.")
        data = render_preset(source, chosen)
    if not data:
        raise PixelArtError("A versão pixel art veio vazia.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return dest


def render_preset(source: Path | bytes | Image.Image, preset: str) -> bytes:
    chosen = require_style(preset)
    image = _load_image(source)
    if chosen == STYLE_ORIGINAL:
        return _encode_png(image)
    pixelated = _pixelize(image, chosen)
    return _encode_png(pixelated)


def preview_bytes(data: bytes, preset: str) -> bytes:
    return render_preset(data, preset)


def write_derivative(source: Path, dest_dir: Path, preset: str) -> str:
    chosen = require_style(preset)
    if chosen == STYLE_ORIGINAL:
        raise PixelArtError("Original não gera derivada.")
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = f"{secrets.token_hex(12)}.png"
    dest = dest_dir / name
    generate_derivative(source, dest, preset=chosen)
    return name


def attach_preset(original_name: str | None, locator, dest_dir: Path, preset: str | None) -> tuple[str | None, str]:
    """Gera derivada a partir do original. Preserva o arquivo-fonte em falha."""
    if not original_name:
        return None, STYLE_ORIGINAL
    chosen = normalize_style(preset)
    if chosen == STYLE_ORIGINAL:
        return None, STYLE_ORIGINAL
    source = locator(original_name)
    if source is None:
        return None, STYLE_ORIGINAL
    try:
        return write_derivative(source, dest_dir, chosen), chosen
    except PixelArtError:
        return None, STYLE_ORIGINAL


def styled_public_url(
    style: str | None,
    pixel_name: str | None,
    original_name: str | None,
    prefix: str,
    locator,
) -> str | None:
    if is_styled(style) and pixel_name:
        path = locator(pixel_name)
        if path:
            return f"{prefix}{path.name}"
    if original_name:
        path = locator(original_name)
        if path:
            return f"{prefix}{path.name}"
    return None


def _load_image(source: Path | bytes | Image.Image) -> Image.Image:
    try:
        if isinstance(source, Image.Image):
            image = source
        elif isinstance(source, (bytes, bytearray)):
            image = Image.open(io.BytesIO(source))
        else:
            image = Image.open(source)
        image.load()
    except UnidentifiedImageError as exc:
        raise PixelArtError("Arquivo de imagem inválido.") from exc
    except Image.DecompressionBombError as exc:
        raise PixelArtError("A imagem é grande demais para processar.") from exc
    except OSError as exc:
        raise PixelArtError("Não foi possível ler a imagem.") from exc
    image = ImageOps.exif_transpose(image) or image
    if image.width > MAX_EDGE or image.height > MAX_EDGE:
        image.thumbnail((MAX_EDGE, MAX_EDGE), Image.Resampling.LANCZOS)
    if image.width * image.height > MAX_IMAGE_PIXELS:
        raise PixelArtError("A imagem é grande demais para processar.")
    if image.mode not in {"RGB", "RGBA"}:
        image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
    return image


def _pixel_size(width: int, height: int) -> tuple[int, int]:
    long_side = max(width, height)
    target = min(PIXEL_LONG_SIDE, long_side)
    scale = target / long_side
    return max(8, int(round(width * scale))), max(8, int(round(height * scale)))


def _pixelize(image: Image.Image, preset: str) -> Image.Image:
    rgba = image.convert("RGBA")
    small_w, small_h = _pixel_size(rgba.width, rgba.height)
    small = rgba.resize((small_w, small_h), Image.Resampling.BOX)
    rgb = Image.new("RGB", small.size, (247, 238, 248))
    rgb.paste(small, mask=small.split()[3] if small.mode == "RGBA" else None)
    if preset == STYLE_FAITHFUL:
        quantized = rgb.quantize(colors=48, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    elif preset == STYLE_PICO8:
        quantized = _quantize_palette(rgb, PICO8_PALETTE, dither=True)
    elif preset == STYLE_GAMEBOY:
        quantized = _quantize_palette(_luma_image(rgb), GAMEBOY_PALETTE, dither=True)
    elif preset == STYLE_1BIT:
        quantized = _quantize_palette(_luma_image(rgb), ONE_BIT_PALETTE, dither=True)
    elif preset == STYLE_CGA:
        quantized = _quantize_palette(rgb, CGA_PALETTE, dither=True)
    else:
        quantized = rgb
    color = quantized.convert("RGB")
    return color.resize((small_w * UPSCALE, small_h * UPSCALE), Image.Resampling.NEAREST)


def _luma_image(rgb: Image.Image) -> Image.Image:
    return rgb.convert("L").convert("RGB")


def _quantize_palette(rgb: Image.Image, colors: tuple[tuple[int, int, int], ...], *, dither: bool) -> Image.Image:
    palette = Image.new("P", (1, 1))
    flat: list[int] = []
    for color in colors:
        flat.extend(color)
    while len(flat) < 768:
        flat.extend(colors[-1])
    palette.putpalette(flat[:768])
    dither_mode = Image.Dither.FLOYDSTEINBERG if dither else Image.Dither.NONE
    return rgb.convert("RGB").quantize(palette=palette, dither=dither_mode)


def _encode_png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    data = buffer.getvalue()
    if not data:
        raise PixelArtError("A versão pixel art veio vazia.")
    return data
