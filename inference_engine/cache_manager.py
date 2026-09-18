import time
from functools import wraps
from core.logger import system_logger

class CacheManager:
    """Simple in-memory cache for predictions."""
    def __init__(self, ttl_seconds=300):
        self.cache = {}
        self.ttl = ttl_seconds

    def get_cached(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None

    def set_cached(self, key, value):
        self.cache[key] = (value, time.time())

prediction_cache = CacheManager(ttl_seconds=60)

def cached_prediction(func):
    """Decorator to cache risk predictions."""
    @wraps(func)
    def wrapper(self, features_df):
        if len(features_df) == 1:
            key = str(features_df.iloc[0].to_dict())
            cached_result = prediction_cache.get_cached(key)
            if cached_result is not None:
                system_logger.debug("Cache hit for prediction.")
                return cached_result
            
            result = func(self, features_df)
            prediction_cache.set_cached(key, result)
            return result
        else:
            return func(self, features_df)
            
    return wrapper
