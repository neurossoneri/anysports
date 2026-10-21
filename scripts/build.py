#!/usr/bin/env python3
"""Build a safe, multilingual static site from Pages CMS content. No API keys needed.

Single source of truth for page copy:
  * content/home_<lang>.json   editable copy, grouped by page section (flattened to "group.key")
  * UI (below)                 small system strings: aria labels, form messages, theme labels
  * content/site.json          name, role, contacts, photos, form endpoint
templates/index.html holds markup only. Every text element carries data-i18n="<key>"; the
Russian copy is baked into the static HTML (SEO, no-JS readers) and all three languages are
embedded for client-side switching.
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
LANGS = ('ru', 'en', 'fr')
LANG_LABEL = {'ru': 'Русский', 'en': 'English', 'fr': 'Français'}
BLOG_LABEL = {'ru': 'Все заметки', 'en': 'All notes', 'fr': 'Toutes les notes'}
EMPTY_LABEL = {'ru': 'Здесь появятся новые материалы.', 'en': 'New articles will appear here.', 'fr': 'De nouveaux articles paraîtront ici.'}
BACK_LABEL = {'ru': 'На главную', 'en': 'Back to home', 'fr': 'Retour à l’accueil'}
READ_LABEL = {'ru': 'Читать', 'en': 'Read', 'fr': 'Lire'}
SKIP_LABEL = {'ru': 'Перейти к содержанию', 'en': 'Skip to content', 'fr': 'Aller au contenu'}
CONTACT_LABEL = {'ru': 'Контакты', 'en': 'Contact', 'fr': 'Contact'}

# System strings that are not part of the editable page copy.
UI = {
    'ru': {
        'skip': SKIP_LABEL['ru'], 'brandAria': 'В начало страницы', 'languageLabel': 'Язык',
        'themeDark': 'Включить тёмную тему', 'themeLight': 'Включить светлую тему',
        'photoSoon': 'Здесь будет фотография', 'backToTop': 'Наверх',
        'contactEmail': 'Написать на email',
        'formRequired': 'Пожалуйста, укажите имя и способ связи.', 'formSending': 'Отправляю…',
        'formMailto': 'Открываю вашу почтовую программу…',
        'formUnset': 'Форма пока не подключена. Пожалуйста, напишите напрямую.',
        'formError': 'Не получилось отправить. Попробуйте ещё раз или напишите напрямую.',
        'formSubject': 'Новое сообщение с сайта', 'cmsAllPosts': BLOG_LABEL['ru'],
    },
    'en': {
        'skip': SKIP_LABEL['en'], 'brandAria': 'Back to the top', 'languageLabel': 'Language',
        'themeDark': 'Switch to dark theme', 'themeLight': 'Switch to light theme',
        'photoSoon': 'A photograph will be here', 'backToTop': 'Back to top',
        'contactEmail': 'Write by email',
        'formRequired': 'Please add your name and a way to reach you.', 'formSending': 'Sending…',
        'formMailto': 'Opening your mail app…',
        'formUnset': 'The form is not connected yet. Please write directly.',
        'formError': 'Could not send. Please try again or write directly.',
        'formSubject': 'New message from the website', 'cmsAllPosts': BLOG_LABEL['en'],
    },
    'fr': {
        'skip': SKIP_LABEL['fr'], 'brandAria': 'Retour en haut', 'languageLabel': 'Langue',
        'themeDark': 'Passer au thème sombre', 'themeLight': 'Passer au thème clair',
        'photoSoon': 'Une photographie sera ici', 'backToTop': 'Haut de page',
        'contactEmail': 'Écrire par e-mail',
        'formRequired': 'Veuillez indiquer votre prénom et un moyen de vous joindre.', 'formSending': 'Envoi…',
        'formMailto': 'Ouverture de votre messagerie…',
        'formUnset': 'Le formulaire n’est pas encore connecté. Merci d’écrire directement.',
        'formError': 'Envoi impossible. Réessayez ou écrivez directement.',
        'formSubject': 'Nouveau message depuis le site', 'cmsAllPosts': BLOG_LABEL['fr'],
    },
}

FONT_LINKS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400..800&family=Source+Serif+4:opsz,wght@8..60,400..700&display=swap" rel="stylesheet">'
PROGRESS_JS = "<script>(function(){if(window.CSS&&CSS.supports&&CSS.supports('animation-timeline','scroll()')&&!matchMedia('(prefers-reduced-motion: reduce)').matches)return;var b=document.querySelector('.scroll-progress');function u(){var m=document.documentElement.scrollHeight-innerHeight;b.style.setProperty('--p',m>0?Math.min(1,scrollY/m).toFixed(4):0)}addEventListener('scroll',u,{passive:true});u()})()</script>"
VALID_SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
SAFE_IMAGE = re.compile(r'^(?:media/|images/)[\w\-/%.]+\.(?:jpe?g|png|gif|webp|avif)$', re.I)
ALLOWED_TAGS = ['p', 'br', 'strong', 'em', 'b', 'i', 'a', 'ul', 'ol', 'li', 'blockquote', 'h2', 'h3', 'h4', 'hr', 'img', 'code', 'pre', 'table', 'thead', 'tbody', 'tr', 'th', 'td']
ALLOWED_ATTRS = {'a': ['href', 'title'], 'img': ['src', 'alt', 'title', 'loading'], 'th': ['align'], 'td': ['align']}
# Page photos: data-photo marker in the template -> field in content/site.json.
PHOTO_FIELDS = ('portrait', 'eyes_photo', 'quote_photo', 'story_photo_1', 'story_photo_2', 'story_photo_3', 'story_photo_4')
FAQ_SLOTS = 8


def esc(v):
    return html.escape(str(v if v is not None else ''), quote=True)


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
    name = str(site.get('name_ru') or '').strip()
    out = (f'  <link rel="canonical" href="{esc(public_url)}">\n'
           f'  <meta property="og:url" content="{esc(public_url)}">\n'
           f'  <meta property="og:site_name" content="{esc(name)}">\n')
    portrait = photo_path(site.get('portrait'))
    if portrait:
        out += f'  <meta property="og:image" content="{esc(public_url + portrait)}">\n'
    if name:
        person = {'@context': 'https://schema.org', '@type': 'Person', 'name': name,
                  'jobTitle': str(site.get('role_ru') or ''), 'url': public_url}
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
        title = flat.get('meta.title', '').strip()
        values[lang] = {
            **UI[lang], **flat,
            'brand': name, 'portraitName': name, 'footerName': name, 'portraitJob': role,
            'meta.fullTitle': f'{title} — {name}' if name and title else (title or name),
        }
    return values


def notes_section(posts):
    """Notes appear on the home page only once at least one article is published."""
    if not posts:
        return ''
    cards = ''.join(card(p, hidden=p['lang'] != 'ru') for p in posts[:1000])
    hidden = '' if any(p['lang'] == 'ru' for p in posts) else ' hidden'
    return ('<section class="band band-frost notes" id="notes" aria-labelledby="notes-title"' + hidden + '>'
            '<div class="container"><h2 class="title" id="notes-title" data-i18n="notes.title"></h2>'
            '<p class="lead" data-i18n="notes.lead"></p>'
            f'<div class="notes-grid">{cards}</div>'
            '<p class="notes-all"><a class="button button-outline" id="notes-all" href="ru/articles/" data-i18n="cmsAllPosts"></a></p>'
            '</div></section>')


def build_home(site, posts, public_url, ready):
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    values = collect_values(site)
    ru = values['ru']

    template = replace_required(template, '<!--@@NOTES@@-->', notes_section(posts), 'notes marker')
    # Builder-managed image src attributes; a missing photo keeps its soft placeholder.
    paths = {field: photo_path(site.get(field)) for field in PHOTO_FIELDS}
    paths['eyes_photo'] = paths['eyes_photo'] or paths['portrait']
    for field in PHOTO_FIELDS:
        template = replace_required(template, f'data-photo="{field}"',
                                    f'src="{esc(paths[field])}"' if paths[field] else '', f'photo {field}')
    settings = {
        'email': str(site.get('email') or ''),
        'whatsapp': str(site.get('whatsapp') or ''),
        'telegram': str(site.get('telegram') or ''),
        'formEndpoint': form_endpoint(site),
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

    # Bake the Russian copy into static HTML: SEO, no-JS readers, no flash before the script runs.
    for key, value in ru.items():
        k = re.escape(key)
        text_pat = re.compile(r'(<(?P<tag>[a-z][a-z0-9]*)\b[^>]*\bdata-i18n="' + k + r'"[^>]*>)([^<]*)(</(?P=tag)>)', re.I)
        template = text_pat.sub(lambda m, v=value: m.group(1) + esc(v) + m.group(4), template)
        template = template.replace(f'data-i18n-alt="{key}" alt=""', f'data-i18n-alt="{key}" alt="{esc(value)}"')
        template = template.replace(f'data-i18n-aria="{key}"', f'data-i18n-aria="{key}" aria-label="{esc(value)}"')
    for slot in range(1, FAQ_SLOTS + 1):
        if not ru.get(f'faq.q{slot}', '').strip():
            template = replace_required(template, f'<details data-faq="{slot}">', f'<details data-faq="{slot}" hidden>', f'faq slot {slot}')

    doc_title = ru['meta.fullTitle']
    template = re.sub(r'<title>.*?</title>', lambda m: f'<title>{esc(doc_title)}</title>', template, count=1)
    template = re.sub(r'(<meta name="description" content=")[^"]*', lambda m: m.group(1) + esc(ru['meta.description']), template, count=1)
    template = re.sub(r'(<meta property="og:title" content=")[^"]*', lambda m: m.group(1) + esc(doc_title), template, count=1)
    template = re.sub(r'(<meta property="og:description" content=")[^"]*', lambda m: m.group(1) + esc(ru['meta.description']), template, count=1)
    if public_url:
        template = replace_required(template, '</head>', seo_head(site, public_url) + '</head>', 'head')
    (OUT / 'index.html').write_text(template, encoding='utf-8')
    css = re.search(r'<style>(.*?)</style>', template, re.S).group(1)
    (OUT / 'assets').mkdir(parents=True, exist_ok=True)
    (OUT / 'assets/site.css').write_text(css + '\n', encoding='utf-8')


def site_chrome():
    """Logo and favicon come from the home template: one source for the home page and articles."""
    tpl = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    brand = re.search(r'<span class="brand-mark"[^>]*>(.*?)</span>\s*<span data-i18n="brand"', tpl, re.S)
    icon = re.search(r'<link rel="icon"[^>]*>', tpl)
    return {'brand_html': brand.group(1) if brand else 'S', 'favicon_html': icon.group(0) if icon else ''}


def article_shell(*, title, description, lang, css_prefix, body, public_url, ready, author, image='', date='', kind='article', brand_html='S', favicon_html=''):
    canonical = (public_url + css_prefix + '/') if public_url else ''
    canonical_html = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ''
    desc = esc(description)
    name = esc(author)
    route = '../../' if kind == 'archive' else '../../../'
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
<meta name="color-scheme" content="light dark"><meta name="theme-color" content="#06121e">{favicon_html}{FONT_LINKS}<meta name="robots" content="{'index,follow' if ready else 'noindex,nofollow'}">
<meta name="description" content="{desc}"><meta property="og:type" content="{'article' if kind == 'article' else 'website'}"><meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{desc}"><title>{esc(title)} — {name}</title>
<base href="{route}"><link rel="stylesheet" href="assets/site.css"><link rel="stylesheet" href="assets/articles.css">
{canonical_html}{json_ld}<script>(function(){{try{{var t=localStorage.getItem('sport-site-theme');document.documentElement.dataset.theme=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'}}catch(e){{}}}})()</script></head>
<body><div class="scroll-progress" aria-hidden="true"></div><a class="skip" href="{css_prefix}/#content">{esc(SKIP_LABEL[lang])}</a><header class="site-header"><div class="container header-inner">
<a class="brand" href="./"><span class="brand-mark" aria-hidden="true">{brand_html}</span><span>{name}</span></a>
<nav class="article-nav"><a href="./">{esc(BACK_LABEL[lang])}</a><a href="{lang}/articles/">{esc(BLOG_LABEL[lang])}</a><a href="./#contact">{esc(CONTACT_LABEL[lang])}</a></nav>
<button class="icon-button" type="button" id="article-theme" aria-label="Theme" aria-pressed="false">◐</button></div></header>
<main id="content" class="article-layout"><div class="container article-wrap">{article_header}<h1>{esc(title)}</h1>
<p class="article-intro">{desc}</p>{bg_img}<div class="article-body">{body}</div>
<div class="article-end"><a class="button button-outline" href="{lang}/articles/">← {esc(BLOG_LABEL[lang])}</a></div></div></main>
<footer class="site-footer"><div class="container footer-inner"><p>© {dt.date.today().year} {name}</p><a href="./">{esc(BACK_LABEL[lang])}</a></div></footer>
<script>(function(){{var b=document.getElementById('article-theme');function s(){{b.setAttribute('aria-pressed',String(document.documentElement.dataset.theme==='dark'))}}b.addEventListener('click',function(){{var t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{{localStorage.setItem('sport-site-theme',t)}}catch(e){{}}s()}});s()}})()</script>{PROGRESS_JS}</body></html>'''


ARTICLES_CSS = '''
.article-nav { display:flex; align-items:center; gap:22px; margin-left:auto; font-weight:650; color:var(--header-muted); font-size:.91rem; }
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
                                      author=site.get('name_' + post['lang'], '') or '', image=post['cover'], date=post['date']), encoding='utf-8')
    for lang in LANGS:
        current = [p for p in posts if p['lang'] == lang]
        body = '<div class="archive-grid">' + ''.join(card(p) for p in current) + '</div>' if current else f'<p>{esc(EMPTY_LABEL[lang])}</p>'
        path = OUT / lang / 'articles/index.html'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(article_shell(**chrome, title=BLOG_LABEL[lang], description=BLOG_LABEL[lang], lang=lang,
                                      css_prefix=f'{lang}/articles', body=body, public_url=public_url, ready=ready,
                                      author=site.get('name_' + lang, '') or '', kind='archive'), encoding='utf-8')


def main():
    site = read_json('content/site.json')
    ready = bool(site.get('publish_ready'))
    public_url = url_for_repo(site)
    posts = parse_posts()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    build_home(site, posts, public_url, ready)
    build_articles(site, posts, public_url, ready)
    if (ROOT / 'media').exists():
        shutil.copytree(ROOT / 'media', OUT / 'media', dirs_exist_ok=True, ignore=shutil.ignore_patterns('.gitkeep'))
        for photo in sorted((OUT / 'media').rglob('*')):
            if photo.is_file() and photo.stat().st_size > 600_000:
                print(f'WARNING: {photo.relative_to(OUT)} is {photo.stat().st_size // 1024} KB. Compress it to about 300-400 KB so the page opens quickly on a phone.', file=sys.stderr)
    (OUT / '.nojekyll').write_text('', encoding='utf-8')
    sitemap = []
    if public_url and ready:
        sitemap = [public_url] + [public_url + f'{lang}/articles/' for lang in LANGS] + [public_url + p['url'] for p in posts]
    if sitemap:
        (OUT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + ''.join(f'<url><loc>{esc(u)}</loc></url>' for u in sitemap) + '</urlset>', encoding='utf-8')
    (OUT / 'robots.txt').write_text('User-agent: *\n' + ('Allow: /\n' + (f'Sitemap: {public_url}sitemap.xml\n' if sitemap else '') if ready else 'Disallow: /\n'), encoding='utf-8')
    print(f'Built homepage, {len(posts)} published posts, 3 archives -> {OUT} | indexable={ready} | URL={public_url or "local"}')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'BUILD ERROR: {exc}', file=sys.stderr)
        raise SystemExit(1) from exc
