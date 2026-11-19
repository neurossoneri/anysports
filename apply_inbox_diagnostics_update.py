#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_inbox_diagnostics_update.py: заявки, когда что-то сломалось.

Запускать из корня репозитория:  python3 apply_inbox_diagnostics_update.py

Что делает:
  1. admin/inbox-script.txt: скрипт Google версии 3 (лист «Журнал», диагностика, пауза приёма,
     читаемая причина ошибки, блокировка больше не останавливает заявку с сайта).
  2. admin/index.html: вкладка «Заявки» получает блок «Управление подключением и журнал»
     (проверка, пауза, отключить, удалить и начать заново, журнал), таймаут 45 секунд.
  3. scripts/test_build.py: тесты скрипта Google и логики панели.
  4. README.md, docs/DASHBOARD.md, docs/HOSTING.md, docs/CONCEPT.md: описание на русском.

Безопасность: сначала все правки проверяются в памяти; если хоть одна не нашла своё место, ничего не пишется.
Повторный запуск ничего не меняет. Оригиналы лежат в .backup-inbox-diagnostics/.
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()
BACKUP = ROOT / '.backup-inbox-diagnostics'

NEW_INBOX_SCRIPT = r'''/**
 * Sport Intuitive: приём заявок с сайта (Google Apps Script).
 *
 * Что делает:
 *   1. Принимает сообщения из формы на сайте и записывает их в эту таблицу (лист «Заявки»).
 *   2. Присылает вам письмо о каждой новой заявке (на любую вашу почту) и, если хотите, сообщение в Telegram.
 *   3. Отдаёт список заявок панели управления /admin/ (только по вашему паролю).
 *
 * Как подключить, подробно: панель /admin/ → вкладка «Заявки».
 * Кратко: вставьте код → «Развернуть» → «Веб-приложение» → доступ «Все». Пароль панель вписывает сама.
 */

// Пароль от панели заявок. Если вы копировали код кнопкой в панели /admin/, он уже вписан сюда сам.
// Если вставляете код вручную: придумайте длинный пароль (12 символов и больше) и введите его же в панели.
var ADMIN_KEY = 'ЗАМЕНИТЕ-НА-ДЛИННЫЙ-ПАРОЛЬ';

// Куда присылать уведомления. Лучше ничего здесь не менять: адрес почты и Telegram настраиваются
// в панели /admin/ (вкладка «Заявки» → «Уведомления о новых заявках») и хранятся в настройках скрипта.
// Пусто = на почту вашего Google-аккаунта.
var NOTIFY_EMAIL = '';

// Версия скрипта. По ней панель понимает, что код в Google нужно обновить.
var SCRIPT_VERSION = 3;

var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
var TG_TOKEN_RE = /^\d{6,12}:[A-Za-z0-9_-]{30,60}$/;
var TG_CHAT_RE = /^-?\d{1,20}$/;

var SHEET_NAME = 'Заявки';
var LOG_SHEET = 'Журнал';
var LOG_HEAD = ['time', 'level', 'step', 'message'];
var LOG_KEEP = 300;                       // сколько строк журнала хранить: старые удаляются сами
var HEAD = ['id', 'created', 'name', 'contact', 'message', 'status', 'note', 'source'];
var STATUSES = ['new', 'work', 'done'];
var MAX = { name: 120, contact: 160, message: 4000, note: 2000 };
var READ_ACTIONS = ['list', 'settings', 'diagnose', 'log'];                 // только читают: блокировка не нужна
var WRITE_ACTIONS = ['update', 'delete', 'add', 'save_settings', 'tg_find', 'test_notify', 'set_enabled', 'clear_log'];

function doGet() {
  return json_({ ok: true, service: 'sport-intuitive-inbox', version: SCRIPT_VERSION });
}

function doPost(e) {
  var started = Date.now(), action = '', lock = null, locked = false;
  try {
    var req = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    action = String(req.action || '');
    if (action !== 'submit' && READ_ACTIONS.concat(WRITE_ACTIONS).indexOf(action) === -1) return json_({ ok: false, error: 'bad' });
    if (action !== 'submit') {
      var denied = checkKey_(req.key);
      if (denied) { log_('warn', action, 'отказ: ' + denied); return json_({ ok: false, error: denied }); }
    }
    // Блокировка нужна, только чтобы две правки не наложились. Заявка с сайта не должна пропасть из-за неё:
    // appendRow сам по себе безопасен, поэтому при занятой блокировке заявка всё равно записывается (и это попадает в журнал).
    if (action === 'submit' || WRITE_ACTIONS.indexOf(action) !== -1) {
      lock = LockService.getScriptLock();
      locked = lock.tryLock(8000);
      if (!locked) {
        log_('warn', action, 'блокировка занята более 8 с');
        if (action !== 'submit') return json_({ ok: false, error: 'locked' });
      }
    }
    var out;
    if (action === 'submit') out = submit_(req);
    else if (action === 'list') out = list_();
    else if (action === 'update') out = update_(req);
    else if (action === 'delete') out = remove_(req);
    else if (action === 'settings') out = settingsInfo_();
    else if (action === 'save_settings') out = saveSettings_(req);
    else if (action === 'tg_find') out = tgFind_(req);
    else if (action === 'test_notify') out = testNotify_();
    else if (action === 'set_enabled') out = setEnabled_(req);
    else if (action === 'diagnose') out = diagnose_();
    else if (action === 'log') out = readLog_();
    else if (action === 'clear_log') out = clearLog_();
    else out = add_(req);
    var ms = Date.now() - started;
    if (action === 'submit') log_(out && out.ok ? 'info' : 'warn', 'submit', (out && out.ok ? 'заявка записана' : 'заявка не записана: ' + (out && out.error)) + ', ' + ms + ' мс');
    else if (ms > 10000) log_('warn', action, 'медленно: ' + ms + ' мс');
    return json_(out);
  } catch (err) {
    log_('error', action || '?', errText_(err) + ', ' + (Date.now() - started) + ' мс');
    return json_({ ok: false, error: 'server', detail: errText_(err), step: action });
  } finally {
    if (lock && locked) { try { lock.releaseLock(); } catch (x) {} }
  }
}

/* ---------- журнал: лист «Журнал» в этой же таблице (без имён и текстов заявок) ---------- */

/** Короткий текст ошибки. Токен Telegram вырезается, чтобы он не попал в журнал. */
function errText_(err) {
  var text = String(err && err.message ? err.message : err);
  return text.replace(/\d{6,12}:[A-Za-z0-9_-]{30,60}/g, '[токен]').replace(/\s+/g, ' ').slice(0, 300);
}

/** Пишет строку в журнал. Сам никогда не падает: журнал не должен ломать приём заявок. */
function log_(level, step, message) {
  try { console.log('[' + level + '] ' + step + ': ' + message); } catch (x) {}
  try {
    var book = SpreadsheetApp.getActiveSpreadsheet();
    var sheet = book.getSheetByName(LOG_SHEET);
    if (!sheet) {
      sheet = book.insertSheet(LOG_SHEET);
      sheet.getRange(1, 1, 1, LOG_HEAD.length).setValues([LOG_HEAD]).setFontWeight('bold');
      sheet.setFrozenRows(1);
    }
    var row = sheet.getLastRow() + 1;
    sheet.getRange(row, 1, 1, LOG_HEAD.length).setNumberFormat('@');
    sheet.appendRow([new Date().toISOString(), String(level), String(step).slice(0, 40), errText_(message)]);
    if (sheet.getLastRow() > LOG_KEEP + 100) sheet.deleteRows(2, sheet.getLastRow() - LOG_KEEP - 1);
  } catch (err) {}
}

function readLog_() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(LOG_SHEET), items = [];
  if (sheet) {
    var rows = sheet.getDataRange().getValues();
    for (var i = rows.length - 1; i >= 1 && items.length < 80; i--) items.push({ t: String(rows[i][0]), level: String(rows[i][1]), step: String(rows[i][2]), msg: String(rows[i][3]) });
  }
  return { ok: true, items: items };
}

function clearLog_() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(LOG_SHEET);
  if (sheet && sheet.getLastRow() > 1) sheet.deleteRows(2, sheet.getLastRow() - 1);
  return { ok: true };
}

/** Проверка по шагам: что работает, что нет и сколько миллисекунд занял каждый шаг. Панель показывает результат списком. */
function diagnose_() {
  var steps = [];
  function run(name, fn) {
    var t = Date.now(), ok = true, detail = '';
    try { detail = String(fn() || ''); } catch (err) { ok = false; detail = errText_(err); }
    steps.push({ name: name, ok: ok, ms: Date.now() - t, detail: detail });
  }
  run('lock', function () { var l = LockService.getScriptLock(), got = l.tryLock(3000); if (!got) throw new Error('занята'); l.releaseLock(); });
  run('props', function () { return props_().getProperty('enabled') === '0' ? 'приём приостановлен' : 'приём включён'; });
  run('book', function () { var b = SpreadsheetApp.getActiveSpreadsheet(); if (!b) throw new Error('скрипт не привязан к таблице: откройте Apps Script из самой таблицы (Расширения → Apps Script)'); return b.getName ? b.getName() : ''; });
  run('sheet', function () { return 'строк: ' + sheet_().getLastRow(); });
  run('header', function () {
    var head = sheet_().getRange(1, 1, 1, HEAD.length).getValues()[0].map(String);
    if (head.join('|') !== HEAD.join('|')) throw new Error('заголовки листа не совпадают: ' + head.join(', '));
    return '';
  });
  run('read', function () { return 'прочитано строк: ' + sheet_().getDataRange().getValues().length; });
  run('mail', function () { return 'осталось писем сегодня: ' + MailApp.getRemainingDailyQuota(); });
  run('log', function () {
    var book = SpreadsheetApp.getActiveSpreadsheet(), sheet = book.getSheetByName(LOG_SHEET);
    if (!sheet) { log_('info', 'diagnose', 'проверка'); sheet = book.getSheetByName(LOG_SHEET); }
    if (!sheet) throw new Error('лист «Журнал» не создался');
    return '';
  });
  var enabled = props_().getProperty('enabled') !== '0';
  log_('info', 'diagnose', 'проверка: ' + steps.filter(function (x) { return !x.ok; }).length + ' ошибок');
  return { ok: true, version: SCRIPT_VERSION, enabled: enabled, steps: steps };
}

function setEnabled_(req) {
  if (req.enabled) props_().deleteProperty('enabled'); else props_().setProperty('enabled', '0');
  log_('info', 'set_enabled', req.enabled ? 'приём заявок возобновлён' : 'приём заявок приостановлен');
  return { ok: true, enabled: !!req.enabled };
}

/* ---------- from the website ---------- */

function submit_(req) {
  if (props_().getProperty('enabled') === '0') return { ok: false, error: 'off' };      // приём приостановлен в панели
  var item = {
    name: clean_(req.name, MAX.name),
    contact: clean_(req.contact, MAX.contact),
    message: clean_(req.message, MAX.message)
  };
  if (!item.name || !item.contact) return { ok: false, error: 'bad' };
  var sheet = sheet_();
  if (recentCount_(sheet) >= 10) return { ok: false, error: 'busy' };   // защита от потока спама
  item.status = 'new';
  item.note = '';
  item.source = 'site';
  var t0 = Date.now();
  append_(sheet, item);
  var saved = Date.now() - t0;
  notify_(item);
  log_('info', 'submit', 'запись в таблицу: ' + saved + ' мс, уведомления: ' + (Date.now() - t0 - saved) + ' мс');
  return { ok: true };
}

function notify_(item) {
  var cfg = config_();
  notifyEmail_(item, cfg);
  notifyTelegram_(item, cfg);
}

function recipients_(cfg) {
  return cfg.email.length ? cfg.email.join(',') : (NOTIFY_EMAIL || Session.getEffectiveUser().getEmail() || '');
}

function notifyEmail_(item, cfg) {
  try {
    var to = recipients_(cfg);
    if (!to) return;
    var options = { to: to, subject: ('Новая заявка с сайта: ' + item.name).replace(/\s+/g, ' ').slice(0, 200), body: [
      'Имя: ' + item.name,
      'Как связаться: ' + item.contact,
      '',
      item.message || '(без сообщения)',
      '',
      'Все заявки: ' + SpreadsheetApp.getActiveSpreadsheet().getUrl()
    ].join('\n') };
    if (EMAIL_RE.test(item.contact)) options.replyTo = item.contact;
    MailApp.sendEmail(options);
    problem_('err_email', '');
  } catch (err) { problem_('err_email', 'mail'); log_('error', 'mail', errText_(err)); }   // письмо не ушло (лимит почты), заявка всё равно сохранена
}

function notifyTelegram_(item, cfg) {
  if (!cfg.tgToken || !cfg.tgChat) return;
  var text = ['Новая заявка с сайта', '', 'Имя: ' + item.name, 'Как связаться: ' + item.contact, '', item.message || '(без сообщения)'].join('\n');
  var result = tgSend_(cfg.tgToken, cfg.tgChat, text);
  problem_('err_tg', result === 'ok' ? '' : result);     // не дошло: заявка всё равно сохранена, а панель покажет причину
  if (result !== 'ok') log_('warn', 'telegram', 'не отправлено: ' + result);
}

/** Отправка в Telegram. Возвращает 'ok' или код ошибки (его же понимает панель). Простой текст, без разметки. */
function tgSend_(token, chat, text) {
  try {
    var response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/sendMessage', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      payload: JSON.stringify({ chat_id: chat, text: String(text).slice(0, 4000), disable_web_page_preview: true })
    });
    var code = response.getResponseCode();
    if (code === 200) return 'ok';
    if (code === 401 || code === 404) return 'tgtoken';
    if (code === 403) return 'tgblocked';
    if (code === 400) return 'tgchat';
    return 'tgnet';
  } catch (err) { return 'tgnet'; }
}

/* ---------- notification settings (stored in this script's own properties, never on the website) ---------- */

function props_() { return PropertiesService.getScriptProperties(); }

function config_() {
  var p = props_();
  return {
    email: String(p.getProperty('notify_email') || '').split(/[,;\s]+/).filter(function (x) { return EMAIL_RE.test(x); }).slice(0, 3),
    tgToken: p.getProperty('tg_token') || '',
    tgChat: p.getProperty('tg_chat') || ''
  };
}

function problem_(key, value) {
  try { if (value) props_().setProperty(key, value); else props_().deleteProperty(key); } catch (err) {}
}

/** Что показать в панели. Токен бота наружу не отдаётся никогда: только «задан ли он» и его последние 4 знака. */
function settingsInfo_() {
  var p = props_(), cfg = config_();
  return {
    ok: true, version: SCRIPT_VERSION, enabled: p.getProperty('enabled') !== '0',
    defaultEmail: NOTIFY_EMAIL || Session.getEffectiveUser().getEmail() || '',
    email: cfg.email.join(', '),
    telegram: { token: !!cfg.tgToken, hint: cfg.tgToken ? '…' + cfg.tgToken.slice(-4) : '', chat: cfg.tgChat },
    problems: { email: p.getProperty('err_email') || '', telegram: p.getProperty('err_tg') || '' }
  };
}

function saveSettings_(req) {
  var p = props_(), email, token, chat;
  if (req.email !== undefined) {                       // сначала проверяем всё, потом пишем: либо всё сохранено, либо ничего
    var list = String(req.email || '').split(/[,;\s]+/).filter(Boolean);
    if (list.length > 3) return { ok: false, error: 'bademail' };
    for (var i = 0; i < list.length; i++) if (!EMAIL_RE.test(list[i]) || list[i].length > 160) return { ok: false, error: 'bademail' };
    email = list.join(',');
  }
  if (req.tgToken !== undefined) {
    token = String(req.tgToken || '').trim();
    if (token && !TG_TOKEN_RE.test(token)) return { ok: false, error: 'badtoken' };
  }
  if (req.tgChat !== undefined) {
    chat = String(req.tgChat || '').trim();
    if (chat && !TG_CHAT_RE.test(chat)) return { ok: false, error: 'badchat' };
  }
  if (email !== undefined) { if (email) p.setProperty('notify_email', email); else p.deleteProperty('notify_email'); p.deleteProperty('err_email'); }
  if (token !== undefined) {
    if (token) p.setProperty('tg_token', token); else { p.deleteProperty('tg_token'); p.deleteProperty('tg_chat'); }
    p.deleteProperty('err_tg');
  }
  if (chat !== undefined) { if (chat) p.setProperty('tg_chat', chat); else p.deleteProperty('tg_chat'); p.deleteProperty('err_tg'); }
  return settingsInfo_();
}

/** Ищет чат владелицы: тех, кто написал боту (в личных сообщениях). Нужен, чтобы не искать номер чата вручную. */
function tgFind_(req) {
  var token = String(req.tgToken || '').trim() || props_().getProperty('tg_token') || '';
  if (!TG_TOKEN_RE.test(token)) return { ok: false, error: 'badtoken' };
  try {
    var response = UrlFetchApp.fetch('https://api.telegram.org/bot' + token + '/getUpdates', { muteHttpExceptions: true });
    var code = response.getResponseCode();
    if (code === 401 || code === 404) return { ok: false, error: 'tgtoken' };
    if (code !== 200) return { ok: false, error: 'tgnet' };
    var data = JSON.parse(response.getContentText()), seen = {}, chats = [];
    (data.result || []).forEach(function (u) {
      var m = u.message || u.edited_message || u.my_chat_member, c = m && m.chat;
      if (!c || c.type !== 'private' || seen[c.id]) return;
      seen[c.id] = true;
      chats.push({ id: String(c.id), name: [c.first_name, c.last_name].filter(Boolean).join(' ') || (c.username ? '@' + c.username : 'без имени') });
    });
    if (!chats.length) return { ok: false, error: 'tgnone' };
    return { ok: true, chats: chats.slice(0, 5) };
  } catch (err) { return { ok: false, error: 'tgnet' }; }
}

function testNotify_() {
  var cfg = config_(), out = { ok: true, email: 'fail', emailTo: '', telegram: 'off' };
  try {
    var to = recipients_(cfg);
    if (to) {
      MailApp.sendEmail({ to: to, subject: 'Проверка уведомлений Sport Intuitive', body: 'Это тестовое письмо. Так будут приходить новые заявки с сайта.' });
      out.email = 'ok'; out.emailTo = to; problem_('err_email', '');
    }
  } catch (err) { problem_('err_email', 'mail'); }
  if (cfg.tgToken && cfg.tgChat) {
    out.telegram = tgSend_(cfg.tgToken, cfg.tgChat, 'Проверка: сюда будут приходить новые заявки с сайта.');
    problem_('err_tg', out.telegram === 'ok' ? '' : out.telegram);
  }
  return out;
}

/* ---------- from the dashboard (password required) ---------- */

function checkKey_(key) {
  if (!ADMIN_KEY || ADMIN_KEY.length < 12 || ADMIN_KEY.indexOf('ЗАМЕНИТЕ') === 0) return 'nokey';
  var cache = CacheService.getScriptCache();
  var fails = Number(cache.get('fails') || 0);
  if (fails >= 10) return 'locked';                                    // слишком много неверных паролей: пауза 10 минут
  if (String(key || '') === ADMIN_KEY) return '';
  cache.put('fails', String(fails + 1), 600);
  return 'key';
}

function list_() {
  var rows = sheet_().getDataRange().getValues();
  var items = [];
  for (var i = rows.length - 1; i >= 1 && items.length < 1000; i--) items.push(toItem_(rows[i]));
  return { ok: true, items: items };
}

function update_(req) {
  var row = find_(req.id);
  if (!row) return { ok: false, error: 'notfound' };
  var sheet = sheet_();
  if (req.status !== undefined) {
    if (STATUSES.indexOf(req.status) === -1) return { ok: false, error: 'bad' };
    sheet.getRange(row, 6).setValue(req.status);
  }
  if (req.note !== undefined) sheet.getRange(row, 7).setValue(clean_(req.note, MAX.note));
  return { ok: true };
}

function remove_(req) {
  var row = find_(req.id);
  if (!row) return { ok: false, error: 'notfound' };
  sheet_().deleteRow(row);
  return { ok: true };
}

function add_(req) {
  var item = {
    name: clean_(req.name, MAX.name),
    contact: clean_(req.contact, MAX.contact),
    message: clean_(req.message, MAX.message),
    status: STATUSES.indexOf(req.status) === -1 ? 'new' : req.status,
    note: '',
    source: 'manual'
  };
  if (!item.name) return { ok: false, error: 'bad' };
  append_(sheet_(), item);
  return { ok: true };
}

/* ---------- the sheet ---------- */

function sheet_() {
  var book = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = book.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = book.insertSheet(SHEET_NAME);
    sheet.getRange(1, 1, 1, HEAD.length).setValues([HEAD]).setFontWeight('bold');
    sheet.setFrozenRows(1);
    sheet.getRange(1, 1, sheet.getMaxRows(), HEAD.length).setNumberFormat('@');   // всё как простой текст: ни дат, ни формул
  }
  return sheet;
}

function append_(sheet, item) {
  var id = Utilities.getUuid().slice(0, 8);
  try { sheet.getRange(sheet.getLastRow() + 1, 1, 1, HEAD.length).setNumberFormat('@'); } catch (err) {}   // и в таблице, которую вы подготовили сами: простой текст, никаких формул
  sheet.appendRow([id, new Date().toISOString(), item.name, item.contact, item.message, item.status, item.note, item.source]);
}

function toItem_(row) {
  var created = row[1] instanceof Date ? row[1].toISOString() : String(row[1]);
  return { id: String(row[0]), at: created, name: String(row[2]), contact: String(row[3]), message: String(row[4]),
           status: STATUSES.indexOf(String(row[5])) === -1 ? 'new' : String(row[5]), note: String(row[6]), source: String(row[7]) };
}

function find_(id) {
  id = String(id || '');
  if (!id) return 0;
  var ids = sheet_().getRange(1, 1, sheet_().getLastRow(), 1).getValues();
  for (var i = 1; i < ids.length; i++) if (String(ids[i][0]) === id) return i + 1;
  return 0;
}

function recentCount_(sheet) {
  var last = sheet.getLastRow();
  if (last < 2) return 0;
  var from = Math.max(2, last - 11);
  var values = sheet.getRange(from, 2, last - from + 1, 1).getValues();
  var limit = Date.now() - 60000, count = 0;
  for (var i = 0; i < values.length; i++) {
    var t = new Date(values[i][0]).getTime();
    if (t > limit) count++;
  }
  return count;
}

function clean_(value, max) {
  return String(value === undefined || value === null ? '' : value).replace(/\r\n/g, '\n').trim().slice(0, max);
}

function json_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
'''

MESSAGES_NEW = r'''  server: 'В скрипте произошла ошибка. Ниже, в блоке «Управление подключением и журнал», нажмите «Проверить подключение»: он покажет, какой шаг не работает. Журнал можно скопировать и прислать.',
  locked: 'Скрипт сейчас занят другой операцией. Подождите несколько секунд и повторите.',
  off: 'Приём заявок приостановлен. Нажмите «Возобновить приём заявок» в блоке «Управление подключением и журнал».',
  timeout: 'Google не ответил за 45 секунд. Нажмите «Повторить»; если так каждый раз, откройте «Управление подключением и журнал» → «Проверить подключение».',
'''

NEW_REQ_FN = r'''function newReq() { return { items: null, loaded: false, loading: false, error: '', code: '', keyProblem: '', filter: 'new', q: '', enabled: null, toolsOpen: false }; }
'''

INBOX_CALL_BLOCK = r'''/* ---------- panel log: what the panel asked the script and what came back (never passwords, never visitors' data) ---------- */
const INBOX_LOG_KEY = 'si-admin-inbox-log';
const INBOX_LIMITS = { timeout: 45000 };
const scrub = v => String(v == null ? '' : v).replace(/\d{6,12}:[A-Za-z0-9_-]{30,60}/g, '[токен]').replace(/\s+/g, ' ').slice(0, 300);
function logRead() { try { const a = JSON.parse(LS.get(INBOX_LOG_KEY) || '[]'); return Array.isArray(a) ? a : []; } catch (e) { return []; } }
function logAdd(action, ok, code, ms, detail) {
  const a = logRead();
  a.push({ t: new Date().toISOString(), action: scrub(action), ok: !!ok, code: scrub(code), ms: Math.round(ms) || 0, detail: scrub(detail) });
  LS.set(INBOX_LOG_KEY, JSON.stringify(a.slice(-60)));
}
const logClear = () => LS.del(INBOX_LOG_KEY);
const pad2 = n => String(n).padStart(2, '0');
const logStamp = iso => { const d = new Date(iso); return isNaN(d) ? String(iso || '') : `${pad2(d.getDate())}.${pad2(d.getMonth() + 1)}.${d.getFullYear()} ${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`; };
/** One text for copying to whoever helps: first the panel's own calls, then (if loaded) what the Google script wrote. */
function logText(scriptItems) {
  const mine = logRead().slice().reverse().map(x => `${logStamp(x.t)} · ${x.action} · ${x.ok ? 'ok' : 'ошибка ' + x.code} · ${x.ms} мс${x.detail ? ' · ' + x.detail : ''}`);
  const out = ['=== Журнал панели (этот браузер) ===', ...(mine.length ? mine : ['(пока пусто)'])];
  if (scriptItems) out.push('', '=== Журнал скрипта (Google) ===', ...(scriptItems.length ? scriptItems.map(x => `${logStamp(x.t)} · ${x.level} · ${x.step} · ${x.msg}`) : ['(пока пусто)']));
  return out.join('\n');
}
async function inboxCall(action, data) {
  const url = inboxUrl(), started = Date.now();
  const fail = (code, message, detail) => { logAdd(action, false, code, Date.now() - started, detail); const e = inboxFail(code, message); e.detail = scrub(detail); return e; };
  if (!INBOX_URL_RE.test(url)) throw fail('url', 'Адрес приёма заявок указан неверно. Он должен выглядеть так: https://script.google.com/macros/s/…/exec');
  const ctl = typeof AbortController === 'function' ? new AbortController() : null;
  const timer = ctl ? setTimeout(() => ctl.abort(), INBOX_LIMITS.timeout) : 0;
  const timedOut = () => !!(ctl && ctl.signal.aborted);
  let j = null, r;
  try {
    try {
      r = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'text/plain;charset=utf-8' }, cache: 'no-store', ...(ctl ? { signal: ctl.signal } : {}),
                             body: JSON.stringify({ action, key: inboxKey(), ...(data || {}) }) });
    } catch (e) {
      if (timedOut()) throw fail('timeout', INBOX_MESSAGES.timeout);
      throw fail('net', 'Не удалось связаться с таблицей заявок. Проверьте интернет. Если с ним всё в порядке, проверьте, что при развёртывании скрипта выбрано «У кого есть доступ: Все».', e && e.message);
    }
    try { j = await r.json(); } catch (e) { if (timedOut()) throw fail('timeout', INBOX_MESSAGES.timeout); /* not JSON: Google sent a sign-in page */ }
  } finally { clearTimeout(timer); }
  if (!j) throw fail('format', 'Google ответил страницей входа, а не данными. Почти всегда это значит, что при развёртывании выбрано не «Все». Исправьте: в Apps Script нажмите «Начать развёртывание» → «Управление развёртываниями» → значок карандаша → «У кого есть доступ»: «Все», «Версия»: «Новая версия» → «Развернуть». Адрес при этом не меняется. Проверьте также «Запуск от имени»: «Я».', 'HTTP ' + (r && r.status));
  if (j.ok !== true) {
    const code = j.error || 'server', base = INBOX_MESSAGES[code] || INBOX_MESSAGES.server, detail = scrub(j.detail);
    throw fail(code, base + (detail ? ' Подробности от скрипта: ' + detail : ''), detail);
  }
  logAdd(action, true, 'ok', Date.now() - started, '');
  return j;
}
const DIAG_LABELS = { lock: 'Блокировка скрипта', props: 'Настройки скрипта', book: 'Доступ к таблице', sheet: 'Лист «Заявки»', header: 'Заголовки столбцов', read: 'Чтение заявок', mail: 'Почта Google', log: 'Журнал' };
const diagText = j => ((j && j.steps) || []).map(s => `${s.ok ? '✓' : '✗'} ${DIAG_LABELS[s.name] || s.name} · ${s.ms} мс${s.detail ? ' · ' + scrub(s.detail) : ''}`);
async function inboxDiagnose() { const j = await inboxCall('diagnose'); S.req.enabled = j.enabled !== false; return j; }
async function inboxScriptLog() { return (await inboxCall('log')).items || []; }
async function inboxToggle(enabled) { const j = await inboxCall('set_enabled', { enabled: !!enabled }); S.req.enabled = j.enabled !== false; return S.req.enabled; }
/** Unlinks the site from the script. Nothing is deleted in Google. The site itself changes after "Save and publish". */
function inboxDisconnect() { S.site.inbox_endpoint = ''; LS.del(INBOX_KEY); S.req = newReq(); S.notify = newNotify(); }
/** Starts from nothing: also forgets the password that was made for the script, so a new one is made together with the new code. */
function inboxReset() { inboxDisconnect(); LS.del(GEN_KEY); logClear(); }
'''

TOOLS_FN = r'''/* ---------- connection tools: check, pause, unlink, start over, log (inbox-diagnostics-v1) ---------- */
function requestsTools(mode, open) {
  const connected = mode === 'connected' && !!inboxUrl();
  const note = el('p', { class: 'muted', role: 'status' });
  const result = el('div', {});
  let scriptItems = null;
  const logBox = el('textarea', { readonly: true, rows: 9, 'aria-label': 'Журнал', style: 'width:100%;box-sizing:border-box;font:12px/1.45 ui-monospace,Menlo,Consolas,monospace;border:1px solid var(--line);border-radius:12px;padding:10px' });
  const paintLog = () => { logBox.value = logText(scriptItems); };
  // These buttons only change the nodes in this block: no redraw of the whole panel, so a click is never lost under the cursor.
  const run = async (btn, fn) => { btn.disabled = true; try { await fn(); } catch (e) { note.textContent = e.code === 'bad' ? 'Код скрипта в Google старый: он ещё не умеет этого. Нажмите «Скопировать новый код скрипта» и обновите его в Google (шаги появятся здесь).' : e.message; } btn.disabled = false; paintLog(); };

  const diag = el('button', { class: 'btn small', type: 'button', onclick: () => run(diag, async () => {
    note.textContent = 'Проверяю по шагам. Это может занять до минуты…'; result.replaceChildren();
    const j = await inboxDiagnose();
    result.replaceChildren(el('ul', { style: 'margin:8px 0;padding-left:18px;font-size:13px' }, ...diagText(j).map(line => el('li', line.startsWith('✗') ? { style: 'font-weight:600' } : {}, line))));
    note.textContent = (j.steps || []).every(s => s.ok) ? 'Все шаги прошли. Если форма на сайте всё равно не отправляется, скопируйте журнал ниже и пришлите мне.' : 'Шаги с ✗ не прошли: причина написана рядом. Скопируйте журнал ниже и пришлите мне.';
    syncToggle();
  }) }, 'Проверить подключение');

  const toggle = el('button', { class: 'btn ghost small', type: 'button' });
  const syncToggle = () => { toggle.textContent = S.req.enabled === false ? 'Возобновить приём заявок' : 'Приостановить приём заявок'; };
  toggle.addEventListener('click', () => run(toggle, async () => {
    const pause = S.req.enabled !== false;
    if (pause && !confirm('Форма на сайте перестанет принимать заявки: посетители увидят «Could not send», пока вы не возобновите приём. Таблица и старые заявки не меняются. Приостановить?')) return;
    note.textContent = pause ? 'Приостанавливаю…' : 'Возобновляю…';
    await inboxToggle(!pause);
    note.textContent = pause ? 'Приём приостановлен. Возобновить можно этой же кнопкой.' : 'Приём заявок возобновлён.';
    syncToggle();
  }));
  syncToggle();

  const disconnect = el('button', { class: 'btn ghost small', type: 'button', onclick: () => {
    if (!confirm('Адрес скрипта уберётся из настроек сайта: форма перестанет писать в таблицу. Заявки в вашей Google-таблице останутся. Изменение попадёт на сайт после «Сохранить и опубликовать». Отключить?')) return;
    inboxDisconnect();
    setNotice('ok', [el('strong', {}, 'Отключено. '), 'Чтобы форма на сайте перестала писать в таблицу, нажмите «Сохранить и опубликовать» внизу. Подключить снова можно здесь же: пароль остался прежним.']);
    paintBar(); renderPanel();
  } }, 'Отключить от сайта');

  const reset = el('button', { class: 'btn ghost small', type: 'button', onclick: () => {
    if (!confirm('Панель забудет адрес скрипта и пароль, а в настройках сайта адрес уберётся. Заявки в вашей Google-таблице останутся. Потом нужно будет заново вставить код и сделать развёртывание (панель покажет шаги, пароль будет новый). Удалить подключение и начать заново?')) return;
    inboxReset();
    setNotice('ok', [el('strong', {}, 'Подключение удалено. '), 'Нажмите «Сохранить и опубликовать» внизу, если адрес был на сайте. Старый скрипт в Google можно выключить: Apps Script → «Начать развёртывание» → «Управление развёртываниями» → «Архивировать». Затем подключите заново по шагам ниже.']);
    paintBar(); renderPanel();
  } }, 'Удалить подключение и начать заново');

  const loadScriptLog = el('button', { class: 'btn ghost small', type: 'button', onclick: () => run(loadScriptLog, async () => {
    note.textContent = 'Загружаю журнал из Google…'; scriptItems = await inboxScriptLog(); note.textContent = 'Журнал скрипта загружен: он в конце окна ниже.';
  }) }, 'Загрузить журнал скрипта');
  const copyLog = el('button', { class: 'btn ghost small', type: 'button', onclick: async () => {
    paintLog();
    try { await navigator.clipboard.writeText(logBox.value); copyLog.textContent = 'Скопировано ✓'; }
    catch (e) { copyLog.textContent = 'Выделите текст и скопируйте'; logBox.select(); }
    setTimeout(() => { copyLog.textContent = 'Скопировать журнал'; }, 3000);
  } }, 'Скопировать журнал');
  const clear = el('button', { class: 'btn ghost small', type: 'button', onclick: () => run(clear, async () => {
    logClear();
    if (connected) { try { await inboxCall('clear_log'); } catch (e) { /* the script log stays: the panel log is already empty */ } if (scriptItems) scriptItems = []; }
    note.textContent = 'Журнал очищен.';
  }) }, 'Очистить журнал');
  const copyCode = el('button', { class: 'btn ghost small', type: 'button', onclick: async () => {
    try {
      const text = scriptWithPassword(await (await fetch('inbox-script.txt', { cache: 'no-store' })).text(), inboxKey() || LS.get(GEN_KEY));
      await navigator.clipboard.writeText(text); copyCode.textContent = 'Скопировано ✓';
      note.textContent = 'Новый код скопирован. В Google: Apps Script → выделите весь код (Ctrl+A) → вставьте → «Сохранить» → «Начать развёртывание» → «Управление развёртываниями» → карандаш → «Версия»: «Новая версия» → «Развернуть». Адрес не изменится. Потом нажмите «Проверить подключение».';
    } catch (e) { note.textContent = 'Не получилось скопировать. Код лежит в репозитории: admin/inbox-script.txt'; }
    setTimeout(() => { copyCode.textContent = 'Скопировать новый код скрипта'; }, 3000);
  } }, 'Скопировать новый код скрипта');
  paintLog();

  return el('details', { class: 'more', open: !!open || !!S.req.toolsOpen, ontoggle: e => { S.req.toolsOpen = e.target.open; } },
    el('summary', {}, connected ? 'Управление подключением и журнал' : 'Журнал и «начать заново»'),
    el('div', { class: 'inner' },
      el('p', { class: 'muted' }, connected
        ? 'Если заявки не приходят или здесь ошибка: нажмите «Проверить подключение», потом скопируйте журнал. Ни одна из этих кнопок не удаляет заявки в Google-таблице.'
        : 'Здесь записано, что панель пыталась сделать при подключении. Если что-то не получилось, скопируйте журнал. «Начать заново» даёт новый пароль и чистый ход подключения; заявки в таблице не трогает.'),
      el('div', { class: 'row', style: 'margin-top:0' }, ...(connected ? [diag, toggle, copyCode, disconnect] : []), reset),
      note, result,
      el('p', { class: 'muted', style: 'margin:14px 0 6px' }, el('strong', {}, 'Журнал')),
      logBox,
      el('div', { class: 'row', style: 'margin-top:8px' }, ...(connected ? [loadScriptLog] : []), copyLog, clear)));
}
'''

MOCK_BLOCK = r'''const store = {}, mails = [], calls = [], formats = [], rows = [['id', 'created', 'name', 'contact', 'message', 'status', 'note', 'source']];
const logRows = [], logFormats = [];
let telegram = 200, breakSheet = null, lockOk = true;
// A sheet that keeps its rows in an array. breakSheet makes reading the requests sheet fail with that message.
const makeSheet = (data, fmts, main) => ({
  getDataRange: () => { if (main && breakSheet) throw new Error(breakSheet); return { getValues: () => data }; },
  getLastRow: () => data.length, getMaxRows: () => 1000, setFrozenRows() {},
  appendRow: r => data.push(r), deleteRow: i => data.splice(i - 1, 1), deleteRows: (i, n) => data.splice(i - 1, n),
  getRange: (r, c, nr, nc) => ({
    getValues: () => data.slice(r - 1, r - 1 + (nr || 1)).map(x => x.slice(c - 1, c - 1 + (nc || 1))),
    setValues: v => { v.forEach((row, k) => { data[r - 1 + k] = row.slice(); }); return { setFontWeight() {} }; },
    setValue: v => { data[r - 1][c - 1] = v; },
    setNumberFormat(f) { fmts.push([r, c, nr, nc, f]); return this; } }) });
const sheet = makeSheet(rows, formats, true), logSheet = makeSheet(logRows, logFormats, false);
'''

SCRIPT_V3_TESTS = r'''
// v3 (inbox-diagnostics-v1): diagnostics, pause, soft lock, readable errors, a log without personal data
let dg = post({ action: 'diagnose', key: K });
assert.ok(dg.ok && dg.version === 3 && dg.enabled === true && dg.steps.length >= 7, 'diagnose answers: ' + JSON.stringify(dg).slice(0, 300));
assert.ok(dg.steps.every(x => x.ok), 'every step passes with healthy services: ' + JSON.stringify(dg.steps.filter(x => !x.ok)));
assert.ok(dg.steps.some(x => x.name === 'mail' && /99/.test(x.detail)), 'the mail quota is shown');
assert.strictEqual(post({ action: 'diagnose', key: 'wrong-key-1234' }).error, 'key', 'diagnose needs the password');

// pause: nothing is stored while paused; resuming works
let n0 = rows.length;
assert.strictEqual(post({ action: 'set_enabled', key: K, enabled: false }).enabled, false);
assert.strictEqual(post({ action: 'settings', key: K }).enabled, false);
assert.strictEqual(post({ action: 'submit', name: 'Paused', contact: 'p@example.com', message: '' }).error, 'off');
assert.strictEqual(rows.length, n0, 'a paused inbox stores nothing');
assert.strictEqual(post({ action: 'set_enabled', key: K, enabled: true }).enabled, true);
assert.ok(post({ action: 'submit', name: 'Resumed', contact: 'r@example.com', message: '' }).ok && rows.length === n0 + 1);

// a busy lock never loses a visitor's request, but does not let an edit through
lockOk = false; n0 = rows.length;
assert.ok(post({ action: 'submit', name: 'Busy', contact: 'busy@example.com', message: '' }).ok && rows.length === n0 + 1, 'the visitor request is still stored');
assert.strictEqual(post({ action: 'delete', key: K, id: 'abcdef12' }).error, 'locked');
assert.strictEqual(rows.length, n0 + 1, 'a refused edit changes nothing');
lockOk = true;

// an error inside the script comes back as a readable reason, and a token never leaks into it
breakSheet = 'boom https://api.telegram.org/bot' + TOKEN + '/x';
const broken = post({ action: 'list', key: K });
assert.strictEqual(broken.error, 'server');
assert.ok(/boom/.test(broken.detail) && !broken.detail.includes(TOKEN) && broken.step === 'list', 'detail: ' + broken.detail);
breakSheet = null;
assert.ok(post({ action: 'list', key: K }).ok, 'works again once the cause is gone');

// the log says what happened, without names, contacts, the password or the token
const lg = post({ action: 'log', key: K }), lgText = JSON.stringify(lg.items);
assert.ok(lg.ok && lg.items.length > 5 && /boom/.test(lgText) && /submit/.test(lgText) && /блокировка/.test(lgText), 'the log tells what happened');
for (const secret of ['Anna', 'Visitor', 'Busy', 'v@example.com', 'b@example.com', 'busy@example.com', 'p@example.com', TOKEN, K]) assert.ok(!lgText.includes(secret), 'the log never holds ' + secret);
assert.ok(post({ action: 'clear_log', key: K }).ok && post({ action: 'log', key: K }).items.length === 0, 'the log can be cleared');
assert.strictEqual(post({ action: 'log', key: 'wrong-key-1234' }).error, 'key', 'the log needs the password');
'''

PANEL_TOOLS_CHECK = r"""# inbox-diagnostics-v1
INBOX_TOOLS_CHECK = r'''
// The dashboard's connection tools, without a browser: a stand-in localStorage and fetch.
const store = {};
globalThis.localStorage = { getItem: k => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; } };
const d = require(process.argv[2]), assert = require('assert');
const ID = 'AKfycb' + 'x'.repeat(30), URL_ = 'https://script.google.com/macros/s/' + ID + '/exec', TOKEN = '123456789:' + 'A'.repeat(35), PW = 'pw-1234567890123';
let answer = { ok: true }, calls = [], hang = false, html = false;
globalThis.fetch = (url, o) => {
  calls.push(JSON.parse(o.body));
  if (hang) return new Promise((resolve, reject) => o.signal.addEventListener('abort', () => reject(new Error('aborted'))));
  return Promise.resolve({ status: 200, json: async () => { if (html) throw new Error('not json'); return answer; } });
};
d.S.site.inbox_endpoint = URL_; store['si-admin-inbox-key'] = PW;
(async () => {
  await d.inboxCall('list');
  assert.strictEqual(d.logRead().length, 1);
  assert.ok(d.logRead()[0].ok && d.logRead()[0].action === 'list');
  assert.strictEqual(calls[0].key, PW, 'the password is sent to the script');
  assert.ok(!store['si-admin-inbox-log'].includes(PW), 'the password is never written to the log');

  answer = { ok: false, error: 'server', detail: 'boom ' + TOKEN };                       // a readable reason, no token
  let err = await d.inboxCall('list').then(() => null, e => e);
  assert.ok(err && err.code === 'server' && /boom/.test(err.message) && /Проверить подключение/.test(err.message) && !err.message.includes(TOKEN));
  assert.ok(/ошибка server/.test(d.logText()) && !d.logText().includes(TOKEN) && !d.logText().includes(PW));

  html = true; err = await d.inboxCall('list').then(() => null, e => e); html = false;       // Google sent a sign-in page
  assert.strictEqual(err.code, 'format');

  hang = true; d.INBOX_LIMITS.timeout = 40;                                                  // Google never answers
  err = await d.inboxCall('list').then(() => null, e => e); hang = false;
  assert.strictEqual(err.code, 'timeout');

  answer = { ok: true, version: 3, enabled: false, steps: [{ name: 'lock', ok: true, ms: 3, detail: '' }, { name: 'sheet', ok: false, ms: 12, detail: 'нет листа' }] };
  const j = await d.inboxDiagnose(), lines = d.diagText(j);
  assert.strictEqual(d.S.req.enabled, false);
  assert.ok(lines[0].startsWith('✓') && lines[1].startsWith('✗') && /нет листа/.test(lines[1]));
  answer = { ok: true, enabled: true };
  assert.strictEqual(await d.inboxToggle(true), true);
  assert.deepStrictEqual([calls[calls.length - 1].action, calls[calls.length - 1].enabled], ['set_enabled', true]);

  for (let i = 0; i < 80; i++) d.logAdd('x', true, 'ok', 1, '');                             // the panel log stays short
  assert.strictEqual(d.logRead().length, 60);
  assert.ok(/Журнал скрипта/.test(d.logText([{ t: '2026-11-19T10:00:00.000Z', level: 'error', step: 'list', msg: 'boom' }])));

  store['si-admin-inbox-gen'] = PW;                                                          // unlink: the site forgets the script, the password stays
  d.inboxDisconnect();
  assert.strictEqual(d.S.site.inbox_endpoint, '');
  assert.ok(!('si-admin-inbox-key' in store) && store['si-admin-inbox-gen'] === PW);
  assert.ok(d.S.req.loaded === false && d.S.req.enabled === null);
  d.S.site.inbox_endpoint = URL_; store['si-admin-inbox-key'] = PW;                          // start over: the generated password and the log go too
  d.inboxReset();
  assert.ok(!('si-admin-inbox-gen' in store) && !('si-admin-inbox-log' in store) && d.S.site.inbox_endpoint === '');
  console.log('inbox tools ok');
})().catch(e => { console.error(e); process.exit(1); });
'''


"""

PANEL_TOOLS_RUN = r'''
            tools = Path(folder) / 'tools.js'   # inbox-diagnostics-v1
            tools.write_text(INBOX_TOOLS_CHECK, encoding='utf-8')
            result = subprocess.run([node, str(tools), str(module)], capture_output=True, text=True)
            assert result.returncode == 0 and 'inbox tools ok' in result.stdout, f'inbox tools: {(result.stderr or result.stdout)[:800]}'
'''

README_ADD = r'''
## Обновление: заявки. Проверка, журнал, пауза и «начать заново» (ноябрь 2026) <!-- inbox-diagnostics-v1 -->

Скрипт: `apply_inbox_diagnostics_update.py`. Зачем: при ошибке «В скрипте произошла ошибка» панель не говорила, что именно сломалось, а подключение нельзя было спокойно выключить и повторить.

- **Скрипт Google стал версии 3** (`admin/inbox-script.txt`). Он ведёт лист **«Журнал»** в вашей таблице: что и когда произошло, сколько миллисекунд заняла запись и письмо. В журнал **не попадают** имена, контакты и тексты заявок, пароль и токен Telegram. Старые строки журнала удаляются сами (хранится около 300).
- **Реальная причина ошибки теперь видна.** Раньше любое исключение внутри скрипта превращалось в безликое «server». Теперь скрипт возвращает короткий текст ошибки, а панель показывает его рядом с сообщением.
- **Блокировка больше не губит заявку.** Если скрипт был занят дольше 8 секунд, заявка с сайта всё равно записывается (это попадает в журнал). Раньше при занятой блокировке скрипт ждал 20 секунд и отвечал ошибкой. Это возможная причина долгого «Sending…», но не доказанная: точную причину покажут «Проверить подключение» и журнал. Правки владелицы (статус, удаление) при занятой блокировке просят повторить.
- **Вкладка «Заявки» → «Управление подключением и журнал»**: «Проверить подключение» (проверка по шагам с временем каждого), «Приостановить / Возобновить приём заявок», «Скопировать новый код скрипта», «Отключить от сайта», «Удалить подключение и начать заново», окно с журналом (панели и, по кнопке, самого скрипта), «Скопировать журнал», «Очистить журнал». Блок доступен и при ошибке, и до подключения (там только журнал и «начать заново»).
- Панель больше не ждёт Google бесконечно: через 45 секунд показывает «Google не ответил».
- Тесты: скрипт Google прогоняется в Node с подставными сервисами (диагностика, пауза, занятая блокировка, ошибка внутри скрипта, отсутствие личных данных и токена в журнале); логика панели (журнал, таймаут, отключение, «начать заново») тоже проверяется в Node.
- Подробности: `docs/DASHBOARD.md`, раздел «Заявки: если что-то не работает».
'''

DASHBOARD_ADD = r'''
## Заявки: если что-то не работает (проверка, журнал, отключение) <!-- inbox-diagnostics-v1 -->

Всё ниже находится на вкладке «Заявки», в блоке **«Управление подключением и журнал»** (при ошибке он раскрыт сам).

**Сначала обновите код скрипта в Google (один раз).** Проверка и журнал есть только в версии 3: нажмите «Скопировать новый код скрипта», в Google откройте «Расширения» → «Apps Script», выделите весь код (Ctrl+A или ⌘A), вставьте новый, сохраните. Затем «Начать развёртывание» → «Управление развёртываниями» → значок карандаша → «Версия»: **«Новая версия»** → «Развернуть». Адрес не меняется, пароль в новом коде уже вписан. Без «Новой версии» Google продолжит запускать старый код.

**Что делает каждая кнопка**

| Кнопка | Что происходит | Заявки в таблице |
|---|---|---|
| Проверить подключение | Скрипт по шагам проверяет блокировку, доступ к таблице, лист «Заявки», заголовки, чтение, почту и журнал. У каждого шага видно время и причину, если он не прошёл. | не меняются |
| Приостановить / Возобновить приём заявок | Сразу, без «Сохранить и опубликовать». Пока приём приостановлен, форма на сайте показывает посетителям ошибку отправки. | не меняются |
| Скопировать новый код скрипта | Копирует код с вашим паролем. Шаги обновления появятся под кнопками. | не меняются |
| Отключить от сайта | Убирает адрес скрипта из настроек сайта. После «Сохранить и опубликовать» форма перестаёт писать в таблицу. Пароль остаётся, подключить снова можно сразу. | остаются |
| Удалить подключение и начать заново | Панель забывает адрес, пароль и журнал; в настройках сайта адрес убирается. Появляется экран подключения с **новым** паролем и новым кодом. | остаются |
| Скопировать журнал / Очистить журнал | Журнал панели (последние 60 обращений к скрипту) и, если нажать «Загрузить журнал скрипта», журнал из Google. | не меняются |

Сам скрипт в Google панель удалить не может. Чтобы выключить старый: Apps Script → «Начать развёртывание» → «Управление развёртываниями» → «Архивировать». Лист «Журнал» можно удалить в любой момент: скрипт создаст его заново. Лист «Заявки» не удаляйте: в нём ваши заявки.

**Что делать, если форма на сайте пишет «Could not send»**

1. «Проверить подключение». Шаг с ✗ покажет причину: нет доступа к таблице, заголовки не совпадают, блокировка занята, лимит почты исчерпан.
2. Если все шаги ✓, а форма не отправляет: «Загрузить журнал скрипта». Строки `submit` показывают, дошла ли заявка до скрипта и сколько миллисекунд ушло на запись и на письмо. Если строк `submit` нет, запрос вообще не дошёл: проверьте «У кого есть доступ: Все» и что адрес скрипта сохранён на сайте («Сохранить и опубликовать»).
3. Нажмите «Скопировать журнал» и пришлите текст. В нём нет паролей, имён и текстов заявок.
4. Если запутались: «Удалить подключение и начать заново» и подключите по шагам.

**Приватность журнала.** Лист «Журнал» лежит в вашей таблице (она закрыта), журнал панели лежит только в этом браузере. Имён, контактов и текстов заявок, пароля и токена Telegram там нет: в ошибках токен вырезается автоматически.
'''

HOSTING_ADD = r'''
### Если запись CNAME для `www` не добавляется <!-- spaceship-cname-help-v1 -->

Я не вижу ваш экран и не нашла описания именно интерфейса Spaceship, поэтому это список вероятных причин, а не точный диагноз. Если появляется сообщение об ошибке, перепишите его дословно.

1. **Значение**: только `ВАШ-ЛОГИН.github.io`, без `https://`, без `/`, без названия репозитория. Логин пишется так же, как в адресе вашего GitHub.
2. **Имя (Host)**: только `www`, а не `www.ваш-домен.com` и не `@`. Для `@` CNAME делать нельзя: там остаются четыре записи A.
3. **Конфликт**: для имени `www` не должно быть другой записи (A, AAAA, ALIAS, CNAME или перенаправления «URL redirect»). Spaceship часто ставит такую запись по умолчанию. Удалите её и добавьте CNAME заново.
4. **Не путайте**: четыре записи A (`@`) уже добавлены, и это правильно. CNAME нужен только для `www` и не обязателен, чтобы сайт открывался по основному адресу. Без него `www.ваш-домен.com` просто не откроется.
5. Если запись есть, но GitHub пишет, что домен не настроен, подождите до нескольких часов и нажмите «Check again» в Settings → Pages.
'''

CONCEPT_ADD = r'''
## Решения: заявки, когда что-то сломалось (ноябрь 2026) <!-- inbox-diagnostics-v1 -->

- «Приостановить приём» (в скрипте Google, мгновенно) и «Отключить от сайта» (убирает адрес из настроек, действует после публикации) разделены намеренно: первое для паузы, второе для демонтажа. Обе кнопки не трогают заявки в таблице.
- Журнал не содержит персональных данных посетителей: репозиторий и панель могут показывать журнал третьим лицам при поиске ошибки, а заявки остаются только в таблице владелицы.
- Заявка с сайта важнее блокировки: при занятой блокировке запись всё равно делается, потому что добавление строки безопасно само по себе.
'''


class Miss(Exception):
    pass


def _lines(text):
    return text.split('\n')


def _find(text, prefix):
    hits = [i for i, line in enumerate(_lines(text)) if line.startswith(prefix)]
    if len(hits) != 1:
        raise Miss(f'начало строки найдено {len(hits)} раз(а), а нужно ровно 1: {prefix[:80]!r}')
    return hits[0]


def exact(text, old, new):
    n = text.count(old)
    if n != 1:
        raise Miss(f'текст найден {n} раз(а), а нужно ровно 1: {old[:80]!r}')
    return text.replace(old, new)


def line(text, prefix, new):
    rows = _lines(text)
    rows[_find(text, prefix)] = new.rstrip('\n')
    return '\n'.join(rows)


def before(text, prefix, new):
    rows = _lines(text)
    i = _find(text, prefix)
    rows[i:i] = new.rstrip('\n').split('\n')
    return '\n'.join(rows)


def after(text, prefix, new):
    rows = _lines(text)
    i = _find(text, prefix)
    rows[i + 1:i + 1] = new.rstrip('\n').split('\n')
    return '\n'.join(rows)


def between(text, start, end, new):
    rows = _lines(text)
    i, j = _find(text, start), _find(text, end)
    if not i < j:
        raise Miss(f'порядок якорей нарушен: {start[:50]!r} должен быть раньше {end[:50]!r}')
    rows[i:j] = new.rstrip('\n').split('\n')
    return '\n'.join(rows)


def whole(new):
    return lambda text: new


def append_doc(add):
    return lambda text: text.rstrip('\n') + '\n' + add


def gitignore_add(text):
    entry = '.backup-inbox-diagnostics/'
    return text if entry in _lines(text) else text.rstrip('\n') + '\n' + entry + '\n'


# (файл, маркер «уже применено», список правок: каждая правка это функция от текста)
FILES = [
    ('admin/inbox-script.txt', 'var SCRIPT_VERSION = 3;', [whole(NEW_INBOX_SCRIPT)]),
    ('admin/index.html', 'inbox-diagnostics-v1', [
        lambda t: exact(t, "req: { items: null, loaded: false, loading: false, error: '', code: '', keyProblem: '', filter: 'new', q: '' } };", "req: newReq() };"),
        lambda t: after(t, 'function newNotify() {', NEW_REQ_FN),
        lambda t: line(t, "  server: 'В скрипте произошла ошибка.", MESSAGES_NEW),
        lambda t: between(t, 'async function inboxCall(action, data) {', 'function requestCounts(items) {', INBOX_CALL_BLOCK),
        lambda t: exact(t, "N.data = await inboxCall('settings'); N.draft = draftFrom(N.data); N.loaded = true; }",
                           "N.data = await inboxCall('settings'); N.draft = draftFrom(N.data); S.req.enabled = N.data.enabled !== false; N.loaded = true; }"),
        lambda t: exact(t, 'inboxCall, notifyLoad, notifySave, notifyFind,',
                           'inboxCall, inboxDiagnose, inboxScriptLog, inboxToggle, inboxDisconnect, inboxReset, logRead, logAdd, logClear, logText, diagText, newReq, INBOX_LIMITS, notifyLoad, notifySave, notifyFind,'),
        lambda t: before(t, 'function counts() {', TOOLS_FN),
        lambda t: exact(t, "if (!inboxUrl()) return el('div', {}, ...head, requestsSetup());", "if (!inboxUrl()) return el('div', {}, ...head, requestsSetup(), requestsTools('setup'));"),
        lambda t: exact(t, "if (!inboxKey()) return el('div', {}, ...head, requestsKeyBox());", "if (!inboxKey()) return el('div', {}, ...head, requestsKeyBox(), requestsTools('connected'));"),
        lambda t: exact(t, "'Ввести пароль заново')));", "'Ввести пароль заново')), requestsTools('connected', true));"),
        lambda t: exact(t, 'panelNotify(), pills, list, add());', "panelNotify(), pills, list, add(), requestsTools('connected'));"),
    ]),
    ('scripts/test_build.py', '# inbox-diagnostics-v1', [
        lambda t: between(t, 'const store = {}, mails = []', 'const ctx = {', MOCK_BLOCK),
        lambda t: line(t, '  LockService: { getScriptLock:', "  LockService: { getScriptLock: () => ({ waitLock() {}, tryLock: () => lockOk, releaseLock() {} }) },"),
        lambda t: line(t, '  MailApp: { sendEmail:', "  MailApp: { sendEmail: o => { mails.push(o); }, getRemainingDailyQuota: () => 99 },"),
        lambda t: line(t, '  SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: () => sheet',
                          "  SpreadsheetApp: { getActiveSpreadsheet: () => ({ getSheetByName: n => (n === 'Заявки' ? sheet : (n === 'Журнал' && logRows.length ? logSheet : null)), insertSheet: () => logSheet, getUrl: () => 'https://sheet.example/', getName: () => 'Test' }) },"),
        lambda t: exact(t, 's.version === 2', 's.version === 3'),
        lambda t: exact(t, "console.log('notify script ok');", SCRIPT_V3_TESTS.lstrip('\n') + "console.log('notify script ok');"),
        lambda t: exact(t, '''"'save_settings'", "'tg_find'", "'test_notify'"):''',
                           '''"'save_settings'", "'tg_find'", "'test_notify'", "'diagnose'", "'set_enabled'", "'clear_log'", 'tryLock', 'LOG_SHEET', 'errText_'):'''),
        lambda t: exact(t, "'scriptWithPassword', 'inboxUrlFrom'):",
                           "'scriptWithPassword', 'inboxUrlFrom', 'requestsTools', 'inboxDiagnose', 'inboxDisconnect', 'inboxReset', 'logText', 'inbox-diagnostics-v1'):"),
        lambda t: before(t, 'def check_inbox(builder, destination):', PANEL_TOOLS_CHECK),
        lambda t: exact(t, "assert result.returncode == 0, f'inboxUrlFrom: {result.stderr[:600]}'",
                           "assert result.returncode == 0, f'inboxUrlFrom: {result.stderr[:600]}'" + PANEL_TOOLS_RUN.rstrip('\n')),
    ]),
    ('README.md', 'inbox-diagnostics-v1', [append_doc(README_ADD)]),
    ('docs/DASHBOARD.md', 'inbox-diagnostics-v1', [append_doc(DASHBOARD_ADD)]),
    ('docs/HOSTING.md', 'spaceship-cname-help-v1', [append_doc(HOSTING_ADD)]),
    ('docs/CONCEPT.md', 'inbox-diagnostics-v1', [append_doc(CONCEPT_ADD)]),
    ('.gitignore', '.backup-inbox-diagnostics/', [gitignore_add]),
]


def main():
    if not (ROOT / 'scripts' / 'build.py').exists():
        print('Запустите скрипт из корня репозитория (там, где папки scripts/ и admin/).')
        return 2
    # 1. Всё проверяем в памяти: либо все правки находят своё место, либо ничего не пишется.
    planned, problems, skipped = {}, [], []
    for path, marker, ops in FILES:
        target = ROOT / path
        if not target.exists():
            problems.append(f'{path}: файла нет')
            continue
        text = target.read_text(encoding='utf-8')
        if marker in text:
            skipped.append(path)
            continue
        try:
            for number, op in enumerate(ops, 1):
                text = op(text)
        except Miss as error:
            problems.append(f'{path}, правка {number}: {error}')
            continue
        planned[path] = text
    if problems:
        print('НИЧЕГО НЕ ЗАПИСАНО. Правки не нашли своё место:')
        for item in problems:
            print('  -', item)
        print('Скорее всего, файлы изменились после снимка. Пришлите свежий repomix.')
        return 1

    # 2. Бэкап и запись.
    changed = []
    for path, text in planned.items():
        target = ROOT / path
        if target.read_text(encoding='utf-8') == text:
            continue
        copy = BACKUP / path
        if not copy.exists():
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, copy)
        target.write_text(text, encoding='utf-8')
        changed.append(path)
    if changed:
        print('Изменено файлов:', len(changed))
        for path in changed:
            print('  +', path)
        print('Оригиналы сохранены в', BACKUP.name + '/')
    else:
        print('Уже применено: изменений 0.')
    if skipped:
        print('Пропущено как уже готовое:', ', '.join(skipped))

    # 3. Сборка и тесты: честный итог.
    ok = True
    for name in ('build.py', 'test_build.py'):
        print(f'\n$ python3 scripts/{name}')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts' / name)], cwd=ROOT)
        if result.returncode != 0:
            ok = False
            print(f'ОШИБКА: scripts/{name} завершился с кодом {result.returncode}. Сайт не опубликуется, пока это не исправлено.')
            break
    print('\n' + ('Готово: сборка и тесты прошли.' if ok else 'Сборка или тесты НЕ прошли (см. выше). Пришлите мне вывод.'))
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
