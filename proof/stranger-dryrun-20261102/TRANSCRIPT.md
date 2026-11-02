# Stranger dry run, 2 Nov 2026

Fresh `git clone` of `claude/paypal-journey-1nov` at 7fea80f into an empty folder. Key home was an isolated temp folder (`APPROVEACCEPT_HOME`), not the owner's `~/.config`. Keys were piped from the Sandbox REST app instead of pasted by hand; a judge pastes them at the hidden prompt.

## Step 0: `python3 connect/byok.py`

```
Sandbox client ID (hidden):
Sandbox client secret (hidden):
Sandbox merchant ID, or Enter to look it up:
No terminal attached: read the owner key from the saved file when you need it.
Step 0 · Connect PayPal Sandbox. Get keys at developer.paypal.com > Apps & Credentials > Sandbox.
Keys accepted by PayPal Sandbox.
Saved to <APPROVEACCEPT_HOME>/sandbox.env (mode 600, outside the repository).
Payments go to your own Sandbox business account <merchant ID, redacted>.
Connect your agent: point an MCP client at mcp_server.py with AA_URL set and the agent key from that file, agent name "Judge agent".
Next: ./journey.sh, then open the printed /journey link and sign in with the owner key.
```

`ls -la` on the key home: directory `drwx------`, `sandbox.env` `-rw-------`.

## Step 1: `./journey.sh`

```
ApproveAccept journey: http://127.0.0.1:8780/journey  (PayPal Sandbox, your own keys)
Sign in with the owner key from step 0. Stop with Ctrl-C.
ApproveAccept (leash-v2) on http://127.0.0.1:8780  PayPal: sandbox
```

## Journey (headless browser, 390 x 844, `record-journey.cjs`)

- Inside limit: Surprise me, swipe, Yes on "Signed poetry book" EUR 32. Receipt, PayPal capture 07A96099FP8059059, mood to receipt 8.7 s.
- Over limit: Yes on "Vegetarian tasting menu for two" EUR 58. One Face ID decision, held, not paid. Face ID itself not exercised (needs a phone and an HTTPS origin).

## PayPal readback (`connect/sandbox_readback.py`, provider GET only)

Order 2SA42216RX9488219 COMPLETED, authorization CAPTURED, capture 07A96099FP8059059 COMPLETED, amount matches. Full output in `sandbox-readback.json`.

## Leak grep

`grep -rlF` for the client ID, the secret and the owner key across the clone, the server log, the data folder and the recording output: 0 files each. Control: the same grep finds the secret in `sandbox.env`, 1 file. `git status` in the clone: clean.
