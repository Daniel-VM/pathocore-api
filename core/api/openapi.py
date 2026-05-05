from drf_spectacular.extensions import OpenApiAuthenticationExtension


class KeycloakJWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "core.api.authentication.KeycloakJWTAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}


class LegacyBasicOrSessionAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "core.api.authentication.LegacyBasicOrSessionAuthentication"
    name = "basicAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "basic"}
