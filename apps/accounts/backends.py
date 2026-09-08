"""
apps/accounts/backends.py

Часть 3 из 4: backend аутентификации по сертификату Рутокена.

Подключается в settings.py ПОСЛЕ axes.backends.AxesBackend:

    AUTHENTICATION_BACKENDS = [
        "axes.backends.AxesBackend",
        "apps.accounts.backends.CertificateAuthBackend",
    ]

Как это работает вместе с axes:
  - django.contrib.auth.authenticate(request, **credentials) сначала
    отдаёт credentials в AxesBackend. Тот проверяет, не заблокирован ли
    клиент (по IP + "username" из credentials), и если всё ок — вызывает
    следующий backend в списке, то есть CertificateAuthBackend ниже.
  - Django сам оборачивает вызов authenticate(): при возврате None шлёт
    сигнал user_login_failed, при возврате пользователя — user_logged_in.
    AxesBackend слушает эти сигналы и считает попытки.
  - Поэтому здесь принципиально: НИКОГДА не поднимать исключение при
    неверной подписи/сертификате — только return None. Иначе сигнал
    не уйдёт и axes не зафиксирует попытку.
  - В credentials обязательно передаётся `username=thumbprint` (см.
    services.authenticate_by_certificate) — это и есть тот идентификатор,
    по которому axes ведёт счётчик неудачных попыток и блокировку.
"""

from __future__ import annotations

import base64
import binascii
import logging

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from .models import TokenCertificate

logger = logging.getLogger("accounts.auth")

User = get_user_model()


class CertificateAuthBackend(BaseBackend):
    """
    Backend, не имеющий отношения к паролям: единственный поддерживаемый
    набор credentials — сертификат + подпись challenge с носителя.
    """

    def authenticate(
        self,
        request,
        certificate_der: bytes = None,
        thumbprint: str = None,
        signature: str = None,
        challenge: str = None,
        **kwargs,
    ):
        if not (certificate_der and thumbprint and signature and challenge):
            return None

        cert_record = self._get_valid_certificate_record(thumbprint)
        if cert_record is None:
            logger.warning("Вход отклонён: сертификат %s не зарегистрирован либо недействителен.", thumbprint)
            return None

        if not self._verify_signature(certificate_der, signature, challenge):
            logger.warning("Вход отклонён: неверная подпись challenge для сертификата %s.", thumbprint)
            return None

        user = cert_record.user
        if not user.is_active or not user.is_account_active:
            logger.warning("Вход отклонён: учётная запись %s деактивирована.", user.username)
            return None

        logger.info("Успешный вход по сертификату: пользователь %s.", user.username)
        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id, is_active=True)
        except User.DoesNotExist:
            return None

    @staticmethod
    def _get_valid_certificate_record(thumbprint: str) -> TokenCertificate | None:
        """Сертификат должен быть зарегистрирован администратором и действителен сейчас."""
        try:
            record = TokenCertificate.objects.select_related("user").get(thumbprint=thumbprint)
        except TokenCertificate.DoesNotExist:
            return None
        return record if record.is_valid_now else None

    @staticmethod
    def _verify_signature(certificate_der: bytes, signature_b64: str, challenge: str) -> bool:
        """
        Проверить, что signature — валидная подпись строки challenge,
        сделанная закрытым ключом, соответствующим открытому ключу
        из сертификата. Поддержаны RSA и ECDSA (обе схемы встречаются
        на носителях Рутокен в зависимости от типа ключа).
        """
        try:
            signature = base64.b64decode(signature_b64, validate=True)
        except (binascii.Error, ValueError):
            return False

        try:
            cert = x509.load_der_x509_certificate(certificate_der)
            public_key = cert.public_key()
            message = challenge.encode("utf-8")

            if isinstance(public_key, rsa.RSAPublicKey):
                public_key.verify(signature, message, padding.PKCS1v15(), hashes.SHA256())
            elif isinstance(public_key, ec.EllipticCurvePublicKey):
                public_key.verify(signature, message, ec.ECDSA(hashes.SHA256()))
            else:
                logger.warning("Неподдерживаемый тип открытого ключа в сертификате: %s", type(public_key))
                return False
            return True
        except InvalidSignature:
            return False
        except Exception:  # noqa: BLE001 — любая ошибка разбора = отказ, не 500-я
            logger.exception("Ошибка при проверке подписи challenge.")
            return False
