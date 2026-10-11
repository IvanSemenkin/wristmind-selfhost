import asyncio
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from wristmind_server.database import Base
from wristmind_server.db_models import Device, Job, KnowledgeSource, Mode, TelegramAccount, User
from wristmind_server.telegram_photos import handle_photo


async def scenario(tmp_path, action):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            user = User(name="Photo owner", role="ADMIN")
            session.add(user)
            await session.flush()
            device = Device(name="Telegram", kind="TELEGRAM", user_id=user.id, token_hash="photo-test")
            session.add(device)
            await session.flush()
            account = TelegramAccount(telegram_user_id="1", chat_id="1", user_id=user.id, device_id=device.id)
            modes = [Mode(name=name, hidden_on_watch=hidden, response_model_id="mock:test")
                     for name, hidden in [("Физика", False), ("Скрытый", True), ("Быстрый чат", False)]]
            session.add_all([account, *modes])
            await session.commit()
            data = BytesIO()
            Image.new("RGB", (8, 8), "white").save(data, "PNG")
            client = SimpleNamespace(token="photo-test-token", send=AsyncMock(), answer_callback=AsyncMock(),
                                     download=AsyncMock(return_value=("files/photo.png", data.getvalue())))
            settings = SimpleNamespace(storage_dir=tmp_path, max_upload_bytes=1024 * 1024)
            await action(session, account, modes[0], client, settings)
    finally:
        await engine.dispose()


def photo(number=1, document=False):
    file = {"file_id": f"image-{number}", "file_size": 100}
    media = {"document": {**file, "mime_type": "image/png"}} if document else {"photo": [file]}
    return {"message": {"message_id": number, "caption": f"Задача {number}", **media}}


def button(client):
    return client.send.call_args.args[2][0][0]["callback_data"]


def callback(data):
    return {"callback_query": {"id": "callback", "data": data}}


def test_photo_waits_for_choice_then_queues_vision_once(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(), account, client, session, settings)
        keyboard = client.send.call_args.args[2]
        assert [row[0]["text"] for row in keyboard] == ["Физика"]
        data = button(client)
        assert len(data.encode()) <= 64
        assert not (await session.scalars(select(KnowledgeSource))).all()
        client.download.assert_not_awaited()
        await handle_photo(callback(data), account, client, session, settings)
        sources = (await session.scalars(select(KnowledgeSource))).all()
        assert len(sources) == 1
        source = sources[0]
        assert source.mode_id == mode.id and source.user_id == account.user_id
        assert source.processing_mode == "VISION" and source.media_type == "image/png"
        assert source.chat_id is None and source.title == "Задача 1"
        jobs = (await session.scalars(select(Job))).all()
        assert jobs[0].kind == "INGEST" and jobs[0].status == "queued"
        assert jobs[0].payload["source_id"] == source.id
        await handle_photo(callback(data), account, client, session, settings)
        await handle_photo(photo(), account, client, session, settings)
        assert len((await session.scalars(select(KnowledgeSource))).all()) == 1
        client.download.assert_awaited_once()
    asyncio.run(scenario(tmp_path, action))


def test_multiple_images_keep_independent_durable_selections(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(1, document=True), account, client, session, settings)
        first = button(client)
        await handle_photo(photo(2), account, client, session, settings)
        second = button(client)
        assert first != second
        session.expire_all()
        await session.refresh(account)
        await handle_photo(callback(first), account, client, session, settings)
        await handle_photo(callback(second), account, client, session, settings)
        sources = (await session.scalars(select(KnowledgeSource))).all()
        assert {source.title for source in sources} == {"Задача 1", "Задача 2"}
        assert [call.args[0] for call in client.download.await_args_list] == ["image-1", "image-2"]
    asyncio.run(scenario(tmp_path, action))


def test_bot_accepts_owner_image_but_rejects_other_users(tmp_path, monkeypatch):
    from pydantic import SecretStr
    from wristmind_server import telegram_bot

    async def action(session, account, mode, client, settings):
        settings.telegram_bot_token = SecretStr(client.token)
        settings.telegram_owner_id = 1
        monkeypatch.setattr(telegram_bot, "TelegramClient", lambda _: client)
        factory = async_sessionmaker(session.bind, expire_on_commit=False)
        monkeypatch.setattr(telegram_bot, "SessionFactory", factory)
        update = photo()
        update["message"].update({"from": {"id": 2}, "chat": {"id": 1, "type": "private"}})
        await telegram_bot.handle_update(update, settings)
        assert not (await session.scalars(select(Job))).all()
        update["message"]["from"]["id"] = 1
        await telegram_bot.handle_update(update, settings)
        assert len((await session.scalars(select(Job))).all()) == 1
        assert button(client).startswith("photo:")
    asyncio.run(scenario(tmp_path, action))


def test_hidden_mode_and_wrong_bot_cannot_import(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(), account, client, session, settings)
        data = button(client)
        client.token = "other-bot"
        await handle_photo(callback(data), account, client, session, settings)
        client.download.assert_not_awaited()
        client.token = "photo-test-token"
        mode.hidden_on_watch = True
        await session.commit()
        await handle_photo(callback(data), account, client, session, settings)
        client.download.assert_not_awaited()
        assert not (await session.scalars(select(KnowledgeSource))).all()
    asyncio.run(scenario(tmp_path, action))


def test_bad_image_does_not_create_source_and_can_retry(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(), account, client, session, settings)
        data = button(client)
        valid = client.download.return_value
        client.download.return_value = ("bad.jpg", b"not an image")
        await handle_photo(callback(data), account, client, session, settings)
        assert not (await session.scalars(select(KnowledgeSource))).all()
        client.download.return_value = valid
        await handle_photo(callback(data), account, client, session, settings)
        assert len((await session.scalars(select(KnowledgeSource))).all()) == 1
    asyncio.run(scenario(tmp_path, action))


def test_polling_startup_only_reads_existing_schema(tmp_path, monkeypatch):
    from wristmind_server import telegram_polling
    from sqlalchemy import event

    async def action(session, account, mode, client, settings):
        statements = []
        event.listen(session.bind.sync_engine, "before_cursor_execute",
                     lambda conn, cursor, statement, parameters, context, many: statements.append(statement))
        monkeypatch.setattr(telegram_polling, "SessionFactory", async_sessionmaker(session.bind))
        await telegram_polling._wait_for_database()
        assert len(statements) == 4
        assert all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    asyncio.run(scenario(tmp_path, action))


def test_expired_callback_ack_does_not_lose_selection(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(), account, client, session, settings)
        data = button(client)
        request = httpx.Request("POST", "https://example.test/callback")
        client.answer_callback.side_effect = httpx.HTTPStatusError(
            "expired callback", request=request, response=httpx.Response(400, request=request))
        await handle_photo(callback(data), account, client, session, settings)
        jobs = (await session.scalars(select(Job))).all()
        assert jobs[0].kind == "INGEST" and jobs[0].status == "queued"
        assert len((await session.scalars(select(KnowledgeSource))).all()) == 1
    asyncio.run(scenario(tmp_path, action))
