"""Spanish number formats as written in Colombia (US49).

Django's generic Spanish groups thousands with a space ("276 436 986"); the
restaurants Mesa serves write "$276.436.986". Dates and everything else come
from the Colombian locale too.
"""
from django.conf.locale.es_CO.formats import *  # noqa: F401,F403
