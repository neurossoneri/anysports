#!/usr/bin/env python3
"""Build a safe static site (English only) from Pages CMS content. No API keys needed.

Single source of truth for page copy:
  * content/home_<lang>.json   editable copy, grouped by page section (flattened to "group.key")
  * UI (below)                 small system strings: aria labels, form messages, theme labels
  * content/site.json          name, role, contacts, photos, form endpoint
templates/index.html holds markup only. Every text element carries data-i18n="<key>"; the
English copy is baked into the static HTML (SEO, no-JS readers).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import os
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

import bleach
import mistune
import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '_site'
LANGS = ('en',)
LANG_LABEL = {'en': 'English'}
BLOG_LABEL = {'en': 'All notes'}
EMPTY_LABEL = {'en': 'New articles will appear here.'}
BACK_LABEL = {'en': 'Back to home'}
READ_LABEL = {'en': 'Read'}
SKIP_LABEL = {'en': 'Skip to content'}
CONTACT_LABEL = {'en': 'Contact'}

# System strings that are not part of the editable page copy.
UI = {
    'en': {
        'skip': SKIP_LABEL['en'], 'photoSoon': 'A photograph will be here', 'backToTop': 'Back to top',
        'contactEmail': 'Write by email', 'privacyLink': 'privacy notice', 'privacyFooter': 'Privacy notice',
        'formRequired': 'Please add your name and a way to reach you.', 'formSending': 'Sending…',
        'formMailto': 'Opening your mail app…',
        'formUnset': 'The form is not connected yet. Please write directly.',
        'formError': 'Could not send. Please try again or write directly.',
        'formSubject': 'New message from the website', 'cmsAllPosts': BLOG_LABEL['en'],
    },
}

# Fonts are stored on this site (fonts/ is copied to assets/fonts/), so a visitor's browser never contacts a font provider.
FONT_CSS = 'assets/fonts/fonts.css'
FONT_PRELOAD = ('inter-normal-latin', 'source-serif-4-normal-latin', 'source-serif-4-italic-latin')   # used above the fold


def font_links(preload):
    """Preload hints and the stylesheet of the self-hosted fonts. The hrefs are relative: on pages with <base> that tag must come first."""
    hints = ''.join(f'<link rel="preload" href="assets/fonts/{name}.woff2" as="font" type="font/woff2" crossorigin>' for name in preload)
    return hints + f'<link rel="stylesheet" href="{FONT_CSS}">'


FONT_LINKS = font_links(FONT_PRELOAD)
HOME_FONT_LINKS = font_links(FONT_PRELOAD + ('caveat-normal-latin',))
PROGRESS_JS = "<script>(function(){if(window.CSS&&CSS.supports&&CSS.supports('animation-timeline','scroll()')&&!matchMedia('(prefers-reduced-motion: reduce)').matches)return;var b=document.querySelector('.scroll-progress');function u(){var m=document.documentElement.scrollHeight-innerHeight;b.style.setProperty('--p',m>0?Math.min(1,scrollY/m).toFixed(4):0)}addEventListener('scroll',u,{passive:true});u()})()</script>"
VALID_SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
SAFE_IMAGE = re.compile(r'^(?:media/|images/)[\w\-/%.]+\.(?:jpe?g|png|gif|webp|avif)$', re.I)
ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'b', 'i', 'a', 'ul', 'ol', 'li', 'blockquote', 'h2', 'h3', 'h4', 'hr', 'img', 'code', 'pre', 'table', 'thead', 'tbody', 'tr', 'th', 'td']
ALLOWED_ATTRS = {'a': ['href', 'title'], 'img': ['src', 'alt', 'title', 'loading'], 'th': ['align'], 'td': ['align']}
PHOTO_SLOTS = (
    {'field': 'portrait', 'num': 1, 'title': 'Главное фото'},
    {'field': 'quote_photo', 'num': 2, 'title': 'Фото для страницы'},
    {'field': 'eyes_photo', 'num': 3, 'title': 'Фото для страницы'},
    {'field': 'story_photo_1', 'num': 4, 'title': 'Фото для страницы'},
    {'field': 'story_photo_2', 'num': 5, 'title': 'Фото для страницы'},
    {'field': 'story_photo_3', 'num': 6, 'title': 'Фото для страницы'},
    {'field': 'story_photo_4', 'num': 7, 'title': 'Фото для страницы'},
)
PHOTO_FIELDS = tuple(slot['field'] for slot in PHOTO_SLOTS)
SLOT_FIELD = {str(slot['num']): slot['field'] for slot in PHOTO_SLOTS}
PLACE_SLOTS = tuple(str(n) for n in range(2, 8))   # photos 2..7 can be put into blocks; photo 1 is the first screen
SRCSET_WIDTHS = (640, 1080, 1600)   # smaller copies (WebP) for phones and small windows; the original is always the largest choice
# Only the first-screen photograph is a fixed place in the template. An empty one is hidden together with its frame on the live site.
HIDE_WHEN_EMPTY = ('portrait',)

QA_SLOTS = 8
BRAND_DEFAULT = 'Sport Intuitive'
# The logo (also the favicon design) for article pages. The home page has no top bar any more.
BRAND_MARK_SVG = '''<svg viewBox="0 0 48 48" width="35" height="35" xmlns="http://www.w3.org/2000/svg" aria-hidden="true" focusable="false"><rect width="48" height="14" fill="#cfe0f5"/><rect y="14" width="48" height="10" fill="#dce8f8"/><rect y="24" width="48" height="8" fill="#e8ecf9"/><circle cx="37" cy="11" r="4.6" fill="#fff" opacity=".85"/><path d="M-2 31 13 12l8 9 8-12 21 22z" fill="#aab9e4"/><path d="M9.7 16 13 12l3.6 4-1.8-1.1-1.6 1.7-1.6-1.7zM25.9 13.6 29 9l4.6 4.6-2.3-1.2-2.1 2-1.6-1.9z" fill="#fff" opacity=".93"/><path d="M-2 31v-4l8-5 9 9zM19 31l11-9 10 6 10-4v7z" fill="#7f9fd3"/><rect y="31" width="48" height="17" fill="#86c4bc"/><rect y="31" width="48" height="6" fill="#c3e2e0" opacity=".55"/><path d="M12 34.5h9M27 37.5h11M8 40h7" stroke="#fff" stroke-width="1.2" stroke-linecap="round" opacity=".6"/><path d="M-2 48v-8c8-4 15-1 22 3 8 4 18 3 30-2v7z" fill="#8ec99b"/><path d="M14 48c10-3 22-2 36-7v7z" fill="#64aa8b"/><path d="M36 46.5l-.6-4.2M39 46.5l.3-5M42 46.5l1.3-4" stroke="#4f9a7a" stroke-width="1" stroke-linecap="round" fill="none"/></svg>'''
# Dashboard: which page section a group of copy lives in (for the "show on the site" link).
SECTION_ANCHORS = {'hero': 'hero', 'contact': 'contact', 'qa': 'qa', 'free': 'free', 'notes': 'notes'}
# Copy that must never be blank (tests check it; the dashboard enforces it before saving).
REQUIRED_COPY = ('qa.q1',)
# Promise-like wording the site must never carry (checked by the tests and, before saving, by the dashboard).
BANNED_PHRASES = {
    'en': [r'risk of (?:physical )?injur', r'\bprevent', r'burn-?out', r'guarantee', r'\bcures?\b', r'\btreat(?:s|ment)?\b'],
}


def esc(v):
    return html.escape(str(v if v is not None else ''), quote=True)


def brand_name(site):
    """The site's name (Sport Intuitive). Separate from the author's personal name."""
    return str(site.get('brand') or '').strip() or BRAND_DEFAULT


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def js_json(obj):
    # Escape all HTML-sensitive bytes so injected JSON cannot terminate the JS script.
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def flatten(data, source, prefix=''):
    """{"group": {"key": "text"}} -> {"group.key": "text"}; anything but strings and groups is an error."""
    flat = {}
    for key, value in data.items():
        name = f'{prefix}{key}'
        if isinstance(value, dict):
            flat.update(flatten(value, source, name + '.'))
        elif isinstance(value, str):
            flat[name] = value
        else:
            raise ValueError(f'{source}: "{name}" must be text')
    return flat


def url_for_repo(site):
    configured = str(site.get('public_url') or '').strip().rstrip('/')
    if configured:
        parsed = urlparse(configured)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError('public_url must be an https:// URL without query or fragment')
        return configured + '/'
    slug = os.environ.get('GITHUB_REPOSITORY', '')
    if '/' in slug:
        owner, repo = slug.split('/', 1)
        suffix = '' if repo.lower() == owner.lower() + '.github.io' else '/' + repo
        return f'https://{owner}.github.io{suffix}/'
    return ''


def photo_path(p):
    if not p:
        return ''
    p = str(p).lstrip('/')
    if p.startswith('./'):
        p = p[2:]
    if not SAFE_IMAGE.fullmatch(p) or '..' in Path(p).parts:
        raise ValueError(f'Invalid local image path: {p}')
    return p


def form_endpoint(site):
    """The form service URL must be https; anything else is ignored (with a warning), never injected."""
    value = str(site.get('form_endpoint') or '').strip()
    if value and not (value.lower().startswith('https://') and urlparse(value).netloc):
        print(f'WARNING: form_endpoint ignored (must start with https://): {value!r}', file=sys.stderr)
        return ''
    return value


INBOX_URL = re.compile(r'^https://script\.google\.com/(?:a/macros/[\w.-]+|macros)/s/[\w-]+/exec$', re.I)


def inbox_endpoint(site):
    """The requests inbox: a Google Apps Script web app in the owner's own Google account. Anything else is ignored (with a warning)."""
    value = str(site.get('inbox_endpoint') or '').strip()
    if value and not INBOX_URL.fullmatch(value):
        print(f'WARNING: inbox_endpoint ignored (must look like https://script.google.com/macros/s/.../exec): {value!r}', file=sys.stderr)
        return ''
    return value


def inbox_endpoint_quiet(site):
    value = str(site.get('inbox_endpoint') or '').strip()
    return value if INBOX_URL.fullmatch(value) else ''


def parse_posts():
    posts = []
    seen = set()
    for p in sorted((ROOT / 'content/posts').glob('*.md')):
        data = p.read_text(encoding='utf-8')
        if not data.startswith('---\n'):
            raise ValueError(f'{p}: missing YAML frontmatter')
        head, separator, body = data[4:].partition('\n---\n')
        if not separator:
            raise ValueError(f'{p}: missing frontmatter delimiter')
        meta = yaml.safe_load(head) or {}
        if not isinstance(meta, dict):
            raise ValueError(f'{p}: invalid frontmatter')
        if not meta.get('published'):
            continue
        lang, slug = meta.get('lang'), meta.get('slug')
        if lang not in LANGS or not VALID_SLUG.fullmatch(str(slug or '')):
            raise ValueError(f'{p}: invalid language or slug')
        key = (lang, slug)
        if key in seen:
            raise ValueError(f'Duplicate published article: {key}')
        seen.add(key)
        if not meta.get('title') or not meta.get('summary') or not body.strip():
            raise ValueError(f'{p}: missing title, summary, or article body')
        date_value = meta.get('date', dt.date.today())
        if isinstance(date_value, (dt.datetime, dt.date)):
            date_value = date_value.isoformat()[:10]
        date_value = str(date_value)[:10]
        dt.date.fromisoformat(date_value)
        posts.append({
            'lang': lang, 'slug': slug, 'url': f'{lang}/articles/{slug}/',
            'title': str(meta['title']), 'summary': str(meta['summary']),
            'category': str(meta.get('category') or ''), 'date': date_value,
            'cover': photo_path(meta.get('cover')), 'body': body,
        })
    return sorted(posts, key=lambda p: (p['date'], p['slug']), reverse=True)


def render_markdown(source):
    rendered = mistune.create_markdown(escape=True, plugins=['table', 'strikethrough'])(source)
    # Images and links inside rich text may refer to uploaded media by relative path.
    return bleach.clean(rendered, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
                        protocols=['http', 'https', 'mailto'], strip=True)


def card(post, hidden=False):
    cover = (f'<img src="{esc(post["cover"])}" alt="" loading="lazy" decoding="async">'
             if post['cover'] else '<span class="blog-illustration" aria-hidden="true">✦</span>')
    return (f'<article class="blog-card" data-post-lang="{post["lang"]}"{" hidden" if hidden else ""}>'
            f'<div class="blog-cover">{cover}</div><div class="blog-body">'
            f'<span class="blog-category">{esc(post["category"])}</span>'
            f'<h3>{esc(post["title"])}</h3><p>{esc(post["summary"])}</p>'
            f'<a class="article-link" href="{esc(post["url"])}">{esc(READ_LABEL[post["lang"]])}</a>'
            '</div></article>')


def replace_required(text, old, new, name):
    if old not in text:
        raise RuntimeError(f'Template marker not found: {name}')
    return text.replace(old, new, 1)


def seo_head(site, public_url):
    """Canonical, Open Graph and JSON-LD for the home page."""
    name = str(site.get('name_en') or '').strip()
    brand = brand_name(site)
    out = (f'  <link rel="canonical" href="{esc(public_url)}">\n'
           f'  <meta property="og:url" content="{esc(public_url)}">\n'
           f'  <meta property="og:site_name" content="{esc(brand)}">\n')
    portrait = photo_path(site.get('portrait'))
    if portrait:
        out += f'  <meta property="og:image" content="{esc(public_url + portrait)}">\n'
    if name:
        person = {'@context': 'https://schema.org', '@type': 'Person', 'name': name,
                  'jobTitle': str(site.get('role_en') or ''), 'url': public_url,
                  'brand': {'@type': 'Brand', 'name': brand}}
        if portrait:
            person['image'] = public_url + portrait
        out += '  <script type="application/ld+json">' + js_json(person) + '</script>\n'
    return out


def collect_values(site):
    """Per-language flat dictionary of every string the page can show."""
    values = {}
    for lang in LANGS:
        source = f'content/home_{lang}.json'
        content = read_json(source)
        if not isinstance(content, dict):
            raise ValueError(f'Invalid {source}')
        flat = flatten(content, source)
        name = str(site.get('name_' + lang) or '').strip()
        role = str(site.get('role_' + lang) or '').strip()
        brand = brand_name(site)
        title = flat.get('meta.title', '').strip()
        values[lang] = {
            **UI[lang], **flat,
            'brand': brand, 'portraitName': name, 'portraitJob': role,
            'footerName': f'{brand} · {name}' if name else brand,
            'meta.fullTitle': f'{title} — {brand}' if title else brand,
        }
    return values


def notes_section(posts, tone='sand'):
    """Notes appear on the home page only once at least one article is published."""
    if not posts:
        return ''
    cards = ''.join(card(p, hidden=p['lang'] != 'en') for p in posts[:1000])
    hidden = '' if any(p['lang'] == 'en' for p in posts) else ' hidden'
    return ('<section class="band band-' + tone + ' notes" id="notes" aria-labelledby="notes-title"' + hidden + '>'
            '<div class="container"><h2 class="title" id="notes-title" data-i18n="notes.title"></h2>'
            '<p class="lead" data-i18n="notes.lead"></p>'
            f'<div class="notes-grid">{cards}</div>'
            '<p class="notes-all"><a class="button button-outline" id="notes-all" href="en/articles/" data-i18n="cmsAllPosts"></a></p>'
            '</div></section>')


def make_variants(out_root, rel):
    """Smaller WebP copies of one page photograph: [(url, width), ...] from small to large, the original last.
    Needs Pillow. Without it, or for a file it cannot read, the original is used on its own and the build goes on."""
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return []
    source = out_root / rel
    if not source.is_file():
        return []
    variants = []
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            width, height = image.size
            if width < SRCSET_WIDTHS[0] * 1.2:
                return []
            image = image.convert('RGBA' if image.mode in ('RGBA', 'LA') or 'transparency' in image.info else 'RGB')
            stem = re.sub(r'[^A-Za-z0-9]+', '-', rel).strip('-').lower()
            for target in SRCSET_WIDTHS:
                if target >= width * 0.85:
                    break
                name = f'media/opt/{stem}-{target}.webp'
                (out_root / name).parent.mkdir(parents=True, exist_ok=True)
                image.resize((target, max(1, round(height * target / width))), Image.LANCZOS).save(out_root / name, 'WEBP', quality=80, method=4)
                variants.append((name, target))
    except Exception as exc:   # an unusual file must never break the build
        print(f'NOTE: no smaller copies for {rel} ({exc.__class__.__name__}); the original is used.', file=sys.stderr)
        return []
    return variants + [(rel, width)] if variants else []


def copy_media():
    """Copy the uploaded photographs next to the page. Done before the page is built: the page looks for their smaller copies."""
    if not (ROOT / 'media').exists():
        return
    shutil.copytree(ROOT / 'media', OUT / 'media', dirs_exist_ok=True, ignore=shutil.ignore_patterns('.gitkeep'))
    for photo in sorted((OUT / 'media').rglob('*')):
        if photo.is_file() and photo.stat().st_size > 1_500_000:
            print(f'WARNING: {photo.relative_to(OUT)} is {photo.stat().st_size // 1024} KB. Smaller copies are made for the page (when Pillow is installed), '
                  'but compress the original to about 300-400 KB anyway: the admin panel does that by itself.', file=sys.stderr)


# ---------------------------------------------------------------------------------------------
# Page sections. content/sections.json is an ordered list of sections; a text section is a title
# plus an ordered list of blocks (text, quote, statement set aside, photos, list of themes).
# The owner reorders, adds and deletes them in the dashboard; the site is drawn from this list.
# ---------------------------------------------------------------------------------------------
SECTIONS_FILE = 'content/sections.json'
SECTION_TYPES = ('text', 'contact', 'qa')
RESERVED_IDS = {'hero', 'contact', 'qa', 'notes', 'free', 'top', 'main', 'content'}
# Background tones follow the position, so neighbouring sections always differ and every transition exists in the CSS.
# The first screen is deep; then sand, teal, dune, deep, sand, teal ... (the same rhythm the page has always had).
TONE_CYCLE = ('sand', 'teal', 'dune', 'deep')
NOTES_TONE = {'deep': 'sand', 'sand': 'teal', 'teal': 'sand', 'dune': 'deep'}   # tone of the notes band that follows the last section
LAYOUTS = (
    ('rail-right', 'Текст слева, боковая колонка справа'),
    ('rail-left', 'Боковая колонка слева, текст справа'),
    ('column', 'Одна колонка у левого края'),
    ('centered', 'Одна колонка по центру (как предисловие)'),
)
TEXT_LOOKS = (
    ('plain', 'Обычный текст (с подзаголовком выглядит как раздел, без него как абзац)'),
    ('lead', 'Крупная вводная фраза'),
    ('panel', 'Плашка с линией слева'),
    ('dropcap', 'Обычный текст, первая буква крупно'),
    ('finale', 'Итоговая фраза по центру'),
    ('hand', 'Рукописная строка по центру'),
)
ASIDE_LOOKS = (('panel', 'Тёмная плашка (можно с фото за текстом)'), ('hand', 'Рукописная фраза без плашки'))
QUOTE_SIZES = (('auto', 'Автоматически (длинные фразы мельче)'), ('large', 'Крупно'), ('small', 'Помельче'))
PHOTO_PLACES = (('inline', 'В тексте'), ('side', 'Сбоку, в боковой колонке'))
THEME_COUNT = 6


def _opts(pairs):
    return [[value, label] for value, label in pairs]


SLOT_OPTIONS = [['', '— нет —']] + [[n, f'Фото {n}'] for n in PLACE_SLOTS]
BLOCK_TYPES = {
    'text': {
        'label': 'Текст', 'add': 'Текст',
        'hint': 'Абзацы разделяйте пустой строкой. Подзаголовок необязателен.',
        'fields': [
            {'name': 'heading', 'label': 'Подзаголовок (необязательно)', 'type': 'string'},
            {'name': 'body', 'label': 'Текст', 'type': 'text'},
            {'name': 'note', 'label': 'Мелкая приписка под текстом (необязательно)', 'type': 'text'},
            {'name': 'look', 'label': 'Оформление', 'type': 'select', 'options': _opts(TEXT_LOOKS), 'default': 'plain'},
        ],
    },
    'quote': {
        'label': 'Цитата в тексте', 'add': 'Цитата',
        'hint': 'Выделенная фраза внутри текста: курсив и цветная линия слева.',
        'fields': [
            {'name': 'text', 'label': 'Цитата', 'type': 'text'},
            {'name': 'size', 'label': 'Размер', 'type': 'select', 'options': _opts(QUOTE_SIZES), 'default': 'auto'},
        ],
    },
    'aside': {
        'label': 'Фраза сбоку', 'add': 'Фраза сбоку',
        'hint': 'Рукописная фраза, вынесенная в сторону, как фото. В разделе с боковой колонкой стоит сбоку, в остальных прямо в тексте. Перенос строки здесь это перенос строки во фразе.',
        'fields': [
            {'name': 'text', 'label': 'Фраза', 'type': 'text'},
            {'name': 'look', 'label': 'Оформление', 'type': 'select', 'options': _opts(ASIDE_LOOKS), 'default': 'panel'},
            {'name': 'photo', 'label': 'Фото за фразой (необязательно)', 'type': 'slot', 'options': SLOT_OPTIONS, 'default': '', 'showIf': {'look': ['panel']}},
        ],
    },
    'photos': {
        'label': 'Фото', 'add': 'Фото',
        'hint': 'Выберите, какие из пронумерованных фото показать (сами фото загружаются на вкладке «Фотографии»). Два фото встают рядом.',
        'fields': [
            {'name': 's1', 'label': 'Первое фото', 'type': 'slot', 'options': SLOT_OPTIONS, 'default': ''},
            {'name': 's2', 'label': 'Второе фото (необязательно)', 'type': 'slot', 'options': SLOT_OPTIONS, 'default': ''},
            {'name': 's3', 'label': 'Третье фото (необязательно)', 'type': 'slot', 'options': SLOT_OPTIONS, 'default': ''},
            {'name': 'place', 'label': 'Где показать', 'type': 'select', 'options': _opts(PHOTO_PLACES), 'default': 'inline'},
            {'name': 'caption', 'label': 'Подпись под фото (необязательно)', 'type': 'string'},
            {'name': 'alt', 'label': 'Описание фото для скринридеров (необязательно)', 'type': 'string'},
        ],
    },
    'themes': {
        'label': 'Список тем со значками', 'add': 'Список тем',
        'hint': 'Шесть тем со значками и итоговая фраза. Тему с пустым названием и пояснением сайт не показывает.',
        'fields': ([{'name': 'title', 'label': 'Заголовок', 'type': 'string'},
                    {'name': 'intro', 'label': 'Вступление', 'type': 'text'}]
                   + [f for n in range(1, THEME_COUNT + 1) for f in (
                       {'name': f't{n}', 'label': f'Тема {n} · фраза', 'type': 'string'},
                       {'name': f'd{n}', 'label': f'Тема {n} · пояснение', 'type': 'text'})]
                   + [{'name': 'finalTitle', 'label': 'Итоговая фраза · заголовок (по центру, крупно)', 'type': 'string'},
                      {'name': 'finalText', 'label': 'Итоговая фраза · текст (по центру)', 'type': 'text'}]),
    },
}
WIDE_BLOCKS = ('themes',)   # these take the full width of the page and close the two-column part of a section
THEME_GLYPHS = (
    '<path d="M4 9h24M8 16h16M12 23h8"/>',
    '<circle cx="16" cy="16" r="2.6"/><path d="M10.5 10.5a7.8 7.8 0 0 0 0 11M21.5 10.5a7.8 7.8 0 0 1 0 11M6 6a14 14 0 0 0 0 20M26 6a14 14 0 0 1 0 20"/>',
    '<circle cx="16" cy="6.5" r="3"/><path d="M16 11v10M8.5 15.5h15M16 21l-5 8M16 21l5 8"/>',
    '<path d="M3 24c5 0 5-8 10-8s5 6 9 0 4-12 7-13" stroke-dasharray="1.5 3.5"/>',
    '<path d="M16 3l11 13-11 13L5 16z"/><circle cx="16" cy="16" r="2.6"/>',
    '<path d="M3 23h26M9 23a7 7 0 0 1 14 0M16 8v4M7.5 12l2.5 2.5M24.5 12L22 14.5"/>',
)
COMPASS_GLYPH = '<svg class="glyph" viewBox="0 0 32 32" aria-hidden="true"><circle cx="16" cy="16" r="12"/><path d="M16 8l3.2 8L16 24l-3.2-8z"/></svg>'
STROKE_SVG = '<svg class="quote-stroke" viewBox="0 0 300 18" preserveAspectRatio="none" aria-hidden="true"><path pathLength="1" d="M2 11 C40 2 72 17 112 9 S190 3 232 10 S282 15 298 7"/></svg>'
PHOTO_PLACEHOLDER = '<div class="ph" aria-hidden="true"><svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="22" cy="26" r="6"/><path d="m9 47 14-13 9 7 11-13 13 16"/></svg><span data-i18n="photoSoon"></span></div>'
SECTION_DEFAULT_LAYOUT = 'column'


def default_block(kind):
    """A new empty block with the default value of every field."""
    block = {'type': kind}
    for field in BLOCK_TYPES[kind]['fields']:
        block[field['name']] = field.get('default', '')
    return block


def _warn(message):
    print(f'WARNING: {message}', file=sys.stderr)


def clean_block(raw, where):
    """One block from sections.json. Cosmetic mistakes (an unknown look, a wrong photo number) fall back to the default and never stop the build."""
    if not isinstance(raw, dict) or raw.get('type') not in BLOCK_TYPES:
        _warn(f'{where}: unknown block skipped')
        return None
    kind = raw['type']
    block = {'type': kind}
    for field in BLOCK_TYPES[kind]['fields']:
        value = raw.get(field['name'], field.get('default', ''))
        value = '' if value is None else str(value)
        if field['type'] in ('select', 'slot') and value not in [o[0] for o in field['options']]:
            if value:
                _warn(f'{where}: "{value}" is not a valid {field["name"]}; the default is used')
            value = field.get('default', '')
        block[field['name']] = value
    return block


def load_sections():
    """The ordered sections of the page. Contact and Q&A are always present (added at the end if the file lost them)."""
    path = ROOT / SECTIONS_FILE
    if not path.exists():
        raise ValueError(f'{SECTIONS_FILE} is missing')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('sections'), list):
        raise ValueError(f'{SECTIONS_FILE}: expected {{"sections": [...]}}')
    sections, seen = [], set()
    for index, raw in enumerate(data['sections'], 1):
        if not isinstance(raw, dict) or raw.get('type') not in SECTION_TYPES:
            _warn(f'section {index}: unknown type skipped')
            continue
        kind = raw['type']
        sid = kind if kind != 'text' else str(raw.get('id') or '').strip()
        if kind == 'text' and (not VALID_SLUG.fullmatch(sid) or sid in RESERVED_IDS):
            _warn(f'section {index}: invalid or reserved id "{sid}" skipped')
            continue
        if sid in seen:
            _warn(f'section {index}: duplicate id "{sid}" skipped')
            continue
        seen.add(sid)
        section = {'id': sid, 'type': kind}
        if kind == 'text':
            layout = str(raw.get('layout') or SECTION_DEFAULT_LAYOUT)
            if layout not in [l[0] for l in LAYOUTS]:
                _warn(f'section {sid}: unknown layout "{layout}"; "{SECTION_DEFAULT_LAYOUT}" is used')
                layout = SECTION_DEFAULT_LAYOUT
            blocks = raw.get('blocks') if isinstance(raw.get('blocks'), list) else []
            section.update({'title': str(raw.get('title') or ''), 'layout': layout,
                            'blocks': [clean_block(b, f'section {sid}, block {n}') for n, b in enumerate(blocks, 1)]})
        sections.append(section)
    for kind in ('contact', 'qa'):
        if kind not in seen:
            _warn(f'section "{kind}" was missing from {SECTIONS_FILE}; it is added at the end')
            sections.append({'id': kind, 'type': kind})
    return sections


def paragraphs(text):
    return [p.strip() for p in re.split(r'\n[ \t]*\n', str(text or '').strip()) if p.strip()]


def para_html(text, cls=''):
    attr = f' class="{cls}"' if cls else ''
    return ''.join(f'<p{attr}>{esc(p)}</p>' for p in paragraphs(text))


def block_has_content(block):
    kind = block['type']
    if kind == 'text':
        return bool(block['heading'].strip() or block['body'].strip() or block['note'].strip())
    if kind in ('quote', 'aside'):
        return bool(block['text'].strip())
    if kind == 'photos':
        return any(block[k] for k in ('s1', 's2', 's3'))
    if kind == 'themes':
        return any(v.strip() for k, v in block.items() if k != 'type')
    return False


def is_rail_block(block):
    return block['type'] == 'aside' or (block['type'] == 'photos' and block['place'] == 'side')


class PageContext:
    """What the block renderers need: the settings, whether the site is live, and the photo copies already made."""
    def __init__(self, site, ready):
        self.site, self.ready, self.cache = site, ready, {}

    def photo(self, num, alt, sizes, frame_class='', bg=False):
        """The frame of numbered photo `num`. An empty place is drawn with a number before launch and left out on the live site."""
        path = photo_path(self.site.get(SLOT_FIELD[num]))
        if not path and self.ready:
            return ''
        attributes = f'data-slot="{num}"'
        if path:
            attributes += f' src="{esc(path)}"'
            if path not in self.cache:
                self.cache[path] = make_variants(OUT, path)
            if self.cache[path]:
                attributes += ' srcset="' + ', '.join(f'{esc(name)} {size}w' for name, size in self.cache[path]) + f'" sizes="{esc(sizes)}"'
        if bg:
            return f'<figure class="photo quote-bg" aria-hidden="true"><img {attributes} alt="" loading="lazy" decoding="async"></figure>'
        return (f'<figure class="photo {frame_class}"><img {attributes} alt="{esc(alt)}" loading="lazy" decoding="async">'
                f'{PHOTO_PLACEHOLDER}</figure>')


def render_block(block, label, ctx, in_rail):
    """HTML of one block, or '' when it is empty or has nothing to show. `label` is its number, like 4.2 (the same as in the dashboard)."""
    if not block or not block_has_content(block):
        return ''
    kind, number = block['type'], f'data-blk="{label}"'
    if kind == 'text':
        heading = f'<h3>{esc(block["heading"].strip())}</h3>' if block['heading'].strip() else ''
        note = f'<p class="b-note">{esc(block["note"].strip())}</p>' if block['note'].strip() else ''
        look = block['look']
        if look == 'lead':
            return f'<div class="b b-lead" {number} data-fade>{para_html(block["body"])}{note}</div>'
        if look == 'panel':
            return f'<div class="b b-panel" {number} data-fade>{heading}{para_html(block["body"])}{note}</div>'
        if look == 'finale':
            return (f'<div class="b b-finale finale" {number} data-finale><span class="finale-line" aria-hidden="true"></span>{COMPASS_GLYPH}'
                    f'{heading}{para_html(block["body"])}</div>')
        if look == 'hand':
            return (f'<div class="b b-hand finale finale-hand" {number} data-finale><span class="finale-line" aria-hidden="true"></span>'
                    f'<p class="finale-note" data-write>{esc(block["body"].strip())}</p>{STROKE_SVG}</div>')
        classes = 'b b-text' + (' has-h' if heading else '') + (' b-dropcap' if look == 'dropcap' else '')
        return f'<div class="{classes}" {number} data-fade>{heading}{para_html(block["body"])}{note}</div>'
    if kind == 'quote':
        text = block['text'].strip()
        small = block['size'] == 'small' or (block['size'] == 'auto' and len(text) > 70)
        return f'<blockquote class="b b-quote pull{" pull-long" if small else ""}" {number} data-fade>{esc(text)}</blockquote>'
    if kind == 'aside':
        text = block['text'].strip()
        if block['look'] == 'hand':
            return f'<div class="b b-aside aside-hand" {number}><blockquote class="quote-text" data-write>{esc(text)}</blockquote>{STROKE_SVG}</div>'
        figure = ctx.photo(block['photo'], '', '(max-width:900px) 100vw, 600px', bg=True) if block['photo'] else ''
        return f'<div class="b b-aside quote-panel" {number}>{figure}<blockquote class="quote-text" data-write>{esc(text)}</blockquote>{STROKE_SVG}</div>'
    if kind == 'photos':
        slots = [block[k] for k in ('s1', 's2', 's3') if block[k]]
        count = len(slots)
        sizes = ('(max-width:900px) 100vw, 45vw' if in_rail else '(max-width:700px) 90vw, 420px') if count == 1 else '(max-width:700px) 45vw, 480px'
        alt = block['alt'].strip() or block['caption'].strip()
        figures = [f for f in (ctx.photo(n, alt, sizes, 'frame') for n in slots) if f]
        if not figures:
            return ''
        caption = f'<p class="b-cap">{esc(block["caption"].strip())}</p>' if block['caption'].strip() else ''
        return f'<div class="b b-photos n{len(figures)}{" b-side" if in_rail else ""}" {number} data-fade>{"".join(figures)}{caption}</div>'
    if kind == 'themes':
        items = ''
        for n in range(1, THEME_COUNT + 1):
            title, detail = block[f't{n}'].strip(), block[f'd{n}'].strip()
            if title or detail:
                items += (f'<li class="theme" data-fade><svg class="glyph" viewBox="0 0 32 32" aria-hidden="true">{THEME_GLYPHS[n - 1]}</svg>'
                          f'<strong>{esc(title)}</strong><span>{esc(detail)}</span></li>')
        head = (f'<h3 class="themes-title" data-fade>{esc(block["title"].strip())}</h3>' if block['title'].strip() else '')
        intro = f'<p class="lead" data-fade>{esc(block["intro"].strip())}</p>' if block['intro'].strip() else ''
        grid = f'<ul class="theme-grid">{items}</ul>' if items else ''
        final = ''
        if block['finalTitle'].strip() or block['finalText'].strip():
            final = ('<div class="finale" data-finale><span class="finale-line" aria-hidden="true"></span>' + COMPASS_GLYPH
                     + (f'<h3>{esc(block["finalTitle"].strip())}</h3>' if block['finalTitle'].strip() else '')
                     + (f'<p>{esc(block["finalText"].strip())}</p>' if block['finalText'].strip() else '') + '</div>')
        return f'<div class="b b-themes themes" {number}>{head}{intro}{grid}{final}</div>'
    return ''


def render_text_section(section, number, tone, ctx):
    """One text section: a title above, then its blocks. Statements set aside and side photos go to a sticky side column when the layout has one."""
    blocks = section['blocks']
    layout = section['layout']
    has_rail_layout = layout in ('rail-left', 'rail-right')
    labelled = list(enumerate(blocks, 1))
    rail_html = ''
    if has_rail_layout:
        rail_html = ''.join(render_block(b, f'{number}.{n}', ctx, True) for n, b in labelled if b and is_rail_block(b))
    if not rail_html and has_rail_layout:
        layout = 'column'   # nothing to put aside (for example a photo that is not uploaded yet): one column
    segments, current, grid_done = [], [], False

    def flush():
        nonlocal current, grid_done
        if current:
            grid = bool(rail_html) and not grid_done
            body = f'<div class="blocks{"" if grid else " col"}">{"".join(current)}</div>'
            if grid:
                rail = f'<div class="rail">{rail_html}</div>'
                body = f'<div class="sec-grid">{rail + body if layout == "rail-left" else body + rail}</div>'
                grid_done = True
            segments.append(body)
            current = []

    for n, block in labelled:
        if not block:
            continue
        if has_rail_layout and rail_html and is_rail_block(block):
            continue
        html_block = render_block(block, f'{number}.{n}', ctx, False)
        if not html_block:
            continue
        if block['type'] in WIDE_BLOCKS:
            flush()
            segments.append(html_block)
        else:
            current.append(html_block)
    flush()
    if rail_html and not grid_done:
        segments.insert(0, f'<div class="sec-grid"><div class="rail">{rail_html}</div></div>')
    title = section['title'].strip()
    head = ''
    if title:
        head = f'<header class="sec-head"><h2 class="title{" title-long" if len(title) > 60 else ""}" id="{section["id"]}-title" data-fade>{esc(title)}</h2></header>'
    labelled_by = f' aria-labelledby="{section["id"]}-title"' if title else ''
    return (f'<section class="band band-{tone} sec sec-{layout}" id="{section["id"]}"{labelled_by} data-sec="{number}">'
            f'<div class="container">{head}{"".join(segments)}</div></section>')


def take_section(template, sid):
    """Cut a fixed section (contact, qa) out of the template; it is put back at its place in the page order."""
    pattern = re.compile(r'[ \t]*<section class="band band-(?:sand|teal|dune|deep)[^"]*" id="' + sid + r'"[^>]*>.*?</section>[ \t]*\n?', re.S)
    found = pattern.findall(template)
    if len(found) != 1:
        raise RuntimeError(f'Template section not found exactly once: {sid}')
    return pattern.sub('', template, count=1), found[0].strip('\n')


def place_sections(template, sections, ctx):
    """Replace the sections marker with every section in order. Returns the new template and the tone of the last section."""
    fixed = {}
    for kind in ('contact', 'qa'):
        template, fixed[kind] = take_section(template, kind)
    parts, tone = [], 'deep'
    for index, section in enumerate(sections):
        tone, number = TONE_CYCLE[index % len(TONE_CYCLE)], index + 1
        if section['type'] == 'text':
            parts.append(render_text_section(section, number, tone, ctx))
        else:
            html_part = fixed[section['type']]
            html_part = re.sub(r'band-(?:sand|teal|dune|deep)', f'band-{tone}', html_part, count=1)
            html_part = html_part.replace(f'id="{section["type"]}"', f'id="{section["type"]}" data-sec="{number}"', 1)
            parts.append('    ' + html_part.lstrip())
    return replace_required(template, '<!--@@SECTIONS@@-->', '\n\n'.join(parts), 'sections marker'), tone


def build_home(site, posts, public_url, ready):
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    values = collect_values(site)
    copy = values['en']

    sections = load_sections()
    context = PageContext(site, ready)
    template, last_tone = place_sections(template, sections, context)
    notes_tone = NOTES_TONE[last_tone]
    template = replace_required(template, '<!--@@NOTES@@-->', notes_section(posts, notes_tone), 'notes marker')
    template = replace_required(template, '<!--@@FONTS@@-->', HOME_FONT_LINKS, 'fonts marker')
    template = replace_required(template, '<span id="year">2026</span>', f'<span id="year">{dt.date.today().year}</span>', 'year marker')
    # the footer fades from the tone of the last band (the notes band when there are articles)
    template = replace_required(template, 'site-footer after-teal', f'site-footer after-{notes_tone if posts else last_tone}', 'footer tone')
    # The first-screen photograph is the only fixed place in the template; every other photograph sits in a block of a section.
    # A numbered place shows its own photograph or stays empty: it never borrows the picture of another one.
    for slot in PHOTO_SLOTS[:1]:
        field = slot['field']
        path = photo_path(site.get(field))
        attributes = f'data-slot="{slot["num"]}"'
        if path:
            attributes += f' src="{esc(path)}"'
            variants = make_variants(OUT, path)
            if variants:
                attributes += ' srcset="' + ', '.join(f'{esc(name)} {size}w' for name, size in variants) + '" sizes="50vw"'
        elif ready and field in HIDE_WHEN_EMPTY:   # live site: an empty place disappears together with its frame
            template, found = re.subn(r'(<figure\b[^>]*)(>\s*<img data-photo="' + field + '")', r'\1 hidden\2', template, count=1)
            if not found:
                raise RuntimeError(f'Template frame not found: {field}')
        template = replace_required(template, f'data-photo="{field}"', attributes, f'photo {field}')
    settings = {
        'email': str(site.get('email') or ''),
        'whatsapp': str(site.get('whatsapp') or ''),
        'telegram': str(site.get('telegram') or ''),
        'formEndpoint': form_endpoint(site),
        'inboxEndpoint': inbox_endpoint(site),
        'preview': not ready,   # before launch the empty photo places carry their numbers
    }
    # Content inserted before the page script reads it, right after the empty translation object.
    counts = {lang: sum(p['lang'] == lang for p in posts) for lang in LANGS}
    injection = (f'    Object.assign(SETTINGS, {js_json(settings)});\n'
                 f'    const CMS_OVERRIDES = {js_json(values)};\n'
                 '    for (const [locale, entries] of Object.entries(CMS_OVERRIDES)) Object.assign(translations[locale], entries);\n'
                 f'    const CMS_VISIBLE_POSTS = {js_json(counts)};')
    template = replace_required(template, '    // @@CMS_INJECTION@@', injection, 'CMS injection')
    template = replace_required(template, '<meta name="color-scheme"',
        ('<meta name="robots" content="index,follow">' if ready else '<meta name="robots" content="noindex,nofollow">') + '\n  <meta name="color-scheme"', 'robots')

    # Bake the English copy into static HTML: SEO, no-JS readers, no flash before the script runs.
    for key, value in copy.items():
        k = re.escape(key)
        text_pat = re.compile(r'(<(?P<tag>[a-z][a-z0-9]*)\b[^>]*\bdata-i18n="' + k + r'"[^>]*>)([^<]*)(</(?P=tag)>)', re.I)
        template = text_pat.sub(lambda m, v=value: m.group(1) + esc(v) + m.group(4), template)
        template = template.replace(f'data-i18n-alt="{key}" alt=""', f'data-i18n-alt="{key}" alt="{esc(value)}"')
        template = template.replace(f'data-i18n-aria="{key}"', f'data-i18n-aria="{key}" aria-label="{esc(value)}"')
    for slot in range(1, QA_SLOTS + 1):
        if not copy.get(f'qa.q{slot}', '').strip():
            template = replace_required(template, f'<details name="qa" data-qa="{slot}">', f'<details name="qa" data-qa="{slot}" hidden>', f'qa slot {slot}')

    doc_title = copy['meta.fullTitle']
    template = re.sub(r'<title>.*?</title>', lambda m: f'<title>{esc(doc_title)}</title>', template, count=1)
    template = re.sub(r'(<meta name="description" content=")[^"]*', lambda m: m.group(1) + esc(copy['meta.description']), template, count=1)
    template = re.sub(r'(<meta property="og:title" content=")[^"]*', lambda m: m.group(1) + esc(doc_title), template, count=1)
    template = re.sub(r'(<meta property="og:description" content=")[^"]*', lambda m: m.group(1) + esc(copy['meta.description']), template, count=1)
    if public_url:
        template = replace_required(template, '</head>', seo_head(site, public_url) + '</head>', 'head')
    (OUT / 'index.html').write_text(template, encoding='utf-8')
    css = re.search(r'<style>(.*?)</style>', template, re.S).group(1)
    (OUT / 'assets').mkdir(parents=True, exist_ok=True)
    (OUT / 'assets/site.css').write_text(css + '\n', encoding='utf-8')


def build_fonts():
    """Copy the self-hosted fonts next to the site (assets/fonts/): no request to any font provider."""
    source = ROOT / 'fonts'
    if not (source / 'fonts.css').exists():
        raise RuntimeError('fonts/fonts.css is missing: the self-hosted fonts are not installed')
    shutil.copytree(source, OUT / 'assets/fonts', dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.md'))


def site_chrome():
    """Logo and favicon for article pages: the favicon comes from the home template, the logo from BRAND_MARK_SVG."""
    tpl = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    icon = re.search(r'<link rel="icon"[^>]*>', tpl)
    return {'brand_html': BRAND_MARK_SVG, 'favicon_html': icon.group(0) if icon else ''}


def article_shell(*, title, description, lang, css_prefix, body, public_url, ready, author, brand, image='', date='', kind='article', brand_html='S', favicon_html=''):
    canonical = (public_url + css_prefix + '/') if public_url else ''
    canonical_html = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ''
    desc = esc(description)
    name = esc(brand)
    route = {'archive': '../../', 'page': '../'}.get(kind, '../../../')
    end_link = (f'<a class="button button-outline" href="./">← {esc(BACK_LABEL[lang])}</a>' if kind == 'page'
                else f'<a class="button button-outline" href="{lang}/articles/">← {esc(BLOG_LABEL[lang])}</a>')
    json_ld = ''
    if kind == 'article':
        schema = {'@context': 'https://schema.org', '@type': 'Article',
                  'headline': title, 'description': description, 'datePublished': date,
                  'inLanguage': lang, 'author': {'@type': 'Person', 'name': author}}
        if canonical:
            schema['mainEntityOfPage'] = canonical
        if image and public_url:
            schema['image'] = public_url + image
        json_ld = '<script type="application/ld+json">' + js_json(schema) + '</script>'
    bg_img = f'<img class="post-hero-image" src="{esc(image)}" alt="" loading="eager">' if image else ''
    article_header = f'<p class="post-meta">{esc(date)} · {esc(LANG_LABEL[lang])}</p>' if date else ''
    return f'''<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="theme-color" content="#06121e"><base href="{route}">{favicon_html}{FONT_LINKS}<meta name="robots" content="{'index,follow' if ready else 'noindex,nofollow'}">
<meta name="description" content="{desc}"><meta property="og:type" content="{'article' if kind == 'article' else 'website'}"><meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{desc}"><title>{esc(title)} — {name}</title>
<link rel="stylesheet" href="assets/site.css"><link rel="stylesheet" href="assets/articles.css">
{canonical_html}{json_ld}<script>(function(){{try{{var t=localStorage.getItem('sport-site-theme');document.documentElement.dataset.theme=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'}}catch(e){{}}}})()</script></head>
<body><div class="scroll-progress" aria-hidden="true"></div><a class="skip" href="{css_prefix}/#content">{esc(SKIP_LABEL[lang])}</a><header class="site-header"><div class="container header-inner">
<a class="brand" href="./"><span class="brand-mark" aria-hidden="true">{brand_html}</span><span class="brand-name">{name}</span></a>
<nav class="article-nav"><a href="./">{esc(BACK_LABEL[lang])}</a><a href="{lang}/articles/">{esc(BLOG_LABEL[lang])}</a><a href="./#contact">{esc(CONTACT_LABEL[lang])}</a></nav>
<button class="icon-button" type="button" id="article-theme" aria-label="Theme" aria-pressed="false">◐</button></div></header>
<main id="content" class="article-layout"><div class="container article-wrap">{article_header}<h1>{esc(title)}</h1>
<p class="article-intro">{desc}</p>{bg_img}<div class="article-body">{body}</div>
<div class="article-end">{end_link}</div></div></main>
<footer class="site-footer"><div class="container footer-inner"><p>© {dt.date.today().year} {name}</p><a href="./">{esc(BACK_LABEL[lang])}</a></div></footer>
<script>(function(){{var b=document.getElementById('article-theme');function s(){{b.setAttribute('aria-pressed',String(document.documentElement.dataset.theme==='dark'))}}b.addEventListener('click',function(){{var t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{{localStorage.setItem('sport-site-theme',t)}}catch(e){{}}s()}});s()}})()</script>{PROGRESS_JS}</body></html>'''


ARTICLES_CSS = '''
.brand { min-width:0; }
.brand-name { min-width:0; overflow:hidden; text-overflow:ellipsis; }
.article-nav { display:flex; align-items:center; gap:22px; flex:none; margin-left:auto; white-space:nowrap; font-weight:650; color:var(--header-muted); font-size:.91rem; }
.article-layout { min-height:65vh; padding:clamp(72px,9vw,128px) 0 clamp(56px,8vw,100px); }
.article-wrap { max-width:760px; }
.article-wrap h1 { font:500 clamp(2.5rem,6vw,4.3rem)/1.08 var(--serif); letter-spacing:-.035em; margin:10px 0 23px; text-wrap:balance; }
.article-intro { font-size:clamp(1.12rem,2.4vw,1.38rem); line-height:1.6; color:var(--text-muted); margin:0 0 48px; text-wrap:pretty; }
.post-meta { color:var(--mint-strong); letter-spacing:.04em; font-size:.84rem; font-weight:700; }
.post-hero-image { max-height:490px; margin-bottom:52px; box-shadow:var(--shadow-strong); }
.article-body { overflow-wrap:anywhere; font-size:1.14rem; line-height:1.9; }
.article-body > * { max-width:100%; }
.article-body p { margin:0 0 1.4em; }
.article-body h2 { font:500 1.9rem/1.25 var(--serif); letter-spacing:-.015em; margin:38px 0 14px; }
.article-body h3 { font:500 1.5rem/1.25 var(--serif); letter-spacing:-.015em; margin:34px 0 12px; }
.article-body a { color:var(--blue-deep); text-decoration:underline; text-underline-offset:3px; }
.article-body img { height:auto; margin:25px 0; }
.article-body blockquote { margin:28px 0; padding:20px 28px; border-left:3px solid var(--mint-strong); color:var(--text-muted); background:var(--glass); }
.article-body blockquote > :last-child { margin-bottom:0; }
.article-body li { margin-bottom:10px; }
.article-body pre { overflow-x:auto; max-width:100%; padding:20px 24px; background:var(--paper); border:1px solid var(--border); }
.article-body table { border-collapse:collapse; max-width:100%; display:block; overflow:auto; }
.article-body th, .article-body td { padding:10px 14px; border:1px solid var(--border); }
.article-end { margin-top:72px; }
.archive-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:clamp(18px,2.4vw,30px); }
.archive-grid .blog-cover { height:180px; }
.article-wrap > * { animation:fadeIn 1s ease both; }
.article-wrap > :nth-child(2) { animation-delay:.07s; }
.article-wrap > :nth-child(3) { animation-delay:.14s; }
.article-wrap > :nth-child(n+4) { animation-delay:.21s; }
@media (prefers-reduced-motion:reduce) {
  .article-wrap > * { animation:none!important; }
}
@media (max-width:760px) {
  .article-nav { gap:12px; font-size:.8rem; }
  .article-nav a:nth-child(2) { display:none; }
  .archive-grid { grid-template-columns:1fr; }
}
@media (max-width:420px) {
  .article-nav a:first-child { display:none; }   /* the site name on the left already links home */
}
'''


def build_articles(site, posts, public_url, ready):
    chrome = site_chrome()
    (OUT / 'assets/articles.css').write_text(ARTICLES_CSS, encoding='utf-8')
    for post in posts:
        body = render_markdown(post['body'])
        path = OUT / post['url'] / 'index.html'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(article_shell(**chrome, title=post['title'], description=post['summary'], lang=post['lang'],
                                      css_prefix=post['url'].rstrip('/'), body=body, public_url=public_url, ready=ready,
                                      author=site.get('name_' + post['lang'], '') or '', brand=brand_name(site), image=post['cover'], date=post['date']), encoding='utf-8')
    for lang in LANGS:
        current = [p for p in posts if p['lang'] == lang]
        body = '<div class="archive-grid">' + ''.join(card(p) for p in current) + '</div>' if current else f'<p>{esc(EMPTY_LABEL[lang])}</p>'
        path = OUT / lang / 'articles/index.html'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(article_shell(**chrome, title=BLOG_LABEL[lang], description=BLOG_LABEL[lang], lang=lang,
                                      css_prefix=f'{lang}/articles', body=body, public_url=public_url, ready=ready,
                                      author=site.get('name_' + lang, '') or '', brand=brand_name(site), kind='archive'), encoding='utf-8')


def md_plain(value):
    """Plain text that is safe inside Markdown."""
    return re.sub(r'([\\`*_{}\[\]<>#|])', r'\\\1', str(value or '').strip())


def privacy_page(site, public_url, ready):
    """privacy/index.html from content/privacy.md: the notice the Swiss FADP (art. 19) asks for, linked from the form and the footer."""
    source = ROOT / 'content/privacy.md'
    if not source.exists():
        return False
    data = source.read_text(encoding='utf-8')
    head, separator, body = data[4:].partition('\n---\n') if data.startswith('---\n') else ('', '', data)
    meta = yaml.safe_load(head) or {}
    name = md_plain(site.get('name_en')) or md_plain(brand_name(site))
    role = md_plain(site.get('role_en'))
    address = md_plain(site.get('privacy_address'))
    email = str(site.get('email') or '').strip()
    lines = ['- **Name:** ' + name + (f', {role}' if role else '')]
    if address:
        lines.append(f'- **Address:** {address}')
    if re.fullmatch(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email):
        lines.append(f'- **Email:** [{email}](mailto:{email})')
    else:
        lines.append('- **Contact:** through the contact form on this website')
        print('WARNING: no email in content/site.json; the privacy notice names the contact form as the way to reach you.', file=sys.stderr)
    endpoint = form_endpoint_quiet(site)
    host = urlparse(endpoint).hostname if endpoint else ''
    inbox = inbox_endpoint_quiet(site)
    if host:
        service = f'The contact form is run by an external service provider (`{host}`). It receives your message and forwards it to my email inbox.'
    elif not inbox:
        service = 'The contact form opens your own email program, so no external form service is involved. Your message then travels through your email provider and mine.'
    else:
        service = 'The contact form sends your message to a script in my own Google account (Google Apps Script), which notifies me by email.'
    if inbox:
        service += ' A copy of your message is also saved in a private spreadsheet in my own Google account (Google Sheets), which I use to keep track of requests and replies. Google processes it on my behalf.'
    updated = meta.get('updated')
    updated = f'{updated.day} {updated:%B %Y}' if isinstance(updated, (dt.date, dt.datetime)) else str(updated or '')
    for marker, value in (('{{controller}}', '\n'.join(lines)), ('{{form_service}}', service), ('{{updated}}', updated)):
        body = body.replace(marker, value)
    chrome = site_chrome()
    out = OUT / 'privacy/index.html'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(article_shell(**chrome, title=str(meta.get('title') or 'Privacy notice'), description=str(meta.get('description') or ''),
                                 lang='en', css_prefix='privacy', body=render_markdown(body), public_url=public_url, ready=ready,
                                 author='', brand=brand_name(site), kind='page'), encoding='utf-8')
    return True


def form_endpoint_quiet(site):
    value = str(site.get('form_endpoint') or '').strip()
    return value if value.lower().startswith('https://') and urlparse(value).netloc else ''


def page_schema():
    """What the dashboard needs to draw the page structure (sections and blocks). Comes from the constants above: one source of truth."""
    return {
        'blockTypes': [{'type': name, 'label': spec['label'], 'add': spec['add'], 'hint': spec['hint'], 'fields': spec['fields']}
                       for name, spec in BLOCK_TYPES.items()],
        'layouts': _opts(LAYOUTS),
        'sectionLabels': {'contact': 'Контакты и форма', 'qa': 'Вопросы и ответы (Q&A) и карточка «вводная беседа бесплатно»'},
        'slots': list(PLACE_SLOTS),
    }


def admin_schema(site):
    """Everything the dashboard needs to draw its forms, generated from .pages.yml so there is one source of truth."""
    config = yaml.safe_load((ROOT / '.pages.yml').read_text(encoding='utf-8'))
    entries = {entry['name']: entry for entry in config['content']}

    def leaf(field):
        item = {'name': field['name'], 'label': field.get('label', field['name']), 'type': field.get('type', 'string')}
        if field.get('description'):
            item['description'] = field['description']
        return item

    groups = []
    for group in entries['home_en']['fields']:
        if group.get('type') != 'object':
            continue
        groups.append({'name': group['name'], 'label': group.get('label', group['name']),
                       'anchor': SECTION_ANCHORS.get(group['name'], ''),
                       'fields': [leaf(f) for f in group['fields']]})
    skip = set(PHOTO_FIELDS) | {'publish_ready'}
    contacts = [leaf(f) for f in entries['site']['fields'] if f['name'] not in skip]
    return {
        'repo': os.environ.get('GITHUB_REPOSITORY', ''),
        'branch': os.environ.get('GITHUB_REF_NAME', '') or 'main',
        'brand': brand_name(site),
        'langs': list(LANGS), 'langLabels': LANG_LABEL,
        'groups': groups, 'contacts': contacts, 'page': page_schema(),
        'photos': [dict(slot) for slot in PHOTO_SLOTS],
        'banned': BANNED_PHRASES, 'required': list(REQUIRED_COPY),
        'publishReady': bool(site.get('publish_ready')),
    }


def build_admin(site):
    """Copy the owner's dashboard (admin/) next to the site and give it its generated schema."""
    source = ROOT / 'admin'
    if not source.exists():
        return False
    target = OUT / 'admin'
    shutil.copytree(source, target)
    (target / 'schema.json').write_text(json.dumps(admin_schema(site), ensure_ascii=False, indent=1), encoding='utf-8')
    return True


def main():
    site = read_json('content/site.json')
    ready = bool(site.get('publish_ready'))
    public_url = url_for_repo(site)
    posts = parse_posts()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    copy_media()
    build_home(site, posts, public_url, ready)
    build_fonts()
    build_articles(site, posts, public_url, ready)
    has_privacy = privacy_page(site, public_url, ready)
    has_admin = build_admin(site)
    (OUT / '.nojekyll').write_text('', encoding='utf-8')
    sitemap = []
    if public_url and ready:
        sitemap = [public_url] + [public_url + f'{lang}/articles/' for lang in LANGS] + ([public_url + 'privacy/'] if has_privacy else []) + [public_url + p['url'] for p in posts]
    if sitemap:
        (OUT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{esc(u)}</loc></url>' for u in sitemap) + '</urlset>', encoding='utf-8')
    robots = 'User-agent: *\n'
    if ready:
        robots += 'Allow: /\nDisallow: /admin/\n' + (f'Sitemap: {public_url}sitemap.xml\n' if sitemap else '')
    else:
        robots += 'Disallow: /\n'
    (OUT / 'robots.txt').write_text(robots, encoding='utf-8')
    print(f'Built homepage, {len(posts)} published posts, 1 archive, privacy={has_privacy}, dashboard={has_admin} -> {OUT} | indexable={ready} | URL={public_url or "local"}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'BUILD ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
