# ApproveAccept

ApproveAccept applies deterministic spend rules when any agent asks to buy something. An owner can grant a named agent a bounded allowance with a merchant list, per-purchase limit, monthly limit, and expiry. Matching one-time purchases proceed automatically. Anything outside the allowance becomes one clear phone decision. A category allowlist still blocks disallowed requests.

The demo uses PayPal sandbox only. It never needs live credentials or real money.

## The idea: your agents buy, PayPal holds, you decide

Claude Code, GrokBot or any agent you name gets its own key. It sends a purchase (a domain, a hosting plan, a flight) over MCP or HTTP. ApproveAccept creates the PayPal Sandbox order at once, labelled with the agent's name, for example "Domain name .com, 1 year - sent by Claude Code", and holds the money. You set each agent's limits: an amount paid automatically per item, a monthly allowance and allowed categories. Inside them, the hold is captured. Over them, it waits in your inbox for Face ID. A category you did not allow stops before PayPal.

## Try it: pick one path

New here? `docs/ONBOARDING.md` says what runs, what is written and what needs a PayPal Sandbox account or an iPhone. To let Claude Code set it up for you: `cp -r skill/approveaccept ~/.claude/skills/`.

You need Python 3.11 or newer and git. Both paths use the same address and pages:

- `http://127.0.0.1:8780/inbox`: your agents' requests. **Start here.**
- `http://127.0.0.1:8780/journey`: Surprise me, the fun shopping journey (also the third tab of the inbox).

### Path A. No PayPal account (about 2 minutes)

A labelled local stand-in replaces PayPal. Every payment ID starts with `SUB`, and no network payment is made.

1. Clone and enter the repository:
   ```sh
   git clone https://github.com/Morkeeth/approveaccept.git && cd approveaccept
   ```
2. Start the app and leave it running. It prints your owner key:
   ```sh
   ./journey.sh --no-paypal
   ```
3. Open `http://127.0.0.1:8780/inbox` and sign in with the owner key from step 2.
4. In a second terminal, in the same folder, let two agents buy:
   ```sh
   python3 connect/demo_agents.py
   ```
   On the Requests tab: Claude Code's domain (EUR 12) and hosting plan (EUR 20) are paid inside its EUR 30 limit. GrokBot's flight (EUR 89) is over its EUR 50 limit and waits for you.
5. Decide on the flight: **Deny** releases the hold. **Raise GrokBot's limit for next time** changes the rule for its next requests only; the flight stays held until you approve or deny it. **Approve with Face ID** needs an HTTPS address (see "Face ID on your phone").
6. Open the **Surprise me** tab, tap **Surprise me**, swipe and tap **Yes, this one**.

### Path B. PayPal Sandbox with your own keys (about 5 minutes)

1. Clone and enter the repository, as in path A.
2. Make a free account at [developer.paypal.com](https://developer.paypal.com). Open Apps & Credentials, switch to **Sandbox**, and copy the client ID and secret of the default app. Never use Live keys.
3. Bring your own keys:
   ```sh
   python3 connect/byok.py
   ```
   Paste the two keys; the input is hidden. Press Enter at the merchant ID prompt to look it up. Optionally paste an Anthropic API key so Claude ranks the Surprise me ideas (run `pip install anthropic` first), or press Enter to skip. The keys are checked with PayPal Sandbox and saved in one file outside this repository, `~/.config/approveaccept/sandbox.env`, readable only by you. Your owner key is shown once on the terminal and also saved in that file.
4. Start the app and leave it running:
   ```sh
   ./journey.sh
   ```
5. Open `http://127.0.0.1:8780/inbox` and sign in with the owner key from step 3.
6. In a second terminal, in the same folder, run `python3 connect/demo_agents.py`. The two paid items are real PayPal Sandbox captures; each order description names the agent that sent it.
7. Decide on the held flight as in path A, then try **Surprise me**. With a model key, Claude ranks the ideas; it writes no free text, so each reason is your own words plus the product's own title or tags, and an answer citing anything else is thrown away. Without a key, the screen says "No AI" and uses the local matcher.

Payments are test payments between your own Sandbox accounts. No retailer order is placed, and there is no live PayPal endpoint in this code.

### Connect your own agent

On the Agents tab of `/inbox`, add an agent by name and copy its key (shown once). Run `mcp_server.py` with `APPROVEACCEPT_AGENT_TOKEN` set to that key and `AA_URL` set to this app: `http://127.0.0.1:8780` on the same machine, or the HTTPS address of the public front service (`./start-host.sh`) for an agent elsewhere. The agent's name comes from its key, so it cannot buy as another agent. Set its limits and categories on the same tab.

### Face ID on your phone

Passkeys need an HTTPS address. Start the public front service with `./start-host.sh`, give it an HTTPS address through a host or a tunnel you choose, and set `APPROVEACCEPT_PUBLIC_BASE_URL` and `APPROVEACCEPT_PASSKEY_ORIGIN` to that exact address before starting. See "Prepare a hosted sandbox demo". Without HTTPS, held purchases stay held, not paid.

## What works

- AI agents request any named purchase through four local MCP tools: spending policy, request, status, and wait for decision.
- Code, not the language model, checks categories and agent allowances (per purchase and per month). The legacy catalog path also applies per-merchant and daily automatic limits.
- A request outside the automatic limits gets a one-use, expiring phone approval link.
- A human Approve action captures the PayPal Sandbox authorization from that phone page.
- A human Refuse action voids the authorization, so no money moves.
- A paid purchase can be undone: the owner taps Refund twice, and PayPal refunds the whole capture (Payments v2). It happens once, only after a capture, never from an agent or an MCP tool. A pending or uncertain refund stays paid in totals. Tap the row and Check refund later to read the capture status; this never sends a second refund. The allowance is not refilled, the same rule as a void.
- An allowed request inside both automatic limits can capture without interrupting the owner.
- An owner can grant or revoke a named agent allowance and see its remaining monthly amount.
- A purchase outside an allowance goes to the phone instead of silently widening the allowance.
- Every phone approval requires a WebAuthn assertion with user verification. On iPhone, this is Face ID.
- The five-minute WebAuthn challenge contains the exact purchase ID, EUR amount, merchant, expiry, and nonce. A different, changed, expired, or replayed purchase stays held.
- Eight published incident patterns are replayed as hostile purchase requests. All eight are refused before a PayPal order is created.
- An independent record through PayPal's own MCP server: `python3 connect/paypal_mcp_record.py` reads every order back with `@paypal/mcp` (pinned 1.8.1, `get_order` only, needs node). It checks PayPal's status, amount and the agent's name in the order against the inbox, then prints the totals for each agent. The Sandbox token goes to the MCP server through its environment only.

## Agent shopping request and owner review

An authenticated agent first calls `spending_policy` with its assigned name, then `request_purchase` with the item, merchant, euro cents, category, task and reason. It may include an HTTPS `product_url`. `purchase_status` and `wait_for_decision` return that same request ID and the exact policy snapshot used at request time. The owner dashboard and phone page show the matching context, including the limit that caused review. Later allowance changes do not rewrite that explanation.

Merchant names, prices, task text and source links in generic requests come from the agent. They are not independently verified. Every generic sandbox payment uses the one configured sandbox payee ID, shown on the review screen. The generic path does not verify that the item matches the task; the historical catalog path has its own item binding. This is a sandbox request and decision prototype, with no real seller checkout or fulfilment.

In substitute mode, a real model may exercise the MCP interface while all payment references remain `SUB` prefixed. An automated browser refusal is a test action, not the owner's decision. No physical phone approval or PayPal call is established by that test.

## Other entry points (advanced)

`./journey.sh` is the supported way to start. Running `app.py` directly is for development:

- `LEASH_V2_SUBSTITUTE=1 APPROVEACCEPT_OWNER_TOKEN=<32 or more characters> python3 -B app.py` serves the local stand-in on port 8753.
- `python3 -B app.py` serves PayPal Sandbox on port 8752. It reads `APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID`, `APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET`, `APPROVEACCEPT_PAYPAL_SANDBOX_MERCHANT_ID` and `APPROVEACCEPT_OWNER_TOKEN` from the environment; `./journey.sh` loads them from the configuration saved by `connect/byok.py`.
- `./demo.sh` starts the older guided judge path on port 8879 with the local stand-in.
- For a demo video without third-party names on screen: start the app with `APPROVEACCEPT_VIDEO_NAMES=1` (the AI label says "an AI model") and run `python3 connect/demo_agents.py --video-names` (agents named "Coding agent" and "Travel agent", also in the PayPal order descriptions).

With the local stand-in and a fixed HTTPS origin, the phone page shows a one-time passkey enrolment link; `signer_service.py` is only a labelled HMAC test double and is not connected to the app. The spend decision is in `spend_rules.py`; the PayPal-shaped state machine is in `leash.py`.

## Run the checks

```sh
python3 -B -m unittest discover
node design/check-tokens.cjs
node design/check-contrast.cjs
node design/check-stamps.cjs
python3 hosting_check.py
```

The Python checks run against the local stand-in inside a temporary data folder. They need no PayPal account and do not touch any Sandbox data.

Optional dev dependency: [Playwright](https://playwright.dev) (`npm install playwright`, or `pip install playwright` and then `playwright install chromium`). It is used by the browser tests, the recording scripts and the rendered layer of `check-stamps.cjs`. Without it, `check-stamps.cjs` checks the HTML source only and prints `SKIPPED rendered check`. The app itself needs only the Python standard library; `anthropic` is needed only for AI ranking.

## Prepare a hosted sandbox demo

Public visitors get a synthetic read-only walkthrough. The owner signs in to the private queue with a separate access key. Remote agents use a different bearer key bound to their exact agent name; they cannot change owner permissions or read another agent’s requests. See `ENVIRONMENT.md` for setup.

`./start-host.sh` starts the sandbox API on an internal port and the judge-facing design service on `$PORT`. The root service and the internal API each expose `/health`. A public demo runs on Render at https://approveaccept.onrender.com, deployed from `render.yaml` in substitute mode: no PayPal secrets are on the host and every payment ID is marked `SUB`. The PayPal Sandbox run is local, shown in the video. See `ENVIRONMENT.md` for environment-variable names and purposes. Sandbox remains the default and live money remains off.

The public judge path is in `JUDGE-PATH.md`.

Expose only the public service from `start-host.sh`; the direct `app.py` API is trusted loopback infrastructure and must not be exposed by a tunnel. For a phone-reachable approval link, set both `APPROVEACCEPT_PUBLIC_BASE_URL` and `APPROVEACCEPT_PASSKEY_ORIGIN` to the exact HTTPS origin supplied by a tunnel or host before starting the app. The relying-party ID comes from this configured origin, never from the request Host header. ApproveAccept does not open a tunnel itself.

For a full Sandbox run with webhooks, `connect/prepare_fresh_run.py` creates a fresh private data directory and ports, an agent-only MCP key, and one exact HTTPS origin. When `LEASH_V2_WEBHOOK_PORT` and this run's `LEASH_V2_WEBHOOK_ID` are set, the public service forwards only `/webhooks/paypal` to the loopback listener for PayPal signature verification. `connect/register_fresh_webhook.py` creates a new Sandbox registration without deleting an older one. The public service never exposes the internal API port.

## Architecture

- `app.py`: generic request API, expiring phone links, PayPal Sandbox calls, receipts, and local state.
- `spend_rules.py`: category allowlist plus per-merchant and daily automatic limits.
- `passkeys.py`: WebAuthn enrolment and purchase-bound assertion verification using the configured HTTPS origin.
- `signer_service.py`: disconnected HMAC test double retained for test comparison only.
- `leash.py`: sandbox-only payment policy, caps, state transitions, and PayPal adapter.
- `index.html`: generic dashboard and one named demo scenario.
- `phone.html`: phone-sized approval and refusal page.
- `mcp_server.py`: local MCP bridge for agent purchase requests and decision status.
- `telegram_approve.py`: optional test-bot buttons that call the same decision path.
- `test_build.py`: substitute-mode tests for purchases, webhooks, MCP, Telegram, design rules, and incident refusal.
- `design/`: frozen visual tokens and automated contrast and no-stamp checks.

## Safety boundary

The agent can request and observe. It cannot make a manual approval decision or change a request after it enters the system. Deterministic rules may allow capture without interruption. Otherwise the expiring phone link requires a valid owner passkey assertion before capture. The PayPal payee is bound by the server. Live credentials, live payments, deployment, tunnels, public hosting, and a real-device test are outside this repository's current state.

## Licence

MIT. See `LICENSE`.


### Internal API access

Loopback does not grant owner access. Set `APPROVEACCEPT_OWNER_TOKEN` (at least 32 characters) for owner sign-in; the dashboard uses an expiring HttpOnly session. Configure a different `APPROVEACCEPT_AGENT_TOKEN` and `APPROVEACCEPT_AGENT_NAME` for a connector: it can request purchases and read only its own policy/status. Missing configuration fails closed, including in substitute mode. Private API reads require authentication. Every API POST requires an explicit `Origin` matching the configured public base URL or the internal localhost/127.0.0.1 port; absent and `null` origins are refused, even with a bearer token. The MCP client supplies its configured API URL as Origin. The public proxy checks the caller before forwarding the appropriate role and internal Origin. Phone capability routes retain purchase-bound token/passkey validation. Provider webhooks remain on their separate signature-verifying listener. Never put access tokens in source or URLs.

Purchase intent keys remain bound to the original details. A confirmed spending-rule refusal before provider effects may be retried with the same key after an owner policy change; it is re-evaluated under current rules. Unknown provider outcomes and pre-existing pending claims remain closed to replacement payments. Completed purchases return their original result. Historical keys are not cleared or guessed safe.

## Find real products with Channel3

Before an agent asks to buy, it can search real retailer offers. The MCP tool `find_products` calls
[Channel3](https://trychannel3.com) product search and returns title, brand, merchant, price and
availability. It is discovery only: it never pays and never sets a payee. The agent then calls
`request_purchase` with the item it found, and the human approves as usual while PayPal holds the money.

Set `CHANNEL3_API_KEY`, then try it from the shell: `python3 channel3_search.py travel adapter`.
