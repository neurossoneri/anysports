# Fonts

These files are the web fonts of the site. They are served from the site itself (`assets/fonts/` after the build),
so a visitor's browser does not connect to Google or any other font provider. Nothing is downloaded at build time.

| Family | Use | Licence |
|---|---|---|
| Inter | text and small interface text (a neo-grotesque in the Helvetica / "Swiss style" tradition) | SIL OFL 1.1, (c) The Inter Project Authors |
| Source Serif 4 | headings and calm reading | SIL OFL 1.1, (c) Adobe |
| Caveat | handwritten quotations | SIL OFL 1.1, (c) The Caveat Project Authors |

Licence text: https://openfontlicense.org (SIL Open Font License, Version 1.1). The files are variable WOFF2 fonts;
`fonts.css` holds the `@font-face` rules and `unicode-range`, so the browser loads only the subsets a page needs.

To replace a font, put the new `.woff2` files here, update `fonts.css`, and (for the preload hints) the names in
`FONT_PRELOAD` in `scripts/build.py`. The tests check that every file listed in `fonts.css` exists.
