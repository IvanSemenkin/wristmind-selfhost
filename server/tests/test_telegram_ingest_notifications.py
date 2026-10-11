import asyncio
from sqlalchemy import select
from wristmind_server.db_models import Job
from wristmind_server.telegram_ingest_notifications import deliver_ingest_notifications
from test_telegram_photos import button, callback, handle_photo, photo, scenario


def test_terminal_statuses_durable_and_only_sent_after_processing(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(), account, client, session, settings)
        await handle_photo(callback(button(client)), account, client, session, settings)
        job = await session.scalar(select(Job))
        client.send.reset_mock()
        assert await deliver_ingest_notifications(session, client) == 0
        job.status = "complete"
        await session.commit()
        client.send.side_effect = RuntimeError("offline")
        assert await deliver_ingest_notifications(session, client) == 0
        assert not job.result.get("telegram_ingest_notified")
        client.send.side_effect = None
        assert await deliver_ingest_notifications(session, client) == 1
        assert client.send.call_args.args[0] == account.chat_id
        assert "обработан" in client.send.call_args.args[1]
        assert mode.name in client.send.call_args.args[1]
        assert await deliver_ingest_notifications(session, client) == 0
    asyncio.run(scenario(tmp_path, action))


def test_failed_source_reports_error_without_internal_details(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(), account, client, session, settings)
        await handle_photo(callback(button(client)), account, client, session, settings)
        job = await session.scalar(select(Job))
        job.status = "failed"; job.error = "private-token-and-path"
        await session.commit(); client.send.reset_mock()
        assert await deliver_ingest_notifications(session, client) == 1
        message = client.send.call_args.args[1]
        assert "Ошибка обработки" in message and "private-token-and-path" not in message
    asyncio.run(scenario(tmp_path, action))


def test_other_bot_and_historical_sources_excluded(tmp_path):
    async def action(session, account, mode, client, settings):
        await handle_photo(photo(), account, client, session, settings)
        await handle_photo(callback(button(client)), account, client, session, settings)
        job = await session.scalar(select(Job)); job.status = "complete"
        job.payload = {**job.payload, "bot_scope": "another-bot"}
        await session.commit(); client.send.reset_mock()
        assert await deliver_ingest_notifications(session, client) == 0
        job.payload = {"telegram_chat_id": account.chat_id, "source_id": job.payload["source_id"]}
        await session.commit()
        assert await deliver_ingest_notifications(session, client) == 0
        client.send.assert_not_awaited()
    asyncio.run(scenario(tmp_path, action))
