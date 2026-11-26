"""PDF page rendering, bounding-box cropping, and ink-trimming utilities (adapted from cbd2)."""

from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

import pymupdf as fitz
import numpy as np
from PIL import Image


def render_pdf_pages(
    pdf_bytes: bytes | None = None,
    pdf_path: str | Path | None = None,
    *,
    dpi: int = 200,
    max_pages: int = 20,
) -> list[Image.Image]:
    """Render PDF pages into PIL RGB Images at the requested DPI."""
    if pdf_bytes is None:
        if pdf_path is None:
            raise ValueError("Either pdf_bytes or pdf_path must be provided.")
        pdf_bytes = Path(pdf_path).read_bytes()

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    images: list[Image.Image] = []
    try:
        for idx in range(min(len(doc), max_pages)):
            page = doc[idx]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            images.append(im)
    finally:
        doc.close()
    return images


def ink_mask(im: Image.Image) -> np.ndarray:
    """True where the image has actual ink (works for RGBA and RGB/white images)."""
    arr = np.asarray(im.convert("RGBA")).astype(np.int16)
    a = arr[:, :, 3]
    rgbmin = arr[:, :, :3].min(axis=2)
    if a.min() < 250:
        return (a > 8) & (rgbmin < 250)
    return rgbmin < 242


def trim_whitespace(im: Image.Image, pad: int = 10) -> Image.Image:
    """Crop excess white/transparent margin around ink and add uniform padding."""
    im = im.convert("RGB")
    m = ink_mask(im)
    ys, xs = np.where(m)
    if len(xs) == 0:
        return im
    cropped = im.crop((int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    out = Image.new("RGB", (cropped.width + 2 * pad, cropped.height + 2 * pad), (255, 255, 255))
    out.paste(cropped, (pad, pad))
    return out


def crop_box_2d(
    page_img: Image.Image,
    box_2d: list[Any] | tuple[Any, ...],
    *,
    margin_ratio: float = 0.008,
    pad: int = 10,
) -> Image.Image:
    """Crop a Gemini [ymin, xmin, ymax, xmax] (0..1000) box from a page image and trim."""
    if len(box_2d) == 1 and isinstance(box_2d[0], (list, tuple)):
        box_2d = box_2d[0]
    if len(box_2d) != 4:
        raise ValueError(f"Expected 4 coordinates [ymin, xmin, ymax, xmax], got {box_2d}")
    ymin, xmin, ymax, xmax = [float(v) for v in box_2d]
    w, h = page_img.size

    dy = margin_ratio * 1000.0
    dx = margin_ratio * 1000.0
    x0 = max(0, int(((xmin - dx) / 1000.0) * w))
    y0 = max(0, int(((ymin - dy) / 1000.0) * h))
    x1 = min(w, int(((xmax + dx) / 1000.0) * w))
    y1 = min(h, int(((ymax + dy) / 1000.0) * h))

    if x1 <= x0 or y1 <= y0:
        raise ValueError(f"Degenerate crop box {box_2d} on image {w}x{h}")

    cropped = page_img.crop((x0, y0, x1, y1))
    return trim_whitespace(cropped, pad=pad)


def image_to_png_bytes(im: Image.Image) -> bytes:
    """Encode a PIL Image as optimized PNG bytes."""
    buf = io.BytesIO()
    im.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def image_to_data_uri(im: Image.Image) -> str:
    """Encode a PIL Image as a compact data:image/png;base64,... URI."""
    b64 = base64.b64encode(image_to_png_bytes(im)).decode("ascii")
    return f"data:image/png;base64,{b64}"
