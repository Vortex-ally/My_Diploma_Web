import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "volunteer"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "volunteer.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

application = get_wsgi_application()
