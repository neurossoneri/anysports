#!/usr/bin/env python3
"""
Скрипт 2 из 3: фото. Библиотека, выбор и загрузка прямо в блоке, кадрирование, композиции, лайтбокс.

Что делает:
  1. Вкладка «Фотографии» становится библиотекой: все файлы media/ с миниатюрами, «где используется»,
     загрузка (в том числе перетаскиванием), удаление неиспользуемых. Прежние семь номеров остаются.
  2. Блок «Фото»: выбор файла плиткой с превью, загрузка нового фото прямо из окна выбора, «Заменить» и «Убрать»
     без пересборки блока, кадрирование перетаскиванием (положение и масштаб, форма кадра на компьютере и телефоне).
     Оригинальный файл не меняется.
  3. Композиции фото: одно, широкое, спокойная пара, крупное и малое (асимметрия), три; на телефоне раскладка перестраивается.
  4. Необязательный лайтбокс (по умолчанию выключен), без библиотек.
  5. Тесты и документация обновлены вместе с кодом.

Нужен установленный скрипт 1 (apply_text_structure_update.py).
Запуск из корня репозитория:   python3 apply_photo_tools_update.py
Повторный запуск ничего не меняет. Если хоть одна замена не нашла своё место, ничего не записывается.
"""
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
NAME = 'photo-tools'
MARK = 'photo-tools-v1'
BACKUP = ROOT / f'.backup-{NAME}'
REQUIRES = 'text-system-v1'   # маркер скрипта 1 в шаблоне


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


# ------------------------------------------------------------------ шаблон сайта: композиции фото, лайтбокс
PHOTO_CSS = r'''/* photo-tools-v1. Композиции фото. Форма рамки каждого фото приходит из сборки (--ar на компьютере, --ar-m на телефоне),
   кадрирование (положение и масштаб) записано на самом фото, поэтому файл оригинала никогда не меняется. */
.b-photos[data-comp] .photo { aspect-ratio:var(--ar,4/5); }
.b-photos[data-comp] .photo:nth-child(n) { margin-top:0; }
.b-photos[data-comp="single"] { display:block; max-width:420px; margin-inline:auto; }
.b-photos[data-comp="wide"] { display:block; max-width:none; margin-inline:0; }
.b-photos[data-comp="calm-pair"], .b-photos[data-comp="lead-small"], .b-photos[data-comp="trio"] { grid-template-columns:repeat(12,minmax(0,1fr)); align-items:end; }
.b-photos[data-comp="calm-pair"] .photo:nth-child(1) { grid-column:1 / span 7; }
.b-photos[data-comp="calm-pair"] .photo:nth-child(2) { grid-column:9 / span 3; }
.b-photos[data-comp="lead-small"] .photo:nth-child(1) { grid-column:1 / span 7; }
.b-photos[data-comp="lead-small"] .photo:nth-child(2) { grid-column:9 / span 4; }
.b-photos[data-comp="trio"] .photo:nth-child(1) { grid-column:1 / span 7; grid-row:1 / span 2; align-self:start; }
.b-photos[data-comp="trio"] .photo:nth-child(2) { grid-column:8 / span 5; grid-row:1; align-self:start; }
.b-photos[data-comp="trio"] .photo:nth-child(3) { grid-column:9 / span 4; grid-row:2; }
.sec-centered .b-photos[data-comp]:not([data-comp="single"]) { width:min(62rem,calc(100vw - 48px)); margin-left:calc(50% - min(31rem,50vw - 24px)); }
.rail .b-photos[data-comp] { display:grid; grid-template-columns:1fr; max-width:none; margin-inline:0; }
.rail .b-photos[data-comp] .photo { grid-column:auto; grid-row:auto; align-self:auto; }
@media (max-width:700px) {
  .b-photos[data-comp] .photo { aspect-ratio:var(--ar-m,var(--ar,4/5)); }
  .b-photos[data-comp="calm-pair"] .photo:nth-child(1) { grid-column:1 / -1; }
  .b-photos[data-comp="calm-pair"] .photo:nth-child(2) { grid-column:6 / -1; margin-top:-9%; box-shadow:0 0 0 clamp(4px,1.2vw,8px) var(--c-bg,transparent); z-index:1; }
  .b-photos[data-comp="lead-small"] .photo:nth-child(1) { grid-column:1 / span 10; }
  .b-photos[data-comp="lead-small"] .photo:nth-child(2) { grid-column:6 / -1; margin-top:-22%; box-shadow:0 0 0 clamp(4px,1.2vw,8px) var(--c-bg,transparent); z-index:1; }
  .b-photos[data-comp="trio"] .photo:nth-child(1) { grid-column:1 / -1; grid-row:auto; }
  .b-photos[data-comp="trio"] .photo:nth-child(2) { grid-column:1 / span 6; grid-row:auto; }
  .b-photos[data-comp="trio"] .photo:nth-child(3) { grid-column:7 / -1; grid-row:auto; margin-top:10%; }
  .rail .b-photos[data-comp] .photo:nth-child(n) { grid-column:auto; margin-top:0; box-shadow:none; }
}
/* An optional larger view: a quiet dark overlay, closed by a tap, Esc or the button. */
.zoom-btn { position:absolute; inset:0; z-index:3; padding:0; border:0; background:transparent; cursor:zoom-in; }
.zoom-btn:focus-visible { outline:2px solid var(--blue-hi); outline-offset:-5px; }
#lightbox { width:100vw; height:100vh; max-width:none; max-height:none; padding:0; border:0; background:transparent; color:#fff; }
#lightbox::backdrop { background:rgba(6,18,30,.93); }
#lightbox img { position:absolute; inset:0; margin:auto; width:auto; height:auto; max-width:92vw; max-height:88vh; object-fit:contain; }
.lb-close { position:fixed; top:14px; right:18px; z-index:2; width:44px; height:44px; border:1px solid rgba(255,255,255,.35); border-radius:var(--r-pill); background:rgba(6,18,30,.5); color:#fff; font:400 1.6rem/1 var(--sans); cursor:pointer; }'''

PHOTO_JS = r'''/* ---------- Photographs: an optional larger view (a setting of the photo block) ---------- */
$$('.b-photos[data-lightbox] .photo').forEach(frame => {
  const image = $('img', frame);
  if (!image || !image.getAttribute('src')) return;
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'zoom-btn';
  button.setAttribute('aria-label', 'Enlarge photograph' + (image.alt ? ': ' + image.alt : ''));
  button.addEventListener('click', () => {
    let box = $('#lightbox');
    if (!box) {
      box = document.createElement('dialog');
      box.id = 'lightbox';
      box.setAttribute('aria-label', 'Photograph');
      box.innerHTML = '<button type="button" class="lb-close" aria-label="Close">&times;</button><img alt="">';
      document.body.append(box);
      box.addEventListener('click', () => box.close());
    }
    const view = $('img', box);
    view.src = image.getAttribute('src');
    view.alt = image.alt;
    box.showModal();
  });
  frame.append(button);
});
'''

TEMPLATE_OPS = [
    ('before', '@media (prefers-reduced-motion:reduce) {', PHOTO_CSS, 'CSS композиций и лайтбокса'),
    ('before', '/* ---------- Photo numbers: every empty place', PHOTO_JS, 'JS лайтбокса'),
]

# ------------------------------------------------------------------ сборка сайта
PY_CONSTANTS = '''COMPS = (('auto', 'Как раньше: ряд из 1–3 фото'), ('single', 'Одно фото'), ('wide', 'Одно широкое фото'),
         ('calm-pair', 'Спокойная пара: большое фото и малое, много воздуха'), ('lead-small', 'Крупное фото и малое рядом (асимметрия)'),
         ('trio', 'Три фото: крупное и два малых'))
# Frame shape of every photograph of a composition: (desktop ratio, phone ratio, name). The dashboard draws its crop frames from the same table.
FRAMES = {
    'auto': (('4/5', '4/5', 'Фото 1'), ('4/5', '4/5', 'Фото 2'), ('4/5', '4/5', 'Фото 3')),
    'single': (('4/5', '4/5', 'Одно фото'),),
    'wide': (('16/9', '4/3', 'Широкий кадр'),),
    'calm-pair': (('3/2', '4/3', 'Большой кадр'), ('4/5', '4/5', 'Малый кадр')),
    'lead-small': (('4/5', '4/5', 'Крупный кадр'), ('1/1', '1/1', 'Малый кадр')),
    'trio': (('4/5', '4/5', 'Крупный кадр'), ('1/1', '1/1', 'Малый кадр сверху'), ('4/5', '4/5', 'Малый кадр снизу')),
}
ZOOM_OPTIONS = (('', 'Нет'), ('yes', 'Да, открывать крупнее по нажатию'))
CROP_RE = re.compile(r'^(\\d{1,3}(?:\\.\\d{1,2})?),(\\d{1,3}(?:\\.\\d{1,2})?),(\\d(?:\\.\\d{1,2})?)$')


def photo_ref_ok(value):
    try:
        return bool(photo_path(value))
    except ValueError:
        return False


def clean_crop(value):
    """'x,y,zoom' (position in percent, zoom 1 to 3) or '' when the value is not usable."""
    m = CROP_RE.fullmatch(str(value or '').strip())
    if not m:
        return ''
    x, y, z = (float(g) for g in m.groups())
    return f'{x:g},{y:g},{z:g}' if x <= 100 and y <= 100 and 1 <= z <= 3 else ''
'''

PHOTO_METHODS = '''    def resolve(self, ref):
        """A photograph is a numbered place ("2" to "7") or a file of the library ("media/...").  Returns (path, place number)."""
        ref = str(ref or '').strip()
        if ref in SLOT_FIELD:
            return photo_path(self.site.get(SLOT_FIELD[ref])), ref
        path = photo_path(ref) if photo_ref_ok(ref) else ''
        if path and not (OUT / path).is_file():
            _warn(f'photograph {path} is not in the media folder; it is left out')
            return '', ''
        return path, ''

    def photo(self, ref, alt, sizes, frame_class='', bg=False, crop='', ratio=None):
        """The frame of one photograph. An empty numbered place is drawn with its number before launch and left out on the live site."""
        path, num = self.resolve(ref)
        if not path and (self.ready or not num):
            return ''
        attributes = f'data-slot="{num}"' if num else ''
        if path:
            attributes += f' src="{esc(path)}"'
            if path not in self.cache:
                self.cache[path] = make_variants(OUT, path)
            if self.cache[path]:
                attributes += ' srcset="' + ', '.join(f'{esc(name)} {size}w' for name, size in self.cache[path]) + f'" sizes="{esc(sizes)}"'
            crop = clean_crop(crop)
            if crop:
                x, y, z = crop.split(',')
                attributes += f' style="object-position:{x}% {y}%' + (f';transform:scale({z});transform-origin:{x}% {y}%' if float(z) != 1 else '') + '"'
        if bg:
            return f'<figure class="photo quote-bg" aria-hidden="true"><img {attributes} alt="" loading="lazy" decoding="async"></figure>'
        shape = f' style="--ar:{esc(ratio[0])};--ar-m:{esc(ratio[1])}"' if ratio else ''
        return (f'<figure class="photo {frame_class}"{shape}><img {attributes} alt="{esc(alt)}" loading="lazy" decoding="async">'
                f'{PHOTO_PLACEHOLDER}</figure>')


def render_block'''

PHOTOS_BRANCH = '''comp = block['comp'] if block['comp'] in FRAMES else 'auto'
refs = [(block[f's{n}'], block[f'f{n}'], n - 1) for n in (1, 2, 3) if block[f's{n}']]
if comp != 'auto':
    refs = [r for r in refs if r[2] < len(FRAMES[comp])]
count = len(refs)
sizes = ('(max-width:900px) 100vw, 45vw' if in_rail else '(max-width:700px) 90vw, 420px') if count == 1 else '(max-width:700px) 45vw, 480px'
alt = block['alt'].strip() or block['caption'].strip()
figures = [f for f in (ctx.photo(ref, alt, sizes, 'frame', crop=crop, ratio=FRAMES[comp][index] if comp != 'auto' else None) for ref, crop, index in refs) if f]
if not figures:
    return ''
caption = f'<p class="b-cap">{esc(block["caption"].strip())}</p>' if block['caption'].strip() else ''
extra = (f' data-comp="{comp}"' if comp != 'auto' else '') + (' data-lightbox' if block['zoom'] == 'yes' else '')
return f'<div class="b b-photos n{len(figures)}{" b-side" if in_rail else ""}" {number}{extra} data-fade>{"".join(figures)}{caption}</div>\''''

BUILD_OPS = [
    ('after', "PLACE_SLOTS = tuple(str(n) for n in range(2, 8))", PY_CONSTANTS, 'композиции, формы рамок, кадрирование'),
    ('before', "if field['type'] in ('select', 'slot') and value not in [o[0] for o in field['options']]:",
     "if field['type'] == 'photo':\n"
     "    value = value.strip()\n"
     "    if value and value not in PLACE_SLOTS and not photo_ref_ok(value):\n"
     "        _warn(f'{where}: \"{value}\" is not a photograph of the site; it is left out')\n"
     "        value = ''\n"
     "elif field['type'] == 'crop':\n"
     "    value = clean_crop(value)", 'проверка фото и кадрирования при загрузке'),
    ('line', "{'name': 'photo', 'label': 'Фото за фразой (необязательно)', 'type': 'slot'",
     "{'name': 'photo', 'label': 'Фото за фразой (необязательно)', 'type': 'photo', 'default': '', 'showIf': {'look': ['panel']}},", 'фото за фразой: файл или номер'),
    ('line', "'hint': 'Выберите, какие из пронумерованных фото показать",
     "'hint': 'Выберите фото из библиотеки (вкладка «Фотографии») или загрузите новое прямо здесь. Композиция задаёт форму кадров, «Кадрировать» двигает фото внутри кадра, оригинал не меняется.',", 'подсказка блока «Фото»'),
    ('line', "{'name': 's1', 'label': 'Первое фото'", "{'name': 'comp', 'label': 'Композиция', 'type': 'select', 'options': _opts(COMPS), 'default': 'auto'},\n{'name': 's1', 'label': 'Первое фото', 'type': 'photo', 'default': ''},", 's1 и композиция перед ним'),
    ('line', "{'name': 's2', 'label': 'Второе фото", "{'name': 's2', 'label': 'Второе фото (необязательно)', 'type': 'photo', 'default': ''},", 's2'),
    ('line', "{'name': 's3', 'label': 'Третье фото",
     "{'name': 's3', 'label': 'Третье фото (необязательно)', 'type': 'photo', 'default': ''},\n"
     "{'name': 'f1', 'label': 'Кадрирование 1', 'type': 'crop', 'default': ''},\n"
     "{'name': 'f2', 'label': 'Кадрирование 2', 'type': 'crop', 'default': ''},\n"
     "{'name': 'f3', 'label': 'Кадрирование 3', 'type': 'crop', 'default': ''},\n"
     "{'name': 'zoom', 'label': 'Открывать фото крупнее по нажатию', 'type': 'select', 'options': _opts(ZOOM_OPTIONS), 'default': ''},", 'кадрирование, композиция, лайтбокс'),
    ('regex', r"    def photo\(self, num, alt, sizes, frame_class='', bg=False\):.*?\n\n\ndef render_block", PHOTO_METHODS, 'PageContext.photo: номер или файл, кадрирование, форма рамки'),
    ('range', "slots = [block[k] for k in ('s1', 's2', 's3') if block[k]]", "return f'<div class=\"b b-photos n{len(figures)}", PHOTOS_BRANCH, 'рендер блока «Фото»'),
    ('line', "'slots': list(PLACE_SLOTS),",
     "'slots': list(PLACE_SLOTS),\n'comps': _opts(COMPS),\n'frames': {name: [list(f) for f in frames] for name, frames in FRAMES.items()},", 'схема для панели: композиции и рамки'),
]

# ------------------------------------------------------------------ .pages.yml
YML_NEW_FIELDS = '''      - name: alt
        label: Описание фото для скринридеров (необязательно)
        type: string
      - name: comp
        label: Композиция фото
        type: select
        options:
          values:
          - value: auto
            label: Как раньше, ряд из 1–3 фото
          - value: single
            label: Одно фото
          - value: wide
            label: Одно широкое фото
          - value: calm-pair
            label: Спокойная пара, большое и малое
          - value: lead-small
            label: Крупное и малое, асимметрия
          - value: trio
            label: Три фото, крупное и два малых
      - name: zoom
        label: Открывать фото крупнее по нажатию
        type: select
        options:
          values:
          - value: ''
            label: Нет
          - value: yes
            label: Да
      - name: f1
        label: Кадрирование 1 (x,y,масштаб; задаётся в панели)
        type: string
      - name: f2
        label: Кадрирование 2 (x,y,масштаб; задаётся в панели)
        type: string
      - name: f3
        label: Кадрирование 3 (x,y,масштаб; задаётся в панели)
        type: string
'''
YML_SELECT = (r"      - name: (s[123]|photo)\n        label: ([^\n]*)\n        type: select\n        options:\n          values:\n"
              r"(?:          - value: [^\n]*\n            label: [^\n]*\n)+")
PAGES_OPS = [
    ('regexn', YML_SELECT, lambda m: f"      - name: {m.group(1)}\n        label: {m.group(2)} (номер 2–7 или файл media/…; удобнее выбирать в панели)\n        type: string\n", 4, 'поля фото в CMS: строка, чтобы файл из библиотеки не стирался'),
    ('text', "      - name: alt\n        label: Описание фото для скринридеров (необязательно)\n        type: string\n", YML_NEW_FIELDS, 'новые поля блока «Фото» в CMS'),
]

# ------------------------------------------------------------------ панель
ADMIN_CORE = r'''const SLOT_NUM = /^\d+$/;
const slotField = num => { const s = S.schema.photos.find(p => String(p.num) === String(num)); return s ? s.field : ''; };
const slotPath = num => S.site[slotField(num)] || '';
/** The file a photograph reference points to: a numbered place ("4") or a file of the library ("media/..."). */
const refPath = ref => { ref = String(ref || ''); return SLOT_NUM.test(ref) ? slotPath(ref) : ref; };
const clampPct = v => Math.max(0, Math.min(100, v));
function parseCrop(v) { const m = String(v || '').split(',').map(Number); return m.length === 3 && m.every(Number.isFinite) ? { x: m[0], y: m[1], z: m[2] } : { x: 50, y: 30, z: 1 }; }
const fmtCrop = c => `${+(+c.x).toFixed(1)},${+(+c.y).toFixed(1)},${+(+c.z).toFixed(2)}`;
/** The same rule the site uses: the picture moves inside its frame and can be enlarged around that point. */
function cropStyle(v) {
  if (!v) return '';
  const c = parseCrop(v);
  return `object-position:${c.x}% ${c.y}%` + (c.z !== 1 ? `;transform:scale(${c.z});transform-origin:${c.x}% ${c.y}%` : '');
}
/** Pending files that will be saved: library uploads, and anything a place or a block points to. */
function pendingKept() {
  const live = new Set(photoFields().map(f => S.site[f]).filter(Boolean));
  const used = new Set();
  S.page.sections.forEach(s => (s.blocks || []).forEach(b => ['s1', 's2', 's3', 'photo'].forEach(k => { if (b[k]) used.add(b[k]); })));
  return Object.entries(S.pending).filter(([path, p]) => p.lib || live.has(path) || used.has(path));
}
function libraryList() {
  const known = new Map((S.lib.items || []).map(i => [i.path, { path: i.path, kb: Math.round(i.size / 1024) }]));
  for (const [path, p] of pendingKept()) known.set(path, { path, kb: p.kb });
  S.deleted.forEach(path => known.delete(path));
  return [...known.values()].sort((a, b) => b.path.localeCompare(a.path));
}
function pathUses(path) {
  const uses = [];
  S.schema.photos.forEach(s => { if (S.site[s.field] === path) uses.push(s.num === 1 ? 'первый экран' : `место ${s.num}`); });
  S.page.sections.forEach((sec, i) => (sec.blocks || []).forEach((b, j) => {
    const where = `блок ${i + 1}.${j + 1}`;
    if (b.type === 'photos' && [b.s1, b.s2, b.s3].some(r => r && refPath(r) === path)) uses.push(where);
    if (b.type === 'aside' && b.photo && refPath(b.photo) === path) uses.push(where + ' (фон фразы)');
  }));
  return uses;
}'''

ADMIN_USED_PENDING = r'''function usedPending() {
  return pendingKept().filter(([, p]) => !p.saved).map(([path, p]) => ({ path, blob: p.blob }));
}
'''

ADMIN_LOAD_LIBRARY = r'''async function loadLibrary() {
  S.lib.loading = true;
  try {
    const list = await gh(`/repos/${S.repo}/contents/media?ref=${encodeURIComponent(S.branch)}`);
    S.lib.items = (Array.isArray(list) ? list : []).filter(f => f.type === 'file' && /\.(jpe?g|png|webp|gif|avif)$/i.test(f.name)).map(f => ({ path: f.path, size: f.size }));
    S.lib.error = '';
  } catch (e) { S.lib.items = e.status === 404 ? [] : null; S.lib.error = e.status === 404 ? '' : 'Не удалось загрузить список фото. Обновите страницу.'; }
  S.lib.loading = false;
  if (S.tab === 'photos' && typeof panel !== 'undefined' && panel) renderPanel();
}
'''

ADMIN_DOM = r'''/* ---------- photo library, picker, crop ---------- */
const thumbSrc = path => (S.pending[path] ? S.pending[path].url : '../' + path);
let libSeq = 0;
function libPath(ext) { const d = new Date(); return `media/photo-${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}-${two(d.getHours())}${two(d.getMinutes())}${two(d.getSeconds())}-${++libSeq}.${ext}`; }
/** Compresses the chosen files and adds them to the library. Nothing is saved until "Сохранить и опубликовать". Returns the new paths. */
async function addToLibrary(files) {
  const added = [];
  for (const file of Array.from(files || [])) {
    if (!/^image\//.test(file.type) && !/\.(jpe?g|png|webp|gif|avif|heic)$/i.test(file.name)) { setNotice('warn', `Файл «${file.name}» не похож на картинку. Подойдут JPG, PNG или WebP.`); continue; }
    S.busy = 'Готовлю фото…'; paintBar();
    try {
      const { blob, ext, source } = await prepareImage(file);
      const path = libPath(ext);
      S.pending[path] = { blob, url: URL.createObjectURL(blob), kb: Math.round(blob.size / 1024), w: source.width, h: source.height, lib: true };
      added.push(path);
      if (Math.max(source.width, source.height) < 1100) setNotice('warn', `Фото «${file.name}» небольшое (${source.width}×${source.height}). На большом экране оно может выглядеть мягким. По возможности загрузите оригинал.`);
    } catch (e) { setNotice('bad', e.message); }
  }
  S.busy = ''; paintBar();
  return added;
}
function removeFromLibrary(path) {
  const p = S.pending[path];
  if (p && !p.saved) { URL.revokeObjectURL(p.url); delete S.pending[path]; }
  else {
    if (!confirm('Удалить файл из библиотеки?\n\nОн исчезнет из репозитория после «Сохранить и опубликовать». Если это фото вставлено в статью («Заметки»), оно там пропадёт.')) return;
    S.deleted.add(path); delete S.pending[path];
  }
  renderPanel(); paintBar();
}
function libraryPanel() {
  const input = el('input', { type: 'file', accept: 'image/*', multiple: true, id: 'lib-file', onchange: async e => { const files = Array.from(e.target.files); e.target.value = ''; if ((await addToLibrary(files)).length) renderPanel(); } });
  const tiles = libraryList().map(item => {
    const uses = pathUses(item.path), pend = S.pending[item.path];
    return el('div', { class: 'ltile' },
      el('div', { class: 'lthumb' }, el('img', { src: thumbSrc(item.path), alt: '', loading: 'lazy', decoding: 'async' })),
      el('div', { class: 'lmeta' }, el('b', {}, item.path.replace(/^media\//, '')), item.kb ? el('span', {}, item.kb + ' КБ') : null,
        pend && !pend.saved ? el('span', { class: 'tag new' }, 'не сохранено') : null,
        el('span', { class: uses.length ? 'use' : '' }, uses.length ? 'Используется: ' + uses.join('; ') : 'нигде не используется')),
      el('button', { class: 'btn ghost small', type: 'button', disabled: uses.length > 0, title: uses.length ? 'Фото используется: сначала уберите его из блоков' : 'Удалить из библиотеки', onclick: () => removeFromLibrary(item.path) }, 'Удалить'));
  });
  const wrap = el('div', {
    ondragover: e => { e.preventDefault(); wrap.classList.add('libdrop'); },
    ondragleave: e => { if (!wrap.contains(e.relatedTarget)) wrap.classList.remove('libdrop'); },
    ondrop: async e => { e.preventDefault(); wrap.classList.remove('libdrop'); if ((await addToLibrary(e.dataTransfer.files)).length) renderPanel(); } },
    el('p', { class: 'lead' }, 'Все фото сайта. Загрузите новые (можно перетащить файлы сюда), посмотрите, что где используется, и выбирайте их в блоках «Фото» на вкладке «Тексты». Загрузить фото можно и прямо из окна выбора в блоке. Сжатие в браузере автоматическое.'),
    el('div', { class: 'lrow' }, input, el('label', { class: 'btn', for: 'lib-file', tabindex: 0, onkeydown: keyClick('lib-file') }, 'Загрузить фото'),
      S.lib.loading ? el('span', { class: 'muted' }, 'Загружаю список…') : null),
    S.lib.error ? el('div', { class: 'note bad' }, S.lib.error) : null,
    el('div', { class: 'lib' }, tiles.length ? tiles : el('p', { class: 'muted' }, S.lib.loading ? 'Загружаю…' : 'Пока нет ни одного фото.')));
  return wrap;
}

/** A simple dialog over the page: Esc, the Close button or a click outside close it, and focus goes back to where it was. */
function openModal(title, build) {
  const prev = document.activeElement;
  const overlay = el('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true', 'aria-label': title });
  const onKey = e => { if (e.key === 'Escape') close(); };
  function close() { document.removeEventListener('keydown', onKey); overlay.remove(); if (prev && prev.isConnected) prev.focus(); }
  document.addEventListener('keydown', onKey);
  overlay.addEventListener('mousedown', e => { if (e.target === overlay) close(); });
  overlay.append(el('div', { class: 'mbox' }, el('div', { class: 'mhead' }, el('h2', {}, title), el('button', { class: 'btn ghost small', type: 'button', onclick: close }, 'Закрыть')), build(close)));
  document.body.append(overlay);
  const first = overlay.querySelector('.mbox .pitem, .mbox label.btn, .mbox button.btn:not(.ghost)'); if (first) first.focus();
  return close;
}
function openPicker(current, onPick) {
  openModal('Выберите фото', close => {
    const input = el('input', { type: 'file', accept: 'image/*', id: 'pick-file', onchange: async e => { const files = Array.from(e.target.files); e.target.value = ''; const added = await addToLibrary(files); if (added.length) { close(); onPick(added[0]); } } });
    const items = libraryList(), now = refPath(current);
    return el('div', {},
      el('div', { class: 'lrow' }, input, el('label', { class: 'btn', for: 'pick-file', tabindex: 0, onkeydown: keyClick('pick-file') }, '+ Загрузить новое фото'), el('span', { class: 'muted' }, 'Новое фото сразу встанет на место.')),
      items.length ? el('div', { class: 'pgrid' }, items.map(item => el('button', { class: 'pitem' + (item.path === now ? ' on' : ''), type: 'button', title: item.path, onclick: () => { close(); onPick(item.path); } },
        el('img', { src: thumbSrc(item.path), alt: '' }), el('span', {}, item.path.replace(/^media\//, ''))))) : el('p', { class: 'muted' }, 'В библиотеке пока пусто. Загрузите первое фото.'));
  });
}
/** Direct manipulation: drag the photograph inside its frame, set the zoom, switch between the computer and phone shape of the frame. */
function openCrop(b, i, frame, path, done) {
  const state = parseCrop(b['f' + i]);
  let phone = false, drag = null;
  openModal('Кадрирование: ' + frame[2], close => {
    const img = el('img', { src: thumbSrc(path), alt: '', draggable: false });
    const box = el('div', { class: 'cframe', tabindex: '0', role: 'img', 'aria-label': 'Кадр. Тяните мышью или стрелками на клавиатуре.' }, img);
    const zoom = el('input', { type: 'range', min: '1', max: '3', step: '0.02', value: String(state.z), 'aria-label': 'Масштаб' });
    const label = el('span', { class: 'muted' }, '');
    const seg = [['Компьютер', false], ['Телефон', true]].map(([text, isPhone]) => el('button', { type: 'button', 'aria-pressed': String(isPhone === phone), onclick: () => { phone = isPhone; apply(); } }, text));
    function apply() {
      box.style.aspectRatio = phone ? frame[1] : frame[0];
      box.style.width = phone ? '220px' : 'min(100%, 460px)';
      img.style.cssText = cropStyle(fmtCrop(state)) || 'object-position:50% 30%';
      zoom.value = String(state.z); label.textContent = 'Масштаб ×' + (+state.z).toFixed(2);
      seg.forEach((button, k) => button.setAttribute('aria-pressed', String((k === 1) === phone)));
    }
    const overflow = () => { const r = box.getBoundingClientRect(), iw = img.naturalWidth || 1, ih = img.naturalHeight || 1, k = Math.max(r.width / iw, r.height / ih) * state.z; return [iw * k - r.width, ih * k - r.height]; };
    box.addEventListener('pointerdown', e => { box.setPointerCapture(e.pointerId); drag = { x: e.clientX, y: e.clientY, s: { ...state } }; box.classList.add('grab'); });
    box.addEventListener('pointermove', e => {
      if (!drag) return;
      const [ox, oy] = overflow();
      if (ox > 0.5) state.x = clampPct(drag.s.x - (e.clientX - drag.x) / ox * 100);
      if (oy > 0.5) state.y = clampPct(drag.s.y - (e.clientY - drag.y) / oy * 100);
      apply();
    });
    const stop = () => { drag = null; box.classList.remove('grab'); };
    box.addEventListener('pointerup', stop); box.addEventListener('pointercancel', stop);
    box.addEventListener('keydown', e => {
      const step = e.shiftKey ? 8 : 2, d = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] }[e.key];
      if (!d) return; e.preventDefault(); state.x = clampPct(state.x + d[0]); state.y = clampPct(state.y + d[1]); apply();
    });
    zoom.addEventListener('input', () => { state.z = Number(zoom.value); apply(); });
    img.addEventListener('load', apply);
    apply();
    return el('div', {},
      el('p', { class: 'muted' }, 'Потяните фото внутри рамки, чтобы важное осталось в кадре. Переключатель показывает форму кадра на компьютере и на телефоне. Оригинальный файл не меняется.'),
      el('div', { class: 'crow' }, el('div', { class: 'seg', role: 'group', 'aria-label': 'Форма кадра' }, seg)),
      box,
      el('div', { class: 'crow' }, el('button', { class: 'btn ghost small mini', type: 'button', 'aria-label': 'Уменьшить', onclick: () => { state.z = Math.max(1, state.z - 0.1); apply(); } }, '−'), zoom,
        el('button', { class: 'btn ghost small mini', type: 'button', 'aria-label': 'Увеличить', onclick: () => { state.z = Math.min(3, state.z + 0.1); apply(); } }, '+'), label),
      el('div', { class: 'crow' },
        el('button', { class: 'btn ghost small', type: 'button', onclick: () => { state.x = 50; state.y = 30; state.z = 1; apply(); } }, 'Сбросить'),
        el('button', { class: 'btn ghost small', type: 'button', onclick: close }, 'Отмена'),
        el('button', { class: 'btn small', type: 'button', onclick: () => {
          const same = state.x === 50 && state.y === 30 && state.z === 1;
          b['f' + i] = same ? '' : fmtCrop(state); close(); done();
        } }, 'Готово')));
  });
}
function photoSlots(sec, si, b, bi) {
  const comp = b.comp || 'auto', frames = S.schema.page.frames[comp] || S.schema.page.frames.auto;
  const count = comp === 'auto' ? 3 : frames.length, done = () => afterStructure({ sid: sec.id, block: bi });
  const tiles = [];
  for (let i = 1; i <= count; i++) {
    const ref = b['s' + i], path = refPath(ref), frame = frames[i - 1] || frames[0];
    tiles.push(el('div', { class: 'ptile' }, el('div', { class: 'plabel' }, `${i}. ${frame[2]}`),
      el('div', { class: 'pframe', style: `aspect-ratio:${frame[0]}` }, path ? el('img', { src: thumbSrc(path), alt: '', style: cropStyle(b['f' + i]) }) : el('span', {}, 'пусто')),
      el('div', { class: 'acts' },
        el('button', { class: 'btn small', type: 'button', onclick: () => openPicker(ref, p => { b['s' + i] = p; b['f' + i] = ''; done(); }) }, path ? 'Заменить' : 'Выбрать'),
        path ? el('button', { class: 'btn ghost small', type: 'button', onclick: () => openCrop(b, i, frame, path, done) }, 'Кадрировать') : null,
        path ? el('button', { class: 'btn ghost small', type: 'button', onclick: () => { b['s' + i] = ''; b['f' + i] = ''; done(); } }, 'Убрать') : null)));
  }
  return el('div', { class: 'fld', 'data-find': 'фото в блоке композиция' }, el('label', {}, 'Фото в блоке'), el('div', { class: 'ptiles' }, tiles),
    el('p', { class: 'hint' }, 'Рамки показаны в форме, в которой фото будут на сайте. Замена и «Убрать» не трогают файл в библиотеке.'));
}
/** One photograph field: the "photos" block draws all its photographs together (from its first field); any other block draws one tile. */
function photoWidget(sec, si, b, bi, f) {
  if (b.type === 'photos') return f.name === 's1' ? photoSlots(sec, si, b, bi) : null;
  const path = refPath(b[f.name]), done = () => afterStructure({ sid: sec.id, block: bi });
  return el('div', { class: 'fld', 'data-find': (f.label + ' фото').toLowerCase() }, el('label', {}, f.label),
    el('div', { class: 'ptile' }, el('div', { class: 'pframe', style: 'aspect-ratio:16/10' }, path ? el('img', { src: thumbSrc(path), alt: '' }) : el('span', {}, 'пусто')),
      el('div', { class: 'acts' }, el('button', { class: 'btn small', type: 'button', onclick: () => openPicker(b[f.name], p => { b[f.name] = p; done(); }) }, path ? 'Заменить' : 'Выбрать'),
        path ? el('button', { class: 'btn ghost small', type: 'button', onclick: () => { b[f.name] = ''; done(); } }, 'Убрать') : null)));
}
'''

ADMIN_PANEL_TAIL = r'''  const old = el('details', { class: 'more' }, el('summary', {}, 'Первый экран и прежние номерные места (1–7)'),
    el('div', { class: 'inner' },
      el('p', { class: 'lead' }, 'Здесь меняется главное фото первого экрана (номер 1). Остальные номера работают как раньше: блок «Фото» может ссылаться и на номер, и на файл из библиотеки. Несколько файлов с номером в названии (3.jpg) можно перетащить на этот список сразу.'),
      el('p', { class: 'muted' }, el('a', { href: '../?photos', target: '_blank', rel: 'noopener' }, 'Открыть сайт с номерами фото ↗')),
      list));
  return el('div', {}, el('h1', {}, 'Фотографии'), libraryPanel(), el('div', { style: 'height:18px' }), old);
}'''

ADMIN_CSS = r'''.modal{position:fixed;inset:0;z-index:100;background:rgba(20,38,58,.55);display:grid;place-items:center;padding:16px}
.mbox{background:#fff;border-radius:12px;max-width:760px;width:100%;max-height:calc(100vh - 32px);overflow:auto;padding:16px 18px;box-shadow:0 20px 50px rgba(0,0,0,.3)}
.mhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:12px}.mhead h2{margin:0;font-size:1.1rem}
.lrow{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0}
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(120px,1fr));gap:10px;margin-top:12px}
.pitem{border:2px solid var(--line);border-radius:10px;background:#fff;padding:0;cursor:pointer;overflow:hidden;text-align:left}
.pitem.on{border-color:var(--blue)}.pitem img{display:block;width:100%;aspect-ratio:4/5;object-fit:cover}
.pitem span{display:block;padding:4px 8px;font-size:.74rem;color:var(--muted);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ptiles{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}
.ptile{width:170px}.plabel{font-size:.82rem;font-weight:600;margin-bottom:6px}
.pframe{width:100%;background:var(--soft);border-radius:8px;overflow:hidden;display:grid;place-items:center;color:var(--muted);font-size:.8rem;position:relative}
.pframe img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 30%}
.ptile .acts{justify-content:flex-start;margin-top:8px}
.cframe{position:relative;margin:12px auto;overflow:hidden;border-radius:8px;background:var(--soft);cursor:grab;touch-action:none}
.cframe.grab{cursor:grabbing}
.cframe img{position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:50% 30%;user-select:none;pointer-events:none}
.crow{display:flex;flex-wrap:wrap;gap:10px;align-items:center;justify-content:center;margin:10px 0}
.crow input[type=range]{flex:1;min-width:140px;max-width:300px}
.lib{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;margin-top:14px}
.ltile{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px;display:grid;gap:8px;align-content:start}
.lthumb{aspect-ratio:4/5;background:var(--soft);border-radius:6px;overflow:hidden}.lthumb img{width:100%;height:100%;object-fit:cover;display:block}
.lmeta{display:grid;gap:3px;font-size:.82rem;color:var(--muted);word-break:break-all}.lmeta b{color:var(--ink);font-size:.86rem}.lmeta .use{color:var(--green)}
.libdrop{outline:3px dashed var(--blue);outline-offset:4px}'''

ADMIN_OPS = [
    ('after', 'const clone = o => JSON.parse(JSON.stringify(o));', 'S.lib = { items: null, loading: false, error: \'\' }; S.deleted = new Set();', 'состояние библиотеки'),
    ('text', "out.total = out.textCount + out.pageCount + out.contacts.length + out.photos.length + (out.ready ? 1 : 0);",
     "out.library = pendingKept().filter(([, p]) => p.lib && !p.saved).length + S.deleted.size;\n  out.total = out.textCount + out.pageCount + out.contacts.length + out.photos.length + out.library + (out.ready ? 1 : 0);", 'счётчик правок библиотеки'),
    ('regex', r"function usedPending\(\) \{.*?\n\}\n", ADMIN_USED_PENDING, 'какие новые фото сохранять'),
    ('after', "if (c.photos.length) parts.push('фото ' + c.photos.join(', '));", "if (c.library) parts.push('библиотека фото');", 'сообщение коммита'),
    ('text', "  if (!files.length) return null;\n  const photos = usedPending();\n",
     "  const photos = usedPending(), removals = [...S.deleted];\n  if (!files.length && !photos.length && !removals.length) return null;\n", 'коммит без текстовых файлов, но с фото'),
    ('text', "...blobs.map(b => ({ path: b.path, mode: '100644', type: 'blob', sha: b.sha })) ] } });",
     "...blobs.map(b => ({ path: b.path, mode: '100644', type: 'blob', sha: b.sha })),\n    ...removals.map(path => ({ path, mode: '100644', type: 'blob', sha: null })) ] } });", 'удаление файлов в коммите'),
    ('text', "blobs.forEach(b => { if (S.pending[b.path]) S.pending[b.path].saved = true; });",
     "blobs.forEach(b => { if (S.pending[b.path]) S.pending[b.path].saved = true; });\n  if (S.lib.items) S.lib.items = S.lib.items.filter(i => !removals.includes(i.path));\n  S.deleted.clear();", 'после сохранения'),
    ('text', "const badge = { photos: [c.photos.length, ''],", "const badge = { photos: [c.photos.length + c.library, ''],", 'метка вкладки'),
    ('after', "S.site = clone(S.orig.site); S.home = clone(S.orig.home);", "S.deleted.clear();", 'отмена всего возвращает удалённые файлы'),
    ('line', "await loadAll();", "await loadAll();\n    loadLibrary();", 'загрузка списка фото при входе'),
    ('before', 'const secOrig = id =>', ADMIN_CORE, 'ссылки на фото, библиотека, где используется'),
    ('text', "const photos = [b.s1, b.s2, b.s3].filter(Boolean).map(n => 'Фото ' + n).join(', ');",
     "const photos = [b.s1, b.s2, b.s3].filter(Boolean).map(n => (/^\\d+$/.test(n) ? 'Фото ' + n : String(n).replace(/^media\\//, '').slice(0, 22))).join(', ');", 'превью блока с фото из библиотеки'),
    ('text', "[b.s1, b.s2, b.s3].includes(n)", "[b.s1, b.s2, b.s3].some(r => r === n || (slotPath(n) && r === slotPath(n)))", 'где используется номерное место: и по файлу'),
    ('text', "b.look === 'panel' && b.photo === n)", "b.look === 'panel' && (b.photo === n || (slotPath(n) && b.photo === slotPath(n))))", 'то же для фона фразы'),
    ('before', 'async function takeFile(slot, file) {', ADMIN_LOAD_LIBRARY, 'загрузка списка фото'),
    ('regex', r"  return el\('div', \{\}, el\('h1', \{\}, 'Фотографии'\),.*?\n    list\);\n\}", ADMIN_PANEL_TAIL, 'вкладка «Фотографии»: библиотека'),
    ('text', ".map(f => makeField({", ".map(f => f.type === 'crop' ? null : f.type === 'photo' ? photoWidget(sec, si, b, bi, f) : makeField({", 'поля фото в блоке'),
    ('text', "redraw: f.name === 'look' && !!spec.fields.some(x => x.showIf),", "redraw: (f.name === 'look' && !!spec.fields.some(x => x.showIf)) || f.name === 'comp',", 'смена композиции перерисовывает блок'),
    ('before', '/* ---------- texts: the page by sections and blocks, then the remaining texts ---------- */', ADMIN_DOM, 'библиотека, выбор, кадрирование'),
    ('after', '.strip .chipbtn:hover{', ADMIN_CSS, 'стили панели'),
]

# ------------------------------------------------------------------ тесты
TEST_CHECK = '''def check_photo_tools(builder):
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


'''

TEST_OPS = [
    ('before', 'def main():', TEST_CHECK.rstrip('\n') + '\n\n', 'проверка инструментов фото'),
    ('after', 'check_text_system(builder)', 'check_photo_tools(builder)', 'вызов проверки'),
    ('line', "allowed = ('.button', '.icon-button'", "allowed = ('.button', '.icon-button', '.contact-links', 'summary::after', '.field', '.slot-badge', '.num-badge', '.skip', '.lb-close')", 'кнопка закрытия лайтбокса мягкая, как все кнопки'),
    ('line', "assert 'data-tab' in admin and", "assert 'data-tab' in admin and \"['requests', 'Заявки'\" in admin, 'dashboard: the Requests tab'\n"
     "for needed in ('addToLibrary', 'loadLibrary', 'libraryPanel', 'openPicker', 'openCrop', 'photoSlots', 'removeFromLibrary', 'pendingKept'):\n"
     "    assert needed in admin, f'dashboard lacks {needed}'", 'панель: библиотека, выбор, кадрирование'),
]

# ------------------------------------------------------------------ документация
DOC_DASHBOARD = '''
## Библиотека фото, кадрирование, композиции (скрипт apply_photo_tools_update.py)

**Фотографии.** Вкладка начинается с **библиотеки**: все файлы из `media/` с миниатюрами, размером и пометкой, где фото используется («блок 5.4», «первый экран») или «нигде не используется». Кнопка **«Загрузить фото»** (или перетащите файлы на страницу) сжимает фото в браузере и кладёт его в библиотеку; сохраняется оно вместе со всем остальным кнопкой «Сохранить и опубликовать». «Удалить» работает только для фото, которое нигде не используется. Главное фото первого экрана и прежние семь номеров лежат в свёрнутой группе «Первый экран и прежние номерные места».

**Блок «Фото» (вкладка «Тексты»).** Вместо списка номеров у каждого кадра есть миниатюра в настоящей форме кадра и кнопки:

- **Выбрать / Заменить**: окно с библиотекой. В нём же **«+ Загрузить новое фото»**: оно сразу встаёт на место, терять своё место в редактировании не нужно.
- **Кадрировать**: фото двигается мышью внутри рамки, ползунок меняет масштаб, переключатель «Компьютер / Телефон» показывает форму кадра на каждом экране. Стрелки на клавиатуре тоже работают. Оригинал не меняется: сохраняется только положение и масштаб, и только для этого места.
- **Убрать** снимает фото с блока, файл остаётся в библиотеке.

**Композиция** блока: «Как раньше» (ряд из 1–3 кадров), «Одно фото», «Одно широкое фото», «Спокойная пара» (большое и малое, много воздуха), «Крупное и малое» (асимметрия), «Три фото». На телефоне раскладка перестраивается, а не уменьшается: кадры складываются в колонку, малые смещаются и слегка заходят на крупное.

**Открывать крупнее по нажатию** (галочка в блоке, по умолчанию выключена): тёмный экран с фото целиком, закрывается нажатием, Esc или кнопкой.

Блок может ссылаться и на номер места (как раньше), и на файл библиотеки. Выбор в окне всегда записывает файл.
'''
DOC_CONCEPT = '''
## 15. Фото: библиотека, кадрирование, композиции (скрипт apply_photo_tools_update.py)

- Фото не привязаны к семи номерам: есть **библиотека** файлов, блок выбирает файл. Номера остались для первого экрана и совместимости.
- **Кадрирование ненавязчивое:** положение и масштаб записаны рядом с местом использования, оригинал не меняется. Одно фото в двух местах можно кадрировать по-разному.
- **Композиции** задают форму кадров и ритм (неравные размеры, воздух, асимметрия), а не сетку одинаковых плиток. На телефоне порядок и иерархия сохраняются, раскладка перестраивается.
- **Лайтбокс** включается в блоке и по умолчанию выключен.
'''
DOC_README = '''
## Библиотека фото, кадрирование, композиции (октябрь 2026)

- Вкладка «Фотографии» теперь библиотека: загрузка, миниатюры, где используется, удаление неиспользуемых. Загрузить фото можно и из окна выбора в блоке «Фото».
- В блоке «Фото»: выбор файла, кадрирование перетаскиванием (положение и масштаб, оригинал не меняется), композиции (одно, широкое, спокойная пара, крупное и малое, три), лайтбокс по желанию. Подробности в `docs/DASHBOARD.md`.
- В `content/sections.json` блок «Фото» получил поля `comp`, `zoom`, `f1`–`f3`; `s1`–`s3` могут быть номером (2–7) или путём `media/…`. Старые данные работают без изменений.
'''
DOC_REVIEW = '''
- [ ] Библиотека фото: загрузите фото и проверьте кадрирование на телефоне и на компьютере (переключатель в окне «Кадрировать»). Подписи (alt) к новым фото вписывайте в поле «Описание фото для скринридеров».
'''
DOCS = [
    ('docs/DASHBOARD.md', DOC_DASHBOARD, 'apply_photo_tools_update.py'),
    ('docs/CONCEPT.md', DOC_CONCEPT, '## 15. Фото: библиотека'),
    ('README.md', DOC_README, '## Библиотека фото, кадрирование, композиции'),
    ('docs/CONTENT-REVIEW.md', DOC_REVIEW, 'Библиотека фото: загрузите фото'),
]
FILE_OPS = [
    ('templates/index.html', TEMPLATE_OPS), ('scripts/build.py', BUILD_OPS), ('.pages.yml', PAGES_OPS),
    ('admin/index.html', ADMIN_OPS), ('scripts/test_build.py', TEST_OPS),
]


# ------------------------------------------------------------------ main
def read(path):
    return (ROOT / path).read_text(encoding='utf-8')


def main():
    needed = ['scripts/build.py', 'scripts/test_build.py', 'templates/index.html', 'admin/index.html', '.pages.yml']
    absent = [p for p in needed if not (ROOT / p).exists()]
    if absent:
        print('Запустите скрипт из корня репозитория. Не найдено: ' + ', '.join(absent))
        return 1
    template = read('templates/index.html')
    if MARK in template:
        print('Это обновление уже применено (маркер найден в шаблоне). Ничего не изменено.')
        return 0
    if REQUIRES not in template:
        print('Сначала примените apply_text_structure_update.py (скрипт 1): без него этот скрипт не найдёт нужные места. Ничего не изменено.')
        return 1
    new = {}
    try:
        for path, ops in FILE_OPS:
            new[path] = run_ops(read(path), ops, path)
    except Miss as e:
        print('ОШИБКА: ' + str(e))
        print('Ничего не записано. Пришлите свежий снимок репозитория: файл, скорее всего, изменился после последнего снимка.')
        return 1
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
