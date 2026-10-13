"""Opt-in owner access from the latest authenticated frame's public network.

The ASGI server must preserve the TCP peer (uvicorn proxy_headers=False). Only
explicitly trusted reverse proxies may supply X-Forwarded-For. This is a shared
network convenience: anyone behind that public IP receives owner access.
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


def source_public_ip(request):
    """Canonical global unicast source; ignore forwarding from untrusted peers."""
    peer = _address(request.client.host) if request.client else None
    proxies = _trusted_proxies()

    def trusted(address):
        return address is not None and any(address in network for network in proxies)

    if trusted(peer):
        forwarded = request.headers.getlist("x-forwarded-for")
        if len(forwarded) != 1 or len(forwarded[0]) > 2048:
            return None
        chain = forwarded[0].split(",")
        if not 1 <= len(chain) <= 32:
            return None
        # Walk right-to-left so attacker-controlled prefixes cannot override the
        # first untrusted hop. Each trusted proxy must append its observed peer.
        for raw in reversed(chain):
            peer = _address(raw)
            if peer is None:
                return None
            if not trusted(peer):
                break
        else:
            return None
    return str(peer) if _global(peer) else None


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
    address = source_public_ip(request)
    if address:
        service.store.record_frame_network(frame["id"], address, now or datetime.now(UTC))
    else:
        service.store.clear_frame_network(frame["id"])


def network_session(request, service, *, now=None):
    """A request-local owner session, with no cookie or public source-IP fields."""
    address = source_public_ip(request)
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
