from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("volunteer_app", "0016_telegram_notifications"),
    ]

    operations = [
        # Drop the broken non-unique index that prevented the OneToOneField constraint
        migrations.RunSQL(
            sql="DROP INDEX IF EXISTS idx_userprofile_user_id;",
            reverse_sql="CREATE INDEX idx_userprofile_user_id ON volunteer_app_userprofile (user_id);",
        ),
        # Add the proper unique constraint that OneToOneField requires
        migrations.RunSQL(
            sql="""
                ALTER TABLE volunteer_app_userprofile
                    ADD CONSTRAINT volunteer_app_userprofile_user_id_uniq
                    UNIQUE (user_id);
            """,
            reverse_sql="ALTER TABLE volunteer_app_userprofile DROP CONSTRAINT IF EXISTS volunteer_app_userprofile_user_id_uniq;",
        ),
        # Safety: remove any remaining duplicates, keeping the highest-privilege role
        migrations.RunSQL(
            sql="""
                DELETE FROM volunteer_app_userprofile
                WHERE id NOT IN (
                    SELECT DISTINCT ON (user_id) id
                    FROM volunteer_app_userprofile
                    ORDER BY user_id,
                             CASE role
                                 WHEN 'admin'     THEN 1
                                 WHEN 'organiser' THEN 2
                                 ELSE 3
                             END,
                             id
                );
            """,
            reverse_sql="-- irreversible",
        ),
    ]
