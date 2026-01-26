from django.core.asgi import get_asgi_application

# TODO: enable channels/redis routing if websockets are introduced later.
application = get_asgi_application()
