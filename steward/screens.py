"""Store screenshots whose app UI is provably the real UI.

1. Muse Image paints only the SCENE: a phone with a blank screen, in the app's palette. It never sees an
   instruction to draw the interface.
2. SAM 3.1 finds the phone screen in that scene ("phone screen" -> box in source pixels).
3. Our compositor pastes the ORIGINAL captured pixels into that box (one documented Lanczos resize) with
   rounded corners.
4. The fidelity guard re-extracts the UI region from the finished image and compares it with the resized
   capture: every pixel inside the screen mask must match exactly (max abs difference 0), or the asset is
   rejected. Captions are set by our code in a real font, never by the image model.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from . import config, media

FONT_CANDIDATES = [r"C:\Windows\Fonts\seguisb.ttf", r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]
SCENE_PROMPT = ("Product photograph for an app store listing: one modern smartphone standing upright and perfectly "
                "front-facing, not tilted, screen facing the camera, thin bezels, the screen completely black and "
                "empty. The phone fills about two thirds of the image height and sits in the lower part of the frame. "
                "{mood} Soft natural light, shallow depth of field, calm empty space above the phone for a headline. "
                "No text, no logos, no hands, no other devices.")
SCENE_PROMPT_LANDSCAPE = (
    "Product photograph for an app store listing: one modern smartphone turned to landscape orientation and "
    "standing upright on its long edge on a small clear stand, facing the camera straight on like a framed picture, "
    "level, not tilted and not lying flat, thin bezels, the screen completely black and empty and seen as a flat "
    "rectangle. The phone fills about two thirds of the image width and sits in the lower part of the frame. "
    "{mood} Soft natural light, shallow depth of field, calm empty space above the phone for a headline. "
    "No text, no logos, no hands, no other devices.")


def _ratio(aspect: float) -> str:
    from fractions import Fraction
    f = Fraction(aspect).limit_denominator(24)
    return f"{f.numerator}:{f.denominator}"


def scene_prompt(aspect: float, mood: str) -> tuple[str, str]:
    """(prompt, size) for a capture: the screen's shape is asked for, and landscape captures get a landscape frame."""
    shape = f"The screen's aspect ratio is {_ratio(aspect)} (width:height). "
    if aspect > 1.0:
        return SCENE_PROMPT_LANDSCAPE.format(mood=shape + mood), "1536x1024"
    return SCENE_PROMPT.format(mood=shape + mood), "1024x1536"


def _font(size: int):
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def _rounded_mask(w: int, h: int, r: int) -> Image.Image:
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    return m


SCREEN_INSET = 0.035      # share of the box's short side kept clear as bezel
PHONE_SHAPE = (1.6, 2.4)   # long side / short side of a real phone screen (16:10 up to 21:9 and a little margin)


def best_screen_box(seg: dict, img_w: int, img_h: int, capture_aspect: float) -> dict | None:
    """Pick the screen box that can hold the capture as a real phone would show it.

    A box qualifies when it is large, in the capture's orientation, phone-shaped, and at least as elongated as the
    capture, so the capture fits inside unchanged and any gap is the phone's own black screen (as a 16:9 game shows
    on a 20:9 phone). `aspect_error` is still reported. Among qualifying boxes the closest shape wins.
    """
    portrait = capture_aspect < 1.0
    cap_long = max(capture_aspect, 1 / capture_aspect)
    best, err = None, 9.0
    for b in seg["boxes"]:
        w, h = b["x2"] - b["x1"], b["y2"] - b["y1"]
        if w < img_w * 0.15 or h < img_h * 0.2 or (h > w) != portrait:
            continue
        long_ = max(w, h) / min(w, h)
        if not (PHONE_SHAPE[0] <= long_ <= PHONE_SHAPE[1]) or long_ < cap_long * 0.97:
            continue
        e = abs((w / h) - capture_aspect) / capture_aspect
        if e < err:
            best, err = b, e
    if best is None:
        return None
    return dict(best, aspect_error=err)


def fidelity(final: Image.Image, ui: Image.Image, box: tuple[int, int, int, int], mask: Image.Image) -> dict:
    x1, y1, x2, y2 = box
    out = np.asarray(final.convert("RGB").crop((x1, y1, x2, y2)), dtype=np.int16)
    ref = np.asarray(ui.convert("RGB"), dtype=np.int16)
    m = np.asarray(mask) == 255
    diff = np.abs(out - ref)[m]
    return {"pixels_checked": int(m.sum()), "max_abs_diff": int(diff.max()) if diff.size else -1,
            "mean_abs_diff": float(diff.mean()) if diff.size else -1.0,
            "ui_sha256": hashlib.sha256(ref[m].tobytes()).hexdigest()[:16],
            "out_sha256": hashlib.sha256(out[m].tobytes()).hexdigest()[:16]}


def compose(capture_path: str, headline: str, *, app_slug: str, mood: str, out_dir: Path | None = None,
            scene_png: bytes | None = None, con=None) -> dict:
    out_dir = out_dir or (config.DATA / "screens" / app_slug)
    out_dir.mkdir(parents=True, exist_ok=True)
    cap = Image.open(capture_path).convert("RGB")
    aspect = cap.width / cap.height
    if scene_png is None:
        prompt, size = scene_prompt(aspect, mood)
        scene_png = media.generate_image(prompt, size=size, purpose=f"screens-scene-{app_slug}", con=con)
    (out_dir / "scene.png").write_bytes(scene_png)
    scene = Image.open(io.BytesIO(scene_png)).convert("RGB")
    seg = media.segment(scene_png, "phone screen", purpose=f"screens-sam-{app_slug}", con=con)
    box = best_screen_box(seg, scene.width, scene.height, aspect)
    result = {"app": app_slug, "capture": Path(capture_path).name, "scene_size": scene.size,
              "sam_boxes": len(seg["boxes"]), "box": box}
    if box is None:
        result["status"] = "rejected: no front-facing screen with the capture's aspect ratio"
        (out_dir / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
        return result
    # fit the capture INSIDE the detected screen without changing its aspect ratio
    # SAM's "phone screen" box can include part of the bezel, so the capture is placed a little inside it
    inset = int(min(box["x2"] - box["x1"], box["y2"] - box["y1"]) * SCREEN_INSET)
    bx1, by1, bx2, by2 = box["x1"] + inset, box["y1"] + inset, box["x2"] - inset, box["y2"] - inset
    bw, bh = bx2 - bx1, by2 - by1
    scale = min(bw / cap.width, bh / cap.height)
    w, h = int(cap.width * scale), int(cap.height * scale)
    x1 = int(bx1 + (bw - w) / 2)
    y1 = int(by1 + (bh - h) / 2)
    ui = cap.resize((w, h), Image.LANCZOS)                      # the one documented resample
    mask = _rounded_mask(w, h, r=max(6, int(w * 0.07)))
    final = scene.copy()
    final.paste(ui, (x1, y1), mask)
    # caption in a real font on a soft top scrim (no outline effects)
    f = _font(max(28, final.width // 15))
    draw = ImageDraw.Draw(final)
    words = headline.split()
    if draw.textlength(headline, font=f) <= final.width * 0.84:
        lines = [headline]
    else:  # two balanced lines: choose the break that minimises the longer line
        best = min(range(1, len(words)), key=lambda k: max(draw.textlength(" ".join(words[:k]), font=f),
                                                            draw.textlength(" ".join(words[k:]), font=f)))
        lines = [" ".join(words[:best]), " ".join(words[best:])]
    top = int(final.height * 0.05)
    text_h = int(f.size * 1.18) * len(lines)
    scrim_h = min(y1 - 4, top + text_h + int(final.height * 0.06))
    if scrim_h > 0:
        grad = Image.new("L", (1, scrim_h))
        for yy in range(scrim_h):
            grad.putpixel((0, yy), int(150 * (1 - yy / scrim_h) ** 1.4))
        shade = Image.new("RGB", (final.width, scrim_h), (12, 14, 18))
        final.paste(shade, (0, 0), grad.resize((final.width, scrim_h)))
    draw = ImageDraw.Draw(final)
    y = top
    for ln in lines:
        tw = draw.textlength(ln, font=f)
        draw.text(((final.width - tw) / 2, y), ln, font=f, fill=(255, 255, 255))
        y += int(f.size * 1.18)
    fid = fidelity(final, ui, (x1, y1, x1 + w, y1 + h), mask)
    result.update({"placed": [x1, y1, x1 + w, y1 + h], "resize_scale": round(scale, 4), "fidelity": fid})
    if fid["max_abs_diff"] != 0 or y > y1:
        result["status"] = "rejected: UI pixels changed" if fid["max_abs_diff"] else "rejected: caption overlaps UI"
    else:
        result["status"] = "accepted"
        final.save(out_dir / "store_screenshot.png")
        side = Image.new("RGB", (final.width + int(cap.width * final.height / cap.height) + 40, final.height),
                         (245, 245, 240))
        side.paste(cap.resize((int(cap.width * final.height / cap.height), final.height), Image.LANCZOS), (0, 0))
        side.paste(final, (side.width - final.width, 0))
        side.save(out_dir / "side_by_side.png")
    (out_dir / "result.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result
