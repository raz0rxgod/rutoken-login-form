# django-rutoken-login

Готовый, рабочий модуль входа в Django-приложение по сертификату на
аппаратном носителе **Рутокен** — без пароля, по схеме challenge/response.
Извлечён из реальной боевой системы (реестр для судебной системы) и
проверен на настоящем носителе через расширение браузера «Адаптер
Рутокен Плагин».

## Как это выглядит

Пользователь подключает Рутокен → нажимает «Считать токен» → плагин
находит сертификат → пользователь вводит PIN → плагин подписывает
одноразовый challenge закрытым ключом с носителя → сервер проверяет
подпись открытым ключом из **заранее зарегистрированного** сертификата
и создаёт сессию. Приватный ключ никогда не покидает носитель.

Полный разбор схемы, эндпоинтов и внутреннего устройства — в
[`docs/RUTOKEN_LOGIN.md`](docs/RUTOKEN_LOGIN.md). Этот README — только
про то, как быстро подключить модуль к своему проекту.

## Что внутри

```
apps/accounts/          — Django-приложение: модели, backend аутентификации,
                           challenge/response API, вход/выход
templates/accounts/     — страница входа (HTML + весь JS-оркестратор)
static/vendor/          — официальный JS-загрузчик плагина от Рутокена (не наш код)
docs/RUTOKEN_LOGIN.md   — подробная документация: схема, эндпоинты, крипто-контракт,
                           чек-лист переноса на свой проект
example_settings_snippet.py — что добавить в settings.py вашего проекта
example_urls_snippet.py     — что добавить в urls.py вашего проекта
```

## Требования

- Django 4.2+
- **Redis** (обязателен для challenge-кеша — не работает на `LocMemCache`
  в проде с несколькими воркерами gunicorn, см. документацию)
- Реальный носитель Рутокен + установленное расширение браузера
  «Адаптер Рутокен Плагин» ([rutoken.ru/products/all/rutoken-plugin](https://www.rutoken.ru/products/all/rutoken-plugin/))
  для реального входа. Без плагина страница входа откроется, но
  корректно покажет ошибку «не найдено расширение…» — это ожидаемо.

## Быстрый старт

```bash
pip install -r requirements.txt
```

1. Скопируйте `apps/accounts/` в свой проект (или установите этот
   репозиторий как git submodule / скопируйте вручную).
2. Скопируйте `templates/accounts/login.html` и `static/vendor/` тоже.
3. Перенесите нужные куски из `example_settings_snippet.py` в свой
   `settings.py` — особое внимание на `AUTH_USER_MODEL`,
   `AUTHENTICATION_BACKENDS` (порядок важен) и `CACHES` (Redis).
4. Перенесите куски из `example_urls_snippet.py` в свой корневой `urls.py`.
5. `python manage.py makemigrations accounts && python manage.py migrate`
6. Создайте пользователя и привяжите к нему сертификат:

```bash
python manage.py createsuperuser
python manage.py shell
```
```python
from apps.accounts.models import User, TokenCertificate
from django.utils import timezone
import datetime

user = User.objects.get(username="ваш_логин")
TokenCertificate.objects.create(
    user=user,
    serial_number="...",   # снять с реального сертификата
    thumbprint="...",      # SHA-256 отпечаток сертификата
    subject_dn="...",
    issuer_dn="...",
    valid_from=timezone.now(),
    valid_to=timezone.now() + datetime.timedelta(days=365),
)
```

(Проще то же самое сделать через `/admin/` — модели зарегистрированы в
`apps/accounts/admin.py`.)

7. Откройте `/login/`, подключите носитель, входите.

Как снять `serial_number`/`thumbprint`/даты с реального сертификата и
что означают все эти поля — раздел 5 в `docs/RUTOKEN_LOGIN.md`.

## Что НЕ входит в этот модуль

- UI для самостоятельной регистрации сертификата пользователем — только
  администратор вручную привязывает сертификат к учётной записи.
- Проверка отзыва по CRL/OCSP у удостоверяющего центра — только локальный
  флаг `TokenCertificate.is_revoked`, выставляется вручную.
- Вход по паролю — сознательно не предусмотрен нигде, кроме собственного
  break-glass-механизма, который вы добавляете на своей стороне, если
  он вам нужен (в этом репозитории такого нет — модуль рассчитан на то,
  что пароль вообще не способ входа).

## Известный нюанс формата данных (уже исправлено в коде)

«Рутокен Плагин» отдаёт все бинарные значения (включая результат
подписи) как hex-строку с двоеточиями между байтами, а не в base64,
хотя бэкенд ожидает base64. Конвертация уже реализована в
`templates/accounts/login.html` (`hexToBase64()`) — подробности и
почему это не очевидно из документации Рутокена — раздел 7 в
`docs/RUTOKEN_LOGIN.md`.

## Лицензия

Код в `apps/`, `templates/`, `docs/` — MIT, см. [`LICENSE`](LICENSE).

`static/vendor/rutoken-plugin.min.js` — сторонний код (© CJSC
Aktiv-Soft), распространяется на условиях
`static/vendor/rutoken-plugin.LICENSE.txt`, не MIT.
