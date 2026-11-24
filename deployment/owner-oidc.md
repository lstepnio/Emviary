# Emviary owner sign-in with Authentik

The owner login can use an existing owner password or a designated Authentik
account. Register one confidential Authentik provider for the canonical
management hostname, select an RSA signing key, and require membership in the
Emviary Owners group. Use the authorization code grant and an exact callback
of `https://emviary.majjix.com/manage/login/oidc/callback`. The app requests only
`openid` and checks each account against its configured list of provider subjects.

| Environment variable | Value |
| --- | --- |
| `EMVIARY_OIDC_ISSUER` | Exact discovery issuer, such as `https://auth.majjix.com/application/o/emviary/` |
| `EMVIARY_OIDC_CLIENT_ID` | Authentik client ID |
| `EMVIARY_OIDC_CLIENT_SECRET_FILE` | Path to the mounted secret, readable by the application UID |
| `EMVIARY_OIDC_CALLBACK_URL` | Exact callback above |
| `EMVIARY_OIDC_OWNER_SUBJECTS` | Comma-separated stable `sub` claims for approved owners |

The alternate management hostname's sign-in link takes users to the canonical
hostname. Password recovery remains available. Device authentication and
trusted-network sign-in continue through their existing paths. An OIDC owner
session expires after one hour. Removing an account from the Authentik group
blocks new sign-ins. To revoke existing owner sessions immediately, use the
existing owner password rotation procedure, which clears all owner sessions.

Verify password sign-in, OIDC sign-in by an approved owner, denial for an account
outside the allowlist, and a frame request with its existing device credential.
Remove the OIDC environment variables and recreate only Emviary to turn off
new OIDC logins. Existing sessions expire normally.
