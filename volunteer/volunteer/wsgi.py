import os

from django.core.management import call_command
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "volunteer.settings")

application = get_wsgi_application()

call_command("migrate", "--noinput")

import django
django.setup()
from django.conf import settings
if not settings.DEBUG:
    call_command("collectstatic", "--noinput")

from django.contrib.auth import get_user_model

User = get_user_model()
if not User.objects.filter(username="admin").exists():
    User.objects.create_superuser("admin", "admin@example.com", "admin12345")
