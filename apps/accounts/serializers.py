"""
apps/accounts/serializers.py

Часть 2 из 4: валидация данных, приходящих от фронтенда в процессе
входа по Рутокену.

Схема входа — challenge/response:
  1. Фронтенд запрашивает одноразовый challenge (GET/POST -> ChallengeView).
  2. Плагин Рутокена подписывает challenge закрытым ключом на носителе.
  3. Фронтенд отправляет сертификат + подпись + сам challenge обратно
     (-> CertificateLoginView), сериализатор ниже проверяет только
     форму данных (это base64, непустая строка и т.д.) — подлинность
     подписи и валидность сертификата проверяются в части 3.
"""

from rest_framework import serializers


class ChallengeResponseSerializer(serializers.Serializer):
    """Ответ на запрос challenge — не привязан к модели, чисто вывод."""

    challenge = serializers.CharField()
    expires_in = serializers.IntegerField(help_text="Время жизни challenge в секундах")


class CertificateLoginSerializer(serializers.Serializer):
    """
    Входные данные для входа по сертификату.

    certificate — сертификат в DER, закодированный в base64
                  (именно так его отдаёт «Рутокен Плагин» — см. templates/accounts/login.html
                  про исправленное название и неподтверждённый JS-контракт).
    signature   — подпись значения `challenge`, тоже в base64.
    challenge   — значение, ранее выданное ChallengeView; должно быть
                  ещё не истёкшим и не использованным ранее (single-use).
    """

    certificate = serializers.CharField(
        allow_blank=False,
        error_messages={"blank": "Не передан сертификат с носителя."},
    )
    signature = serializers.CharField(
        allow_blank=False,
        error_messages={"blank": "Не передана подпись challenge."},
    )
    challenge = serializers.CharField(
        allow_blank=False,
        error_messages={"blank": "Отсутствует challenge — запросите его заново."},
    )

    def validate_certificate(self, value: str) -> str:
        if not _looks_like_base64(value):
            raise serializers.ValidationError("Сертификат передан в некорректном формате (ожидался base64).")
        return value

    def validate_signature(self, value: str) -> str:
        if not _looks_like_base64(value):
            raise serializers.ValidationError("Подпись передана в некорректном формате (ожидался base64).")
        return value


def _looks_like_base64(value: str) -> bool:
    import base64
    import binascii

    try:
        # validate=True отклоняет строки с посторонними символами
        base64.b64decode(value, validate=True)
        return True
    except (binascii.Error, ValueError):
        return False
