#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt

cd volunteer

python manage.py collectstatic --no-input
python manage.py migrate
python manage.py createsuperuser --noinput || true
