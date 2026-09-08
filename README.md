# django-rutoken-login

Passwordless authentication for Django using Rutoken USB smart-card tokens. Challenge/response over asymmetric crypto (RSA/ECDSA + SHA-256) — the private key never leaves the hardware token, the server only ever sees a signature.

Extracted from a production system (a judicial case registry) where password-based login was a hard "no" by requirement. Battle-tested against real hardware through the "Адаптер Рутокен Плагин" browser extension.

## Why this exists

Most Rutoken integration examples out there are either vendor sample code that doesn't map cleanly onto Django's auth stack, or internal tooling nobody open-sources. This is a working `AUTHENTICATION_BACKENDS` implementation plus the frontend glue code, minus the parts that were specific to the project it came from.

## How it works

```
Browser                                   Django
   │                                         │
   │  POST /api/accounts/auth/challenge/     │
   │ ───────────────────────────────────────▶│  random token, cached in Redis, 60s TTL
   │  { challenge, expires_in }               │
   │ ◀───────────────────────────────────────│
   │                                         │
   │  (plugin signs `challenge` with the      │
   │   token's private key, PIN required)     │
   │                                         │
   │  POST /api/accounts/auth/login/          │
   │  { certificate, signature, challenge }   │
   │ ───────────────────────────────────────▶│  1. challenge valid & unused? consume it
   │                                         │  2. certificate parses as X.509 DER?
   │                                         │  3. thumbprint registered & not revoked/expired?
   │                                         │  4. signature verifies against the cert's public key?
   │                                         │  5. django-axes hasn't locked this thumbprint/IP?
   │  200 OK + session cookie                 │
   │  or 400/401                             │
   │ ◀───────────────────────────────────────│
```

`CertificateAuthBackend` plugs into Django's normal `authenticate()` pipeline and sits *after* `axes.backends.AxesBackend`, so failed-attempt tracking and lockouts come for free — no custom rate-limiting code needed.

Full breakdown of the crypto contract, endpoint schemas, and the (undocumented) quirks of the Rutoken plugin's data format: [`docs/RUTOKEN_LOGIN.md`](docs/RUTOKEN_LOGIN.md).

## Stack

- Django 4.2+, DRF for the two API endpoints
- `cryptography` for X.509 parsing and signature verification (RSA-PKCS1v15 and ECDSA, both SHA-256)
- Redis (`django-redis`) as the challenge store — required, not optional, once you're running more than one gunicorn worker
- `django-axes` for lockout after repeated failures
- Vanilla JS on the frontend (no framework), talking to the official Rutoken plugin loader

## Repo layout

```
apps/accounts/
├── models.py        User, TokenCertificate (cert ↔ user binding)
├── backends.py       CertificateAuthBackend — signature verification, no password logic at all
├── services.py       challenge issue/consume, X.509 parsing
├── serializers.py    request validation (DRF)
├── views.py           ChallengeView, CertificateLoginView, LoginPageView
└── urls.py

templates/accounts/login.html   full login UI + JS orchestration (plugin detection → PIN → sign → submit)
static/vendor/                   official Rutoken plugin loader (vendored, not ours — see LICENSE)
docs/RUTOKEN_LOGIN.md            endpoint reference, crypto contract, integration checklist
```

## Installation

```bash
pip install -r requirements.txt
```

1. Copy `apps/accounts/` into your project.
2. Copy `templates/accounts/login.html` and `static/vendor/`.
3. Merge the relevant bits of `example_settings_snippet.py` into your `settings.py`. Pay attention to `AUTH_USER_MODEL`, backend ordering in `AUTHENTICATION_BACKENDS`, and the Redis cache config — this is the part people get wrong.
4. Merge `example_urls_snippet.py` into your root `urls.py`.
5. `python manage.py makemigrations accounts && python manage.py migrate`
6. Register a user + certificate:

```python
from apps.accounts.models import User, TokenCertificate
from django.utils import timezone
import datetime

user = User.objects.get(username="jdoe")
TokenCertificate.objects.create(
    user=user,
    serial_number="...",     # pull these from the actual cert —
    thumbprint="...",        # openssl x509 -noout -fingerprint -sha256 -serial -subject -issuer -dates
    subject_dn="...",
    issuer_dn="...",
    valid_from=timezone.now(),
    valid_to=timezone.now() + datetime.timedelta(days=365),
)
```

(Or just use `/admin/` — both models are registered.)

7. Hit `/login/` with a token plugged in.

## API

| Endpoint | Auth | Notes |
|---|---|---|
| `POST /api/accounts/auth/challenge/` | anonymous, throttled 30/min | Returns a single-use, 60s-TTL challenge. Redis-backed. |
| `POST /api/accounts/auth/login/` | anonymous | `{certificate, signature, challenge}`, all base64. 400 on malformed input, 401 on failed auth (deliberately generic — doesn't leak *why*). |

Full request/response bodies and error shapes: `docs/RUTOKEN_LOGIN.md`.

## Not included, on purpose

- **Self-service certificate enrollment.** An admin binds `TokenCertificate` rows manually (or via `/admin/`). There's no "register your own token" flow — that's a deliberate scope cut, not an oversight.
- **CRL/OCSP revocation checking.** Only the local `TokenCertificate.is_revoked` flag is checked. If you need live revocation status against a CA, that's on you to add.
- **Any password fallback.** This is intentionally single-purpose. If you need a break-glass path for initial admin setup, wire up `ModelBackend` conditionally on your end — don't bolt it onto this module.

## Gotchas that cost real debugging time

- **Redis is not optional.** The challenge is written by one process and read by another (different gunicorn worker handling the login POST). `LocMemCache` will silently break this in any multi-worker deployment — you'll get "challenge expired" on every single attempt and no useful error telling you why.
- **The Rutoken plugin returns everything as colon-separated hex, not base64** — serial numbers, key IDs, and critically, the signature from `rawSign()`. The backend's serializer expects base64. The conversion is already handled in `login.html` (`hexToBase64()`), but if you're extending this and see `400: "Подпись передана в некорректном формате"`, this is why.
- **`rawSign()` with `computeHash: false` wants the hash itself as colon-hex too**, not a plain hex string — undocumented as far as I could find; confirmed against the Rutoken forum (linked in a code comment). Get this wrong and the plugin fails with an opaque `{error: 'Could not execute command', message: 2}`.
- **`SESSION_COOKIE_SECURE=True` behind plain HTTP silently breaks login.** No error dialog, no server log worth mentioning — the browser just never sends the cookie back, and you get a CSRF failure that has nothing to do with CSRF. Don't flip this to `True` until there's real TLS in front of the app.

## License

Code under `apps/`, `templates/`, `docs/` is MIT — see [`LICENSE`](LICENSE).

`static/vendor/rutoken-plugin.min.js` is third-party (© CJSC Aktiv-Soft) under the terms in `static/vendor/rutoken-plugin.LICENSE.txt`. Not MIT, don't relicense it.
