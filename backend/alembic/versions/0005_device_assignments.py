"""Device assignments: decouple hardware from batches while keeping all history

Upgrade is data-preserving: no reading, assessment or observation is rewritten.
Every existing device gets an assignment row (id = device id) recording its current
batch. Devices whose batch is archived are released, because archived batches are
read-only. Downgrade refuses to run if the data cannot be represented in the old
one-batch-per-device schema.
"""

import sqlalchemy as sa

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_assignments",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.String(length=36), nullable=False),
        sa.Column("assigned_by", sa.String(length=36), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_by", sa.String(length=36), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(
            ["assigned_by"], ["users.id"], name=op.f("fk_device_assignments_assigned_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"], ["batches.id"], name=op.f("fk_device_assignments_batch_id_batches")
        ),
        sa.ForeignKeyConstraint(
            ["device_id"], ["devices.id"], name=op.f("fk_device_assignments_device_id_devices")
        ),
        sa.ForeignKeyConstraint(
            ["released_by"], ["users.id"], name=op.f("fk_device_assignments_released_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_device_assignments")),
    )
    op.create_index(
        "ix_assignments_device_time",
        "device_assignments",
        ["device_id", "assigned_at"],
        unique=False,
    )
    op.create_index("ix_assignments_batch", "device_assignments", ["batch_id"], unique=False)
    op.create_index(
        "uq_assignment_open_device",
        "device_assignments",
        ["device_id"],
        unique=True,
        postgresql_where=sa.text("released_at IS NULL"),
        sqlite_where=sa.text("released_at IS NULL"),
    )

    # Backfill: one assignment per device. Reusing the device id as the row id keeps
    # this a single portable statement that also works in offline SQL mode.
    op.execute(
        "INSERT INTO device_assignments "
        "(id, device_id, batch_id, assigned_by, assigned_at, released_at, released_by, note) "
        "SELECT id, id, batch_id, NULL, created_at, NULL, NULL, "
        "'Backfilled from the device registration' FROM devices"
    )
    op.execute(
        "UPDATE device_assignments SET "
        "released_at = (SELECT b.updated_at FROM batches b "
        "WHERE b.id = device_assignments.batch_id), "
        "note = 'Released when the batch was archived' "
        "WHERE batch_id IN (SELECT id FROM batches WHERE archived)"
    )

    # Readings may now belong to no batch (device unassigned) and no longer pin a device
    # to one batch. The old composite FK must go first: it depends on devices(id, batch_id).
    with op.batch_alter_table("sensor_readings") as batch_op:
        batch_op.drop_constraint("fk_sensor_readings_device_id_devices", type_="foreignkey")
        batch_op.alter_column("batch_id", existing_type=sa.String(length=36), nullable=True)
        batch_op.create_foreign_key(
            "fk_sensor_readings_device_id_devices", "devices", ["device_id"], ["id"]
        )
    with op.batch_alter_table("devices") as batch_op:
        batch_op.drop_constraint("uq_devices_id", type_="unique")
        batch_op.alter_column("batch_id", existing_type=sa.String(length=36), nullable=True)
    op.execute(
        "UPDATE devices SET batch_id = NULL "
        "WHERE batch_id IN (SELECT id FROM batches WHERE archived)"
    )


def downgrade() -> None:
    if not op.get_context().as_sql:
        bind = op.get_bind()
        unrepresentable_devices = bind.scalar(
            sa.text(
                "SELECT count(*) FROM devices d WHERE d.batch_id IS NULL AND NOT EXISTS "
                "(SELECT 1 FROM device_assignments a WHERE a.device_id = d.id)"
            )
        )
        unrepresentable_readings = bind.scalar(
            sa.text(
                "SELECT count(*) FROM sensor_readings r JOIN devices d ON d.id = r.device_id "
                "WHERE r.batch_id IS NULL OR r.batch_id <> COALESCE(d.batch_id, "
                "(SELECT a.batch_id FROM device_assignments a WHERE a.device_id = d.id "
                "ORDER BY a.assigned_at DESC LIMIT 1))"
            )
        )
        if unrepresentable_devices or unrepresentable_readings:
            raise RuntimeError(
                "Cannot downgrade without losing data: "
                f"{unrepresentable_devices} unassigned device(s) never had a batch and "
                f"{unrepresentable_readings} reading(s) are unassigned or belong to a batch "
                "other than their device's last one. Nothing was changed."
            )
    op.execute(
        "UPDATE devices SET batch_id = (SELECT a.batch_id FROM device_assignments a "
        "WHERE a.device_id = devices.id ORDER BY a.assigned_at DESC LIMIT 1) "
        "WHERE batch_id IS NULL"
    )
    with op.batch_alter_table("devices") as batch_op:
        batch_op.alter_column("batch_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_unique_constraint("uq_devices_id", ["id", "batch_id"])
    with op.batch_alter_table("sensor_readings") as batch_op:
        batch_op.drop_constraint("fk_sensor_readings_device_id_devices", type_="foreignkey")
        batch_op.alter_column("batch_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_foreign_key(
            "fk_sensor_readings_device_id_devices",
            "devices",
            ["device_id", "batch_id"],
            ["id", "batch_id"],
        )
    op.drop_index(
        "uq_assignment_open_device",
        table_name="device_assignments",
        postgresql_where=sa.text("released_at IS NULL"),
        sqlite_where=sa.text("released_at IS NULL"),
    )
    op.drop_index("ix_assignments_batch", table_name="device_assignments")
    op.drop_index("ix_assignments_device_time", table_name="device_assignments")
    op.drop_table("device_assignments")
