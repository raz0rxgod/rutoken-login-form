"""
example_urls_snippet.py

Фрагмент корневого urls.py вашего проекта — добавьте эти два path().
"""

from django.contrib import admin
from django.urls import include, path

from apps.accounts.views import LoginPageView, logout_view

urlpatterns = [
    path("admin/", admin.site.urls),

    path("login/", LoginPageView.as_view(), name="login"),
    path("logout/", logout_view, name="logout"),
    path("api/accounts/", include("apps.accounts.urls")),

    # ... остальные маршруты вашего проекта ...
]
