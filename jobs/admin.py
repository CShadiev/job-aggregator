from django.contrib import admin

from jobs.models import Job
from jobs.models import Tag
from jobs.models import Country

# Register your models here.
admin.site.register(Job)
admin.site.register(Tag)
admin.site.register(Country)
