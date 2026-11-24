# Home-network management access

Password-free management remains opt-in per frame. An authenticated frame
contact through the validated device routes must renew its recognized origin within 30 days. Browser requests never
create or renew that trust.

Public origins match their observed public address. Hairpin NAT can use an exact
router address in `EMVIARY_TRUSTED_LOCAL_IPS`. Direct home-LAN routing gives each
device its own private address; configure that physical subnet explicitly with
`EMVIARY_TRUSTED_LOCAL_NETWORKS`, for example `192.168.10.0/24`.

LAN recognition requires a correctly configured `EMVIARY_TRUSTED_PROXY_IPS` and
the proxy's observed forwarded source. Subnets must be RFC1918 IPv4 `/24` or
narrower, or IPv6 ULA `/64` or narrower. Broad ranges, malformed configuration,
public ranges and subnets overlapping the trusted proxy are rejected. Never
configure a Docker bridge, VPN, or general private-address range as the home LAN.

Each admitted LAN uses a shared network identity, allowing a browser and frame
with different host addresses to match. A fresh authenticated frame connection
on that LAN is still required. Existing exact-router and public-origin behavior
is retained. This trusts other people on the configured home LAN, matching the
existing shared-network opt-in; devices elsewhere must sign in.

After deployment, use a normal online frame contact to renew recognition. If a
gift welcome is armed, use green/network wake rather than right, which reveals
the first picture. Then check `/manage` without a sign-in cookie. Verify rejection from an
outside network and with forged forwarding headers. Do not populate trust
records manually from a browser address or from device-reported local IP alone.

See [RUNBOOK](../RUNBOOK.md) for owner authentication and [OIDC configuration](owner-oidc.md) for the separate owner identity path.
