"""Scheduled PathoCore maintenance jobs."""

from django.core.management import call_command


def refresh_databrowser_caches():
    """Refresh the global DataBrowser and per-use-case summary caches."""
    call_command("refresh_databrowser_cache")
    call_command("refresh_use_case_cache")
