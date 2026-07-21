from django.urls import include, path

# Compatibility shim: expose the versioned API if anything still imports core.urls.
API_V1_URLS = ("core.api.v1.urls", "pathocore_api")

urlpatterns = [
    path("api/v1/", include(API_V1_URLS, namespace="pathocore_api_v1")),
    path("v1/", include(API_V1_URLS, namespace="pathocore_api_v1_legacy")),
]
