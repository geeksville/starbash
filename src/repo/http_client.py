from requests_cache import CachedSession

# We use this cache so that if the client is offline all previously downloaded repos will
# still keep working.
http_session = CachedSession(stale_if_error=True, use_cache_dir=True)
