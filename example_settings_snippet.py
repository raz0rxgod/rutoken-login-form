"""
example_settings_snippet.py

Это НЕ полноценный settings.py — набор фрагментов, которые нужно
добавить/поправить в settings.py вашего проекта, чтобы подключить
apps.accounts из этого репозитория. Скопируйте только нужные куски,
подставив свои значения (SECRET_KEY, БД и т.д. здесь не показаны —
это обычные настройки Django, к этому модулю отношения не имеют).
"""

import os

INSTALLED_APPS = [
    # ... ваши обычные apps ...
    "django.contrib.staticfiles",
    "rest_framework",
    "axes",
    "apps.accounts",
]

AUTH_USER_MODEL = "accounts.User"

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "axes.middleware.AxesMiddleware",  # обязателен для django-axes
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesBackend",                       # порядок важен — axes первым
    "apps.accounts.backends.CertificateAuthBackend",    # наш backend вторым
]

# Обязательно Redis (или Memcached) — НЕ LocMemCache. Challenge, выданный
# одним воркером gunicorn, должен быть виден другому воркеру, принявшему
# запрос на вход. См. docs/RUTOKEN_LOGIN.md, раздел 4.
CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}

AXES_FAILURE_LIMIT = int(os.environ.get("AXES_FAILURE_LIMIT", "5"))
AXES_COOLOFF_TIME = float(os.environ.get("AXES_COOLOFF_TIME_HOURS", "1"))
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]  # "username" здесь = thumbprint сертификата
AXES_RESET_ON_SUCCESS = True
AXES_HANDLER = "axes.handlers.cache.AxesCacheHandler"  # использует те же CACHES выше

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "1000/min"},
}

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"

# Не True без реального TLS перед сайтом — иначе браузер не сохранит
# сессию/CSRF-cookie и вход будет падать с "Ошибка проверки CSRF".
SESSION_COOKIE_SECURE = os.environ.get("DJANGO_USE_SECURE_COOKIES", "True") == "True"
CSRF_COOKIE_SECURE = os.environ.get("DJANGO_USE_SECURE_COOKIES", "True") == "True"

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]  # чтобы Django нашёл static/vendor/rutoken-plugin.min.js
STATIC_ROOT = BASE_DIR / "staticfiles"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],  # чтобы Django нашёл templates/accounts/login.html
        "APP_DIRS": True,
        # ...
    }
]
