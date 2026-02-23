# Local imports
import core.models
import core.api.v1.serializers
from django.utils import timezone
from rest_framework.response import Response
from rest_framework import status


def get_schema_version_if_exists(data):
    """Check if schema name and schema version exists"""
    apps_name = __package__.split(".")[0]
    print("apps_name", apps_name)
    print(data)
    if "schema_name" in data and "schema_version" in data:
        if core.models.Schema.objects.filter(
            schema_name__iexact=data["schema_name"],
            schema_version__iexact=data["schema_version"],
            schema_app_name__iexact=apps_name,
        ).exists():
            return core.models.Schema.objects.filter(
                schema_name__iexact=data["schema_name"],
                schema_version__iexact=data["schema_version"],
                schema_app_name__iexact=apps_name,
            ).last()
    return None


def get_analysis_defined(s_obj):
    return core.models.BioinfoAnalysisValue.objects.filter(
        bioinfo_analysis_fieldID__property_name="analysis_date", sample=s_obj
    ).values_list("value", flat=True)


def map_error_name(error_message):
    if error_message == "Sample already exists":
        return "Sample already defined"
    if error_message in {
        "schema_name and schema_version are required",
        "Schema not found for provided name/version",
        "Sample has no schema assigned",
    }:
        return "Schema name and version is not defined"
    return "Other"


def record_sample_error(sample_obj, error_name):
    if sample_obj is None:
        return
    try:
        add_sample_state_history(sample_obj, state_id=None, error_name=error_name)
    except ValueError:
        # If no prior state exists, skip logging silently.
        return


def add_sample_state_history(sample_obj, state_id, error_name=None):
    """
    Adds a new state history entry for a sample and marks previous states as not current.
    """
    # Resolve state for the history entry.
    if state_id:
        state_obj = core.models.SampleState.objects.filter(pk=state_id).last()
    else:
        last_history = (
            core.models.SampleStateHistory.objects.filter(sample=sample_obj)
            .order_by("-changed_at")
            .first()
        )
        state_obj = last_history.state if last_history else None

    if not state_obj:
        raise ValueError("No valid state found for the sample.")

    # Handle error_name if provided
    if error_name:
        error_name_obj = core.models.ErrorName.objects.filter(
            error_name=error_name
        ).last()
    else:
        error_name_obj = None
    if error_name_obj is None:
        error_name_obj = core.models.ErrorName.objects.filter(pk=999).first()
    if error_name_obj is None:
        raise ValueError("No valid error name found for the sample.")

    state_history_obj = {
        "is_current": True,
        "changed_at": timezone.now(),
        "sample": sample_obj.pk,
        "state": state_obj.pk,
        "error_name": error_name_obj.pk,
    }

    # Serialization
    state_history_serializer = core.api.v1.serializers.SampleStateHistorySerializer(
        data=state_history_obj
    )
    # Validation
    if not state_history_serializer.is_valid():
        return Response(
            state_history_serializer.errors, status=status.HTTP_400_BAD_REQUEST
        )
    # Mark previous states as not current after validation succeeds.
    core.models.SampleStateHistory.objects.filter(
        sample=sample_obj, is_current=True
    ).update(is_current=False)
    state_history_serializer.save()
    return True
