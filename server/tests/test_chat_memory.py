import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from wristmind_server.chat_memory import (
    ConversationState, MemoryEnvelope, history_tokens, memory_context,
    transcript_batches, uncompacted_messages,
)
from wristmind_server.database import SessionFactory
from wristmind_server.db_models import Chat, Job, Message, utcnow
import wristmind_server.worker as worker


def message(index, content, role='user', status='complete'):
    return SimpleNamespace(id=str(index), content=content, role=role, status=status)


def test_cursor_keeps_recent_messages_verbatim_and_legacy_keeps_originals():
    messages = [message(i, f'Текст {i}') for i in range(20)]
    memory = MemoryEnvelope(through_message_id='7', state=ConversationState(topic='Тема')).model_dump_json()
    assert uncompacted_messages(messages, memory) == messages[8:]
    assert uncompacted_messages(messages, 'Старая память') == messages
    assert uncompacted_messages(messages, memory.replace('"7"', '"missing"')) == messages
    assert 'through_message_id' not in memory_context(memory)


def test_long_message_tail_is_not_lost_and_budget_depends_on_size():
    text = 'а' * 65000 + 'ПОСЛЕДНЕЕ УТОЧНЕНИЕ'
    batches = transcript_batches([message(1, text)])
    recovered = ''.join(json.loads(line)['content'] for batch in batches for line in batch.splitlines())
    assert recovered == text
    assert len(batches) > 1
    assert history_tokens([message(1, text)]) > 6000
    assert history_tokens([message(i, 'Да') for i in range(50)]) < 6000


@pytest.mark.parametrize('invalid', [False, True])
def test_background_compaction_is_atomic_and_preserves_recent_turns(
    client, admin, admin_headers, mode, monkeypatch, invalid,
):
    chat_id = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id']}).json()['id']
    seen = []
    state = ConversationState(topic='Системы счисления', user_corrections=['321 дано в десятичной'],
                              superseded_assumptions=['Трактовка 321 как шестнадцатеричного отменена'])

    async def stream(model_id, messages, **kwargs):
        seen.append(messages)
        yield 'not json' if invalid else state.model_dump_json()

    monkeypatch.setattr(worker.providers, 'stream_answer', stream)

    async def run():
        async with SessionFactory() as session:
            chat = await session.get(Chat, chat_id)
            chat.memory_summary = 'Старая ошибочная память'
            origin = utcnow()
            rows = [Message(chat_id=chat_id, role='user' if i % 2 == 0 else 'assistant',
                            status='cancelled' if i == 1 else 'complete',
                            content=f'Исходное сообщение {i} ' + ('х' * 2000 if i == 0 else ''),
                            created_at=origin + timedelta(seconds=i)) for i in range(16)]
            session.add_all(rows)
            job = Job(kind='CHAT_MEMORY', status='running', device_id=admin['device_id'],
                      client_request_id='memory-test', payload={'chat_id': chat_id})
            session.add(job)
            await session.commit()
            job_id = job.id
            row_ids = [row.id for row in rows]
        if invalid:
            with pytest.raises(ValueError):
                await worker.process_chat_memory(job_id)
        else:
            await worker.process_chat_memory(job_id)
        async with SessionFactory() as session:
            chat = await session.get(Chat, chat_id)
            if invalid:
                assert chat.memory_summary == 'Старая ошибочная память'
            else:
                saved = MemoryEnvelope.model_validate_json(chat.memory_summary)
                assert saved.through_message_id == row_ids[3]
                assert saved.state == state
                assert 'Старая ошибочная память' not in seen[0][1]['content']
                transcript = json.loads(seen[0][1]['content'])['messages']
                assert 'х' * 2000 in transcript
                assert 'cancelled' in transcript
                assert 'Исходное сообщение 4' not in transcript
                assert (await session.get(Job, job_id)).status == 'complete'
                all_rows = [await session.get(Message, row_id) for row_id in row_ids]
                assert uncompacted_messages(all_rows, chat.memory_summary) == all_rows[4:]
    asyncio.run(run())


def test_answer_preserves_uncompacted_history_and_queues_one_memory_job(
    client, admin_headers, mode, monkeypatch,
):
    from sqlalchemy import select, update
    from wristmind_server.identity import CORE_IDENTITY_PROMPT
    recorded = []
    original_stream = worker.providers.stream_answer

    async def stream(model_id, messages, **kwargs):
        if CORE_IDENTITY_PROMPT in messages[0]['content']:
            recorded.extend(messages[1:])
        async for chunk in original_stream(model_id, messages, **kwargs):
            yield chunk
    monkeypatch.setattr(worker.providers, 'stream_answer', stream)
    chat_id = client.post('/v1/chats', headers=admin_headers, json={'mode_id': mode['id']}).json()['id']

    async def seed():
        async with SessionFactory() as session:
            origin = utcnow() - timedelta(minutes=10)
            session.add_all([Message(chat_id=chat_id, role='user' if i % 2 == 0 else 'assistant',
                                    content=f'История {i} ' + 'текст ' * 400,
                                    status='complete', created_at=origin + timedelta(seconds=i))
                             for i in range(14)])
            await session.commit()
    asyncio.run(seed())
    job_id = client.post(f'/v1/chats/{chat_id}/messages', headers=admin_headers,
                         json={'client_request_id': 'memory-answer', 'text': 'Сколько будет 2+2?'}).json()['id']

    async def run():
        async with SessionFactory() as session:
            await session.execute(update(Job).where(Job.id == job_id).values(status='running'))
            await session.commit()
        await worker.process_answer(job_id)
        async with SessionFactory() as session:
            jobs = list((await session.scalars(select(Job).where(Job.kind == 'CHAT_MEMORY'))).all())
            assert len(jobs) == 1
            assert jobs[0].status == 'queued'
            assert (await session.get(Job, job_id)).status == 'complete'
    asyncio.run(run())
    assert len(recorded) == 15
    assert recorded[0]['content'].startswith('История 0 ')
    assert recorded[-1]['content'] == 'Сколько будет 2+2?'
    async def compact():
        async def summary(*args, **kwargs):
            yield ConversationState(topic='Математика').model_dump_json()
        monkeypatch.setattr(worker.providers, 'stream_answer', summary)
        async with SessionFactory() as session:
            memory_job = await session.scalar(select(Job).where(Job.kind == 'CHAT_MEMORY'))
            memory_job_id = memory_job.id
        await worker.process_chat_memory(memory_job_id)
        monkeypatch.setattr(worker.providers, 'stream_answer', stream)
    asyncio.run(compact())
    recorded.clear()
    next_job = client.post(f'/v1/chats/{chat_id}/messages', headers=admin_headers,
                           json={'client_request_id': 'memory-answer-next', 'text': 'А 3+3?'}).json()['id']
    async def followup():
        async with SessionFactory() as session:
            await session.execute(update(Job).where(Job.id == next_job).values(status='running'))
            await session.commit()
        await worker.process_answer(next_job)
    asyncio.run(followup())
    assert len(recorded) == 13
    assert recorded[0]['content'].startswith('История 4 ')
    assert recorded[-1]['content'] == 'А 3+3?'
