"""Reading the rendered page: sections, pills, visible text, the data blob.

Everything here works on the HTML string render_page() returns -- the same
string the app shows and offers as a download -- so a check built on it tests
what the reader sees, not an intermediate model.

Sections are found by POSITION against render/sections.flat_sections(), the
same walk that numbers them, so a check asks for "returns" and keeps working
when the sections are renumbered.

Python 3.9 compatible.
"""

from __future__ import annotations

import html as _html
import json
import re
from html.parser import HTMLParser

from aecb.render import sections as _sections

SECTION_RE = re.compile(r'<section class="([^"]*)" id="(s\d+)">(.*?)</section>',
                        re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Elements that never take an end tag.
_VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input",
                   "link", "meta", "param", "source", "track", "wbr"))

# Attributes whose text a reader sees (hovers, labels).
_READ_ATTRS = ("data-info", "data-hint", "title", "aria-label", "alt")


def module_names():
    """Section module names in display order ('identity', 'score', ...)."""
    return [m.__name__.rsplit(".", 1)[-1] for m in _sections.flat_sections()]


def sections(raw):
    """{module name: the section's full <section> markup}.

    Returns (mapping, problems): problems lists structural surprises -- a
    missing, repeated or unexpected section id.
    """
    names = module_names()
    found, problems = {}, []
    seen = []
    for m in SECTION_RE.finditer(raw):
        sid = m.group(2)
        seen.append(sid)
        idx = int(sid[1:])
        if not 1 <= idx <= len(names):
            problems.append("unexpected section id %s" % sid)
            continue
        name = names[idx - 1]
        if name in found:
            problems.append("section %s (%s) rendered twice" % (sid, name))
            continue
        found[name] = m.group(0)
    for i, name in enumerate(names, start=1):
        if name not in found:
            problems.append("section s%d (%s) is missing from the page" % (i, name))
    expected = ["s%d" % i for i in range(1, len(names) + 1)]
    if seen and seen != expected[:len(seen)] and not problems:
        problems.append("sections out of order: %s" % ", ".join(seen))
    return found, problems


def balanced(markup, start, tag="div"):
    """The element that opens at `start`, through its matching end tag."""
    open_re = re.compile(r"<%s\b" % tag)
    close = "</%s>" % tag
    depth, i = 0, start
    while i < len(markup):
        nxt_open = open_re.search(markup, i)
        nxt_close = markup.find(close, i)
        if nxt_close < 0:
            return markup[start:]
        if nxt_open and nxt_open.start() < nxt_close:
            depth += 1
            i = nxt_open.end()
        else:
            depth -= 1
            i = nxt_close + len(close)
            if depth == 0:
                return markup[start:i]
    return markup[start:]


def aside(section_markup):
    """The section header's pill area (.sec-aside), or ''."""
    i = section_markup.find('<div class="sec-aside">')
    return balanced(section_markup, i) if i >= 0 else ""


def text(fragment):
    """Visible text of a fragment: tags dropped, entities decoded, spaces
    collapsed. Tags are dropped without inserting a space, matching how the
    browser runs inline elements together ('AED' + '391,020')."""
    return _WS_RE.sub(" ", _html.unescape(_TAG_RE.sub("", fragment or ""))).strip()


class _Reader(HTMLParser):
    """Collects visible text and reader-facing attribute text, each tagged
    with the section it sits in, and checks tag nesting on the way."""

    def __init__(self):
        HTMLParser.__init__(self, convert_charrefs=True)
        self.skip = 0
        self.section = "page"
        self.texts = []          # (section, text)
        self.attrs = []          # (section, attr, value)
        self.ids = {}            # id -> count
        self.stack = []          # (tag, line, col)
        self.nesting = []        # problems

    def handle_starttag(self, tag, attrs):
        self._open(tag, attrs)
        if tag not in _VOID:
            self.stack.append((tag, self.getpos()))

    def handle_startendtag(self, tag, attrs):
        # Self-closed (<circle .../>): attributes count, nothing to balance.
        self._open(tag, attrs)

    def _open(self, tag, attrs):
        if tag in ("style", "script"):
            self.skip += 1
        for key, value in attrs:
            if key == "id" and value:
                self.ids[value] = self.ids.get(value, 0) + 1
                if tag == "section":
                    self.section = value
            if key in _READ_ATTRS and value and not self.skip:
                self.attrs.append((self.section, key, value))

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self.skip = max(0, self.skip - 1)
        if tag in _VOID:
            return
        if self.stack and self.stack[-1][0] == tag:
            self.stack.pop()
        elif any(t == tag for t, _pos in self.stack):
            # Close the elements left open inside it -- each one is a problem.
            while self.stack and self.stack[-1][0] != tag:
                t, pos = self.stack.pop()
                self._problem("<%s> opened at line %d col %d is never closed "
                              "before </%s>" % (t, pos[0], pos[1], tag))
            self.stack.pop()
        else:
            line, col = self.getpos()
            self._problem("stray </%s> at line %d col %d" % (tag, line, col))
        if tag == "section":
            self.section = "page"

    def handle_data(self, data):
        if not self.skip and data.strip():
            self.texts.append((self.section, data.strip()))

    def _problem(self, message):
        if len(self.nesting) < 5:
            self.nesting.append(message)

    def close(self):
        HTMLParser.close(self)
        for t, pos in self.stack:
            if t not in ("html", "body", "head"):
                self._problem("<%s> opened at line %d col %d is never closed"
                              % (t, pos[0], pos[1]))


def read(raw):
    """Parse the page once. Returns the _Reader with texts, attrs, ids and
    nesting problems filled in."""
    reader = _Reader()
    reader.feed(raw)
    reader.close()
    return reader


def section_names_by_id():
    return dict(("s%d" % i, n) for i, n in enumerate(module_names(), start=1))


class BlobError(ValueError):
    pass


def _reject_constant(name):
    raise BlobError("the blob carries %s, which is not valid JSON" % name)


def blob(raw):
    """The window.__AECB object exactly as shipped. Raises BlobError."""
    marker = "window.__AECB = "
    i = raw.find(marker)
    if i < 0:
        raise BlobError("no window.__AECB blob in the page")
    decoder = json.JSONDecoder(parse_constant=_reject_constant)
    try:
        obj, _end = decoder.raw_decode(raw, i + len(marker))
    except BlobError:
        raise
    except ValueError as exc:
        raise BlobError("the blob is not valid JSON: %s" % exc)
    return obj


def replace_blob(raw, data):
    """The page with its blob swapped for `data` (self-test use)."""
    marker = "window.__AECB = "
    start = raw.find(marker) + len(marker)
    _obj, end = json.JSONDecoder().raw_decode(raw, start)
    return raw[:start] + json.dumps(data, ensure_ascii=False) + raw[end:]


def heatmap_rows(data):
    """[(block key, category, row)] from the blob's heatmap."""
    out = []
    for block in ((data or {}).get("heatmap") or {}).get("blocks") or []:
        for group in block.get("groups") or []:
            for row in group.get("rows") or []:
                out.append((block.get("key"), group.get("cat"), row))
    return out
