"""Per-section rail-closed vs rail-open comparison images, for visual review.

    .venv/bin/python scripts/measure/shots.py            # every section
    .venv/bin/python scripts/measure/shots.py s1 s2      # just these

Writes one PNG per section into the work area, each stacking the two rail
states with the report column width and section height labelled. Computed
styles can be right while the page still looks wrong -- a specificity slip once
left a tile a quarter of its intended width with every font-size in the vector
still correct. Look at the pictures.

Python 3.9 compatible. Needs Pillow (a dev-only dependency, deliberately not in
requirements.txt, which is the air-gapped runtime bundle).
"""
from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                                                   # noqa: E402

SCALE = 2
VIEWPORT = 1560

EXPAND = """
<script>
window.addEventListener('load', function () {
  setTimeout(function () {
    /* Open every collapsible section, so a screenshot shows the whole card
       rather than a header. */
    [].slice.call(document.querySelectorAll('.sec.coll.closed'))
      .forEach(function (s) { s.classList.remove('closed'); });
    setTimeout(function () {
      var o = [].slice.call(document.querySelectorAll('.sec')).map(function (s) {
        var r = s.getBoundingClientRect();
        return {id: s.id,
                no: s.querySelector('.sec-no').textContent.trim(),
                title: s.querySelector('.sec-title').textContent.trim(),
                top: Math.round(r.top + window.scrollY),
                h: Math.round(r.height), w: Math.round(r.width)};
      });
      /* Section titles carry em dashes; btoa alone cannot encode them. */
      document.title = 'X<<' + btoa(unescape(encodeURIComponent(JSON.stringify(
        {secs: o, bodyH: Math.round(document.body.scrollHeight)})))) + '>>X';
    }, 400);
  }, 700);
});
</script>
"""


def font(size):
    from PIL import ImageFont
    for candidate in ("/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                      "/System/Library/Fonts/Helvetica.ttc",
                      "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        if os.path.exists(candidate):
            try:
                return ImageFont.truetype(candidate, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main() -> int:
    from PIL import Image, ImageDraw

    wanted = set(sys.argv[1:])
    outdir = paths.work("shots")
    html = paths.render()
    variants = paths.rail_variants(html)

    meta, full = {}, {}
    for state, doc in variants.items():
        page = doc.replace("</body>", EXPAND + "</body>")
        meta[state] = paths.probe(page, EXPAND, VIEWPORT, sentinel="X")
        png = paths.work("_full_%s.png" % state)
        paths.shoot(page, VIEWPORT, meta[state]["bodyH"] + 60, png, scale=SCALE)
        full[state] = Image.open(png)

    by_id = {}
    for state in variants:
        for section in meta[state]["secs"]:
            by_id.setdefault(section["id"], {})[state] = section

    label_font, sub_font = font(26), font(19)
    PAD, GAP, HDR = 24, 26, 46
    made = []

    for sid in sorted(by_id, key=lambda s: int(s[1:])):
        if wanted and sid not in wanted:
            continue
        pair = by_id[sid]
        crops, labels = [], []
        for state, caption in (("railoff", "RAIL CLOSED  —  default on load"),
                               ("railon", "RAIL OPEN  —  brief panel showing")):
            s = pair[state]
            image = full[state]
            crops.append(image.crop(
                (0, max(0, (s["top"] - 6) * SCALE),
                 image.width, min(image.height, (s["top"] + s["h"] + 6) * SCALE))))
            labels.append("%s   (report column %dpx, section %dpx tall)"
                          % (caption, s["w"], s["h"]))

        width = max(c.width for c in crops) + PAD * 2
        height = PAD + sum(HDR + c.height for c in crops) + GAP + PAD
        canvas = Image.new("RGB", (width, height), "#FFFFFF")
        draw = ImageDraw.Draw(canvas)
        title = "%s  %s" % (pair["railoff"]["no"], pair["railoff"]["title"])
        y = PAD
        for i, crop in enumerate(crops):
            if i == 0:
                draw.text((PAD, y + 4), title, font=label_font, fill="#141E2C")
            # Offset the caption past the title on the first row only, and far
            # enough that a long section title cannot collide with it.
            draw.text((PAD + (560 if i == 0 else 0), y + 8), labels[i],
                      font=sub_font, fill="#B02430" if i == 0 else "#00426A")
            y += HDR
            canvas.paste(crop, (PAD, y))
            draw.rectangle([PAD, y, PAD + crop.width - 1, y + crop.height - 1],
                           outline="#DCE2E9")
            y += crop.height + (GAP if i == 0 else 0)

        slug = re.sub(r"[^a-z0-9]+", "-", pair["railoff"]["title"].lower()).strip("-")
        name = os.path.join(outdir, "%s_%s.png" % (pair["railoff"]["no"], slug[:28]))
        canvas.save(name)
        made.append(name)
        print("  %-46s %dx%d" % (os.path.basename(name), canvas.width, canvas.height))

    print("wrote %d image(s) to %s" % (len(made), outdir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
