import uuid
from django.db import models


class Tag(models.Model):
    """
    Tag for a job.
    """
    name = models.CharField(max_length=100, primary_key=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)


class Country(models.Model):
    """
    Country for a job.
    """
    code = models.CharField(max_length=100, primary_key=True)
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)


class Job(models.Model):
    """
    Normalized job posting.
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    source_id = models.CharField(max_length=255, unique=True)
    title = models.CharField(max_length=255)
    title_normalized = models.CharField(max_length=255)
    company = models.CharField(max_length=255)
    company_normalized = models.CharField(max_length=255)
    location = models.CharField(max_length=255)
    country = models.ForeignKey(Country, on_delete=models.CASCADE)
    remote = models.BooleanField()
    url = models.URLField(max_length=255)
    tags = models.ManyToManyField(Tag, related_name='jobs', blank=True)
    description_raw = models.TextField()
    posted_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
