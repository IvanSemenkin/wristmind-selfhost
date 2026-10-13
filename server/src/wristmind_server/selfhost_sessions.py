"""Cookie policy and a signed browser identity; identity never grants access."""
import hashlib
import hmac

SESSION_SECONDS = 30 * 24 * 60 * 60
RENEW_BEFORE_SECONDS = SESSION_SECONDS - 24 * 60 * 60
BROWSER_SECONDS = 365 * 24 * 60 * 60


def browser_identity(device_id, settings):
    digest = hmac.new(settings.token_pepper.get_secret_value().encode(),
                      f'web-browser-v1:{device_id}'.encode(), hashlib.sha256).hexdigest()
    return f'{device_id}.{digest}'


def browser_device_id(value, settings):
    if not value or len(value) > 150 or '.' not in value:
        return None
    device_id, _ = value.rsplit('.', 1)
    expected = browser_identity(device_id, settings)
    return device_id if hmac.compare_digest(value.encode(), expected.encode()) else None


def cookie_options(request, settings):
    return dict(httponly=True, samesite='strict',
                secure=request.url.scheme == 'https' or settings.public_base_url.startswith('https://'), path='/')


def set_session_cookie(response, token, request, settings):
    response.set_cookie('wm_session', token, max_age=SESSION_SECONDS, **cookie_options(request, settings))
    response.headers['Cache-Control'] = 'no-store'


def set_browser_cookie(response, device_id, request, settings):
    response.set_cookie('wm_browser', browser_identity(device_id, settings), max_age=BROWSER_SECONDS,
                        **cookie_options(request, settings))
