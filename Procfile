release: python manage.py migrate --noinput && python manage.py compilemessages
web: gunicorn config.wsgi --log-file -
