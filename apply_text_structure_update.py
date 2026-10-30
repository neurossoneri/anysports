#!/usr/bin/env python3
"""
Скрипт 1 из 3: структура панели, единая система текста, линии, тестовый блок фото.

Что делает:
  1. Панель /admin/: «+ Новый раздел» в любом месте страницы, «+ Вставить сюда» между блоками,
     удаление раздела (с кнопкой «Вернуть»), перестановка перетаскиванием (ручка ⠿) и выбором номера
     у разделов и блоков, полоска «порядок страницы».
  2. Три вида текста с общими токенами в одном месте CSS (:root, «--type-*»): Текст, Цитата, Фраза.
     Без курсива, без печати по буквам, без дорисовки линии, без переливов. Новый вид фразы «тихая»
     (обычный шрифт); рукописный Caveat остаётся выбором («рукописью» и «на плашке»).
  3. Убраны линии над подзаголовками и над списком тем; между шестью темами остаётся едва заметная линия.
  4. Из раздела Transformation удалён временный блок «Фото» (фото 7 и 2). Сами файлы фото не тронуты.
  5. Пустой раздел (без заголовка и без содержимого) сайт не рисует.
  6. Тесты и документация обновлены вместе с кодом.

Запуск из корня репозитория:   python3 apply_text_structure_update.py
Повторный запуск ничего не меняет. Если хоть одна замена не нашла своё место, ничего не записывается.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
NAME = 'text-structure'
MARK = 'text-system-v1'
BACKUP = ROOT / f'.backup-{NAME}'


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


def run_ops(src, ops, path):
    for kind, *args, label in ops:
        fn = {'text': op_text, 'line': op_line, 'after': op_after, 'before': op_before, 'range': op_range, 'regex': op_regex}[kind]
        src = fn(src, *args, f'{path}: {label}')
    return src


# ------------------------------------------------------------------ шаблон сайта
TOKENS = '''/* text-system-v1. Три вида текста определены здесь один раз: меняйте значения, и вся страница последует за ними.
   Текст (body): спокойный, для чтения. Цитата (quote): выразительная, цветом и размером. Фраза (statement): отдельное высказывание.
   Рукописный Caveat (--type-hand) нужен только там, где выбран «рукописью» или «на плашке». */
--type-body:400 clamp(1.08rem,1.4vw,1.2rem)/1.8 var(--serif);
--type-lead:400 clamp(1.4rem,2.6vw,2.1rem)/1.35 var(--serif);
--type-quote:400 clamp(1.5rem,2.6vw,2.2rem)/1.34 var(--serif);
--type-quote-long:400 clamp(1.2rem,1.9vw,1.55rem)/1.5 var(--serif);
--type-statement:500 clamp(1.75rem,3.2vw,2.8rem)/1.26 var(--serif);
--type-hand:500 clamp(2rem,3.6vw,3.2rem)/1.2 var(--hand);'''

STATEMENT_CSS = '''/* Фраза («тихая»): отдельное высказывание обычным шрифтом. Ничего не появляется и не движется. */
.aside-quiet { padding:clamp(8px,2vw,24px) 0; }
.statement { margin:0; max-width:22em; font:var(--type-statement); letter-spacing:-.015em; color:var(--c-text); text-wrap:balance; white-space:pre-line; }
.sec-centered .aside-quiet { margin-inline:auto; text-align:center; }
.sec-centered .aside-quiet .statement { margin-inline:auto; }'''

FINALE_CSS = '''/* Фразы, которые завершают раздел: по центру, на месте, без эффектов */
.finale { max-width:46rem; margin:clamp(56px,8vw,112px) auto 0; padding:clamp(32px,5vw,64px) clamp(8px,3vw,32px); text-align:center; }
.finale-line { display:block; width:72px; height:3px; margin:0 auto clamp(22px,3vw,34px); background:linear-gradient(90deg,var(--c-a),var(--c-b)); }
.finale .glyph { margin:0 auto 18px; width:40px; height:40px; }
.finale h3 { margin:0 0 clamp(14px,2vw,24px); font:500 clamp(2rem,4.4vw,3.4rem)/1.12 var(--serif); letter-spacing:-.025em; color:var(--c-text); }
.finale p { margin:0 auto; max-width:28em; font:400 clamp(1.25rem,2.1vw,1.7rem)/1.55 var(--serif); color:var(--c-text); }
.finale p + p { margin-top:.8em; }
.finale-hand .finale-note { margin:0 auto; font:500 clamp(2.1rem,5vw,3.8rem)/1.2 var(--hand); color:var(--c-b); text-wrap:balance; }'''

TEMPLATE_OPS = [
    ('after', '--float-hi:', TOKENS, 'токены текста в :root'),
    ('line', '.hero-q2 { margin-top:clamp(22px,3vw,36px)', '.hero-q2 { margin-top:clamp(22px,3vw,36px); max-width:24em; font:400 clamp(1.05rem,1.5vw,1.3rem)/1.6 var(--serif); color:var(--c-muted); animation:riseIn 1.6s var(--ease) 1.1s both; }', 'hero-q2 без курсива'),
    ('line', '.b-text p {', '.b-text p { font:var(--type-body); color:var(--c-text); max-width:56ch; }', 'текст: токен'),
    ('line', '.b-text.has-h {', '.b-text.has-h { margin-top:clamp(34px,5vw,64px); padding:0; }   /* подзаголовок отделяется воздухом, а не линией */', 'без линии над подзаголовком'),
    ('line', '.b-lead {', '.b-lead { max-width:24em; font:var(--type-lead); letter-spacing:-.01em; color:var(--c-text); }', 'вводная: токен'),
    ('line', '.sec-centered .b-lead {', '.sec-centered .b-lead { margin-inline:auto; text-align:center; font:400 clamp(1.25rem,2.1vw,1.7rem)/1.45 var(--serif); color:var(--c-a); }', 'центральная вводная без курсива'),
    ('line', '/* Highlighted phrase', '/* Quotation: upright serif, accent colour, larger and set in by space. No italics, no rule. */', 'комментарий цитаты'),
    ('line', '.pull {', '.pull { margin:clamp(40px,6vw,76px) 0; padding-left:clamp(0px,3vw,36px); font:var(--type-quote); letter-spacing:-.012em; color:var(--c-a); max-width:20em; white-space:pre-line; text-wrap:balance; }', 'цитата: без курсива и линии'),
    ('line', '.pull-long {', '.pull-long { font:var(--type-quote-long); max-width:26em; }', 'длинная цитата'),
    ('line', '.blocks > .pull {', '.blocks > .pull { margin-top:clamp(40px,6vw,76px); margin-bottom:clamp(40px,6vw,76px); }', 'отступы цитаты'),
    ('line', '.quote-text {', '.quote-text { margin:0; font:var(--type-hand); color:var(--c-a); text-wrap:balance; }', 'рукописная фраза: токен'),
    ('range', '.quote-stroke { display:block', '.is-written + .quote-stroke path', STATEMENT_CSS, 'без дорисовки линии, новая «тихая» фраза'),
    ('range', '/* Handwriting: text is written in real time */', '.js .is-written .ch', '', 'без печати по буквам (CSS)'),
    ('range', '/* Statements that close a section', '.finale-hand .quote-stroke {', FINALE_CSS, 'завершающие фразы без эффектов'),
    ('line', '.themes {', '.themes { margin-top:clamp(64px,9vw,120px); }', 'список тем: без линии сверху'),
    ('line', '.theme {', '.theme { padding:clamp(22px,3vw,34px) clamp(18px,2.4vw,30px) clamp(22px,3vw,34px) 0; border-top:1px solid color-mix(in srgb,var(--c-line) 55%,transparent); }', 'темы: едва заметная линия'),
    ('line', '.theme:nth-child(3n+2), .theme:nth-child(3n+3) { padding-left:clamp', '.theme:nth-child(3n+2), .theme:nth-child(3n+3) { padding-left:clamp(18px,2.4vw,30px); }', 'темы: без вертикальных линий'),
    ('line', '.theme:nth-child(even) {', '.theme:nth-child(even) { padding-left:clamp(18px,3vw,28px); }', 'темы на планшете: без вертикальной линии'),
    ('line', '@keyframes sheen', None, 'убран keyframes sheen'),
    ('line', '.quote-stroke path { stroke-dashoffset:0; }', None, 'убрано правило reduced-motion для линии'),
    ('regex', r"    /\* ---------- Handwriting: each quote is written letter by letter ---------- \*/.*?\n    function watch\(", '    function watch(', 'JS печати по буквам удалён'),
    ('line', "$$('[data-write]').forEach(splitWrite);", None, 'вызов splitWrite'),
    ('line', "watch('[data-write]'", None, 'наблюдатель data-write'),
    ('line', "watch('[data-finale]'", None, 'наблюдатель data-finale'),
]

# ------------------------------------------------------------------ сборка сайта
BUILD_OPS = [
    ('line', 'ASIDE_LOOKS = ', "ASIDE_LOOKS = (('quiet', 'Тихая: обычным шрифтом, без рамки'), ('hand', 'Рукописью (Caveat), без плашки'), ('panel', 'На тёмной плашке (можно с фото за текстом)'))", 'виды фразы'),
    ('line', 'STROKE_SVG = ', None, 'константа дорисовки линии больше не нужна'),
    ('line', "'label': 'Цитата в тексте', 'add': 'Цитата',", "'label': 'Цитата', 'add': 'Цитата',", 'подпись блока «Цитата»'),
    ('line', "'hint': 'Выделенная фраза внутри текста", "'hint': 'Выделенная мысль внутри текста: крупнее, цветом, без курсива и без линии. Для отдельного высказывания лучше блок «Фраза».',", 'подсказка цитаты'),
    ('line', "'label': 'Фраза сбоку', 'add': 'Фраза сбоку',", "'label': 'Фраза', 'add': 'Фраза',", 'подпись блока «Фраза»'),
    ('line', "'hint': 'Рукописная фраза, вынесенная в сторону", "'hint': 'Отдельное высказывание. «Тихая» по умолчанию, рукописью (Caveat) только когда это уместно. В разделе с боковой колонкой стоит сбоку, в остальных прямо в тексте. Перенос строки здесь это перенос строки во фразе.',", 'подсказка фразы'),
    ('line', "{'name': 'look', 'label': 'Оформление', 'type': 'select', 'options': _opts(ASIDE_LOOKS)", "{'name': 'look', 'label': 'Вид фразы', 'type': 'select', 'options': _opts(ASIDE_LOOKS), 'default': 'quiet'},", 'вид фразы по умолчанию'),
    ('text', "        if block['look'] == 'hand':\n            return f'<div class=\"b b-aside aside-hand\" {number}><blockquote class=\"quote-text\" data-write>{esc(text)}</blockquote>{STROKE_SVG}</div>'\n",
     "        if block['look'] == 'quiet':\n            return f'<div class=\"b b-aside aside-quiet\" {number}><p class=\"statement\">{esc(text)}</p></div>'\n        if block['look'] == 'hand':\n            return f'<div class=\"b b-aside aside-hand\" {number}><blockquote class=\"quote-text\">{esc(text)}</blockquote></div>'\n", 'фраза: тихая и рукописная'),
    ('text', "<blockquote class=\"quote-text\" data-write>{esc(text)}</blockquote>{STROKE_SVG}</div>'\n    if kind == 'photos':", "<blockquote class=\"quote-text\">{esc(text)}</blockquote></div>'\n    if kind == 'photos':", 'фраза на плашке'),
    ('text', "return (f'<div class=\"b b-finale finale\" {number} data-finale><span", "return (f'<div class=\"b b-finale finale\" {number}><span", 'finale без data-finale'),
    ('text', "return (f'<div class=\"b b-hand finale finale-hand\" {number} data-finale><span class=\"finale-line\" aria-hidden=\"true\"></span>'\n                    f'<p class=\"finale-note\" data-write>{esc(block[\"body\"].strip())}</p>{STROKE_SVG}</div>')",
     "return (f'<div class=\"b b-hand finale finale-hand\" {number}><span class=\"finale-line\" aria-hidden=\"true\"></span>'\n                    f'<p class=\"finale-note\">{esc(block[\"body\"].strip())}</p></div>')", 'рукописная строка без эффектов'),
    ('text', "class=\"b b-quote pull{\" pull-long\" if small else \"\"}\" {number} data-fade>", "class=\"b b-quote pull{\" pull-long\" if small else \"\"}\" {number}>", 'цитата видна сразу'),
    ('text', "final = ('<div class=\"finale\" data-finale><span", "final = ('<div class=\"finale\"><span", 'итог списка тем без data-finale'),
    ('before', 'def take_section(template, sid):', '''def section_has_content(section):
    """A text section with no title and nothing to show is not drawn (a new section the owner has not filled in yet)."""
    return bool(section['title'].strip()) or any(block_has_content(b) for b in section['blocks'] if b)


''', 'функция section_has_content'),
    ('text', "        if section['type'] == 'text':\n            parts.append(render_text_section(section, number, tone, ctx))",
     "        if section['type'] == 'text':\n            if section_has_content(section):\n                parts.append(render_text_section(section, number, tone, ctx))", 'пустой раздел не рисуется'),
]

# ------------------------------------------------------------------ .pages.yml (подписи для Pages CMS)
PAGES_OPS = [
    ('text', "          - value: quote\n            label: Цитата в тексте\n          - value: aside\n            label: Фраза сбоку\n",
     "          - value: quote\n            label: Цитата\n          - value: aside\n            label: Фраза\n", 'подписи типов блоков'),
    ('text', "      - name: look\n        label: Оформление\n        type: select\n        options:\n          values:\n          - value: plain\n",
     "      - name: look\n        label: Оформление (у Фразы quiet — тихая, hand — рукописью, panel — на плашке)\n        type: select\n        options:\n          values:\n          - value: quiet\n            label: Фраза · тихая\n          - value: plain\n", 'вид «тихая» для CMS'),
]

# ------------------------------------------------------------------ панель
ADMIN_HELPERS = '''function newSectionId() { const used = new Set(S.page.sections.map(s => s.id)); let n = 1; while (used.has('section-' + n)) n++; return 'section-' + n; }
function newSection() { return { id: newSectionId(), type: 'text', title: '', layout: 'column', blocks: [newBlock('text')] }; }
function insertAt(list, index, item) { list.splice(Math.max(0, Math.min(index, list.length)), 0, item); }'''

ADMIN_DOM = '''/* ----- adding at a chosen place, deleting, dragging ----- */
function addSectionAt(at) { const sec = newSection(); insertAt(S.page.sections, at, sec); S.open.add(sec.id); afterStructure({ sid: sec.id, fresh: true }); }
function addBlockAt(sec, at, type) { insertAt(sec.blocks, at, newBlock(type)); S.open.add(sec.id); afterStructure({ sid: sec.id, block: at, fresh: true }); }
function deleteSection(si) {
  const sec = S.page.sections[si], name = sec.title || sec.id;
  if (!confirm(`Удалить раздел ${si + 1} «${name}» вместе со всеми его блоками (${sec.blocks.length})?\\n\\nСразу после удаления появится кнопка «Вернуть раздел». Файлы фотографий не удаляются.`)) return;
  S.page.sections.splice(si, 1);
  (S.removed = S.removed || []).push({ sec, at: si });
  afterStructure(null);
  setNotice('warn', [`Раздел «${name}» удалён. `, el('button', { class: 'btn small', type: 'button', onclick: undoDeleteSection }, 'Вернуть раздел')]);
}
function undoDeleteSection() {
  const last = (S.removed || []).pop(); if (!last) return;
  insertAt(S.page.sections, last.at, last.sec); S.open.add(last.sec.id);
  setNotice('ok', null); afterStructure({ sid: last.sec.id });
}
/** A thin row between two cards: says where the new thing will appear. */
function sectionGap(at) {
  const total = S.page.sections.length;
  const where = at === 0 ? 'в начало (сразу после первого экрана)' : at >= total ? 'в самый конец' : `между разделами ${at} и ${at + 1}`;
  return el('div', { class: 'gap' }, el('button', { class: 'btn ghost small', type: 'button', onclick: () => addSectionAt(at) }, '+ Новый раздел ' + where));
}
function blockGap(sec, si, at) {
  const menu = el('span', { class: 'gapmenu', hidden: true }, S.schema.page.blockTypes.map(spec => el('button', { class: 'btn small', type: 'button', onclick: () => addBlockAt(sec, at, spec.type) }, spec.add)));
  const open = el('button', { class: 'btn ghost small', type: 'button', 'aria-expanded': 'false', onclick: () => { menu.hidden = !menu.hidden; open.setAttribute('aria-expanded', String(!menu.hidden)); } },
    at === 0 ? '+ Вставить в начало раздела' : `+ Вставить сюда (будет блок ${si + 1}.${at + 1})`);
  return el('div', { class: 'gap' }, open, menu);
}
function pageStrip() {
  const short = s => { const t = s.type === 'text' ? (s.title || '(без заголовка)') : ({ contact: 'Контакты', qa: 'Q&A' })[s.type]; return t.length > 26 ? t.slice(0, 26) + '…' : t; };
  return el('div', { class: 'strip', role: 'group', 'aria-label': 'Порядок разделов на странице' }, el('span', { class: 'muted' }, 'Страница сверху вниз: первый экран →'),
    ...S.page.sections.map((sec, i) => el('button', { class: 'chipbtn', type: 'button', onclick: () => jumpToSection(sec.id) }, `${i + 1} · ${short(sec)}`)));
}
function jumpToSection(id) {
  const node = document.querySelector(`.pcard[data-key="${id}"]`); if (!node) return;
  S.open.add(id); setCardOpen(node, true); node.scrollIntoView({ block: 'start', behavior: 'smooth' });
}
let dragFrom = null;
const gripButton = label => el('button', { class: 'grip', type: 'button', 'aria-label': label + '. Или выберите номер в списке рядом.', title: 'Потяните, чтобы переставить' }, '⠿');
/** Dragging starts only from the handle, so text selection inside the card keeps working. Touch screens use the position list. */
function makeDraggable(node, grip, { group, index, onMove }) {
  const off = () => { node.draggable = false; };
  const clear = () => document.querySelectorAll('.dragging, .drop-before, .drop-after').forEach(n => n.classList.remove('dragging', 'drop-before', 'drop-after'));
  grip.addEventListener('mousedown', () => { node.draggable = true; });
  grip.addEventListener('mouseup', off);
  node.addEventListener('dragstart', e => {
    if (!node.draggable) return;
    e.stopPropagation(); dragFrom = { group, index };
    try { e.dataTransfer.setData('text/plain', group + ':' + index); e.dataTransfer.effectAllowed = 'move'; } catch (err) {}
    node.classList.add('dragging');
  });
  node.addEventListener('dragend', () => { dragFrom = null; off(); clear(); });
  node.addEventListener('dragover', e => {
    if (!dragFrom || dragFrom.group !== group || dragFrom.index === index) return;
    e.preventDefault(); e.stopPropagation();
    const r = node.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2;
    node.classList.toggle('drop-after', after); node.classList.toggle('drop-before', !after);
  });
  node.addEventListener('dragleave', e => { if (!node.contains(e.relatedTarget)) node.classList.remove('drop-before', 'drop-after'); });
  node.addEventListener('drop', e => {
    if (!dragFrom || dragFrom.group !== group) return;
    e.preventDefault(); e.stopPropagation();
    const r = node.getBoundingClientRect(), after = e.clientY > r.top + r.height / 2, from = dragFrom.index;
    let to = after ? index + 1 : index; if (from < to) to -= 1;
    dragFrom = null; clear(); onMove(from, to);
  });
}'''

BLOCK_CARD = '''function blockCard(sec, si, b, bi) {
  const spec = blockSpec(b.type), last = sec.blocks.length - 1, label = `${si + 1}.${bi + 1}`;
  const fields = spec.fields.filter(f => !f.showIf || Object.entries(f.showIf).every(([k, vals]) => vals.includes(b[k]))).map(f => makeField({
    label: f.label, value: b[f.name], type: f.type, options: f.options, redraw: f.name === 'look' && !!spec.fields.some(x => x.showIf),
    hint: f.name === 'text' && b.type === 'aside' ? 'Перенос строки здесь это перенос строки во фразе.' : '', onSet: val => { b[f.name] = val; } }));
  const grip = gripButton(`Перетащить блок ${label}`);
  const pos = el('select', { class: 'pos', 'aria-label': `Положение блока ${label} в разделе`, onchange: e => moveBlock(sec, bi, Number(e.target.value)) },
    sec.blocks.map((_, k) => el('option', { value: String(k) }, '№ ' + (k + 1))));
  pos.value = String(bi);
  const node = el('div', { class: 'blk', 'data-bi': String(bi) },
    el('div', { class: 'bhead' }, grip, el('span', { class: 'num' }, label), el('span', { class: 'bname' }, blockName(b)), el('span', { class: 'bprev' }, blockPreview(b)), pos,
      miniBtn('▲', `Поднять блок ${label} выше`, () => moveBlock(sec, bi, bi - 1), bi === 0),
      miniBtn('▼', `Опустить блок ${label} ниже`, () => moveBlock(sec, bi, bi + 1), bi === last),
      el('button', { class: 'btn danger small', type: 'button', 'aria-label': `Удалить блок ${label}`, onclick: () => deleteBlock(sec, si, bi) }, 'Удалить')),
    spec.hint ? el('p', { class: 'hint', style: 'margin:0 0 10px' }, spec.hint) : null,
    el('div', { class: 'flds' }, fields));
  makeDraggable(node, grip, { group: 'blk:' + sec.id, index: bi, onMove: (from, to) => moveBlock(sec, from, to) });
  return node;
}
'''

TEXT_SECTION_BODY = '''function textSectionBody(sec, si) {
  const layoutField = makeField({ label: 'Расположение раздела', value: sec.layout, type: 'select', options: S.schema.page.layouts,
    hint: 'Боковая колонка нужна блокам «Фраза» (если она не тихая) и фото с пометкой «сбоку»; если таких блоков нет, раздел идёт одной колонкой.', onSet: val => { sec.layout = val; } });
  const titleField = makeField({ label: 'Заголовок раздела', value: sec.title, type: 'string', onSet: val => { sec.title = val; } });
  const adds = S.schema.page.blockTypes.map(spec => el('button', { class: 'btn small', type: 'button', onclick: () => addBlock(sec, spec.type) }, '+ ' + spec.add));
  const original = secOrig(sec.id);
  const items = [];
  sec.blocks.forEach((b, bi) => { items.push(blockGap(sec, si, bi), blockCard(sec, si, b, bi)); });
  return el('div', {},
    el('div', { class: 'flds' }, titleField, layoutField),
    el('h3', { class: 'subh' }, sec.blocks.length ? 'Блоки раздела (идут сверху вниз)' : 'В разделе пока нет блоков'),
    ...items,
    el('div', { class: 'addrow' }, el('span', { class: 'muted' }, 'Добавить в конец раздела:'), ...adds),
    el('div', { class: 'row' },
      original && secChanged(sec) ? el('button', { class: 'btn ghost small', type: 'button',
        onclick: () => { S.page.sections[si] = clone(original); afterStructure({ sid: sec.id }); } }, '↩ Вернуть раздел как было') : null,
      el('button', { class: 'btn danger small', type: 'button', onclick: () => deleteSection(si) }, 'Удалить раздел')));
}
'''

SECTION_CARD = '''function sectionCard(sec, si) {
  const total = S.page.sections.length, isText = sec.type === 'text';
  const pos = el('select', { class: 'pos', 'aria-label': `Положение раздела «${isText ? sec.title : sec.type}» в списке`, onchange: e => moveSection(si, Number(e.target.value)) },
    S.page.sections.map((_, k) => el('option', { value: String(k) }, '№ ' + (k + 1))));
  pos.value = String(si);
  const grip = gripButton(`Перетащить раздел ${si + 1}`);
  const controls = el('span', { class: 'ctl' }, grip, pos, miniBtn('▲', `Поднять раздел ${si + 1} выше`, () => moveSection(si, si - 1), si === 0),
    miniBtn('▼', `Опустить раздел ${si + 1} ниже`, () => moveSection(si, si + 1), si === total - 1));
  let body;
  if (isText) body = textSectionBody(sec, si);
  else if (sec.type === 'contact') body = el('div', { class: 'flds' }, groupByName('contact').fields.map(f => groupField(groupByName('contact'), f)));
  else body = el('div', {}, el('div', { class: 'flds' }, groupByName('qa').fields.map(f => groupField(groupByName('qa'), f))),
    el('h3', { class: 'subh' }, groupByName('free').label), el('div', { class: 'flds' }, groupByName('free').fields.map(f => groupField(groupByName('free'), f))));
  const node = card({ key: sec.id, num: si + 1, title: isText ? (sec.title || '(без заголовка)') : S.schema.page.sectionLabels[sec.type],
    sub: isText ? sec.blocks.length + ' бл.' : 'форма', sid: sec.id, link: sec.id, controls, body, open: S.open.has(sec.id) });
  makeDraggable(node, grip, { group: 'sec', index: si, onMove: (from, to) => moveSection(from, to) });
  return node;
}
'''

ADMIN_CSS = '''.gap{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:4px 0}
.gap>.btn{opacity:.78}.gap>.btn:hover,.gap>.btn:focus-visible{opacity:1}
.gapmenu{display:inline-flex;flex-wrap:wrap;gap:6px}
.grip{border:0;background:none;cursor:grab;color:var(--muted);font-size:1.1rem;line-height:1;padding:4px 6px;border-radius:6px}
.grip:hover{background:var(--soft)}
.dragging{opacity:.45}
.drop-before{box-shadow:0 -3px 0 var(--blue)}
.drop-after{box-shadow:0 3px 0 var(--blue)}
.strip{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:0 0 14px}
.strip .chipbtn{border:1px solid var(--line);background:#fff;border-radius:8px;padding:4px 10px;cursor:pointer;font-size:.84rem;font-weight:600;color:var(--ink)}
.strip .chipbtn:hover{background:var(--soft)}'''

ADMIN_OPS = [
    ('before', 'const secOrig = id =>', ADMIN_HELPERS, 'вспомогательные функции разделов'),
    ('text', 'newBlock, moveItem, pageChangeCount,', 'newBlock, newSection, newSectionId, insertAt, moveItem, pageChangeCount,', 'экспорт для тестов'),
    ('after', 'function addBlock(sec, type)', ADMIN_DOM, 'добавление на место, удаление, перетаскивание'),
    ('regex', r"function blockCard\(sec, si, b, bi\) \{.*?\n\}\n", BLOCK_CARD, 'карточка блока'),
    ('regex', r"function textSectionBody\(sec, si\) \{.*?\n\}\n", TEXT_SECTION_BODY, 'тело раздела'),
    ('regex', r"function sectionCard\(sec, si\) \{.*?\n\}\n", SECTION_CARD, 'карточка раздела'),
    ('line', 'const sections = S.page.sections.map(sectionCard);',
     'const sections = []; S.page.sections.forEach((sec, i) => { sections.push(sectionGap(i), sectionCard(sec, i)); }); sections.push(sectionGap(S.page.sections.length));', 'список разделов с промежутками'),
    ('text', "el('h2', { class: 'subh' }, 'Разделы страницы (сверху вниз)'), ...sections,", "el('h2', { class: 'subh' }, 'Разделы страницы (сверху вниз)'), pageStrip(), ...sections,", 'полоска порядка'),
    ('text', 'текст, цитата, фраза сбоку, фото). Всё пронумеровано: раздел 3, его блок 3.2. Номер можно выбрать в списке или двигать стрелками ▲▼, блоки добавляются и удаляются внутри раздела.',
     'текст, цитата, фраза, фото). Всё пронумеровано: раздел 3, его блок 3.2. Перетаскивайте за ручку ⠿ или выберите номер в списке; кнопки «+» между карточками добавляют раздел или блок ровно туда.', 'вводный текст вкладки'),
    ('after', 'const q = S.filter.trim().toLowerCase();', "document.querySelectorAll('.gap').forEach(g => { g.hidden = !!q; });", 'поиск прячет промежутки'),
    ('after', '.addrow{', ADMIN_CSS, 'стили панели'),
]

# ------------------------------------------------------------------ тесты
TEST_CHECK = '''def check_text_system(builder):
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
        assert re.findall(r'<section class="band[^"]*" id="([\\w-]+)"', home) == ['hero', 'one', 'two', 'contact', 'qa'], 'a section with nothing in it is not drawn'
        assert re.findall(r'data-sec="(\\d+)"', home) == ['1', '3', '4', '5'], 'numbers still count the hidden empty section, so they match the dashboard'
        assert 'class="b b-aside aside-quiet"' in home and '<p class="statement">Quiet statement</p>' in home and 'aside-hand' in home
        assert 'data-write' not in home and 'quote-stroke' not in home and 'data-finale' not in home, 'nothing is typed, drawn or revealed'
        assert 'data-fade' not in re.search(r'<blockquote class="b b-quote[^>]*>', home).group(0), 'a quotation is visible at once'
        rule = lambda selector: re.search(re.escape(selector) + r' \\{([^}]*)\\}', css).group(1)
        for selector in ('.pull', '.pull-long', '.finale p', '.hero-q2', '.sec-centered .b-lead', '.statement'):
            assert 'italic' not in rule(selector), f'{selector}: no italics'
        assert 'border' not in rule('.pull') and 'border' not in rule('.b-text.has-h') and 'border' not in rule('.themes'), 'no rules around quotations, subheadings or the list of themes'
        assert 'border-left' not in rule('.theme'), 'the themes are not cards'
        root = re.search(r':root \\{([^}]*)\\}', css).group(1)
        for token in ('--type-body', '--type-quote', '--type-statement', '--type-hand'):
            assert token in root, f'text style {token} is defined centrally'
        assert 'var(--type-quote)' in rule('.pull') and 'var(--type-statement)' in rule('.statement') and 'var(--type-hand)' in rule('.quote-text')
    assert builder.default_block('aside')['look'] == 'quiet', 'a new statement is the quiet one; handwriting is a choice'


'''

TEST_OPS = [
    ('text', "'aria-describedby=\"form-status\"' in template and 'data-write' in template",
     "'aria-describedby=\"form-status\"' in template and 'data-write' not in template and 'splitWrite' not in template", 'печати по буквам больше нет в шаблоне'),
    ('line', "assert 'quickBar' not in admin and 'photoMap' not in admin and 'backdrop-filter' not in admin",
     "assert 'quickBar' not in admin and 'photoMap' not in admin and 'backdrop-filter' not in admin, 'dashboard: a plain list, no photo map, no blur'\n"
     "for needed in ('addSectionAt', 'deleteSection', 'undoDeleteSection', 'sectionGap', 'blockGap', 'addBlockAt', 'makeDraggable', 'pageStrip'):\n"
     "    assert needed in admin, f'dashboard lacks {needed}'", 'панель: вставка на место, удаление, перетаскивание'),
    ('line', "assert 'aside-hand' in change and 'finale-hand' in about",
     "assert 'aside-hand' in change and 'finale-hand' in about and 'data-write' not in home and 'quote-stroke' not in home and 'data-finale' not in home, 'statements are still: no typing, no drawn line, no reveal'", 'фразы без эффектов'),
    ('line', "letter = re.search(", None, 'плавность: проверка букв'),
    ('line', "assert 'filter' not in letter", "assert '.js .ch' not in css and '.is-written' not in css, 'no letter-by-letter writing'", 'плавность: букв больше нет'),
    ('before', 'def main():', TEST_CHECK.rstrip('\n') + '\n\n', 'новая проверка текстовой системы'),
    ('after', 'check_sections(builder)', 'check_text_system(builder)', 'вызов новой проверки'),
]

# ------------------------------------------------------------------ тестовый блок фото в Transformation
def drop_test_photos(text):
    """Удаляет последний блок «Фото» (7 и 2, в тексте, без подписи) раздела change. Возвращает (текст, удалено?)."""
    data = json.loads(text)
    for section in data.get('sections', []):
        if section.get('id') != 'change' or not section.get('blocks'):
            continue
        block = section['blocks'][-1]
        if (block.get('type') == 'photos' and block.get('s1') == '7' and block.get('s2') == '2' and not block.get('s3')
                and block.get('place') == 'inline' and not block.get('caption') and not block.get('alt')):
            section['blocks'].pop()
            return json.dumps(data, ensure_ascii=False, indent=2) + '\n', True
    return text, False


# ------------------------------------------------------------------ документация (дописывается с защитой от дублей)
DOC_DASHBOARD = '''
## Разделы и блоки на нужном месте, три вида текста (скрипт apply_text_structure_update.py)

**Добавить.** Между любыми двумя карточками разделов есть строка «+ Новый раздел между разделами 2 и 3» (она же в начале и в конце списка). Новый раздел появляется ровно там, с одним пустым блоком «Текст». Внутри раздела перед каждым блоком стоит «+ Вставить сюда (будет блок 3.2)»: нажмите, выберите вид блока. Кнопки «Добавить в конец раздела» остались.

**Переставить.** Потяните карточку за ручку **⠿** (слева в заголовке раздела или блока) или выберите номер в списке «№» рядом. На телефоне и планшете перетаскивания нет, там работает список «№» и кнопки ▲ ▼.

**Удалить раздел.** Кнопка «Удалить раздел» внизу раскрытого раздела (с подтверждением). Сразу после удаления вверху появляется «Вернуть раздел». Фотографии при этом не удаляются. Раздел без заголовка и без содержимого сайт не показывает, так что новый пустой раздел до заполнения никому не виден.

**Порядок страницы.** Над списком разделов лежит полоска с номерами и названиями: нажмите, чтобы перейти к разделу. Она обновляется при перестановке и добавлении (при наборе заголовка обновится, когда вы что-то передвинете).

**Три вида текста.**

| Вид | Для чего | Как выглядит |
|---|---|---|
| **Текст** | рассказ | спокойный, удобный для чтения; оформления «обычный», «крупная вводная», «буквица», «плашка» |
| **Цитата** | выделенная мысль внутри текста | крупнее, акцентным цветом, без курсива и без линии слева |
| **Фраза** | отдельное высказывание | вид «тихая» (по умолчанию), «рукописью» (Caveat) или «на плашке» (можно с фото за ней) |

Рукописный Caveat теперь выбор, а не правило: берите его там, где почерк добавляет личного. Все три вида определены в одном месте шаблона (`templates/index.html`, блок «text-system-v1» в `:root`, переменные `--type-*`), поэтому размеры и шрифты меняются там один раз для всей страницы. Ничего не печатается по буквам, не дорисовывается и не переливается: фразы видны сразу.

Линий над подзаголовками нет. Между шестью темами остаётся едва заметная линия.
'''

DOC_CONCEPT = '''
## 14. Единая система текста (скрипт apply_text_structure_update.py)

Заменяет в разделе 5 «Handwriting reveal» и в разделе 12 пункт про цитаты «от руки».

- Три вида: **Текст**, **Цитата**, **Фраза**. Определены один раз в `:root` шаблона (`--type-body`, `--type-quote`, `--type-statement`, `--type-hand`).
- **Без курсива** у цитат и фраз. Цитата выделяется размером, акцентным цветом и отступом, без линии слева.
- **Без печати по буквам, дорисовки линии и переливов.** Тексты и фразы видны сразу. Мягкое появление при прокрутке осталось только у обычного текста, фото и списка тем.
- **Caveat выборочно.** Фраза по умолчанию «тихая» (обычный шрифт). Рукописью она бывает, когда это выбрано в блоке.
- **Линии убраны** над подзаголовками и над списком тем. Структуру задают воздух и размер заголовка. Между шестью темами едва заметная линия, вертикальных линий нет.
'''

DOC_README = '''
## Единая система текста и структура страницы (октябрь 2026)

- **Три вида текста** (Текст, Цитата, Фраза) определены в `templates/index.html` одним блоком переменных `--type-*`. Без курсива, без эффектов появления у цитат и фраз; Caveat только там, где выбран «рукописью» или «на плашке».
- **Панель.** Новый раздел и новый блок добавляются на любое место («+ Новый раздел между…», «+ Вставить сюда»). Разделы и блоки переставляются за ручку ⠿ или выбором номера. Раздел можно удалить и тут же вернуть. Подробности в `docs/DASHBOARD.md`.
- Раздел без заголовка и без содержимого на сайте не рисуется.
- Временный блок «Фото» (7 и 2) из Transformation убран. Файлы фотографий остались в `media/`.
'''

DOC_REVIEW = '''
- [ ] Новая система текста (`apply_text_structure_update.py`): пройдитесь по странице. Цитаты теперь без курсива и без линии, фразы видны сразу. Подходит ли рукописное «This journey continues…» в конце «My story» или его лучше сделать тихой фразой? Нужно ли сохранить рукописный вид у фразы на плашке во введении?
'''

DOCS = [
    ('docs/DASHBOARD.md', DOC_DASHBOARD, 'apply_text_structure_update.py'),
    ('docs/CONCEPT.md', DOC_CONCEPT, '## 14. Единая система текста'),
    ('README.md', DOC_README, '## Единая система текста и структура страницы'),
    ('docs/CONTENT-REVIEW.md', DOC_REVIEW, 'Новая система текста (`apply_text_structure_update.py`)'),
]


# ------------------------------------------------------------------ main
def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def main():
    needed = ['scripts/build.py', 'scripts/test_build.py', 'templates/index.html', 'admin/index.html', '.pages.yml', 'content/sections.json']
    absent = [p for p in needed if not (ROOT / p).exists()]
    if absent:
        print('Запустите скрипт из корня репозитория. Не найдено: ' + ', '.join(absent))
        return 1
    template = read('templates/index.html')
    if MARK in template:
        print('Это обновление уже применено (маркер найден в шаблоне). Ничего не изменено.')
        return 0

    # 1. все правки сначала в памяти
    new = {}
    try:
        new['templates/index.html'] = run_ops(template, TEMPLATE_OPS, 'templates/index.html')
        new['scripts/build.py'] = run_ops(read('scripts/build.py'), BUILD_OPS, 'scripts/build.py')
        new['.pages.yml'] = run_ops(read('.pages.yml'), PAGES_OPS, '.pages.yml')
        new['admin/index.html'] = run_ops(read('admin/index.html'), ADMIN_OPS, 'admin/index.html')
        new['scripts/test_build.py'] = run_ops(read('scripts/test_build.py'), TEST_OPS, 'scripts/test_build.py')
    except Miss as e:
        print('ОШИБКА: ' + str(e))
        print('Ничего не записано. Пришлите свежий снимок репозитория: файл, скорее всего, изменился после последнего снимка.')
        return 1
    sections_text, removed = drop_test_photos(read('content/sections.json'))
    if removed:
        new['content/sections.json'] = sections_text
    for path, block, guard in DOCS:
        if (ROOT / path).exists():
            old = read(path)
            if guard not in old:
                new[path] = old.rstrip('\n') + '\n' + block
    # 2. бэкап и запись
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
    print('Тестовый блок «Фото» в Transformation: ' + ('удалён (файлы фото не тронуты)' if removed else 'не найден в ожидаемом виде, не трогала'))
    # 3. сборка и тесты
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
