"""data export and restore jobs

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-06 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "data_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.Enum("export", "restore", name="data_job_kind"), nullable=False),
        sa.Column(
            "status",
            sa.Enum("queued", "running", "done", "failed", name="data_job_status"),
            nullable=False,
        ),
        sa.Column("storage_key", sa.String(length=200), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("counts", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_data_jobs_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_jobs")),
    )
    op.create_index(
        "ix_data_jobs_user_created", "data_jobs", ["user_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_data_jobs_user_created", table_name="data_jobs")
    op.drop_table("data_jobs")
    sa.Enum(name="data_job_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="data_job_kind").drop(op.get_bind(), checkfirst=True)
