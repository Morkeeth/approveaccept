# Judge path

## What the judge sees

1. Open the hosted HTTPS demo. Public visitors get clearly labelled synthetic examples with no payment actions. The owner signs in to run the actual sandbox path.
2. Select **Start guided demo**.
3. See three outcomes created by the normal request API:
   - EUR 18.00 is inside the agent allowance and is captured automatically.
   - EUR 48.00 exceeds the per-purchase allowance and waits for the owner.
   - EUR 76.00 travel is outside the allowed category and is stopped before PayPal.
4. Select **Open the Face ID decision**.
5. Read the exact agent, merchant, amount, task and reason.
6. Select **Approve with Face ID** on the enrolled phone.
7. Return to the dashboard and confirm the request is captured in PayPal Sandbox.

The guided route never approves for the judge. It never broadens an allowance. It uses the same spend rules, PayPal adapter, passkey verifier and state transitions as an agent request.

## Seeded PayPal Sandbox setup

Create one dedicated PayPal business sandbox account and one REST app owned by it. Put only its sandbox client ID, sandbox secret and merchant ID in the host secret manager. The judge does not need a PayPal login because the demo uses PayPal's public sandbox card to create an authorization. The owner phone needs one passkey enrolment on the final HTTPS origin.

Required host values are listed in `ENVIRONMENT.md`. Do not put their values in the repository.

## Clean judge test

Use a private browser with no local storage. Open the public root URL. Confirm the guided button is visible. Start the demo, open the held request, approve it on the enrolled phone, then reload the dashboard. Confirm that the same request moved from **Needs me** to **Auto-approved** with state captured. Confirm the blocked travel request has no PayPal order.

Sign in with the owner's private access key before the payment-backed steps. Never give that key to a public judge or put it in a submission. Show the real owner phone and matching Sandbox receipt in the reviewed demonstration video; public judges can explore the synthetic read-only interface without gaining purchasing permission.

This test proves the public judge journey only after it is run on the deployed HTTPS origin. Local checks do not prove deployment, Face ID on a real phone, or PayPal Sandbox acceptance.
