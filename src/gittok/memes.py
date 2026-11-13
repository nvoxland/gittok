"""Draw meme cards locally, using bundled defaults and optional downloaded templates.

Default images, layouts and free fonts from memegen ship in the package. A user's
download in `<data_dir>/memes/` takes precedence. Runtime rendering needs no network.
See assets/memes/SOURCES.json and the accompanying upstream notices.
"""

from __future__ import annotations

import functools
import io
import re
import shutil
import tempfile
from pathlib import Path

import httpx
import yaml
from PIL import Image, ImageDraw, ImageFont

from gittok import private

SOURCE = "https://raw.githubusercontent.com/jacebrowning/memegen/main"
BUNDLED = Path(__file__).parent / "assets" / "memes"
# memegen's font aliases -> the free fonts (SIL OFL) GitTok downloads with the templates. A
# template that names another font (Impact is not free) gets the thick one.
FONT_FILES = {
    "thick": "TitilliumWeb-Black.ttf",
    "thin": "TitilliumWeb-SemiBold.ttf",
    "comic": "Kalam-Regular.ttf",
    "notosans": "NotoSans-Bold.ttf",
}
DEFAULT_FONT = "thick"
IMAGE_EXTS = ("png", "jpg", "gif")  # a gif is drawn from its first frame
DEFAULT_HEIGHT = 600  # memegen's default size: 600 px on the short side, the image's ratio
MIN_FONT_SIZE = 7
APPROX_MB = 20  # the download for the shipped templates


# ---------------------------------------------------------------- where templates live


def store(cfg) -> Path:
    return Path(cfg.settings.data_dir) / "memes"


def template_image(d: Path) -> Path | None:
    return next((d / f"default.{e}" for e in IMAGE_EXTS if (d / f"default.{e}").exists()), None)


def downloaded_in(root: Path) -> set[str]:
    base = root / "templates"
    if not base.is_dir():
        return set()
    return {d.name for d in base.iterdir() if (d / "config.yml").exists() and template_image(d)}


def downloaded(cfg) -> set[str]:
    return available_in(store(cfg))


def available_in(root: Path) -> set[str]:
    """Bundled templates plus the user's downloads, without copying into their home."""
    return downloaded_in(BUNDLED) | downloaded_in(root)


def template_dir(root: Path, tid: str) -> Path:
    base = root if tid in downloaded_in(root) else BUNDLED
    return base / "templates" / tid


def configured(cfg) -> list[str]:
    return list(cfg.meme_templates)


def missing(cfg) -> list[str]:
    have = downloaded(cfg)
    return [t for t in configured(cfg) if t not in have]


def usable_templates(cfg) -> dict:
    """The configured templates that can be drawn, bundled or downloaded."""
    have = downloaded(cfg)
    return {k: v for k, v in cfg.meme_templates.items() if k in have}


def hint(cfg) -> str | None:
    """One line for the SessionStart hook while configured templates are not downloaded."""
    gone = missing(cfg)
    if not gone:
        return None
    total = len(configured(cfg))
    return (
        f"GitTok: {len(gone)} of {total} meme templates are not downloaded, so the feed makes "
        f"no meme cards with them. Default templates are bundled; these are additional or "
        f"missing assets. Offer to download them (about {APPROX_MB} MB from the "
        "memegen GitHub repo, needs network; no card text is sent); if the user agrees, run "
        "`gittok memes --prefetch` with Bash (in a clone: `uv run gittok memes --prefetch`)."
    )


# ---------------------------------------------------------------- download


def _layout_ok(data: bytes) -> bool:
    try:
        layout = yaml.safe_load(data)
    except yaml.YAMLError:
        return False
    return (
        isinstance(layout, dict) and isinstance(layout.get("text"), list) and bool(layout["text"])
    )


def prefetch(cfg, ids, base: str | None = None, transport=None) -> dict:
    """Download the fonts and the given templates that are not here yet. Returns
    {"downloaded": [ids], "failed": {id: reason}, "bytes": n}."""
    base = (base or cfg.settings.render.meme_source or SOURCE).rstrip("/")
    root = store(cfg)
    private.make_dir(root / "fonts")
    private.make_dir(root / "templates")
    done: list[str] = []
    failed: dict[str, str] = {}
    size = 0
    with httpx.Client(timeout=60, transport=transport, follow_redirects=True) as client:

        def get(path: str) -> bytes | None:
            resp = client.get(f"{base}/{path}")
            return resp.content if resp.status_code == 200 else None

        for name in FONT_FILES.values():
            dest = root / "fonts" / name
            if dest.exists():
                continue
            data = get(f"fonts/{name}")
            if data is None:
                failed[f"font {name}"] = "not found"
                continue
            dest.write_bytes(data)
            size += len(data)
        have = available_in(root)
        for tid in ids:
            if tid in have:
                continue
            try:
                layout = get(f"templates/{tid}/config.yml")
                if layout is None:
                    failed[tid] = "no such template in memegen"
                    continue
                if not _layout_ok(layout):
                    failed[tid] = "its config.yml has no text boxes"
                    continue
                image = ext = None
                for e in IMAGE_EXTS:
                    if (image := get(f"templates/{tid}/default.{e}")) is not None:
                        ext = e
                        break
                if image is None:
                    failed[tid] = "no default image"
                    continue
            except httpx.HTTPError as e:
                failed[tid] = f"download failed: {e}"
                continue
            # Write to a temp folder and move it in, so a stopped download leaves no half
            # template that `downloaded` would count.
            tmp = Path(tempfile.mkdtemp(dir=root / "templates", prefix=f".{tid}-"))
            (tmp / "config.yml").write_bytes(layout)
            (tmp / f"default.{ext}").write_bytes(image)
            dest = root / "templates" / tid
            shutil.rmtree(dest, ignore_errors=True)
            tmp.rename(dest)
            size += len(layout) + len(image)
            done.append(tid)
    return {"downloaded": sorted(done), "failed": failed, "bytes": size}


# ---------------------------------------------------------------- drawing (after memegen)


@functools.lru_cache(maxsize=512)
def _font(path: str, size: int):
    try:
        # The basic layout, as memegen uses: raqm fails to measure text with line breaks.
        return ImageFont.truetype(path, size=size, layout_engine=ImageFont.Layout.BASIC)
    except OSError:  # not downloaded, or not a font: Pillow's own font still draws
        return ImageFont.load_default(size=size)


def _text_size(text: str, font) -> tuple[int, int]:
    box = ImageDraw.Draw(Image.new("RGB", (8, 8))).textbbox((0, 0), text, font)
    stroke = _stroke_width(font)
    return box[2] + stroke, box[3] + stroke


def _stroke_width(font) -> int:
    return min(3, max(1, int(font.size / 12)))


def _fit(path: str, text: str, box: tuple[int, int], max_size: int):
    """The largest font (at most max_size) that fits the text in the box."""
    max_w, max_h = box[0] - box[0] / 35, box[1] - box[1] / 10
    font = _font(path, MIN_FONT_SIZE)
    for size in range(max(MIN_FONT_SIZE, max_size), MIN_FONT_SIZE - 1, -1):
        font = _font(path, size)
        w, h = _text_size(text, font)
        x0, y0, _, _ = font.getbbox(text) if text else (0, 0, 0, 0)
        if w - x0 <= max_w and h - y0 <= max_h:
            break
    return font


def split_2(line: str) -> str:
    """Break a line in two at the space nearest its middle."""
    mid = len(line) // 2 - 1
    for off in range(0, len(line) // 4):
        for i in (mid - off, mid + off):
            if line[i] == " ":
                return line[:i].strip() + "\n" + line[i:].strip()
    return line


def split_3(line: str) -> str:
    """Break a line in three parts of about the same length, at spaces."""
    most = len(line) / 3
    rows = ["", "", ""]
    at = 0
    for word in line.split(" "):
        if len(rows[at]) + len(word) * 0.7 > most and at < 2:
            at += 1
        rows[at] += word + " "
    return "\n".join(rows).strip()


def wrap(path: str, line: str, box: tuple[int, int], max_size: int) -> str:
    """One, two or three rows: whichever lets the text be largest, as memegen chooses."""
    one, two, three = line, split_2(line), split_3(line)
    f1, f2, f3 = (_fit(path, t, box, max_size) for t in (one, two, three))
    if f1.size == f2.size and f2.size <= MIN_FONT_SIZE:
        return two
    if f1.size >= f2.size:
        return one
    if _text_size(three, f3)[0] >= box[0] * 0.60:
        return three
    if _text_size(two, f2)[0] >= box[0] * 0.60:
        return two
    return one


def _mock(text: str) -> str:
    out, upper = [], False
    for ch in text:
        if ch.isalpha():
            out.append(ch.upper() if upper else ch.lower())
            upper = not upper
        else:
            out.append(ch)
    return "".join(out)


def stylize(text: str, style: str, lines=None) -> str:
    """The case a layout asks for: upper, none (as written), default (sentence case), mock."""
    if style == "none":
        return text
    if style == "default":
        rows = [ln for ln in (lines or [text]) if ln.strip()]
        sentence = any(ln.endswith((".", "?", "!")) for ln in rows)
        if text.islower() and (all(ln.islower() for ln in rows) or sentence):
            text = text.capitalize()
        return re.sub(r"\bi\b", "I", text)
    if style == "mock":
        return _mock(text)
    method = getattr(str, style or "upper", None)
    return method(text) if callable(method) and style in {"upper", "lower", "title"} else text


def _stroke(color: str, width: int) -> tuple[int, str]:
    if color == "black":
        return 1, "#FFFFFF80"
    if color.startswith("#"):
        return 1, "#000000"
    return width, "black"


def _offset(text: str, font, box: tuple[int, int], align: str) -> tuple[float, float]:
    w, h = _text_size(text, font)
    stroke = _stroke_width(font)
    x, y, _, _ = font.getbbox(text) if text else (0, 0, 0, 0)
    x, y = x - stroke, y - stroke
    rows = text.count("\n") + 1
    adjust = 1.1 if rows >= 3 else 1 + (3 - rows) * 0.25
    if align != "left":
        x -= (box[0] - w) / 2
    y -= (box[1] - h / adjust) / 2
    if any(ch in text.split("\n")[-1] for ch in "gjpqy"):
        y += h // 20
    return x, y


def draw(template_dir: Path, fonts_dir: Path, lines: list[str]) -> bytes:
    """The meme as PNG bytes: the template image at memegen's default size, with each line
    in its text box."""
    layout = yaml.safe_load((template_dir / "config.yml").read_text())
    path = template_image(template_dir)
    if path is None:
        raise FileNotFoundError(f"{template_dir} has no default image")
    with Image.open(path) as src:
        src.seek(0)
        image = src.convert("RGBA")
    ratio = image.width / image.height
    if ratio >= 1:
        size = int(DEFAULT_HEIGHT * ratio), DEFAULT_HEIGHT
    else:
        size = DEFAULT_HEIGHT, int(DEFAULT_HEIGHT / ratio)
    image = image.resize(size, Image.Resampling.LANCZOS)
    width, height = image.size
    raw = [str(x) for x in lines]
    for i, box in enumerate(layout.get("text") or []):
        style = str(box.get("style") or "upper")
        line = raw[i] if i < len(raw) else ""
        if style not in {"none", "default", "mock"}:
            line = line.lower()
        angle = float(box.get("angle") or 0)
        area = (
            max(1, int(width * float(box.get("scale_x", 1.0)))),
            max(1, int(height * float(box.get("scale_y", 0.2)))),
        )
        font_file = FONT_FILES.get(str(box.get("font") or DEFAULT_FONT), FONT_FILES["thick"])
        font_path = fonts_dir / font_file
        if not font_path.is_file():
            font_path = BUNDLED / "fonts" / font_file
        font_path = str(font_path)
        biggest = int(height / (4 if angle else 9))
        text = stylize(wrap(font_path, line, area, biggest), style, raw)
        font = _fit(font_path, text, area, biggest)
        ox, oy = _offset(text, font, area, str(box.get("align") or "center"))
        color = str(box.get("color") or "white")
        stroke_width, stroke_fill = _stroke(color, _stroke_width(font))
        rows = text.count("\n") + 1
        layer = Image.new("RGBA", area)
        ImageDraw.Draw(layer).text(
            (-ox, -oy),
            text,
            fill=color,
            font=font,
            spacing=-oy / (rows * 2),
            align=str(box.get("align") or "center"),
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        turned = layer.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        x = int(width * float(box.get("anchor_x", 0))) - (turned.width - area[0]) // 2
        y = int(height * float(box.get("anchor_y", 0))) - (turned.height - area[1]) // 2
        image.paste(turned, (x, y), turned)
    out = io.BytesIO()
    image.convert("RGB").save(out, "PNG", optimize=True)
    return out.getvalue()
