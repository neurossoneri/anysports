#!/usr/bin/env python3
"""Добавляет внизу страницы раздел «Q&A» (RU / EN / FR).

Запуск из корня репозитория:

    python apply_qa_section.py              # применить и проверить сборкой + тестами
    python apply_qa_section.py --dry-run    # ничего не писать, только показать, что изменится
    python apply_qa_section.py --no-verify  # применить без запуска build.py / test_build.py
    python apply_qa_section.py --restore    # вернуть файлы из последней резервной копии

Что делает:
  1. content/home_{ru,en,fr}.json  — новая группа «qa» (после «free»): заголовок, подводка,
     ссылка к форме, 3 подписи групп, 8 вопросов и 8 ответов.
  2. .pages.yml                    — та же группа для всех трёх файлов, чтобы тексты можно
     было править в /admin/ и в Pages CMS (пустой вопрос скрывает слот, как в FAQ).
  3. templates/index.html          — разметка раздела (после FAQ, перед «Заметками»),
     стили, правка адаптива и строка в JS, которая скрывает пустые слоты при смене языка.
  4. scripts/build.py              — QA_SLOTS, якорь раздела для панели, «запекание»
     скрытых пустых слотов в русский HTML.
  5. scripts/test_build.py         — раздел «qa» в проверке порядка секций + проверки слотов.

Скрипт идемпотентен: повторный запуск ничего не меняет. Перед записью он делает копию
изменяемых файлов в .backup-qa/ (папка добавляется в .gitignore).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKUP = ROOT / '.backup-qa'
MARK = 'id="qa"'          # признак того, что шаблон уже обновлён

# --------------------------------------------------------------------------------------
# 1. ТЕКСТЫ
#    Порядок ключей = порядок полей в админке. g1/g2/g3 — подписи над группами вопросов:
#    g1 → вопросы 1–4, g2 → вопросы 5–6, g3 → вопросы 7–8. Пустая подпись скрывается.
# --------------------------------------------------------------------------------------
QA_ORDER = ['title', 'lead', 'ask',
            'g1', 'q1', 'a1', 'q2', 'a2', 'q3', 'a3', 'q4', 'a4',
            'g2', 'q5', 'a5', 'q6', 'a6',
            'g3', 'q7', 'a7', 'q8', 'a8']

COPY = {
    'en': {
        'title': 'Q&A',
        'lead': 'The practical side, the boundaries of this work and who it is for — all in one place.',
        'ask': 'Can’t find your question? Write to me',
        'g1': 'The practical side',
        'q1': 'How does the first meeting work?',
        'a1': 'We begin with an introductory call to get to know each other, discuss your initial request and goals, and explore how we might work together. There is no obligation to continue — we can both decide whether it feels right to move forward.',
        'q2': 'Are the sessions held online?',
        'a2': 'Yes. Our introductory meeting takes place online, and most of the process is built around online sessions. However, if we happen to be based in the same area or you would prefer to meet in person and are willing to travel, we can discuss the possibilities.',
        'q3': 'What are the session duration and fees?',
        'a3': 'We discuss the session format, duration, and fees during our initial conversation and agree on a way forward that works for both of us.\n\nI believe this work should be accessible to those who genuinely feel drawn to it. If your financial circumstances are a concern, please reach out anyway. We can discuss the possibilities and hopefully find a solution that works for you.',
        'q4': 'Are the sessions confidential?',
        'a4': 'Absolutely. Your personal information and everything you share during our sessions remain confidential. No information about you or your personal journey is shared publicly, and sessions are never recorded.',
        'g2': 'Good to know',
        'q5': 'What is the appropriate age for these sessions?',
        'a5': 'I currently work with individuals aged 14 and above. For anyone under 18, written parental consent is required, in accordance with the applicable requirements.',
        'q6': 'Is this psychological counselling?',
        'a6': 'No. These sessions are not psychological counselling or conventional mental training, although we may occasionally explore elements that overlap with these approaches.\n\nThe sessions are focused on developing your relationship with your intuition and instinct. They are not a substitute for medical care or psychological therapy when these are needed.',
        'g3': 'Is this for me?',
        'q7': 'Do I need any knowledge or background to start this work? What if I’ve never experienced intuition?',
        'a7': 'We all connect with ourselves in different ways. You don’t need any special preparation — just come as you are, with curiosity and a willingness to explore. You will find your own way of connecting to yourself.',
        'q8': 'I am not an athlete, but I feel I could benefit from these sessions. Can I reach out?',
        'a8': 'Intuition and personal transformation are not exclusive to athletes — they are part of everyone’s life.\n\nSport represents a kind of quintessence of life, where experiences, emotions, and challenges can become particularly intense. This can make the role of intuition especially visible.\n\nHowever, if you feel drawn to this work and are motivated to explore it, please reach out. We can discuss your needs and whether working together would be a good fit.',
    },
    'ru': {
        'title': 'Q&A',
        'lead': 'Практические детали, границы этой работы и то, кому она может подойти, — в одном месте.',
        'ask': 'Не нашли свой вопрос? Напишите мне',
        'g1': 'Практическое',
        'q1': 'Как проходит первая встреча?',
        'a1': 'Мы начинаем с ознакомительного разговора: знакомимся, обсуждаем ваш первоначальный запрос и цели и смотрим, как мы могли бы работать вместе. Продолжать необязательно — мы оба решим, подходит ли нам двигаться дальше.',
        'q2': 'Сессии проходят онлайн?',
        'a2': 'Да. Наша первая встреча проходит онлайн, и большая часть процесса построена вокруг онлайн-сессий. Но если мы окажемся в одном регионе или вы предпочтёте встретиться лично и готовы приехать, мы можем обсудить такую возможность.',
        'q3': 'Сколько длятся сессии и сколько они стоят?',
        'a3': 'Формат, длительность и стоимость сессий мы обсуждаем в первом разговоре и договариваемся о том, что подойдёт нам обоим.\n\nЯ считаю, что эта работа должна быть доступна тем, кого она по-настоящему привлекает. Если вас беспокоит финансовая сторона, всё равно напишите мне. Мы обсудим возможности и, надеюсь, найдём решение, которое подойдёт вам.',
        'q4': 'Сессии конфиденциальны?',
        'a4': 'Безусловно. Ваши личные данные и всё, чем вы делитесь на сессиях, остаётся конфиденциальным. Никакая информация о вас и вашем пути не публикуется, а сессии никогда не записываются.',
        'g2': 'Важно знать',
        'q5': 'С какого возраста можно приходить на сессии?',
        'a5': 'Сейчас я работаю с людьми от 14 лет. Для тех, кому ещё нет 18, необходимо письменное согласие родителей — в соответствии с применимыми требованиями.',
        'q6': 'Это психологическое консультирование?',
        'a6': 'Нет. Эти сессии — не психологическое консультирование и не классический ментальный тренинг, хотя иногда мы можем касаться элементов, которые пересекаются с этими подходами.\n\nСессии посвящены развитию ваших отношений с интуицией и инстинктом. Они не заменяют медицинскую помощь или психологическую терапию, когда в них есть необходимость.',
        'g3': 'Подходит ли это мне?',
        'q7': 'Нужны ли знания или опыт, чтобы начать? А если интуиция мне пока незнакома?',
        'a7': 'Каждый соединяется с собой по-своему. Специальная подготовка не нужна — приходите такими, какие вы есть, с любопытством и готовностью исследовать. Вы найдёте свой собственный способ соединяться с собой.',
        'q8': 'Спортом я не занимаюсь, но чувствую, что эти сессии могли бы мне помочь. Можно ли обратиться?',
        'a8': 'Интуиция и личная трансформация не принадлежат только спортсменам — они часть жизни каждого.\n\nСпорт — своего рода квинтэссенция жизни, где переживания, эмоции и вызовы могут становиться особенно яркими. Из-за этого роль интуиции в нём особенно заметна.\n\nНо если вас тянет к этой работе и вы хотите её исследовать, пожалуйста, напишите мне. Мы обсудим ваши потребности и то, подойдёт ли нам работать вместе.',
    },
    'fr': {
        'title': 'Q&A',
        'lead': 'Les aspects pratiques, le cadre de ce travail et à qui il s’adresse — au même endroit.',
        'ask': 'Votre question n’y est pas ? Écrivez-moi',
        'g1': 'Côté pratique',
        'q1': 'Comment se passe la première rencontre ?',
        'a1': 'Nous commençons par un appel de présentation pour faire connaissance, parler de votre demande initiale et de vos objectifs, et voir comment nous pourrions travailler ensemble. Rien ne vous oblige à poursuivre — nous déciderons tous les deux si cela nous convient d’aller plus loin.',
        'q2': 'Les séances ont-elles lieu en ligne ?',
        'a2': 'Oui. Notre première rencontre a lieu en ligne, et l’essentiel du parcours repose sur des séances en ligne. Toutefois, si nous vivons dans la même région, ou si vous préférez nous rencontrer en personne et acceptez de vous déplacer, nous pouvons en discuter.',
        'q3': 'Quelle est la durée des séances et quels sont les tarifs ?',
        'a3': 'Nous abordons le format, la durée et les tarifs des séances lors de notre premier échange, puis nous convenons d’une façon de procéder qui nous convienne à tous les deux.\n\nJe crois que ce travail doit être accessible à celles et ceux qui s’y sentent réellement attirés. Si votre situation financière vous préoccupe, écrivez-moi quand même. Nous en discuterons et trouverons, je l’espère, une solution qui vous convienne.',
        'q4': 'Les séances sont-elles confidentielles ?',
        'a4': 'Absolument. Vos informations personnelles et tout ce que vous partagez pendant les séances restent confidentiels. Aucune information sur vous ni sur votre parcours n’est rendue publique, et les séances ne sont jamais enregistrées.',
        'g2': 'Bon à savoir',
        'q5': 'À partir de quel âge peut-on suivre ces séances ?',
        'a5': 'Je travaille actuellement avec des personnes à partir de 14 ans. Pour les moins de 18 ans, le consentement écrit des parents est requis, conformément aux exigences applicables.',
        'q6': 'Est-ce du conseil psychologique ?',
        'a6': 'Non. Ces séances ne relèvent ni du conseil psychologique ni du mental training classique, même si nous pouvons parfois explorer des éléments qui recoupent ces approches.\n\nElles visent à développer votre relation avec votre intuition et votre instinct. Elles ne remplacent ni les soins médicaux ni une thérapie psychologique lorsque ceux-ci sont nécessaires.',
        'g3': 'Est-ce pour moi ?',
        'q7': 'Faut-il des connaissances ou un parcours particulier pour commencer ? Et si je n’ai jamais ressenti mon intuition ?',
        'a7': 'Nous nous relions tous à nous-mêmes de façons différentes. Aucune préparation particulière n’est nécessaire — venez tel que vous êtes, avec de la curiosité et l’envie d’explorer. Vous trouverez votre propre façon de vous relier à vous-même.',
        'q8': 'Je ne pratique pas de sport, mais je sens que ces séances pourraient m’être utiles. Puis-je vous contacter ?',
        'a8': 'L’intuition et la transformation personnelle ne sont pas réservées aux sportifs — elles font partie de la vie de chacun.\n\nLe sport est une sorte de quintessence de la vie, où les expériences, les émotions et les défis peuvent devenir particulièrement intenses. Le rôle de l’intuition y est alors particulièrement visible.\n\nMais si ce travail vous attire et que vous avez envie de l’explorer, n’hésitez pas à me contacter. Nous pourrons parler de vos besoins et voir si travailler ensemble vous convient.',
    },
}

# --------------------------------------------------------------------------------------
# 2. .pages.yml — блок группы «qa» (подписи в админке всегда русские, как и у остальных групп)
# --------------------------------------------------------------------------------------
def yaml_block() -> str:
    lines = [
        '  - name: qa',
        '    label: 8 · Q&A внизу страницы (пустой вопрос скрывает слот)',
        '    type: object',
        '    fields:',
    ]

    def field(name, label, kind, description=None):
        lines.extend([f'    - name: {name}', f'      label: {label}', f'      type: {kind}'])
        if description:
            lines.append(f'      description: {description}')

    group_range = {'g1': '1–4', 'g2': '5–6', 'g3': '7–8'}
    for key in QA_ORDER:
        if key == 'title':
            field(key, 'Заголовок', 'string')
        elif key == 'lead':
            field(key, 'Текст под заголовком', 'text')
        elif key == 'ask':
            field(key, 'Ссылка под текстом (ведёт к форме контактов)', 'string')
        elif key in group_range:
            n = key[1]
            field(key, f'Подпись группы {n} (над вопросами {group_range[key]})', 'string',
                  'Оставьте пустым, чтобы убрать подпись.')
        elif key[0] == 'q':
            field(key, f'Вопрос {key[1:]}', 'string', 'Оставьте пустым, чтобы скрыть этот вопрос.')
        else:
            field(key, f'Ответ {key[1:]}', 'text')
    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------------------
# 3. ШАБЛОН: разметка, стили, JS
# --------------------------------------------------------------------------------------
def section_markup() -> str:
    def item(n: int) -> str:
        return (f'            <details name="qa" data-qa="{n}"><summary><span class="qa-n" aria-hidden="true"></span>'
                f'<span class="qa-q" data-i18n="qa.q{n}"></span></summary>'
                f'<div class="qa-a"><p data-i18n="qa.a{n}"></p></div></details>')

    groups = {1: (1, 2, 3, 4), 2: (5, 6), 3: (7, 8)}
    body = []
    for g, slots in groups.items():
        body.append('          <div class="qa-group">')
        body.append(f'            <h3 class="qa-group-title" data-i18n="qa.g{g}"></h3>')
        body.extend(item(n) for n in slots)
        body.append('          </div>')
    return (
        '    <!-- 8. Q&A: numbered accordion in three groups (blank question = hidden slot, blank label = no label) -->\n'
        '    <section class="band band-ice qa" id="qa" aria-labelledby="qa-title">\n'
        '      <div class="container">\n'
        '        <div class="split">\n'
        '          <div class="sticky">\n'
        '            <h2 class="title" id="qa-title" data-i18n="qa.title"></h2>\n'
        '            <p class="lead" data-i18n="qa.lead"></p>\n'
        '            <a class="qa-ask" href="#contact" data-i18n="qa.ask"></a>\n'
        '          </div>\n'
        '          <div class="qa-body">\n'
        + '\n'.join(body) + '\n'
        '          </div>\n'
        '        </div>\n'
        '      </div>\n'
        '    </section>\n\n'
    )


CSS = '''    /* ---------- 8. Q&A: numbered accordion, three groups ---------- */
    .qa { --qa-pad:clamp(8px,1.6vw,20px); --qa-gap:clamp(14px,2.4vw,28px); --qa-num:2.2rem; interpolate-size:allow-keywords; }
    .qa .split { grid-template-columns:minmax(0,.62fr) minmax(0,1.38fr); }
    .qa-ask { display:inline-flex; align-items:center; gap:12px; margin-top:clamp(20px,3vw,32px); padding:12px 0; font-weight:650; color:var(--c-a); border-bottom:1px solid currentColor; }
    .qa-ask::after { content:"\\2192"; transition:transform .5s var(--ease); }
    .qa-ask:hover::after, .qa-ask:focus-visible::after { transform:translateX(6px); }
    .qa-body { counter-reset:qa; display:grid; gap:clamp(36px,5vw,60px); }
    .qa-group-title { display:flex; align-items:center; gap:18px; margin-bottom:6px; font:700 .76rem/1.2 var(--sans); letter-spacing:.16em; text-transform:uppercase; color:var(--c-a); }
    .qa-group-title::after { content:""; flex:1; height:1px; background:var(--c-line); }
    .qa-group-title:empty { display:none; }
    .qa-group:not(:has(details:not([hidden]))) { display:none; }
    .qa details { counter-increment:qa; border-bottom:1px solid var(--c-line); transition:background-color .5s var(--ease),box-shadow .5s var(--ease); }
    .qa-group-title:empty + details { border-top:1px solid var(--c-line); }
    .qa details[open] { background:var(--c-panel); box-shadow:inset 3px 0 0 var(--c-b); }
    .qa summary { display:grid; grid-template-columns:var(--qa-num) minmax(0,1fr) auto; align-items:center; gap:var(--qa-gap); padding:clamp(20px,2.6vw,28px) var(--qa-pad); cursor:pointer; list-style:none; }
    .qa summary::-webkit-details-marker { display:none; }
    .qa-n::before { content:counter(qa,decimal-leading-zero); font:500 .95rem/1 var(--serif); letter-spacing:.06em; font-variant-numeric:tabular-nums; color:var(--c-a); }
    .qa-q { font:500 clamp(1.1rem,1.7vw,1.4rem)/1.35 var(--serif); letter-spacing:-.01em; color:var(--c-text); text-wrap:balance; }
    .qa summary::after { content:""; flex:none; width:36px; height:36px; border:1px solid var(--c-line); color:var(--c-a); background:linear-gradient(currentColor,currentColor) center/13px 1.8px no-repeat,linear-gradient(currentColor,currentColor) center/1.8px 13px no-repeat; transition:transform .5s var(--ease),border-color .3s ease,background-size .4s var(--ease); }
    .qa summary:hover::after, .qa details[open] summary::after { border-color:var(--c-a); }
    .qa details[open] summary::after { background-size:13px 1.8px,1.8px 0; transform:rotate(180deg); }
    .qa-a { padding:0 var(--qa-pad) clamp(24px,3vw,34px) calc(var(--qa-pad) + var(--qa-num) + var(--qa-gap)); }
    .qa-a p { max-width:62ch; color:var(--c-muted); line-height:1.85; }
    .qa details[open] .qa-a p { animation:fadeIn .6s ease both; }
    @supports (interpolate-size:allow-keywords) {
      .qa details::details-content { block-size:0; overflow:hidden; transition:block-size .55s var(--ease),content-visibility .55s allow-discrete; }
      .qa details[open]::details-content { block-size:auto; }
    }

'''

# Каждая правка шаблона: (что искать, на что заменить, описание). Ищется РОВНО одно вхождение.
def template_edits():
    css_anchor = '    /* ---------- Notes (appear only when an article is published) ---------- */\n'
    notes_marker = '    <!--@@NOTES@@-->\n'
    faq_js = "      $$('[data-faq]').forEach(node => { node.hidden = !t('faq.q' + node.dataset.faq).trim(); });\n"
    split_rule = '.about .split, .contact .split, .faq .split { grid-template-columns:1fr; }'
    small_rule = '      .mcol:nth-child(2) { margin-top:28px; }\n'
    return [
        (css_anchor, CSS + css_anchor, 'стили раздела'),
        (notes_marker, section_markup() + notes_marker, 'разметка раздела'),
        (faq_js, faq_js + "      $$('[data-qa]').forEach(node => { node.hidden = !t('qa.q' + node.dataset.qa).trim(); });\n", 'JS: скрытие пустых слотов'),
        (split_rule, '.about .split, .contact .split, .faq .split, .qa .split { grid-template-columns:1fr; }', 'адаптив ≤900px'),
        (small_rule,
         small_rule + '      .qa { --qa-num:1.7rem; }\n      .qa summary::after { width:32px; height:32px; }\n'
                      '      .qa-a { padding-left:var(--qa-pad); }\n', 'адаптив ≤560px'),
    ]


BUILD_EDITS = [
    ('FAQ_SLOTS = 8\n', 'FAQ_SLOTS = 8\nQA_SLOTS = 8\n', 'константа QA_SLOTS'),
    ("'faq': 'faq', 'free': 'free'}", "'faq': 'faq', 'free': 'free', 'qa': 'qa'}", 'якорь раздела для панели'),
    ("""    for slot in range(1, FAQ_SLOTS + 1):
        if not ru.get(f'faq.q{slot}', '').strip():
            template = replace_required(template, f'<details data-faq="{slot}">', f'<details data-faq="{slot}" hidden>', f'faq slot {slot}')
""",
     """    for slot in range(1, FAQ_SLOTS + 1):
        if not ru.get(f'faq.q{slot}', '').strip():
            template = replace_required(template, f'<details data-faq="{slot}">', f'<details data-faq="{slot}" hidden>', f'faq slot {slot}')
    for slot in range(1, QA_SLOTS + 1):
        if not ru.get(f'qa.q{slot}', '').strip():
            template = replace_required(template, f'<details name="qa" data-qa="{slot}">', f'<details name="qa" data-qa="{slot}" hidden>', f'qa slot {slot}')
""", 'скрытие пустых слотов в статическом HTML'),
]

TEST_EDITS = [
    ("SECTION_IDS = ('hero', 'intro', 'sessions', 'change', 'about', 'contact', 'faq')",
     "SECTION_IDS = ('hero', 'intro', 'sessions', 'change', 'about', 'contact', 'faq', 'qa')", 'порядок секций'),
    ("""    assert builder.FAQ_SLOTS == 8 and template.count('<details data-faq=') == 8, 'FAQ must have 8 editable slots'
""",
     """    assert builder.FAQ_SLOTS == 8 and template.count('<details data-faq=') == 8, 'FAQ must have 8 editable slots'
    assert builder.QA_SLOTS == 8 and template.count('<details name="qa" data-qa=') == 8, 'Q&A must have 8 editable slots'
""", 'проверка слотов Q&A'),
    ("""        ru['faq']['q5'] = ''
""",
     """        ru['faq']['q5'] = ''
        ru['qa']['q3'] = ''
""", 'пустой слот Q&A в полной сборке'),
    ("""        assert '<details data-faq="5" hidden>' in home and '<details data-faq="4">' in home
""",
     """        assert '<details data-faq="5" hidden>' in home and '<details data-faq="4">' in home
        assert '<details name="qa" data-qa="3" hidden>' in home and '<details name="qa" data-qa="2">' in home
""", 'проверка скрытого слота Q&A'),
]


# --------------------------------------------------------------------------------------
# Механика
# --------------------------------------------------------------------------------------
def sub_once(text: str, old: str, new: str, label: str, path: str) -> str:
    n = text.count(old)
    if n != 1:
        raise SystemExit(f'✗ {path}: «{label}» — ожидалось одно совпадение, найдено {n}. '
                         f'Файл отличается от версии, под которую написан скрипт; ничего не записано.')
    return text.replace(old, new, 1)


def patch_json(lang: str) -> str:
    path = f'content/home_{lang}.json'
    raw = (ROOT / path).read_text(encoding='utf-8')
    data = json.loads(raw)
    if 'qa' in data:
        return raw
    if 'free' not in data:
        raise SystemExit(f'✗ {path}: нет группы «free», не понимаю, куда вставлять «qa».')
    out = {}
    for key, value in data.items():
        out[key] = value
        if key == 'free':
            out['qa'] = {k: COPY[lang][k] for k in QA_ORDER}
    return json.dumps(out, ensure_ascii=False, indent=2) + '\n'


def patch_pages_yml() -> str:
    path = '.pages.yml'
    lines = (ROOT / path).read_text(encoding='utf-8').split('\n')
    block = yaml_block().rstrip('\n').split('\n')
    homes = [i for i, l in enumerate(lines) if l.startswith('- name: home_')]
    if len(homes) != 3:
        raise SystemExit(f'✗ {path}: ожидалось 3 файла home_*, найдено {len(homes)}.')
    ends = homes[1:] + [len(lines)]
    # Идём с конца, чтобы индексы выше по файлу не сдвигались.
    for start, end in reversed(list(zip(homes, ends))):
        segment = lines[start:end]
        if '  - name: qa' in segment:
            continue
        try:
            at = start + segment.index('  - name: notes')
        except ValueError:
            raise SystemExit(f'✗ {path}: в «{lines[start]}» нет группы notes, не понимаю, куда вставлять «qa».')
        lines[at:at] = block
    return '\n'.join(lines)


def collect_changes() -> dict[str, str]:
    changes: dict[str, str] = {}

    for lang in ('ru', 'en', 'fr'):
        new = patch_json(lang)
        if new != (ROOT / f'content/home_{lang}.json').read_text(encoding='utf-8'):
            changes[f'content/home_{lang}.json'] = new

    new = patch_pages_yml()
    if new != (ROOT / '.pages.yml').read_text(encoding='utf-8'):
        changes['.pages.yml'] = new

    for rel, edits in (('templates/index.html', template_edits()), ('scripts/build.py', BUILD_EDITS),
                       ('scripts/test_build.py', TEST_EDITS)):
        text = (ROOT / rel).read_text(encoding='utf-8')
        if rel == 'templates/index.html' and MARK in text:
            continue
        if rel == 'scripts/build.py' and 'QA_SLOTS' in text:
            continue
        if rel == 'scripts/test_build.py' and "'qa')" in text:
            continue
        for old, new_text, label in edits:
            text = sub_once(text, old, new_text, label, rel)
        changes[rel] = text

    gi = (ROOT / '.gitignore').read_text(encoding='utf-8') if (ROOT / '.gitignore').exists() else ''
    if '.backup-qa/' not in gi.split():
        changes['.gitignore'] = gi + ('' if gi.endswith('\n') or not gi else '\n') + '.backup-qa/\n'
    return changes


def validate(changes: dict[str, str]) -> None:
    """Проверяем результат ДО записи: JSON, YAML и совпадение ключей CMS с текстами."""
    try:
        import yaml
    except ImportError:
        print('  (PyYAML не установлен — проверка .pages.yml пропущена; сборка проверит её сама)')
        yaml = None
    jsons = {}
    for lang in ('ru', 'en', 'fr'):
        key = f'content/home_{lang}.json'
        text = changes.get(key) or (ROOT / key).read_text(encoding='utf-8')
        jsons[lang] = json.loads(text)
        got = list(jsons[lang]['qa'])
        if got != QA_ORDER:
            raise SystemExit(f'✗ {key}: ключи qa не совпадают с ожидаемыми: {got}')
        blank = [k for k, v in jsons[lang]['qa'].items() if not str(v).strip()]
        if blank:
            raise SystemExit(f'✗ {key}: пустые поля в qa: {blank}')
    if yaml and '.pages.yml' in changes:
        cfg = yaml.safe_load(changes['.pages.yml'])
        for entry in cfg['content']:
            if entry.get('name', '').startswith('home_'):
                qa = next((f for f in entry['fields'] if f['name'] == 'qa'), None)
                names = [f['name'] for f in qa['fields']] if qa else None
                if names != QA_ORDER:
                    raise SystemExit(f'✗ .pages.yml: поля qa в {entry["name"]} не совпадают с JSON: {names}')


def write(changes: dict[str, str]) -> Path:
    target = BACKUP
    if target.exists():
        from datetime import datetime
        target = ROOT / f'.backup-qa-{datetime.now():%Y%m%d-%H%M%S}'
    for rel in changes:
        src = ROOT / rel
        if src.exists():
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    for rel, text in changes.items():
        (ROOT / rel).write_text(text, encoding='utf-8')
    return target


def restore() -> None:
    candidates = sorted(p for p in ROOT.glob('.backup-qa*') if p.is_dir())
    if not candidates:
        raise SystemExit('Резервных копий .backup-qa* не найдено.')
    source = BACKUP if BACKUP.exists() else candidates[-1]
    count = 0
    for file in source.rglob('*'):
        if file.is_file():
            dst = ROOT / file.relative_to(source)
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, dst)
            count += 1
    print(f'Возвращено файлов: {count} (из {source.name}).')


def verify() -> bool:
    ok = True
    for script in ('scripts/build.py', 'scripts/test_build.py'):
        print(f'→ python {script}')
        result = subprocess.run([sys.executable, script], cwd=ROOT, capture_output=True, text=True)
        tail = (result.stdout + result.stderr).strip().splitlines()[-6:]
        for line in tail:
            print('   ', line)
        if result.returncode != 0:
            ok = False
            print(f'✗ {script} завершился с ошибкой.')
            break
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description='Добавляет раздел Q&A (RU/EN/FR).')
    parser.add_argument('--dry-run', action='store_true', help='показать изменения, ничего не записывая')
    parser.add_argument('--no-verify', action='store_true', help='не запускать сборку и тесты после записи')
    parser.add_argument('--restore', action='store_true', help='вернуть файлы из резервной копии')
    args = parser.parse_args()

    if args.restore:
        restore()
        return 0

    needed = ['templates/index.html', '.pages.yml', 'scripts/build.py', 'scripts/test_build.py',
              'content/home_ru.json', 'content/home_en.json', 'content/home_fr.json']
    missing = [p for p in needed if not (ROOT / p).exists()]
    if missing:
        raise SystemExit('Запустите скрипт из корня репозитория. Не найдено: ' + ', '.join(missing))

    changes = collect_changes()
    if not changes:
        print('Раздел Q&A уже добавлен — менять нечего.')
        return 0

    validate(changes)
    print('Будут изменены файлы:')
    for rel in changes:
        print('  •', rel)
    if args.dry_run:
        print('\n--dry-run: ничего не записано.')
        return 0

    backup = write(changes)
    print(f'\n✓ Записано. Копии прежних файлов: {backup.name}/')
    if args.no_verify:
        print('Проверка пропущена (--no-verify). Запустите: python scripts/build.py && python scripts/test_build.py')
        return 0
    print('\nПроверка:')
    if verify():
        print('\n✓ Сборка и тесты прошли. Осталось закоммитить изменения.')
        return 0
    print(f'\nЕсли нужно откатиться: python {Path(__file__).name} --restore')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
