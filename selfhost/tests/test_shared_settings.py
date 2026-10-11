"""The user explicitly requested matching provider settings in both checkouts."""
import json
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[2]
class SharedSettingsTest(unittest.TestCase):
    def test_shared_sources_match_original(self):
        original = ROOT.parent / 'WristMind'
        if original == ROOT or not (original / 'server/src/wristmind_server/config.py').is_file():
            self.skipTest('Original checkout is not present; release/install test has no sibling')
        for relative in json.loads((ROOT / 'selfhost/shared-settings.json').read_text()):
            self.assertEqual((ROOT / relative).read_bytes(), (original / relative).read_bytes(), relative)
