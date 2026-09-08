"""
apps/accounts/urls.py

Подключается в корневом urls.py как:

    path("login/", LoginPageView.as_view(), name="login"),
    path("api/accounts/", include("apps.accounts.urls")),
"""

from django.urls import path

from .views import ChallengeView, CertificateLoginView

app_name = "accounts"

urlpatterns = [
    path("auth/challenge/", ChallengeView.as_view(), name="auth-challenge"),
    path("auth/login/", CertificateLoginView.as_view(), name="auth-login"),
]
