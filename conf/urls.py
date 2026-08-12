from django.contrib import admin
from django.urls import path, include
from django.views.generic import RedirectView

# from drf_yasg.views import get_schema_view
# from drf_yasg import openapi
# from drf_yasg.generators import OpenAPISchemaGenerator
from drf_spectacular.views import (
    SpectacularRedocView,
    SpectacularSwaggerView,
    SpectacularAPIView,
)
from rest_framework.permissions import AllowAny

API_V1_URLS = ("core.api.v1.urls", "pathocore_api")


class PublicSpectacularAPIView(SpectacularAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]


class PublicSpectacularSwaggerView(SpectacularSwaggerView):
    authentication_classes = []
    permission_classes = [AllowAny]


class PublicSpectacularRedocView(SpectacularRedocView):
    authentication_classes = []
    permission_classes = [AllowAny]


"""
class BothHttpAndHttpsSchemaGenerator(OpenAPISchemaGenerator):
    def get_schema(self, request=None, public=False):
        schema = super().get_schema(request, public)
        schema.schemes = ["http", "https"]
        return schema


schema_view = get_schema_view(
    openapi.Info(
        title="PathoCore API",
        default_version="v0.0.1",
        description="PathoCore API",
    ),
    generator_class=BothHttpAndHttpsSchemaGenerator,
    public=True,
)
"""

urlpatterns = [
    path("", RedirectView.as_view(pattern_name="v1-swagger-ui", permanent=False)),
    path("admin/", admin.site.urls),
    # API-only project: UI routes removed
    # API REST FULL using drf spectacular
    path(
        "v1/openapi/",
        PublicSpectacularAPIView.as_view(),
        name="v1-schema",
    ),
    path(
        "v1/swagger/",
        PublicSpectacularSwaggerView.as_view(url_name="v1-schema"),
        name="v1-swagger-ui",
    ),
    path(
        "v1/swagger/redoc/",
        PublicSpectacularRedocView.as_view(url_name="v1-schema"),
        name="v1-redoc",
    ),
    path("openapi/", RedirectView.as_view(pattern_name="v1-schema", permanent=False)),
    path(
        "swagger/",
        RedirectView.as_view(pattern_name="v1-swagger-ui", permanent=False),
    ),
    path(
        "swagger/redoc/",
        RedirectView.as_view(pattern_name="v1-redoc", permanent=False),
    ),
    # REST FRAMEWORK URLS
    path("v1/", include(API_V1_URLS, namespace="pathocore_api_v1")),
    # Backward-compatible alias kept while clients migrate back to /v1.
    path("api/v1/", include(API_V1_URLS, namespace="pathocore_api_v1_legacy")),
    # user accounts
    path("accounts/", include("django.contrib.auth.urls")),
    # path('markdownx/', include('markdownx.urls')),
]
