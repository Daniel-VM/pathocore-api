from django.urls import include, path

# Compatibility shim: expose the versioned API if anything still imports core.urls.
urlpatterns = [
    path("v1/", include("core.api.v1.urls")),
]
