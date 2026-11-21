import pytest
from sqlalchemy.pool import QueuePool

from app.db.session import install_idle_ping


class FlakyCursor:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql):
        self.conn.pings += 1
        if self.conn.dead:
            raise OSError("server closed the connection")

    def close(self):
        pass


class FlakyConnection:
    def __init__(self):
        self.pings = 0
        self.dead = False

    def cursor(self):
        return FlakyCursor(self)

    def rollback(self):
        pass

    def commit(self):
        pass

    def close(self):
        pass


def make_pool(connections, fail_create=False):
    def creator():
        if fail_create:
            raise OSError("down")
        conn = FlakyConnection()
        connections.append(conn)
        return conn

    return QueuePool(creator, pool_size=1)


def use(pool):
    pool.connect().close()


def test_recent_connection_is_not_pinged():
    connections = []
    pool = make_pool(connections)
    install_idle_ping(pool, idle_seconds=60)
    for _ in range(3):
        use(pool)
    # Only the first checkout (never used before) is checked.
    assert connections[0].pings == 1


def test_idle_connection_is_pinged_and_dead_one_replaced():
    connections = []
    pool = make_pool(connections)
    install_idle_ping(pool, idle_seconds=0)
    use(pool)
    connections[0].dead = True
    use(pool)
    assert len(connections) == 2
    assert connections[1].dead is False


def test_unreachable_database_still_raises():
    pool = make_pool([], fail_create=True)
    install_idle_ping(pool)
    with pytest.raises(OSError):
        use(pool)
