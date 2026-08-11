"""Brand mark for the top bar.

Looks for a logo in resources/ and inlines it as a base64 data URI, because the
page must stay self-contained -- the server is air-gapped and the downloadable
HTML has to render from a file:// URL with no companion assets.

With no logo present it falls back to an "FH" monogram on the Finance House
blue, so the bar never renders empty.
"""

from __future__ import annotations

import base64
import os

from . import tokens

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
RESOURCES = os.path.join(_ROOT, "resources")

# Checked in order, so a vector logo wins over a raster one at the same name.
CANDIDATES = (
    "logo.svg", "logo.png", "logo.webp", "logo.jpg", "logo.jpeg",
    "fh-logo.svg", "fh-logo.png", "financehouse.svg", "financehouse.png",
)

MIME = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}

_cache = {}


def logo_path():
    """First matching logo in resources/, or None.

    Falls back to scanning the folder so a differently-named file still gets
    picked up rather than silently ignored.
    """
    if not os.path.isdir(RESOURCES):
        return None
    for name in CANDIDATES:
        path = os.path.join(RESOURCES, name)
        if os.path.isfile(path):
            return path
    for name in sorted(os.listdir(RESOURCES)):
        if os.path.splitext(name)[1].lower() in MIME:
            return os.path.join(RESOURCES, name)
    return None


def logo_data_uri():
    """The logo as a data: URI, or None when there is no usable file."""
    path = logo_path()
    if not path:
        return None
    stamp = os.path.getmtime(path)
    if _cache.get("path") == path and _cache.get("stamp") == stamp:
        return _cache.get("uri")

    mime = MIME.get(os.path.splitext(path)[1].lower())
    if not mime:
        return None
    with open(path, "rb") as fh:
        encoded = base64.b64encode(fh.read()).decode("ascii")

    _cache.update({"path": path, "stamp": stamp,
                   "uri": "data:%s;base64,%s" % (mime, encoded)})
    return _cache["uri"]


def brand_mark() -> str:
    """The mark shown at the far left of the top bar."""
    uri = logo_data_uri()
    if uri:
        return ('<span class="brand-mark has-logo">'
                '<img src="%s" alt="Finance House"></span>' % uri)
    return '<span class="brand-mark">FH</span>'


# Square FH monogram on the brand blue, used for the browser tab when no logo
# has been supplied. Kept as SVG so it stays crisp at any tab density and needs
# no image library to produce.
_FALLBACK_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
    '<rect width="64" height="64" rx="14" fill="%s"/>'
    '<text x="32" y="43" font-family="Archivo,Helvetica,Arial,sans-serif" '
    'font-size="30" font-weight="800" fill="#fff" text-anchor="middle">FH</text>'
    '</svg>'
)


def favicon_data_uri(blue: str = None) -> str:
    """Browser-tab icon: the supplied logo, else the blue FH monogram.

    The monogram's colour comes from the design tokens rather than a literal, so
    the brand blue stays defined in exactly one place.

    A wide wordmark logo will letterbox in a square tab, but showing the real
    mark still beats showing a generic one.
    """
    if blue is None:
        blue = tokens.token("fh-blue")
    uri = logo_data_uri()
    if uri:
        return uri
    svg = _FALLBACK_ICON % blue
    return "data:image/svg+xml;base64,%s" % base64.b64encode(
        svg.encode("utf-8")).decode("ascii")


def favicon_bytes():
    """(bytes, mime) for the tab icon -- what Streamlit's page_icon needs.

    Returns None when there is no logo and the caller should use the SVG data
    URI instead.
    """
    path = logo_path()
    if not path:
        return None
    mime = MIME.get(os.path.splitext(path)[1].lower())
    if not mime:
        return None
    with open(path, "rb") as fh:
        return fh.read(), mime


def clear_cache() -> None:
    _cache.clear()
