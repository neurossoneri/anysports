#!/usr/bin/env python3
"""Regression checks: copy/template/CMS consistency, static output, privacy notice, form settings, notes, safe HTML."""
import html
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
esc = lambda v: html.escape(v, quote=True)
LANGS = ('en',)
SECTION_IDS = ('hero', 'intro', 'sessions', 'change', 'about', 'contact', 'qa')   # page order, top to bottom


def load_builder():
    spec = importlib.util.spec_from_file_location('site_build', ROOT / 'scripts/build.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    return builder


def cms_keys(fields, prefix=''):
    keys = set()
    for field in fields:
        name = prefix + field['name']
        if field.get('type') == 'object':
            keys |= cms_keys(field['fields'], name + '.')
        else:
            keys.add(name)
    return keys


def check_consistency(builder):
    """Every key the template asks for has copy; CMS config and JSON agree; the site really has one language; the sections file is sound."""
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    wanted = set(re.findall(r'data-(?:i18n|i18n-aria|i18n-alt)="([^"]+)"', template))
    site = json.loads((ROOT / 'content/site.json').read_text(encoding='utf-8'))
    values = builder.collect_values(site)
    config = yaml.safe_load((ROOT / '.pages.yml').read_text(encoding='utf-8'))
    entries = {entry['name']: entry for entry in config['content']}
    assert builder.LANGS == ('en',), 'the site is English only'
    assert not (ROOT / 'content/home_ru.json').exists() and not (ROOT / 'content/home_fr.json').exists(), 'RU/FR copy must stay removed'
    assert 'home_ru' not in entries and 'home_fr' not in entries, 'RU/FR forms must stay removed from .pages.yml'
    home_en = json.loads((ROOT / 'content/home_en.json').read_text(encoding='utf-8'))
    flat = builder.flatten(home_en, 'en')
    missing = wanted - set(values['en']) - {'notes.title', 'notes.lead'}
    assert not missing, f'template keys without copy: {sorted(missing)}'
    assert cms_keys(entries['home_en']['fields']) == set(flat), '.pages.yml and content/home_en.json differ'
    unused = {k for k in flat if k not in wanted and not k.startswith(('meta.', 'notes.'))}
    assert not unused, f'copy that the template never shows: {sorted(unused)}'
    for group in ('story', 'quotes', 'sessions', 'client', 'change', 'about'):
        assert group not in home_en, f'{group} now lives in content/sections.json'
    for key in ('form_endpoint', 'inbox_endpoint', 'portrait', 'eyes_photo', 'story_photo_1', 'story_photo_4', 'privacy_address'):
        assert key in cms_keys(entries['site']['fields']), f'site settings lack {key}'
    for key in ('name_ru', 'name_fr', 'role_ru', 'role_fr'):
        assert key not in site and key not in cms_keys(entries['site']['fields']), f'old language field is back: {key}'
    assert 'privacy' in entries and (ROOT / 'content/privacy.md').exists(), 'the privacy notice must stay editable'
    # the page structure: the CMS form knows every field of every block type; the file itself is sound (without judging what the owner wrote)
    form = entries['sections']
    assert form['path'] == 'content/sections.json'
    block_form = [f for f in form['fields'][0]['fields'] if f['name'] == 'blocks'][0]['fields']
    needed = {'type'} | {f['name'] for spec in builder.BLOCK_TYPES.values() for f in spec['fields']}
    assert needed <= {f['name'] for f in block_form}, 'the CMS form lacks block fields'
    data = json.loads((ROOT / 'content/sections.json').read_text(encoding='utf-8'))
    ids = [s['id'] for s in data['sections']]
    assert len(ids) == len(set(ids)) and ids.count('contact') == 1 and ids.count('qa') == 1, 'section ids are unique; contact and Q&A are present once'
    for section in data['sections']:
        assert section['type'] in builder.SECTION_TYPES
        for block in section.get('blocks', []):
            assert block['type'] in builder.BLOCK_TYPES, f'unknown block type {block["type"]}'
    assert builder.TONE_CYCLE == ('sand', 'teal', 'dune', 'deep') and set(builder.NOTES_TONE) == set(builder.TONE_CYCLE)


def check_static(builder, destination):
    home = (destination / 'index.html').read_text(encoding='utf-8')
    css = (destination / 'assets/site.css').read_text(encoding='utf-8')
    assert '<html lang="en">' in home and 'const CMS_OVERRIDES' in home
    assert '@@' not in home and 'data-photo=' not in home, 'unresolved template marker'
    sections = builder.load_sections()
    expected = ['hero'] + [s['id'] for s in sections]
    ids = re.findall(r'<section class="band[^"]*" id="(\w+)"', home)
    assert [i for i in ids if i != 'notes'] == expected, 'the page follows the order of content/sections.json, hero first'
    assert re.findall(r'data-sec="(\d+)"', home) == [str(n) for n in range(1, len(sections) + 1)], 'sections are numbered in page order'
    for index, section in enumerate(sections):
        assert re.search(r'band-' + builder.TONE_CYCLE[index % 4] + r'[^"]*" id="' + section['id'] + '"', home), f'tone of section {index + 1}'
    assert home.index('id="qa"') < home.index('id="free"') < home.index('class="site-footer'), 'the introductory-conversation card closes the Q&A'

    # one language, no top bar, favicon stays
    assert 'id="language"' not in home and '<header class="site-header">' not in home and 'langSelect' not in home, 'language switch / top bar must stay removed'
    assert 'rel="icon"' in home and 'data:image/svg+xml' in home, 'the favicon stays'

    # hero: photograph on the left, text on the right
    assert home.index('<figure class="photo hero-photo">') < home.index('<div class="hero-quote">'), 'hero: photograph first, quotation second'
    assert re.search(r'\.hero-grid \{[^}]*grid-template-columns:minmax\(0,1fr\) minmax\(0,1fr\)', css), 'hero: the vertical photograph fills exactly half of the first screen'
    assert not re.search(r'\.hero-grid \{[^}]*grid-template-columns:1fr[;\s]', css), 'hero: two halves also on phones, no stacking'

    # soft light bands and soft transitions
    for band in ('band-deep', 'band-sand', 'band-teal', 'band-dune'):
        assert band in home, f'background band missing: {band}'
    assert 'band-frost' not in home and 'band-ice' not in home
    assert '#edf3f7' not in css and '#dae7f0' not in css, 'near-white blue must not return'
    assert '--sand:#e5dac4' in css and '--dune:#dccfb4' in css, 'warm sand tokens'
    assert not any(old in css for old in ('#e6e3d8', '#d9dfd6', '#f4f2ea', '#f2f0e7', '#e8e5da')), 'the cool near-white greys must not return'
    for pair in ('.band-deep + .band-sand::before', '.band-sand + .band-teal::before', '.band-teal + .band-dune::before',
                 '.band-dune + .band-deep::before', '.band-teal + .band-sand::before', '.site-footer.after-teal::before', '.site-footer.after-sand::before',
                 '.site-footer.after-dune::before', '.site-footer.after-deep::before'):
        assert pair in css, f'transition missing: {pair}'

    # the form, privacy links, no old promises
    assert 'By sending this form you agree' in home and home.count('href="privacy/"') >= 2, 'consent text and privacy links (form and footer)'
    assert '30 minutes' not in home.lower() and '30-minute' not in home.lower() and 'free-num' not in home, 'no 30-minute limit'
    assert re.search(r'<a class="button" href="#contact" data-i18n="free\.cta">', home), 'the card leads back to the form'

    # blocks of the page: one set of shared formats, no leftovers of the fixed layout
    assert len(re.findall(r'class="b b-', home)) >= 1 and 'class="blocks' in home
    for gone in ('class="mm"', 'plate-r', 'preface-body', 'class="s-block"', 'class="scene"', 'quote-inline'):
        assert gone not in home, f'old fixed markup is back: {gone}'
    assert '.mm' not in css and '.plate' not in css and '.scene' not in css and '.sessions' not in css, 'the butterfly and the fixed section styles stay removed'
    for needed in ('.pull {', '.b-photos', '.rail {', '.sec-grid', '.b-panel', '.aside-hand', '.finale {', '.b-dropcap'):
        assert needed in css, f'block style missing: {needed}'

    assert 'id="contact-form"' in home and 'name="_gotcha"' in home
    assert 'id="close-page"' not in home and 'farewell' not in home, 'no forced choice and no farewell dialog'
    assert 'id="to-top"' not in home and 'class="scroll-progress"' in home, 'no up button, but the progress line stays'
    assert re.search(r'<div id="top"', home)
    first = [s for s in sections if s['type'] == 'text'][0]
    assert esc(first['title']) in home or not first['title'].strip(), 'section titles are baked into the static HTML'
    assert ('id="notes"' in home) == bool(builder.parse_posts()), 'notes appear exactly when an article is published'
    for gone in ('review-grid', 'quiz', 'credential', 'mobile-cta', 'hero-floating', 'hero-tag', 'hero-hint', 'contact-booking', 'id="check"', 'id="fork"', 'id="invite"'):
        assert gone not in home, f'old template block is back: {gone}'
    assert 'prefers-reduced-motion' in home and '[hidden] { display:none!important; }' in home
    articles_css = (destination / 'assets/articles.css').read_text(encoding='utf-8')
    check_soft_controls(destination)   # rounded corners only on buttons and fields
    for phrase in ('book online', 'choose a timezone', 'choose a time', 'conversation with'):
        assert phrase not in home.lower(), f'call to action must not return: {phrase}'
    assert '@view-transition' in css and 'scroll-progress' in css
    assert (destination / 'en/articles/index.html').exists() and not (destination / 'ru').exists() and not (destination / 'fr').exists()
    assert (destination / '.nojekyll').exists()


def check_privacy(destination):
    """The Swiss FADP (art. 19) asks for: who is responsible, why, who receives the data, which countries."""
    page = (destination / 'privacy/index.html').read_text(encoding='utf-8')
    for needle in ('Privacy notice', 'Swiss Federal Act on Data Protection', 'Who is responsible', 'What data I process', 'Who receives your data',
                   'Disclosure abroad', 'Your consent', 'Your rights', 'FDPIC', '<base href="../">'):
        assert needle in page, f'privacy notice lacks: {needle}'
    assert '{{' not in page, 'unresolved placeholder in the privacy notice'
    assert 'Google Fonts' not in page and not re.search(r'<li>[^<]*Google', page), 'fonts are self-hosted: Google is not a recipient'
    assert 'stored on this website' in page, 'the notice says where the fonts come from'
    assert 'rel="icon"' in page and 'viewBox="0 0 48 48"' in page, 'privacy page keeps the logo and favicon'


def check_integrity(builder):
    """Honesty of copy, editable FAQ, accessible form."""
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    assert 'window.close' not in template, 'a web page must not pretend it can close the tab'
    assert builder.QA_SLOTS == 8 and template.count('<details name="qa" data-qa=') == 8, 'Q&A must have 8 editable slots'
    assert '<!--@@SECTIONS@@-->' in template and 'id="contact"' in template and 'id="qa"' in template, 'the template keeps the marker for the sections, the form and the Q&A'
    assert 'id="sessions"' not in template and 'id="intro"' not in template, 'text sections come from content/sections.json, not from the template'
    assert 'aria-describedby="form-status"' in template and 'data-write' not in template and 'splitWrite' not in template
    assert template.count('<h1') == 1, 'exactly one h1 (the opening quotation)'
    data = json.loads((ROOT / 'content/home_en.json').read_text(encoding='utf-8'))
    sections = json.loads((ROOT / 'content/sections.json').read_text(encoding='utf-8'))

    def strings(node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            for value in node.values():
                yield from strings(value)
        elif isinstance(node, list):
            for value in node:
                yield from strings(value)
    for lang, patterns in builder.BANNED_PHRASES.items():
        text = (json.dumps(data, ensure_ascii=False) + ' ' + ' '.join(strings(sections))).lower()
        for pattern in patterns:
            assert not re.search(pattern, text), f'{lang}: promise-like wording must not return: {pattern}'
    for dotted in builder.REQUIRED_COPY:
        group, key = dotted.split('.')
        assert data[group][key].strip(), f'{dotted} must not be blank'
    assert 'fork' not in data and 'check' not in data and 'invite' not in data and 'why' not in data, 'removed blocks must stay removed'


def check_fonts(destination):
    """Fonts live on the site: no request to Google (or any font provider), and every listed file exists."""
    pages = {name: (destination / name).read_text(encoding='utf-8') for name in ('index.html', 'assets/site.css', 'assets/articles.css', 'privacy/index.html')}
    for name, text in pages.items():
        assert 'fonts.googleapis' not in text and 'fonts.gstatic' not in text, f'{name}: fonts must not load from Google'
    home = pages['index.html']
    fonts_css = (destination / 'assets/fonts/fonts.css').read_text(encoding='utf-8')
    assert '<link rel="stylesheet" href="assets/fonts/fonts.css">' in home and 'assets/fonts/fonts.css' in pages['privacy/index.html']
    files = re.findall(r'url\(([^)]+\.woff2)\)', fonts_css)
    assert files, 'fonts.css lists no font files'
    for name in files:
        data = (destination / 'assets/fonts' / name).read_bytes()
        assert data[:4] == b'wOF2' and len(data) > 1000, f'{name} is not a WOFF2 font'
    for family in ('Inter', 'Source Serif 4', 'Caveat'):
        assert f'font-family:"{family}"' in fonts_css, f'{family} is missing from fonts.css'
    assert fonts_css.count('font-display:swap') == fonts_css.count('@font-face'), 'every font shows text at once (font-display: swap)'
    preloads = re.findall(r'<link rel="preload" href="(assets/fonts/[^"]+)"', home)
    assert preloads and all((destination / path).exists() for path in preloads), 'preloaded fonts must exist'
    assert 'preconnect' not in home, 'no connection to a third party is opened'


def check_questions(destination):
    """One question block (Q&A), warm sand."""
    home = (destination / 'index.html').read_text(encoding='utf-8')
    data = json.loads((ROOT / 'content/home_en.json').read_text(encoding='utf-8'))
    assert 'faq' not in data and 'id="faq"' not in home and 'data-faq' not in home and 'Questions and answers' not in home, 'the old question block must stay removed'
    assert home.index('id="qa"') < home.index('id="free"'), 'the free card closes the Q&A'
    css = (destination / 'assets/site.css').read_text(encoding='utf-8')
    assert '.faq' not in css, 'no leftover styles of the old block'


def check_scripts(destination):
    """Syntax check of the inline scripts (only when Node.js is available)."""
    node = shutil.which('node')
    if not node:
        return
    for page in ('index.html', 'admin/index.html'):
        text = (destination / page).read_text(encoding='utf-8')
        scripts = [s for s in re.findall(r'<script>(.*?)</script>', text, re.S) if len(s) > 400]
        assert scripts, f'{page}: no inline script found'
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'check.js'
            target.write_text(scripts[-1], encoding='utf-8')
            result = subprocess.run([node, '--check', str(target)], capture_output=True, text=True)
            assert result.returncode == 0, f'{page}: JavaScript syntax error: {result.stderr[:400]}'


def check_brand_and_dashboard(builder, destination):
    """Sport Intuitive in the title and footer; numbered photo slots; the owner's dashboard ships with the site."""
    home = (destination / 'index.html').read_text(encoding='utf-8')
    brand = builder.BRAND_DEFAULT
    assert brand in re.search(r'<title>(.*?)</title>', home).group(1), 'brand missing from <title>'
    assert brand in re.search(r'<footer.*?</footer>', home, re.S).group(0), 'brand missing from the footer'
    assert '<img data-slot="1"' in home, 'the first-screen photograph keeps its number'
    assert 'slot-badge' in home and 'photos' in home, 'the ?photos mode is missing'
    assert 'num-badge' in home and 'show-blocks' in home and 'blocks' in home, 'the ?blocks mode (section and block numbers) is missing'
    schema = json.loads((destination / 'admin/schema.json').read_text(encoding='utf-8'))
    assert [p['num'] for p in schema['photos']] == list(range(1, 8)) and schema['brand'] == brand
    assert schema['langs'] == ['en'], 'the dashboard edits one language'
    assert {s['name'] for s in schema['groups']} >= {'hero', 'contact', 'qa', 'free'} and not {s['name'] for s in schema['groups']} & {'story', 'sessions', 'about'}
    page = schema['page']
    assert {b['type'] for b in page['blockTypes']} == set(builder.BLOCK_TYPES) and page['slots'] == ['2', '3', '4', '5', '6', '7']
    assert 'banned' in schema and schema['required'] == list(builder.REQUIRED_COPY)
    admin = (destination / 'admin/index.html').read_text(encoding='utf-8')
    assert 'noindex' in admin and 'fonts.googleapis' not in admin and 'localStorage' in admin
    assert 'takeMany' in admin and 'numberFromName' in admin and 'photo-row' in admin, 'dashboard: one row per numbered photo; several files can be dropped by number'
    for needed in ('moveSection', 'moveBlock', 'addBlock', 'deleteBlock', 'slotUsage', "content/sections.json"):
        assert needed in admin, f'dashboard lacks {needed}'
    assert 'quickBar' not in admin and 'photoMap' not in admin and 'backdrop-filter' not in admin, 'dashboard: a plain list, no photo map, no blur'
    for needed in ('addSectionAt', 'deleteSection', 'undoDeleteSection', 'sectionGap', 'blockGap', 'addBlockAt', 'makeDraggable', 'pageStrip'):
        assert needed in admin, f'dashboard lacks {needed}'
    assert 'data-tab' in admin and "['requests', 'Заявки'" in admin, 'dashboard: the Requests tab'
    for needed in ('addToLibrary', 'loadLibrary', 'libraryPanel', 'openPicker', 'openCrop', 'photoSlots', 'removeFromLibrary', 'pendingKept'):
        assert needed in admin, f'dashboard lacks {needed}'
    for field in builder.PHOTO_FIELDS:
        assert any(p['field'] == field for p in schema['photos'])
    robots = (destination / 'robots.txt').read_text(encoding='utf-8')
    assert 'Disallow' in robots


def check_soft_controls(destination):
    """Rounded corners belong to buttons and fields only; photos, panels and sections stay square. No "up" button."""
    css = (destination / 'assets/site.css').read_text(encoding='utf-8')
    articles_css = (destination / 'assets/articles.css').read_text(encoding='utf-8')
    allowed = ('.button', '.icon-button', '.contact-links', 'summary::after', '.field', '.slot-badge', '.num-badge', '.skip', '.lb-close')
    for sheet in (css, articles_css):
        for selector, body in re.findall(r'([^{}]+)\{([^{}]*border-radius[^{}]*)\}', sheet):
            values = re.findall(r'border-radius\s*:\s*([^;}]+)', body)
            if all(v.strip() in ('0', '0px') for v in values):
                continue                      # resets are fine
            assert any(token in selector for token in allowed), f'rounded corners are only for buttons and fields, found on: {selector.strip()[:60]}'
    for must in ('.button { display:inline-flex', '.qa summary::after {', '.contact-links a {'):
        rule = css[css.index(must):].split('}', 1)[0]
        assert 'border-radius' in rule, f'{must} should be soft'
    for square in ('.photo {', '.quote-panel {', '.free {', '.blog-card {', '.b-panel {', '.b-photos .photo {'):
        rule = css[css.index(square):].split('}', 1)[0]
        assert 'border-radius' not in rule, f'{square} stays square'
    home = (destination / 'index.html').read_text(encoding='utf-8')
    assert 'to-top' not in home and 'to-top' not in css, 'the up button is gone'
    assert 'id="top"' in home and 'href="#top"' in home, 'the footer link still goes up'


def check_photo_numbers(destination):
    """Photo places carry numbers: empty places before launch, every photo with ?photos."""
    home = (destination / 'index.html').read_text(encoding='utf-8')
    assert 'const showAllSlots' in home and 'SETTINGS.preview' in home and "'Фото ' + image.dataset.slot" in home
    assert 'data-fallback' not in home, "an empty place is never filled with another photograph"
    assert "image.closest('.quote-panel')" in home, 'the badge of the quotation background must stay visible'
    assert '"preview":' in home, 'the page knows whether it is still a preview'


def check_smooth(destination):
    """Smooth scrolling: only cheap properties move while the page is read, and nothing heavy runs per letter or per scroll event."""
    home = (destination / 'index.html').read_text(encoding='utf-8')
    css = (destination / 'assets/site.css').read_text(encoding='utf-8')
    assert '.js .ch' not in css and '.is-written' not in css, 'no letter-by-letter writing'
    assert not re.search(r'\.finale[^{}]*\{[^}]*filter', css), 'closing statements appear without blur'
    assert 'photo-grade' not in css and 'mix-blend-mode' not in css and 'backdrop-filter' not in css, 'no full-size filters, blend modes or backdrop blur'
    assert 'optimizeLegibility' not in css, 'text-rendering stays at the browser default'
    assert '.mm' not in css and "$$('.mm')" not in home and 'is-idle' not in home, 'the butterfly and its resting logic are gone'
    assert "$$('main > section').forEach(section => rest" not in home
    assert 'window.__ready = true' in home and 'window.__ready' in home.split('<style>')[0], 'safety net: the page shows itself even if its script fails'
    assert 'scrollMax' in home, 'the progress fallback measures the page on resize, not on every scroll'
    assert 'data-fallback' not in home, 'no place borrows the photograph of another place'
    assert 'preload" href="assets/fonts/caveat-normal-latin.woff2"' in home, 'the handwriting font is preloaded'


def check_inbox(builder, destination):
    """The requests inbox: script file, dashboard tab, form wiring."""
    script = (destination / 'admin/inbox-script.txt').read_text(encoding='utf-8')
    for needle in ('function doPost', 'ADMIN_KEY', "'submit'", 'LockService', 'setNumberFormat'):
        assert needle in script, f'inbox script lacks {needle}'
    admin = (destination / 'admin/index.html').read_text(encoding='utf-8')
    for needle in ('panelRequests', 'inboxCall', 'inbox-script.txt', 'csvOf', 'panelPhotos'):
        assert needle in admin, f'dashboard lacks {needle}'
    home = (destination / 'index.html').read_text(encoding='utf-8')
    assert "action:'submit'" in home and 'Promise.allSettled' in home, 'the form must also write to the inbox'
    node = shutil.which('node')
    if node:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'inbox.js'
            target.write_text(script, encoding='utf-8')
            result = subprocess.run([node, '--check', str(target)], capture_output=True, text=True)
            assert result.returncode == 0, f'inbox script syntax error: {result.stderr[:400]}'
    assert builder.inbox_endpoint({'inbox_endpoint': 'https://script.google.com/macros/s/AKfy_1-x/exec'}).endswith('/exec')
    assert builder.inbox_endpoint_quiet({'inbox_endpoint': 'https://evil.example/macros/s/x/exec'}) == ''
    assert builder.inbox_endpoint_quiet({'inbox_endpoint': 'http://script.google.com/macros/s/x/exec'}) == ''


def check_page_polish(destination):
    """Guards for the small fixes: <base> before the font links, a header that fits narrow phones, a current year, no dead CSS."""
    import datetime
    privacy = (destination / 'privacy/index.html').read_text(encoding='utf-8')
    assert privacy.index('<base ') < privacy.index('assets/fonts/'), 'the <base> tag must precede the font links, or the fonts 404 on inner pages'
    articles_css = (destination / 'assets/articles.css').read_text(encoding='utf-8')
    for rule in ('text-overflow:ellipsis', 'white-space:nowrap', '@media (max-width:420px)'):
        assert rule in articles_css, f'the article header keeps to one line on narrow phones ({rule})'
    home = (destination / 'index.html').read_text(encoding='utf-8')
    assert f'<span id="year">{datetime.date.today().year}</span>' in home, 'the footer year is filled in at build time'
    assert '.blog-empty' not in home and (destination / 'assets/site.css').read_text(encoding='utf-8').count('.brand-name {') == 1, 'no dead or repeated CSS'


def write_post(work, lang, body, name='published'):
    metadata = {'title': f'Example {lang}', 'slug': 'sample', 'lang': lang, 'published': True, 'date': '2026-10-13',
                'category': 'Sport', 'summary': f'Summary {lang}', 'cover': 'media/test-cover.webp'}
    (work / 'content/posts' / f'{name}-{lang}.md').write_text('---\n' + yaml.safe_dump(metadata, allow_unicode=True) + '---\n' + body, encoding='utf-8')


def build_fixture(builder, mutate, posts):
    """Build a throw-away copy of the project and return its output directory (kept alive by the caller)."""
    temporary = tempfile.TemporaryDirectory(prefix='site-build-test-')
    work = Path(temporary.name)
    shutil.copytree(ROOT / 'templates', work / 'templates')
    shutil.copytree(ROOT / 'content', work / 'content')
    shutil.copytree(ROOT / 'admin', work / 'admin')
    shutil.copytree(ROOT / 'fonts', work / 'fonts')
    shutil.copy(ROOT / '.pages.yml', work / '.pages.yml')
    (work / 'media').mkdir()
    (work / 'media/test-cover.webp').write_bytes(b'fake image bytes')
    (work / 'content/posts').mkdir(exist_ok=True)
    site = json.loads((work / 'content/site.json').read_text(encoding='utf-8'))
    mutate(work, site)
    (work / 'content/site.json').write_text(json.dumps(site, ensure_ascii=False), encoding='utf-8')
    for path in (work / 'content/posts').glob('*.md'):
        path.unlink()
    if posts:
        for lang in LANGS:
            write_post(work, lang, '\n# Testing heading\n\nRich **text** with [link](https://example.org).\n\n<script>alert(1)</script>\n')
    previous = os.environ.get('GITHUB_REPOSITORY')
    os.environ['GITHUB_REPOSITORY'] = 'demo/athlete-support'
    builder.ROOT, builder.OUT = work, work / '_site'
    try:
        builder.main()
    finally:
        if previous is None:
            del os.environ['GITHUB_REPOSITORY']
        else:
            os.environ['GITHUB_REPOSITORY'] = previous
    return temporary, work


def sample_sections(builder):
    """A fixed page for the checks: they never depend on what the owner has typed into the real content/sections.json."""
    def text(body, heading='', look='plain', note=''):
        return {'type': 'text', 'heading': heading, 'body': body, 'note': note, 'look': look}

    def photos(s1, s2='', place='inline', caption='', alt=''):
        return {'type': 'photos', 's1': s1, 's2': s2, 's3': '', 'place': place, 'caption': caption, 'alt': alt}
    themes = builder.default_block('themes')
    themes.update({'title': 'Sample themes', 't1': 'Theme one', 'd1': 'Detail one', 'finalTitle': 'Sample closing', 'finalText': 'Closing text.'})
    return {'sections': [
        {'id': 'intro', 'type': 'text', 'title': 'Sample intro', 'layout': 'rail-right', 'blocks': [
            text('First paragraph.'), {'type': 'quote', 'text': 'A short quote.', 'size': 'auto'},
            {'type': 'aside', 'text': 'Set\naside', 'look': 'panel', 'photo': '2'}]},
        {'id': 'sessions', 'type': 'text', 'title': 'Sample sessions', 'layout': 'rail-left', 'blocks': [
            photos('3', place='side', alt='Side photo'), text('Lead text.', look='lead'), text('Body text.', 'Sub heading'),
            text('Panel body.', 'Panel heading', 'panel', 'Small note'), themes]},
        {'id': 'change', 'type': 'text', 'title': 'Sample change', 'layout': 'rail-left', 'blocks': [
            {'type': 'aside', 'text': 'Hand\nwritten', 'look': 'hand', 'photo': ''}, text('Scene text.', 'Scene heading')]},
        {'id': 'about', 'type': 'text', 'title': 'Sample story', 'layout': 'centered', 'blocks': [
            text('Story lead.', look='lead'), text('Part one A.\n\nPart one B.', look='dropcap'),
            {'type': 'quote', 'text': 'A long highlighted phrase that is clearly longer than seventy characters, so it is set smaller.', 'size': 'auto'},
            photos('4', '5', caption='From the FIFA archive', alt='Archive photographs'), text('Part two.'), photos('6', '7', alt='Recent photographs'),
            text('Closing line.', look='hand')]},
        {'id': 'contact', 'type': 'contact'}, {'id': 'qa', 'type': 'qa'}]}


def section_html(home, sid):
    return re.search(r'<section class="band[^"]*" id="' + sid + r'".*?</section>', home, re.S).group(0)


def check_sections(builder):
    """Sections and blocks: order and numbers, the story layout, side columns, photos on the live site, reordering and defensive loading."""
    def with_sections(data, **site_extra):
        def mutate(work, site):
            site.update(site_extra)
            (work / 'content/sections.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return mutate

    # preview: every numbered photo place is drawn, the story has its two photo pairs
    temporary, work = build_fixture(builder, with_sections(sample_sections(builder), portrait='media/test-cover.webp', quote_photo='', eyes_photo='', story_photo_1='', story_photo_2='', story_photo_3='', story_photo_4='', publish_ready=False), posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        ids = re.findall(r'<section class="band[^"]*" id="(\w+)"', home)
        assert ids == ['hero', 'intro', 'sessions', 'change', 'about', 'contact', 'qa'], ids
        assert re.findall(r'data-sec="(\d+)"', home) == ['1', '2', '3', '4', '5', '6'], 'sections are numbered in page order'
        for index, tone in enumerate(('sand', 'teal', 'dune', 'deep', 'sand', 'teal'), 0):
            assert re.search(r'<section class="band band-' + tone + r'[^"]*" id="\w+"[^>]*data-sec="' + str(index + 1) + '"', home), f'section {index + 1} should be {tone}'
        assert sorted({int(n) for n in re.findall(r'data-slot="(\d+)"', home)}) == list(range(1, 8)), 'before launch every numbered place is drawn'
        about = section_html(home, 'about')
        assert re.findall(r'<(?:div|blockquote) class="b (b-[a-z]+)', about) == ['b-lead', 'b-text', 'b-quote', 'b-photos', 'b-text', 'b-photos', 'b-hand'], 'story: lead, part one, phrase, archive photos, part two, recent photos, closing line'
        assert about.count('<figure class="photo frame">') == 4 and 'From the FIFA archive' in about and 'class="b-cap"' in about
        assert 'b-dropcap' in about and about.count('<p>Part one') == 2, 'a text block splits paragraphs at blank lines'
        assert 'pull pull-long' in about, 'a long phrase is set smaller'
        assert 'sec-centered' in about and 'sec-grid' not in about and 'data-blk="4.4"' in about, 'blocks carry their number'
        intro, sessions, change = section_html(home, 'intro'), section_html(home, 'sessions'), section_html(home, 'change')
        assert 'sec-rail-right' in intro and intro.index('class="blocks"') < intro.index('class="rail"'), 'rail on the right'
        assert 'sec-rail-left' in sessions and sessions.index('class="rail"') < sessions.index('class="blocks"'), 'rail on the left'
        assert 'quote-panel' in intro and 'class="photo quote-bg"' in intro and 'b-quote pull"' in intro, 'statement set aside and quote in the text are two different things'
        assert 'aside-hand' in change and 'finale-hand' in about and 'data-write' not in home and 'quote-stroke' not in home and 'data-finale' not in home, 'statements are still: no typing, no drawn line, no reveal'
        assert 'theme-grid' in sessions and sessions.index('class="b b-themes themes"') > sessions.index('class="blocks"'), 'themes take the full width after the columns'
        assert 'b-panel' in sessions and 'Small note' in sessions and 'b-lead' in sessions
        assert 'class="mm"' not in home and 'mm1' not in home, 'the butterfly stays removed'

    # live site: empty photo places disappear, a missing side photo leaves one column
    temporary, work = build_fixture(builder, with_sections(sample_sections(builder), portrait='media/test-cover.webp', story_photo_2='media/test-cover.webp', quote_photo='', eyes_photo='', story_photo_1='', story_photo_3='', story_photo_4='', publish_ready=True), posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        sessions, about = section_html(home, 'sessions'), section_html(home, 'about')
        assert '<img data-slot="3"' not in home and '<img data-slot="6"' not in home and '<img data-slot="2"' not in home, 'live: places without a photograph are left out'
        assert 'sec-column' in sessions and 'class="rail"' not in sessions, 'no side photo: one column'
        assert about.count('class="b b-photos') == 1 and 'b-photos n1' in about and '<img data-slot="5"' in about and '<img data-slot="4"' not in about
        assert 'class="photo quote-bg"' not in home and 'class="b b-aside quote-panel"' in home, 'the statement stays, only its empty photograph goes'
        assert home.count('src="media/test-cover.webp"') == 2, 'hero and photo 5 only'
        assert '<footer class="site-footer after-teal"' in home, 'the footer follows the tone of the last section'

    # reordering, hostile and broken content
    broken = {'sections': [
        {'id': 'qa', 'type': 'qa'},
        {'id': 'about', 'type': 'text', 'title': '</script><b>x</b>', 'layout': 'nonsense', 'blocks': [
            {'type': 'text', 'heading': '', 'body': 'Fine <i>text</i>', 'note': '', 'look': 'nonsense'}, {'type': 'unknown', 'text': 'skipped'}, 'not a block',
            {'type': 'photos', 's1': '99', 's2': '', 's3': '', 'place': 'inline', 'caption': '', 'alt': ''}]},
        {'id': 'contact', 'type': 'contact'},
        {'id': 'intro', 'type': 'text', 'title': 'Last', 'layout': 'column', 'blocks': []}]}
    temporary, work = build_fixture(builder, with_sections(broken), posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        assert re.findall(r'<section class="band[^"]*" id="(\w+)"', home) == ['hero', 'qa', 'about', 'contact', 'intro'], 'the page follows the order of the list'
        for index, tone in enumerate(('sand', 'teal', 'dune', 'deep')):
            assert f'band-{tone}' in re.findall(r'<section class="band[^"]*" id="\w+"[^>]*data-sec="' + str(index + 1) + '"', home)[0], 'tones follow the position, not the content'
        assert '<footer class="site-footer after-deep"' in home
        assert '</script><b>x</b>' not in home and '&lt;/script&gt;' in home and '<i>text</i>' not in home and 'skipped' not in home
        assert 'sec-column' in section_html(home, 'about'), 'an unknown layout falls back'
        assert 'data-slot="99"' not in home

    def without_fixed(work, site):
        (work / 'content/sections.json').write_text(json.dumps({'sections': [{'id': 'intro', 'type': 'text', 'title': 'Only', 'layout': 'column', 'blocks': []}]}), encoding='utf-8')
    temporary, work = build_fixture(builder, without_fixed, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        assert re.findall(r'<section class="band[^"]*" id="(\w+)"', home) == ['hero', 'intro', 'contact', 'qa'], 'the form and the questions come back if the list lost them'


def check_text_system(builder):
    """Three kinds of text defined once; statements are still; no rules in the running text; an empty section is not drawn."""
    data = {'sections': [
        {'id': 'one', 'type': 'text', 'title': 'One', 'layout': 'column', 'blocks': [
            {'type': 'text', 'heading': 'A heading', 'body': 'Body.', 'note': '', 'look': 'plain'},
            {'type': 'quote', 'text': 'Quote.', 'size': 'auto'},
            {'type': 'aside', 'text': 'Quiet statement', 'look': 'quiet', 'photo': ''}]},
        {'id': 'empty-one', 'type': 'text', 'title': '', 'layout': 'column', 'blocks': [{'type': 'text', 'heading': '', 'body': '', 'note': '', 'look': 'plain'}]},
        {'id': 'two', 'type': 'text', 'title': 'Two', 'layout': 'column', 'blocks': [{'type': 'aside', 'text': 'Written by hand', 'look': 'hand', 'photo': ''}]},
        {'id': 'contact', 'type': 'contact'}, {'id': 'qa', 'type': 'qa'}]}

    def mutate(work, site):
        (work / 'content/sections.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, mutate, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        css = (work / '_site/assets/site.css').read_text(encoding='utf-8')
        assert re.findall(r'<section class="band[^"]*" id="([\w-]+)"', home) == ['hero', 'one', 'two', 'contact', 'qa'], 'a section with nothing in it is not drawn'
        assert re.findall(r'data-sec="(\d+)"', home) == ['1', '3', '4', '5'], 'numbers still count the hidden empty section, so they match the dashboard'
        assert 'class="b b-aside aside-quiet"' in home and '<p class="statement">Quiet statement</p>' in home and 'aside-hand' in home
        assert 'data-write' not in home and 'quote-stroke' not in home and 'data-finale' not in home, 'nothing is typed, drawn or revealed'
        assert 'data-fade' not in re.search(r'<blockquote class="b b-quote[^>]*>', home).group(0), 'a quotation is visible at once'
        rule = lambda selector: re.search(re.escape(selector) + r' \{([^}]*)\}', css).group(1)
        for selector in ('.pull', '.pull-long', '.finale p', '.hero-q2', '.sec-centered .b-lead', '.statement'):
            assert 'italic' not in rule(selector), f'{selector}: no italics'
        assert 'border' not in rule('.pull') and 'border' not in rule('.b-text.has-h') and 'border' not in rule('.themes'), 'no rules around quotations, subheadings or the list of themes'
        assert 'border-left' not in rule('.theme'), 'the themes are not cards'
        root = re.search(r':root \{([^}]*)\}', css).group(1)
        for token in ('--type-body', '--type-quote', '--type-statement', '--type-hand'):
            assert token in root, f'text style {token} is defined centrally'
        assert 'var(--type-quote)' in rule('.pull') and 'var(--type-statement)' in rule('.statement') and 'var(--type-hand)' in rule('.quote-text')
    assert builder.default_block('aside')['look'] == 'quiet', 'a new statement is the quiet one; handwriting is a choice'


def check_photo_tools(builder):
    """Compositions, crops, library files, the optional larger view; the dashboard has the library, picker and crop tools."""
    def photos(**kw):
        block = {'type': 'photos', 's1': '', 's2': '', 's3': '', 'place': 'inline', 'caption': '', 'alt': 'Alt', 'f1': '', 'f2': '', 'f3': '', 'comp': 'auto', 'zoom': ''}
        block.update(kw)
        return block
    cover = 'media/test-cover.webp'
    data = {'sections': [
        {'id': 'one', 'type': 'text', 'title': 'One', 'layout': 'column', 'blocks': [
            photos(s1=cover, s2=cover, comp='lead-small', f1='30.5,40,1.5', f2='200,5,9', zoom='yes'),
            photos(s1=cover, s2=cover, comp='single'),
            photos(s1='media/does-not-exist.webp'),
            photos(s1=cover, s2=cover, s3=cover, comp='trio'),
            photos(s1=cover, comp='wide', f1='50,30,1')]},
        {'id': 'contact', 'type': 'contact'}, {'id': 'qa', 'type': 'qa'}]}

    def mutate(work, site):
        site.update({'portrait': cover, 'publish_ready': True})
        (work / 'content/sections.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, mutate, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        css = (work / '_site/assets/site.css').read_text(encoding='utf-8')
        blocks = re.findall(r'<div class="b b-photos[^>]*>(?:<figure.*?</figure>)+(?:<p class="b-cap">.*?</p>)?</div>', home, re.S)
        assert len(blocks) == 4, 'the block whose file is missing is left out, the others stay'
        lead, single, trio, wide = blocks
        assert 'data-comp="lead-small"' in lead and 'data-lightbox' in lead and 'data-lightbox' not in single
        assert 'style="--ar:4/5;--ar-m:4/5"' in lead and 'style="--ar:1/1;--ar-m:1/1"' in lead, 'every frame has its own shape'
        assert 'object-position:30.5% 40%;transform:scale(1.5);transform-origin:30.5% 40%' in lead, 'the crop is set on the photograph'
        assert lead.count('transform') == 2 and 'scale(9)' not in lead, 'an impossible crop is ignored'
        assert 'data-slot' not in lead, 'a library file is not a numbered place'
        assert single.count('<figure') == 1 and 'data-comp="single"' in single, 'a single frame shows one photograph even if more are chosen'
        assert trio.count('<figure') == 3 and 'data-comp="trio"' in trio
        assert 'style="--ar:16/9;--ar-m:4/3"' in wide and 'transform' not in wide, 'zoom 1 needs no transform'
        for needle in ('.b-photos[data-comp="lead-small"]', '.zoom-btn', '#lightbox', 'photo-tools-v1'):
            assert needle in css, f'site style lacks {needle}'
        assert 'lightbox' in home and 'showModal' in home
    schema = builder.page_schema()
    assert set(schema['frames']) == {name for name, _ in builder.COMPS} and schema['comps'][0][0] == 'auto'
    assert all(len(frames) >= 1 and all(len(f) == 3 for f in frames) for frames in schema['frames'].values())
    assert builder.clean_crop('10,20,1.5') == '10,20,1.5' and builder.clean_crop('101,0,1') == '' and builder.clean_crop('5,5,0.5') == '' and builder.clean_crop('x') == ''


def check_story_and_closing(builder):
    """The closing statement is a quiet narrow column; compositions get room around them."""
    data = {'sections': [
        {'id': 'one', 'type': 'text', 'title': 'One', 'layout': 'centered', 'blocks': [
            {'type': 'text', 'heading': '', 'body': 'Body.', 'note': '', 'look': 'plain'},
            {'type': 'aside', 'text': 'The last thought', 'look': 'closing', 'photo': ''}]},
        {'id': 'contact', 'type': 'contact'}, {'id': 'qa', 'type': 'qa'}]}

    def mutate(work, site):
        (work / 'content/sections.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, mutate, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        css = (work / '_site/assets/site.css').read_text(encoding='utf-8')
        assert '<div class="b b-aside aside-closing"' in home and '<p class="statement">The last thought</p>' in home
        assert 'data-write' not in home and 'data-fade' not in re.search(r'<div class="b b-aside aside-closing"[^>]*>', home).group(0), 'the ending is visible at once'
        rule = re.search(r'\.aside-closing \.statement \{([^}]*)\}', css).group(1)
        assert 'italic' not in rule and 'background' not in rule and 'border' not in rule, 'the ending is typography and space only'
        assert 'about-story-v1' in css
    assert dict(builder.ASIDE_LOOKS).get('closing'), 'the dashboard offers the closing statement'


def main():
    builder = load_builder()
    check_consistency(builder)
    check_integrity(builder)
    check_static(builder, ROOT / '_site')
    check_privacy(ROOT / '_site')
    check_brand_and_dashboard(builder, ROOT / '_site')
    check_fonts(ROOT / '_site')
    check_questions(ROOT / '_site')
    check_scripts(ROOT / '_site')
    check_photo_numbers(ROOT / '_site')
    check_smooth(ROOT / '_site')
    check_inbox(builder, ROOT / '_site')
    check_page_polish(ROOT / '_site')
    check_sections(builder)
    check_text_system(builder)
    check_photo_tools(builder)
    check_story_and_closing(builder)

    # Full-featured build: photos, contacts, form, published notes, a blank FAQ slot and hostile copy.
    def full(work, site):
        site.update({'name_en': 'Test Person', 'email': 'hello@example.com', 'privacy_address': 'Example Street 1, 8000 Zürich, Switzerland',
                     'portrait': 'media/test-cover.webp', 'story_photo_2': 'media/test-cover.webp', 'eyes_photo': '', 'quote_photo': '',
                     'story_photo_1': '', 'story_photo_3': '', 'story_photo_4': '', 'form_endpoint': 'https://formspree.io/f/abc123', 'inbox_endpoint': 'https://script.google.com/macros/s/AKfycbTEST_123/exec', 'publish_ready': True})
        data = json.loads((work / 'content/home_en.json').read_text(encoding='utf-8'))
        data['qa']['q3'] = ''
        (work / 'content/home_en.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        (work / 'content/sections.json').write_text(json.dumps(sample_sections(builder), ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, full, posts=True)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        article = (work / '_site/en/articles/sample/index.html').read_text(encoding='utf-8')
        privacy = (work / '_site/privacy/index.html').read_text(encoding='utf-8')
        assert 'Test Person' in home and 'hello@example.com' in home and 'Sport Intuitive' in home
        assert 'Disallow: /admin/' in (work / '_site/robots.txt').read_text(encoding='utf-8')
        assert home.count('src="media/test-cover.webp"') == 3, 'hero, photo 5 and one note cover: no place borrows another photograph'
        assert '<figure class="photo hero-photo">' in home and '<img data-slot="5"' in home and '<img data-slot="3"' not in home, 'live site: a place without a photograph is left out'
        assert '"formEndpoint":"https://formspree.io/f/abc123"' in home
        assert '"inboxEndpoint":"https://script.google.com/macros/s/AKfycbTEST_123/exec"' in home and '"preview":false' in home
        assert 'Google Sheets' in privacy and 'formspree.io' in privacy, 'privacy notice names the form service and the spreadsheet'
        assert 'id="notes"' in home and 'CMS_VISIBLE_POSTS = {"en":1}' in home
        assert '<article class="blog-card" data-post-lang="en">' in home
        assert '<footer class="site-footer after-sand"' in home, 'with notes the footer fades from the notes band (sand after a teal section)'
        assert '<details name="qa" data-qa="3" hidden>' in home and '<details name="qa" data-qa="2">' in home
        assert 'https://demo.github.io/athlete-support/' in home and 'index,follow' in home
        assert 'application/ld+json' in home and 'og:image' in home
        assert 'Testing heading' in article and '<script>alert(1)</script>' not in article
        assert '<base href="../../../">' in article and 'rel="icon"' in article and 'scroll-progress' in article and 'viewBox="0 0 48 48"' in article
        assert 'https://demo.github.io/athlete-support/en/articles/sample/' in article
        assert 'assets/fonts/fonts.css' in article and 'fonts.googleapis' not in article and (work / '_site/assets/fonts/fonts.css').exists(), 'article pages use the self-hosted fonts'
        assert 'href="en/articles/sample/#content"' in article, 'with <base>, the skip link must point back at the article itself'
        assert article.index('<base ') < article.index('assets/fonts/'), 'the <base> tag must precede the font links in articles too'
        assert 'Test Person' in privacy and 'hello@example.com' in privacy and 'Example Street 1' in privacy and 'formspree.io' in privacy
        assert 'https://demo.github.io/athlete-support/privacy/' in privacy, 'privacy page has its canonical address'
        sitemap = (work / '_site/sitemap.xml').read_text(encoding='utf-8')
        assert 'privacy/' in sitemap and (work / '_site/media/test-cover.webp').exists()
        assert 'Disallow: /\n' not in (work / '_site/robots.txt').read_text(encoding='utf-8'), 'an indexable site must not block everything'

    # Defensive build: an insecure form endpoint is dropped, nothing is published, no notes appear.
    def careless(work, site):
        site.update({'form_endpoint': 'http://insecure.example/submit', 'inbox_endpoint': 'https://evil.example/macros/s/x/exec', 'publish_ready': False,
                     'portrait': '', 'quote_photo': '', 'eyes_photo': '', 'story_photo_1': '', 'story_photo_2': '', 'story_photo_3': '', 'story_photo_4': ''})
        (work / 'content/sections.json').write_text(json.dumps(sample_sections(builder), ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, careless, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        privacy = (work / '_site/privacy/index.html').read_text(encoding='utf-8')
        assert '"formEndpoint":""' in home and 'insecure.example' not in home and 'insecure.example' not in privacy
        assert '"inboxEndpoint":""' in home and 'evil.example' not in home and 'Google Sheets' not in privacy and '"preview":true' in home
        assert 'id="notes"' not in home and 'noindex,nofollow' in home and '<footer class="site-footer after-teal"' in home
        assert 'through the contact form on this website' in privacy and 'opens your own email program' in privacy
        assert '<img data-slot="3"' in home and ' hidden>' not in re.search(r'<figure class="photo hero-photo"[^>]*>', home).group(0), 'before launch every place stays visible'
        assert 'Disallow: /' in (work / '_site/robots.txt').read_text(encoding='utf-8')
    # Smaller copies of the photographs (needs Pillow, which the workflow installs).
    if importlib.util.find_spec('PIL'):
        def photographed(work, site):
            from PIL import Image
            Image.new('RGB', (2400, 3000), (40, 90, 140)).save(work / 'media/big.jpg', quality=85)
            Image.new('RGB', (500, 600), (90, 40, 140)).save(work / 'media/small.jpg', quality=85)
            site.update({'portrait': 'media/big.jpg', 'story_photo_1': 'media/small.jpg', 'quote_photo': '', 'eyes_photo': '', 'story_photo_2': '', 'story_photo_3': '', 'story_photo_4': '', 'publish_ready': False})
            (work / 'content/sections.json').write_text(json.dumps(sample_sections(builder), ensure_ascii=False), encoding='utf-8')
        temporary, work = build_fixture(builder, photographed, posts=False)
        with temporary:
            home = (work / '_site/index.html').read_text(encoding='utf-8')
            expected = ', '.join(f'media/opt/media-big-jpg-{w}.webp {w}w' for w in (640, 1080, 1600)) + ', media/big.jpg 2400w'
            assert f'srcset="{expected}" sizes="50vw"' in home, 'the hero photograph offers smaller copies'
            for width in (640, 1080, 1600):
                assert (work / f'_site/media/opt/media-big-jpg-{width}.webp').stat().st_size > 0
            assert (work / '_site/media/big.jpg').exists(), 'the original stays'
            assert 'media-small' not in home and 'src="media/small.jpg"' in home, 'a small photograph needs no copies (photo 4 sits in the story)'
    print('OK: sections and blocks (order, numbers, tones, story layout, side column, live photo places, broken content), smooth scrolling rules, own photo for every number, smaller photo copies, plain dashboard, English-only copy and CMS in sync, warm sand bands and transitions, self-hosted fonts, one Q&A block, photo-left hero, soft floating buttons, numbered photo places, requests inbox, privacy notice, photos, form, notes, safety and publish mode')


if __name__ == '__main__':
    main()
