from requests_cache import CachedSession

http_session = CachedSession(stale_if_error=True, use_cache_dir=True)
