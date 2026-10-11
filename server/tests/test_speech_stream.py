import base64
from uuid import uuid4


def test_live_dictation_order_retry_finish_and_cancel(client, admin_headers):
    endpoint = '/v1/stt/stream'
    identity = {'session_id': str(uuid4())}
    def send(action, **extra):
        return client.post(endpoint, headers=admin_headers, json={**identity, 'action': action, **extra})
    assert client.post(endpoint, json={**identity, 'action': 'start'}).status_code == 401
    assert send('start').status_code == 200
    audio = base64.b64encode(b'\0\0' * 3200).decode()
    assert send('chunk', seq=1, data=audio).status_code == 409
    assert send('chunk', seq=0, data=audio).status_code == 200
    assert send('chunk', seq=0, data=audio).json()['seq'] == 1
    assert send('chunk', seq=1, data='bad').status_code == 422
    result = send('finish')
    assert result.status_code == 200
    assert result.json()['text'] == 'Тестовая расшифровка WristMind'
    assert send('finish').json() == result.json()
    assert send('cancel').status_code == 200
    assert send('chunk', seq=1, data=audio).status_code == 409


def test_live_dictation_owner_and_audio_budget(client, admin_headers):
    endpoint = '/v1/stt/stream'
    identity = {'session_id': str(uuid4())}
    def send(action, **extra):
        return client.post(endpoint, headers=admin_headers, json={**identity, 'action': action, **extra})
    assert send('start').status_code == 200
    audio = base64.b64encode(b'\0' * 64000).decode()
    for seq in range(15):
        assert send('chunk', seq=seq, data=audio).status_code == 200
    assert send('chunk', seq=15, data=audio).status_code == 413
    assert send('cancel').status_code == 200


def test_compressed_audio_is_bounded_and_decoded_losslessly(client, admin_headers, monkeypatch):
    import zlib
    from wristmind_server import speech_stream
    observed = []
    async def capture(session, settings):
        while (audio := await session.queue.get()) is not None:
            observed.append(audio)
        return 'Привет'
    monkeypatch.setattr(speech_stream, 'recognize', capture)
    identity = {'session_id': str(uuid4())}
    def send(action, **extra):
        return client.post('/v1/stt/stream', headers=admin_headers, json={**identity, 'action': action, **extra})
    assert send('start').status_code == 200
    audio = b'\1\0' * 16000
    compressed = base64.b64encode(zlib.compress(audio)).decode()
    assert send('chunk', seq=0, encoding='pcm_zlib', data=compressed).status_code == 200
    oversized = base64.b64encode(zlib.compress(b'\0' * 1000000)).decode()
    assert send('chunk', seq=1, encoding='pcm_zlib', data=oversized).status_code == 422
    assert send('chunk', seq=1, encoding='pcm_zlib', data=compressed[:-4]).status_code == 422
    assert send('finish').json()['text'] == 'Привет'
    assert observed == [audio]
