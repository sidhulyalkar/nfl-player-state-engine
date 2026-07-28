from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass, field
from urllib.parse import urlparse


class AccessBoundaryError(PermissionError):
    """Raised when collection would cross a configured public-access boundary."""


_BLOCKED_HOSTNAMES = {"localhost", "localhost.localdomain", "metadata.google.internal"}


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def validate_public_url(url: str, *, resolve_dns: bool = True) -> str:
    """Validate that a URL targets a public HTTP(S) endpoint.

    This is an SSRF guard for collectors. It intentionally rejects credentials,
    local names, literal private addresses, and DNS names resolving to non-public
    address space.
    """

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise AccessBoundaryError("Only public HTTP(S) URLs are supported.")
    if parsed.username or parsed.password:
        raise AccessBoundaryError("URLs containing credentials are not supported.")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if not hostname:
        raise AccessBoundaryError("URL must include a hostname.")
    if hostname in _BLOCKED_HOSTNAMES or hostname.endswith((".local", ".internal", ".localhost")):
        raise AccessBoundaryError(f"Local or internal hostname is blocked: {hostname}")

    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if literal is not None and not _is_public_ip(hostname):
        raise AccessBoundaryError(f"Non-public IP address is blocked: {hostname}")

    if resolve_dns and literal is None:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
        except socket.gaierror as exc:
            raise AccessBoundaryError(f"Could not resolve public hostname: {hostname}") from exc
        if not addresses or any(not _is_public_ip(address) for address in addresses):
            raise AccessBoundaryError(f"Hostname resolves to non-public address space: {hostname}")
    return url


@dataclass(slots=True)
class PublicHostGuard:
    """Cache URL validation decisions while a rendered page loads subresources."""

    validated_hosts: set[str] = field(default_factory=set)

    def check(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme in {"data", "blob", "about"}:
            return True
        host = (parsed.hostname or "").lower()
        if not host:
            return False
        if host in self.validated_hosts:
            return True
        try:
            validate_public_url(url, resolve_dns=True)
        except AccessBoundaryError:
            return False
        self.validated_hosts.add(host)
        return True
