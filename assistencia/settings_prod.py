from .settings import *  # noqa


DEBUG = False
ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()]
CSRF_TRUSTED_ORIGINS = [o.strip() for o in os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()]

if not ALLOWED_HOSTS:
    raise RuntimeError("Defina DJANGO_ALLOWED_HOSTS para ambiente de producao.")
if SECRET_KEY == "django-insecure-dev-key-change-in-production":
    raise RuntimeError("Defina DJANGO_SECRET_KEY forte para ambiente de producao.")
if not CSRF_TRUSTED_ORIGINS:
    raise RuntimeError("Defina DJANGO_CSRF_TRUSTED_ORIGINS para ambiente de producao.")

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "31536000"))
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
