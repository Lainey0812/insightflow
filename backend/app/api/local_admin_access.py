"""Explicit local testing access; never trusts forwarded client identities."""
from ipaddress import ip_address
from urllib.parse import urlsplit

from fastapi import Request

from app.domain.errors import AppError


def loopback(host: str | None) -> bool:
    if host == 'localhost':
        return True
    try:
        return ip_address(host or '').is_loopback
    except ValueError:
        return False


def require_local_request(request: Request) -> None:
    origin = request.headers.get('origin')
    try:
        parsed = urlsplit(origin) if origin else None
        origin_allowed = parsed is None or (
            parsed.scheme in {'http', 'https'} and loopback(parsed.hostname)
            and not parsed.username and not parsed.password
        )
        allowed = (
            request.client is not None and loopback(request.client.host)
            and loopback(request.url.hostname) and origin_allowed
            and request.headers.get('sec-fetch-site') != 'cross-site'
        )
    except ValueError:
        allowed = False
    if not allowed:
        raise AppError('ADMIN_LOCAL_ONLY', '免登录测试模式仅允许本机访问。', 403)
