# ApproveAccept: getting started

## What it is

A local app that lets an AI agent ask to buy something, and lets your spend rules and your Face ID decide, with PayPal Sandbox test money only. It is for people who run coding or assistant agents and want to see what "my agent may spend, but only inside limits I set" looks like before any real money is involved.

## What happens when you run it

There are two modes. The no-PayPal mode is the one anyone can click in two minutes.

| | No-PayPal mode (`./journey.sh --no-paypal`) | PayPal Sandbox mode (`./journey.sh`) |
|---|---|---|
| Reads | Your owner key file. The `APPROVEACCEPT_ANTHROPIC_API_KEY` variable, if your shell sets it. The Keychain items described below the table. | Your Sandbox keys file. An Anthropic key if you saved one. |
| Writes | `~/.config/approveaccept/no-paypal.env` (your owner key, mode 600) and `~/.config/approveaccept/data-no-paypal/` (`state.db`, `spend.db`). Nothing inside the repository. | `~/.config/approveaccept/sandbox.env` (keys, mode 600, written by `connect/byok.py`) and `~/.config/approveaccept/data/`. |
| Leaves your machine | No payment call. Every payment ID starts with `SUB` (`app.py`, `SUBSTITUTE`). The shop search on Surprise me is switched off in this mode (`shopping.py`). The server listens on `127.0.0.1:8780` only (`app.py`, last line). Anthropic is called only if that variable is set and the `anthropic` package is installed (`catalog_ai.py`). | Calls to `api-m.sandbox.paypal.com` (`leash.py`, `connect/byok.py`). With a saved Anthropic key and the `anthropic` package, Surprise me sends product titles, tags, prices and your stated preferences to Anthropic (`catalog_ai.py`). There is no live PayPal address anywhere in the code. |

One more outbound path exists in both modes, and it is off by default. If a Telegram test bot token and chat ID are stored in the macOS Keychain under the account `leash-sandbox`, the app sends held requests to `api.telegram.org` (`telegram_approve.py`). The server then prints `Telegram approvals on`. If you do not see that line, it is off.

**What you gain.** You watch the rules work on three purchases. In a clean test run on 8 November 2026 (no-PayPal mode, fresh clone at `a641706`), the demo agents sent three requests. Claude Code's domain (EUR 12) and hosting plan (EUR 20) were inside its EUR 30 limit and were paid at once (`SUB-CAPTURE-...`). GrokBot's flight (EUR 89) was over its EUR 50 limit and waited in the inbox. Deny released the hold and moved it to Stopped. In Sandbox mode the same paid items become real Sandbox captures with the agent's name in the order. The record from 2 November 2026 in `proof/core-flow-20261102/sandbox-readback.json` shows PayPal reporting the order `COMPLETED` with the description "Domain name .com, 1 year - sent by Claude Code".

## Quick start

Needs: macOS or Linux, git, Python 3 (the README asks for 3.11; the no-PayPal path also ran on the stock macOS Python 3.9.6 in this test). No packages.

**Let your agent do it.** From the cloned repository, copy the skill into Claude Code and ask "show me the ApproveAccept demo":

```
cp -r skill/approveaccept ~/.claude/skills/
```

It checks first, says what will happen, waits for your yes, runs the demo, and tells you how to stop and undo it.

**Or by hand, no PayPal account (about 2 minutes):**

```
git clone https://github.com/Morkeeth/approveaccept.git
cd approveaccept
./journey.sh --no-paypal
```

Leave it running. It prints your owner key. In a second terminal, in the same folder:

```
python3 connect/demo_agents.py
```

Then click:

1. Open http://127.0.0.1:8780/inbox and paste the owner key.
2. Requests tab: two paid items from Claude Code, one held flight from GrokBot.
3. Press **Raise GrokBot's limit to EUR 89 for next time**. The note says the flight is still held. The rule changes for later requests only.
4. Press **Deny**. The flight moves to Stopped: "You denied it. The PayPal hold was released."
5. Open the **Surprise me** tab, tap **Surprise me**, then **Yes, this one**. You get a simulated receipt. It says "No AI" unless you added a model key.
6. Agents tab: add your own agent by name and copy its key (shown once).
7. Stop with Ctrl-C.

**What needs more than a laptop.** Two steps cannot be done by a stranger with nothing:

- **Real PayPal Sandbox payments** need a free PayPal developer account with Sandbox keys. Run `python3 connect/byok.py`, paste the Sandbox client ID and secret (never Live keys), then `./journey.sh`. See README, Path B.
- **Approve with Face ID** needs an iPhone (or another device with a passkey) and an HTTPS address for the app, from a host or a tunnel you choose. Without HTTPS, pressing Approve gives you a link, and the phone page says "HTTPS setup required. Nothing can be captured yet." The held purchase stays held. See README, "Face ID on your phone". Deny and Raise work without any of this.

**Connect your own agent.** After step 6, point any MCP client at `mcp_server.py`:

```
AA_URL=http://127.0.0.1:8780 APPROVEACCEPT_AGENT_TOKEN=<the agent key> python3 -B mcp_server.py
```

It offers four tools: `spending_policy`, `request_purchase`, `purchase_status`, `wait_for_decision`. In Claude Code, the repository's `.mcp.json` does the same: start Claude Code from this folder with `APPROVEACCEPT_AGENT_TOKEN` set, and it connects to the demo on port 8780. Without a key it still starts, and each tool answers with where to get one.

**Undo the no-PayPal demo:**

```
lsof -ti tcp:8780 -sTCP:LISTEN | xargs kill
rm -rf ~/.config/approveaccept/no-paypal.env ~/.config/approveaccept/data-no-paypal
```

Then delete the cloned folder. If you also ran Path B, `~/.config/approveaccept/sandbox.env` holds your Sandbox keys and `~/.config/approveaccept/data/` its records; remove them only when you mean to.

## Do it yourself instead

No install. You lose the per-agent keys, the inbox, the spend history and the Face ID binding. You keep the idea.

The rule check, in `jq`. Paste a request, get pay, hold or refuse:

```
echo '{"agent":"GrokBot","category":"travel","cents":8900}' | jq -r \
  --argjson limits '{"Claude Code":{"per":3000,"cats":["domain","hosting","database"]},"GrokBot":{"per":5000,"cats":["travel"]}}' '
  ($limits[.agent]) as $l
  | if $l == null then "refuse: unknown agent"
    elif (.category | IN($l.cats[]) | not) then "refuse: category not allowed"
    elif .cents <= $l.per then "pay"
    else "hold: ask the owner" end'
```

This prints `hold: ask the owner`. The same request at 1200 cents from Claude Code in `domain` prints `pay`.

The hold itself is PayPal's own Orders API: create an order with `intent: AUTHORIZE`, then capture the authorization to pay or void it to release. Every call starts with a token:

```
curl -s -u "$CLIENT_ID:$SECRET" -d grant_type=client_credentials https://api-m.sandbox.paypal.com/v1/oauth2/token
```

Only this first call was run for this page, with fake values. It answered `{"error":"invalid_client","error_description":"Client Authentication failed"}`. The create, authorize, capture and void calls need a Sandbox account and were not run here. PayPal documents them under Orders v2 and Payments v2.

## Limits and privacy

- Sandbox only. There is no live PayPal endpoint in this code. Sandbox payments move test money between your own Sandbox accounts. No shop sends you anything.
- The agent supplies the item, merchant, price and reason. ApproveAccept does not check that they are true. It checks them against your rules and sets the payee itself.
- Rules are code (`spend_rules.py`, `app.py`), not a language model. A category you did not allow is refused before any PayPal order.
- A Face ID approval on a real phone over a hosted HTTPS address is not proven in this repository. The README says a real-device test is outside its current state.
- Your owner key and Sandbox keys stay in `~/.config/approveaccept/`, readable only by you. In no-PayPal mode the owner key is printed on the terminal each time the app starts.
- Nothing is deployed. `Dockerfile`, `render.yaml` and `start-host.sh` prepare a hosted demo; none of them has been run on a host.
