#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_intuition_update.py — переносит презентацию «Website_Intuition v1.1» в существующий лендинг.

Запуск (из корня репозитория):

    python apply_intuition_update.py --pptx Website_Intuition_v1_1.pptx --dry-run   # только показать, что изменится
    python apply_intuition_update.py --pptx Website_Intuition_v1_1.pptx             # применить

Что делает (подробности в docs/CONTENT-REVIEW.md, который скрипт создаёт сам):
  1. Делает резервную копию каждого изменяемого файла в .backup-intuition/<время>/.
  2. Достаёт 6 фотографий из .pptx, сжимает их (WebP, нужен Pillow) и кладёт в media/;
     заполняет только ПУСТЫЕ поля фото в content/site.json (свои уже выбранные фото не трогает).
  3. Переписывает content/home_ru.json, home_en.json, home_fr.json по презентации
     (английский — исходник, RU и FR — перевод). Поля meta, notes, контакты и подвал сохраняет.
  4. Обновляет .pages.yml (редактор Pages CMS) так, чтобы он совпадал с новыми полями.
  5. Заменяет разметку <main> в templates/index.html и дописывает стили/скрипты. Прежняя структура,
     SVG-бабочка, форма, переключатель языка/темы и логика сборки остаются.
  6. Чуть правит scripts/build.py (8 слотов FAQ, поле quote_photo) и scripts/test_build.py (новые проверки).
  7. Запускает scripts/build.py и scripts/test_build.py. Если проверки не прошли — откатывает всё из копии.

Скрипт идемпотентен: повторный запуск даёт тот же результат.
Зависимости: Python 3.9+, PyYAML (уже в requirements.txt). Pillow — по желанию (для WebP).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit('Нужен PyYAML: pip install pyyaml')

LANGS = ('ru', 'en', 'fr')

# ----------------------------------------------------------------------------------------------
# 1. СХЕМА ПОЛЕЙ. Один источник для JSON-файлов и для .pages.yml (редактор Pages CMS).
#    (группа, подпись группы, [(ключ, подпись поля, тип)])
# ----------------------------------------------------------------------------------------------
SCHEMA = [
    ('meta', 'Вкладка браузера и поиск', [
        ('title', 'Название страницы (имя добавится само)', 'string'),
        ('description', 'Описание для поисковиков и соцсетей', 'text')]),
    ('hero', '1 · Главный экран: фото и первая цитата', [
        ('hint', 'Тихая подпись под фото', 'string'),
        ('alt', 'Описание фото для скринридеров', 'string'),
        ('quote1', 'Цитата, строка 1 (это заголовок страницы)', 'text'),
        ('quote2', 'Цитата, строка 2 (меньше, рядом)', 'text')]),
    ('quotes', '2 · Цитаты (проявляются «от руки»)', [
        ('a', 'Цитата А — атмосферная пауза после главного экрана', 'text'),
        ('b', 'Цитата Б — после блока «Почему я работаю со спортсменами»', 'text'),
        ('c', 'Цитата В — поворот внутри «Трансформации»', 'text'),
        ('d', 'Финальная цитата внизу страницы', 'text')]),
    ('story', '3 · Интуиция в спорте', [
        ('title', 'Центральный вопрос (заголовок)', 'text'),
        ('p1', 'Абзац 1', 'text'), ('p2', 'Абзац 2', 'text'),
        ('p3', 'Крупная рукописная строка', 'text'),
        ('p4', 'Абзац 4', 'text'), ('p5', 'Абзац 5', 'text')]),
    ('client', '4 · Для кого это (семь тем из презентации)', [
        ('title', 'Заголовок', 'string'), ('intro', 'Вступление', 'text'),
        ('l1', 'Тема 1 · фраза', 'string'), ('l1t', 'Тема 1 · пояснение', 'text'),
        ('l2', 'Тема 2 · фраза', 'string'), ('l2t', 'Тема 2 · пояснение', 'text'),
        ('l3', 'Тема 3 · фраза', 'string'), ('l3t', 'Тема 3 · пояснение', 'text'),
        ('l4', 'Тема 4 · фраза', 'string'), ('l4t', 'Тема 4 · пояснение', 'text'),
        ('l5', 'Тема 5 · фраза', 'string'), ('l5t', 'Тема 5 · пояснение', 'text'),
        ('l6', 'Тема 6 · фраза', 'string'), ('l6t', 'Тема 6 · пояснение', 'text'),
        ('l7', 'Тема 7 · крупная рукописная фраза', 'string'), ('l7t', 'Тема 7 · пояснение', 'text'),
        ('note', 'Тихая строка в конце', 'text')]),
    ('why', '5 · Почему я работаю со спортсменами', [
        ('title', 'Заголовок', 'text'), ('text', 'Текст (пустая строка = новый абзац)', 'text')]),
    ('about', '6 · Моя история (четыре кадра; фото — в «Контакты, фото, имя»)', [
        ('title', 'Заголовок', 'string'),
        ('c1Title', 'Кадр 1 · заголовок', 'string'), ('c1Text', 'Кадр 1 · текст', 'text'), ('c1Alt', 'Кадр 1 · описание фото', 'string'),
        ('c2Title', 'Кадр 2 · заголовок', 'string'), ('c2Text', 'Кадр 2 · текст', 'text'), ('c2Alt', 'Кадр 2 · описание фото', 'string'),
        ('c3Title', 'Кадр 3 · заголовок', 'string'), ('c3Text', 'Кадр 3 · текст', 'text'), ('c3Alt', 'Кадр 3 · описание фото', 'string'),
        ('c4Title', 'Кадр 4 · заголовок', 'string'), ('c4Text', 'Кадр 4 · текст', 'text'), ('c4Alt', 'Кадр 4 · описание фото', 'string'),
        ('note', 'Рукописная строка после истории', 'text')]),
    ('check', '7 · Момент интуиции', [
        ('title', 'Заголовок', 'string'),
        ('l1', 'Строка 1', 'text'), ('l2', 'Строка 2', 'text'), ('l3', 'Строка 3', 'text'),
        ('note1', 'Рукописная строка 1', 'text'), ('note2', 'Рукописная строка 2', 'text')]),
    ('fork', '8 · Выбор: откликается / сейчас нет', [
        ('lead', 'Первая фраза', 'text'), ('voice', 'Рукописная строка 1', 'string'),
        ('eyes', 'Рукописная строка 2', 'string'),
        ('yesTitle', 'Вариант «откликается» · заголовок', 'string'),
        ('yesText', 'Вариант «откликается» · текст', 'string'),
        ('yesButton', 'Вариант «откликается» · подпись (ведёт к сессиям)', 'string'),
        ('noTitle', 'Вариант «сейчас нет» · заголовок', 'string'),
        ('noText', 'Вариант «сейчас нет» · текст', 'string'),
        ('noButton', 'Вариант «сейчас нет» · подпись', 'string'),
        ('photoAlt', 'Описание фото крупным планом', 'string'),
        ('farewellTitle', 'Спокойное окно · заголовок', 'string'),
        ('farewellText', 'Спокойное окно · текст', 'text'),
        ('farewellEnd', 'Спокойное окно · кнопка «завершить визит»', 'string'),
        ('farewellDone', 'Спокойное окно · текст после «завершить»', 'text'),
        ('farewellBack', 'Спокойное окно · кнопка «продолжить»', 'string')]),
    ('sessions', '9 · Интуитивные сессии', [
        ('title', 'Заголовок', 'string'), ('lead', 'Вводная фраза', 'text'),
        ('h1', 'Блок 1 · заголовок', 'string'), ('p1', 'Блок 1 · текст', 'text'),
        ('h2', 'Блок 2 · заголовок', 'string'), ('p2', 'Блок 2 · текст', 'text'),
        ('h3', 'Блок 3 · заголовок', 'string'), ('p3', 'Блок 3 · текст', 'text'),
        ('h4', 'Блок «Как проходят сессии» · заголовок', 'string'),
        ('p4', 'Блок «Как проходят сессии» · абзац 1', 'text'),
        ('p5', 'Блок «Как проходят сессии» · абзац 2', 'text'),
        ('note', 'Мелкая оговорка про медицину и терапию', 'text'),
        ('bring', 'Что принести с собой', 'text')]),
    ('change', '10 · Трансформация', [
        ('title', 'Заголовок раздела', 'string'),
        ('s1Title', 'Сцена 1 · заголовок', 'string'), ('s1Text', 'Сцена 1 · текст', 'text'),
        ('s2Title', 'Сцена 2 · заголовок', 'string'), ('s2Text', 'Сцена 2 · текст', 'text'),
        ('s3Title', 'Сцена 3 · заголовок', 'string'), ('s3Text', 'Сцена 3 · текст', 'text'),
        ('s4Title', 'Сцена 4 · заголовок', 'string'), ('s4Text', 'Сцена 4 · текст', 'text'),
        ('bTitle', 'Сцена с бабочкой · заголовок', 'string'), ('bText', 'Сцена с бабочкой · текст', 'text'),
        ('mTitle', 'Сцена «когда не понимают» · заголовок', 'string'), ('mText', 'Сцена «когда не понимают» · текст', 'text'),
        ('wTitle', 'Сцена «свидетель» · заголовок', 'string'), ('wText', 'Сцена «свидетель» · текст', 'text'),
        ('wNote', 'Рукописная строка в конце', 'text')]),
    ('invite', '11 · Приглашение', [
        ('title', 'Заголовок', 'text'), ('button', 'Кнопка (ведёт к форме)', 'string')]),
    ('free', '12 · Первые 30 минут', [
        ('number', 'Число в круге', 'string'), ('unit', 'Единица', 'string'),
        ('title', 'Заголовок', 'string'), ('text', 'Текст', 'text')]),
    ('contact', '13 · Контакты и форма', [
        ('title', 'Заголовок', 'string'), ('lead', 'Текст под заголовком', 'text'),
        ('linksTitle', 'Подзаголовок над прямыми контактами', 'string'),
        ('formName', 'Поле «имя»', 'string'), ('formReach', 'Поле «как связаться»', 'string'),
        ('formMessage', 'Поле «сообщение»', 'string'), ('formSend', 'Кнопка отправки', 'string'),
        ('formSent', 'Сообщение после успешной отправки', 'text'),
        ('formNote', 'Мелкая пометка под формой', 'text')]),
    ('faq', '14 · Вопросы и ответы (пустой вопрос скрывает слот)', [
        ('title', 'Заголовок', 'string'), ('lead', 'Текст под заголовком', 'text')]
        + [item for n in range(1, 9) for item in (
            (f'q{n}', f'Вопрос {n}', 'string'), (f'a{n}', f'Ответ {n}', 'text'))]),
    ('notes', '15 · Заметки (раздел виден, только если есть опубликованные статьи)', [
        ('title', 'Заголовок', 'string'), ('lead', 'Текст под заголовком', 'text')]),
    ('footer', '16 · Подвал', [
        ('line', 'Короткая фраза', 'string'), ('privacy', 'Строка о приватности', 'text')]),
]

# Эти поля автор мог уже отредактировать в CMS и они не зависят от презентации: если есть — оставляем.
PRESERVE = {'meta.title', 'meta.description', 'hero.hint', 'quotes.a', 'faq.title', 'faq.lead',
            'notes.title', 'notes.lead', 'footer.line', 'contact.title', 'contact.lead',
            'contact.linksTitle', 'contact.formName', 'contact.formReach', 'contact.formSend',
            'contact.formNote', 'free.number', 'free.unit'}

# ----------------------------------------------------------------------------------------------
# 2. ТЕКСТЫ. Английский — исходник из презентации (опечатки исправлены, абзацы разбиты на фрагменты).
#    Русский и французский — перевод. Женский род в RU/FR сохранён.
# ----------------------------------------------------------------------------------------------
EN = {
    'meta': {'title': 'Intuition in sport',
             'description': 'A personal space about intuition, sport and change, and individual sessions for athletes. The first 30-minute conversation is free and carries no obligation.'},
    'hero': {'hint': 'scroll slowly',
             'alt': 'A smiling woman standing by the sea at dusk with her arms open wide',
             'quote1': 'Intuition is a different kind of intelligence.',
             'quote2': 'There are things you can only know by listening inwardly.'},
    'quotes': {'a': 'You can only control yourself.\nThe rest is out of your control.',
               'b': 'Not everything in life can be understood through logic,\nnor does everything need to be.',
               'c': 'Often, transformation doesn’t lead us to something new;\nit leads us back to ourselves.',
               'd': 'Intuition is a different kind of intelligence.'},
    'story': {'title': 'Intuition is for everyone, so why is this page created specifically for athletes?',
              'p1': 'Because I believe that intuition is essential in sport.',
              'p2': 'Throughout their careers, athletes often experience a powerful connection to their intuition. At least once, every competitive athlete has experienced moments when they instinctively know something that goes beyond the logical next step, their coach’s instructions or an agreed strategy.',
              'p3': 'The momentum, instinct, feel for the game — whatever you call it.',
              'p4': 'They bring an immediate sense of flow and clarity — an inner shift that changes the outer reality.',
              'p5': 'How long and deep this connection goes often determines an athlete’s ability to turn a difficult situation in their favour, stay present and creative, and enjoy their performance.'},
    'client': {'title': 'What we can explore together',
               'intro': 'Connecting to intuition on a deeper level can help athletes navigate both sport and life with greater awareness, balance and self-trust. These are a few examples of what we might explore.',
               'l1': 'Performance pressure', 'l1t': 'Staying connected to the process rather than fixating on the result.',
               'l2': 'Your inner voice', 'l2t': 'Telling it apart from fears, mental chatter and external expectations.',
               'l3': 'Your body', 'l3t': 'Building a deeper relationship with it, and learning to notice what it is telling you.',
               'l4': 'Uncertainty and change', 'l4t': 'Accepting periods of uncertainty, crisis, rest, growth and change as natural parts of everyone’s path.',
               'l5': 'Authenticity', 'l5t': 'Expressing yourself beyond social pressure and rigid ideas of what is right or wrong, possible or impossible.',
               'l6': 'Life beyond sport', 'l6t': 'Shifting attention and energy towards other meaningful aspects of life, and developing an identity beyond sport.',
               'l7': 'Trusting yourself first', 'l7t': 'Listening to the advice of family, friends, coaches, doctors and other experts — and checking it with yourself too.',
               'note': 'If one of these sounds familiar, you are welcome to read on.'},
    'why': {'title': 'I am not an athlete myself — but sport has always been part of my life',
            'text': 'From joining grassroots sports clubs as a child, to becoming a passionate sports fan, and eventually working as a Competition Manager at the world’s largest sports organisations, my journey has taken me through many different sides of sport.\n\nAlong the way I met athletes at different stages of their careers, with different backgrounds, experiences and levels of achievement. I believe this is where I began to relate to them on a deeper level — and to want to direct my energy towards supporting them.'},
    'about': {'title': 'My story',
              'c1Title': 'Sport, always',
              'c1Text': 'Sport has been part of my life since childhood: grassroots clubs, then a passionate fan. For ten years at FIFA I contributed to the organisation of football World Cups and numerous related events.',
              'c1Alt': 'A smiling woman in a pink top standing by the sea',
              'c2Title': '“Enough”',
              'c2Text': 'A few years ago I decided to change direction — not by plan, and with no other plan in hand. Something inside simply said “enough”. I paused, and my focus shifted from external validation and having a cool job towards inner reflection and exploration.',
              'c2Alt': 'A woman standing by a wooden fence among dune grass, looking aside',
              'c3Title': 'Exploring',
              'c3Text': 'I explored psychology, body and energy practices, alternative healing approaches and ancient philosophies. I went deeper into my own experiences, experimented, and gradually discovered new ways of understanding myself.',
              'c3Alt': 'A woman sitting in dry grass in warm evening light',
              'c4Title': 'Learning to trust',
              'c4Text': 'I have always been intuitive, even as a child, but my sensitivity was often dismissed or seen as weakness in my family, so I never learnt to trust it. Over recent years I have cleared my inner voice from layers of family conditioning and social expectations. I trust myself more deeply, and rely less on external validation and the need for constant control and security. It has made my life feel lighter and happier.',
              'c4Alt': 'A smiling woman in a white top by the sea',
              'note': 'This journey continues — and I want to support others in their own search for fulfilment and happiness.'},
    'check': {'title': 'And now, listen',
              'l1': 'You have seen my photographs. You have read my story.',
              'l2': 'Now, take a moment to listen to yourself.',
              'l3': 'Does something resonate? Would you like to talk?',
              'note1': 'If not, that is completely fine, too.',
              'note2': 'Think of it as a first small test of your intuition.'},
    'fork': {'lead': 'Take a moment.',
             'voice': 'Look at the photograph. Notice what comes up.',
             'eyes': 'There is no right answer.',
             'yesTitle': 'Something resonates.', 'yesText': 'I’d like to explore further.', 'yesButton': 'Continue',
             'noTitle': 'I’m not feeling a connection right now.', 'noText': 'That is completely fine.', 'noButton': 'Not now',
             'photoAlt': 'Close-up portrait: part of a woman’s face, looking at the camera',
             'farewellTitle': 'Thank you for stopping by',
             'farewellText': 'Trust what you felt. You are welcome to finish your visit here, or to keep exploring the site.',
             'farewellEnd': 'Finish my visit',
             'farewellDone': 'Thank you for your time. You can close this tab whenever you like.',
             'farewellBack': 'Keep exploring'},
    'sessions': {'title': 'Intuition sessions',
                 'lead': 'A space to develop the ability to connect with yourself, listen to your inner voice and recognise what it is saying.',
                 'h1': 'It speaks differently to everyone',
                 'p1': 'For some, intuition comes as a gut feeling or a sensation in the heart; for others, as a voice, an image, a sudden flash of insight, or even something that appears in a dream. Sometimes it arrives instantly and clearly; at other times it is subtle and needs silence, patience and attention to notice.',
                 'h2': 'Where we begin',
                 'p2': 'Our work begins with exploring what intuition means to you: how you naturally perceive it, how it shows up in different situations, and what helps you recognise its signals. You learn to notice, distinguish and interpret these messages, while developing the confidence to trust your own perceptions.',
                 'h3': 'Not only answers',
                 'p3': 'Intuition can reconnect us with our inner truth: our values, what makes us happy, what we want from life and how we wish to move through it. Yet this journey is not only about understanding and answers. It is also about learning to accept the unknown, the unpredictable and the uncontrollable. Letting go of the boundaries that stand in the way of your inner alignment and contentment is one of the few skills we practise.',
                 'h4': 'How the sessions work',
                 'p4': 'These sessions are led intuitively and individually. There is no predefined programme designed for everyone. My approach is not based on scientific studies or established concepts, but neither does it seek to deny or exclude any particular perspective.',
                 'p5': 'It is not psychological counselling or conventional mental training, though we may touch on some elements of those methods. Sessions normally unfold naturally, instinctively: your intuition will lead us to where your attention and awareness are most needed.',
                 'note': 'Sessions are not a substitute for medical care or psychological therapy.',
                 'bring': 'As with any new experience, curiosity, courage, openness and trust are essential. Above all, bring a willingness to explore, to experience something new, and to discover your beautiful self.'},
    'change': {'title': 'Transformation',
               's1Title': 'It begins before we are ready',
               's1Text': 'Transformation often begins independently of our readiness or desire. At a certain point in life, we feel that something is changing — first inside us.\n\nInitially, we dismiss these shifts, calling them moods or temporary phases, thinking that once something external changes, we’ll return to normal.',
               's2Title': 'We are changing',
               's2Text': 'But at some point, we realise this is not something that will simply pass. We can’t run from it or keep denying it. The first step is to acknowledge the truth: we are changing.',
               's3Title': 'When things lose their power',
               's3Text': 'You recognise this stage when things that once mattered lose their power — what used to bring you joy, purpose and satisfaction no longer does. There is a sense of inner confusion, a void where nothing feels alive or purposeful.',
               's4Title': 'The pull of the familiar',
               's4Text': 'We reach for what is familiar: it feels safe, even when it no longer fits. Resisting change is natural — we do not know what lies on the other side.\n\nThis discomfort is hard to endure for long. Some manage, but often the easiest path is to face it — to welcome what is emerging, to embrace the transformation.',
               'bTitle': 'Rediscovering what feels like you',
               'bText': 'After years of parental advice, education and social conditioning, we often drift far from who we truly are. Transformation pushes us to step back and rediscover what truly feels like us.\n\nThis work is difficult and challenging.',
               'mTitle': 'Being misunderstood',
               'mText': 'In this stage there is a lot of social pressure. People offer well-meaning advice — just keep trying, see a therapist, change jobs, find a new relationship. These shifts might distract you, but ultimately you will confront the same inner truths again.\n\nThis alienation, this sense of being misunderstood, is deeply hard.',
               'wTitle': 'A steady presence',
               'wText': 'What I offer is simply to be a witness — a steady presence as you navigate these shifts, to normalise what you’re feeling. This is deep and individual work, but everyone sometimes needs a hand to hold in these moments. Of course, it’s not a hand you rely on forever. Much of the journey you walk alone, but a friend, a witness, a guide — someone who can name your experience as valid — can make all the difference.\n\nI speak from my own journey, and what I offer is to be that hand, that witness, perhaps even that guide, whenever you need it.',
               'wNote': 'If you are walking this path and don’t have that support, you can reach out.'},
    'invite': {'title': 'If something here resonates, we can start with a conversation.', 'button': 'Write to me'},
    'free': {'number': '30', 'unit': 'minutes', 'title': 'The first 30 minutes are free',
             'text': 'We can simply meet, talk and listen.\n\nThere is no obligation to continue. We can both decide whether it feels right to work together.'},
    'contact': {'title': 'Write to me',
                'lead': 'A few words about you are enough. The details can wait for our conversation.',
                'linksTitle': 'Or reach out directly',
                'formName': 'Your name', 'formReach': 'How to reach you (email, Telegram or WhatsApp)',
                'formMessage': 'What brought you here? (optional)', 'formSend': 'Send',
                'formSent': 'Thank you. Your message has been sent.',
                'formNote': 'Your message will arrive in my inbox. Please do not share medical or other sensitive information here.'},
    'faq': {'title': 'Questions and answers', 'lead': 'If something is still unclear, the answer may be here.',
            'q1': 'How does the first conversation work?',
            'a1': 'The first 30 minutes are free. We can simply meet, talk and listen. There is no obligation to continue — we can both decide whether it feels right to work together.',
            'q2': 'What is an intuition session?',
            'a2': 'It is a space to develop the ability to connect with yourself, listen to your inner voice and recognise what it is saying. Our work begins with exploring what intuition means to you: how you naturally perceive it, and what helps you recognise its signals.',
            'q3': 'Is there a programme or a method?',
            'a3': 'There is no predefined programme designed for everyone. Sessions are led intuitively and individually. My approach is not based on scientific studies or established concepts, but neither does it seek to deny or exclude any particular perspective.',
            'q4': 'Is this psychological counselling?',
            'a4': 'No. It is not psychological counselling or conventional mental training, though we may touch on some elements of those methods. Sessions are not a substitute for medical care or psychological therapy.',
            'q5': 'What is the difference between an intuition session and transformation support?',
            'a5': 'Intuition sessions are about learning to notice, distinguish and trust your own intuition. Transformation support is about having a steady presence — a witness, and perhaps a guide — while something inside you is changing. Which of the two is closer to what you need is something we can explore in the first conversation.',
            'q6': 'What should I bring?',
            'a6': 'Curiosity, courage, openness and trust. Above all, a willingness to explore, to experience something new, and to discover your beautiful self.',
            'q7': '', 'a7': '', 'q8': '', 'a8': ''},
    'notes': {'title': 'Notes', 'lead': 'Short thoughts on sport, intuition and change.'},
    'footer': {'line': 'Listen to yourself.',
               'privacy': 'This site uses no analytics or tracking and does not record what you choose while reading. Your language and theme preferences stay in your own browser. If you write to me, your name and message are used only to reply to you.'},
}

RU = {
    'meta': {'title': 'Интуиция в спорте',
             'description': 'Личное пространство об интуиции, спорте и переменах и индивидуальные сессии для спортсменов. Первая беседа на 30 минут бесплатна и ни к чему не обязывает.'},
    'hero': {'hint': 'листайте не спеша',
             'alt': 'Улыбающаяся женщина стоит у моря на закате, широко раскинув руки',
             'quote1': 'Интуиция — это другой вид интеллекта.',
             'quote2': 'Есть вещи, о которых можно узнать, только прислушавшись к себе.'},
    'quotes': {'a': 'Ты можешь контролировать только себя.\nВсё остальное — вне твоего контроля.',
               'b': 'Не всё в жизни можно понять логикой —\nи не всё нужно понимать.',
               'c': 'Трансформация часто ведёт не к чему-то новому,\nа обратно к себе.',
               'd': 'Интуиция — это другой вид интеллекта.'},
    'story': {'title': 'Интуиция нужна каждому. Почему же эта страница создана именно для спортсменов?',
              'p1': 'Потому что я верю: в спорте интуиция необходима.',
              'p2': 'На протяжении карьеры спортсмены нередко ощущают сильную связь со своей интуицией. Хотя бы раз каждый профессиональный спортсмен переживал моменты, когда он инстинктивно знал нечто большее, чем логичный следующий шаг, указания тренера или оговорённая стратегия.',
              'p3': 'Импульс, инстинкт, чувство игры — как ни назови.',
              'p4': 'Они приносят мгновенное ощущение потока и ясности — внутренний сдвиг, который меняет внешнюю реальность.',
              'p5': 'От того, как долго и глубоко длится эта связь, часто зависит способность спортсмена повернуть трудную ситуацию в свою пользу, оставаться в моменте, сохранять творческий настрой и получать удовольствие от выступления.'},
    'client': {'title': 'Что мы можем исследовать вместе',
               'intro': 'Более глубокая связь с интуицией помогает спортсменам проходить и спорт, и жизнь с большей осознанностью, равновесием и доверием к себе. Вот несколько примеров того, что мы можем исследовать.',
               'l1': 'Соревновательное давление', 'l1t': 'Оставаться связанным с процессом, а не зацикливаться на результате.',
               'l2': 'Внутренний голос', 'l2t': 'Отличать его от страхов, ментальной болтовни и чужих ожиданий.',
               'l3': 'Тело', 'l3t': 'Выстраивать с ним более глубокие отношения и учиться замечать, что оно подсказывает.',
               'l4': 'Неопределённость и перемены', 'l4t': 'Принимать периоды неопределённости, кризиса, отдыха, роста и перемен как естественную часть пути каждого.',
               'l5': 'Подлинность', 'l5t': 'Выражать себя за пределами социального давления и жёстких представлений о том, что правильно и неправильно, возможно и невозможно.',
               'l6': 'Жизнь за пределами спорта', 'l6t': 'Переносить внимание и энергию на другие важные стороны жизни и развивать идентичность, которая не сводится к спорту.',
               'l7': 'Сначала доверять себе', 'l7t': 'Слушать советы семьи, друзей, тренеров, врачей и других специалистов — и сверять их ещё и с собой.',
               'note': 'Если что-то из этого вам знакомо, можно читать дальше.'},
    'why': {'title': 'Я сама не спортсменка, но спорт всегда был частью моей жизни',
            'text': 'От детских любительских спортивных клубов — к страстной болельщице, а затем к работе менеджером соревнований в крупнейших спортивных организациях мира: мой путь прошёл через самые разные стороны спорта.\n\nПо дороге я встречала спортсменов на разных этапах карьеры — с разным опытом, разным прошлым и разным уровнем достижений. Думаю, именно тогда я начала понимать их на более глубоком уровне — и захотела направить свои силы на то, чтобы их поддерживать.'},
    'about': {'title': 'Моя история',
              'c1Title': 'Спорт — всегда рядом',
              'c1Text': 'Спорт был частью моей жизни с детства: любительские клубы, потом страсть болельщицы. А десять лет в FIFA я участвовала в организации чемпионатов мира по футболу и многих связанных с ними событий.',
              'c1Alt': 'Улыбающаяся женщина в розовой майке стоит у моря',
              'c2Title': '«Хватит»',
              'c2Text': 'Несколько лет назад я решила сменить направление — не по плану и не имея другого плана. Что-то внутри просто сказало «хватит». Я взяла паузу, и фокус сместился с внешнего одобрения и «крутой работы» на внутренние размышления и поиск.',
              'c2Alt': 'Женщина стоит у деревянного забора среди дюнной травы и смотрит в сторону',
              'c3Title': 'Поиск',
              'c3Text': 'Я исследовала психологию, телесные и энергетические практики, альтернативные подходы к исцелению и древние философии. Я глубже погружалась в собственный опыт, экспериментировала и постепенно открывала для себя новые способы понимать себя.',
              'c3Alt': 'Женщина сидит в сухой траве в тёплом вечернем свете',
              'c4Title': 'Учиться доверять',
              'c4Text': 'Я всегда была интуитивной, ещё в детстве, но в семье мою чувствительность часто обесценивали или считали слабостью, поэтому я так и не научилась ей доверять. За последние годы я очистила свой внутренний голос от слоёв семейных установок и социальных ожиданий. Я стала глубже доверять себе и меньше зависеть от внешнего одобрения и потребности в постоянном контроле и безопасности. Жизнь от этого стала легче и счастливее.',
              'c4Alt': 'Улыбающаяся женщина в белой майке у моря',
              'note': 'Этот путь продолжается — и я хочу поддерживать других в их собственном поиске полноты жизни и счастья.'},
    'check': {'title': 'А теперь — прислушайтесь',
              'l1': 'Вы увидели мои фотографии и прочитали мою историю.',
              'l2': 'Теперь на минуту прислушайтесь к себе.',
              'l3': 'Откликается ли что-то? Хотите поговорить?',
              'note1': 'Если нет — это совершенно нормально.',
              'note2': 'Считайте это маленькой первой проверкой вашей интуиции.'},
    'fork': {'lead': 'Остановитесь на минуту.',
             'voice': 'Посмотрите на фотографию. Заметьте, что поднимается внутри.',
             'eyes': 'Правильного ответа нет.',
             'yesTitle': 'Что-то откликается.', 'yesText': 'Я хочу узнать больше.', 'yesButton': 'Продолжить',
             'noTitle': 'Сейчас я не чувствую связи.', 'noText': 'Это совершенно нормально.', 'noButton': 'Не сейчас',
             'photoAlt': 'Портрет крупным планом: часть лица женщины, взгляд в камеру',
             'farewellTitle': 'Спасибо, что заглянули',
             'farewellText': 'Доверяйте тому, что вы почувствовали. Можно завершить визит здесь, а можно продолжить знакомство с сайтом.',
             'farewellEnd': 'Завершить визит',
             'farewellDone': 'Спасибо за ваше время. Эту вкладку можно закрыть, когда захотите.',
             'farewellBack': 'Продолжить знакомство'},
    'sessions': {'title': 'Интуитивные сессии',
                 'lead': 'Пространство, где можно развить способность соединяться с собой, слушать внутренний голос и распознавать, что он говорит.',
                 'h1': 'У каждого она говорит по-своему',
                 'p1': 'Для одних интуиция приходит как ощущение в животе или в сердце, для других — как голос, образ, внезапная вспышка понимания или даже сон. Иногда она появляется мгновенно и ясно, а иногда едва различима и требует тишины, терпения и внимания, чтобы её заметить.',
                 'h2': 'С чего мы начинаем',
                 'p2': 'Наша работа начинается с исследования того, что интуиция значит для вас: как вы воспринимаете её естественным образом, как она проявляется в разных ситуациях и что помогает распознавать её сигналы. Вы учитесь замечать, различать и интерпретировать эти послания и обретаете уверенность, чтобы доверять собственному восприятию.',
                 'h3': 'Не только ответы',
                 'p3': 'Интуиция может вернуть нас к нашей внутренней правде: к ценностям, к тому, что делает нас счастливыми, к тому, чего мы хотим от жизни и как хотим по ней идти. Но этот путь не только о понимании и ответах. Он ещё и о том, чтобы учиться принимать неизвестное, непредсказуемое и неподконтрольное. Отпускать границы, которые мешают внутренней согласованности и удовлетворённости, — один из немногих навыков, которые мы практикуем.',
                 'h4': 'Как проходят сессии',
                 'p4': 'Эти сессии ведутся интуитивно и индивидуально. Заранее заданной программы, одинаковой для всех, нет. Мой подход не основан на научных исследованиях или устоявшихся концепциях, но и не стремится отрицать или исключать какую-либо точку зрения.',
                 'p5': 'Это не психологическое консультирование и не классический ментальный тренинг, хотя мы можем касаться отдельных элементов этих методов. Обычно сессии разворачиваются естественно, инстинктивно: ваша интуиция сама приведёт нас туда, где ваше внимание и осознанность нужны в первую очередь.',
                 'note': 'Сессии не заменяют медицинскую помощь или психологическую терапию.',
                 'bring': 'Как и в любом новом опыте, здесь важны любопытство, смелость, открытость и доверие. А главное — принесите готовность исследовать, пережить что-то новое и открыть своё прекрасное «я».'},
    'change': {'title': 'Трансформация',
               's1Title': 'Это начинается раньше, чем мы готовы',
               's1Text': 'Трансформация часто начинается независимо от нашей готовности или желания. В какой-то момент жизни мы чувствуем, что что-то меняется — сначала внутри нас.\n\nПоначалу мы отмахиваемся от этих сдвигов, называем их настроением или временным периодом и думаем, что как только изменится что-то внешнее, всё вернётся в норму.',
               's2Title': 'Мы меняемся',
               's2Text': 'Но в какой-то момент мы понимаем: это не пройдёт само. Мы не можем убежать от этого и не можем бесконечно отрицать. Первый шаг — признать правду: мы меняемся.',
               's3Title': 'Когда прежнее теряет силу',
               's3Text': 'Этот этап можно узнать по тому, что прежде важное теряет силу: то, что раньше приносило радость, смысл и удовлетворение, больше этого не даёт. Возникает внутренняя растерянность, пустота, в которой ничто не кажется живым или осмысленным.',
               's4Title': 'Притяжение привычного',
               's4Text': 'Мы тянемся к привычному: оно кажется безопасным, даже когда уже не подходит. Сопротивляться переменам естественно — мы не знаем, что ждёт по ту сторону.\n\nДолго выносить этот дискомфорт трудно. Кто-то справляется, но чаще самый лёгкий путь — встретить его лицом к лицу: принять то, что возникает, принять трансформацию.',
               'bTitle': 'Вспомнить, что ощущается как «я»',
               'bText': 'После лет родительских советов, образования и социальных установок мы часто уходим далеко от того, кто мы на самом деле. Трансформация подталкивает нас отступить на шаг и заново найти то, что по-настоящему ощущается нами.\n\nЭта работа трудная и непростая.',
               'mTitle': 'Когда вас не понимают',
               'mText': 'На этом этапе много социального давления. Люди дают добрые советы: продолжай стараться, сходи к психотерапевту, смени работу, найди новые отношения. Эти перемены могут отвлечь, но в итоге вы снова столкнётесь с теми же внутренними истинами.\n\nЭто отчуждение, это чувство, что тебя не понимают, — очень тяжело.',
               'wTitle': 'Спокойное присутствие',
               'wText': 'Я предлагаю просто быть свидетелем — устойчивым присутствием рядом, пока вы проходите эти перемены, и помочь нормализовать то, что вы чувствуете. Это глубокая и индивидуальная работа, но каждому иногда нужна рука, за которую можно взяться. Конечно, не рука, на которую опираешься всю жизнь. Большую часть пути вы проходите сами, но друг, свидетель, проводник — тот, кто может признать ваш опыт настоящим, — способен изменить многое.\n\nЯ говорю из собственного пути, и я предлагаю быть этой рукой, этим свидетелем, возможно, даже проводником — тогда, когда вам это нужно.',
               'wNote': 'Если вы идёте по этому пути и у вас нет такой поддержки, вы можете написать мне.'},
    'invite': {'title': 'Если что-то здесь откликнулось, мы можем начать с разговора.', 'button': 'Написать мне'},
    'free': {'number': '30', 'unit': 'минут', 'title': 'Первые 30 минут бесплатны',
             'text': 'Мы можем просто встретиться, поговорить и послушать.\n\nПродолжать необязательно. Мы оба решим, подходит ли нам работать вместе.'},
    'contact': {'title': 'Напишите мне',
                'lead': 'Достаточно нескольких слов о себе. Подробности могут подождать до нашего разговора.',
                'linksTitle': 'Или напрямую',
                'formName': 'Ваше имя', 'formReach': 'Как с вами связаться (email, Telegram или WhatsApp)',
                'formMessage': 'Что привело вас сюда? (необязательно)', 'formSend': 'Отправить',
                'formSent': 'Спасибо. Ваше сообщение отправлено.',
                'formNote': 'Сообщение придёт мне на почту. Пожалуйста, не отправляйте здесь медицинские и другие чувствительные данные.'},
    'faq': {'title': 'Вопросы и ответы', 'lead': 'Если что-то осталось неясным — возможно, ответ здесь.',
            'q1': 'Как проходит первая беседа?',
            'a1': 'Первые 30 минут бесплатны. Мы можем просто встретиться, поговорить и послушать. Продолжать необязательно — мы оба решим, подходит ли нам работать вместе.',
            'q2': 'Что такое интуитивная сессия?',
            'a2': 'Это пространство, где можно развить способность соединяться с собой, слушать внутренний голос и распознавать, что он говорит. Наша работа начинается с исследования того, что интуиция значит для вас: как вы её естественным образом воспринимаете и что помогает распознавать её сигналы.',
            'q3': 'Есть ли программа или метод?',
            'a3': 'Заранее заданной программы, одинаковой для всех, нет. Сессии ведутся интуитивно и индивидуально. Мой подход не основан на научных исследованиях или устоявшихся концепциях, но и не стремится отрицать или исключать какую-либо точку зрения.',
            'q4': 'Это психологическое консультирование?',
            'a4': 'Нет. Это не психологическое консультирование и не классический ментальный тренинг, хотя мы можем касаться отдельных элементов этих методов. Сессии не заменяют медицинскую помощь или психологическую терапию.',
            'q5': 'Чем интуитивная сессия отличается от сопровождения в трансформации?',
            'a5': 'Интуитивные сессии — о том, чтобы учиться замечать, различать и доверять собственной интуиции. Сопровождение в трансформации — о спокойном присутствии рядом: свидетеля, а возможно и проводника, пока что-то внутри вас меняется. Что из двух ближе к тому, что нужно вам, мы можем исследовать в первой беседе.',
            'q6': 'Что мне принести с собой?',
            'a6': 'Любопытство, смелость, открытость и доверие. А главное — готовность исследовать, пережить что-то новое и открыть своё прекрасное «я».',
            'q7': '', 'a7': '', 'q8': '', 'a8': ''},
    'notes': {'title': 'Заметки', 'lead': 'Короткие мысли о спорте, интуиции и переменах.'},
    'footer': {'line': 'Прислушайтесь к себе.',
               'privacy': 'На этом сайте нет аналитики и слежки, и он не запоминает, что вы выбираете по ходу чтения. Настройки языка и темы хранятся только в вашем браузере. Если вы мне напишете, ваше имя и сообщение используются только для ответа вам.'},
}

FR = {
    'meta': {'title': 'L’intuition dans le sport',
             'description': 'Un espace personnel sur l’intuition, le sport et le changement, et des séances individuelles pour les sportifs. Le premier échange de 30 minutes est gratuit et sans engagement.'},
    'hero': {'hint': 'faites défiler doucement',
             'alt': 'Une femme souriante au bord de la mer au crépuscule, les bras grands ouverts',
             'quote1': 'L’intuition est une autre forme d’intelligence.',
             'quote2': 'Il y a des choses que l’on ne peut connaître qu’en s’écoutant de l’intérieur.'},
    'quotes': {'a': 'Tu ne peux contrôler que toi-même.\nLe reste ne dépend pas de toi.',
               'b': 'Tout ne se comprend pas par la logique,\net il n’est pas nécessaire que tout se comprenne.',
               'c': 'Souvent, la transformation ne nous mène pas vers quelque chose de nouveau :\nelle nous ramène à nous-mêmes.',
               'd': 'L’intuition est une autre forme d’intelligence.'},
    'story': {'title': 'L’intuition est pour tout le monde, alors pourquoi cette page est-elle créée spécialement pour les sportifs ?',
              'p1': 'Parce que je crois que l’intuition est essentielle dans le sport.',
              'p2': 'Au fil de leur carrière, les sportifs vivent souvent un lien puissant avec leur intuition. Au moins une fois, tout athlète de compétition a connu des moments où il sait instinctivement quelque chose qui va au-delà de la prochaine étape logique, des consignes de l’entraîneur ou d’une stratégie convenue.',
              'p3': 'L’élan, l’instinct, le sens du jeu — peu importe le nom qu’on lui donne.',
              'p4': 'Ils apportent un sentiment immédiat de fluidité et de clarté — un basculement intérieur qui change la réalité extérieure.',
              'p5': 'La durée et la profondeur de ce lien déterminent souvent la capacité d’un sportif à retourner une situation difficile en sa faveur, à rester présent et créatif, et à prendre plaisir à sa performance.'},
    'client': {'title': 'Ce que nous pouvons explorer ensemble',
               'intro': 'Se relier plus profondément à son intuition peut aider les sportifs à traverser le sport comme la vie avec plus de conscience, d’équilibre et de confiance en eux. Voici quelques exemples de ce que nous pouvons explorer.',
               'l1': 'La pression de la performance', 'l1t': 'Rester relié au processus plutôt que de se focaliser sur le résultat.',
               'l2': 'Votre voix intérieure', 'l2t': 'La distinguer des peurs, du bavardage mental et des attentes extérieures.',
               'l3': 'Votre corps', 'l3t': 'Construire avec lui une relation plus profonde et apprendre à remarquer ce qu’il vous dit.',
               'l4': 'L’incertitude et le changement', 'l4t': 'Accepter les périodes d’incertitude, de crise, de repos, de croissance et de changement comme des parties naturelles du chemin de chacun.',
               'l5': 'L’authenticité', 'l5t': 'S’exprimer au-delà de la pression sociale et des idées rigides sur ce qui est bien ou mal, possible ou impossible.',
               'l6': 'Une vie au-delà du sport', 'l6t': 'Tourner son attention et son énergie vers d’autres aspects importants de la vie et développer une identité qui ne se réduit pas au sport.',
               'l7': 'D’abord se faire confiance', 'l7t': 'Écouter les conseils de la famille, des amis, des entraîneurs, des médecins et d’autres experts — et les confronter aussi à soi-même.',
               'note': 'Si l’un de ces thèmes vous parle, vous pouvez poursuivre la lecture.'},
    'why': {'title': 'Je ne suis pas sportive moi-même, mais le sport a toujours fait partie de ma vie',
            'text': 'Des clubs sportifs amateurs de mon enfance au statut de fan passionnée, puis au poste de Competition Manager dans les plus grandes organisations sportives du monde, mon parcours m’a fait traverser de nombreuses facettes du sport.\n\nEn chemin, j’ai rencontré des sportifs à différents stades de leur carrière, d’horizons, d’expériences et de niveaux de réussite très divers. C’est là, je crois, que j’ai commencé à les comprendre plus profondément — et à vouloir mettre mon énergie au service de leur accompagnement.'},
    'about': {'title': 'Mon histoire',
              'c1Title': 'Le sport, depuis toujours',
              'c1Text': 'Le sport fait partie de ma vie depuis l’enfance : les clubs amateurs, puis la fan passionnée. Pendant dix ans à la FIFA, j’ai contribué à l’organisation des Coupes du monde de football et de nombreux événements associés.',
              'c1Alt': 'Une femme souriante en haut rose au bord de la mer',
              'c2Title': '« Assez »',
              'c2Text': 'Il y a quelques années, j’ai décidé de changer de direction — sans plan, et sans autre plan en main. Quelque chose en moi a simplement dit « assez ». J’ai fait une pause, et mon attention s’est déplacée de la validation extérieure et d’un « super travail » vers la réflexion et l’exploration intérieures.',
              'c2Alt': 'Une femme près d’une clôture en bois, parmi les herbes des dunes, regardant sur le côté',
              'c3Title': 'Explorer',
              'c3Text': 'J’ai exploré la psychologie, les pratiques corporelles et énergétiques, des approches alternatives de soin et les philosophies anciennes. Je suis allée plus loin dans ma propre expérience, j’ai expérimenté, et peu à peu découvert de nouvelles façons de me comprendre.',
              'c3Alt': 'Une femme assise dans l’herbe sèche, dans la lumière chaude du soir',
              'c4Title': 'Apprendre à me faire confiance',
              'c4Text': 'J’ai toujours été intuitive, déjà enfant, mais ma sensibilité était souvent écartée ou vue comme une faiblesse dans ma famille ; je n’ai donc pas appris à lui faire confiance. Ces dernières années, j’ai dégagé ma voix intérieure des couches de conditionnement familial et d’attentes sociales. Je me fais plus profondément confiance et dépends moins de la validation extérieure et du besoin constant de contrôle et de sécurité. Ma vie en est devenue plus légère et plus heureuse.',
              'c4Alt': 'Une femme souriante en haut blanc au bord de la mer',
              'note': 'Ce chemin continue — et je veux soutenir les autres dans leur propre quête d’épanouissement et de bonheur.'},
    'check': {'title': 'Maintenant, écoutez-vous',
              'l1': 'Vous avez vu mes photographies. Vous avez lu mon histoire.',
              'l2': 'Prenez maintenant un instant pour vous écouter.',
              'l3': 'Quelque chose résonne-t-il ? Avez-vous envie d’échanger ?',
              'note1': 'Sinon, c’est tout à fait normal aussi.',
              'note2': 'Voyez-y un premier petit test de votre intuition.'},
    'fork': {'lead': 'Prenez un instant.',
             'voice': 'Regardez la photographie. Remarquez ce qui monte en vous.',
             'eyes': 'Il n’y a pas de bonne réponse.',
             'yesTitle': 'Quelque chose résonne.', 'yesText': 'J’aimerais en savoir plus.', 'yesButton': 'Continuer',
             'noTitle': 'Je ne ressens pas de lien pour l’instant.', 'noText': 'C’est tout à fait normal.', 'noButton': 'Pas maintenant',
             'photoAlt': 'Portrait en gros plan : une partie du visage d’une femme, regardant l’objectif',
             'farewellTitle': 'Merci de votre visite',
             'farewellText': 'Faites confiance à ce que vous avez ressenti. Vous pouvez terminer votre visite ici, ou continuer à explorer le site.',
             'farewellEnd': 'Terminer ma visite',
             'farewellDone': 'Merci pour votre temps. Vous pouvez fermer cet onglet quand vous le souhaitez.',
             'farewellBack': 'Continuer à explorer'},
    'sessions': {'title': 'Séances d’intuition',
                 'lead': 'Un espace pour développer la capacité de se relier à soi, d’écouter sa voix intérieure et de reconnaître ce qu’elle dit.',
                 'h1': 'Elle parle différemment à chacun',
                 'p1': 'Pour certains, l’intuition vient comme une sensation au ventre ou dans le cœur ; pour d’autres, comme une voix, une image, un éclair soudain de compréhension, ou même quelque chose qui apparaît en rêve. Parfois elle arrive instantanément et clairement ; d’autres fois elle est subtile et demande du silence, de la patience et de l’attention pour être remarquée.',
                 'h2': 'Là où nous commençons',
                 'p2': 'Notre travail commence par explorer ce que l’intuition signifie pour vous : comment vous la percevez naturellement, comment elle se manifeste dans différentes situations, et ce qui vous aide à reconnaître ses signaux. Vous apprenez à remarquer, distinguer et interpréter ces messages, tout en développant la confiance nécessaire pour vous fier à vos propres perceptions.',
                 'h3': 'Pas seulement des réponses',
                 'p3': 'L’intuition peut nous reconnecter à notre vérité intérieure : nos valeurs, ce qui nous rend heureux, ce que nous voulons de la vie et la façon dont nous souhaitons la traverser. Pourtant, ce chemin ne consiste pas seulement à comprendre et à trouver des réponses. Il s’agit aussi d’apprendre à accepter l’inconnu, l’imprévisible et l’incontrôlable. Lâcher les limites qui empêchent votre alignement intérieur et votre contentement est l’une des rares compétences que nous pratiquons.',
                 'h4': 'Comment se déroulent les séances',
                 'p4': 'Ces séances sont menées de façon intuitive et individuelle. Il n’existe pas de programme prédéfini conçu pour tout le monde. Mon approche ne repose pas sur des études scientifiques ni sur des concepts établis, mais elle ne cherche pas non plus à nier ou à exclure un point de vue particulier.',
                 'p5': 'Ce n’est ni du conseil psychologique ni du mental training classique, même si nous pouvons toucher à certains éléments de ces méthodes. Les séances se déroulent en général naturellement, instinctivement : votre intuition nous conduira là où votre attention et votre conscience sont le plus nécessaires.',
                 'note': 'Les séances ne remplacent ni les soins médicaux ni une thérapie psychologique.',
                 'bring': 'Comme pour toute nouvelle expérience, la curiosité, le courage, l’ouverture et la confiance sont essentiels. Apportez surtout l’envie d’explorer, de vivre quelque chose de nouveau et de découvrir votre beauté intérieure.'},
    'change': {'title': 'Transformation',
               's1Title': 'Cela commence avant que nous soyons prêts',
               's1Text': 'La transformation commence souvent indépendamment de notre préparation ou de notre désir. À un certain moment de la vie, nous sentons que quelque chose change — d’abord en nous.\n\nAu début, nous écartons ces changements, les appelant des humeurs ou des phases passagères, pensant qu’une fois que quelque chose d’extérieur aura changé, tout redeviendra normal.',
               's2Title': 'Nous changeons',
               's2Text': 'Mais à un moment, nous réalisons que cela ne va pas simplement passer. Nous ne pouvons ni le fuir ni continuer à le nier. La première étape est de reconnaître la vérité : nous changeons.',
               's3Title': 'Quand les choses perdent leur force',
               's3Text': 'On reconnaît cette étape quand ce qui comptait autrefois perd sa force : ce qui apportait joie, sens et satisfaction ne le fait plus. Il y a une confusion intérieure, un vide où rien ne semble vivant ni porteur de sens.',
               's4Title': 'L’attrait du familier',
               's4Text': 'Nous cherchons le familier : il rassure, même quand il ne nous convient plus. Résister au changement est naturel — nous ne savons pas ce qui se trouve de l’autre côté.\n\nCet inconfort est difficile à supporter longtemps. Certains y parviennent, mais souvent le chemin le plus simple est de lui faire face — d’accueillir ce qui émerge, d’embrasser la transformation.',
               'bTitle': 'Retrouver ce qui nous ressemble',
               'bText': 'Après des années de conseils parentaux, d’éducation et de conditionnement social, nous nous éloignons souvent de qui nous sommes vraiment. La transformation nous pousse à prendre du recul et à retrouver ce qui nous ressemble vraiment.\n\nCe travail est difficile et exigeant.',
               'mTitle': 'Ne pas être compris',
               'mText': 'À ce stade, la pression sociale est forte. Les gens donnent des conseils bien intentionnés : continue d’essayer, va voir un thérapeute, change de travail, trouve une nouvelle relation. Ces changements peuvent distraire, mais finalement vous retrouverez les mêmes vérités intérieures.\n\nCette aliénation, ce sentiment de ne pas être compris, est profondément difficile.',
               'wTitle': 'Une présence stable',
               'wText': 'Ce que je propose, c’est simplement d’être un témoin — une présence stable pendant que vous traversez ces changements, pour normaliser ce que vous ressentez. C’est un travail profond et individuel, mais chacun a parfois besoin d’une main à tenir dans ces moments. Bien sûr, ce n’est pas une main sur laquelle on s’appuie pour toujours. Une grande partie du chemin se fait seul, mais un ami, un témoin, un guide — quelqu’un qui peut nommer votre expérience comme légitime — peut faire toute la différence.\n\nJe parle depuis mon propre chemin, et ce que je propose, c’est d’être cette main, ce témoin, peut-être même ce guide, quand vous en avez besoin.',
               'wNote': 'Si vous marchez sur ce chemin sans avoir ce soutien, vous pouvez me contacter.'},
    'invite': {'title': 'Si quelque chose ici résonne, nous pouvons commencer par une conversation.', 'button': 'M’écrire'},
    'free': {'number': '30', 'unit': 'minutes', 'title': 'Les 30 premières minutes sont gratuites',
             'text': 'Nous pouvons simplement nous rencontrer, parler et écouter.\n\nIl n’y a aucune obligation de poursuivre. Nous déciderons tous les deux si cela nous convient de travailler ensemble.'},
    'contact': {'title': 'Écrivez-moi',
                'lead': 'Quelques mots sur vous suffisent. Les détails peuvent attendre notre conversation.',
                'linksTitle': 'Ou directement',
                'formName': 'Votre prénom', 'formReach': 'Comment vous joindre (e-mail, Telegram ou WhatsApp)',
                'formMessage': 'Qu’est-ce qui vous a amené ici ? (facultatif)', 'formSend': 'Envoyer',
                'formSent': 'Merci. Votre message a bien été envoyé.',
                'formNote': 'Votre message arrivera dans ma boîte mail. Merci de ne pas partager ici d’informations médicales ou autrement sensibles.'},
    'faq': {'title': 'Questions et réponses', 'lead': 'Si quelque chose reste flou, la réponse est peut-être ici.',
            'q1': 'Comment se passe le premier échange ?',
            'a1': 'Les 30 premières minutes sont gratuites. Nous pouvons simplement nous rencontrer, parler et écouter. Rien ne vous oblige à poursuivre — nous déciderons tous les deux si cela nous convient de travailler ensemble.',
            'q2': 'Qu’est-ce qu’une séance d’intuition ?',
            'a2': 'C’est un espace pour développer la capacité de se relier à soi, d’écouter sa voix intérieure et de reconnaître ce qu’elle dit. Notre travail commence par explorer ce que l’intuition signifie pour vous : comment vous la percevez naturellement et ce qui vous aide à reconnaître ses signaux.',
            'q3': 'Y a-t-il un programme ou une méthode ?',
            'a3': 'Il n’existe pas de programme prédéfini conçu pour tout le monde. Les séances sont menées de façon intuitive et individuelle. Mon approche ne repose pas sur des études scientifiques ni sur des concepts établis, mais elle ne cherche pas non plus à nier ou à exclure un point de vue particulier.',
            'q4': 'Est-ce du conseil psychologique ?',
            'a4': 'Non. Ce n’est ni du conseil psychologique ni du mental training classique, même si nous pouvons toucher à certains éléments de ces méthodes. Les séances ne remplacent ni les soins médicaux ni une thérapie psychologique.',
            'q5': 'Quelle différence entre une séance d’intuition et l’accompagnement de transformation ?',
            'a5': 'Les séances d’intuition consistent à apprendre à remarquer, distinguer et faire confiance à sa propre intuition. L’accompagnement de transformation consiste à offrir une présence stable — un témoin, et peut-être un guide — pendant que quelque chose change en vous. Ce qui correspond le mieux à vos besoins, nous pouvons l’explorer lors du premier échange.',
            'q6': 'Que dois-je apporter ?',
            'a6': 'De la curiosité, du courage, de l’ouverture et de la confiance. Surtout l’envie d’explorer, de vivre quelque chose de nouveau et de découvrir votre beauté intérieure.',
            'q7': '', 'a7': '', 'q8': '', 'a8': ''},
    'notes': {'title': 'Notes', 'lead': 'De courtes réflexions sur le sport, l’intuition et le changement.'},
    'footer': {'line': 'Écoutez-vous.',
               'privacy': 'Ce site n’utilise ni analyse d’audience ni suivi, et n’enregistre pas ce que vous choisissez en lisant. Vos préférences de langue et de thème restent dans votre propre navigateur. Si vous m’écrivez, votre prénom et votre message ne servent qu’à vous répondre.'},
}
COPY = {'en': EN, 'ru': RU, 'fr': FR}

# ----------------------------------------------------------------------------------------------
# 3. РАЗМЕТКА <main>. Бабочка и «рука» (SVG) берутся из текущего шаблона, а не переписываются.
# ----------------------------------------------------------------------------------------------
PH_PERSON = '<div class="ph" aria-hidden="true"><svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="32" cy="22" r="10"/><path d="M10 58c1-14 9-22 22-22s21 8 22 22"/></svg><span data-i18n="photoSoon"></span></div>'
PH_FRAME = '<div class="ph" aria-hidden="true"><svg viewBox="0 0 64 64" fill="none" stroke="currentColor" stroke-width="1.7"><circle cx="22" cy="26" r="6"/><path d="m9 47 14-13 9 7 11-13 13 16"/></svg><span data-i18n="photoSoon"></span></div>'
STROKE = '<svg class="quote-stroke" viewBox="0 0 300 18" preserveAspectRatio="none" aria-hidden="true"><path pathLength="1" d="M2 11 C40 2 72 17 112 9 S190 3 232 10 S282 15 298 7"/></svg>'


def quote_block(letter: str, with_photo: bool = False) -> str:
    bg = ('<figure class="photo quote-bg" aria-hidden="true"><img data-photo="quote_photo" alt="" loading="lazy" decoding="async"></figure>'
          if with_photo else '')
    return (f'    <section class="quote q-{letter}">\n'
            f'      <div class="quote-card"><i></i><i></i><i></i>{bg}\n'
            f'        <blockquote class="quote-text" data-write data-i18n="quotes.{ {"a":"a","b":"b","c":"c","d":"d"}[letter] }"></blockquote>\n'
            f'        {STROKE}\n      </div>\n    </section>\n')


def chapter(n: int, photo_first: bool) -> str:
    fig = (f'<figure class="photo"><img data-photo="story_photo_{n}" data-i18n-alt="about.c{n}Alt" alt="" loading="lazy" decoding="async">{PH_FRAME}</figure>')
    glass = ' glass' if n == 4 else ''
    text = f'<div class="chap-text{glass}" data-fade><h3 data-i18n="about.c{n}Title"></h3><p data-i18n="about.c{n}Text"></p></div>'
    parts = (fig + '\n          ' + text) if photo_first else (text + '\n          ' + fig)
    return f'        <article class="chapter c{n}">\n          {parts}\n        </article>\n'


def thread(n: int) -> str:
    delay = f' style="--d:{(n % 3) * .12:.2f}s"' if n % 3 else ''
    return (f'          <li class="thread" data-fade{delay}><strong data-i18n="client.l{n}"></strong>'
            f'<span data-i18n="client.l{n}t"></span></li>\n')


def build_main(mm_svg: str, hold_svg: str) -> str:
    threads = ''.join(thread(n) for n in range(1, 8))
    chapters = chapter(1, True) + chapter(2, False) + chapter(3, True) + chapter(4, True)
    faq = ''.join(f'          <details data-faq="{n}"><summary data-i18n="faq.q{n}"></summary><p data-i18n="faq.a{n}"></p></details>\n' for n in range(1, 9))
    return f'''<main id="main" tabindex="-1">
    <!-- 1. Opening: the encounter. The quotation and the photograph form one composition. -->
    <section class="hero" id="hero">
      <div class="hero-stage">
        <figure class="photo hero-photo">
          <img data-photo="portrait" data-i18n-alt="hero.alt" alt="" fetchpriority="high" decoding="async">
          {PH_PERSON}
        </figure>
        <div class="hero-quote">
          <h1 class="hero-q1" data-i18n="hero.quote1"></h1>
          <p class="hero-q2" data-i18n="hero.quote2"></p>
        </div>
        <div class="hero-tag glass"><strong data-i18n="portraitName"></strong><span data-i18n="portraitJob"></span></div>
      </div>
      <p class="hero-hint"><i aria-hidden="true"></i><span data-i18n="hero.hint"></span></p>
    </section>

    <!-- 2. Atmospheric pause (optional landscape photo: site.json -> quote_photo) -->
{quote_block('a', True)}
    <!-- 3. Intuition in sport -->
    <section class="sec story" id="story" aria-labelledby="story-title">
      <div class="container">
        <div class="ripple" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="story-body">
          <h2 class="title" id="story-title" data-fade data-i18n="story.title"></h2>
          <p class="lead" data-fade style="--d:.15s" data-i18n="story.p1"></p>
          <p class="mid" data-fade style="--d:.1s" data-i18n="story.p2"></p>
          <p class="story-pull" data-fade data-i18n="story.p3"></p>
          <p class="mid" data-fade data-i18n="story.p4"></p>
          <p class="lead" data-fade style="--d:.1s" data-i18n="story.p5"></p>
        </div>
      </div>
    </section>

    <!-- 4. What we can explore: a quiet sequence of fragments, not cards -->
    <section class="sec client" id="client" aria-labelledby="client-title">
      <div class="container">
        <div class="client-head">
          <h2 class="title" id="client-title" data-fade data-i18n="client.title"></h2>
          <p class="lead" data-fade style="--d:.1s" data-i18n="client.intro"></p>
        </div>
        <ul class="threads">
{threads}        </ul>
        <p class="client-note" data-fade data-i18n="client.note"></p>
      </div>
    </section>

    <!-- 5. Why athletes -->
    <section class="sec why" id="why" aria-labelledby="why-title">
      <div class="container">
        <div class="why-art" aria-hidden="true"><i></i><i></i></div>
        <div class="why-body">
          <h2 class="title" id="why-title" data-fade data-i18n="why.title"></h2>
          <p class="lead" data-fade style="--d:.15s" data-i18n="why.text"></p>
        </div>
      </div>
    </section>

{quote_block('b')}
    <!-- 6. My story: four frames, ongoing -->
    <section class="sec about" id="about" aria-labelledby="about-title">
      <div class="container">
        <div class="about-head"><h2 class="title" id="about-title" data-fade data-i18n="about.title"></h2></div>
{chapters}        <p class="about-note" data-fade data-i18n="about.note"></p>
      </div>
    </section>

    <!-- 7. The intuition moment -->
    <section class="sec sec--air check" id="check" aria-labelledby="check-title">
      <div class="container">
        <div class="ripple" aria-hidden="true"><i></i><i></i><i></i></div>
        <h2 class="title" id="check-title" data-fade data-i18n="check.title"></h2>
        <p class="check-line" data-fade data-i18n="check.l1"></p>
        <p class="check-line" data-fade style="--d:.2s" data-i18n="check.l2"></p>
        <p class="check-line" data-fade style="--d:.2s" data-i18n="check.l3"></p>
        <p class="check-note" data-fade data-i18n="check.note1"></p>
        <p class="check-note" data-fade data-i18n="check.note2"></p>
      </div>
    </section>

    <!-- 8. Two equal choices. Nothing is recorded. -->
    <section class="sec fork" id="fork" aria-labelledby="fork-lead">
      <div class="container">
        <figure class="photo eyes"><img data-photo="eyes_photo" data-i18n-alt="fork.photoAlt" alt="" loading="lazy" decoding="async">{PH_PERSON}</figure>
        <div>
          <h2 class="fork-lead" id="fork-lead" data-fade data-i18n="fork.lead"></h2>
          <p class="fork-voice" data-fade style="--d:.2s" data-i18n="fork.voice"></p>
          <p class="fork-voice" data-fade style="--d:.4s" data-i18n="fork.eyes"></p>
          <div class="paths">
            <a class="path path-yes" href="#sessions"><strong data-i18n="fork.yesTitle"></strong><span data-i18n="fork.yesText"></span><em data-i18n="fork.yesButton"></em></a>
            <button class="path path-no" type="button" id="close-page"><strong data-i18n="fork.noTitle"></strong><span data-i18n="fork.noText"></span><em data-i18n="fork.noButton"></em></button>
          </div>
        </div>
      </div>
    </section>

    <!-- 9. Intuition sessions -->
    <section class="sec sessions" id="sessions" aria-labelledby="sessions-title">
      <div class="container">
        <div class="sessions-head">
          <h2 class="title" id="sessions-title" data-fade data-i18n="sessions.title"></h2>
          <p class="sessions-lead" data-fade style="--d:.1s" data-i18n="sessions.lead"></p>
        </div>
        <div class="s-flow">
          <article class="s-block s1" data-fade><h3 data-i18n="sessions.h1"></h3><p data-i18n="sessions.p1"></p></article>
          <article class="s-block s2" data-fade><h3 data-i18n="sessions.h2"></h3><p data-i18n="sessions.p2"></p></article>
          <article class="s-block s3" data-fade><h3 data-i18n="sessions.h3"></h3><p data-i18n="sessions.p3"></p></article>
        </div>
        <div class="s-honest glass" data-fade>
          <h3 data-i18n="sessions.h4"></h3>
          <p data-i18n="sessions.p4"></p>
          <p data-i18n="sessions.p5"></p>
          <p class="s-note" data-i18n="sessions.note"></p>
        </div>
        <p class="s-bring" data-fade data-i18n="sessions.bring"></p>
      </div>
    </section>

    <!-- 10. Transformation: the emotional centre. A darker, slower scene. -->
    <section class="sec change" id="change" aria-labelledby="change-title-1">
      <div class="container">
        <div class="shift" aria-hidden="true"><i></i><i></i></div>
        <h2 class="title" id="change-title-1" data-fade data-i18n="change.title"></h2>
        <article class="scene sc1"><h3 data-fade data-i18n="change.s1Title"></h3><p data-fade style="--d:.15s" data-i18n="change.s1Text"></p></article>
        <article class="scene sc2"><h3 data-fade data-i18n="change.s2Title"></h3><p data-fade style="--d:.15s" data-i18n="change.s2Text"></p></article>
        <article class="scene sc3"><h3 data-fade data-i18n="change.s3Title"></h3><p data-fade style="--d:.15s" data-i18n="change.s3Text"></p></article>
        <article class="scene sc4"><h3 data-fade data-i18n="change.s4Title"></h3><p data-fade style="--d:.15s" data-i18n="change.s4Text"></p></article>
      </div>
    </section>

{quote_block('c')}
    <!-- The butterfly appears once, here -->
    <section class="sec change2" aria-labelledby="change-title-2">
      <div class="container">
        {mm_svg}
        <h2 class="title" id="change-title-2" data-fade data-i18n="change.bTitle"></h2>
        <p class="lead" data-fade style="--d:.15s" data-i18n="change.bText"></p>
      </div>
    </section>

    <section class="sec support" aria-labelledby="change-title-3">
      <div class="container">
        <div class="ripple" aria-hidden="true"><i></i><i></i><i></i></div>
        <div class="support-body">
          <h2 class="title" id="change-title-3" data-fade data-i18n="change.mTitle"></h2>
          <p class="lead" data-fade style="--d:.15s" data-i18n="change.mText"></p>
        </div>
      </div>
    </section>

    <section class="sec witness" aria-labelledby="change-title-4">
      <div class="container">
        <div class="witness-body">
          <h2 class="title" id="change-title-4" data-fade data-i18n="change.wTitle"></h2>
          <p class="lead" data-fade style="--d:.15s" data-i18n="change.wText"></p>
          <p class="witness-note" data-fade data-i18n="change.wNote"></p>
        </div>
        {hold_svg}
      </div>
    </section>

    <!-- 11. A quiet invitation -->
    <section class="sec invite" id="invite" aria-labelledby="invite-title">
      <div class="container">
        <h2 class="title" id="invite-title" data-fade data-i18n="invite.title"></h2>
        <a class="button button-outline" href="#contact" data-i18n="invite.button"></a>
      </div>
    </section>

    <section class="sec free" aria-labelledby="free-title">
      <div class="container">
        <div class="coin" aria-hidden="true"><b data-i18n="free.number"></b><span data-i18n="free.unit"></span></div>
        <div>
          <h2 class="title" id="free-title" data-fade data-i18n="free.title"></h2>
          <p class="lead" data-fade style="--d:.15s" data-i18n="free.text"></p>
        </div>
      </div>
    </section>

    <!-- 12. Contacts and the form -->
    <section class="sec contact" id="contact" aria-labelledby="contact-title">
      <div class="container">
        <div class="contact-card glass">
          <div>
            <h2 id="contact-title" data-i18n="contact.title"></h2>
            <p class="lead" data-i18n="contact.lead"></p>
            <div class="contact-links">
              <h3 data-i18n="contact.linksTitle"></h3>
              <a id="contact-email" href="" hidden><span data-i18n="contactEmail"></span></a>
              <a id="contact-telegram" href="" target="_blank" rel="noopener noreferrer" hidden><span>Telegram</span></a>
              <a id="contact-whatsapp" href="" target="_blank" rel="noopener noreferrer" hidden><span>WhatsApp</span></a>
              <a id="contact-booking" href="" target="_blank" rel="noopener noreferrer" hidden><span data-i18n="contactBooking"></span></a>
            </div>
          </div>
          <div>
            <form id="contact-form" novalidate>
              <label class="field"><span data-i18n="contact.formName"></span><input type="text" name="name" autocomplete="name" required aria-required="true" aria-describedby="form-status" maxlength="120"></label>
              <label class="field"><span data-i18n="contact.formReach"></span><input type="text" name="contact" autocomplete="email" required aria-required="true" aria-describedby="form-status" maxlength="160"></label>
              <label class="field"><span data-i18n="contact.formMessage"></span><textarea name="message" rows="4" maxlength="4000"></textarea></label>
              <input class="hp" type="text" name="_gotcha" tabindex="-1" autocomplete="off" aria-hidden="true">
              <button class="button button-primary" type="submit" id="form-send" data-i18n="contact.formSend"></button>
              <p class="form-status" id="form-status" role="status" aria-live="polite"></p>
              <p class="form-note" data-i18n="contact.formNote"></p>
            </form>
            <p class="form-sent" id="form-sent" role="status" tabindex="-1" hidden data-i18n="contact.formSent"></p>
          </div>
        </div>
      </div>
    </section>

    <!-- 13. Questions and answers (blank question = hidden slot) -->
    <section class="sec faq" id="faq" aria-labelledby="faq-title">
      <div class="container">
        <h2 class="title" id="faq-title" data-i18n="faq.title"></h2>
        <p class="lead" data-i18n="faq.lead"></p>
        <div class="faq-list">
{faq}        </div>
      </div>
    </section>

    <!--@@NOTES@@-->

    <!-- 14. The closing phrase -->
{quote_block('d')}  </main>'''


FOOTER_HTML = ('<footer class="site-footer"><div class="container footer-inner"><p>© <span id="year">2026</span> '
               '<span data-i18n="footerName"></span> · <span data-i18n="footer.line"></span></p>'
               '<a href="#top" data-i18n="backToTop"></a></div>'
               '<div class="container"><p class="footer-privacy" data-i18n="footer.privacy"></p></div></footer>')

FAREWELL_HTML = '''<div class="farewell" id="farewell" role="dialog" aria-modal="true" aria-labelledby="farewell-title" tabindex="-1" hidden>
    <div class="farewell-card glass">
      <h2 id="farewell-title" data-i18n="fork.farewellTitle"></h2>
      <p class="farewell-ask" data-i18n="fork.farewellText"></p>
      <p class="farewell-done" data-i18n="fork.farewellDone" hidden></p>
      <div class="farewell-actions">
        <button class="button button-outline" type="button" id="farewell-end" data-i18n="fork.farewellEnd"></button>
        <button class="button button-outline" type="button" id="farewell-back" data-i18n="fork.farewellBack"></button>
      </div>
    </div>
  </div>'''

# ----------------------------------------------------------------------------------------------
# 4. СТИЛИ. Дописываются в конец <style>, поэтому перекрывают старые правила. Мягкие формы,
#    никаких border-radius:0. Палитра прежняя (синий из презентации) + графитовая сцена «Трансформации».
# ----------------------------------------------------------------------------------------------
CSS_BEGIN = '    /* intuition-update:begin */'
CSS_END = '    /* intuition-update:end */'
CSS = r'''
    /* ---------- Intuition update: opening, composition ---------- */
    .hero-photo::after { content:""; position:absolute; inset:0; z-index:1; pointer-events:none; background:linear-gradient(180deg,rgba(12,28,48,.60),rgba(12,28,48,.16) 44%,rgba(12,28,48,0) 68%); }
    .hero-photo > img { object-position:50% 58%; }
    .hero-quote { position:absolute; z-index:2; inset:clamp(22px,4.6vw,60px) clamp(64px,11vw,170px) auto clamp(56px,8vw,112px); display:flex; justify-content:space-between; align-items:flex-start; gap:clamp(20px,4vw,56px); color:#fff; text-shadow:0 2px 26px rgba(8,20,40,.5); pointer-events:none; }
    .hero-q1 { flex:0 1 54%; font:500 clamp(2rem,4.7vw,4.5rem)/1.06 var(--serif); letter-spacing:-.03em; animation:riseIn 1.8s var(--ease) .9s both; }
    .hero-q2 { flex:0 1 25%; margin-top:.5em; text-align:right; font:italic 400 clamp(1rem,1.7vw,1.4rem)/1.5 var(--serif); opacity:.94; animation:riseIn 1.8s var(--ease) 1.6s both; }
    .hero-photo { overflow:hidden; }
    .eyes img { object-position:84% 36%; }

    /* ---------- The two choices are equal in size, weight and colour ---------- */
    .paths { grid-template-columns:repeat(2,minmax(0,1fr)); align-items:stretch; }
    .path-yes, .path-no { background:var(--glass-bright); margin-top:0; border-radius:38px; }
    .path-no:hover, .path-yes:hover { background:linear-gradient(135deg,var(--glass-bright),var(--soft-green)); }
    .path em { align-self:end; }

    /* ---------- Atmospheric quotation with an optional photograph ---------- */
    .quote-bg { position:absolute; inset:0; z-index:-2; border-radius:inherit; box-shadow:none; background:none; }
    .quote-card:has(.quote-bg.has-photo) { color:#fff; }
    .quote-card:has(.quote-bg.has-photo)::before { content:""; position:absolute; inset:0; z-index:-1; background:linear-gradient(180deg,rgba(12,28,48,.32),rgba(12,28,48,.58)); }
    .quote-card:has(.quote-bg.has-photo) i { display:none; }
    .quote-card:has(.quote-bg.has-photo) .quote-text { color:#fff; text-shadow:0 2px 24px rgba(8,20,40,.5); }
    .quote-card:has(.quote-bg.has-photo) .quote-stroke path { stroke:rgba(255,255,255,.8); }

    /* ---------- Intuition in sport ---------- */
    .story .title { font-size:clamp(1.85rem,3.9vw,3rem); max-width:19em; }
    .story-body { max-width:700px; }
    .story-pull { margin:clamp(34px,6vw,76px) 0; font:500 clamp(2rem,4.6vw,3.7rem)/1.12 var(--hand); color:var(--blue-deep); max-width:14em; }

    /* ---------- What we can explore: fragments at uneven offsets ---------- */
    .client-head { max-width:720px; }
    .threads { list-style:none; margin:clamp(44px,7vw,96px) 0 0; padding:0; display:grid; gap:clamp(30px,5vw,66px); }
    .thread { position:relative; max-width:min(540px,100%); padding-left:26px; }
    .thread::before { content:""; position:absolute; left:0; top:.7em; width:10px; height:10px; border-radius:50%; background:var(--mint); box-shadow:0 0 0 6px var(--soft-green); }
    .thread strong { display:block; font:500 clamp(1.4rem,2.5vw,2.1rem)/1.2 var(--serif); letter-spacing:-.015em; }
    .thread span { display:block; margin-top:8px; max-width:44ch; color:var(--text-muted); font-size:clamp(.98rem,1.3vw,1.08rem); line-height:1.75; }
    .thread:nth-child(2) { margin-left:clamp(0px,18vw,260px); }
    .thread:nth-child(3) { margin-left:clamp(0px,6vw,80px); }
    .thread:nth-child(4) { margin-left:clamp(0px,30vw,430px); }
    .thread:nth-child(5) { margin-left:clamp(0px,12vw,170px); }
    .thread:nth-child(6) { margin-left:clamp(0px,24vw,340px); }
    .thread:nth-child(7) { max-width:30em; margin:clamp(20px,4vw,60px) auto 0; padding-left:0; text-align:center; }
    .thread:nth-child(7)::before { display:none; }
    .thread:nth-child(7) strong { font:500 clamp(2rem,4.6vw,3.6rem)/1.12 var(--hand); color:var(--blue-deep); }
    .thread:nth-child(7) span { margin-inline:auto; }
    .client-note { margin-top:clamp(56px,8vw,110px); font-size:clamp(1.4rem,2.6vw,2rem); }

    /* ---------- My story ---------- */
    .c1 img { object-position:50% 30%; }
    .c2 img { object-position:75% 52%; transform:scale(1.5); transform-origin:75% 52%; }
    .c3 img { object-position:60% 40%; }
    .c4 { grid-template-columns:minmax(0,1.05fr) minmax(0,.95fr); align-items:end; justify-items:stretch; }
    .c4 .photo { order:2; width:min(100%,440px); aspect-ratio:4/5; justify-self:end; border-radius:var(--r-cloud); }
    .c4 .chap-text { width:auto; margin:0; padding:clamp(24px,4vw,44px); border-radius:44px; justify-self:start; }
    .c4 img { object-position:50% 26%; }
    .about-note { margin:clamp(70px,10vw,140px) auto 0; max-width:19em; text-align:center; font:500 clamp(1.7rem,3.2vw,2.5rem)/1.3 var(--hand); color:var(--blue-deep); }

    /* ---------- Intuition sessions ---------- */
    .sessions-head { max-width:860px; }
    .sessions-lead { max-width:24em; font:400 clamp(1.5rem,3vw,2.4rem)/1.35 var(--serif); letter-spacing:-.01em; }
    .s-flow { display:grid; gap:clamp(56px,9vw,130px); margin-top:clamp(56px,9vw,120px); }
    .s-block { max-width:540px; }
    .s-block h3 { font:500 clamp(1.4rem,2.4vw,1.9rem)/1.25 var(--serif); margin-bottom:12px; }
    .s-block h3::before { content:""; display:block; width:34px; height:34px; margin-bottom:16px; border-radius:var(--r-leaf); background:linear-gradient(135deg,var(--soft-blue),var(--soft-green)); }
    .s-block p { color:var(--text-muted); line-height:1.9; font-size:clamp(1.02rem,1.4vw,1.14rem); }
    .s1 { margin-left:clamp(0px,8vw,120px); }
    .s2 { margin-left:auto; margin-right:clamp(0px,6vw,90px); }
    .s3 { margin-left:clamp(0px,22vw,320px); }
    .s-honest { display:grid; gap:16px; max-width:780px; margin:clamp(70px,11vw,150px) auto 0; padding:clamp(28px,5vw,56px); border-radius:56px 28px 56px 28px; }
    .s-honest h3 { font:500 clamp(1.5rem,2.6vw,2rem)/1.25 var(--serif); }
    .s-honest p { color:var(--text-muted); line-height:1.85; }
    .s-honest .s-note { font-size:.92rem; color:var(--text); }
    .s-bring { max-width:24em; margin:clamp(60px,9vw,120px) auto 0; text-align:center; font:italic 400 clamp(1.3rem,2.5vw,1.9rem)/1.5 var(--serif); color:var(--blue-deep); }

    /* ---------- Transformation: a darker, slower scene ---------- */
    .change { width:min(1240px,calc(100% - 24px)); margin:clamp(30px,6vw,90px) auto; isolation:isolate; overflow:hidden; color:#eef4fc; background:linear-gradient(165deg,#131f33,#1b2f4a 52%,#1f3a4c); border-radius:clamp(56px,10vw,150px) clamp(40px,6vw,90px); box-shadow:var(--shadow-strong); }
    .change .container { position:relative; display:block; }
    .change .title { color:#fff; max-width:12em; }
    .change .shift { position:absolute; right:-4%; top:2%; width:min(44%,420px); opacity:.55; z-index:-1; }
    .scene { max-width:540px; margin-top:clamp(56px,9vw,130px); }
    .scene h3 { margin-bottom:16px; font:500 clamp(1.7rem,3.4vw,2.7rem)/1.15 var(--serif); letter-spacing:-.02em; color:#fff; }
    .scene p { color:rgba(232,241,252,.84); line-height:1.9; font-size:clamp(1.04rem,1.5vw,1.2rem); }
    .sc2 { margin-left:auto; }
    .sc3 { margin-left:clamp(0px,9vw,130px); }
    .sc4 { margin-left:auto; margin-right:clamp(0px,5vw,70px); }
    .support .container { display:block; position:relative; }
    .support .ripple { right:-6%; top:-20%; --s:clamp(240px,40vw,480px); }
    .support-body { max-width:600px; margin-left:clamp(0px,14vw,200px); }
    .witness .container { display:grid; grid-template-columns:minmax(0,1.1fr) minmax(0,.9fr); gap:clamp(28px,6vw,96px); align-items:center; }
    .witness-body { max-width:600px; }
    .witness-note { margin-top:clamp(28px,4vw,44px); font:500 clamp(1.5rem,2.6vw,2rem)/1.35 var(--hand); color:var(--blue-deep); }

    /* ---------- Invitation: quiet, not a funnel ---------- */
    .invite .title { max-width:16em; margin-inline:auto; }
    .button-primary { background:linear-gradient(110deg,#5878ad,#6a97a6 58%,#78a896); box-shadow:0 14px 34px -22px rgba(40,90,130,.6); }
    .footer-privacy { margin-top:14px; max-width:64ch; font-size:.8rem; line-height:1.6; color:var(--text-muted); }

    .field input[aria-invalid="true"] { border-color:#b64c56; box-shadow:0 0 0 3px rgba(182,76,86,.18); }

    /* ---------- Calm farewell ---------- */
    .farewell-card p { margin-bottom:28px; }
    .farewell-actions { display:flex; flex-wrap:wrap; justify-content:center; gap:12px; }

    @media (max-width:900px) {
      .c4 { grid-template-columns:1fr; }
      .c4 .photo { order:0; width:min(82%,380px); aspect-ratio:4/5; justify-self:end; }
      .c4 .chap-text { width:92%; margin-top:-44px; justify-self:start; }
      .witness .container { grid-template-columns:1fr; }
      .support-body { margin-left:0; }
      .change .shift { opacity:.35; }
    }
    @media (max-width:700px) {
      .hero-photo::after { display:none; }
      .hero-quote { position:static; display:grid; gap:14px; padding:clamp(20px,6vw,32px) 10px 0; color:var(--text); text-shadow:none; }
      .hero-tag { position:static; width:max-content; max-width:100%; margin:18px 10px 0; transform:none; }
      .hero-q1 { font-size:clamp(2rem,9vw,2.7rem); }
      .hero-q2 { margin:0; text-align:left; font-size:1.1rem; color:var(--text-muted); }
      .paths { grid-template-columns:1fr; }
      .change { padding-inline:clamp(8px,4vw,24px); }
      .thread:nth-child(n+2):nth-child(-n+6) { margin-left:clamp(0px,7vw,28px); }
      .s1, .s2, .s3 { margin-inline:0; }
      .sc2, .sc3, .sc4 { margin-inline:0; }
      .change { border-radius:48px 36px; }
    }
    /* intuition-update:end */'''

# ----------------------------------------------------------------------------------------------
# 5. СКРИПТ. «Сейчас нет» больше НЕ пытается закрыть вкладку: открывается тихое окно с двумя
#    честными вариантами. Выбор нигде не сохраняется и никуда не отправляется.
# ----------------------------------------------------------------------------------------------
JS_FORK = r'''/* ---------- The fork: "not now" opens a calm message. Nothing is recorded; the tab is never force-closed ---------- */
    const farewell = $('#farewell');
    const frozen = ['header', 'main', 'footer', '#to-top'].map(selector => $(selector));
    const farewellAsk = $('.farewell-ask');
    const farewellDone = $('.farewell-done');
    const farewellEnd = $('#farewell-end');
    let farewellEntry = false;                           // true while the message owns a history entry
    let ignoreNextPop = false;
    function showFarewell(open) {
      farewell.hidden = !open;
      root.classList.toggle('farewell-open', open);
      frozen.forEach(node => { if (node) node.inert = open; });
      if (open) farewell.focus(); else $('#close-page').focus({ preventScroll: true });
    }
    function openFarewell() {
      if (!farewell.hidden) return;
      farewellAsk.hidden = false; farewellDone.hidden = true; farewellEnd.hidden = false;
      try { history.pushState({ farewell: true }, ''); farewellEntry = true; } catch (_) { farewellEntry = false; }
      showFarewell(true);
    }
    function closeFarewell() {
      if (farewell.hidden) return;
      showFarewell(false);
      if (farewellEntry) { farewellEntry = false; ignoreNextPop = true; history.back(); }
    }
    addEventListener('popstate', () => {                 // the system Back button closes the message, not the site
      if (ignoreNextPop) { ignoreNextPop = false; return; }
      if (!farewell.hidden) { farewellEntry = false; showFarewell(false); }
    });
    $('#close-page').addEventListener('click', openFarewell);
    farewellEnd.addEventListener('click', () => {        // an honest goodbye: a page cannot reliably close the tab itself
      farewellAsk.hidden = true; farewellDone.hidden = false; farewellEnd.hidden = true;
      $('#farewell-back').focus();
    });
    $('#farewell-back').addEventListener('click', closeFarewell);
    addEventListener('keydown', event => { if (event.key === 'Escape') closeFarewell(); });

    '''

JS_FORM_OLD = '''      if (!name || !contact) {
        say('formRequired', true);
        form.elements.namedItem(name ? 'contact' : 'name').focus();
        return;
      }'''
JS_FORM_NEW = '''      form.elements.namedItem('name').removeAttribute('aria-invalid');
      form.elements.namedItem('contact').removeAttribute('aria-invalid');
      if (!name || !contact) {
        say('formRequired', true);
        const missing = form.elements.namedItem(name ? 'contact' : 'name');
        missing.setAttribute('aria-invalid', 'true');   // announced by screen readers, styled below
        missing.focus();
        return;
      }'''

# ----------------------------------------------------------------------------------------------
# 6. ТЕСТЫ, КОТОРЫЕ ДОБАВЛЯЮТСЯ В scripts/test_build.py
# ----------------------------------------------------------------------------------------------
TEST_FUNC = r'''def check_integrity(builder):
    """Guards added with the Intuition update: honesty of copy, calm exit, editable FAQ, accessible form."""
    template = (ROOT / 'templates/index.html').read_text(encoding='utf-8')
    assert 'window.close' not in template, 'a web page must not pretend it can close the tab'
    assert builder.FAQ_SLOTS == 8 and template.count('<details data-faq=') == 8, 'FAQ must have 8 editable slots'
    assert 'quote_photo' in builder.PHOTO_FIELDS and 'id="sessions"' in template
    assert 'id="farewell-end"' in template and 'aria-describedby="form-status"' in template
    assert template.count('<h1') == 1, 'exactly one h1 (the opening quotation)'
    banned = {
        'en': [r'risk of (?:physical )?injur', r'\bprevent', r'burn-?out', r'guarantee', r'\bcures?\b', r'\btreat(?:s|ment)?\b'],
        'ru': [r'снижени[ея] риск', r'предотвращ', r'выгоран', r'гарантир', r'излеч', r'лечени'],
        'fr': [r'risque de blessure', r'prévenir', r'burn-?out', r'garanti', r'guérir', r'traitement'],
    }
    for lang, patterns in banned.items():
        text = json.dumps(json.loads((ROOT / f'content/home_{lang}.json').read_text(encoding='utf-8')), ensure_ascii=False).lower()
        for pattern in patterns:
            assert not re.search(pattern, text), f'{lang}: promise-like wording must not return: {pattern}'
    for lang in LANGS:
        data = json.loads((ROOT / f'content/home_{lang}.json').read_text(encoding='utf-8'))
        assert data['faq']['q1'].strip() and data['fork']['farewellEnd'].strip() and data['fork']['farewellBack'].strip()


'''

# ----------------------------------------------------------------------------------------------
# 7. ФОТОГРАФИИ из презентации
# ----------------------------------------------------------------------------------------------
# поле site.json -> (файл в ppt/media, имя в media/)
PHOTO_MAP = {
    'portrait':      ('image7.png',  'hero-sea'),         # широкий кадр, руки раскинуты: главный экран
    'eyes_photo':    ('image5.png',  'eyes-closeup'),     # крупный план: «посмотрите на фотографию»
    'story_photo_1': ('image8.png',  'story-1-sport'),
    'story_photo_2': ('image10.png', 'story-2-enough'),
    'story_photo_3': ('image9.png',  'story-3-exploring'),
    'story_photo_4': ('image6.png',  'story-4-trust'),
}


def extract_photos(root: Path, pptx: Path, site: dict, dry: bool, log) -> dict:
    """Кладёт фото в media/ и возвращает {поле: 'media/файл'} только для пустых полей site.json."""
    if not pptx or not pptx.exists():
        log(f'  ! презентация не найдена ({pptx}) — фото пропущены; в сайте останутся мягкие заготовки')
        return {}
    try:
        from PIL import Image
    except ImportError:
        Image = None
        log('  ! Pillow не установлен: фото будут скопированы как PNG (тяжёлые). Лучше: pip install pillow')
    result = {}
    with zipfile.ZipFile(pptx) as z:
        names = set(z.namelist())
        for field, (src, stem) in PHOTO_MAP.items():
            if site.get(field):
                log(f'  = {field}: уже задано ({site[field]}), не трогаю')
                continue
            member = f'ppt/media/{src}'
            if member not in names:
                log(f'  ! {field}: в презентации нет {member}')
                continue
            target_dir = root / 'media'
            if Image is not None:
                out = target_dir / f'{stem}.webp'
                rel = f'media/{stem}.webp'
            else:
                out = target_dir / f'{stem}.png'
                rel = f'media/{stem}.png'
            log(f'  + {field}: {src} -> {rel}')
            if not dry:
                target_dir.mkdir(exist_ok=True)
                with z.open(member) as fh:
                    if Image is not None:
                        im = Image.open(fh).convert('RGB')
                        im.thumbnail((1800, 1800))
                        im.save(out, 'WEBP', quality=82, method=6)
                    else:
                        out.write_bytes(fh.read())
            result[field] = rel
    return result


# ----------------------------------------------------------------------------------------------
# 8. ПАТЧИ
# ----------------------------------------------------------------------------------------------
class PatchError(RuntimeError):
    pass


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise PatchError(f'не найден фрагмент «{label}» — файл отличается от ожидаемого')
    return text.replace(old, new, 1)


def build_content(root: Path, lang: str) -> dict:
    """Новый JSON одного языка; PRESERVE-поля берутся из уже существующего файла."""
    path = root / 'content' / f'home_{lang}.json'
    old = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    out = {}
    for group, _, fields in SCHEMA:
        out[group] = {}
        for key, _, _ in fields:
            dotted = f'{group}.{key}'
            previous = old.get(group, {}).get(key) if isinstance(old.get(group), dict) else None
            use_old = dotted in PRESERVE and isinstance(previous, str) and previous.strip()
            out[group][key] = previous if use_old else COPY[lang][group][key]
    return out


def pages_fields() -> list:
    result = []
    for group, label, fields in SCHEMA:
        sub = []
        for key, flabel, ftype in fields:
            item = {'name': key, 'label': flabel, 'type': ftype}
            if group == 'faq' and key.startswith('q') and key[1:].isdigit():
                item['description'] = 'Оставьте пустым, чтобы скрыть этот вопрос.'
            sub.append(item)
        result.append({'name': group, 'label': label, 'type': 'object', 'fields': sub})
    return result


def patch_pages_yml(text: str) -> str:
    data = yaml.safe_load(text)
    entries = {e['name']: e for e in data['content']}
    for lang in LANGS:
        entries[f'home_{lang}']['fields'] = pages_fields()
    site = entries['site']
    names = [f['name'] for f in site['fields']]
    if 'quote_photo' not in names:
        at = names.index('eyes_photo') + 1 if 'eyes_photo' in names else len(names)
        site['fields'].insert(at, {'name': 'quote_photo', 'label': 'Атмосферное фото за цитатой А (необязательно; если пусто — мягкий цвет)', 'type': 'image'})
    labels = {
        'portrait': 'Главное фото (широкий кадр, на нём лежит первая цитата)',
        'eyes_photo': 'Фото крупным планом («посмотрите на фотографию»)',
        'story_photo_1': 'История · кадр 1 (спорт с детства и FIFA)',
        'story_photo_2': 'История · кадр 2 («хватит» — смена пути)',
        'story_photo_3': 'История · кадр 3 (поиск)',
        'story_photo_4': 'История · кадр 4 (доверие к себе)',
    }
    for f in site['fields']:
        if f['name'] in labels:
            f['label'] = labels[f['name']]
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False, width=1000)


def patch_template(text: str) -> str:
    # 1. разметка <main>; SVG берём из текущего файла
    mm = re.search(r'<svg class="mm".*?</svg>', text, re.S)
    hold = re.search(r'<svg class="hold support-art".*?</svg>', text, re.S)
    if not mm or not hold:
        raise PatchError('в шаблоне не найдены SVG бабочки или «руки» (class="mm" / class="hold support-art")')
    main_html = build_main(mm.group(0), hold.group(0))
    text, n = re.subn(r'<main id="main" tabindex="-1">.*?</main>', lambda m: main_html, text, count=1, flags=re.S)
    if n != 1:
        raise PatchError('не найден блок <main id="main">')
    # 2. подвал и окно «спасибо, что заглянули»
    text, n = re.subn(r'<footer class="site-footer">.*?</footer>', lambda m: FOOTER_HTML, text, count=1, flags=re.S)
    if n != 1:
        raise PatchError('не найден <footer class="site-footer">')
    text, n = re.subn(r'<div class="farewell" id="farewell".*?\n  </div>(?=\s*<script>)', lambda m: FAREWELL_HTML, text, count=1, flags=re.S)
    if n != 1:
        raise PatchError('не найдено окно farewell')
    # 3. стили: блок между маркерами заменяется, при первом запуске дописывается перед </style>
    block = CSS_BEGIN + CSS
    if CSS_BEGIN in text:
        text = re.sub(re.escape(CSS_BEGIN) + r'.*?' + re.escape(CSS_END), lambda m: block, text, count=1, flags=re.S)
    else:
        text = replace_once(text, '\n  </style>', block + '\n  </style>', '</style>')
    # 4. скрипт: блок «развилка» целиком, и доступная ошибка формы
    text, n = re.subn(r'/\* -{10} The fork: "not (?:yet|now)".*?(?=/\* -{10} Contact links:)', lambda m: JS_FORK, text, count=1, flags=re.S)
    if n != 1:
        raise PatchError('не найден блок скрипта «The fork»')
    if "setAttribute('aria-invalid'" not in text:
        text = replace_once(text, JS_FORM_OLD, JS_FORM_NEW, 'проверка полей формы')
    return text


def patch_build(text: str) -> str:
    text = re.sub(r"PHOTO_FIELDS = \([^)]*\)", "PHOTO_FIELDS = ('portrait', 'eyes_photo', 'quote_photo', 'story_photo_1', 'story_photo_2', 'story_photo_3', 'story_photo_4')", text, count=1)
    if 'quote_photo' not in text:
        raise PatchError('не удалось обновить PHOTO_FIELDS в scripts/build.py')
    text = re.sub(r'FAQ_SLOTS = \d+', 'FAQ_SLOTS = 8', text, count=1)
    return text


def patch_tests(text: str) -> str:
    if 'def check_integrity' not in text:
        text = replace_once(text, 'def write_post(', TEST_FUNC + 'def write_post(', 'write_post')
        text = replace_once(text, '    check_consistency(builder)\n', '    check_consistency(builder)\n    check_integrity(builder)\n', 'вызов check_consistency')
    if "'sessions'" not in text:
        text = replace_once(text, "'fork', 'change'", "'fork', 'sessions', 'change'", 'SECTION_IDS')
    # the fixture must not depend on which real photos the author has already filled in
    text = text.replace("'story_photo_2': 'media/test-cover.webp', 'form_endpoint'",
                        "'story_photo_2': 'media/test-cover.webp', 'eyes_photo': '', 'quote_photo': '', 'story_photo_1': '', 'story_photo_3': '', 'story_photo_4': '', 'form_endpoint'")
    text = text.replace("assert 'Этот сайт устроен иначе' in home and 'Ты можешь контролировать только себя' in home",
                        "assert 'Интуиция нужна каждому' in home and 'Ты можешь контролировать только себя' in home")
    return text


def patch_docs(root: Path, dry: bool, log) -> list:
    changed = []
    readme = root / 'README.md'
    if readme.exists():
        t = readme.read_text(encoding='utf-8')
        t = t.replace('Шесть слотов. Чтобы убрать вопрос, **очистите поле вопроса**: слот исчезнет с сайта. Чтобы добавить, заполните пустой слот. Нужно больше шести? Скажите, добавим слоты.',
                      'Восемь слотов (7 и 8 пока пустые и скрыты: туда можно добавить вопросы про стоимость, формат, конфиденциальность). Чтобы убрать вопрос, **очистите поле вопроса**: слот исчезнет с сайта. Чтобы добавить, заполните пустой слот.')
        t = t.replace('Цитаты **B** и **C** — черновики по смыслу вашего рассказа, замените их своими словами.',
                      'Цитаты **Б** и **В** теперь взяты из вашей презентации; проверьте формулировки (см. `docs/CONTENT-REVIEW.md`).')
        marker = '## Обновление по презентации Intuition v1.1'
        if marker not in t:
            t = t.rstrip('\n') + '\n\n' + README_ADD
        changed.append(('README.md', t))
    concept = root / 'docs' / 'CONCEPT.md'
    if concept.exists():
        t = concept.read_text(encoding='utf-8')
        if '## 11. Обновление по презентации' not in t:
            t = t.rstrip('\n') + '\n\n' + CONCEPT_ADD
        changed.append(('docs/CONCEPT.md', t))
    changed.append(('docs/CONTENT-REVIEW.md', REVIEW_DOC))
    return changed

# ----------------------------------------------------------------------------------------------
# 9. ДОКУМЕНТЫ
# ----------------------------------------------------------------------------------------------
README_ADD = '''## Обновление по презентации Intuition v1.1

Страница переработана по презентации `Website_Intuition_v1.1.pptx` скриптом `apply_intuition_update.py`. Что появилось: центральная цитата прямо на главном фото, раздел «Интуиция в спорте» (вопрос из презентации), «Что мы можем исследовать вместе» (семь тем в виде тихих фрагментов), «Моя история» из четырёх кадров с подписью «этот путь продолжается», момент интуиции с двумя равноправными вариантами, **«Интуитивные сессии»**, расширенная **«Трансформация»** (тёмная сцена, бабочка один раз, «свидетель»), спокойное приглашение, FAQ на 8 слотов, строка о приватности в подвале.

- Все тексты по-прежнему в **Pages CMS** (`Тексты сайта · …`), поля идут в порядке страницы.
- Кнопка «Сейчас я не чувствую связи» **не закрывает вкладку** (браузеры этого не позволяют). Она показывает спокойное окно: «завершить визит» или «продолжить знакомство». Выбор нигде не сохраняется и не отправляется.
- Необязательное фото за цитатой А: поле **«Атмосферное фото за цитатой А»** в «Контакты, фото, имя». Пока пусто — мягкий цвет.
- Что ещё нужно подтвердить или заполнить (стоимость, формат, конфиденциальность, юридические данные, фото без водяных знаков) — в [`docs/CONTENT-REVIEW.md`](docs/CONTENT-REVIEW.md).
- Форму связи по-прежнему нужно подключить (раздел 3 выше). Пока адрес формы пуст, сайт честно пишет, что форма не подключена, и не делает вид, что отправил сообщение.
'''

CONCEPT_ADD = '''## 11. Обновление по презентации v1.1

Порядок страницы теперь: главный экран (фото + центральная цитата) → цитата А → интуиция в спорте → что мы можем исследовать → почему я работаю со спортсменами → цитата Б → моя история (4 кадра) → момент интуиции → выбор из двух вариантов → интуитивные сессии → трансформация (тёмная сцена из четырёх фрагментов) → цитата В → бабочка → «когда не понимают» → «свидетель» → приглашение → первые 30 минут → контакты и форма → вопросы и ответы → финальная цитата.

Принципы, которые уточнились:

- **Выход без обмана.** Страница не обещает закрыть вкладку. «Сейчас нет» — это спокойное окно с двумя вариантами; выбор не сохраняется.
- **Без обещаний результата.** Из презентации убраны формулировки про «снижение риска травм и болезней» и «предотвращение выгорания»; вместо них описано внимание к телу и внутреннему голосу. Для автоматической защиты в `scripts/test_build.py` есть проверка запрещённых формулировок на трёх языках.
- **Методика не прячется.** Прямо сказано: заранее заданной программы нет, подход не основан на научных исследованиях, это не психологическое консультирование и не замена медицинской помощи.
- **Палитра.** Синяя гамма презентации сохранена (она совпадает с цветом моря и неба на фотографиях). Добавлена одна графитово-синяя сцена для «Трансформации».
- **Ответов нет — значит, и нет вопросов.** FAQ содержит только то, что есть в презентации. Вопросы о стоимости, формате и конфиденциальности скрыты, пока автор не даст ответы.
'''

REVIEW_DOC = '''# Что проверить автору перед публикацией

Этот файл создан скриптом `apply_intuition_update.py`. Отметьте, что принимаете, а что правите.

## 1. Где что взято из презентации

| Слайд | Раздел сайта | Заметки |
|---|---|---|
| 1 | Главный экран: центральная цитата на фото | Обе строки слайда |
| 2 | «Интуиция в спорте» | Вопрос из слайда — заголовок; текст разбит на короткие фрагменты, смысл сохранён |
| 3 | «Что мы можем исследовать вместе» | Семь тем слайда, **два места смягчены** (см. п. 2) |
| 4 и 5 | «Интуитивные сессии» + FAQ | Фраза «нет предопределённой программы» и «не основано на научных исследованиях» сохранены |
| 6 | «Трансформация» | Четыре сцены, переход «назад к себе», «когда не понимают», «свидетель» |
| 7 | «Почему я работаю со спортсменами», «Моя история», «Момент интуиции» | Хронология сохранена; ничего не добавлено |
| 8, 9 | Фотографии | Главное фото, кадры истории, крупный план |
| 10 | FAQ | В презентации только заголовок «Q&A», ответов нет |

## 2. Содержательные изменения — подтвердите

1. **Слайд 3, «снижение риска физических травм и болезней»** — убрано. Вместо этого: «выстраивать с телом более глубокие отношения и учиться замечать, что оно подсказывает». Утверждение о защите от травм и болезней нужно основание, поэтому в публичный текст оно не вошло.
2. **Слайд 3, «предотвращение эмоционального истощения и выгорания»** — убрано по той же причине. Осталось: «отличать внутренний голос от страхов, ментальной болтовни и чужих ожиданий».
3. **Слайд 3, «принимать советы врачей… только после сверки с собой»** — смягчено до «слушать советы… и сверять их ещё и с собой», чтобы это не читалось как призыв не доверять врачам.
4. **Добавлена оговорка** «Сессии не заменяют медицинскую помощь или психологическую терапию» (в «Сессиях» и в FAQ). В презентации её нет; это моё предложение.
5. **Цитата Б** («Не всё в жизни можно понять логикой — и не всё нужно понимать») — ваши слова из слайда 4. **Цитата В** («Трансформация часто ведёт не к чему-то новому, а обратно к себе») — ваши слова из слайда 6. Прежние черновые цитаты Б и В не были вашими словами и убраны.
6. **Предложение про привычное** в «Трансформации» («Мы тянемся к привычному: оно кажется безопасным…») взято из прежней версии сайта, а не из презентации. Оставлено, потому что тема «сопротивление и возврат к безопасному» есть в вашем ТЗ; подтвердите, что формулировка ваша.
7. **Тихая строка** «Если что-то из этого вам знакомо, можно читать дальше» заменила «возможно, вы здесь не случайно» (это давило на читателя).
8. **Первые 30 минут бесплатны** — формулировка из вашего ТЗ, а не из слайдов. Подтвердите условие.
9. **Строка о приватности** в подвале — это обещание от вашего имени («ваше имя и сообщение используются только для ответа вам»). Подтвердите.
10. Заголовки блоков в «Сессиях» («У каждого она говорит по-своему», «С чего мы начинаем», «Не только ответы», «Как проходят сессии») и в «Трансформации» — редакторские подписи, придуманные для навигации.
11. Исправлены опечатки презентации (Dieveloping, lead → led и т. п.) и «Few years ago» → «A few years ago».
12. Перевод на русский и французский сделан с английского; фразы про «beautiful self» переданы как «своё прекрасное “я”» и «votre beauté intérieure». Проверьте тон.

## 3. FAQ

Заполнено шесть вопросов, на которые есть ответ в презентации. **Нет ответов, поэтому нет и вопросов:** сколько стоит, как проходят встречи (онлайн/очно), можно ли с несовершеннолетними, конфиденциальность. Слоты 7–8 пусты — заполните в CMS, когда определитесь. Прежние заготовленные ответы на эти темы убраны: их нет в презентации.

## 4. Фотографии

- Фото из презентации в низком разрешении (около 500–1170 px). Для главного экрана это допустимо, для больших экранов лучше **оригиналы**.
- **На фотографиях видны полупрозрачные водяные знаки.** Перед включением индексации замените их на файлы без знаков и убедитесь, что у вас есть права на публикацию.
- Раскладка: главный экран — широкий кадр с раскинутыми руками; кадр 1 — розовая майка; кадр 2 — у забора; кадр 3 — в траве; кадр 4 — улыбка в белой майке; крупный план — «посмотрите на фотографию». Меняется в Pages CMS → «Контакты, фото, имя».
- Атмосферная фотография за цитатой А не выбрана: нужна ваша пейзажная.

## 5. Что нужно заполнить

- [ ] Имя и специализация (сейчас заготовки «Анна М.» / «Prénom Nom»).
- [ ] Почта / Telegram / WhatsApp и **адрес формы** (раздел 3 README). Пока адрес формы пуст, форма честно пишет, что не подключена.
- [ ] Юридические сведения и политика конфиденциальности, если они нужны вам по закону вашей страны. В подвале только короткая строка, юридических страниц нет и они не придуманы.
- [ ] Ответы для FAQ 7–8.
- [ ] Включить «Готов к индексации» (`publish_ready`) только после всего выше.

## 6. Чего намеренно нет

- Порядок и видимость разделов не настраиваются из CMS (кроме пустых вопросов FAQ и пустого фото); перестановка разделов — правка шаблона.
- Нет аналитики, трекеров, всплывающих окон на выход, срочности и отзывов.
'''


# ----------------------------------------------------------------------------------------------
# 10. ЗАПУСК
# ----------------------------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description='Переносит презентацию Intuition v1.1 в лендинг.')
    ap.add_argument('--root', default='.', help='корень репозитория (по умолчанию текущая папка)')
    ap.add_argument('--pptx', default='Website_Intuition_v1_1.pptx', help='путь к презентации (для фотографий)')
    ap.add_argument('--dry-run', action='store_true', help='ничего не менять, только показать план')
    ap.add_argument('--no-photos', action='store_true', help='не доставать фото из презентации')
    ap.add_argument('--skip-checks', action='store_true', help='не запускать build.py и test_build.py после изменений')
    ap.add_argument('--yes', action='store_true', help='не спрашивать подтверждение')
    args = ap.parse_args()

    root = Path(args.root).resolve()
    log = print
    needed = ['templates/index.html', 'scripts/build.py', 'scripts/test_build.py', '.pages.yml',
              'content/site.json', 'content/home_ru.json', 'content/home_en.json', 'content/home_fr.json']
    missing = [n for n in needed if not (root / n).exists()]
    if missing:
        log('Это не тот репозиторий или он изменён: нет файлов: ' + ', '.join(missing))
        return 2
    dry = args.dry_run
    log(f'Репозиторий: {root}' + ('   [пробный запуск: файлы не меняются]' if dry else ''))
    if not dry and not args.yes:
        log('\nБудут перезаписаны content/home_*.json (поля, которых нет в PRESERVE), templates/index.html, .pages.yml,')
        log('scripts/build.py, scripts/test_build.py, README.md, docs/CONCEPT.md. Резервная копия — в .backup-intuition/.')
        if input('Продолжить? [y/N] ').strip().lower() not in ('y', 'yes', 'д', 'да'):
            log('Отменено.')
            return 1

    # --- вычисляем новые содержимые файлов в памяти: если что-то не сходится, ничего не записано ---
    site_path = root / 'content/site.json'
    site = json.loads(site_path.read_text(encoding='utf-8'))
    new_files = {}

    log('\nФотографии:')
    photos = {} if args.no_photos else extract_photos(root, Path(args.pptx).resolve() if args.pptx else None, site, dry, log)
    site_new = dict(site)
    site_new.update(photos)
    site_new.setdefault('quote_photo', '')
    new_files['content/site.json'] = json.dumps(site_new, ensure_ascii=False, indent=2) + '\n'

    log('\nТексты:')
    for lang in LANGS:
        data = build_content(root, lang)
        new_files[f'content/home_{lang}.json'] = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
        log(f'  home_{lang}.json: {sum(len(f) for _, _, f in SCHEMA)} полей')

    try:
        new_files['.pages.yml'] = patch_pages_yml((root / '.pages.yml').read_text(encoding='utf-8'))
        new_files['templates/index.html'] = patch_template((root / 'templates/index.html').read_text(encoding='utf-8'))
        new_files['scripts/build.py'] = patch_build((root / 'scripts/build.py').read_text(encoding='utf-8'))
        new_files['scripts/test_build.py'] = patch_tests((root / 'scripts/test_build.py').read_text(encoding='utf-8'))
    except PatchError as exc:
        log(f'\nОШИБКА: {exc}\nНичего не изменено.')
        return 3
    for rel, text in patch_docs(root, dry, log):
        new_files[rel] = text

    log('\nФайлы:')
    changed = []
    for rel, text in new_files.items():
        path = root / rel
        same = path.exists() and path.read_text(encoding='utf-8') == text
        log(f'  {"=" if same else "~"} {rel}' + ('  (без изменений)' if same else ''))
        if not same:
            changed.append(rel)
    if dry:
        log('\nПробный запуск завершён. Для применения запустите без --dry-run.')
        return 0

    # --- резервная копия и запись ---
    if not changed:
        log('\nИзменений нет: сайт уже обновлён.')
        return 0
    stamp = dt.datetime.now().strftime('%Y%m%d-%H%M%S')
    backup = root / '.backup-intuition' / stamp
    for rel in changed:
        src = root / rel
        if src.exists():
            (backup / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, backup / rel)
    for rel in changed:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_files[rel], encoding='utf-8')
    gi = root / '.gitignore'
    if gi.exists() and '.backup-intuition/' not in gi.read_text(encoding='utf-8'):
        gi.write_text(gi.read_text(encoding='utf-8').rstrip('\n') + '\n.backup-intuition/\n', encoding='utf-8')
    log(f'\nЗаписано файлов: {len(changed)}. Резервная копия: {backup.relative_to(root)}')

    if args.skip_checks:
        return 0
    log('\nПроверка: сборка и тесты…')
    for script in ('scripts/build.py', 'scripts/test_build.py'):
        result = subprocess.run([sys.executable, script], cwd=root, capture_output=True, text=True)
        log(f'  $ python {script} -> код {result.returncode}')
        if result.stdout.strip():
            log('    ' + result.stdout.strip().replace('\n', '\n    '))
        if result.returncode != 0:
            log(result.stderr.strip())
            log('\nПроверка не прошла. Возвращаю файлы из резервной копии.')
            for rel in changed:
                saved = backup / rel
                if saved.exists():
                    shutil.copy2(saved, root / rel)
                else:
                    (root / rel).unlink(missing_ok=True)
            return 4
    log('\nГотово. Сайт собран в _site/. Дальше: git add -A && git commit && git push — и GitHub Actions опубликует.')
    log('Важно: publish_ready остаётся как был; сайт не попадёт в поиск, пока вы сами не включите индексацию.')
    log('Прочитайте docs/CONTENT-REVIEW.md: там то, что нужно подтвердить.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
