# Hosted sandbox environment

The hosted judge demo remains PayPal sandbox. Set only these values in the host's secret manager:

- `APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_ID`: client ID for the dedicated PayPal sandbox REST app.
- `APPROVEACCEPT_PAYPAL_SANDBOX_CLIENT_SECRET`: secret for that same sandbox REST app.
- `APPROVEACCEPT_PAYPAL_SANDBOX_MERCHANT_ID`: merchant ID of the business sandbox account linked to that app.
- `APPROVEACCEPT_LIVE_MONEY_ENABLED`: must remain `false`; this package has no live PayPal endpoint.
- `AA_DATA_DIR`: writable directory for the sandbox demo databases; defaults to `/tmp/approveaccept-data`.
- `PORT`: public design service port supplied by the host; defaults to `8080`.
- `AA_DESIGN_HOST`: public service bind address. `start-host.sh` defaults to `0.0.0.0` for container ingress; direct development server runs default to loopback. The internal API stays on loopback.
- `AA_BACKEND_PORT`: internal sandbox API port; defaults to `8752`.
- `LEASH_V2_WEBHOOK_PORT`: optional loopback-only PayPal webhook listener port. Set a fresh port such as `8893` for an isolated local run. The public service forwards only `/webhooks/paypal` to this listener; it never exposes the full backend.
- `LEASH_V2_WEBHOOK_ID`: ID of the webhook registered for this exact HTTPS origin and sandbox run. Without this ID, the listener cannot verify a real PayPal event. `connect/register_fresh_webhook.py` records a new ID in the run's `AA_DATA_DIR` without deleting any older webhook.
- `APPROVEACCEPT_PUBLIC_BASE_URL`: HTTPS origin used in the expiring phone links. On Render, `start-host.sh` uses `RENDER_EXTERNAL_URL` when this is unset.
- `APPROVEACCEPT_PASSKEY_ORIGIN`: fixed HTTPS WebAuthn origin. `start-host.sh` uses `APPROVEACCEPT_PUBLIC_BASE_URL` when this is unset. The relying-party ID comes from this value, not from a request Host header.
- `APPROVEACCEPT_GUIDED_DEMO`: set to `1` only on the judge demo. It enables the explicit guided-demo button. It does not approve a payment or bypass Face ID.
- `APPROVEACCEPT_OWNER_TOKEN`: a separate random owner access key, at least 32 characters. Set it in the host secret manager and use Owner sign-in on the dashboard. It is never included in a public page or URL. Missing or short keys keep owner access disabled.
- `APPROVEACCEPT_AGENT_TOKEN`: a different random access key, at least 32 characters, for one named agent. The remote MCP client sends it as a bearer credential. It cannot grant allowances, start the owner demo or read the owner's queue.
- `APPROVEACCEPT_AGENT_NAME`: exact identity assigned to that agent key. Requests for another agent are refused. The owner configures the matching allowance after signing in.

Public visitors see three synthetic, read-only examples. They cannot start the PayPal-backed guided demo, mint phone links, enrol a passkey or change permissions. Owner sign-in uses an HttpOnly, SameSite=Strict one-hour session; HTTPS origins also set Secure. Owner writes require the same browser origin. Phone enrolment and decisions use their existing narrow, expiring capabilities and server-side passkey validation; the public state never exposes their setup links.

For a remote MCP client set `AA_URL` to the public HTTPS origin, set its agent key privately, and use the exact assigned agent name. The internal loopback API is trusted single-machine infrastructure and must not be published separately.

Keep `AA_DATA_DIR` on durable private storage before using the hosted sandbox across restarts. The default temporary directory is suitable only for disposable local demos and loses the payment record and enrolled passkey on host replacement. This package does not provision or purchase a hosted disk.

Start both services with `./start-host.sh`. Health checks are `/health` on the public service and `http://127.0.0.1:$AA_BACKEND_PORT/health` inside the container. The public service proxies generic purchase requests, expiring phone-link reads, passkey enrolment and assertions, and human decisions to the internal Sandbox API.

Do not set production credentials. The live-money switch is documented for an explicit boundary only; no code path reads it and no live PayPal host exists in this package.
