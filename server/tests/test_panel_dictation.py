def test_panel_dictation_is_authenticated_bounded_and_returns_draft(client, admin_headers):
    audio = b'\x00\x00' * 1600
    assert client.post('/v1/stt/yandex', files={'file': ('voice.pcm', audio)}).status_code == 401
    response = client.post('/v1/stt/yandex', headers=admin_headers, files={'file': ('voice.pcm', audio)})
    assert response.status_code == 200
    assert response.json()['text'] == 'Тестовая расшифровка WristMind'
    assert response.json()['provider'] == 'yandex'
    response = client.post('/v1/stt/yandex', headers=admin_headers, files={'file': ('voice.pcm', b'\0' * 960_002)})
    assert response.status_code == 413
    response = client.post('/v1/stt/yandex', headers=admin_headers, files={'file': ('voice.pcm', b'\0')})
    assert response.status_code == 422
