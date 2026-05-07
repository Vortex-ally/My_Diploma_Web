from django.conf import settings
from django.db import migrations


def ensure_user_profiles(apps, schema_editor):
    User = apps.get_model("auth", "User")
    UserProfile = apps.get_model("volunteer_app", "UserProfile")

    for user in User.objects.all().iterator():
        UserProfile.objects.get_or_create(user_id=user.id)


class Migration(migrations.Migration):
    dependencies = [
        ("volunteer_app", "0006_project_max_volunteers"),
    ]

    operations = [
        migrations.RunPython(ensure_user_profiles, migrations.RunPython.noop),
    ]

