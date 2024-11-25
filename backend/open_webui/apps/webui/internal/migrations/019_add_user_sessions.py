from contextlib import suppress

import peewee as pw
from peewee_migrate import Migrator


with suppress(ImportError):
    import playhouse.postgres_ext as pw_pext


def migrate(migrator: Migrator, database: pw.Database, *, fake=False):
    """Write your migrations here."""

    @migrator.create_model
    class UserSession(pw.Model):
        id = pw.CharField(max_length=255, primary_key=True)
        user_id = pw.CharField(max_length=255)
        socket_id = pw.CharField(max_length=255, null=True)
        last_active = pw.DateTimeField(null=False)
        token = pw.TextField(null=False)

        class Meta:
            table_name = "user_sessions"


def rollback(migrator: Migrator, database: pw.Database, *, fake=False):
    """Write your rollback migrations here."""

    migrator.remove_model("user_sessions") 