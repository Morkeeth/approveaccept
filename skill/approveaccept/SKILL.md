---
name: approveaccept
description: Set up and run the ApproveAccept demo, where AI agents ask to buy things and the owner's spend rules and Face ID decide, with PayPal Sandbox or a local stand-in. Use when the person asks to try ApproveAccept, wants to see agent spending limits in action, or asks how an agent could pay for something with owner approval.
---

# ApproveAccept: set up and click the demo

You set up the no-PayPal demo for the person, let two demo agents buy, and show them where to click. No account and no real money. Never ask for, type or paste real PayPal, card, bank or wallet credentials. Never create an account for them.

## Steps

1. **Look before installing.** Run:
   ```
   python3 -c 'import sys; print(sys.version_info[:2])'
   git --version
   lsof -ti tcp:8780 -sTCP:LISTEN
   ls ~/.config/approveaccept 2>/dev/null
   ```
   Done when you can say: the Python version (3.9 or newer ran the demo; the README asks for 3.11), git is present, port 8780 is free (the `lsof` line prints nothing), and whether an earlier ApproveAccept setup exists. If port 8780 is taken, stop and tell them what holds it.

2. **Say what will happen, and get a yes.** Tell them, in these words or close: it clones a public repository; it writes one owner key file and two small databases in `~/.config/approveaccept/`; it serves a page on 127.0.0.1:8780 only; in this mode no payment call leaves the machine and every payment ID starts with `SUB`. Done when they say yes.

3. **Get the code.** In the folder they choose (default `~/CODE`):
   ```
   git clone https://github.com/Morkeeth/approveaccept.git
   cd approveaccept
   ```
   Done when `ls journey.sh connect/demo_agents.py` lists both files.

4. **Start the app.**
   ```
   ./journey.sh --no-paypal > /tmp/approveaccept.log 2>&1 &
   curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8780/inbox
   ```
   Retry the `curl` for a few seconds. Done when it prints `200` and the log's last line says `PayPal: SUBSTITUTE, no network`. Do not print the owner key into the chat. Tell them it is in `~/.config/approveaccept/no-paypal.env` and in the first lines of `/tmp/approveaccept.log`.

5. **Let the demo agents buy.**
   ```
   python3 connect/demo_agents.py
   ```
   Done when it prints three JSON lines: two with `"state": "captured"` (Claude Code, EUR 12 and EUR 20) and one with `"state": "authorized"` (GrokBot, EUR 89, held).

6. **Report and hand over the clicks.** Open http://127.0.0.1:8780/inbox for them. Tell them: sign in with the owner key; the two paid items were inside Claude Code's EUR 30 limit; the flight is over GrokBot's EUR 50 limit and waits for them; they can press Deny to release it, Raise to change the rule for next time, and try the Surprise me tab. Say plainly that Approve with Face ID needs an HTTPS address and an iPhone or passkey device, and that real Sandbox payments need their own free PayPal developer account (README, Path B). Done when all of this is said.

7. **Stop and undo when asked.**
   ```
   lsof -ti tcp:8780 -sTCP:LISTEN | xargs kill
   rm -rf ~/.config/approveaccept
   ```
   Done when the `lsof` line from step 1 prints nothing again. Remove the cloned folder only if they ask.

## Reference

- To connect their own agent: Agents tab, add a name, copy the key once, then run `AA_URL=http://127.0.0.1:8780 APPROVEACCEPT_AGENT_TOKEN=<key> python3 -B mcp_server.py` as an MCP server. Do not use the repository's `.mcp.json`; it needs a prepared run file.
- Rules are code, not a model. The agent's item, merchant and price are not verified; the payee is set by the server.
- Full page: `docs/ONBOARDING.md`.
