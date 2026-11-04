"""A barcode in a frame (#13, option A): zxing-cpp decodes EAN-13, EAN-8, UPC-A, UPC-E and
Code 128 from the JPEG the glasses sent, on the Mac, about 18 ms a frame. The wearer shows the
wrapper to the glasses, close, and the product names the next food; no phone in hand."""

from __future__ import annotations

import io

import zxingcpp
from PIL import Image

FORMATS = (
    zxingcpp.BarcodeFormat.EAN13
    | zxingcpp.BarcodeFormat.EAN8
    | zxingcpp.BarcodeFormat.UPCA
    | zxingcpp.BarcodeFormat.UPCE
    | zxingcpp.BarcodeFormat.Code128
)


def decode(jpeg: bytes) -> str | None:
    """The first product barcode in the frame, digits only, or None. Bytes that are not an image
    (tests, a lost frame) are None too."""
    try:
        im = Image.open(io.BytesIO(jpeg))
        im.load()
    except Exception:
        return None
    for candidate in _views(im):
        results = zxingcpp.read_barcodes(
            candidate, formats=FORMATS, try_rotate=True, try_downscale=True, try_invert=True
        )
        for r in results:
            text = "".join(ch for ch in (r.text or "") if ch.isdigit())
            if len(text) >= 8:
                return text
    return None


def _views(im: Image.Image) -> list[Image.Image]:
    """The frame as sent, then its middle doubled: the glasses' stream is 720 wide and
    compressed, so stripes shown at arm's length are one or two pixels each; doubling the
    centre gives the decoder something to work with."""
    w, h = im.size
    centre = im.crop((w // 6, h // 6, w - w // 6, h - h // 6))
    return [im, centre.resize((centre.width * 2, centre.height * 2), Image.LANCZOS)]


def encode_for_test(code: str, width: int = 400, height: int = 160) -> bytes:
    """An EAN-13 (or UPC-A) image as JPEG bytes, for the tests only."""
    fmt = zxingcpp.BarcodeFormat.EAN13 if len(code) == 13 else zxingcpp.BarcodeFormat.UPCA
    bitmap = zxingcpp.write_barcode(fmt, code, width=width, height=height)
    im = Image.fromarray(bitmap).convert("L")
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=92)
    return out.getvalue()
