#!/usr/bin/env python3
"""Regression checks for generated paths, CMS edits, translations and safe article HTML."""
import importlib.util
import json
import os
import shutil
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


def check_static(destination):
    home = (destination/'index.html').read_text(encoding='utf-8')
    assert '<html lang="ru">' in home
    assert 'const CMS_OVERRIDES' in home
    assert 'site-header' in home and 'hero-floating' in home
    assert 'mediaTheme' in home and 'language-select' in home
    assert '[hidden] { display:none!important; }' in home
    assert (destination/'ru/articles/index.html').exists()
    assert (destination/'en/articles/index.html').exists()
    assert (destination/'fr/articles/index.html').exists()
    assert (destination/'.nojekyll').exists()
    assert 'scroll-progress' in home and 'mobile-cta' in home
    assert '@view-transition' in (destination/'assets/site.css').read_text(encoding='utf-8')
    assert 'rel="icon"' in home
    assert 'class="brand-mark"' in home and 'viewBox="0 0 48 48"' in home
    assert '-2026' not in home and 'premium' not in home and 'watercolor' not in home


def main():
    check_static(ROOT/'_site')
    spec = importlib.util.spec_from_file_location('site_build', ROOT/'scripts/build.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    yaml.safe_load((ROOT/'.pages.yml').read_text(encoding='utf-8'))
    with tempfile.TemporaryDirectory(prefix='site-build-test-') as temporary:
        work = Path(temporary)
        shutil.copytree(ROOT/'templates', work/'templates')
        shutil.copytree(ROOT/'content', work/'content')
        (work/'media').mkdir()
        (work/'media/test-cover.webp').write_bytes(b'fake image bytes')
        site = json.loads((work/'content/site.json').read_text())
        site.update({'name_ru':'Наталья Тестовая','email':'hello@example.com','portrait':'media/test-cover.webp','publish_ready':True})
        (work/'content/site.json').write_text(json.dumps(site,ensure_ascii=False))
        reviews = [{'visible':True,'quote_ru':'Удобный формат общения','author_ru':'Участник (с согласия)','quote_en':'Helpful conversation','author_en':'Participant (with permission)'}]
        (work/'content/reviews.json').write_text(json.dumps(reviews,ensure_ascii=False))
        for lang in ('ru','en','fr'):
            metadata = {'title':f'Example {lang}','slug':'sample','lang':lang,'published':True,'date':'2026-10-13',
                        'category':'Sport','summary':f'Summary {lang}','cover':'media/test-cover.webp'}
            body = '\n# Testing heading\n\nRich **text** with [link](https://example.org).\n\n<script>alert(1)</script>\n'
            (work/'content/posts'/f'published-{lang}.md').write_text('---\n'+yaml.safe_dump(metadata,allow_unicode=True)+'---\n'+body)
        previous = os.environ.get('GITHUB_REPOSITORY')
        os.environ['GITHUB_REPOSITORY'] = 'demo/athlete-support'
        builder.ROOT = work
        builder.OUT = work/'_site'
        builder.main()
        if previous is None: del os.environ['GITHUB_REPOSITORY']
        else: os.environ['GITHUB_REPOSITORY'] = previous
        home = (work/'_site/index.html').read_text()
        ru = (work/'_site/ru/articles/sample/index.html').read_text()
        assert 'Наталья Тестовая' in home
        assert 'mailto:' not in home or 'hello@example.com' in home
        assert 'media/test-cover.webp' in home
        assert 'data-review-lang="ru"' in home and 'data-review-lang="en"' in home
        assert 'data-post-lang="ru"' in home and 'data-post-lang="en"' in home and 'data-post-lang="fr"' in home
        assert 'CMS_VISIBLE_POSTS = {"ru":1,"en":1,"fr":1}' in home
        assert 'https://demo.github.io/athlete-support/' in home
        assert 'index,follow' in home
        assert 'Testing heading' in ru
        assert 'viewBox="0 0 48 48"' in ru and 'rel="icon"' in ru
        assert 'class="skip" href="#content">Example' not in ru and 'scroll-progress' in ru
        assert 'application/ld+json' in home and 'og:image' in home
        assert '<script>alert(1)</script>' not in ru
        assert '<base href="../../../">' in ru
        assert 'https://demo.github.io/athlete-support/ru/articles/sample/' in ru
        assert 'media/test-cover.webp' in ru
        assert (work/'_site/en/articles/sample/index.html').exists()
        assert (work/'_site/fr/articles/sample/index.html').exists()
        assert (work/'_site/media/test-cover.webp').exists()
        assert (work/'_site/sitemap.xml').exists()
        assert 'Disallow:' not in (work/'_site/robots.txt').read_text()
    print('OK: template, three languages, articles, media paths, reviews, metadata, safety and publish mode')


if __name__ == '__main__':
    main()
