"""Find your chat id with the ApproveAccept test bot. Reads the bot token from Keychain, prints only chat ids.
Step: send any message to your bot in Telegram first, then: python3 -B connect/telegram_chat_id.py"""
import json, subprocess, urllib.request

tok = subprocess.check_output(['security', 'find-generic-password', '-a', 'leash-sandbox', '-s',
                               'approveaccept.telegram.bot-token', '-w']).decode().strip()
with urllib.request.urlopen(f'https://api.telegram.org/bot{tok}/getUpdates', timeout=20) as r:
    ups = json.loads(r.read()).get('result', [])
ids = sorted({str(u['message']['chat']['id']) for u in ups if u.get('message')})
print('\n'.join(ids) or 'No messages yet. Send /start to your bot in Telegram, then run this again.')
