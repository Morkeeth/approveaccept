# ApproveAccept

ApproveAccept applies deterministic spend rules when any agent asks to buy something. An owner can grant a named agent a bounded allowance with a merchant list, per-purchase limit, monthly limit, and expiry. Matching one-time purchases proceed automatically. Anything outside the allowance becomes one clear phone decision. A category allowlist still blocks disallowed requests.

The demo uses PayPal sandbox only. It never needs live credentials or real money.

## The core flow: your agents buy, PayPal holds, you decide

Claude Code, GrokBot or any agent you name gets its own key. It sends a purchase (a domain, a hosting plan, a flight) over MCP or HTTP. ApproveAccept creates the PayPal Sandbox order at once, labelled with the agent's name, for example "Domain name .com, 1 year - sent by Claude Code", and holds the money. You set each agent's limits on the Agents tab: an amount paid automatically per item, a monthly allowance and allowed categories. Inside them, the hold is captured. Over them, it waits in your inbox for Face ID. A category you did not allow stops before PayPal.

After step 0 below, open `http://127.0.0.1:8780/inbox`, then run `APPROVEACCEPT_OWNER_TOKEN=<owner key> AA_URL=http://127.0.0.1:8780 python3 connect/demo_agents.py` to watch two agents buy.

## Try it in 60 seconds: tap a mood, swipe, say yes

You need Python 3.11 or newer and a free PayPal Developer account.

**Step 0. Bring your own PayPal Sandbox keys.** In [developer.paypal.com](https://developer.paypal.com) open Apps & Credentials, switch to **Sandbox**, and copy the client ID and secret of your default app. Then run:

```sh
python3 connect/byok.py
```

Paste the two keys when asked; the input is hidden. Press Enter at the merchant ID prompt to look it up. Then paste an Anthropic API key so a model ranks the ideas, or press Enter to skip. With a key, `pip install anthropic` first. The script checks the keys with PayPal Sandbox. It saves them in one file outside this repository, `~/.config/approveaccept/sandbox.env`, readable only by you. It shows your owner sign-in key once on the terminal. Nothing is committed, logged or sent anywhere except PayPal Sandbox. There is no live PayPal endpoint in this code.

**Step 1. Start the journey.**

```sh
./journey.sh
```

Open `http://127.0.0.1:8780/journey` and sign in with the owner key from step 0. Tap **Surprise me**, swipe the three ideas and tap **Yes, this one**.

- With a model key, Claude ranks the ideas. It writes no free text: each reason is your own words plus the product's own title or tags, and an answer that cites anything else is thrown away. Without a key, or if the model fails, the screen says "No AI" and uses the local matcher.
- Inside your per-purchase limit (default EUR 50), it is bought at once in PayPal Sandbox and you get a receipt with the PayPal capture ID.
- Over the limit, it becomes one Face ID decision. Nothing is charged until you approve. Face ID needs an HTTPS origin (see below); without one the purchase stays held, not paid.

Payments are test payments from your own Sandbox account to your own Sandbox business account. No retailer order is placed.

**Connect your agent.** Step 0 also creates an agent key, saved in the same file under the name `Judge agent`. Point any MCP client at `mcp_server.py` with that key and `AA_URL=http://127.0.0.1:8780`. Its requests go through the same spend rules; grant it an allowance from the owner dashboard at `/` to let it buy automatically.

No PayPal account? `LEASH_V2_SUBSTITUTE=1 APPROVEACCEPT_OWNER_TOKEN=<any 32 or more characters> python3 -B app.py` serves the same `/journey` on port 8753 against labelled local fakes, with no PayPal call.

## What works

- AI agents request any named purchase through four local MCP tools: spending policy, request, status, and wait for decision.
- Code, not the language model, checks the category, per-merchant automatic limit, and daily automatic limit.
- A request outside the automatic limits gets a one-use, expiring phone approval link.
- A human Approve action captures the PayPal Sandbox authorization from that phone page.
- A human Refuse action voids the authorization, so no money moves.
- An allowed request inside both automatic limits can capture without interrupting the owner.
- An owner can grant or revoke a named agent allowance and see its remaining monthly amount.
- A purchase outside an allowance goes to the phone instead of silently widening the allowance.
- Every phone approval requires a WebAuthn assertion with user verification. On iPhone, this is Face ID.
- The five-minute WebAuthn challenge contains the exact purchase ID, EUR amount, merchant, expiry, and nonce. A different, changed, expired, or replayed purchase stays held.
- Eight published incident patterns are replayed as hostile purchase requests. All eight are refused before a PayPal order is created.

## Agent shopping request and owner review

An authenticated agent first calls `spending_policy` with its assigned name, then `request_purchase` with the item, merchant, euro cents, category, task and reason. It may include an HTTPS `product_url`. `purchase_status` and `wait_for_decision` return that same request ID and the exact policy snapshot used at request time. The owner dashboard and phone page show the matching context, including the limit that caused review. Later allowance changes do not rewrite that explanation.

Merchant names, prices, task text and source links in generic requests come from the agent. They are not independently verified. Every generic sandbox payment uses the one configured sandbox payee ID, shown on the review screen. The generic path does not verify that the item matches the task; the historical catalog path has its own item binding. This is a sandbox request and decision prototype, with no real seller checkout or fulfilment.

In substitute mode, a real model may exercise the MCP interface while all payment references remain `SUB` prefixed. An automated browser refusal is a test action, not the owner's decision. No physical phone approval or PayPal call is established by that test.

## Run locally without PayPal credentials

You need Python 3.11 or newer and the OpenSSL command-line tool for passkey verification. The substitute mode uses local fake PayPal-shaped responses and marks every reference with `SUB`.

```sh
LEASH_V2_SUBSTITUTE=1 python3 -B app.py
```

Passkeys require a public HTTPS origin. Set the same fixed origin used by the phone page before starting the local substitute:

```sh
APPROVEACCEPT_PUBLIC_BASE_URL=https://approve.example.test \
APPROVEACCEPT_PASSKEY_ORIGIN=https://approve.example.test \
LEASH_V2_SUBSTITUTE=1 python3 -B app.py
```

The owner dashboard shows a one-time enrolment link on first use. After enrolment, the phone page invokes the platform authenticator for every manual approval. `signer_service.py` remains only as a labelled HMAC test double and is not connected to the app.

Clone the repository with its Code button, enter the cloned folder, and run the command above.

Open `http://127.0.0.1:8753`.

For the guided judge path, use one command from this repository:

```sh
./demo.sh
```

Then open `http://127.0.0.1:8879`. The guided button creates one automatic purchase, one purchase held for Face ID, and one blocked request through the normal request API. This local route uses the labelled substitute. It makes no PayPal call and cannot prove a phone passkey.

The spend decision is in `spend_rules.py`; the PayPal-shaped state machine remains in `leash.py`. The substitute path needs no sibling repository and no credentials.

## Run the checks

```sh
python3 -B -m unittest -v test_spend_rules test_build test_viewport test_hosted_runtime
node design/check-tokens.cjs
node design/check-contrast.cjs
node design/check-stamps.cjs
python3 hosting_check.py
```

The Python checks run in substitute mode inside a temporary data folder. They do not touch the PayPal sandbox database.

## Prepare a hosted sandbox demo

Public visitors get a synthetic read-only walkthrough. The owner signs in to the private queue with a separate access key. Remote agents use a different bearer key bound to their exact agent name; they cannot change owner permissions or read another agent’s requests. See `ENVIRONMENT.md` for setup.

`./start-host.sh` starts the sandbox API on an internal port and the judge-facing design service on `$PORT`. The root service and the internal API each expose `/health`. `Dockerfile` and `render.yaml` are local deployment preparation only; nothing has been deployed. See `ENVIRONMENT.md` for environment-variable names and purposes. Sandbox remains the default and live money remains off.

The public judge path is in `JUDGE-PATH.md`.

Expose only the public service from `start-host.sh`; the direct `app.py` API is trusted loopback infrastructure and must not be exposed by a tunnel. For a phone-reachable approval link, set both `APPROVEACCEPT_PUBLIC_BASE_URL` and `APPROVEACCEPT_PASSKEY_ORIGIN` to the exact HTTPS origin supplied by a tunnel or host before starting the app. The relying-party ID comes from this configured origin, never from the request Host header. ApproveAccept does not open a tunnel itself.

For a full Sandbox run with webhooks, `connect/prepare_fresh_run.py` creates a fresh private data directory and ports, an agent-only MCP key, and one exact HTTPS origin. When `LEASH_V2_WEBHOOK_PORT` and this run's `LEASH_V2_WEBHOOK_ID` are set, the public service forwards only `/webhooks/paypal` to the loopback listener for PayPal signature verification. `connect/register_fresh_webhook.py` creates a new Sandbox registration without deleting an older one. The public service never exposes the internal API port.

## PayPal sandbox demo

The sandbox mode reads its client ID and secret from macOS Keychain through the payment adapter. A hosted copy may read the same sandbox-only values from its secret manager. No credential belongs in this repository.

```sh
python3 -B app.py
```

Open `http://127.0.0.1:8752`.

The sandbox is the hackathon and judge path. Live money is out of scope for this repository.

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
