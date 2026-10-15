from pathlib import Path
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import io

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'prototype'))
from runtime_config import load_config, preflight

class RuntimeConfigTests(unittest.TestCase):
    def config(self, values):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json';p.write_text(json.dumps(values),encoding='utf-8')
            return load_config(p)

    def test_defaults_and_native_model(self):
        self.assertEqual(load_config().max_output_tokens,1000)
        self.assertEqual(self.config({'model':'other:8b','qwen_text_prefill':False}).model,'other:8b')

    def test_invalid_values_rejected(self):
        for value in ({'extra':1},{'max_output_tokens':True},{'timeout_seconds':0},{'model':'other'},
                      {'model_url':'http://user:secret@localhost'},{'model_url':'file:///tmp'}):
            with self.subTest(value=value), self.assertRaises(ValueError):self.config(value)

    def test_preflight_is_metadata_only(self):
        responses=[io.BytesIO(json.dumps({'models':[{'name':'qwen3-vl:8b','digest':'abc'}]}).encode()),
                   io.BytesIO(b'{"version":"test"}')]
        with patch('runtime_config.urlopen',side_effect=responses) as call:
            info=preflight(load_config())
        self.assertEqual(info['digest'],'abc')
        self.assertTrue(all('/api/generate' not in str(c) for c in call.call_args_list))

    def test_missing_model_fails_without_download(self):
        with patch('runtime_config.urlopen',return_value=io.BytesIO(b'{"models":[]}')):
            with self.assertRaisesRegex(ValueError,'不会自动下载'):preflight(load_config())

if __name__=='__main__':unittest.main()
