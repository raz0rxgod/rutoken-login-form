"""
apps/accounts/models.py

Модели для входа по сертификату на носителе Рутокен (challenge/response,
без пароля). См. docs/RUTOKEN_LOGIN.md — полное описание схемы и того,
как перенести этот модуль на свой проект.

  - User.password остаётся технически обязательным полем Django
    (наследие AbstractUser), но реально не используется как способ
    входа — вход только через TokenCertificate (см. ниже) и
    apps.accounts.backends.CertificateAuthBackend.
  - Один пользователь может иметь несколько записей TokenCertificate
    (например, после перевыпуска сертификата) — валиден для входа
    только тот, у которого TokenCertificate.is_valid_now == True.

ПРИМЕЧАНИЕ ПРО ПЕРЕНОС НА СВОЙ ПРОЕКT: это извлечение из более крупной
системы (реестр лиц для суда), где у User было поле court (ForeignKey на
модель судов) для row-level security. Здесь это поле сознательно убрано,
чтобы репозиторий не тянул за собой чужую модель Court — если вам нужна
похожая привязка (к организации/подразделению/офису), просто добавьте
своё поле сюда. Как это было устроено в исходном проекте — см.
docs/RUTOKEN_LOGIN.md, раздел 8, пункт про перенос.
"""

from django.contrib.auth.models import AbstractUser
from django.conf import settings
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    """Пример ролей — замените под свою систему прав, поле опционально."""

    ADMIN = "admin", "Администратор"
    OPERATOR = "operator", "Оператор"
    VIEWER = "viewer", "Пользователь с правом просмотра"
    AUDITOR = "auditor", "Аудитор"


class User(AbstractUser):
    """
    Кастомная модель пользователя — точка привязки для сертификатов
    Рутокена (см. TokenCertificate ниже). Обязательна как AUTH_USER_MODEL,
    если хотите использовать её как есть, либо перенесите поля ниже
    (full_name как минимум) на свою существующую модель пользователя и
    поменяйте TokenCertificate.user на неё.
    """

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.VIEWER,
        verbose_name="Роль",
        help_text="Для отображения в интерфейсе. Фактические права — через Django Groups/Permissions.",
    )
    full_name = models.CharField(max_length=255, blank=True, verbose_name="ФИО")
    is_account_active = models.BooleanField(
        default=True,
        verbose_name="Учётная запись активна",
        help_text="Ручная деактивация администратором — отдельно от is_active Django, для явного разграничения смысла.",
    )

    class Meta:
        verbose_name = "Пользователь"
        verbose_name_plural = "Пользователи"

    def __str__(self) -> str:
        return self.full_name or self.username

    @property
    def has_active_certificate(self) -> bool:
        """Есть ли у пользователя хотя бы один действующий сертификат."""
        return self.certificates.filter(is_revoked=False).exists()


class TokenCertificate(models.Model):
    """
    Сертификат на носителе Рутокен, привязанный к учётной записи.

    Заполняется вручную администратором (см. docs/RUTOKEN_LOGIN.md,
    раздел 5) после того, как реальный сертификат снят с носителя.
    Входить в систему можно только по сертификату, для которого
    is_valid_now возвращает True.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="certificates",
        verbose_name="Пользователь",
    )
    serial_number = models.CharField(max_length=64, unique=True, verbose_name="Серийный номер сертификата")
    thumbprint = models.CharField(
        max_length=64,
        unique=True,
        verbose_name="Отпечаток (SHA-256)",
        help_text="Используется для быстрого и однозначного поиска сертификата при входе.",
    )
    subject_dn = models.CharField(max_length=500, verbose_name="Владелец (Subject DN)")
    issuer_dn = models.CharField(max_length=500, verbose_name="Издатель (Issuer DN)")
    valid_from = models.DateTimeField(verbose_name="Действителен с")
    valid_to = models.DateTimeField(verbose_name="Действителен по")
    is_revoked = models.BooleanField(default=False, verbose_name="Отозван")
    revoked_at = models.DateTimeField(null=True, blank=True, verbose_name="Дата отзыва")
    revoked_reason = models.CharField(max_length=255, blank=True, verbose_name="Причина отзыва")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата привязки к учётной записи")

    class Meta:
        verbose_name = "Сертификат Рутокена"
        verbose_name_plural = "Сертификаты Рутокена"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.subject_dn} ({self.serial_number})"

    @property
    def is_valid_now(self) -> bool:
        """Сертификат не отозван и находится в пределах срока действия."""
        now = timezone.now()
        return (not self.is_revoked) and self.valid_from <= now <= self.valid_to

    def revoke(self, reason: str = "") -> None:
        """Отозвать сертификат (например, при утере носителя)."""
        self.is_revoked = True
        self.revoked_at = timezone.now()
        self.revoked_reason = reason
        self.save(update_fields=["is_revoked", "revoked_at", "revoked_reason"])
