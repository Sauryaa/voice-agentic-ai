from slowapi import Limiter
from slowapi.util import get_remote_address

# Use client IP as the rate-limit key.
# Behind Cloud Run, the remote address comes through the proxy chain.
limiter = Limiter(key_func=get_remote_address)
