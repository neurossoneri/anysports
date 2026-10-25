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
    """Every key the template asks for has copy; CMS config and JSON agree; the site really has one language."""
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    wanted = set(re.findall(r'data-(?:i18n|i18n-aria|i18n-alt)="([^"]+)"', template))
    site = json.loads((ROOT / 'content/site.json').read_text(encoding='utf-8'))
    values = builder.collect_values(site)
    config = yaml.safe_load((ROOT / '.pages.yml').read_text(encoding='utf-8'))
    entries = {entry['name']: entry for entry in config['content']}
    assert builder.LANGS == ('en',), 'the site is English only'
    assert not (ROOT / 'content/home_ru.json').exists() and not (ROOT / 'content/home_fr.json').exists(), 'RU/FR copy must stay removed'
    assert 'home_ru' not in entries and 'home_fr' not in entries, 'RU/FR forms must stay removed from .pages.yml'
    flat = builder.flatten(json.loads((ROOT / 'content/home_en.json').read_text(encoding='utf-8')), 'en')
    missing = wanted - set(values['en']) - {'notes.title', 'notes.lead'}
    assert not missing, f'template keys without copy: {sorted(missing)}'
    assert cms_keys(entries['home_en']['fields']) == set(flat), '.pages.yml and content/home_en.json differ'
    unused = {k for k in flat if k not in wanted and not k.startswith(('meta.', 'notes.'))}
    assert not unused, f'copy that the template never shows: {sorted(unused)}'
    for key in ('form_endpoint', 'inbox_endpoint', 'portrait', 'eyes_photo', 'story_photo_1', 'story_photo_4', 'privacy_address'):
        assert key in cms_keys(entries['site']['fields']), f'site settings lack {key}'
    for key in ('name_ru', 'name_fr', 'role_ru', 'role_fr'):
        assert key not in site and key not in cms_keys(entries['site']['fields']), f'old language field is back: {key}'
    assert 'privacy' in entries and (ROOT / 'content/privacy.md').exists(), 'the privacy notice must stay editable'


def check_static(builder, destination):
    home = (destination / 'index.html').read_text(encoding='utf-8')
    css = (destination / 'assets/site.css').read_text(encoding='utf-8')
    assert '<html lang="en">' in home and 'const CMS_OVERRIDES' in home
    assert '@@' not in home and 'data-photo=' not in home, 'unresolved template marker'
    for section in SECTION_IDS:
        assert f'id="{section}"' in home, f'section missing: {section}'
    positions = [home.index(f'id="{section}"') for section in SECTION_IDS]
    assert positions == sorted(positions), 'sections are out of the agreed order'
    assert home.index('id="qa"') < home.index('id="free"') < home.index('class="site-footer'), 'the introductory-conversation card closes the Q&A'
    assert home.index('id="contact"') > home.index('id="about"') and home.index('id="contact"') < home.index('id="qa"'), 'the form goes right after "My story"'

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
                 '.band-dune + .band-deep::before', '.band-teal + .band-sand::before', '.site-footer.after-teal::before', '.site-footer.after-sand::before'):
        assert pair in css, f'transition missing: {pair}'

    # copy changes
    assert 'Intuition speaks differently to everyone' in home and 'It speaks differently' not in home
    assert 'Leave your message' in home and '(optional)' not in home and 'sensitive information here' not in home
    assert 'By sending this form you agree' in home and home.count('href="privacy/"') >= 2, 'consent text and privacy links (form and footer)'
    assert '30 minutes' not in home.lower() and '30-minute' not in home.lower() and 'free-num' not in home, 'no 30-minute limit'
    assert 'An introductory conversation costs you nothing' in home
    assert re.search(r'<a class="button" href="#contact" data-i18n="free\.cta">', home), 'the card leads back to the form'
    assert re.search(r'<p class="mid"[^>]*data-i18n="story\.p1"', home) and re.search(r'<p class="mid"[^>]*data-i18n="story\.p5"', home), 'intro lines use the main text style'

    # highlighted phrases, in the text where they belong
    assert len(re.findall(r'class="pull[ "]', home)) >= 5, 'key phrases are highlighted in every block'
    order = [home.index(f'data-i18n="{k}"') for k in ('sessions.p1', 'quotes.b', 'sessions.p2', 'sessions.bring', 'sessions.p3')]
    assert order == sorted(order), 'quote B follows the first sessions text, "bring" follows "Where we begin"'
    assert home.index('data-i18n="change.s2Text"') < home.index('data-i18n="change.s2Pull"')
    assert home.count('<blockquote class="quote-text" data-write ') == 2, 'two handwritten quotations (A and C)'

    # closing statements
    finales = re.findall(r'<div class="finale[^"]*" data-finale>', home)
    assert len(finales) == 2, 'two centred closing statements'
    assert home.index('data-i18n="client.l6t"') < home.index('data-i18n="client.l7"') < home.index('id="change"')
    assert 'data-write data-i18n="about.note"' in home

    # my story: one flowing preface
    assert 'about.c1Title' not in home and 'mosaic' not in home and 'class="chap dropcap"' in home
    assert home.count('class="photo plate plate-') == 4, 'four numbered photographs inside the story'

    assert 'id="contact-form"' in home and 'name="_gotcha"' in home
    assert 'id="close-page"' not in home and 'farewell' not in home, 'no forced choice and no farewell dialog'
    assert 'id="to-top"' not in home and 'class="scroll-progress"' in home, 'no up button, but the progress line stays'
    assert re.search(r'<div id="top"', home)
    en = json.loads((ROOT / 'content/home_en.json').read_text(encoding='utf-8'))
    assert esc(en['story']['title']) in home and esc(en['quotes']['a'].split('\n')[0]) in home, 'English copy must be baked into the static HTML'
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
    assert 'quote_photo' in builder.PHOTO_FIELDS and 'id="sessions"' in template
    assert 'aria-describedby="form-status"' in template and 'data-write' in template
    assert template.count('<h1') == 1, 'exactly one h1 (the opening quotation)'
    for lang, patterns in builder.BANNED_PHRASES.items():
        text = json.dumps(json.loads((ROOT / f'content/home_{lang}.json').read_text(encoding='utf-8')), ensure_ascii=False).lower()
        for pattern in patterns:
            assert not re.search(pattern, text), f'{lang}: promise-like wording must not return: {pattern}'
    data = json.loads((ROOT / 'content/home_en.json').read_text(encoding='utf-8'))
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


def check_about_and_questions(destination):
    """One question block (Q&A), the new story text in the preface layout, warm sand."""
    home = (destination / 'index.html').read_text(encoding='utf-8')
    data = json.loads((ROOT / 'content/home_en.json').read_text(encoding='utf-8'))
    assert 'faq' not in data and 'id="faq"' not in home and 'data-faq' not in home and 'Questions and answers' not in home, 'the old question block must stay removed'
    keys = ('about.lead', 'about.c1Text', 'about.c2Text', 'about.pull', 'about.c3Text', 'about.c4Text', 'about.c5Text', 'about.note')
    order = [home.index(f'data-i18n="{key}"') for key in keys]
    assert order == sorted(order), 'the story keeps its order: lead, four paragraphs with photos, highlighted phrase, closing line'
    assert re.search(r'<p class="pull pull-long"[^>]*data-i18n="about\.pull"', home), 'the highlighted phrase uses the shared format'
    assert data['about']['lead'].startswith('Although I am not an athlete myself') and 'FIFA' in data['about']['c2Text']
    assert data['about']['note'].startswith('Guiding others'), 'the closing line is the last sentence of the new text'
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
    slots = sorted(int(n) for n in re.findall(r'data-slot="(\d+)"', home))
    assert slots == list(range(1, 8)), f'photo slots must be numbered 1..7, got {slots}'
    assert 'slot-badge' in home and 'photos' in home, 'the ?photos mode is missing'
    schema = json.loads((destination / 'admin/schema.json').read_text(encoding='utf-8'))
    assert [p['num'] for p in schema['photos']] == list(range(1, 8)) and schema['brand'] == brand
    assert schema['langs'] == ['en'], 'the dashboard edits one language'
    assert {s['name'] for s in schema['sections']} >= {'hero', 'story', 'sessions', 'about', 'qa'}
    assert 'banned' in schema and schema['required'] == list(builder.REQUIRED_COPY)
    admin = (destination / 'admin/index.html').read_text(encoding='utf-8')
    assert 'noindex' in admin and 'fonts.googleapis' not in admin and 'localStorage' in admin
    assert 'takeMany' in admin and 'numberFromName' in admin and 'photo-row' in admin, 'dashboard: one row per numbered photo; several files can be dropped by number'
    assert 'quickBar' not in admin and 'photoMap' not in admin and 'backdrop-filter' not in admin, 'dashboard: a plain list, no page map, no blur'
    assert 'data-tab' in admin and "['requests', 'Заявки'" in admin, 'dashboard: the Requests tab'
    for field in builder.PHOTO_FIELDS:
        assert any(p['field'] == field for p in schema['photos'])
    robots = (destination / 'robots.txt').read_text(encoding='utf-8')
    assert 'Disallow' in robots


def check_soft_controls(destination):
    """Rounded corners belong to buttons and fields only; photos, panels and sections stay square. No \"up\" button."""
    css = (destination / 'assets/site.css').read_text(encoding='utf-8')
    articles_css = (destination / 'assets/articles.css').read_text(encoding='utf-8')
    allowed = ('.button', '.icon-button', '.contact-links', 'summary::after', '.field', '.slot-badge', '.skip')
    for sheet in (css, articles_css):
        for selector, body in re.findall(r'([^{}]+)\{([^{}]*border-radius[^{}]*)\}', sheet):
            values = re.findall(r'border-radius\s*:\s*([^;}]+)', body)
            if all(v.strip() in ('0', '0px') for v in values):
                continue                      # resets are fine
            assert any(token in selector for token in allowed), f'rounded corners are only for buttons and fields, found on: {selector.strip()[:60]}'
    for must in ('.button { display:inline-flex', '.qa summary::after {', '.contact-links a {'):
        rule = css[css.index(must):].split('}', 1)[0]
        assert 'border-radius' in rule, f'{must} should be soft'
    for square in ('.photo {', '.plate {', '.quote-panel {', '.free {', '.blog-card {', '.s-honest {'):
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
    letter = re.search(r'\.js \.ch \{([^}]*)\}', css).group(1)
    assert 'filter' not in letter and 'clip-path' not in letter, 'every letter may only fade and rise (opacity, transform)'
    assert not re.search(r'\.finale[^{}]*\{[^}]*filter', css), 'closing statements appear without blur'
    assert 'photo-grade' not in css and 'mix-blend-mode' not in css and 'backdrop-filter' not in css, 'no full-size filters, blend modes or backdrop blur'
    assert 'optimizeLegibility' not in css, 'text-rendering stays at the browser default'
    assert '.mm.is-idle' in css and '.is-idle, .is-idle *' not in css, 'only the butterfly rests off screen, not whole sections'
    assert "$$('.mm')" in home and "$$('main > section').forEach(section => rest" not in home
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


def main():
    builder = load_builder()
    check_consistency(builder)
    check_integrity(builder)
    check_static(builder, ROOT / '_site')
    check_privacy(ROOT / '_site')
    check_brand_and_dashboard(builder, ROOT / '_site')
    check_fonts(ROOT / '_site')
    check_about_and_questions(ROOT / '_site')
    check_scripts(ROOT / '_site')
    check_photo_numbers(ROOT / '_site')
    check_smooth(ROOT / '_site')
    check_inbox(builder, ROOT / '_site')

    # Full-featured build: photos, contacts, form, published notes, a blank FAQ slot and hostile copy.
    def full(work, site):
        site.update({'name_en': 'Test Person', 'email': 'hello@example.com', 'privacy_address': 'Example Street 1, 8000 Zürich, Switzerland',
                     'portrait': 'media/test-cover.webp', 'story_photo_2': 'media/test-cover.webp', 'eyes_photo': '', 'quote_photo': '',
                     'story_photo_1': '', 'story_photo_3': '', 'story_photo_4': '', 'form_endpoint': 'https://formspree.io/f/abc123', 'inbox_endpoint': 'https://script.google.com/macros/s/AKfycbTEST_123/exec', 'publish_ready': True})
        data = json.loads((work / 'content/home_en.json').read_text(encoding='utf-8'))
        data['qa']['q3'] = ''
        data['story']['title'] = '</script><b>x</b>'
        (work / 'content/home_en.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, full, posts=True)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        article = (work / '_site/en/articles/sample/index.html').read_text(encoding='utf-8')
        privacy = (work / '_site/privacy/index.html').read_text(encoding='utf-8')
        assert 'Test Person' in home and 'hello@example.com' in home and 'Sport Intuitive' in home
        assert 'Disallow: /admin/' in (work / '_site/robots.txt').read_text(encoding='utf-8')
        assert home.count('src="media/test-cover.webp"') == 3, 'hero, story frame 2 and one note cover: no place borrows another photograph'
        eyes = re.search(r'<img data-slot="3"[^>]*>', home).group(0)
        assert 'src=' not in eyes, 'photo 3 stays empty instead of repeating photo 1'
        assert '<figure class="photo eyes" hidden>' in home and '<figure class="photo plate plate-r" hidden>' in home, 'live site: empty places are hidden with their frames'
        assert '<figure class="photo hero-photo">' in home and '<figure class="photo plate plate-l">' in home, 'places that have a photograph stay visible'
        assert '"formEndpoint":"https://formspree.io/f/abc123"' in home
        assert '"inboxEndpoint":"https://script.google.com/macros/s/AKfycbTEST_123/exec"' in home and '"preview":false' in home
        assert 'Google Sheets' in privacy and 'formspree.io' in privacy, 'privacy notice names the form service and the spreadsheet'
        assert 'id="notes"' in home and 'CMS_VISIBLE_POSTS = {"en":1}' in home
        assert '<article class="blog-card" data-post-lang="en">' in home
        assert '<footer class="site-footer after-sand"' in home, 'with notes the footer fades from sand'
        assert '<details name="qa" data-qa="3" hidden>' in home and '<details name="qa" data-qa="2">' in home
        assert '</script><b>x</b>' not in home and '\\u003c/script' in home and '&lt;/script&gt;' in home
        assert 'https://demo.github.io/athlete-support/' in home and 'index,follow' in home
        assert 'application/ld+json' in home and 'og:image' in home
        assert 'Testing heading' in article and '<script>alert(1)</script>' not in article
        assert '<base href="../../../">' in article and 'rel="icon"' in article and 'scroll-progress' in article and 'viewBox="0 0 48 48"' in article
        assert 'https://demo.github.io/athlete-support/en/articles/sample/' in article
        assert 'assets/fonts/fonts.css' in article and 'fonts.googleapis' not in article and (work / '_site/assets/fonts/fonts.css').exists(), 'article pages use the self-hosted fonts'
        assert 'href="en/articles/sample/#content"' in article, 'with <base>, the skip link must point back at the article itself'
        assert 'Test Person' in privacy and 'hello@example.com' in privacy and 'Example Street 1' in privacy and 'formspree.io' in privacy
        assert 'https://demo.github.io/athlete-support/privacy/' in privacy, 'privacy page has its canonical address'
        sitemap = (work / '_site/sitemap.xml').read_text(encoding='utf-8')
        assert 'privacy/' in sitemap and (work / '_site/media/test-cover.webp').exists()
        assert 'Disallow: /\n' not in (work / '_site/robots.txt').read_text(encoding='utf-8'), 'an indexable site must not block everything'

    # Defensive build: an insecure form endpoint is dropped, nothing is published, no notes appear.
    def careless(work, site):
        site.update({'form_endpoint': 'http://insecure.example/submit', 'inbox_endpoint': 'https://evil.example/macros/s/x/exec', 'publish_ready': False})
    temporary, work = build_fixture(builder, careless, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        privacy = (work / '_site/privacy/index.html').read_text(encoding='utf-8')
        assert '"formEndpoint":""' in home and 'insecure.example' not in home and 'insecure.example' not in privacy
        assert '"inboxEndpoint":""' in home and 'evil.example' not in home and 'Google Sheets' not in privacy and '"preview":true' in home
        assert 'id="notes"' not in home and 'noindex,nofollow' in home and '<footer class="site-footer after-teal"' in home
        assert 'through the contact form on this website' in privacy and 'opens your own email program' in privacy
        assert '<figure class="photo eyes">' in home and ' hidden>' not in re.search(r'<figure class="photo hero-photo"[^>]*>', home).group(0), 'before launch every place stays visible'
        assert 'Disallow: /' in (work / '_site/robots.txt').read_text(encoding='utf-8')
    # Smaller copies of the photographs (needs Pillow, which the workflow installs).
    if importlib.util.find_spec('PIL'):
        def photographed(work, site):
            from PIL import Image
            Image.new('RGB', (2400, 3000), (40, 90, 140)).save(work / 'media/big.jpg', quality=85)
            Image.new('RGB', (500, 600), (90, 40, 140)).save(work / 'media/small.jpg', quality=85)
            site.update({'portrait': 'media/big.jpg', 'story_photo_1': 'media/small.jpg', 'publish_ready': False})
        temporary, work = build_fixture(builder, photographed, posts=False)
        with temporary:
            home = (work / '_site/index.html').read_text(encoding='utf-8')
            expected = ', '.join(f'media/opt/media-big-jpg-{w}.webp {w}w' for w in (640, 1080, 1600)) + ', media/big.jpg 2400w'
            assert f'srcset="{expected}" sizes="50vw"' in home, 'the hero photograph offers smaller copies'
            for width in (640, 1080, 1600):
                assert (work / f'_site/media/opt/media-big-jpg-{width}.webp').stat().st_size > 0
            assert (work / '_site/media/big.jpg').exists(), 'the original stays'
            assert 'media-small' not in home and 'src="media/small.jpg"' in home, 'a small photograph needs no copies'
    print('OK: smooth scrolling rules, own photo for every number, smaller photo copies, plain dashboard, English-only copy and CMS in sync, warm sand bands and transitions, self-hosted fonts, one Q&A block, photo-left hero, soft floating buttons, numbered photo places, requests inbox, highlighted phrases, closing statements, preface, privacy notice, photos, form, notes, safety and publish mode')


if __name__ == '__main__':
    main()
