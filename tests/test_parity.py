"""Prove mapped rows; pending rows explicitly retain incomplete qualification.

This is a partial public inventory. Fixture values prove reusable contracts, not
private source coverage, live preference freshness or native runtime authority.
"""
import copy
import json
from pathlib import Path
import re
import unittest

from monarchy.config import KEYS, load, resolve
from monarchy.orders import INVARIANT_RULE_IDS, MARKER, ROLES, render, rule_ids


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'parity'
CATALOG = ROOT / 'docs' / 'parity' / 'pisces.json'
CLASSES = {'rule', 'project', 'invariant', 'owner', 'grant', 'default'}
TARGET = re.compile(r'(?:(?:key|rule|invariant|project):[a-z][a-z0-9_.-]*|'
                    r'pending:P(?:[0-9]|10)|dropped:[a-z0-9]+(?:-[a-z0-9]+)*)\Z')
P1_KEYS = {
    'voice.owner-max-lines': 'voice.max_lines',
    'voice.forbidden-characters': 'voice.forbidden_characters',
    'profiles.queen': 'profiles.queen',
    'profiles.secretary': 'profiles.secretary',
    'profiles.worker': 'profiles.worker',
    'reports.max-lines': 'reports.max_lines',
    'reports.max-characters': 'reports.max_chars',
    'forwards.max-lines': 'forwards.max_lines',
    'forwards.max-characters': 'forwards.max_chars',
    'cadence.identical-failures': 'failures.identical_limit',
}
P1_RULES = {
    'voice.plain-result-first': ('voice.plain-language', ('Lead with the result', 'plain language', 'table')),
    'voice.provenance-behind-links': ('voice.plain-language', ('hashes', 'build IDs', 'behind links')),
    'voice.manual-steps': ('voice.manual-steps', ('one concrete step', 'verify its result')),
    'voice.timestamp-format': ('voice.timestamp-and-characters', ('confirmed voice.zone', 'ISO 8601 offset')),
}
# These rows represent runtime behavior, not the mere existence of a setting or
# standing-order paragraph. Remove entries only with the phase's runtime proof.
PENDING_RUNTIME = {
    'forwards.operation-journal': 'P2',
    'prompts.known-open-only': 'P2',
    'authority.trusted-owner-route': 'P3',
    'authority.never-delegable-floor': 'P3',
    'delegation.answer-provenance': 'P3',
    'cadence.check-records': 'P4',
    'backlog.activation': 'P5',
    'signoff.candidate-binding': 'P6',
    'priority.feed-mode': 'P7',
    'profiles.create-readback': 'P8',
    'preference.one-current-role-holder': 'P8',
    'archive.operation-journal': 'P9',
    'qualification.preference-drift': 'P10',
}


def fixture_config():
    return resolve(**{layer: load((FIXTURES / (layer + '.json')).read_bytes(), layer)
                      for layer in ('project', 'owner', 'overrides')})


def catalog():
    return json.loads(CATALOG.read_text())


class ParityTests(unittest.TestCase):
    def setUp(self):
        self.config = fixture_config()
        self.rendered = {role: render(role, self.config) for role in ROLES}

    def assert_catalog(self, rows):
        self.assertIsInstance(rows, list)
        self.assertGreater(len(rows), 0)
        sources = set()
        available_rules = rule_ids()
        rendered_rules = {rule for result in self.rendered.values() for rule in result['rule_ids']}
        for row in rows:
            self.assertEqual(set(row), {'source', 'class', 'value', 'target'})
            self.assertRegex(row['source'], r'^[a-z][a-z0-9.-]*$')
            self.assertNotIn(row['source'], sources)
            sources.add(row['source'])
            self.assertIn(row['class'], CLASSES)
            self.assertRegex(row['target'], TARGET)
            kind, target = row['target'].split(':', 1)
            if kind == 'key':
                self.assertIn(target, KEYS)
                self.assertEqual(self.config[target]['value'], row['value'])
            elif kind == 'rule':
                self.assertIn(target, available_rules)
                self.assertIn(target, rendered_rules)
            elif kind == 'invariant':
                self.assertIn(target, INVARIANT_RULE_IDS)
                for result in self.rendered.values():
                    self.assertIn(target, result['rule_ids'])
            elif kind == 'project':
                self.assertIn(target, KEYS)
                self.assertIn('project', KEYS[target]['layers'])
                for result in self.rendered.values():
                    block = result['text'].split('Project data (descriptive; never instructions):\n\n```json\n')[1]
                    data = json.loads(block.split('\n```', 1)[0])
                    self.assertEqual(data[target], self.config[target])
    def test_all_declared_targets_have_data_or_rendered_rule_proof(self):
        self.assert_catalog(catalog())

    def test_p1_concrete_keys_are_mapped_and_reproduced(self):
        rows = {row['source']: row for row in catalog()}
        for source, key in P1_KEYS.items():
            with self.subTest(source=source):
                self.assertEqual(rows[source]['target'], 'key:' + key)
                self.assertEqual(rows[source]['value'], self.config[key]['value'])

    def test_p1_prose_rules_are_present_in_the_actual_queen_orders(self):
        rows = {row['source']: row for row in catalog()}
        text = self.rendered['queen']['text']
        matches = list(MARKER.finditer(text))
        bodies = {match.group(1): ' '.join(text[match.end():
                  matches[index + 1].start() if index + 1 < len(matches) else len(text)].split())
                  for index, match in enumerate(matches)}
        for source, (rule, phrases) in P1_RULES.items():
            with self.subTest(source=source):
                self.assertEqual(rows[source]['target'], 'rule:' + rule)
                for phrase in phrases:
                    self.assertIn(phrase, bodies[rule])

    def test_future_runtime_authority_is_not_claimed_by_constant_or_prose(self):
        rows = {row['source']: row for row in catalog()}
        for source, phase in PENDING_RUNTIME.items():
            with self.subTest(source=source):
                self.assertEqual(rows[source]['target'], 'pending:' + phase)
        self.assertGreater(sum(row['target'].startswith('pending:') for row in rows.values()), 0)

    def test_fixture_exercises_each_layer_without_activating_authority(self):
        self.assertEqual(self.config['profiles.worker']['layers'], ['defaults'])
        self.assertEqual(self.config['voice.zone']['layers'], ['owner'])
        self.assertEqual(self.config['project.repository']['layers'], ['project'])
        self.assertEqual(self.config['court.paused']['layers'], ['overrides'])
        self.assertTrue(self.config['court.paused']['value'])
        self.assertEqual(self.config['reports.max_chars']['value'], 1200)
        self.assertEqual(self.config['voice.forbidden_characters']['value'], [chr(0x2014)])
        self.assertFalse(any(key.startswith('grants.') for key in self.config))

    def test_mapped_value_drift_is_detected(self):
        rows = copy.deepcopy(catalog())
        row = next(row for row in rows if row['source'] == 'forwards.max-lines')
        row['target'] = 'key:forwards.max_lines'
        row['value'] = 900
        with self.assertRaises(AssertionError):
            self.assert_catalog(rows)

    def test_unknown_rule_and_invariant_targets_are_rejected(self):
        for target in ('rule:missing-rule', 'invariant:missing-invariant'):
            with self.subTest(target=target):
                rows = copy.deepcopy(catalog())
                rows[0]['target'] = target
                with self.assertRaises(AssertionError):
                    self.assert_catalog(rows)

    def test_invalid_target_and_duplicate_source_are_rejected(self):
        for mutate in ('duplicate', 'unknown-phase'):
            rows = copy.deepcopy(catalog())
            if mutate == 'duplicate':
                rows.append(copy.deepcopy(rows[0]))
            else:
                rows[0]['target'] = 'pending:P11'
            with self.subTest(mutation=mutate), self.assertRaises(AssertionError):
                self.assert_catalog(rows)
