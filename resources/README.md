# resources/

Drop the Finance House logo in here and the top bar picks it up automatically —
no code change, no rebuild.

## Naming

Name the file `logo.svg` (preferred) or `logo.png`. These are checked in order:

```
logo.svg   logo.png   logo.webp   logo.jpg   logo.jpeg
fh-logo.svg   fh-logo.png   financehouse.svg   financehouse.png
```

If none of those match, the first `.svg` / `.png` / `.webp` / `.jpg` / `.gif`
in this folder is used, so an oddly named file still works.

With no logo present the bar falls back to an **FH** monogram on the Finance
House blue.

## What happens to it

The file is **inlined as a base64 data URI** at render time. Nothing is fetched
over the network — the target server is air-gapped, and the downloadable
standalone HTML has to render from a `file://` URL with no companion assets.

That means the logo's size counts toward the page weight, so keep it lean:
an SVG under ~20 KB, or a PNG no wider than about 400 px.

## Sizing

The mark renders at **28 px tall**, width automatic, capped at 170 px. A
horizontal lockup (wordmark beside the symbol) works well at that height; a
tall stacked logo will be scaled down and read small.

Transparent background preferred — the mark sits on white with no tile behind
it once a logo is supplied.

## Brand colour

The blue used for the fallback monogram and the *AI Analysis* button is the
Finance House corporate blue:

```
--fh-blue    #00426A
```

The wash, hairline and pressed-state shades are derived from it.

All five blue tokens live in [`aecb/render/tokens.py`](../aecb/render/tokens.py)
under *Finance House brand*. Correcting the brand is a one-file edit there.
