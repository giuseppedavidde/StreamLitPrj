"""Cache manager with file persistence and TTL."""

import json, os, time
from typing import Optional, Any

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.cache')

class CacheManager:
    DEFAULT_TTL = 86400 * 3

    def __init__(self, cache_dir: str = CACHE_DIR):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key: str) -> str:
        safe = key.replace('/', '_').replace(' ', '_')
        return os.path.join(self.cache_dir, f'{safe}.json')

    def get(self, key: str, max_age: int = 0) -> Optional[Any]:
        path = self._path(key)
        if not os.path.exists(path):
            return None
        try:
            with open(path) as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None
        ttl = max_age or self.DEFAULT_TTL
        if time.time() - entry['ts'] > ttl:
            return None
        return entry['data']

    def set(self, key: str, data: Any):
        path = self._path(key)
        try:
            with open(path, 'w') as f:
                json.dump({'ts': time.time(), 'data': data}, f)
        except OSError:
            pass

    def clear(self, prefix: str = ''):
        for fname in os.listdir(self.cache_dir):
            if fname.startswith(prefix):
                os.remove(os.path.join(self.cache_dir, fname))

    def clear_all(self):
        for fname in os.listdir(self.cache_dir):
            os.remove(os.path.join(self.cache_dir, fname))

    def keys(self) -> list[str]:
        return [f.replace('.json', '') for f in os.listdir(self.cache_dir) if f.endswith('.json')]
