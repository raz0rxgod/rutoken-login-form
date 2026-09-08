"""
apps/accounts/views.py

HTTP-эндпоинты для входа по Рутокену:

  POST /api/accounts/auth/challenge/  -> выдать одноразовый challenge
  POST /api/accounts/auth/login/      -> принять сертификат + подпись

Оба доступны анонимно (AllowAny) — это точка входа, сессии на этом
этапе ещё нет. Защита от подбора и повторных попыток — на django-axes
и одноразовости challenge, а не на правах доступа Django.

ПРО ЛОГИРОВАНИЕ: в исходном проекте, откуда извлечён этот модуль, здесь
были вызовы apps.audit.services.log_action(...) — записывали
login_success/login_failed в общий журнал действий системы. Тут они
убраны, чтобы репозиторий не зависел от чужого приложения audit.
Если на вашем проекте есть подобный журнал — добавьте свои вызовы в
точках, помеченных `# TODO: log_action(...)` ниже.
"""

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.views.generic import TemplateView
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from .serializers import CertificateLoginSerializer, ChallengeResponseSerializer
from .services import (
    AuthenticationFailedError,
    CertificateParseError,
    ChallengeInvalidError,
    authenticate_by_certificate,
    consume_challenge,
    issue_challenge,
    parse_certificate,
)


class LoginPageView(TemplateView):
    """
    Страница входа — рендерит форму (см. templates/accounts/login.html),
    сама аутентификация происходит через ChallengeView/CertificateLoginView
    ниже, JS на странице обращается к ним напрямую.
    """

    template_name = "accounts/login.html"

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect(settings.LOGIN_REDIRECT_URL)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # open-redirect: используем next только если это локальный путь,
        # никогда не отдаём его как есть во внешний домен.
        next_url = self.request.GET.get("next", "")
        context["next_url"] = next_url if next_url.startswith("/") else settings.LOGIN_REDIRECT_URL
        return context


@login_required
def logout_view(request):
    if request.method == "POST":
        # TODO: log_action(request=request, actor=request.user, action="logout", ...)
        logout(request)
    return redirect(settings.LOGOUT_REDIRECT_URL)


class ChallengeThrottle(AnonRateThrottle):
    """Ограничение на выдачу challenge — не даёт заваливать эндпоинт запросами."""

    rate = "30/min"


class ChallengeView(APIView):
    """Шаг 1: выдать одноразовый challenge для подписи на токене."""

    permission_classes = [AllowAny]
    throttle_classes = [ChallengeThrottle]

    def post(self, request):
        challenge, ttl = issue_challenge()
        data = ChallengeResponseSerializer({"challenge": challenge, "expires_in": ttl}).data
        return Response(data, status=status.HTTP_200_OK)


class CertificateLoginView(APIView):
    """
    Шаг 2: приём сертификата, подписи и challenge.

    Валидирует форму данных, разбирает сертификат, проверяет что
    challenge не истёк. Саму аутентификацию (подпись + поиск
    пользователя) делегирует services.authenticate_by_certificate.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CertificateLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payload = serializer.validated_data

        try:
            consume_challenge(payload["challenge"])
        except ChallengeInvalidError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            parsed_cert = parse_certificate(payload["certificate"])
        except CertificateParseError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = authenticate_by_certificate(
                parsed_cert=parsed_cert,
                signature_b64=payload["signature"],
                challenge=payload["challenge"],
                request=request,
            )
        except AuthenticationFailedError as exc:
            # Единый ответ на неверную подпись / неизвестный сертификат / блокировку axes —
            # намеренно без деталей, чтобы не подсказывать атакующему причину отказа.
            # TODO: log_action(..., action="login_failed", details={"thumbprint": parsed_cert.thumbprint_sha256})
            return Response({"detail": str(exc)}, status=status.HTTP_401_UNAUTHORIZED)

        # CertificateAuthBackend уже подтвердил личность — django login() создаёт
        # сессию и привязывает backend к ней (нужно для последующих проверок прав).
        login(request, user, backend="apps.accounts.backends.CertificateAuthBackend")

        # TODO: log_action(..., action="login_success", details={"certificate_thumbprint": parsed_cert.thumbprint_sha256})

        return Response(
            {
                "detail": "Вход выполнен.",
                "user": {
                    "id": user.id,
                    "full_name": user.full_name,
                    "role": getattr(user, "role", None),
                },
            }
        )
