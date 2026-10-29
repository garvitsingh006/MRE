"""Django ticket #31664 / SWE-bench Lite django__django-13028.

A normal model instance can have a field called ``filterable`` set to False.
That does not make the instance a non-filterable ORM expression.

Before: an erroneous django.db.utils.NotSupportedError escapes Django code.
After: the same QuerySet filter can be constructed without an exception.

The filter is constructed, not evaluated: no database tables are required.
"""

from django.conf import settings

if not settings.configured:
    settings.configure(
        SECRET_KEY="mre-day1",
        INSTALLED_APPS=[],
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        },
    )

import django

django.setup()

from django.db import models


class MetaType(models.Model):
    label = models.CharField(max_length=30)
    filterable = models.BooleanField(default=False)

    class Meta:
        app_label = "mre_day1"


class Item(models.Model):
    meta_type = models.ForeignKey(MetaType, on_delete=models.CASCADE)

    class Meta:
        app_label = "mre_day1"


# A PK is set because Django does not permit filtering by an unsaved
# related object. No actual database queries are needed.
meta_type = MetaType(pk=1, label="brand", filterable=False)
queryset = Item.objects.filter(meta_type=meta_type)
# Reaching this point without an exception is the expected fixed behavior.
