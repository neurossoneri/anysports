# Site concept: intuition

A living document. When the idea changes, change this file first, then the site.

> **Внимание:** визуальный язык и порядок блоков ниже описывают прежнюю, «мягкую» версию. Актуальный дизайн — в разделе 12 в конце файла.

## 1. What this site is

A one-page invitation, not a sales page. The owner left ten years at FIFA, changed careers on intuition, and works with athletes who feel that something inside has begun to change. The page is a short walk through that story. At the end the visitor either feels a pull and writes, or feels nothing and leaves. Both outcomes are good.

**The feeling we want:** something quietly draws the visitor in. Calm, air, honesty, a person looking back at them from the photograph.

## 2. Principles

1. **Not about selling.** No funnels, no urgency, no persuasion. We never try to convince anyone. We do not want pointless conversations; we want the people whom this resonates with.
2. **No method, no template, no algorithm.** The site itself breaks templates. There are no process steps, no numbered stages, no certificates, no testimonials, no credentials wall. The service is fluid; the page must not pretend otherwise.
3. **Everything is built around intuition.** Copy, structure and interaction all refer back to it. Choosing intuitively is presented as normal.
4. **Torn rhythm.** Blocks differ in height, width, alignment and tempo. A loud moment is followed by a pause. No two neighbouring blocks share a layout.
5. **More visual, less text.** Short lines, large pauses, generous white space. Emotion comes from form and motion rather than from paragraphs.
6. **Soft and transparent.** No sharp corners or hard edges anywhere. Glass, washes of colour, organic outlines, no divider lines.
7. **The visitor may leave.** "Close the page" is a first-class button and is phrased kindly.

## 3. Voice

First person, calm, warm, short sentences. Questions are asked gently and never answered for the reader. No jargon, no promises of results, no claims that cannot be kept. The owner is female; Russian and French copy use feminine forms.

## 4. Page map (top to bottom)

| # | Block | Purpose | Form |
|---|---|---|---|
| 1 | **Hero photograph** | The first and strongest moment: a person, not a headline | Large pebble-shaped photo that slowly breathes (outline morphs), small name chip, quiet "scroll slowly" hint |
| 2 | **Quote A** | Her own words: *you can only control yourself; the rest is out of your control* | Wide soft card, dawn palette, handwritten reveal |
| 3 | **About this site** | Why the site is built this way; intuition in sport and why it matters there | Narrow column, offset to the right, concentric "ripples" behind |
| 4 | **For you, if…** | Mirror for the potential client; creates the pull | Four floating glass bubbles at uneven offsets, a handwritten closing line |
| 5 | **Why athletes** | Her definition | Asymmetric: soft blob left, text right |
| 6 | **Quote B** | Intuition in sport | Mint-morning card, right-aligned, narrower |
| 7 | **My story** | Ten years at FIFA → changed career on intuition → still looking for answers → wants to help | Four frames with different photo shapes (leaf, circle, egg, cloud) and offsets |
| 8 | **Listen** | The intuition check: you saw the photos, you read the story, what do you feel? | Centered, huge air, ripples |
| 9 | **The fork** | Resonated → go deeper; not yet → close the page. "If you are here, something brought you. Look me in the eyes." | Round close-up photo, two glass paths of unequal size |
| 10 | **Change** | People who have done one thing for years begin to change inside; we resist; resistance rarely helps | Morphing blob + text |
| 11 | **Caterpillar → butterfly** | Change is not always pleasant; it transforms | Looping SVG: caterpillar, chrysalis, butterfly |
| 12 | **Quote C** | You do not have to work it out alone (leads into Support) | Lavender-apricot card, left-aligned |
| 13 | **Support** | People will not understand; find support outside | Orb held by two arcs |
| 14 | **Invitation** | "I can help you walk this path. If you wish, get in touch." | One soft button |
| 15 | **Thirty minutes** | First meeting free, no obligation; each listens to their intuition, then we see | Round glass "coin" with 30 / minutes / free |
| 16 | **Contacts and form** | Direct links and a short form delivered to her inbox | Large soft glass card |
| 17 | **Questions and answers** | Kept and editable | Soft accordion, six slots, blank question hides a slot |
| 18 | **Notes** | Only appears if an article is published | Soft cards |
| 19 | **Closing phrase** | *Intuition is a different kind of intelligence. There are things you can only learn about yourself by listening inward.* | Deep dusk card, handwritten reveal |

## 5. Visual language

- **Palette:** dawn sky `#e2ecfc`, lavender mist `#ebe4f8`, sea mint `#dcf1ea`, ink blue `#1b3452`, deep dusk `#1d3a70`. A warm apricot appears only in the change quote. Dark theme keeps the same moods at night.
- **Type:** Source Serif 4 for headings and calm reading, Inter for small interface text, **Caveat** for everything handwritten.
- **Shapes:** organic outlines (`--r-hero-*`, `--r-leaf`, `--r-egg`, `--r-cloud`); cards use large, unequal corner radii; photos are never plain rectangles. A test fails if `border-radius: 0` appears.
- **Motion language:** slow, soft, breathing. One orchestrated arrival (hero), one signature gesture (handwriting), a few loops (blob morph, ripples, butterfly). Ordinary text only fades. A pointer-following light adds the feeling of being drawn in. Everything respects `prefers-reduced-motion`.
- **Handwriting reveal:** each letter fades in from a soft blur with a small wipe, left to right, paced so a quote takes about three seconds; a hand-drawn stroke is drawn last. Screen readers get the full quote as plain text.

## 6. Interaction details

- **Fork:** "It resonated" scrolls on to the change section. "Not yet" asks the browser to close the tab; if the browser refuses (the usual case), a calm farewell appears with a way back. The rest of the page is inert while the farewell is open, and the browser Back button closes it instead of leaving the site.
- **Form:** name, how to reach you, optional message. Sent to a form service (see README) that forwards to the owner's inbox. Hidden honeypot against bots. Without a service the form falls back to the visitor's mail app. A note asks visitors not to share sensitive information.
- **Languages:** RU / EN / FR with the language switcher; Russian is baked into the static HTML.

## 7. Content model

- All copy lives in `content/home_<lang>.json`, grouped in the order of the page, and is editable in Pages CMS. Templates contain markup only.
- Photos, contacts, name and the form address live in `content/site.json`.
- Small system strings (aria labels, form messages) live in `UI` in `scripts/build.py`.
- A test keeps template keys, the three language files and `.pages.yml` in sync.

## 8. Decisions made on the owner's behalf (please review)

- Quotes **B** and **C** are drafts distilled from the owner's own phrasing. Replace them with her exact words.
- Quote **A** is translated into Russian and French. If it should stay in English everywhere, paste the English into all three files.
- The wording of the FAQ answers (price, formats, minors, confidentiality) is a calm placeholder that promises nothing specific. Confirm or replace.
- Reviews, the quiz-style finder, the credentials block and the four-step process of the previous version were removed on purpose (see principles 1 and 2).
- Articles are kept as quiet "Notes", shown only once something is published.
- The caterpillar image is used once (the animated moment). Quote C no longer repeats it, and the text no longer promises that every hard change leads somewhere good.
- The closing quote no longer claims that intuition "knows more than artificial intelligence"; it says intuition is a different kind of intelligence.
- The resistance paragraph explains why we hold on to the familiar instead of judging resistance.

## 9. Open items

- [ ] Upload the hero photograph, the four story photographs and a close-up.
- [ ] Connect a form service and paste its address into site settings.
- [ ] Fill in the French name (currently a placeholder) and confirm the role titles.
- [ ] Replace draft quotes and review the FAQ.
- [ ] Turn on "allow search indexing" when everything above is done.

## 10. Parked ideas

- Her own landscape photographs as quote backgrounds (CSS-only backgrounds are used for now).
- A short audio greeting under the hero photograph.
- More FAQ slots, if six turn out to be too few.

## 11. Обновление по презентации v1.1

Порядок страницы теперь: главный экран (фото + центральная цитата) → цитата А → интуиция в спорте → что мы можем исследовать → почему я работаю со спортсменами → цитата Б → моя история (4 кадра) → момент интуиции → выбор из двух вариантов → интуитивные сессии → трансформация (тёмная сцена из четырёх фрагментов) → цитата В → бабочка → «когда не понимают» → «свидетель» → приглашение → первые 30 минут → контакты и форма → вопросы и ответы → финальная цитата.

Принципы, которые уточнились:

- **Выход без обмана.** Страница не обещает закрыть вкладку. «Сейчас нет» — это спокойное окно с двумя вариантами; выбор не сохраняется.
- **Без обещаний результата.** Из презентации убраны формулировки про «снижение риска травм и болезней» и «предотвращение выгорания»; вместо них описано внимание к телу и внутреннему голосу. Для автоматической защиты в `scripts/test_build.py` есть проверка запрещённых формулировок на трёх языках.
- **Методика не прячется.** Прямо сказано: заранее заданной программы нет, подход не основан на научных исследованиях, это не психологическое консультирование и не замена медицинской помощи.
- **Палитра.** Синяя гамма презентации сохранена (она совпадает с цветом моря и неба на фотографиях). Добавлена одна графитово-синяя сцена для «Трансформации».
- **Ответов нет — значит, и нет вопросов.** FAQ содержит только то, что есть в презентации. Вопросы о стоимости, формате и конфиденциальности скрыты, пока автор не даст ответы.

## 12. Холодный редизайн (заменяет разделы 2.4, 2.6, 4 и 5 выше)

Дизайн переработан: первый экран тёмный и холодный, секции чередуют тёмные и светлые фоны, углы прямые, текст разбавлен фотографиями и символами.

**Принципы визуального языка**

1. Первый экран: глубокие холодные тона, крупное фото автора с одной стороны, цитата с другой. Ни имён, ни ярлыков, ни кнопок.
2. Секции отделены фоном: тёмный, светлый, тёмный, светлый и так далее. Соседние секции никогда не совпадают по тону.
3. Бренд-акценты: оттенки синего и зелёного. Цвет живёт в акцентах, а не в заливках.
4. Прямые углы везде: фото, плашки, поля формы, кнопки. Тест следит, чтобы скруглений не появилось снова.
5. На десктопе секции двухколоночные: текст с одной стороны, фото, цитата или графика с другой.
6. Никакого сплошного текста: фото, цитаты «от руки», линейные символы (семь тем, бабочка).
7. Нет принудительных призывов и выборов: нет «записаться», «выбрать время», «Момент интуиции» с двумя кнопками.

**Порядок страницы**

| # | Секция | Фон | Содержимое |
|---|---|---|---|
| 1 | Главный экран | тёмный | Фото автора + цитата |
| 2 | Введение | светлый | Почему страница для спортсменов; фото с цитатой А |
| 3 | Интуитивные сессии | тёмно-бирюзовый | Описание формата, фото, цитата Б, семь тем с символами |
| 4 | Трансформация | светлый (ледяной) | Бабочка и цитата В рядом с текстом |
| 5 | Обо мне | тёмный | Короткий текст и мозаика из четырёх фото |
| 6 | Форма | светлый | Контакты и форма, сразу после «Обо мне» |
| 7 | Вопросы и ответы | тёмно-бирюзовый | FAQ; в конце блок «первые 30 минут бесплатно» |

**Палитра:** `--abyss #06121e` (шапка, подвал), `--deep #08192a`, `--teal #0c2a3d`, `--frost #edf3f7`, `--ice #dae7f0`; акценты синий `#2f6fb3` / `#8dbdf0` и зелёный `#1f8a74` / `#6fd2b8`.

**Фото:** обрабатываются в холодной гамме. Пока файлы не обработаны фотографом, CSS слегка охлаждает их (`--photo-grade` в начале стилей). Когда все кадры будут холодными, поставьте `--photo-grade:0`.

Убрано при редизайне: бейдж с именем и ролью на первом экране, подпись «листайте не спеша», блоки «Момент интуиции» и «Выбор», окно прощания, «Приглашение» с кнопкой, ссылка на запись, подзаголовок «Или напрямую», финальная цитата (повторяла цитату первого экрана), строка «можно читать дальше». Тексты сохранены в `docs/REMOVED-COPY.md`.
