#!/usr/bin/env python3
"""Применяет к репозиторию лендинга акварельную палитру (голубой -> лавандовый -> зелёный),
новый фон-переливы, логотип-пейзаж (горы, озеро, трава) в шапке и новый favicon.

Запуск из корня репозитория:

    python apply_watercolor_palette.py --dry-run   # только показать, что изменится
    python apply_watercolor_palette.py             # внести правки

Скрипт идемпотентен: повторный запуск обновляет свои блоки, а не дублирует их.
Все файлы сначала формируются в памяти и записываются на диск только если
каждая правка нашла свою точку привязки, поэтому «половинчатого» состояния не бывает.
Рекомендую запускать на чистой git-ветке: итог легко посмотреть через `git diff`.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import quote

# --------------------------------------------------------------------------- #
# 1. Логотип-пейзаж. Только плоские заливки: без url(#id) и clipPath, потому что
#    на страницах статей стоит <base href>, а он ломает ссылки на градиенты в SVG
#    (Safari/Firefox). Скругление углов делает CSS (.brand-mark { overflow:hidden }).
# --------------------------------------------------------------------------- #
LANDSCAPE = (
    # небо (три полосы дают мягкий переход)
    '<rect width="48" height="14" fill="#cfe0f5"/>'
    '<rect y="14" width="48" height="10" fill="#dce8f8"/>'
    '<rect y="24" width="48" height="8" fill="#e8ecf9"/>'
    '<circle cx="37" cy="11" r="4.6" fill="#fff" opacity=".85"/>'
    # дальние горы со снежными вершинами
    '<path d="M-2 31 13 12l8 9 8-12 21 22z" fill="#aab9e4"/>'
    '<path d="M9.7 16 13 12l3.6 4-1.8-1.1-1.6 1.7-1.6-1.7zM25.9 13.6 29 9l4.6 4.6-2.3-1.2-2.1 2-1.6-1.9z" fill="#fff" opacity=".93"/>'
    # ближние предгорья
    '<path d="M-2 31v-4l8-5 9 9zM19 31l11-9 10 6 10-4v7z" fill="#7f9fd3"/>'
    # озеро
    '<rect y="31" width="48" height="17" fill="#86c4bc"/>'
    '<rect y="31" width="48" height="6" fill="#c3e2e0" opacity=".55"/>'
    '<path d="M12 34.5h9M27 37.5h11M8 40h7" stroke="#fff" stroke-width="1.2" stroke-linecap="round" opacity=".6"/>'
    # трава на переднем плане
    '<path d="M-2 48v-8c8-4 15-1 22 3 8 4 18 3 30-2v7z" fill="#8ec99b"/>'
    '<path d="M14 48c10-3 22-2 36-7v7z" fill="#64aa8b"/>'
    '<path d="M36 46.5l-.6-4.2M39 46.5l.3-5M42 46.5l1.3-4" stroke="#4f9a7a" stroke-width="1" '
    'stroke-linecap="round" fill="none"/>'
)

BRAND_SVG = ('<svg viewBox="0 0 48 48" width="35" height="35" xmlns="http://www.w3.org/2000/svg" '
             'aria-hidden="true" focusable="false">' + LANDSCAPE + '</svg>')

_FAVICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48">'
                '<clipPath id="c"><rect width="48" height="48" rx="11"/></clipPath>'
                '<g clip-path="url(#c)">' + LANDSCAPE + '</g></svg>')
FAVICON_LINK = ('<link rel="icon" type="image/svg+xml" sizes="any" href="data:image/svg+xml,'
                + quote(_FAVICON_SVG, safe="/:=' ,.-()") + '">')


# --------------------------------------------------------------------------- #
# 2. Контурные «волны» для hero (как тонкие прозрачные линии на референсах).
# --------------------------------------------------------------------------- #
def waves_url(fill: str, stroke: str, stroke2: str) -> str:
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 800' preserveAspectRatio='none'>"
           f"<path d='M0 470C190 380 360 420 540 520S900 660 1090 560 1360 430 1440 470V800H0Z' fill='{fill}' stroke='{stroke}' stroke-width='1.4'/>"
           f"<path d='M0 600C220 520 380 590 600 640S1000 720 1180 640 1380 560 1440 590V800H0Z' fill='{fill}' stroke='{stroke}' stroke-width='1.2'/>"
           f"<path d='M0 250C200 170 420 190 620 120S1000 -10 1180 80 1360 190 1440 150' fill='none' stroke='{stroke}' stroke-width='1.1' opacity='.7'/>"
           f"<path d='M0 330C240 260 460 300 700 240S1120 150 1440 260' fill='none' stroke='{stroke2}' stroke-width='1' opacity='.6'/>"
           "</svg>")
    return 'url("data:image/svg+xml,' + quote(svg, safe="/:=' ,.-()") + '")'


WAVES_LIGHT = waves_url('rgba(255,255,255,.17)', 'rgba(255,255,255,.85)', 'rgba(120,150,214,.55)')
WAVES_DARK = waves_url('rgba(140,170,240,.05)', 'rgba(190,212,255,.24)', 'rgba(150,130,230,.30)')

# --------------------------------------------------------------------------- #
# 3. CSS-слой палитры. Стоит ПОСЛЕ блока premium-2026, поэтому переопределяет
#    прежние цвета, не трогая остальную вёрстку и анимации.
# --------------------------------------------------------------------------- #
CSS_START = '/* watercolor-2026:start */'
CSS_END = '/* watercolor-2026:end */'

CSS_BLOCK = r'''/* watercolor-2026:start */
/* Палитра: небесно-голубой -> лавандовый -> морская зелень / шалфей. Фон — наложение
   акварельных «пятен» (--wash-*). Чтобы поменять настроение сайта, правьте токены ниже. */
:root {
  --bg:#f5f9fc; --bg-soft:#eaf2f9; --paper:#ffffff; --paper-alt:#f4f8fd;
  --text:#1b3452; --text-muted:#465e75;
  --blue:#3f6cb0; --blue-deep:#2c559a;
  --mint:#79b9a3; --mint-strong:#25735f; --lavender:#9b92d0;
  --border:rgba(63,100,165,.16);
  --glow-blue:rgba(148,178,230,.38); --glow-mint:rgba(134,198,178,.34);
  --shadow:0 26px 66px -42px rgba(44,85,154,.34);
  --shadow-strong:0 36px 90px -46px rgba(38,76,140,.36);
  --focus:#3a64ae; --on-accent:#fff; --hero:#e4eef9;
  --header-bg:rgba(247,250,253,.89); --testimonials:#eef4fa;
  --glass:rgba(255,255,255,.64); --glass-bright:rgba(255,255,255,.78); --glass-stroke:rgba(255,255,255,.85);
  --glass-shadow:0 22px 65px -34px rgba(52,92,166,.30);
  --soft-blue:rgba(160,188,234,.52); --soft-green:rgba(140,201,178,.42); --soft-lav:rgba(196,185,232,.42);
  --surface-gradient:linear-gradient(122deg,rgba(255,255,255,.5),rgba(226,236,250,.28) 48%,rgba(176,215,203,.24));
  --veil:rgba(255,255,255,.42);
  --wash-indigo:rgba(116,142,210,.56); --wash-blue:rgba(156,190,238,.58); --wash-teal:rgba(110,184,166,.52);
  --wash-sage:rgba(156,202,170,.46); --wash-lav:rgba(184,170,228,.46); --wash-lemon:rgba(238,242,208,.55);
  --waves:@@WAVES_LIGHT@@;
}
:root[data-theme="dark"] {
  --bg:#0e1f34; --bg-soft:#13293f; --paper:#182f48; --paper-alt:#1c3752;
  --text:#f1f6fd; --text-muted:#bdd0e4;
  --blue:#9fb9ee; --blue-deep:#b7caf5;
  --mint:#8fd1bb; --mint-strong:#a8dfc9; --lavender:#b8aee8;
  --border:rgba(168,196,240,.18);
  --glow-blue:rgba(74,102,176,.30); --glow-mint:rgba(52,150,128,.20);
  --shadow:0 26px 65px -40px rgba(0,7,20,.8); --shadow-strong:0 34px 80px -40px rgba(0,7,20,.82);
  --focus:#b7caf5; --on-accent:#0e2038; --hero:#13293f;
  --header-bg:rgba(14,31,52,.91); --testimonials:#122840;
  --glass:rgba(28,52,82,.66); --glass-bright:rgba(33,62,96,.78); --glass-stroke:rgba(176,200,240,.22);
  --glass-shadow:0 24px 70px -35px rgba(0,9,29,.72);
  --soft-blue:rgba(78,108,184,.30); --soft-green:rgba(50,140,120,.24); --soft-lav:rgba(110,96,186,.26);
  --surface-gradient:linear-gradient(122deg,rgba(44,72,118,.34),rgba(24,52,84,.18) 48%,rgba(30,104,92,.16));
  --veil:rgba(16,38,62,.46);
  --wash-indigo:rgba(66,88,170,.42); --wash-blue:rgba(54,96,164,.34); --wash-teal:rgba(34,126,116,.34);
  --wash-sage:rgba(60,128,100,.26); --wash-lav:rgba(96,82,170,.30); --wash-lemon:rgba(120,140,100,.10);
  --waves:@@WAVES_DARK@@;
}
::selection { background:rgba(148,178,230,.42); }

/* Фон страницы: фиксированная акварель под всем контентом */
body { background:var(--bg); }
body::before {
  content:""; position:fixed; inset:0; z-index:-1; pointer-events:none;
  background:
    radial-gradient(ellipse 80% 60% at 0% 104%, var(--wash-indigo), transparent 68%),
    radial-gradient(ellipse 60% 46% at 42% 112%, var(--wash-teal), transparent 70%),
    radial-gradient(ellipse 50% 44% at 104% 86%, var(--wash-blue), transparent 68%),
    radial-gradient(ellipse 44% 36% at 8% 38%, var(--wash-lav), transparent 70%),
    radial-gradient(ellipse 60% 40% at 92% -4%, var(--wash-lemon), transparent 70%),
    linear-gradient(180deg, var(--bg), var(--bg-soft));
}

/* Hero: самая насыщенная акварель, как на референсе */
.hero { background:transparent; }  /* фон страницы (body::before) продолжается под hero без шва */
.hero::before {
  background:
    radial-gradient(ellipse 46% 40% at 12% 84%, var(--wash-indigo), transparent 72%),
    radial-gradient(ellipse 40% 34% at 48% 92%, var(--wash-teal), transparent 74%),
    radial-gradient(ellipse 34% 34% at 90% 74%, var(--wash-blue), transparent 72%),
    radial-gradient(ellipse 30% 28% at 28% 58%, var(--wash-lav), transparent 72%),
    radial-gradient(ellipse 34% 30% at 76% 38%, var(--wash-sage), transparent 74%);
}
.hero::after {
  inset:0; height:auto; opacity:1; z-index:0; pointer-events:none;
  background:var(--waves) center/100% 100% no-repeat;
}
@media (max-width:760px) { .hero::after { background-size:280% 100%; background-position:62% 100%; } }

/* Секции с лёгкой «вуалью», чтобы фон просвечивал */
.section-soft {
  background:radial-gradient(ellipse 62% 85% at 94% 11%,var(--soft-green),transparent 76%),
             radial-gradient(ellipse 60% 95% at 4% 92%,var(--soft-lav),transparent 76%),
             var(--veil);
}
.reviews {
  background:radial-gradient(ellipse at 12% 18%,var(--soft-blue),transparent 52%),
             radial-gradient(ellipse at 90% 81%,var(--soft-lav),transparent 56%),
             var(--veil);
}
.site-footer { background:var(--veil); }

/* Логотип-пейзаж в шапке */
.brand-mark {
  padding:0; overflow:hidden; color:transparent; font-size:0; background:#dce8f8;
  box-shadow:inset 0 0 0 1px rgba(255,255,255,.55),0 7px 20px -12px rgba(63,100,165,.8);
}
.brand-mark svg { display:block; width:100%; height:100%; }

/* Кнопки, прогресс, плейсхолдеры фото */
.button-primary { background-image:linear-gradient(110deg,#2c5ea3,#2b6f9d 50%,#2b7d6c); }
.progress-fill { background:linear-gradient(90deg,#4a7cc4,#6fb4a0); }
.photo-frame { background:linear-gradient(135deg,#d6e4f6,#b9d2ec 48%,#b5dccb); }
:root[data-theme="dark"] .photo-frame { background:linear-gradient(135deg,#27406c,#2a4e78 50%,#2a6a62); }
.photo-placeholder { color:#2c559a; }
:root[data-theme="dark"] .photo-placeholder { color:#dbe8fb; }

/* Обложки статей: горы -> озеро -> луг */
.blog-cover { color:#1d3f6e; background:linear-gradient(135deg,#d3def4,#a9bfe8); }
.blog-card:nth-child(3n+2) .blog-cover { background:linear-gradient(135deg,#d6edeb,#8fc9c3); }
.blog-card:nth-child(3n+3) .blog-cover { background:linear-gradient(135deg,#e3f0d6,#a5d0a9); }

/* Блок контактов: глубокое озеро с зелёным бликом */
.contact {
  background:radial-gradient(ellipse at 8% 85%,rgba(120,150,226,.34),transparent 61%),
             radial-gradient(ellipse at 90% 10%,rgba(122,196,172,.32),transparent 57%),
             radial-gradient(ellipse at 52% 0%,rgba(176,160,228,.20),transparent 55%),
             linear-gradient(125deg,#1f3f78,#2a5c8f 54%,#2c7a7c);
}
.contact .eyebrow { background:rgba(255,255,255,.14); border-color:rgba(255,255,255,.34); box-shadow:none; }
.contact .eyebrow[data-index]::before { color:#c4efe3; border-right-color:rgba(255,255,255,.3); }
.contact-links a { color:#25508f; }
.contact-links a:hover { background:#e9f1fb; }
/* watercolor-2026:end */'''.replace('@@WAVES_LIGHT@@', WAVES_LIGHT).replace('@@WAVES_DARK@@', WAVES_DARK)

README_MARKER = '## 10. Палитра «акварель»'
README_SECTION = '''
## 10. Палитра «акварель» и логотип-пейзаж

Цвета сайта (небесно-голубой → лавандовый → морская зелень) заданы токенами в блоке
`watercolor-2026:start/end` в конце `<style>` файла `templates/index.html`. Он стоит после `premium-2026`
и переопределяет прежние цвета: чтобы изменить настроение сайта, правьте только переменные `--bg`, `--blue`,
`--mint`, `--wash-*` в этом блоке (отдельно для светлой и тёмной темы). Фон страницы и hero — наложение
полупрозрачных градиентов, картинок не требуется.

Логотип в шапке (горы, озеро, трава) — встроенный SVG внутри `<span class="brand-mark">`, favicon — тот же рисунок
в `<link rel="icon">`. `scripts/build.py` берёт их из шаблона и подставляет на страницы статей, так что источник один.
'''


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #
class PatchError(RuntimeError):
    pass


def sub_once(text: str, pattern: str, repl: str, what: str, flags: int = 0) -> str:
    new, n = re.subn(pattern, lambda _m: repl, text, count=1, flags=flags)
    if n != 1:
        raise PatchError(f'не найдена точка привязки: {what}')
    return new


def replace_literal(text: str, old: str, new: str, what: str, *, done_marker: str | None = None) -> str:
    if done_marker and done_marker in text:
        return text
    if old not in text:
        raise PatchError(f'не найдена точка привязки: {what}')
    return text.replace(old, new, 1)


def patch_template(text: str) -> str:
    # favicon
    text = sub_once(text, r'<link rel="icon"[^>]*>', FAVICON_LINK, 'favicon в templates/index.html')
    # логотип в шапке (буква S -> пейзаж); работает и при повторном запуске
    text = sub_once(text, r'<span class="brand-mark"[^>]*>.*?</span>(?=\s*<span data-i18n="brand")',
                    '<span class="brand-mark" aria-hidden="true">' + BRAND_SVG + '</span>',
                    'логотип .brand-mark', re.S)
    # цвет адресной строки на мобильных
    text = text.replace('<meta name="theme-color" content="#f8fbfd"', '<meta name="theme-color" content="#f5f9fc"')
    text = text.replace("'#0e2035'", "'#0e1f34'").replace("'#f8fbfd'", "'#f5f9fc'")
    # CSS-слой
    if CSS_START in text:
        text = sub_once(text, re.escape(CSS_START) + r'.*?' + re.escape(CSS_END), CSS_BLOCK,
                        'блок watercolor-2026', re.S)
    else:
        anchor = '/* premium-2026:end */'
        if anchor not in text:
            raise PatchError('не найден маркер /* premium-2026:end */ — шаблон изменился?')
        text = text.replace(anchor, anchor + '\n' + CSS_BLOCK, 1)
    return text


SITE_CHROME_FUNC = '''def site_chrome():
    """Логотип и favicon берём из шаблона главной: единый источник для главной и статей."""
    tpl = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    brand = re.search(r'<span class="brand-mark"[^>]*>(.*?)</span>\\s*<span data-i18n="brand"', tpl, re.S)
    icon = re.search(r'<link rel="icon"[^>]*>', tpl)
    return {'brand_html': brand.group(1) if brand else 'S', 'favicon_html': icon.group(0) if icon else ''}


'''


def patch_build(text: str) -> str:
    if 'def site_chrome' in text:
        return text  # уже применено
    text = replace_literal(text, "def article_shell(*, title,", SITE_CHROME_FUNC + "def article_shell(*, title,",
                           'def article_shell')
    text = replace_literal(text, "kind='article'):", "kind='article', brand_html='S', favicon_html=''):",
                           'сигнатура article_shell')
    text = replace_literal(text, '<span class="brand-mark">S</span>',
                           '<span class="brand-mark" aria-hidden="true">{brand_html}</span>',
                           'brand-mark в article_shell')
    text = replace_literal(text, '<meta name="theme-color" content="#f8fbfd">{FONT_LINKS}',
                           '<meta name="theme-color" content="#f5f9fc">{favicon_html}{FONT_LINKS}',
                           'theme-color в article_shell')
    text = replace_literal(text, "def build_articles(site, posts, public_url, ready):\n",
                           "def build_articles(site, posts, public_url, ready):\n    chrome = site_chrome()\n",
                           'def build_articles')
    text = replace_literal(text, "article_shell(title=post['title'],", "article_shell(**chrome, title=post['title'],",
                           'вызов article_shell (статья)')
    text = replace_literal(text, "article_shell(title=BLOG_LABEL[lang],", "article_shell(**chrome, title=BLOG_LABEL[lang],",
                           'вызов article_shell (архив)')
    return text


def patch_tests(text: str) -> str:
    if 'watercolor-2026:start' in text:
        return text
    text = replace_literal(
        text, "    assert '@view-transition' in (destination/'assets/site.css').read_text(encoding='utf-8')\n",
        "    assert '@view-transition' in (destination/'assets/site.css').read_text(encoding='utf-8')\n"
        "    assert 'watercolor-2026:start' in home and 'rel=\"icon\"' in home\n"
        "    assert 'class=\"brand-mark\"' in home and 'viewBox=\"0 0 48 48\"' in home\n",
        'check_static в test_build.py')
    text = replace_literal(
        text, "        assert 'Testing heading' in ru\n",
        "        assert 'Testing heading' in ru\n"
        "        assert 'viewBox=\"0 0 48 48\"' in ru and 'rel=\"icon\"' in ru\n",
        'проверка статьи в test_build.py')
    return text


def patch_readme(text: str) -> str:
    if README_MARKER in text:
        return text
    return text.rstrip('\n') + '\n' + README_SECTION


# --------------------------------------------------------------------------- #
def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--root', default='.', help='корень репозитория (по умолчанию — текущая папка)')
    parser.add_argument('--dry-run', action='store_true', help='ничего не записывать, только показать результат')
    args = parser.parse_args()
    root = Path(args.root).resolve()

    plan = [
        ('templates/index.html', patch_template, True),
        ('scripts/build.py', patch_build, True),
        ('scripts/test_build.py', patch_tests, False),
        ('README.md', patch_readme, False),
    ]
    results = []
    try:
        for rel, func, required in plan:
            path = root / rel
            if not path.exists():
                if required:
                    raise PatchError(f'файл не найден: {rel} (запускайте из корня репозитория или укажите --root)')
                print(f'  пропущен (нет файла): {rel}')
                continue
            old = path.read_text(encoding='utf-8')
            new = func(old)
            results.append((rel, path, old, new))
    except PatchError as exc:
        print(f'ОШИБКА: {exc}\nНичего не изменено.', file=sys.stderr)
        return 1

    changed = 0
    for rel, path, old, new in results:
        if new == old:
            print(f'  без изменений: {rel}')
            continue
        changed += 1
        print(f'  {"будет изменён" if args.dry_run else "изменён"}: {rel}  ({len(old):,} -> {len(new):,} символов)')
        if not args.dry_run:
            path.write_text(new, encoding='utf-8', newline='\n')

    if args.dry_run:
        print('\nDry-run: файлы не записаны.')
    elif changed:
        print('\nГотово. Проверьте локально: python scripts/build.py && python scripts/test_build.py, '
              'затем git diff, commit и push в main.')
    else:
        print('\nУже применено — менять нечего.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
