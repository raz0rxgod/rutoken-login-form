# Вход по Рутокену — как устроен и как перенести на другой сайт

Описывает готовый, рабочий модуль входа по сертификату на носителе
Рутокен (challenge/response, без пароля). Написано так, чтобы можно
было скопировать компоненты на другой Django-проект без повторного
чтения всей остальной документации реестра.

## 1. Общая схема (challenge/response)

```
Браузер                              Сервер (Django)
   │                                       │
   │  GET /login/                          │
   │ ─────────────────────────────────────▶│  рендерит login.html
   │                                       │
   │  (плагин Рутокена: пользователь       │
   │   нажимает «Считать токен», вводит    │
   │   PIN, JS получает сертификат)        │
   │                                       │
   │  POST /api/accounts/auth/challenge/   │
   │ ─────────────────────────────────────▶│  генерирует случайную строку,
   │                                       │  кладёт в Redis на 60 сек
   │  {challenge, expires_in}              │
   │ ◀─────────────────────────────────────│
   │                                       │
   │  (плагин подписывает challenge        │
   │   закрытым ключом на носителе)        │
   │                                       │
   │  POST /api/accounts/auth/login/       │
   │  {certificate, signature, challenge}  │
   │ ─────────────────────────────────────▶│  1. challenge существует? удалить (single-use)
   │                                       │  2. сертификат парсится (DER)?
   │                                       │  3. thumbprint есть в TokenCertificate и не отозван/просрочен?
   │                                       │  4. подпись challenge валидна для открытого ключа из сертификата?
   │                                       │  5. django-axes не заблокировал этот thumbprint/IP?
   │  200 + Set-Cookie (сессия)            │
   │  либо 401/400                         │
   │ ◀─────────────────────────────────────│
```

Ключевая идея: **приватный ключ никогда не покидает носитель** — браузер
только просит плагин подписать случайную строку, сервер проверяет
подпись открытым ключом из уже заранее зарегистрированного сертификата.
Пароль нигде не участвует.

## 2. Файлы модуля — что копировать

| Файл | Роль |
|---|---|
| `apps/accounts/models.py` | `User` (кастомная модель, `AUTH_USER_MODEL`), `TokenCertificate` (сертификат ↔ пользователь) |
| `apps/accounts/backends.py` | `CertificateAuthBackend` — проверяет подпись, ищет пользователя по сертификату |
| `apps/accounts/services.py` | генерация/проверка challenge (Redis), разбор сертификата (`cryptography`), оркестрация `authenticate()` |
| `apps/accounts/serializers.py` | валидация формы входящих данных (DRF) |
| `apps/accounts/views.py` | `ChallengeView`, `CertificateLoginView` (DRF `APIView`), `LoginPageView` |
| `apps/accounts/urls.py` | маршруты API (см. ниже) |
| `templates/accounts/login.html` | HTML-страница + весь JS-оркестратор общения с плагином и API |
| `static/vendor/rutoken-plugin.min.js` | **официальный** JS-загрузчик от Рутокена/Aktiv — определяет браузерное расширение «Адаптер Рутокен Плагин» и оборачивает его API в Promise. Не наш код — берётся с сайта Рутокена вместе с самим плагином/SDK, лицензия — `rutoken-plugin.LICENSE.txt` рядом с файлом. |

Не входит в этот список, но нужно из остального проекта:
`apps/audit/services.py::log_action` (логирование `login_success`/
`login_failed`) — можно убрать вызовы или подставить свою функцию
логирования, если переносите на сайт без такого журнала.

## 3. Эндпоинты

### `POST /api/accounts/auth/challenge/`

Анонимный (`AllowAny`), троттлинг `30/min` с одного IP.

Запрос — без тела.

Ответ `200`:
```json
{ "challenge": "aR8I_leCAM-44yast5Hkh8ynDjOfAun9gKQf2ehO9lQ", "expires_in": 60 }
```

`challenge` живёт 60 секунд в Redis (`CHALLENGE_TTL_SECONDS` в
`services.py`) и одноразовый — удаляется из кеша при первой попытке
входа, независимо от того, успешна она или нет.

### `POST /api/accounts/auth/login/`

Анонимный (`AllowAny`) — сессии на этом шаге ещё нет.

Запрос:
```json
{
  "certificate": "<сертификат в DER, base64>",
  "signature": "<подпись challenge закрытым ключом, base64>",
  "challenge": "<строка, полученная от /challenge/>"
}
```

Ответ `200`:
```json
{ "detail": "Вход выполнен.", "user": { "id": 1, "full_name": "...", "role": "operator" } }
```
плюс `Set-Cookie` с сессией (Django session + CSRF).

Ответ `400` — форма данных не прошла валидацию (не base64, пустое
значение) или challenge истёк/не найден:
```json
{ "signature": ["Подпись передана в некорректном формате (ожидался base64)."] }
```

Ответ `401` — challenge и сертификат синтаксически корректны, но
аутентификация не удалась (неверная подпись, сертификат не
зарегистрирован/отозван/просрочен, учётная запись деактивирована, или
`django-axes` заблокировал этот `thumbprint`+IP после серии неудач).
Специально без деталей — чтобы не подсказывать атакующему причину:
```json
{ "detail": "Не удалось подтвердить подлинность сертификата." }
```

### `GET /login/`

Обычная Django-view (не API), рендерит `templates/accounts/login.html`.
Если пользователь уже аутентифицирован — редиректит на
`LOGIN_REDIRECT_URL`. Параметр `?next=/куда-то/` уважается, только если
это локальный путь (защита от open redirect).

## 4. Зависимости

**Python** (добавить в `requirements.txt`):
```
djangorestframework   # DRF-эндпоинты challenge/login
cryptography          # разбор сертификата и проверка подписи (RSA/ECDSA + SHA-256)
django-axes            # блокировка после серии неудачных попыток
django-redis            # кеш для challenge (см. ниже, обязателен для прод — не locmem)
```

**JS** (в `static/vendor/`): `rutoken-plugin.min.js` + файл лицензии —
официальный загрузчик, скачивается с сайта производителя вместе с
самим «Рутокен Плагин» (https://www.rutoken.ru/products/all/rutoken-plugin/).
Не переписывать/минифицировать заново — это чужой код с отдельной
лицензией, только подключать как есть.

**Django settings**, которые обязательно нужны на новом проекте:

```python
AUTH_USER_MODEL = "accounts.User"  # или как называется ваше приложение

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesBackend",                       # порядок важен — axes первым
    "apps.accounts.backends.CertificateAuthBackend",    # наш backend вторым
]

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": os.environ.get("REDIS_URL", "redis://localhost:6379/1"),
        "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
    }
}
# ВАЖНО: challenge хранится через django.core.cache.cache.set()/get().
# Если gunicorn работает несколькими воркерами (а он всегда так работает
# в проде), challenge, выданный одним воркером, должен быть виден
# другому воркеру, принявшему POST /auth/login/ — in-memory кеш
# (LocMemCache) для этого не годится, между процессами не расшарен.
# Обязательно Redis или Memcached, не LocMemCache.

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1  # часы
AXES_LOCKOUT_PARAMETERS = ["ip_address", "username"]  # "username" здесь = thumbprint сертификата
AXES_RESET_ON_SUCCESS = True
AXES_HANDLER = "axes.handlers.cache.AxesCacheHandler"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["rest_framework.authentication.SessionAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_RATES": {"anon": "60/min", "user": "1000/min"},
}

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"
```

И в `urls.py`:
```python
path("login/", LoginPageView.as_view(), name="login"),
path("api/accounts/", include("apps.accounts.urls")),  # challenge/ + login/
```

## 5. Данные, которые нужно подготовить вручную

Модуль **не создаёт пользователей и не привязывает сертификаты сам** —
это делает администратор через `/admin/` (или свою management-команду)
для каждого нового оператора:

1. `User` — обычная учётная запись (пароль не используется как способ
   входа, но поле технически обязательно — Django создаёт
   unusable-password).
2. `TokenCertificate`, привязанный к этому `User`:
   - `serial_number`, `thumbprint` (SHA-256 отпечаток сертификата),
     `subject_dn`, `issuer_dn`, `valid_from`, `valid_to` — снимаются
     с реального сертификата на носителе (например, через штатную
     утилиту Рутокена или `openssl x509 -noout -fingerprint -sha256
     -serial -subject -issuer -dates` после экспорта сертификата в
     файл).
   - `is_revoked=False` по умолчанию — `revoke()` вызывается вручную,
     если носитель утерян/скомпрометирован.

Без предварительно созданной записи `TokenCertificate` с правильным
`thumbprint` вход всегда будет отклонён с 401, даже если сертификат и
подпись абсолютно корректны — это осознанное поведение («сертификат
должен быть в списке допущенных», а не просто криптографически валиден).

## 6. Криптографический контракт (backend)

`CertificateAuthBackend._verify_signature()`:
- сертификат передаётся в DER, base64-строкой;
- подпись — тоже в base64, покрывает **UTF-8 байты строки `challenge`
  как есть** (не хеш от неё — хеширование, если нужно, происходит
  внутри самой схемы подписи алгоритма, см. ниже);
- поддержаны два типа ключей на носителе: RSA (`PKCS1v15` + SHA-256) и
  ECDSA (SHA-256). Тип определяется автоматически по открытому ключу
  из сертификата — ничего дополнительно передавать не нужно.
- Любой другой тип ключа → отказ (`return False`, не исключение).

## 7. Важный урок с фронтенда — формат данных от плагина

«Рутокен Плагин» отдаёт **все** бинарные значения (серийный номер,
идентификаторы ключа/сертификата, и в том числе результат `rawSign()`)
в виде **hex-строки с двоеточиями между байтами** (`"6e:4a:5f:44:..."`),
а не в base64. Бэкенд же (см. `serializers.py`) жёстко требует base64
для полей `certificate`/`signature`. Поэтому на фронте обязательна
конвертация hex → base64 перед отправкой (см. функцию `hexToBase64()`
в `login.html`) — без неё бэкенд отклоняет запрос с `400 "Подпись
передана в некорректном формате (ожидался base64)"`, хотя сама подпись
на носителе была сделана корректно.

Отдельно: `rawSign()` с `computeHash: false` принимает сам хеш **тоже**
в hex-с-двоеточиями (не сплошной hex) — иначе плагин отвечает `{error:
'Could not execute command', message: 2}`. Оба нюанса не задокументированы
явно в публичной документации Рутокена на момент написания — найдены
опытным путём (см. форум forum.rutoken.ru/topic/3396/) и закомментированы
прямо в коде `login.html`.

## 8. Чек-лист переноса на другой сайт

1. Скопировать `apps/accounts/{models,backends,services,serializers,views,urls}.py`.
2. Скопировать `templates/accounts/login.html` и `static/vendor/rutoken-plugin.min.js` (+ LICENSE).
3. Поправить импорты, если приложение будет называться не `accounts`
   (в частности, `AUTH_USER_MODEL` и путь в `AUTHENTICATION_BACKENDS`).
4. Убрать/заменить вызовы `apps.audit.services.log_action(...)` в
   `views.py`, если на новом сайте нет такого журнала — иначе будет
   `ImportError`.
5. Добавить настройки из раздела 4 в `settings.py` нового проекта, в
   первую очередь — **Redis-кеш**, без него challenge не переживёт
   несколько воркеров gunicorn.
6. Установить зависимости из раздела 4 (`pip install`).
7. `makemigrations`/`migrate` для `accounts.User`/`TokenCertificate`
   (или свои эквивалентные модели, если объединяете с существующей
   моделью пользователя — тогда `TokenCertificate.user` нужно
   перенаправить на неё).
8. Создать хотя бы одного пользователя и привязать к нему
   `TokenCertificate` вручную (раздел 5) — без этого шага входить будет
   некому.
9. Реальное подключённое USB-устройство + установленное расширение
   «Адаптер Рутокен Плагин» в браузере — без него `window.rutoken`
   не появится, и `ensurePluginLoaded()` в `login.html` сразу бросит
   понятную ошибку с этим текстом.
10. Cookies: если сайт без HTTPS — `SESSION_COOKIE_SECURE`/
    `CSRF_COOKIE_SECURE` в settings.py вашего проекта не должны быть
    `True` без реального TLS-сертификата перед сайтом, иначе браузер
    не сохранит ни сессию, ни CSRF-cookie, и вход будет падать с
    «Ошибка проверки CSRF» ещё до какой-либо бизнес-логики.

## 9. Что не входит в этот модуль (сознательно)

- Импорт/массовая регистрация сертификатов — только вручную через
  `/admin/` либо свой скрипт поверх модели `TokenCertificate`.
- UI для самостоятельной привязки пользователем своего сертификата —
  только администратор регистрирует сертификаты за пользователя.
- Отзыв по CRL/OCSP (проверка у удостоверяющего центра, не отозван ли
  сертификат централизованно) — проверяется только локальный флаг
  `TokenCertificate.is_revoked`, который выставляется вручную.
