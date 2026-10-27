from django.core.cache.backends.db import DatabaseCache
from django.db import connections

class RateLimitCache(DatabaseCache):
    """Never discard live auth counters when the cache reaches capacity."""
    def _cull(self, db, cursor, now, num):
        connection = connections[db]
        table = connection.ops.quote_name(self._table)
        cursor.execute(f"DELETE FROM {table} WHERE expires < %s", [connection.ops.adapt_datetimefield_value(now)])
