from rest_framework import permissions, viewsets
from jobs.models import Job
from jobs.models import Tag
from jobs.models import Country
from jobs.serializers import JobSerializer
from jobs.serializers import TagSerializer
from jobs.serializers import CountrySerializer


class JobViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows jobs to be viewed or edited.
    """
    queryset = Job.objects.all()
    serializer_class = JobSerializer
    permission_classes = [permissions.IsAuthenticated]


class TagViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows tags to be viewed or edited.
    """
    queryset = Tag.objects.all().order_by("name")
    serializer_class = TagSerializer
    permission_classes = [permissions.IsAuthenticated]


class CountryViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows countries to be viewed or edited.
    """
    queryset = Country.objects.all().order_by("name")
    serializer_class = CountrySerializer
    permission_classes = [permissions.IsAuthenticated]
