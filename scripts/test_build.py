#!/usr/bin/env python3
"""Regression checks: copy/template/CMS consistency, static output, form settings, notes, safe HTML."""
import importlib.util
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
LANGS = ('ru', 'en', 'fr')
SECTION_IDS = ('hero', 'story', 'client', 'why', 'about', 'check', 'fork', 'change', 'invite', 'contact', 'faq')


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
    """Every key the template asks for exists in all languages; CMS config and JSON files agree."""
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    wanted = set(re.findall(r'data-(?:i18n|i18n-aria|i18n-alt)="([^"]+)"', template))
    site = json.loads((ROOT / 'content/site.json').read_text(encoding='utf-8'))
    values = builder.collect_values(site)
    config = yaml.safe_load((ROOT / '.pages.yml').read_text(encoding='utf-8'))
    entries = {entry['name']: entry for entry in config['content']}
    content_sets = {}
    for lang in LANGS:
        flat = builder.flatten(json.loads((ROOT / f'content/home_{lang}.json').read_text(encoding='utf-8')), lang)
        content_sets[lang] = set(flat)
        missing = wanted - set(values[lang]) - {'notes.title', 'notes.lead'}
        assert not missing, f'{lang}: template keys without copy: {sorted(missing)}'
        assert cms_keys(entries[f'home_{lang}']['fields']) == set(flat), f'{lang}: .pages.yml and content/home_{lang}.json differ'
        unused = {k for k in flat if k not in wanted and not k.startswith(('meta.', 'notes.'))}
        assert not unused, f'{lang}: copy that the template never shows: {sorted(unused)}'
    assert content_sets['ru'] == content_sets['en'] == content_sets['fr'], 'languages have different keys'
    for key in ('form_endpoint', 'portrait', 'eyes_photo', 'story_photo_1', 'story_photo_4'):
        assert key in cms_keys(entries['site']['fields']), f'site settings lack {key}'


def check_static(destination):
    home = (destination / 'index.html').read_text(encoding='utf-8')
    css = (destination / 'assets/site.css').read_text(encoding='utf-8')
    assert '<html lang="ru">' in home and 'const CMS_OVERRIDES' in home
    assert '@@' not in home and 'data-photo=' not in home, 'unresolved template marker'
    for section in SECTION_IDS:
        assert f'id="{section}"' in home, f'section missing: {section}'
    assert home.count('<blockquote class="quote-text" data-write ') == 4, 'expected four handwritten quote blocks'
    assert 'id="contact-form"' in home and 'name="_gotcha"' in home
    assert 'id="close-page"' in home and 'id="farewell"' in home
    assert 'Этот сайт устроен иначе' in home and 'Ты можешь контролировать только себя' in home
    assert 'id="notes"' not in home, 'notes must stay hidden until an article is published'
    for gone in ('review-grid', 'quiz', 'credential', 'mobile-cta', 'hero-floating'):
        assert gone not in home, f'old template block is back: {gone}'
    assert 'prefers-reduced-motion' in home and '[hidden] { display:none!important; }' in home
    assert not re.search(r'border-radius\s*:\s*0(?:px)?\s*[;}]', css), 'sharp corners are against the concept'
    assert '@view-transition' in css and 'scroll-progress' in css
    assert 'rel="icon"' in home and 'class="brand-mark"' in home and 'viewBox="0 0 48 48"' in home
    for lang in LANGS:
        assert (destination / lang / 'articles/index.html').exists()
    assert (destination / '.nojekyll').exists()


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
    (work / 'media').mkdir()
    (work / 'media/test-cover.webp').write_bytes(b'fake image bytes')
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
    check_static(ROOT / '_site')

    # Full-featured build: photos, contacts, form, published notes, a blank FAQ slot and hostile copy.
    def full(work, site):
        site.update({'name_ru': 'Наталья Тестовая', 'email': 'hello@example.com', 'portrait': 'media/test-cover.webp',
                     'story_photo_2': 'media/test-cover.webp', 'form_endpoint': 'https://formspree.io/f/abc123', 'publish_ready': True})
        ru = json.loads((work / 'content/home_ru.json').read_text(encoding='utf-8'))
        ru['faq']['q5'] = ''
        ru['story']['title'] = '</script><b>x</b>'
        (work / 'content/home_ru.json').write_text(json.dumps(ru, ensure_ascii=False), encoding='utf-8')
    temporary, work = build_fixture(builder, full, posts=True)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        article = (work / '_site/ru/articles/sample/index.html').read_text(encoding='utf-8')
        assert 'Наталья Тестовая' in home and 'hello@example.com' in home
        assert home.count('src="media/test-cover.webp"') == 6, 'hero, eyes fallback, story frame 2 and three note covers'
        assert '"formEndpoint":"https://formspree.io/f/abc123"' in home
        assert 'id="notes"' in home and 'CMS_VISIBLE_POSTS = {"ru":1,"en":1,"fr":1}' in home
        assert 'data-post-lang="ru"' in home and 'data-post-lang="en" hidden' in home and 'data-post-lang="fr" hidden' in home
        assert '<details data-faq="5" hidden>' in home and '<details data-faq="4">' in home
        assert '</script><b>x</b>' not in home and '\\u003c/script' in home and '&lt;/script&gt;' in home
        assert 'https://demo.github.io/athlete-support/' in home and 'index,follow' in home
        assert 'application/ld+json' in home and 'og:image' in home
        assert 'Testing heading' in article and '<script>alert(1)</script>' not in article
        assert '<base href="../../../">' in article and 'rel="icon"' in article and 'scroll-progress' in article
        assert 'https://demo.github.io/athlete-support/ru/articles/sample/' in article
        for lang in ('en', 'fr'):
            assert (work / f'_site/{lang}/articles/sample/index.html').exists()
        assert (work / '_site/media/test-cover.webp').exists() and (work / '_site/sitemap.xml').exists()
        assert 'Disallow:' not in (work / '_site/robots.txt').read_text(encoding='utf-8')

    # Defensive build: an insecure form endpoint is dropped, nothing is published, no notes appear.
    def careless(work, site):
        site.update({'form_endpoint': 'http://insecure.example/submit', 'publish_ready': False})
    temporary, work = build_fixture(builder, careless, posts=False)
    with temporary:
        home = (work / '_site/index.html').read_text(encoding='utf-8')
        assert '"formEndpoint":""' in home and 'insecure.example' not in home
        assert 'id="notes"' not in home and 'noindex,nofollow' in home
        assert 'Disallow: /' in (work / '_site/robots.txt').read_text(encoding='utf-8')
    print('OK: copy and CMS in sync, three languages, handwritten quotes, photos, form, notes, safety and publish mode')


if __name__ == '__main__':
    main()
