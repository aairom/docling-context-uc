# Credential Rotation Runbook

This runbook describes how the platform team rotates API credentials for the
billing service. Rotation happens every 90 days or immediately after a suspected leak.

## Preconditions

- You hold the `platform-admin` role in the secrets manager.
- A change ticket is approved and linked in the on-call channel.

## Rotate the API credentials

1. Generate a new key pair in the secrets manager under `billing/api`.
2. Deploy the new key to the staging environment and run the smoke tests.
3. Promote the key to production with a rolling restart of the billing pods.
4. Revoke the previous key after 24 hours once error rates stay below 0.1 percent.

## Rollback

If error rates exceed 1 percent after promotion, re-enable the previous key
and open an incident. Never delete the previous key before the 24 hour window ends.
