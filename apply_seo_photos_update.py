#!/usr/bin/env python3
"""apply_seo_photos_update.py: правки по SEO-аудиту (то, что имеет смысл для этого репозитория) и вид фотографий.

Запуск из корня репозитория:   python3 apply_seo_photos_update.py

Что делает (подробности в README.md, раздел «SEO-аудит и вид фото»):
  * content/site.json: «Адрес сайта» (public_url) = https://sportintuitive.com. От него зависят canonical, og:url, JSON-LD, sitemap.
  * scripts/build.py: robots-мета для открытого сайта, JPEG-обложка 1200x630 для превью ссылок, og:* и twitter:*, @id в JSON-LD,
    width/height у всех фото, preload главного фото, referrer, Content-Security-Policy (по хэшам скриптов), llms.txt.
  * templates/index.html: фото в блоках с мягкими углами и лёгкой тенью (как у цитат и кнопки «Send»).
  * scripts/test_build.py: тест на всё это; правило «фото остаются квадратными» заменено новым.
  * README.md, docs/*.md: что сделано и что намеренно нет.

publish_ready НЕ включается: это выключатель запуска в панели («Готов к индексации»), его включают по списку docs/CONTENT-REVIEW.md.

Безопасность запуска:
  1. сначала все правки проверяются в памяти; если хоть одна не нашла своё место, ничего не записывается;
  2. повторный запуск ничего не меняет (маркер seo-photos-v1);
  3. оригиналы копируются в .backup-seo-photos/ (папка в .gitignore);
  4. в конце запускаются scripts/build.py и scripts/test_build.py, результат печатается как есть.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
MARK = 'seo-photos-v1'
BACKUP = ROOT / '.backup-seo-photos'

# ----------------------------------------------------------------------------------------------------------
# Новый код для scripts/build.py
# ----------------------------------------------------------------------------------------------------------
BUILD_HELPERS = r'''# seo-photos-v1 ------------------------------------------------------------------------------------------
ROBOTS_INDEX = 'index,follow,max-image-preview:large,max-snippet:-1'   # robots meta of an indexable site
OG_SIZE = (1200, 630)
OG_FILE = 'assets/og-cover.jpg'
SCRIPT_TAG = re.compile(r'<script(\s[^>]*)?>(.*?)</script>', re.S)


def image_size(path):
    """(width, height) of a photograph of the built site as a browser shows it (EXIF turn applied), or None."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        with Image.open(OUT / path) as opened:
            width, height = opened.size
            if opened.getexif().get(274, 1) in (5, 6, 7, 8):   # EXIF orientation: the browser shows the photograph turned
                width, height = height, width
        return (width, height) if width > 0 and height > 0 else None
    except Exception:
        return None


def size_attrs(path):
    """width/height of the original file: the browser reserves the space before the photograph loads (no layout jump). CSS still sets the real size."""
    size = image_size(path)
    return f' width="{size[0]}" height="{size[1]}"' if size else ''


def make_og_cover(site):
    """A 1200x630 JPEG of the first-screen photograph for link previews (social networks do not take WebP). Returns its path in the site, or ''.
    A vertical photograph is shown whole, on a blurred and darkened copy of itself, so the face is never cut off; a landscape one is cut to shape."""
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return ''
    try:
        rel = photo_path(site.get('portrait'))
        source = OUT / rel if rel else None
        if not source or not source.is_file():
            return ''
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened).convert('RGB')
        width, height = OG_SIZE
        if image.width / image.height >= 1.6:
            x, y = (float(v) / 100 for v in (clean_crop(site.get('portrait_crop')) or '50,50,1').split(',')[:2])
            scale = max(width / image.width, height / image.height)
            scaled = image.resize((max(width, round(image.width * scale)), max(height, round(image.height * scale))), Image.LANCZOS)
            left, top = round((scaled.width - width) * x), round((scaled.height - height) * y)
            canvas = scaled.crop((left, top, left + width, top + height))
        else:
            canvas = ImageEnhance.Brightness(ImageOps.fit(image, OG_SIZE, Image.LANCZOS).filter(ImageFilter.GaussianBlur(26))).enhance(.55)
            scale = min(width / image.width, height / image.height)
            photo = image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))), Image.LANCZOS)
            canvas.paste(photo, ((width - photo.width) // 2, (height - photo.height) // 2))
        target = OUT / OG_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(target, 'JPEG', quality=86, optimize=True, progressive=True)
        return OG_FILE
    except Exception as exc:   # the preview image must never break the build
        print(f'NOTE: no preview image for link sharing ({exc.__class__.__name__}); the first-screen photograph is named instead.', file=sys.stderr)
        return ''


def csp_meta(page):
    """Content-Security-Policy as a <meta> tag (GitHub Pages cannot send headers). Only scripts are restricted: the page's own file and its inline
    scripts, each named by its hash, so a script injected by anything else does not run. The hashes are computed from the finished page."""
    hashes = []
    for attrs, body in SCRIPT_TAG.findall(page):
        if re.search(r'\bsrc\s*=', attrs or ''):
            continue
        kind = re.search(r'\btype\s*=\s*["\']?([^"\'\s>]+)', attrs or '')
        if kind and kind.group(1).lower() not in ('text/javascript', 'module'):
            continue   # data blocks (JSON-LD) are never executed
        token = "'sha256-" + base64.b64encode(hashlib.sha256(body.encode('utf-8')).digest()).decode('ascii') + "'"
        if token not in hashes:
            hashes.append(token)
    policy = "script-src 'self' " + ' '.join(hashes) + "; object-src 'none'; base-uri 'self'"
    return f'<meta http-equiv="Content-Security-Policy" content="{policy}">'


def add_csp():
    """The policy on every public page. The dashboard (admin/) is left alone: it has its own scripts and talks to GitHub."""
    count = 0
    for page in sorted(OUT.rglob('*.html')):
        if page.relative_to(OUT).parts[0] == 'admin':
            continue
        text = page.read_text(encoding='utf-8')
        marker = '<meta charset="utf-8">'
        if 'Content-Security-Policy' in text:
            continue
        if marker not in text:
            raise RuntimeError(f'{page.relative_to(OUT)}: no charset tag to put the security policy after')
        page.write_text(text.replace(marker, marker + csp_meta(text), 1), encoding='utf-8')
        count += 1
    return count


def llms_txt(site, public_url, has_privacy, has_posts):
    """llms.txt: a short plain-text map of the site for AI search. Built from the site's own settings and section titles, nothing is invented."""
    copy = collect_values(site)['en']
    clean = lambda text: re.sub(r'[\[\]]', '', re.sub(r'\s+', ' ', rich_plain(text))).strip()
    name, role = str(site.get('name_en') or '').strip(), str(site.get('role_en') or '').strip()
    out = [f'# {brand_name(site)}', '']
    if clean(copy.get('meta.description', '')):
        out += [f'> {clean(copy["meta.description"])}', '']
    if name:
        out += ['## About', '', name + (f', {role}.' if role else '.'), '']
    pages = [f'- [Home]({public_url})']
    for section in load_sections():
        if section['type'] == 'text' and section_has_content(section) and section['title'].strip():
            pages.append(f'- [{clean(section["title"])}]({public_url}#{section["id"]})')
        elif section['type'] == 'contact' and flag_on(site, 'contact_form_enabled'):
            pages.append(f'- [{clean(copy.get("contact.title", "")) or "Contact"}]({public_url}#contact)')
        elif section['type'] == 'qa' and load_qa():
            pages.append(f'- [{clean(copy.get("qa.title", "")) or "Q&A"}]({public_url}#qa)')
    out += ['## Home page', ''] + pages + ['']
    other = ([f'- [Notes]({public_url}en/articles/)'] if has_posts else []) + ([f'- [Privacy notice]({public_url}privacy/)'] if has_privacy else [])
    if other:
        out += ['## Other pages', ''] + other + ['']
    out += ['## Notes', '', '- Site language: English.', '']
    return '\n'.join(out)


def copy_media():'''

BUILD_SEO_PORTRAIT_OLD = '''    portrait = photo_path(site.get('portrait'))
    if portrait:
        out += f'  <meta property="og:image" content="{esc(public_url + portrait)}">\\n'
'''
BUILD_SEO_PORTRAIT_NEW = '''    portrait = photo_path(site.get('portrait'))
    copy = copy or {}
    image = public_url + cover if cover else (public_url + portrait if portrait else '')
    out += '  <meta property="og:locale" content="en_US">\\n'
    if image:
        out += f'  <meta property="og:image" content="{esc(image)}">\\n'
        if cover:
            out += ('  <meta property="og:image:type" content="image/jpeg">\\n'
                    f'  <meta property="og:image:width" content="{OG_SIZE[0]}">\\n  <meta property="og:image:height" content="{OG_SIZE[1]}">\\n')
        if copy.get('hero.alt'):
            out += f'  <meta property="og:image:alt" content="{esc(copy["hero.alt"])}">\\n'
    out += f'  <meta name="twitter:card" content="{"summary_large_image" if cover else "summary"}">\\n'
    if copy.get('meta.fullTitle'):
        out += f'  <meta name="twitter:title" content="{esc(copy["meta.fullTitle"])}">\\n'
    if copy.get('meta.description'):
        out += f'  <meta name="twitter:description" content="{esc(copy["meta.description"])}">\\n'
    if image:
        out += f'  <meta name="twitter:image" content="{esc(image)}">\\n'
'''

BUILD_HERO_OLD = '''            variants = make_variants(OUT, path)
            if variants:
                attributes += ' srcset="' + ', '.join(f'{esc(name)} {size}w' for name, size in variants) + '" sizes="50vw"'
'''
BUILD_HERO_NEW = '''            variants = make_variants(OUT, path)
            if variants:
                attributes += ' srcset="' + ', '.join(f'{esc(name)} {size}w' for name, size in variants) + '" sizes="50vw"'
            # seo-photos-v1: the browser starts loading the first-screen photograph at once (the same copies as the <img> itself)
            preload = f'<link rel="preload" as="image" href="{esc(path)}"'
            if variants:
                preload += ' imagesrcset="' + ', '.join(f'{esc(name)} {size}w' for name, size in variants) + '" imagesizes="50vw"'
            template = replace_required(template, "<script>document.documentElement.classList.add('js')", preload + ' fetchpriority="high">\\n  <script>document.documentElement.classList.add(\\'js\\')', 'hero preload')
'''

BUILD_MAIN_OLD = '''    (OUT / 'robots.txt').write_text(robots, encoding='utf-8')
'''
BUILD_MAIN_NEW = '''    (OUT / 'robots.txt').write_text(robots, encoding='utf-8')
    if public_url and ready:
        (OUT / 'llms.txt').write_text(llms_txt(site, public_url, has_privacy, bool(posts)), encoding='utf-8')
    add_csp()   # seo-photos-v1: last, because the hashes are computed from the finished pages
'''

BUILD_EDITS = [
    ('import datetime as dt\nimport html\n', 'import base64\nimport datetime as dt\nimport hashlib\nimport html\n', 'imports'),
    ('def copy_media():', BUILD_HELPERS, 'helpers before copy_media'),
    ('def seo_head(site, public_url):', 'def seo_head(site, public_url, copy=None, cover=\'\'):', 'seo_head signature'),
    (BUILD_SEO_PORTRAIT_OLD, BUILD_SEO_PORTRAIT_NEW, 'og:image, twitter'),
    ("person = {'@context': 'https://schema.org', '@type': 'Person', 'name': name,",
     "person = {'@context': 'https://schema.org', '@type': 'Person', '@id': public_url + '#person', 'name': name,", 'JSON-LD @id'),
    ('''            attributes += f' src="{esc(path)}"'
            if path not in self.cache:''', '''            attributes += f' src="{esc(path)}"' + size_attrs(path)
            if path not in self.cache:''', 'width/height of block photos'),
    ('''            attributes += f' src="{esc(path)}"'
            variants = make_variants(OUT, path)''', '''            attributes += f' src="{esc(path)}"' + size_attrs(path)
            variants = make_variants(OUT, path)''', 'width/height of the hero photo'),
    (BUILD_HERO_OLD, BUILD_HERO_NEW, 'hero preload'),
    ("""('<meta name="robots" content="index,follow">' if ready else""", """('<meta name="robots" content="' + ROBOTS_INDEX + '">' if ready else""", 'robots meta of the home page'),
    ("""+ '\\n  <meta name="color-scheme"', 'robots')""", """+ '\\n  <meta name="referrer" content="strict-origin-when-cross-origin">\\n  <meta name="color-scheme"', 'robots')""", 'referrer of the home page'),
    ('''    if public_url:
        template = replace_required(template, '</head>', seo_head(site, public_url) + '</head>', 'head')''',
     '''    if public_url:
        cover = make_og_cover(site)
        template = replace_required(template, '</head>', seo_head(site, public_url, copy, cover) + '</head>', 'head')''', 'seo head call'),
    ("""{'index,follow' if ready else 'noindex,nofollow'}""", """{ROBOTS_INDEX if ready else 'noindex,nofollow'}""", 'robots meta of inner pages'),
    ('''<meta name="color-scheme" content="light dark"><meta name="theme-color"''',
     '''<meta name="referrer" content="strict-origin-when-cross-origin"><meta name="color-scheme" content="light dark"><meta name="theme-color"''', 'referrer of inner pages'),
    ("""cover = (f'<img src="{esc(post["cover"])}" alt="" loading="lazy" decoding="async">'""",
     """cover = (f'<img src="{esc(post["cover"])}"{size_attrs(post["cover"])} alt="" loading="lazy" decoding="async">'""", 'width/height of note covers'),
    ("""<img class="post-hero-image" src="{esc(image)}" alt="" loading="eager">""",
     """<img class="post-hero-image" src="{esc(image)}"{size_attrs(image)} alt="" loading="eager">""", 'width/height of the article image'),
    (BUILD_MAIN_OLD, BUILD_MAIN_NEW, 'llms.txt and security policy in main'),
]

# ----------------------------------------------------------------------------------------------------------
# templates/index.html
# ----------------------------------------------------------------------------------------------------------
TEMPLATE_CSS = '''    /* seo-photos-v1. Фото в блоках: мягкие углы и лёгкая тень, как у панелей цитат и кнопки «Send». Первый экран и широкая полоса растворяются в фон и остаются без рамки. */
    :root { --photo-float:0 24px 44px -24px rgba(6,18,30,.62),0 8px 18px -10px rgba(6,18,30,.32); }
    .band-deep, .band-teal { --photo-float:0 28px 50px -30px rgba(0,0,0,.85),0 8px 18px -10px rgba(0,0,0,.5); }
    .b-photos .photo { border-radius:var(--r-panel); box-shadow:var(--photo-float); }
    #lightbox img { border-radius:var(--r-panel); }
'''
TEMPLATE_EDITS = [
    ('''    @media (prefers-reduced-motion:reduce) {
      html { scroll-behavior:auto; }''', TEMPLATE_CSS + '''    @media (prefers-reduced-motion:reduce) {
      html { scroll-behavior:auto; }''', 'photo style block'),
    ('''.b-photos[data-comp="calm-pair"] .photo:nth-child(2) { grid-column:6 / -1; margin-top:-9%; box-shadow:0 0 0 clamp(4px,1.2vw,8px) var(--c-bg,transparent); z-index:1; }''',
     '''.b-photos[data-comp="calm-pair"] .photo:nth-child(2) { grid-column:6 / -1; margin-top:-9%; box-shadow:0 0 0 clamp(4px,1.2vw,8px) var(--c-bg,transparent),var(--photo-float); z-index:1; }''', 'ring + shadow, calm pair'),
    ('''.b-photos[data-comp="lead-small"] .photo:nth-child(2) { grid-column:6 / -1; margin-top:-22%; box-shadow:0 0 0 clamp(4px,1.2vw,8px) var(--c-bg,transparent); z-index:1; }''',
     '''.b-photos[data-comp="lead-small"] .photo:nth-child(2) { grid-column:6 / -1; margin-top:-22%; box-shadow:0 0 0 clamp(4px,1.2vw,8px) var(--c-bg,transparent),var(--photo-float); z-index:1; }''', 'ring + shadow, lead and small'),
    ('''.rail .b-photos[data-comp] .photo:nth-child(n) { grid-column:auto; margin-top:0; box-shadow:none; }''',
     '''.rail .b-photos[data-comp] .photo:nth-child(n) { grid-column:auto; margin-top:0; box-shadow:var(--photo-float); }''', 'side column on phones keeps the shadow'),
]

# ----------------------------------------------------------------------------------------------------------
# scripts/test_build.py
# ----------------------------------------------------------------------------------------------------------
TEST_FUNCTION = r'''def check_seo_photos(builder):
    """seo-photos-v1: address of the site, robots meta, preview image, twitter card, JSON-LD, photo sizes, preload, security policy, llms.txt, rounded photos.
    Uses its own fixtures only: nothing here depends on the texts or photos the owner edits."""
    import base64
    import hashlib
    if not importlib.util.find_spec('PIL'):
        return

    def live(work, site):
        from PIL import Image
        Image.new('RGB', (2400, 3000), (40, 90, 140)).save(work / 'media/big.jpg', quality=85)
        Image.new('RGB', (900, 600), (140, 90, 40)).save(work / 'media/wide.jpg', quality=85)
        site.update({'public_url': 'https://example.com', 'publish_ready': True, 'name_en': 'Test Person', 'portrait': 'media/big.jpg', 'story_photo_2': 'media/wide.jpg',
                     'quote_photo': '', 'eyes_photo': '', 'story_photo_1': '', 'story_photo_3': '', 'story_photo_4': '', 'email': 'hello@example.com'})
        (work / 'content/sections.json').write_text(json.dumps(sample_sections(builder), ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, live, posts=True)
    with temporary:
        from PIL import Image
        site_dir = work / '_site'
        home = (site_dir / 'index.html').read_text(encoding='utf-8')
        assert '<meta name="robots" content="index,follow,max-image-preview:large,max-snippet:-1">' in home and 'noindex' not in home
        assert '<link rel="canonical" href="https://example.com/">' in home and 'github.io' not in home, 'every address of the page is the owner\'s own'
        assert '<meta property="og:image" content="https://example.com/assets/og-cover.jpg">' in home
        assert 'og:image:width" content="1200"' in home and 'og:image:height" content="630"' in home and 'og:image:type" content="image/jpeg"' in home
        assert '<meta name="twitter:card" content="summary_large_image">' in home and 'twitter:image" content="https://example.com/assets/og-cover.jpg"' in home
        for pair in ('title', 'description'):
            assert re.search(r'og:' + pair + r'" content="([^"]*)"', home).group(1) == re.search(r'twitter:' + pair + r'" content="([^"]*)"', home).group(1), f'twitter:{pair} equals og:{pair}'
        with Image.open(site_dir / 'assets/og-cover.jpg') as cover:
            assert cover.format == 'JPEG' and cover.size == (1200, 630), 'the preview image is a JPEG of 1200x630'
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', home, re.S).group(1))
        assert ld['@id'] == 'https://example.com/#person' and ld['url'] == 'https://example.com/' and ld['image'].startswith('https://example.com/media/')
        assert 'name="referrer" content="strict-origin-when-cross-origin"' in home
        # width and height of every photograph, taken from the file (EXIF turn included)
        assert re.search(r'<img data-slot="1" src="media/big\.jpg" width="2400" height="3000" srcset=', home), 'the hero photograph carries its real size'
        assert re.search(r'src="media/wide\.jpg" width="900" height="600"', home), 'block photographs carry their real size'
        for tag in re.findall(r'<img [^>]*\bsrc="media/[^"]+"[^>]*>', home):
            if 'test-cover' in tag:
                continue   # the fixture's note cover is a file that cannot be read
            assert ' width="' in tag and ' height="' in tag, f'photograph without width/height: {tag[:80]}'
        preload = re.search(r'<link rel="preload" as="image"[^>]*>', home).group(0)
        assert 'href="media/big.jpg"' in preload and 'imagesrcset="media/opt/media-big-jpg-640.webp 640w' in preload and 'fetchpriority="high"' in preload
        assert home.index(preload) < home.index('<style>'), 'the preload comes before the style rules'
        # the security policy names every inline script by its hash; the dashboard is not touched
        for page in ('index.html', 'privacy/index.html', 'en/articles/index.html', 'en/articles/sample/index.html'):
            text = (site_dir / page).read_text(encoding='utf-8')
            policy = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', text)
            assert policy and text.index('charset') < policy.start() < text.index('<script'), f'{page}: policy comes first among the scripts'
            assert "'unsafe-inline'" not in policy.group(1) and "'unsafe-eval'" not in policy.group(1) and "script-src 'self'" in policy.group(1)
            scripts = [(a, b) for a, b in re.findall(r'<script(\s[^>]*)?>(.*?)</script>', text, re.S) if not (a or '').strip().startswith(('src', 'type="application/ld+json"'))]
            assert scripts, f'{page}: inline scripts expected'
            for _, body in scripts:
                digest = base64.b64encode(hashlib.sha256(body.encode('utf-8')).digest()).decode('ascii')
                assert f"'sha256-{digest}'" in policy.group(1), f'{page}: an inline script is not covered by the policy'
        assert 'Content-Security-Policy' not in (site_dir / 'admin/index.html').read_text(encoding='utf-8'), 'the dashboard keeps its own rules'
        llms = (site_dir / 'llms.txt').read_text(encoding='utf-8')
        assert llms.startswith('# Sport Intuitive') and 'https://example.com/#contact' in llms and 'https://example.com/privacy/' in llms and 'github.io' not in llms
        robots = (site_dir / 'robots.txt').read_text(encoding='utf-8')
        assert 'Allow: /' in robots and 'Disallow: /admin/' in robots and 'Sitemap: https://example.com/sitemap.xml' in robots
        assert 'https://example.com/' in (site_dir / 'sitemap.xml').read_text(encoding='utf-8')

    # a landscape portrait is cut to shape, a missing or unreadable one gives no preview image (and no promise of one)
    def landscape(work, site):
        from PIL import Image
        Image.new('RGB', (3000, 1500), (40, 90, 140)).save(work / 'media/land.jpg', quality=85)
        site.update({'public_url': 'https://example.com', 'publish_ready': False, 'portrait': 'media/land.jpg', 'quote_photo': '', 'eyes_photo': '', 'story_photo_1': '',
                     'story_photo_2': '', 'story_photo_3': '', 'story_photo_4': ''})
        (work / 'content/sections.json').write_text(json.dumps(sample_sections(builder), ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, landscape, posts=False)
    with temporary:
        from PIL import Image
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        with Image.open(work / '_site/assets/og-cover.jpg') as cover:
            assert cover.size == (1200, 630)
        assert 'noindex,nofollow' in home and not (work / '_site/llms.txt').exists() and not (work / '_site/sitemap.xml').exists(), 'before launch: closed, no llms.txt, no sitemap'
        assert 'og:image" content="https://example.com/assets/og-cover.jpg"' in home, 'the addresses are right even before launch'

    def broken(work, site):
        site.update({'public_url': 'https://example.com', 'publish_ready': True, 'portrait': 'media/test-cover.webp', 'quote_photo': '', 'eyes_photo': '', 'story_photo_1': '',
                     'story_photo_2': '', 'story_photo_3': '', 'story_photo_4': ''})
        (work / 'content/sections.json').write_text(json.dumps(sample_sections(builder), ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, broken, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        assert not (work / '_site/assets/og-cover.jpg').exists() and 'og:image:width' not in home and 'summary_large_image' not in home
        assert 'og:image" content="https://example.com/media/test-cover.webp"' in home and 'name="twitter:card" content="summary"' in home, 'without a preview image the photograph itself is named'
        assert ' width=' not in re.search(r'<img data-slot="1"[^>]*>', home).group(0), 'a file that cannot be read gets no invented size'

    # photographs: soft corners and a light shadow (like the quotation panels), the first screen and the wide strip stay without a frame
    css = (ROOT / '_site/assets/site.css').read_text(encoding='utf-8')
    assert re.search(r'\.b-photos \.photo \{ border-radius:var\(--r-panel\); box-shadow:var\(--photo-float\); \}', css), 'block photographs: the corners of the quotation panels and a light shadow'
    assert '#lightbox img { border-radius:var(--r-panel); }' in css
    for plain in ('.hero-photo {', '.b-band .photo {'):
        assert 'border-radius' not in css[css.index(plain):].split('}', 1)[0], f'{plain} dissolves into the page: no frame'
    for ring in ('calm-pair', 'lead-small'):
        rule = re.search(r'\.b-photos\[data-comp="' + ring + r'"\] \.photo:nth-child\(2\) \{ grid-column:6 / -1;[^}]*\}', css).group(0)
        assert 'var(--c-bg,transparent),var(--photo-float)' in rule, f'{ring} on phones: the ring around the overlapping photograph and the shadow'


'''

TEST_EDITS = [
    ("allowed = ('.button', '.icon-button', '.contact-links', 'summary::after', '.field', '.slot-badge', '.num-badge', '.skip', '.lb-close', '.quote-panel')",
     "allowed = ('.button', '.icon-button', '.contact-links', 'summary::after', '.field', '.slot-badge', '.num-badge', '.skip', '.lb-close', '.quote-panel', '.b-photos .photo', '#lightbox img')", 'soft controls: photo blocks may be rounded'),
    ('"""Rounded corners belong to buttons, fields and the quotation panels; photos, other panels and sections stay square. No "up" button."""',
     '"""Rounded corners belong to buttons, fields, the quotation panels and the photographs of the blocks (seo-photos-v1); the first-screen photograph, the wide strip, other panels and sections stay square. No "up" button."""', 'soft controls: docstring'),
    ("for square in ('.photo {', '.free {', '.blog-card {', '.b-panel {', '.b-photos .photo {'):", "for square in ('.photo {', '.free {', '.blog-card {', '.b-panel {'):", 'soft controls: photo blocks are no longer square'),
    ('def main():\n    builder = load_builder()\n', TEST_FUNCTION + 'def main():\n    builder = load_builder()\n', 'new test function'),
    ('    check_rich_text(builder)\n\n    # Full-featured build', '    check_rich_text(builder)\n    check_seo_photos(builder)\n\n    # Full-featured build', 'call of the new test'),
]

# ----------------------------------------------------------------------------------------------------------
# Документы (дописываются в конец; повторно не добавляются)
# ----------------------------------------------------------------------------------------------------------
README_ADD = '''

## Обновление: SEO-аудит и вид фотографий (ноябрь 2026) <!-- seo-photos-v1 -->

Скрипт `apply_seo_photos_update.py`. Коллега прогнал сайт через автоматический аудит; ниже, что из этого применимо к нашему сайту, что сделано и что намеренно нет.

**Главное про «noindex» и `robots.txt`.** Эти два запрета не вшиты в файлы: их ставит выключатель `publish_ready` («Готов к индексации»). Пока он выключен, страницы закрыты, и аудит честно ставит низкий балл. Выключатель **не включён**: по `docs/CONTENT-REVIEW.md` его включают после замены фото с водяными знаками и проверки текстов. Когда будете готовы: панель → «Публикация» → «Готов к индексации». Тогда же появятся `sitemap.xml` и `llms.txt`, а `robots.txt` откроет сайт (закрытой останется только `/admin/`).

**Сделано**

- **Адрес сайта** (`public_url` в `content/site.json`) = `https://sportintuitive.com`. Раньше он был пустым, и сборка подставляла `neurossoneri.github.io/anysports`: отсюда чужой canonical, og:url, адрес в JSON-LD и карте сайта. Теперь все они на вашем домене (проверено на тестовой сборке; домен без `www`, как в замечании коллеги, из песочницы я это не проверяла).
- **Метатег robots** при включённой индексации: `index,follow,max-image-preview:large,max-snippet:-1`. До запуска остаётся `noindex,nofollow`.
- **Картинка для превью ссылок.** При сборке из главного фото делается `assets/og-cover.jpg`, 1200×630, JPEG (соцсети не берут WebP). Вертикальное фото целиком, на размытой тёмной копии себя, так что лицо не обрезается; горизонтальное обрезается по размеру. Добавлены `og:image:type/width/height/alt`, `og:locale` и карточка `twitter:*` (заголовок и описание те же, что в `og:*`).
- **JSON-LD:** постоянный `@id` (`…/#person`). Ключ `sameAs` не добавлен: профилей в настройках нет, придумывать их нельзя.
- **Размеры фото.** У каждого фото на странице теперь `width` и `height` (берутся из файла при сборке), браузер резервирует место и страница не «прыгает». Вид не меняется: размер по-прежнему задаёт CSS.
- **Главное фото** сразу ставится в очередь загрузки: `<link rel="preload" as="image">` с теми же уменьшенными копиями, что и у самого `<img>` (так браузер не скачивает фото дважды). `fetchpriority="high"` у него уже был, остальные фото уже были `loading="lazy"`.
- **Заголовки безопасности, которые возможны в `<head>`:** `Referrer-Policy` (мета-тег) и `Content-Security-Policy` (мета-тег, на всех страницах кроме `/admin/`).
- **`llms.txt`** (при включённой индексации): короткая карта сайта из ваших же названий разделов.
- **Фото.** Фотографии в блоках получили мягкие скругления (как у панелей цитат) и лёгкую тень, будто парят над страницей; то же скругление у фото в режиме «открыть крупнее». Первый экран и широкая полоса растворяются в фон (маска), рамка и тень там смотрелись бы чужими, поэтому они без изменений.

**Про политику безопасности (CSP).** В аудите предложена строка со `script-src 'self'`: она заблокировала бы все скрипты страницы (форма, фото крупнее, прогресс прокрутки), потому что они написаны прямо в странице. Поэтому политика другая: скрипты разрешены только свои и те, что названы по хэшу (его сборка считает сама из готовой страницы). Стили, картинки, шрифты и связь с Google-скриптом формы политикой **не ограничены**: форму проверить на настоящем Google из песочницы нельзя, а потерянная заявка хуже, чем неограниченная картинка.

**Что намеренно не сделано (решайте вы)**

- `publish_ready` не включён (см. выше).
- Правило для ИИ-ботов (`GPTBot`, `ClaudeBot` и т. п.) в `robots.txt` не добавлено: группа `User-agent: *` и так разрешает всем. К тому же бот с собственной группой не читает правило для `*`, и ему стала бы доступна `/admin/`.
- Абзац-оговорка в подвале: в нём слово «treatment», а проверка запрещённых формулировок его не пропустит; оговорка о том, что сессии не заменяют медицинскую помощь, на сайте уже есть (см. `docs/CONTENT-REVIEW.md`, раздел 2). Добавлять второй текст от своего имени я не стала.
- Заголовок «Intuition is for everyone, so why is this page created specifically for athletes?» (81 знак) не сокращён: это ваш текст и ваш голос; править в панели «Тексты».
- Внутренние ссылки между разделами и внешние ссылки: это новый текст на странице, решение за вами (якоря у разделов уже есть: `#sessions`, `#change`, `#about`, `#contact`, `#qa`).
- Описания фото (alt): я не вижу фотографий, поэтому описывать их не могу. Три пустых alt принадлежат декоративным фото (фон цитаты и широкие полосы), и пустое значение для них правильно. Повторяющиеся «Photographs from the FIFA archive» и «Recent photographs» меняются в панели, блок «Фото», поле «Описание фото для скринридеров».

**Невозможно на GitHub Pages** (нужны настоящие HTTP-заголовки): HSTS, `X-Frame-Options`, `X-Content-Type-Options`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`. Решение, если понадобится: Cloudflare перед доменом или другой хостинг (`docs/HOSTING.md`). TLS на GitHub Pages обычно уже 1.2/1.3.

**Что проверено и что нет:** см. ответ к патчу. Тесты: `check_seo_photos()` в `scripts/test_build.py`; правило «фото остаются квадратными» заменено правилом «фото в блоках мягкие, первый экран и полоса без рамки».
'''

DASHBOARD_ADD = '''

## Адрес сайта, индексация и превью ссылок <!-- seo-photos-v1 -->

- **Адрес сайта** (панель → «Настройки») должен быть `https://sportintuitive.com/`. От него зависят канонические ссылки, карта сайта, превью ссылок. Если поле пустое, сайт использует адрес `…github.io/…`.
- **«Готов к индексации»** (вкладка «Публикация») включайте последним, по списку из `docs/CONTENT-REVIEW.md`. Пока выключено, страницы закрыты от поисковиков, и это нормально.
- **Превью ссылки** (когда пересылаете сайт в мессенджере или соцсети) берётся из главного фото: сайт сам делает картинку 1200×630. Если смените главное фото, она обновится при следующей публикации. Соцсети хранят старое превью несколько дней.
- **Описания фото** (для скринридеров и поисковиков): блок «Фото» → «Описание фото для скринридеров». У фонов цитат и широких полос поле намеренно пустое.
'''

CONCEPT_ADD = '''

## Фото: мягкие углы и лёгкая тень (ноябрь 2026) <!-- seo-photos-v1 -->

- Фото в блоках повторяют язык панелей цитат и кнопки «Send»: те же скругления (`--r-panel`) и мягкая тень (`--photo-float`), как будто фото чуть парит над страницей. На тёмных полосах тень глубже, иначе её не видно. Прежнее правило «фото остаются квадратными» отменено владелицей.
- Первый экран и широкая полоса остаются без рамки: их нижний и верхний край растворяются в фон (маска), и скругление с тенью там выглядели бы чужими. Если захотите скруглить и их, это отдельное решение.
- На телефоне у перекрывающихся фото (спокойная пара, крупное и малое) сохранён светлый ободок вокруг малого фото, тень добавлена поверх него.
'''

CONTENT_REVIEW_ADD = '''

## Что проверить после SEO-обновления <!-- seo-photos-v1 -->

- [ ] В панели → «Настройки» адрес сайта `https://sportintuitive.com/` (патч вписал его сам; если у домена основной вариант с `www`, замените).
- [ ] Посмотреть превью ссылки (отправить адрес себе в мессенджер или открыть opengraph.xyz) после включения индексации: лицо на картинке 1200×630 целиком, фон приятный. Если нет, смените главное фото или его кадрирование.
- [ ] Описания фото: «Photographs from the FIFA archive» стоит у трёх фото подряд, «Recent photographs» тоже. Лучше описать каждое своими словами (5–12 слов).
- [ ] Посмотреть сайт на компьютере и на телефоне: фото в блоках скруглены и чуть «парят». Если тень слишком сильная или слабая, скажите, поправлю одну переменную `--photo-float`.
- [ ] Оговорка про медицинскую и психологическую помощь уже есть в тексте; отдельный абзац в подвале не добавлялся (см. README, «Что намеренно не сделано»).
- [ ] После включения индексации в Google Search Console добавить сайт и отправить `https://sportintuitive.com/sitemap.xml`.
'''

HOSTING_ADD = '''

## Заголовки безопасности на GitHub Pages <!-- seo-photos-v1 -->

GitHub Pages не позволяет задавать HTTP-заголовки, поэтому в `<head>` страниц стоят только `Referrer-Policy` и `Content-Security-Policy` (мета-теги). Невозможны: `Strict-Transport-Security` (HSTS), `X-Frame-Options`, `X-Content-Type-Options`, `Permissions-Policy`, `Cross-Origin-Opener-Policy`; файл `_headers` здесь не работает. Закрыть их можно только Cloudflare перед доменом (бесплатный план, правила заголовков) или переездом на хостинг с заголовками (этап 2 выше). Для сайта-визитки это не срочно; решение за владелицей.
'''

# ----------------------------------------------------------------------------------------------------------
# Применение
# ----------------------------------------------------------------------------------------------------------
texts, originals, newline_style, problems = {}, {}, {}, []


def load(rel):
    if rel not in texts:
        path = ROOT / rel
        if not path.is_file():
            problems.append(f'{rel}: файл не найден (запускайте скрипт из корня репозитория)')
            texts[rel] = ''
            originals[rel] = ''
            newline_style[rel] = '\n'
        else:
            raw = path.read_bytes().decode('utf-8')
            newline_style[rel] = '\r\n' if '\r\n' in raw else '\n'
            texts[rel] = raw.replace('\r\n', '\n')
            originals[rel] = texts[rel]
    return texts[rel]


def replace(rel, old, new, name):
    text = load(rel)
    count = text.count(old)
    if count != 1:
        problems.append(f'{rel}: «{name}» найдено {count} раз (нужно ровно 1)')
        return
    texts[rel] = text.replace(old, new, 1)


def insert_line_before(rel, prefix, new_line, name):
    text = load(rel)
    lines = text.split('\n')
    hits = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    if len(hits) != 1:
        problems.append(f'{rel}: «{name}»: строк, начинающихся с {prefix!r}, {len(hits)} (нужна ровно 1)')
        return
    lines.insert(hits[0], new_line)
    texts[rel] = '\n'.join(lines)


def append_doc(rel, addition):
    text = load(rel)
    if MARK not in text:
        texts[rel] = text.rstrip('\n') + '\n' + addition


def plan():
    done = []
    # content/site.json
    site = load('content/site.json')
    try:
        data = json.loads(site)
    except ValueError:
        problems.append('content/site.json: не читается как JSON')
        data = {}
    if str(data.get('public_url') or '').strip():
        done.append('content/site.json')
    else:
        insert_line_before('content/site.json', '  "publish_ready"', '  "public_url": "https://sportintuitive.com",', 'public_url')
    for rel, edits, marker in (('scripts/build.py', BUILD_EDITS, '# seo-photos-v1'), ('templates/index.html', TEMPLATE_EDITS, '/* seo-photos-v1.'),
                               ('scripts/test_build.py', TEST_EDITS, 'def check_seo_photos')):
        if marker in load(rel):
            done.append(rel)
            continue
        for old, new, name in edits:
            replace(rel, old, new, name)
    for rel, addition in (('README.md', README_ADD), ('docs/DASHBOARD.md', DASHBOARD_ADD), ('docs/CONCEPT.md', CONCEPT_ADD),
                          ('docs/CONTENT-REVIEW.md', CONTENT_REVIEW_ADD), ('docs/HOSTING.md', HOSTING_ADD)):
        append_doc(rel, addition)
    return done


def main():
    already = plan()
    if not problems:   # синтаксис проверяется до записи
        for rel in ('scripts/build.py', 'scripts/test_build.py'):
            try:
                compile(texts[rel], rel, 'exec')
            except SyntaxError as exc:
                problems.append(f'{rel}: после правки не компилируется ({exc})')
        try:
            json.loads(texts['content/site.json'])
        except ValueError:
            problems.append('content/site.json: после правки не JSON')
    if problems:
        print('НИЧЕГО НЕ ЗАПИСАНО. Не нашлось места для правок:')
        for item in problems:
            print('  -', item)
        print('Скорее всего файлы изменились после снимка репозитория. Пришлите свежий снимок.')
        return 1
    changed = [rel for rel in texts if texts[rel] != originals[rel]]
    if not changed:
        print('Уже применено: изменений 0.')
        return 0
    for rel in changed:
        target = BACKUP / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(ROOT / rel, target)
    for rel in changed:
        data = texts[rel].replace('\n', newline_style[rel])
        (ROOT / rel).write_bytes(data.encode('utf-8'))
    ignore = ROOT / '.gitignore'
    existing = ignore.read_text(encoding='utf-8') if ignore.exists() else ''
    if '.backup-seo-photos/' not in existing.split('\n'):
        ignore.write_text(existing.rstrip('\n') + '\n.backup-seo-photos/\n', encoding='utf-8')
    print('Изменено файлов:', len(changed))
    for rel in changed:
        print('  +', rel)
    print('Оригиналы сохранены в .backup-seo-photos/ (вернуть: скопировать файлы оттуда обратно).')
    print('\n=== scripts/build.py ===')
    build = subprocess.run([sys.executable, 'scripts/build.py'], cwd=ROOT)
    print('\n=== scripts/test_build.py ===')
    tests = subprocess.run([sys.executable, 'scripts/test_build.py'], cwd=ROOT)
    if build.returncode or tests.returncode:
        print('\nСБОРКА ИЛИ ТЕСТЫ КРАСНЫЕ (код сборки %s, тестов %s). Если нужно откатиться: скопируйте файлы из .backup-seo-photos/ обратно.' % (build.returncode, tests.returncode))
        return 1
    print('\nСборка и тесты зелёные. Дальше: git add -A && git commit && git push (команды в ответе).')
    return 0


if __name__ == '__main__':
    sys.exit(main())
