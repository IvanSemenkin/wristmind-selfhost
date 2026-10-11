"""Fresh and upgraded installs retain the complete public assistant contract."""
import unittest
import runpy
from pathlib import Path
import test_setup

class PromptDefaultsTest(unittest.TestCase):
    run_case = test_setup.SetupTest.run_case

    def test_documented_prompt_matches_runtime_default(self):
        root = Path(__file__).resolve().parents[2]
        prompt = runpy.run_path(str(root / 'server/src/wristmind_server/assistant_prompt.py'))['DEFAULT_GLOBAL_PROMPT']
        document = (root / 'docs/ASSISTANT_SYSTEM_PROMPT.md').read_text().split('\n\n', 1)[1]
        self.assertEqual(document.strip(), prompt.strip())

    def test_full_defaults_and_migration_preserve_custom_prompts(self):
        self.run_case('''
from wristmind_server.database import init_database, DEFAULT_GLOBAL_PROMPT, MINIMAL_DEFAULT_GLOBAL_PROMPT, LEGACY_DEFAULT_GLOBAL_PROMPT
from wristmind_server.db_models import AppSettings
from wristmind_server.assistant_prompt import DEFAULT_GLOBAL_PROMPT as canonical
create()
response = client.get('/v1/settings')
assert response.status_code == 200, response.text
async def read():
    async with SessionFactory() as session:
        return (await session.get(AppSettings, 1)).global_system_prompt
async def save(value):
    async with SessionFactory() as session:
        row = await session.get(AppSettings, 1)
        row.global_system_prompt = value
        await session.commit()
assert asyncio.run(read()) == canonical == DEFAULT_GLOBAL_PROMPT
assert 'chart' in canonical and 'functions' in canonical and '[Ответ]' in canonical
for old in (MINIMAL_DEFAULT_GLOBAL_PROMPT, LEGACY_DEFAULT_GLOBAL_PROMPT):
    asyncio.run(save(old))
    asyncio.run(init_database())
    assert asyncio.run(read()) == canonical
custom = 'Мои инструкции: отвечай подробно и не меняй этот текст.'
asyncio.run(save(custom))
asyncio.run(init_database())
assert asyncio.run(read()) == custom
client.__exit__(None, None, None)
''')
