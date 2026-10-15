import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'prototype'))
from evaluation_scope import evaluate_inputs, input_fingerprints, sha256


class EvaluationScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'samples').mkdir()
        self.pdf = self.root / 'samples/input.pdf'
        self.pdf.write_bytes(b'fixture PDF bytes')
        self.labels = self.root / 'samples/expected.json'
        self.records = [{'case_id': 'input', 'project': 'fixture project'}]
        self.labels.write_text(json.dumps(self.records), encoding='utf-8')
        self.manifest = self.root / 'samples/evaluation_manifest.json'
        self.manifest.write_text(json.dumps({'input_files': input_fingerprints([self.pdf], self.root),
             'labels_sha256': sha256(self.labels), 'data_kind': 'synthetic'}), encoding='utf-8')

    def test_builtin_matching_inputs_are_evaluated(self):
        self.assertEqual(evaluate_inputs(self.records, [self.pdf], self.root)['field_accuracy'], 1)

    def test_unknown_input_not_scored(self):
        self.pdf.write_bytes(b'different PDF bytes')
        result = evaluate_inputs(self.records, [self.pdf], self.root)
        self.assertFalse(result['evaluated'])
        self.assertIsNone(result['field_accuracy'])
        self.assertEqual(result['data_kind'], 'unknown')

    def test_changed_labels_not_scored(self):
        self.labels.write_text('[]', encoding='utf-8')
        self.assertFalse(evaluate_inputs([], [self.pdf], self.root)['evaluated'])

    def test_explicit_mismatch_raises(self):
        self.pdf.write_bytes(b'other bytes')
        with self.assertRaisesRegex(ValueError, 'SHA256'):
            evaluate_inputs([], [self.pdf], self.root, self.labels, self.manifest)

    def test_matching_external_labels(self):
        self.assertTrue(evaluate_inputs(self.records, [self.pdf], self.root, self.labels, self.manifest)['evaluated'])

    def test_missing_manifest_raises_for_explicit_labels(self):
        with self.assertRaises(ValueError):
            evaluate_inputs([], [self.pdf], self.root, self.labels)


if __name__ == '__main__':
    unittest.main()
