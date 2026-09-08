"""
apps/accounts/services.py

Часть 2 из 4: вспомогательная логика приёма данных для входа —
генерация/хранение challenge и разбор присланного сертификата.

Проверка подписи, поиск пользователя по сертификату и блокировка
по django-axes реализуются в части 3 (см. authenticate_by_certificate,
пока это заглушка с чётко описанным контрактом).
"""

from __future__ import annotations

import base64
import binascii
import secrets
from dataclasses import dataclass
from datetime import datetime

from cryptography import x509
from cryptography.hazmat.backends import default_backend
from django.contrib.auth import authenticate
from django.core.cache import cache

CHALLENGE_CACHE_PREFIX = "rutoken_challenge:"
CHALLENGE_TTL_SECONDS = 60  # столько времени пользователь успевает ввести PIN


class CertificateParseError(Exception):
    """Сертификат нечитаем или повреждён — не путать с невалидностью по сроку/CA."""


class ChallengeInvalidError(Exception):
    """Challenge не найден, истёк или уже был использован (защита от replay-атак)."""


class AuthenticationFailedError(Exception):
    """
    Общая ошибка отказа во входе: неверная подпись, незарегистрированный
    сертификат, деактивированная учётная запись или блокировка django-axes
    после серии неудачных попыток. Специально не детализируется дальше —
    чтобы не давать атакующему подсказок, какая часть проверки не прошла.
    """


@dataclass
class ParsedCertificate:
    """Данные, извлечённые из сертификата, для передачи в часть 3."""

    serial_number: str
    thumbprint_sha256: str
    subject_dn: str
    issuer_dn: str
    valid_from: datetime
    valid_to: datetime
    der_bytes: bytes


def issue_challenge() -> tuple[str, int]:
    """
    Сгенерировать одноразовый challenge и сохранить его в кеше (Redis).

    Возвращает (challenge, ttl_seconds). Хранение в cache, а не в БД —
    осознанно: значение живёт секунды, не должно попадать в историю/аудит
    и должно автоматически истекать без отдельной задачи на очистку.
    """
    challenge = secrets.token_urlsafe(32)
    cache.set(CHALLENGE_CACHE_PREFIX + challenge, True, timeout=CHALLENGE_TTL_SECONDS)
    return challenge, CHALLENGE_TTL_SECONDS


def consume_challenge(challenge: str) -> None:
    """
    Проверить, что challenge существует (не истёк), и сразу удалить его.

    Удаление до, а не после проверки подписи — намеренно: даже если
    подпись окажется неверной, повторно этот challenge использовать
    уже нельзя. Каждая попытка входа требует нового challenge.
    """
    key = CHALLENGE_CACHE_PREFIX + challenge
    if not cache.get(key):
        raise ChallengeInvalidError("Challenge истёк или уже был использован. Запросите новый.")
    cache.delete(key)


def parse_certificate(certificate_b64: str) -> ParsedCertificate:
    """
    Декодировать base64 -> DER и извлечь поля сертификата.

    Здесь проверяется только то, что сертификат синтаксически корректен
    и читаем библиотекой `cryptography`. Действителен ли он (срок,
    отзыв, доверенный ли издатель) и совпадает ли с ранее привязанным
    TokenCertificate — проверяет часть 3.
    """
    try:
        der_bytes = base64.b64decode(certificate_b64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CertificateParseError("Не удалось декодировать сертификат из base64.") from exc

    try:
        cert = x509.load_der_x509_certificate(der_bytes, default_backend())
    except ValueError as exc:
        raise CertificateParseError("Файл сертификата повреждён либо имеет неверный формат (ожидался DER).") from exc

    thumbprint = cert.fingerprint(cert.signature_hash_algorithm or __import__("hashlib").sha256())

    return ParsedCertificate(
        serial_number=format(cert.serial_number, "x"),
        thumbprint_sha256=thumbprint.hex(),
        subject_dn=cert.subject.rfc4514_string(),
        issuer_dn=cert.issuer.rfc4514_string(),
        valid_from=cert.not_valid_before_utc,
        valid_to=cert.not_valid_after_utc,
        der_bytes=der_bytes,
    )


def authenticate_by_certificate(parsed_cert: ParsedCertificate, signature_b64: str, challenge: str, request=None):
    """
    Провести аутентификацию через django.contrib.auth.authenticate().

    Это намеренно НЕ прямой вызов CertificateAuthBackend, а стандартный
    Django-механизм: authenticate() перебирает AUTHENTICATION_BACKENDS,
    первым идёт axes.backends.AxesBackend (проверяет блокировку и слушает
    сигналы успеха/неудачи), вторым — apps.accounts.backends.CertificateAuthBackend
    (часть 3), который и проверяет подпись с использованием parsed_cert.

    `username=thumbprint` передаётся специально для django-axes — именно
    по этому значению (в паре с IP из request) считаются попытки входа
    и работает блокировка после исчерпания лимита (см. AXES_FAILURE_LIMIT).
    """
    user = authenticate(
        request=request,
        username=parsed_cert.thumbprint_sha256,
        certificate_der=parsed_cert.der_bytes,
        thumbprint=parsed_cert.thumbprint_sha256,
        signature=signature_b64,
        challenge=challenge,
    )
    if user is None:
        # None означает и «неверная подпись/сертификат», и «заблокировано axes» —
        # разграничивать эти случаи в ответе пользователю не стоит (см. docstring класса).
        raise AuthenticationFailedError("Не удалось подтвердить подлинность сертификата.")
    return user
