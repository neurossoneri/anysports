#!/usr/bin/env python3
"""
Скрипт 3 из 3: раздел «My story» (две стадии) и заключительная фраза (вариант B).

Что делает:
  1. «My story»: фото FIFA в композиции «Спокойная пара» сразу после рассказа о FIFA (пауза), цитата «Over time…» как мост,
     рассказ о нынешнем пути делится на две части (тексты не меняются), между ними недавние фото в композиции
     «Крупное и малое» (асимметрия), в конце заключительная фраза.
  2. Новый вид фразы «Заключительная»: узкая тихая колонка, обычный шрифт, много воздуха, без линий, фона и анимации.
  3. Если вы уже меняли «My story» сами, структура не трогается (сообщение будет в выводе), добавляются только стили и вид фразы.
  4. Тесты и документация обновлены вместе с кодом.

Нужны скрипты 1 и 2. Запуск из корня репозитория:   python3 apply_about_story_update.py
Повторный запуск ничего не меняет. Если хоть одна замена не нашла своё место, ничего не записывается.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
NAME = 'about-story'
MARK = 'about-story-v1'
BACKUP = ROOT / f'.backup-{NAME}'
REQUIRES = 'photo-tools-v1'   # маркер скрипта 2 в шаблоне


# ------------------------------------------------------------------ механика замен
class Miss(Exception):
    pass


def op_text(src, old, new, label):
    n = src.count(old)
    if n != 1:
        raise Miss(f'{label}: текст найден {n} раз(а), нужен ровно 1')
    return src.replace(old, new, 1)


def _find_line(lines, prefix, label):
    hits = [i for i, l in enumerate(lines) if l.strip().startswith(prefix)]
    if len(hits) != 1:
        raise Miss(f'{label}: строка с началом «{prefix[:50]}» найдена {len(hits)} раз(а), нужна ровно 1')
    return hits[0]


def op_line(src, prefix, new, label):
    """Строка, начинающаяся с prefix (после отступа), заменяется целиком. new=None удаляет строку."""
    lines = src.split('\n')
    i = _find_line(lines, prefix, label)
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    if new is None:
        del lines[i]
    else:
        lines[i:i + 1] = [(indent + l if l.strip() else l) for l in new.split('\n')]
    return '\n'.join(lines)


def op_after(src, prefix, new, label):
    lines = src.split('\n')
    i = _find_line(lines, prefix, label)
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    lines[i + 1:i + 1] = [(indent + l if l.strip() else l) for l in new.split('\n')]
    return '\n'.join(lines)


def op_before(src, prefix, new, label):
    lines = src.split('\n')
    i = _find_line(lines, prefix, label)
    indent = lines[i][:len(lines[i]) - len(lines[i].lstrip())]
    lines[i:i] = [(indent + l if l.strip() else l) for l in new.split('\n')]
    return '\n'.join(lines)


def op_range(src, start, end, new, label):
    """От строки с началом start до строки с началом end включительно. new='' удаляет блок."""
    lines = src.split('\n')
    a = _find_line(lines, start, label + ' (начало)')
    b = _find_line(lines, end, label + ' (конец)')
    if b < a:
        raise Miss(f'{label}: конец раньше начала')
    indent = lines[a][:len(lines[a]) - len(lines[a].lstrip())]
    repl = [(indent + l if l.strip() else l) for l in new.split('\n')] if new else []
    lines[a:b + 1] = repl
    return '\n'.join(lines)


def op_regex(src, pattern, new, label):
    result, n = re.subn(pattern, lambda m: new, src, count=0, flags=re.S)
    if n != 1:
        raise Miss(f'{label}: образец найден {n} раз(а), нужен ровно 1')
    return result


def op_regexn(src, pattern, repl, count, label):
    result, n = re.subn(pattern, repl, src, flags=re.S)
    if n != count:
        raise Miss(f'{label}: образец найден {n} раз(а), нужно {count}')
    return result


def run_ops(src, ops, path):
    for kind, *args, label in ops:
        fn = {'text': op_text, 'line': op_line, 'after': op_after, 'before': op_before, 'range': op_range, 'regex': op_regex, 'regexn': op_regexn}[kind]
        src = fn(src, *args, f'{path}: {label}')
    return src


# ------------------------------------------------------------------ шаблон: воздух вокруг композиций, заключительная фраза
STORY_CSS = '''/* about-story-v1. Два этапа истории: спокойная пауза с фото прошлого и более личная асимметричная композиция с недавними фото. */
.blocks > .b-photos[data-comp="calm-pair"] { margin-block:clamp(64px,10vw,140px); }
.blocks > .b-photos[data-comp="lead-small"] { margin-block:clamp(48px,7vw,104px); }
.sec-centered .blocks > .b-photos[data-comp="calm-pair"] { margin-block:clamp(64px,10vw,140px); }
.sec-centered .blocks > .b-photos[data-comp="lead-small"] { margin-block:clamp(48px,7vw,104px); }
/* Closing statement: a narrow, quiet column with a lot of air. Ordinary type, no line, no ornament, no background. */
.aside-closing { margin:clamp(72px,12vw,168px) auto clamp(24px,5vw,72px); padding:0; text-align:center; }
.aside-closing .statement { max-width:16em; margin-inline:auto; font:400 clamp(1.45rem,2.6vw,2.2rem)/1.42 var(--serif); letter-spacing:-.01em; color:var(--c-text); }'''

TEMPLATE_OPS = [
    ('before', '/* An optional larger view: a quiet dark overlay', STORY_CSS, 'CSS: воздух вокруг композиций, заключительная фраза'),
]

# ------------------------------------------------------------------ сборка
BUILD_OPS = [
    ('line', 'ASIDE_LOOKS = ', "ASIDE_LOOKS = (('quiet', 'Тихая: обычным шрифтом, без рамки'), ('closing', 'Заключительная: узкая колонка, много воздуха (для конца страницы)'), ('hand', 'Рукописью (Caveat), без плашки'), ('panel', 'На тёмной плашке (можно с фото за текстом)'))", 'вид фразы «заключительная»'),
    ('text', "        if block['look'] == 'quiet':\n",
     "        if block['look'] == 'closing':\n            return f'<div class=\"b b-aside aside-closing\" {number}><p class=\"statement\">{esc(text)}</p></div>'\n        if block['look'] == 'quiet':\n", 'рендер заключительной фразы'),
]
PAGES_OPS = [
    ('text', "          - value: quiet\n            label: Фраза · тихая\n",
     "          - value: quiet\n            label: Фраза · тихая\n          - value: closing\n            label: Фраза · заключительная\n", 'вид «заключительная» в CMS'),
]

# ------------------------------------------------------------------ тесты
TEST_CHECK = '''def check_story_and_closing(builder):
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
        rule = re.search(r'\\.aside-closing \\.statement \\{([^}]*)\\}', css).group(1)
        assert 'italic' not in rule and 'background' not in rule and 'border' not in rule, 'the ending is typography and space only'
        assert 'about-story-v1' in css
    assert dict(builder.ASIDE_LOOKS).get('closing'), 'the dashboard offers the closing statement'


'''
TEST_OPS = [
    ('before', 'def main():', TEST_CHECK.rstrip('\n') + '\n\n', 'проверка заключительной фразы'),
    ('after', 'check_photo_tools(builder)', 'check_story_and_closing(builder)', 'вызов проверки'),
]


# ------------------------------------------------------------------ раздел About в content/sections.json
def restructure_about(text):
    """Переставляет блоки «My story» под две стадии истории. Тексты не меняются. Возвращает (новый текст, сообщение)."""
    data = json.loads(text)
    section = next((s for s in data.get('sections', []) if s.get('id') == 'about'), None)
    if not section:
        return text, 'раздел about не найден, не трогала'
    blocks = section.get('blocks', [])
    if [b.get('type') for b in blocks] != ['text', 'text', 'quote', 'photos', 'text', 'photos', 'text']:
        return text, 'структура «My story» уже другая (вы меняли её сами), не трогала'
    lead, text_a, bridge, fifa, text_b, recent, last = blocks
    paragraphs = [p for p in re.split(r'\n\s*\n', text_b.get('body', '').strip()) if p.strip()]
    expected = ((fifa.get('s1'), fifa.get('s2'), recent.get('s1'), recent.get('s2')) == ('4', '5', '6', '7')
                and len(paragraphs) == 3 and paragraphs[2].startswith('Today,')
                and last.get('body', '').startswith('Guiding others') and last.get('look') == 'hand'
                and not fifa.get('comp') and not recent.get('comp'))
    if not expected:
        return text, 'текст или фото «My story» уже отличаются от ожидаемых, не трогала'
    fifa['comp'] = 'calm-pair'
    recent['comp'] = 'lead-small'
    part_one = dict(text_b, body='\n\n'.join(paragraphs[:2]))
    part_two = dict(text_b, body=paragraphs[2])
    closing = {'type': 'aside', 'text': last['body'].strip(), 'look': 'closing', 'photo': ''}
    section['blocks'] = [lead, text_a, fifa, bridge, part_one, recent, part_two, closing]
    return json.dumps(data, ensure_ascii=False, indent=2) + '\n', 'раздел «My story» перестроен'


DOC_DASHBOARD = '''
## «My story»: две стадии и заключительная фраза (скрипт apply_about_story_update.py)

Порядок блоков в разделе «My story» теперь такой (все тексты прежние, добавлено только разбиение одного блока на два):

1. Вводная фраза.
2. **Стадия A, профессиональный путь:** рассказ про спорт и десять лет в FIFA.
3. **Пауза с фото FIFA** (композиция «Спокойная пара»): большой горизонтальный кадр и малый вертикальный, много воздуха вокруг.
4. Цитата «Over time, I began to envision…» как мост к следующему этапу.
5. **Стадия B, личный путь:** две части рассказа, между ними **недавние фото** (композиция «Крупное и малое»: крупный кадр, малый рядом, асимметрия).
6. Заключительная фраза «Guiding others…» (вид «Заключительная»: узкая колонка, обычный шрифт, много воздуха, без линий и фона).

Всё это обычные блоки: переставляйте, меняйте композицию и кадрирование в панели («Тексты» → My story). Кадрирование для фото 4–7 я не задавала, потому что не видела сами кадры: откройте «Кадрировать» у каждого фото и проверьте лицо в кадре на телефоне и на компьютере.

Вид фразы **«Заключительная»** можно выбрать у любого блока «Фраза»: она предназначена для конца страницы.
'''
DOC_CONCEPT = '''
## 16. «My story» и конец страницы (скрипт apply_about_story_update.py)

- Рассказ идёт в две стадии, и композиция фото отражает их: **прошлое** (FIFA) тихая пауза с парой кадров разного размера; **настоящее** (текущее направление) более личная асимметрия, один крупный недавний кадр и малый.
- Цитата стоит между стадиями и служит мостом, а не заголовком раздела.
- **Конец страницы** узкая тихая колонка: обычный шрифт, воздух, ни линий, ни фона, ни анимации. Страница делает паузу, а не произносит лозунг.
'''
DOC_README = '''
## «My story» и конец страницы (октябрь 2026)

Раздел «My story» перестроен в две стадии (профессиональный путь, затем личное направление) с композициями «Спокойная пара» и «Крупное и малое». Последняя фраза теперь вид «Заключительная»: узкая тихая колонка. Тексты не менялись. Подробности в `docs/DASHBOARD.md`.
'''
DOC_REVIEW = '''
- [ ] «My story»: проверьте кадрирование фото 4–7 на телефоне (лицо должно остаться в кадре) и нравится ли место цитаты «Over time…» между двумя стадиями.
'''
DOCS = [
    ('docs/DASHBOARD.md', DOC_DASHBOARD, 'apply_about_story_update.py'),
    ('docs/CONCEPT.md', DOC_CONCEPT, '## 16. «My story» и конец страницы'),
    ('README.md', DOC_README, '## «My story» и конец страницы'),
    ('docs/CONTENT-REVIEW.md', DOC_REVIEW, '«My story»: проверьте кадрирование фото 4–7'),
]
FILE_OPS = [('templates/index.html', TEMPLATE_OPS), ('scripts/build.py', BUILD_OPS), ('.pages.yml', PAGES_OPS), ('scripts/test_build.py', TEST_OPS)]


# ------------------------------------------------------------------ main
def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def main():
    needed = ['scripts/build.py', 'scripts/test_build.py', 'templates/index.html', '.pages.yml', 'content/sections.json']
    absent = [p for p in needed if not (ROOT / p).exists()]
    if absent:
        print('Запустите скрипт из корня репозитория. Не найдено: ' + ', '.join(absent))
        return 1
    template = read('templates/index.html')
    if MARK in template:
        print('Это обновление уже применено (маркер найден в шаблоне). Ничего не изменено.')
        return 0
    if REQUIRES not in template:
        print('Сначала примените скрипты 1 и 2 (apply_text_structure_update.py, apply_photo_tools_update.py). Ничего не изменено.')
        return 1
    new = {}
    try:
        for path, ops in FILE_OPS:
            new[path] = run_ops(read(path), ops, path)
        sections_text, about_message = restructure_about(read('content/sections.json'))
    except Miss as e:
        print('ОШИБКА: ' + str(e))
        print('Ничего не записано. Пришлите свежий снимок репозитория: файл, скорее всего, изменился после последнего снимка.')
        return 1
    if sections_text != read('content/sections.json'):
        new['content/sections.json'] = sections_text
    for path, block, guard in DOCS:
        if (ROOT / path).exists():
            old = read(path)
            if guard not in old:
                new[path] = old.rstrip('\n') + '\n' + block
    BACKUP.mkdir(exist_ok=True)
    for path in new:
        target = BACKUP / path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / path, target)
    gi = ROOT / '.gitignore'
    ignore = gi.read_text(encoding='utf-8') if gi.exists() else ''
    if f'.backup-{NAME}/' not in ignore:
        gi.write_text(ignore.rstrip('\n') + f'\n.backup-{NAME}/\n', encoding='utf-8')
    for path, text in new.items():
        (ROOT / path).write_text(text, encoding='utf-8')
    print('Изменено файлов: ' + str(len(new)))
    for path in new:
        print('  ' + path)
    print('My story: ' + about_message)
    print('\nСобираю сайт…')
    build = subprocess.run([sys.executable, 'scripts/build.py'], cwd=ROOT)
    print('\nЗапускаю тесты…')
    tests = subprocess.run([sys.executable, 'scripts/test_build.py'], cwd=ROOT)
    if build.returncode or tests.returncode:
        print('\nСборка или тесты НЕ прошли (см. выше). Оригиналы лежат в ' + BACKUP.name + '/')
        return 1
    print('\nГотово: сборка и тесты прошли. Оригиналы сохранены в ' + BACKUP.name + '/')
    return 0


if __name__ == '__main__':
    sys.exit(main())
