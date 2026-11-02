# Payment-first shopping prototype

ApproveAccept starts with payment permission, then offers Surprise me, Gift ideas and Date ideas. Each idea has a price, an editable-preference explanation and alternatives. Activity and the existing approval/rules controls remain secondary.

This is a Sandbox shopping prototype. Setup saves an allowance, expiry and explicit automatic-purchase opt-in. It does not vault a buyer's payment method. Purchases use the existing configured PayPal Sandbox test funding; substitute mode makes no provider calls. The seven server-owned demo catalog items are not live retailer offers, and capture does not fulfil an order at a retailer. Ranking uses local preference matching, not a new AI model call. The existing AI/MCP paths remain available separately.

Only the owner may access the new web-proxy endpoints. An agent token cannot grant an allowance, read personal shopping setup or choose a purchase. Direct internal API access stays on loopback.

## Quotes, permission and retries

The server freezes each session's offers for 15 minutes. At choice time it rejects client prices, unknown items, expired quotes and changed catalog amounts/titles. Automatic purchases require explicit opt-in and a currently active, unexpired allowance with sufficient per-purchase and monthly budget. The shopping categories are passed by trusted internal code; the generic agent API retains its original category policy.

A request key binds to its mode and automatic flag. A session records its chosen item before any payment action. Retries and concurrent requests return the same completed purchase; changed choices are refused. An interrupted attempt without a recorded result fails closed and needs reconciliation against the existing payment record. It never automatically creates a replacement. This is per-session duplicate protection, not a claim of distributed exactly-once execution or fully automatic crash recovery.

Manual choices create a hold and use the existing purchase-bound owner approval path. The current local proof exercises holds, automatic captures, revoked permissions, expiry, retry races and public/agent denial using synthetic data and the payment substitute. A fresh same-version real Sandbox journey and physical phone approval are still required before submission.

## Local verification

`python3 -B -m unittest test_shopping_flow test_spend_rules test_build test_hosted_runtime -v`

The browser proof needs installed Chrome and Playwright. Run `node test_shopping_browser.cjs /absolute/path/to/worktree /absolute/path/to/existing/proof-folder` with `PLAYWRIGHT_MODULE` set to the installed Playwright module if it is not in the local Node search path. It launches its own temporary substitute API and authenticated web proxy, checks desktop and 390 px journeys, saves before/after screenshots against pinned base 741da01, then stops both owned processes. It does not connect to existing services or payment providers.

## Connected merchant discovery and AI ranking

The optional Merci source reads three fixed first-party product endpoints and their presentment currency. This is a bounded product selection, not a general shopping search. Surprise, gift and date modes use the same first-party catalog; date mode selects supported at-home activities rather than selling a venue, event or booking. The [Shopify Product API](https://shopify.dev/docs/api/ajax/reference/product) defines product JSON and minor-unit prices; currency is verified from the storefront's read-only cart endpoint. Source product links, variant, availability, item price and fetch time are retained in each quote. Shipping and checkout-total adjustments are excluded. Fixed hosts/paths, no redirects and bounded response sizes prevent arbitrary URL access.

An actual subscription Claude CLI ranks these offers against the owner's editable taste text with tools disabled and API credentials removed. The model may cite only existing product identities, nonempty merchant fields and an exact phrase from the supplied preferences. Code composes the explanation from these references. Invalid output or model unavailability refuses the request; there is no silent model fallback or automatic regeneration retry. Source strings are untrusted data and cannot change the payment target or limits.

Selection re-fetches currency, current variant, stock and price. Any mismatch or failed recheck refuses payment before a provider action. An accepted choice tests the corresponding item amount with the configured Sandbox shop, never with Merci. No retailer cart, order, shipping or fulfilment action occurs. The owner-only proxy boundary and existing session retry controls apply unchanged.

## Three grounded modes

Surprise favours a small unexpected use, gift favours a personal giving gesture, and date favours a shared at-home activity. Each offer has a server-authored action tied to its fixed product handle, current product type and mode. AI ranks the product/action pairs against taste references and must cite the exact supplied action ID; it cannot invent a booking, personalisation service, included supplies or another mode's action. The linen pouch has gift/surprise actions but no supported date action, so date mode currently offers the notebook and craft product. Activity suggestions are explicitly separate from merchant facts and from the product being paid for in Sandbox.

## Purchase intent keys

Generic HTTP purchases and MCP purchase requests require a stable `request_key` (12–80 letters, digits, underscores or hyphens). Generate it once per intended purchase and reuse it with the same details on every retry. Keys are scoped by requesting agent and purchase interface. Changed details with an existing key are refused; simultaneous requests cannot create separate operations. Completed retries return the original creation response; use purchase_status for current state. An interrupted or uncertain operation stays claimed and must be reconciled before it can be replaced. The server does not silently generate replacement payment keys.

Shopping choices derive their key from the saved idea session. Follow-up suggestions derive it from the original purchase and suggestion. The guided sample uses fixed keys for its one retained sample journey in a data directory. Historical requests are preserved; their missing client intent keys are not invented retroactively.

## Shared model boundary

Legacy proposal generation and merchant ranking both use llm_launcher.run_json. It inherits only runtime/locale variables, runs from a fresh temporary directory, disables tools and MCP, disables slash commands and attachment expansion, disables hooks and automatic memory, and never returns provider stderr to a caller. App, owner, Telegram, payment and API credentials are not inherited. Existing subscription authentication uses the CLI's own stored login. The installed CLI's bare mode only permits API-key authentication, so it is intentionally not used: hooks are disabled explicitly with the documented per-run settings instead (https://code.claude.com/docs/en/hooks#disable-or-remove-hooks). Failed calls do not trigger a retry or an alternate paid provider.
## Alternatives reel

Alternatives use a native horizontal scroll-snap reel with a next-card preview. Phone users can swipe; desktop users can use Previous/Next, numbered options or Left/Right/Home/End while the reel has focus. Reduced-motion preferences disable smooth scrolling. There is no autoplay. Each card retains its own product, reason, action, source and quote age. Purchasing sends that card's SKU, freezes every choice while pending, and records the selected card across the reel. Expired quotes cannot be chosen in the interface; the server still owns revalidation.

`node test_alternatives_reel.cjs <absolute-worktree> <proof-folder> [retained-three-mode-proof-folder]` uses installed Chrome, an owned payment-substitute API and no messaging startup. It checks real touch input, keyboard, buttons, numbered options and a real substitute capture of the second option. Optional recorded merchant/AI sessions are read from the prior proof database and rendered with a visible replay label; they do not make new merchant, AI or provider calls. `REEL_BASELINE=1` pins the served HTML to5c36e40 and proves the missing-track failure without changing that commit or shared files.

## Buyer return, 30 October

Each Sandbox buyer return now carries a random, hashed-at-rest, 30-minute capability bound to the stored purchase and order. A valid return works without the owner cookie, through both the loopback API and the public ingress. The public return uses APPROVEACCEPT_PUBLIC_BASE_URL when configured; no tunnel or host is created by this change. The proxy never adds owner credentials for this route. Old bare-purchase-ID returns are refused, including when the caller is signed in as owner. An order ID returned by PayPal must match the bound order when present; the server always reads the stored order from the provider and verifies its identity, amount, intent, payee and APPROVED status before authorization.

A return can authorize the already approved order once, but cannot capture funds or bypass the stored passkey requirement. An unapproved substitute order is never made approved by opening a return. The static status page exposes no account history, amounts or provider identifiers, uses no external assets and sends no-referrer/no-store headers. Expired, forged, mismatched or replayed capabilities cannot perform the action. A failed or uncertain authorization consumes the capability and asks the owner to reconcile the existing purchase; it never creates a replacement. Existing signed provider webhooks and owner reconciliation remain separate. Physical-phone and real new Sandbox-provider runs have not been performed for this delta.

Review fixes, 30 October: the public buyer-return proxy sends no Authorization header at all, including no agent credential. The return handler does not use the global application lock; its token is consumed atomically in SQLite and the existing conditional Book.claim arbitrates authorization against a racing webhook. Provider reads and authorization calls therefore cannot hold the global lock through this return path. Tests force a callback/webhook race and verify exactly one authorization request.
