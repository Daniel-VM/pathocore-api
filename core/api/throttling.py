from rest_framework.settings import api_settings
from rest_framework.throttling import SimpleRateThrottle


class PublicAPIRateThrottle(SimpleRateThrottle):
    scope = "public_api"

    def get_rate(self):
        return api_settings.DEFAULT_THROTTLE_RATES.get(self.scope)

    def get_cache_key(self, request, view):
        return self.cache_format % {
            "scope": self.scope,
            "ident": self.get_ident(request),
        }
