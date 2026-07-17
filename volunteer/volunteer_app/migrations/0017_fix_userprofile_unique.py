from django.db import migrations
from django.db import connection


def fix_userprofile(apps, schema_editor):
    # Для SQLite нічого не потрібно робити.
    if connection.vendor == "sqlite":
        return

    # Для PostgreSQL залишаємо SQL.
    with connection.cursor() as cursor:
        cursor.execute("DROP INDEX IF EXISTS idx_userprofile_user_id;")

        cursor.execute("""
            DELETE FROM volunteer_app_userprofile
            WHERE id NOT IN (
                SELECT DISTINCT ON (user_id) id
                FROM volunteer_app_userprofile
                ORDER BY user_id,
                    CASE role
                        WHEN 'admin' THEN 1
                        WHEN 'organiser' THEN 2
                        ELSE 3
                    END,
                    id
            );
        """)

        cursor.execute("""
            ALTER TABLE volunteer_app_userprofile
            ADD CONSTRAINT volunteer_app_userprofile_user_id_uniq
            UNIQUE (user_id);
        """)


class Migration(migrations.Migration):
    dependencies = [
        ("volunteer_app", "0016_telegram_notifications"),
    ]

    operations = [
        migrations.RunPython(fix_userprofile, migrations.RunPython.noop),
    ]
