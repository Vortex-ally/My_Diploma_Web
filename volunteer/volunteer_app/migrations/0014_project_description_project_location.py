from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("volunteer_app", "0013_eventtemplate_grouptemplate_hourstemplate_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="description",
            field=models.TextField(
                default="",
                blank=True,
                verbose_name="Опис",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="location",
            field=models.CharField(
                max_length=255,
                default="",
                blank=True,
                verbose_name="Місце проведення",
            ),
        ),
    ]
