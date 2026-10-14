"""Opt-in owner access from the latest authenticated frame's observed network.

The ASGI server must preserve the TCP peer (uvicorn proxy_headers=False). Only
explicitly trusted reverse proxies may supply X-Forwarded-For. This is a shared
network convenience: anyone sharing an admissible origin receives owner access.
"""

import hashlib
import hmac
import ipaddress
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

MAX_CONTACT_AGE = timedelta(hours=48)


def _address(value):
    try:
        # Zone identifiers and host:port syntax are never accepted from a proxy.
        if not value or "%" in value:
            return None
        address = ipaddress.ip_address(value.strip())
        return (
            address.ipv4_mapped
            if isinstance(address, ipaddress.IPv6Address) and (address.ipv4_mapped)
            else address
        )
    except ValueError:
        return None


def _global(address):
    return bool(
        address
        and address.is_global
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
        and not address.is_loopback
        and not address.is_link_local
    )


def _trusted_proxies():
    try:
        values = os.getenv("EMVIARY_TRUSTED_PROXY_IPS", "").split(",")
        return [
            ipaddress.ip_network(value.strip(), strict=False) for value in values if value.strip()
        ]
    except ValueError:
        # A typo must disable proxy trust, never broaden it.
        return []


def _source_address(request):
    """Return the observed client and whether an explicit proxy supplied it."""
    peer = _address(request.client.host) if request.client else None
    proxies = _trusted_proxies()

    def trusted(address):
        return address is not None and any(address in network for network in proxies)

    proxied = trusted(peer)
    if proxied:
        forwarded = request.headers.getlist("x-forwarded-for")
        if len(forwarded) != 1 or len(forwarded[0]) > 2048:
            return None, False
        chain = forwarded[0].split(",")
        if not 1 <= len(chain) <= 32:
            return None, False
        # Walk right-to-left so attacker-controlled prefixes cannot override the
        # first untrusted hop. Each trusted proxy must append its observed peer.
        for raw in reversed(chain):
            peer = _address(raw)
            if peer is None:
                return None, False
            if not trusted(peer):
                break
        else:
            return None, False
    return peer, proxied


def source_public_ip(request):
    """Canonical global unicast source; ignore forwarding from untrusted peers."""
    peer, _ = _source_address(request)
    return str(peer) if _global(peer) else None


def source_management_ip(request):
    """Allow exact, configured LAN origins only behind an explicitly trusted proxy.

    Hairpin NAT can make both a frame and a browser appear as their router's
    private address. This exception does not trust private ranges, Docker peers,
    or browser-supplied forwarding headers.
    """
    peer, proxied = _source_address(request)
    if _global(peer):
        return str(peer)
    if not peer or not proxied:
        return None
    ranges = tuple(
        ipaddress.ip_network(value)
        for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
    )
    allowed = []
    for value in os.getenv("EMVIARY_TRUSTED_LOCAL_IPS", "").split(","):
        if not value.strip():
            continue
        address = _address(value)
        if address is None or not any(address in network for network in ranges):
            return None
        allowed.append(address)
    return str(peer) if peer in allowed else None


def record_frame_network(request, service, frame, *, now=None):
    """Record only a successfully authenticated frame image request.

    Recheck the bearer so a future caller cannot accidentally record rejected
    traffic or a browser-provided frame ID. Invalid sources cannot grant access.
    """
    if request.url.path != "/v1/image":
        return
    authorization = request.headers.get("authorization", "")
    scheme, separator, token = authorization.partition(" ")
    authenticated = (
        service.store.authenticate(token) if (separator and scheme.lower() == "bearer") else None
    )
    if not authenticated or authenticated["id"] != frame["id"]:
        return
    address = source_management_ip(request)
    if address:
        service.store.record_frame_network(frame["id"], address, now or datetime.now(UTC))
    else:
        service.store.clear_frame_network(frame["id"])


def network_session(request, service, *, now=None):
    """A request-local owner session, with no cookie or public source-IP fields."""
    address = source_management_ip(request)
    if not address:
        return None
    now = now or datetime.now(UTC)
    matches = []
    for contact in service.store.frame_network_contacts():
        try:
            policy = json.loads(contact["policy"])
            if not isinstance(policy, dict):
                continue
            seen = datetime.fromisoformat(contact["authenticated_at"])
            if (
                policy.get("management_trusted_wan") is True
                and contact["public_ip"] == address
                and timedelta(0) <= now - seen <= MAX_CONTACT_AGE
            ):
                matches.append(contact["frame_id"])
        except (ValueError, TypeError):
            continue
    if not matches:
        return None
    try:
        auth_path = Path(os.getenv("EMVIARY_SECRET_DIR", "/run/secrets")) / "owner-auth.json"
        auth = json.loads(auth_path.read_text())
        secret = bytes.fromhex(auth["hash"])
        if len(secret) != 32:
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    # Domain separation keeps this token distinct from password sessions. Binding
    # IP, frame set and day means copying a form cannot carry network access away.
    message = json.dumps(
        ["emviary-network-csrf-v1", address, matches, now.date().isoformat()],
        separators=(",", ":"),
    ).encode()
    csrf = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return {"csrf": csrf, "network_access": True}
