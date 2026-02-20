from core import models
from core.api.utils import access_control


def get_sample_detail(sample_unique_id: str, request_user=None):
    queryset = models.Sample.objects.filter(sample_unique_id=sample_unique_id)
    if request_user is not None:
        queryset = access_control.apply_sample_scope(queryset, request_user)
    return queryset.last()
