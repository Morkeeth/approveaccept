"""Accept or Refuse from Telegram. Each new hold is sent once to one chat with two buttons; a tap calls the
same decide() as the dashboard. Long polling, so no public URL is needed.

Off unless a bot token and a chat ID exist. Keychain, account leash-sandbox:
  approveaccept.telegram.bot-token   (a test bot from @BotFather)
  approveaccept.telegram.chat-id     (your own chat with that bot; taps from anyone else are ignored)
AA_TELEGRAM_API, AA_TELEGRAM_TOKEN and AA_TELEGRAM_CHAT override these for the local fake in test_telegram.py.
"""
import html, json, os, subprocess, threading, time, urllib.request, urllib.error
from datetime import date


def keychain(name):
    try:
        return subprocess.check_output(['security', 'find-generic-password', '-a', 'leash-sandbox', '-s', name, '-w'],
                                       stderr=subprocess.DEVNULL, timeout=3).decode().strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return ''


class Bot:
    def __init__(self, app, api, token, chat):
        self.app, self.base, self.chat, self.offset = app, f'{api.rstrip("/")}/bot{token}/', str(chat), 0

    def call(self, method, **params):
        req = urllib.request.Request(self.base + method, json.dumps(params).encode(), {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read()).get('result')
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError):
            return None  # never log the URL: it carries the token

    def announce(self):
        """Send each authorized hold once."""
        S = self.app.S
        with S.db() as db:
            sent = set(r['pid'] for r in db.execute("SELECT pid FROM telegram_sent"))
            props = {r['id']: dict(r) for r in db.execute('SELECT * FROM proposals')}
        for r in S.book.summary()['requests']:
            p = props.get(r['id'])
            if r['state'] != 'authorized' or r['id'] in sent or not p:
                continue
            text = ask_text(self.app, p, r)
            m = self.call('sendMessage', chat_id=self.chat, text=text, parse_mode='HTML', reply_markup={'inline_keyboard': [[
                {'text': 'Accept ' + self.app.eur(r['cents']), 'callback_data': 'a:' + r['id']}, {'text': 'Refuse', 'callback_data': 'r:' + r['id']}]]})
            if m:
                with S.db() as db:
                    db.execute('INSERT OR IGNORE INTO telegram_sent VALUES (?,?)', (r['id'], m.get('message_id')))
                S.note('Telegram', 'sent', f"Asked in Telegram with Accept and Refuse buttons.", r['id'])

    def updates(self):
        for u in self.call('getUpdates', offset=self.offset, timeout=20, allowed_updates=['callback_query']) or []:
            self.offset = u['update_id'] + 1
            q = u.get('callback_query')
            if q:
                self.tap(q)

    def tap(self, q):
        S, data = self.app.S, str(q.get('data', ''))
        who = str((q.get('from') or {}).get('id', ''))
        if who != self.chat or str(((q.get('message') or {}).get('chat') or {}).get('id', '')) != self.chat:
            S.note('Dashboard', 'refused', 'Telegram tap from an unknown user ignored.')
            return self.call('answerCallbackQuery', callback_query_id=q['id'], text='Not your approval.')
        kind, _, pid = data.partition(':')
        try:
            with self.app.LOCK:
                row = self.app.decide(pid, kind == 'a')
            S.note('Telegram', 'tap', ('Accept' if kind == 'a' else 'Refuse') + ' tapped in Telegram.', pid)
            paid = row['state'] == 'captured'
            done = f"Paid, capture {row['capture_id']}." if paid else 'Refused. Hold released, no money moved.'
            edit = receipt_text(self.app, pid, row, paid)
        except self.app.Refused as exc:
            S.note('Dashboard', 'refused', 'Telegram: ' + str(exc), pid)
            done = str(exc)
            edit = None
        self.call('answerCallbackQuery', callback_query_id=q['id'], text=done[:190])
        msg = q.get('message') or {}
        if msg.get('message_id') and edit:
            self.call('editMessageText', chat_id=self.chat, message_id=msg['message_id'], text=edit, parse_mode='HTML')

    def run(self):
        while True:
            try:
                self.announce()
                self.updates()
            except Exception as exc:  # keep the loop alive; the dashboard keeps working
                self.app.S.note('Telegram', 'error', type(exc).__name__)
                time.sleep(5)


# The message keeps the dashboard's reading order: what and how much, who asks and why, limits, then IDs.
# Telegram draws the skin; HTML parse mode gives bold and code only, so every user-written field is escaped.
def for_line(app, link):
    ev = {e['id']: e for e in app.S.kv('events')}
    wish = {w['id']: w for w in app.S.kv('wish')}
    item = ev.get(link) or wish.get(link)
    if not item:
        return 'for nothing on your list', None
    d = item.get('date') or (ev.get(item.get('event')) or {}).get('date')
    when = date.fromisoformat(d).strftime(', %a %-d %b') if d else ''
    return f"for {html.escape(item['title'])}{when}", item.get('budget')


def ask_text(app, p, r):
    e = html.escape
    for_, budget = for_line(app, p['link'])
    checks = json.loads(p['checks']) if isinstance(p['checks'], str) else p['checks']
    ok = sum(1 for c in checks if c[1])
    limits = f"{ok} of {len(checks)} checks passed" + (f". {app.eur(r['cents'])} of {app.eur(budget)} budget." if budget else '.')
    return (f"<b>{e(p['title'])}</b>\n<b>{app.eur(r['cents'])}</b>, held in PayPal, not paid\n\n"
            f"{e(p['agent'])} asks, {for_}:\n\"{e(p['why'])}\"\n\n{limits}\n"
            f"<code>order {e(r['order_id'])}</code>")


def receipt_text(app, pid, row, paid):
    e = html.escape
    with app.S.db() as db:
        p = dict(db.execute('SELECT * FROM proposals WHERE id=?', (pid,)).fetchone())
    for_, _ = for_line(app, p['link'])
    head = f"<b>{e(p['title'])}</b>\n<b>{app.eur(row['cents'])}</b>, " + ('paid' if paid else 'refused, hold released')
    who = f"You {'accepted' if paid else 'refused'} in Telegram, {time.strftime('%H:%M')}."
    ids = f"<code>capture {e(row['capture_id'])}</code>" if paid else f"<code>order {e(row['order_id'])}</code>"
    return f"{head}\n\n{e(p['agent'])} asked, {for_}.\n{who}\n{ids}"


def start(app):
    token = os.environ.get('AA_TELEGRAM_TOKEN') or keychain('approveaccept.telegram.bot-token')
    chat = os.environ.get('AA_TELEGRAM_CHAT') or keychain('approveaccept.telegram.chat-id')
    if not token or not chat:
        return None
    with app.S.db() as db:
        db.execute('CREATE TABLE IF NOT EXISTS telegram_sent(pid TEXT PRIMARY KEY, message_id INTEGER)')
    bot = Bot(app, os.environ.get('AA_TELEGRAM_API', 'https://api.telegram.org'), token, chat)
    threading.Thread(target=bot.run, daemon=True).start()
    print('Telegram approvals on, chat ' + ('set' if chat else 'missing'), flush=True)
    return bot
