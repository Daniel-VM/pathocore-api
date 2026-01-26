from core import models


def get_sample_detail(sample_unique_id: str):
    return models.Sample.objects.filter(sample_unique_id=sample_unique_id).last()
