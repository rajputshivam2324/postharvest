from io import StringIO

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.db.base import Base


def test_clean_migration_upgrade_downgrade_and_schema(tmp_path, monkeypatch):
    path = tmp_path / "migrations.sqlite"
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("JWT_SECRET", "migration-test-key-that-is-at-least-32-characters")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    engine = create_engine(f"sqlite:///{path}")
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        context = MigrationContext.configure(connection)
        assert compare_metadata(context, Base.metadata) == []
    assert "sensor_readings" in inspect(engine).get_table_names()
    engine.dispose()
    command.downgrade(config, "base")
    engine = create_engine(f"sqlite:///{path}")
    assert inspect(engine).get_table_names() == ["alembic_version"]
    engine.dispose()
    command.upgrade(config, "head")


def test_postgres_migration_sql_includes_vector_and_constraints(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/harvest")
    monkeypatch.setenv("JWT_SECRET", "migration-test-key-that-is-at-least-32-characters")
    output = StringIO()
    config = Config("alembic.ini", output_buffer=output)
    command.upgrade(config, "head", sql=True)
    sql = output.getvalue()
    assert "CREATE EXTENSION IF NOT EXISTS vector" in sql
    assert "TYPE vector(768)" in sql
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert "UNIQUE (device_id, event_id)" in sql
    assert "WHERE resolved_at IS NULL" in sql


def test_supplied_connection_keeps_migrations_in_outer_transaction(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("JWT_SECRET", "migration-test-key-that-is-at-least-32-characters")
    engine = create_engine("sqlite://")
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.exec_driver_sql("BEGIN")  # SQLite needs explicit BEGIN for transactional DDL.
        config = Config("alembic.ini")
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"
        assert transaction.is_active
        transaction.rollback()
        assert inspect(connection).get_table_names() == []
    engine.dispose()


def _insert_old_schema_data(engine):
    """Two devices (one on an archived batch) with readings, as the 0004 schema stored them."""
    reading = (
        "INSERT INTO sensor_readings (id,device_id,batch_id,event_id,temperature_c,humidity_pct,"
        "gas_adc,gas_voltage_v,warming_up,simulated,source_timestamp,ingested_at) "
        "VALUES (:id,:d,:b,:e,20,70,1000,0.8,0,0,'2026-01-03','2026-01-03')"
    )
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO users (id,user_id,password_hash,role,active,created_at) "
                "VALUES ('u1','u1','h','operator',1,'2026-01-01')"
            )
        )
        for batch_id, archived in (("b1", 0), ("b2", 1)):
            c.execute(
                text(
                    "INSERT INTO batches (id,identifier,owner_id,commodity,quantity,unit,"
                    "storage_location,attributes,status,archived,recovery_count,created_at,"
                    "updated_at) VALUES (:i,:i,'u1','tomato',1,'kg','A','{}','unknown',:a,0,"
                    "'2026-01-01','2026-02-01')"
                ),
                {"i": batch_id, "a": archived},
            )
        for device_id, batch_id in (("d1", "b1"), ("d2", "b2")):
            c.execute(
                text(
                    "INSERT INTO devices (id,identifier,batch_id,credential_hash,active,"
                    "simulated,created_at) VALUES (:d,:d,:b,'h',1,0,'2026-01-02')"
                ),
                {"d": device_id, "b": batch_id},
            )
            for n in range(3):
                c.execute(
                    text(reading),
                    {"id": f"{device_id}r{n}", "d": device_id, "b": batch_id, "e": f"e{n}"},
                )
        c.execute(
            text(
                "INSERT INTO device_baselines (id,device_id,actor_id,gas_adc,recorded_at,"
                "created_at) VALUES ('bl1','d1','u1',1000,'2026-01-02','2026-01-02')"
            )
        )


def test_upgrade_preserves_existing_records_and_downgrade_refuses_to_lose_data(
    tmp_path, monkeypatch
):
    path = tmp_path / "preserve.sqlite"
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    monkeypatch.setenv("JWT_SECRET", "migration-test-key-that-is-at-least-32-characters")
    config = Config("alembic.ini")
    command.upgrade(config, "0004")
    engine = create_engine(f"sqlite:///{path}")
    _insert_old_schema_data(engine)
    tables = ("sensor_readings", "devices", "batches", "device_baselines")

    def counts():
        with engine.connect() as c:
            return {t: c.scalar(text(f"SELECT count(*) FROM {t}")) for t in tables}

    before = counts()
    command.upgrade(config, "head")
    assert counts() == before  # nothing was deleted or duplicated
    with engine.connect() as c:
        # Devices that existed already hold a credential, so they must not turn "unpaired".
        assert c.scalar(text("SELECT count(*) FROM devices WHERE paired_at IS NULL")) == 0
    with engine.connect() as c:
        by_device = dict(c.execute(text("SELECT id, batch_id FROM device_assignments")).all())
        assert by_device == {"d1": "b1", "d2": "b2"}
        released = dict(
            c.execute(text("SELECT id, released_at IS NOT NULL FROM device_assignments")).all()
        )
        assert released == {"d1": 0, "d2": 1}  # the archived batch's device is freed
        pointers = dict(c.execute(text("SELECT id, batch_id FROM devices")).all())
        assert pointers == {"d1": "b1", "d2": None}
        # Every reading still belongs to the batch it was recorded for.
        owners = c.execute(
            text("SELECT device_id, batch_id, count(*) FROM sensor_readings GROUP BY 1, 2")
        ).all()
        assert sorted(owners) == [("d1", "b1", 3), ("d2", "b2", 3)]

    # A clean downgrade restores the old shape without losing a row.
    command.downgrade(config, "0004")
    assert counts() == before
    command.upgrade(config, "head")

    # An unattached reading cannot exist in the old schema: refuse rather than delete it.
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO sensor_readings (id,device_id,batch_id,event_id,temperature_c,"
                "humidity_pct,gas_adc,gas_voltage_v,warming_up,simulated,source_timestamp,"
                "ingested_at) VALUES ('held','d1',NULL,'x',20,70,1000,0.8,0,0,"
                "'2026-01-03','2026-01-03')"
            )
        )
    command.downgrade(config, "0005")  # pairing is purely additive, so this step is safe
    with pytest.raises(RuntimeError, match="without losing data"):
        command.downgrade(config, "0004")
    with engine.connect() as c:
        assert c.scalar(text("SELECT version_num FROM alembic_version")) == "0005"
        assert c.scalar(text("SELECT count(*) FROM sensor_readings")) == 7
    engine.dispose()
