#!/usr/bin/env python3
"""Build a safe, multilingual static site from Pages CMS content. No API keys needed."""
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
BLOG_LABEL = {'ru': 'Все статьи', 'en': 'All articles', 'fr': 'Tous les articles'}
EMPTY_LABEL = {'ru': 'Здесь появятся новые материалы.', 'en': 'New articles will appear here.', 'fr': 'De nouveaux articles paraîtront ici.'}
BACK_LABEL = {'ru': 'На главную', 'en': 'Back to home', 'fr': "Retour à l’accueil"}
READ_LABEL = {'ru': 'Читать статью', 'en': 'Read article', 'fr': "Lire l’article"}
REVIEWS_EMPTY = {'ru': 'Отзывы появятся здесь после получения разрешения на их публикацию.', 'en': 'Testimonials will appear here once publication permission is granted.', 'fr': 'Les témoignages apparaîtront ici après obtention des autorisations de publication.'}
SKIP_LABEL = {'ru': 'Перейти к содержанию', 'en': 'Skip to content', 'fr': 'Aller au contenu'}
FONT_LINKS = '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400..800&family=Source+Serif+4:opsz,wght@8..60,400..700&display=swap" rel="stylesheet">'
PROGRESS_JS = "<script>(function(){if(window.CSS&&CSS.supports&&CSS.supports('animation-timeline','scroll()'))return;var b=document.querySelector('.scroll-progress');function u(){var m=document.documentElement.scrollHeight-innerHeight;b.style.setProperty('--p',m>0?Math.min(1,scrollY/m).toFixed(4):0)}addEventListener('scroll',u,{passive:true});u()})()</script>"
VALID_SLUG = re.compile(r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
SAFE_IMAGE = re.compile(r'^(?:media/|images/)[\w\-/%.]+\.(?:jpe?g|png|gif|webp|avif)$', re.I)
ALLOWED_TAGS = ['p','br','strong','em','b','i','a','ul','ol','li','blockquote','h2','h3','h4','hr','img','code','pre','table','thead','tbody','tr','th','td']
ALLOWED_ATTRS = {'a': ['href','title'], 'img':['src','alt','title','loading'], 'th':['align'], 'td':['align']}


def esc(v):
    return html.escape(str(v if v is not None else ''), quote=True)


def read_json(path):
    return json.loads((ROOT / path).read_text(encoding='utf-8'))


def js_json(obj):
    # Escape all HTML-sensitive bytes so injected JSON cannot terminate the JS script.
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


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
            'lang':lang, 'slug':slug, 'url':f'{lang}/articles/{slug}/',
            'title':str(meta['title']), 'summary':str(meta['summary']),
            'category':str(meta.get('category') or ''), 'date':date_value,
            'cover':photo_path(meta.get('cover')), 'body':body,
        })
    return sorted(posts, key=lambda p:(p['date'], p['slug']), reverse=True)


def render_markdown(source):
    rendered = mistune.create_markdown(escape=True, plugins=['table', 'strikethrough'])(source)
    # Images and links inside rich text may refer to uploaded media by relative path.
    return bleach.clean(rendered, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS,
                        protocols=['http','https','mailto'], strip=True)


def card(post):
    cover = (f'<img src="{esc(post["cover"])}" alt="" loading="lazy" decoding="async">'
             if post['cover'] else '<span class="blog-illustration" aria-hidden="true">✦</span>')
    return (f'<article class="blog-card" data-post-lang="{post["lang"]}">'
            f'<div class="blog-cover">{cover}</div><div class="blog-body">'
            f'<span class="blog-category">{esc(post["category"])}</span>'
            f'<h3>{esc(post["title"])}</h3><p>{esc(post["summary"])}</p>'
            f'<a class="article-link" href="{esc(post["url"])}" data-i18n="cmsReadArticle">{READ_LABEL[post["lang"]]} →</a>'
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


def build_home(site, posts, public_url, ready):
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    overrides = {lang:read_json(f'content/home_{lang}.json') for lang in LANGS}
    for lang in LANGS:
        if not isinstance(overrides[lang], dict):
            raise ValueError(f'Invalid content/home_{lang}.json')
        name = str(site.get('name_'+lang) or '').strip()
        role = str(site.get('role_'+lang) or '').strip()
        overrides[lang].update({
            'brand':name, 'portraitName':name, 'footerName':name,
            'portraitJob':role,
            'cmsReadArticle': READ_LABEL[lang],
            'cmsAllPosts': BLOG_LABEL[lang],
            'cmsEmptyPosts': EMPTY_LABEL[lang],
            'reviewsNote': '',
            'contactUnset': {
                'ru':'Контакты пока не настроены.',
                'en':'Contact details are not configured yet.',
                'fr':'Les coordonnées ne sont pas encore renseignées.'
            }[lang],
        })
        # Replace the old placeholder name in the default 'about me' paragraph.
        old_names = {'ru':'Имя Фамилия','en':'First Last','fr':'Prénom Nom'}
        if name and old_names[lang] in overrides[lang].get('aboutP1',''):
            overrides[lang]['aboutP1'] = overrides[lang]['aboutP1'].replace(old_names[lang], name)
        translations_title = {'ru':'Консультации для спортсменов','en':'Support for athletes','fr':'Accompagnement des sportifs'}
        overrides[lang]['title'] = f'{translations_title[lang]} — {name}' if name else translations_title[lang]
        overrides[lang]['ogDescription'] = overrides[lang].get('heroLead','')
        overrides[lang]['metaDescription'] = overrides[lang].get('heroLead','')
        # The CMS owns the blog introduction. Never overwrite an editor's text.
        overrides[lang]['blogNote'] = ''
        overrides[lang]['contactBoxLead'] = {
            'ru':'Выберите удобный способ связи.',
            'en':'Choose the contact method that works for you.',
            'fr':'Choisissez le moyen de contact qui vous convient.'
        }[lang]
        if ready:
            overrides[lang]['areasNote'] = ''

    reviews = read_json('content/reviews.json')
    if not isinstance(reviews,list):
        raise ValueError('content/reviews.json must be an array')
    review_html = []
    for index, review in enumerate(reviews):
        if not review.get('visible'):
            continue
        for lang in LANGS:
            quote = str(review.get('quote_'+lang) or '').strip()
            if not quote:
                continue
            author = str(review.get('author_'+lang) or '').strip()
            review_html.append('<article class="review" data-review-lang="'+lang+'">'
                f'<blockquote>{esc(quote)}</blockquote><footer>{esc(author)}</footer></article>')
    for lang in LANGS:
        review_html.append(f'<p class="reviews-empty" data-review-empty="{lang}">{esc(REVIEWS_EMPTY[lang])}</p>')
    # Target exact structural boundaries, without reformatting previous CSS / HTML.
    review_pattern = re.compile(r'(<div class="review-grid">)(.*?)(</div>\s*<p class="review-disclaimer"[^>]*>.*?</p>)', re.S)
    template, n = review_pattern.subn(lambda m:m.group(1)+'\n'+''.join(review_html)+'\n</div>',template,count=1)
    if n != 1: raise RuntimeError('Reviews section not found')

    blog_pattern = re.compile(r'(<div class="blog-grid">)(.*?)(</div>\s*<p class="blog-footnote"[^>]*>.*?</p>)',re.S)
    blog_parts = [card(post) for post in posts[:1000]]
    for lang in LANGS:
        blog_parts.append(f'<p class="blog-empty" data-post-empty="{lang}" data-i18n="cmsEmptyPosts">{esc(EMPTY_LABEL[lang])}</p>')
    blog_parts.append('<p class="blog-all-wrap"><a class="button button-outline" id="blog-all-link" href="ru/articles/" data-i18n="cmsAllPosts">Все статьи →</a></p>')
    template,n = blog_pattern.subn(lambda m:m.group(1)+'\n'+''.join(blog_parts)+'\n</div>',template,count=1)
    if n != 1: raise RuntimeError('Blog section not found')
    # Add builder-managed image src attributes. Missing photos retain the original placeholders.
    for old, field in [('portrait.webp','portrait'),('consultation.webp','consultation_photo'),('sport.webp','sport_photo'),('event.webp','event_photo')]:
        path = photo_path(site.get(field))
        template = replace_required(template, 'src="images/'+old+'"',
                                    ('src="'+esc(path)+'"' if path else ''), old)
    settings = {
        'email':str(site.get('email') or ''),
        'whatsapp':str(site.get('whatsapp') or ''),
        'telegram':str(site.get('telegram') or ''),
        'bookingUrl':str(site.get('booking_url') or ''),
    }
    # Content inserted AFTER the original translation object, BEFORE applyLanguage runs.
    injection = (f'    Object.assign(SETTINGS, {js_json(settings)});\n'
                 f'    const CMS_OVERRIDES = {js_json(overrides)};\n'
                 '    for (const [locale, values] of Object.entries(CMS_OVERRIDES)) Object.assign(translations[locale], values);\n'
                 '    const CMS_VISIBLE_POSTS = '+js_json({lang:sum(p['lang']==lang for p in posts) for lang in LANGS})+';\n')
    template = replace_required(template, '    const root = document.documentElement;', injection+'    const root = document.documentElement;', 'JS translations')
    lang_line = "      syncTheme();\n      menuButton.setAttribute('aria-label'"
    language_logic = """      document.querySelectorAll('[data-post-lang]').forEach(node => { node.hidden = node.dataset.postLang !== lang; });
      document.querySelectorAll('[data-post-empty]').forEach(node => { node.hidden = node.dataset.postEmpty !== lang || CMS_VISIBLE_POSTS[lang] > 0; });
      document.querySelectorAll('[data-review-lang]').forEach(node => { node.hidden = node.dataset.reviewLang !== lang; });
      document.querySelectorAll('[data-review-empty]').forEach(node => {
        node.hidden = node.dataset.reviewEmpty !== lang || !!document.querySelector('[data-review-lang="' + lang + '"]');
      });
      document.querySelector('#blog-all-link').href = lang + '/articles/';
"""
    template = replace_required(template, lang_line, language_logic+lang_line, 'language switching')
    template = replace_required(template, '  </style>', '''    [hidden] { display:none !important; }
    .blog-grid { align-items:stretch; }
    .blog-cover img { width:100%; height:100%; object-fit:cover; }
    .blog-illustration { font:400 4rem/1 var(--serif); color:var(--blue-deep); opacity:.6; }
    .blog-card .article-link { display:inline-block; margin-top:14px; color:var(--blue-deep); font-weight:750; }
    .blog-all-wrap { grid-column:1/-1; margin:10px 0 0; }
    .blog-empty,.reviews-empty { grid-column:1/-1; padding:32px; background:var(--paper); border:1px solid var(--border); border-radius:14px; color:var(--text-muted); }
  </style>''','CSS')
    template = replace_required(template, '<meta name="color-scheme"',
        ('<meta name="robots" content="index,follow">' if ready else '<meta name="robots" content="noindex,nofollow">')+'\n  <meta name="color-scheme"', 'robots')
    # Materialize the Russian-language fallback into static HTML for SEO, no-JS
    # readers, and to avoid flashing placeholders before translation code runs.
    for key, value in overrides['ru'].items():
        if not isinstance(value, str):
            continue
        pat = re.compile(r'(<(?P<tag>[a-z][a-z0-9]*)\b[^>]*\bdata-i18n="'+re.escape(key)+r'"[^>]*>)([^<]*)(</(?P=tag)>)', re.I)
        template = pat.sub(lambda match: match.group(1)+esc(value)+match.group(4), template)
    # Update meta initial markup as well as JavaScript-managed multilingual metadata.
    doc_title = overrides['ru']['title']
    template = re.sub(r'<title>.*?</title>',f'<title>{esc(doc_title)}</title>',template,count=1)
    template = re.sub(r'(<meta name="description" content=")[^"]*',lambda m:m.group(1)+esc(overrides['ru']['metaDescription']),template,count=1)
    template = re.sub(r'(<meta property="og:title" content=")[^"]*',lambda m:m.group(1)+esc(doc_title),template,count=1)
    if public_url:
        template = replace_required(template, '</head>', seo_head(site, public_url) + '</head>', 'head')
    (OUT/'index.html').write_text(template,encoding='utf-8')
    css = re.search(r'<style>(.*?)</style>', template,re.S).group(1)
    (OUT/'assets').mkdir(parents=True, exist_ok=True)
    (OUT/'assets/site.css').write_text(css+'\n',encoding='utf-8')


def article_shell(*, title, description, lang, css_prefix, body, public_url, ready, author, image='', date='', kind='article'):
    canonical = (public_url + css_prefix + '/') if public_url else ''
    canonical_html = f'<link rel="canonical" href="{esc(canonical)}">' if canonical else ''
    desc = esc(description)
    name = esc(author)
    route = '../../' if kind=='archive' else '../../../'
    website = public_url if public_url else './'
    json_ld = ''
    if kind == 'article':
        schema = {'@context':'https://schema.org','@type':'Article',
            'headline':title,'description':description,'datePublished':date,
            'inLanguage':lang,'author':{'@type':'Person','name':author}}
        if canonical: schema['mainEntityOfPage'] = canonical
        if image and public_url: schema['image'] = public_url + image
        json_ld = '<script type="application/ld+json">'+js_json(schema)+'</script>'
    bg_img = f'<img class="post-hero-image" src="{esc(image)}" alt="" loading="eager">' if image else ''
    article_header = f'<p class="post-meta">{esc(date)} · {esc(LANG_LABEL[lang])}</p>' if date else ''
    return f'''<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark"><meta name="theme-color" content="#f8fbfd">{FONT_LINKS}<meta name="robots" content="{'index,follow' if ready else 'noindex,nofollow'}">
<meta name="description" content="{desc}"><meta property="og:type" content="{'article' if kind=='article' else 'website'}"><meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{desc}"><title>{esc(title)} — {name}</title>
<base href="{route}"><link rel="stylesheet" href="assets/site.css"><link rel="stylesheet" href="assets/articles.css">
{canonical_html}{json_ld}<script>(function(){{try{{var t=localStorage.getItem('sport-site-theme');document.documentElement.dataset.theme=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches)?'dark':'light'}}catch(e){{}}}})()</script></head>
<body><div class="scroll-progress" aria-hidden="true"></div><a class="skip" href="#content">{esc(SKIP_LABEL[lang])}</a><header class="site-header"><div class="container header-inner">
<a class="brand" href="./"><span class="brand-mark">S</span><span>{name}</span></a>
<nav class="article-nav"><a href="./">{esc(BACK_LABEL[lang])}</a><a href="{lang}/articles/">{esc(BLOG_LABEL[lang])}</a><a href="./#contact">{esc({'ru':'Контакты','en':'Contact','fr':'Contact'}[lang])}</a></nav>
<button class="icon-button" type="button" id="article-theme" aria-label="Theme" aria-pressed="false">◐</button></div></header>
<main id="content" class="section article-layout"><div class="container article-wrap">{article_header}<h1>{esc(title)}</h1>
<p class="article-intro">{desc}</p>{bg_img}<div class="article-body">{body}</div>
<div class="article-end"><a class="button button-outline" href="{lang}/articles/">← {esc(BLOG_LABEL[lang])}</a></div></div></main>
<footer class="site-footer"><div class="container footer-inner"><p>© {dt.date.today().year} {name}</p><a href="./">{esc(BACK_LABEL[lang])}</a></div></footer>
<script>(function(){{var b=document.getElementById('article-theme');function s(){{b.setAttribute('aria-pressed',String(document.documentElement.dataset.theme==='dark'))}}b.addEventListener('click',function(){{var t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{{localStorage.setItem('sport-site-theme',t)}}catch(e){{}}s()}});s()}})()</script>{PROGRESS_JS}</body></html>'''


def build_articles(site, posts, public_url, ready):
    css = '''
.article-nav { display:flex; align-items:center; gap:22px; margin-left:auto; font-weight:650; color:var(--text-muted); font-size:.91rem; }
.article-layout { min-height:65vh; }
.article-wrap { max-width:810px; }
.article-wrap h1 { font:600 clamp(2.7rem,6vw,4.6rem)/1.11 var(--serif); letter-spacing:-.04em; margin:10px 0 23px; }
.article-intro { font-size:clamp(1.05rem,2.5vw,1.32rem); color:var(--text-muted); margin:0 0 35px; }
.post-meta { color:var(--mint-strong); letter-spacing:.07em; font-size:.84rem; font-weight:700; }
.post-hero-image { max-height:490px; border-radius:24px; margin-bottom:36px; border:1px solid var(--border); object-fit:cover; }
.article-body { font-size:1.09rem; line-height:1.85; overflow-wrap:anywhere; }
.article-body > * { max-width:100%; }
.article-body h2,.article-body h3 { font:600 1.9rem/1.25 var(--serif); letter-spacing:-.015em; margin:38px 0 14px; }
.article-body h3 { font-size:1.5rem; }
.article-body a { color:var(--blue-deep); text-decoration:underline; text-underline-offset:3px; }
.article-body img { height:auto; border-radius:16px; margin:25px 0; }
.article-body blockquote { border-left:3px solid var(--mint); margin:25px 0; padding:12px 22px; color:var(--text-muted); background:var(--paper); }
.article-body li { margin-bottom:10px; }
.article-body pre { overflow-x:auto; max-width:100%; padding:18px; background:var(--paper); border:1px solid var(--border); border-radius:12px; }
.article-body table { border-collapse:collapse; max-width:100%; display:block; overflow:auto; }
.article-body th,.article-body td { padding:10px 14px; border:1px solid var(--border); }
.article-end { margin-top:54px; padding-top:24px; border-top:1px solid var(--border); }
.archive-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:22px; }
.archive-grid .blog-cover { height:180px; }
.article-layout { padding-top:clamp(72px,9vw,128px); }
.article-wrap { max-width:760px; }
.article-wrap h1 { font-size:clamp(2.6rem,6vw,4.4rem); line-height:1.06; letter-spacing:-.04em; text-wrap:balance; }
.article-intro { font-size:clamp(1.12rem,2.4vw,1.38rem); line-height:1.6; margin-bottom:48px; text-wrap:pretty; }
.article-body { font-size:1.14rem; line-height:1.9; }
.article-body p { margin:0 0 1.4em; }
.post-hero-image { border-radius:28px; margin-bottom:52px; box-shadow:var(--shadow-strong); }
.article-wrap > * { animation:riseIn .9s var(--ease) both; }
.article-wrap > :nth-child(2) { animation-delay:.07s; }
.article-wrap > :nth-child(3) { animation-delay:.14s; }
.article-wrap > :nth-child(n+4) { animation-delay:.21s; }
.article-end { margin-top:72px; }
.archive-grid { gap:clamp(18px,2.4vw,30px); }
@media(prefers-reduced-motion:reduce) { .article-wrap > * { animation:none!important; } }
@media(max-width:760px){.article-nav{gap:12px;font-size:.8rem}.article-nav a:nth-child(2){display:none}.archive-grid{grid-template-columns:1fr}}
'''
    (OUT/'assets/articles.css').write_text(css,encoding='utf-8')
    for post in posts:
        body = render_markdown(post['body'])
        path = OUT/post['url']/'index.html'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(article_shell(title=post['title'], description=post['summary'],lang=post['lang'],
                 css_prefix=post['url'].rstrip('/'),body=body,public_url=public_url,ready=ready,
                 author=site.get('name_'+post['lang'],'') or '',image=post['cover'],date=post['date']),encoding='utf-8')
    for lang in LANGS:
        current=[p for p in posts if p['lang']==lang]
        body = '<div class="archive-grid">'+''.join(card(p) for p in current)+'</div>' if current else f'<p>{esc(EMPTY_LABEL[lang])}</p>'
        path = OUT/lang/'articles/index.html'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(article_shell(title=BLOG_LABEL[lang],description=BLOG_LABEL[lang],lang=lang,
            css_prefix=f'{lang}/articles', body=body,public_url=public_url,ready=ready,
            author=site.get('name_'+lang,'') or '',kind='archive'),encoding='utf-8')


def main():
    site = read_json('content/site.json')
    ready = bool(site.get('publish_ready'))
    public_url = url_for_repo(site)
    posts = parse_posts()
    if OUT.exists(): shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    build_home(site,posts,public_url,ready)
    build_articles(site,posts,public_url,ready)
    if (ROOT/'media').exists():
        shutil.copytree(ROOT/'media', OUT/'media', dirs_exist_ok=True, ignore=shutil.ignore_patterns('.gitkeep'))
    (OUT/'.nojekyll').write_text('',encoding='utf-8')
    sitemap=[]
    if public_url and ready:
        sitemap=[public_url]+[public_url+f'{l}/articles/' for l in LANGS]+[public_url+p['url'] for p in posts]
    if sitemap:
        (OUT/'sitemap.xml').write_text('<?xml version="1.0" encoding="utf-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{esc(u)}</loc></url>' for u in sitemap)+'</urlset>',encoding='utf-8')
    (OUT/'robots.txt').write_text('User-agent: *\n'+ ('Allow: /\n'+(f'Sitemap: {public_url}sitemap.xml\n' if sitemap else '') if ready else 'Disallow: /\n'),encoding='utf-8')
    print(f'Built homepage, {len(posts)} published posts, 3 archives -> {OUT} | indexable={ready} | URL={public_url or "local"}')

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(f'BUILD ERROR: {exc}',file=sys.stderr)
        raise SystemExit(1) from exc
