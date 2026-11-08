import ipaddress, socket
from urllib.parse import urlparse
from fastapi import HTTPException

def validate_url(value: str) -> str:
    p=urlparse(value)
    if p.scheme not in ("http","https") or not p.hostname: raise HTTPException(400,"Only valid public HTTP/HTTPS URLs are accepted.")
    if p.username or p.password: raise HTTPException(400,"Embedded URL credentials are not allowed.")
    host=p.hostname.lower().rstrip(".")
    if host == "localhost" or host.endswith(".localhost"): raise HTTPException(400,"Localhost targets are blocked.")
    try: rows=socket.getaddrinfo(host,p.port or (443 if p.scheme=="https" else 80),type=socket.SOCK_STREAM)
    except OSError: raise HTTPException(400,"Target hostname could not be resolved.")
    ips={ipaddress.ip_address(x[4][0].split("%")[0]) for x in rows}
    if not ips or any(not x.is_global for x in ips): raise HTTPException(400,"Private, loopback, link-local, and reserved IPs are blocked.")
    return value
