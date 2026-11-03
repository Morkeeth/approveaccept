# Judge path

There are two ways in. Both use PayPal Sandbox only, and no live money moves.

## 1. On your own machine (about 2 or 5 minutes)

Follow "Try it: pick one path" in the README. Path A needs no PayPal account. Path B uses your own Sandbox keys and makes real Sandbox captures. Either way you sign in at `http://127.0.0.1:8780/inbox` with the owner key the app prints.

## 2. Preparing a hosted Sandbox (not yet deployed)

The hosted service is `./start-host.sh`, the entrypoint in `Dockerfile` and `render.yaml`. It serves the same pages as the local app, through a public front service that never exposes the internal API port:

- `/inbox`: your agents' requests, their limits, and Surprise me. A visitor without the owner key sees the sign-in form and a link to path 1.
- `/journey`: Surprise me on its own.
- `/approve`: the phone decision. Approve needs a passkey (Face ID) enrolled on this exact HTTPS origin.

What the owner shows, in order:

1. Sign in at `/inbox` with the owner key. The key stays private and never goes in a submission.
2. Let agents buy through the public front: `AA_URL=<hosted URL> APPROVEACCEPT_OWNER_TOKEN=<hosted owner key> python3 connect/demo_agents.py`. Inside a limit, PayPal captures. Over a limit, PayPal holds and the request waits. A category the owner did not allow stops before PayPal.
3. Open the held request on the phone and approve it with Face ID. PayPal captures that exact purchase.
4. For a local Path B run, read the same local data back through PayPal's MCP: `python3 connect/paypal_mcp_record.py` (requires Node and npx). This command is not a remote client for a hosted database. The supplied Python-only Docker image does not include Node; hosted readback requires a separate operator setup with Node and access to that host's data.

## What must be true on the hosted origin

- `APPROVEACCEPT_PUBLIC_BASE_URL` and `APPROVEACCEPT_PASSKEY_ORIGIN` equal the HTTPS URL. On Render, `start-host.sh` sets both from `RENDER_EXTERNAL_URL`.
- `AA_DATA_DIR` is on durable storage. On a default temporary directory, a restart loses the payment record and the enrolled passkey (see `ENVIRONMENT.md`).
- Only Sandbox keys are set, and `APPROVEACCEPT_LIVE_MONEY_ENABLED` stays `false`.

`test_hosted_judge_pages.py` drives this path through the hosted entrypoint in a browser, in substitute mode. A real phone approval on the deployed origin is proven only by running it there.
