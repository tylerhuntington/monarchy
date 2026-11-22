"""Prove mapped rows; pending rows explicitly retain incomplete qualification.

This is a partial public inventory. Fixture values prove reusable contracts, not
private source coverage, live preference freshness or native runtime authority.
"""
import copy
import json
from pathlib import Path
import re
import unittest

from monarchy.config import KEYS, NEVER_DELEGABLE, load, resolve
from monarchy.controls import RESTRICTIONS, WIDENING
from monarchy.delegation import STATES, TAXONOMY
from monarchy.orders import INVARIANT_RULE_IDS, MARKER, ROLES, render, rule_ids
from monarchy.prompt_hooks import HookError, lint_box


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
P2_KEYS = {
    'prompts.abandoned-minutes': 'prompts.abandoned_minutes',
    'owner.bearings-lines': 'voice.max_lines',
}
P2_RULES = {
    'preference.box-framing': ('queen', 'conversation.decision-box',
        ('framing before the box', 'reason and consequence', '(Recommended) option first')),
    'preference.reopen-cancelled-box': ('queen', 'conversation.no-prose-decisions',
        ('cancelled unanswered box reopens on the next turn', 'prose fallback cannot supply missing authority')),
    'preference.single-owner-conversation': ('secretary', 'coordination.owner-channel',
        ("Keep routine coordination away from the owner's conversation", 'Bring the Queen',
         'never replace an unanswered box with prose')),
    'preference.one-question-per-box': ('queen', 'conversation.decision-box',
        ('one question per box', 'two to four options')),
    'preference.requested-decision-prompt': ('queen', 'conversation.requested-decisions',
        ('present its box promptly', 'short framing')),
    'preference.no-decisions-hidden-in-prose': ('queen', 'conversation.no-prose-decisions',
        ('Never leave a decision in prose', 'open or parked decisions receive their box in the same turn')),
    'preference.bounded-bundled-approval': ('queen', 'conversation.bounded-approval',
        ('one bounded box', 'remaining steps', 'scope, limits and stopping conditions',
         'reserved actions', 'exact-candidate approvals', 'required project gates', 'never widens authority')),
    'boxes.option-bounds': ('queen', 'conversation.decision-box',
        ('two to four options', '(Recommended) option first')),
}
P2_INVARIANTS = {
    'forwards.operation-journal': 'invariant.one-writer',
    'forwards.secretary-header': 'invariant.headers',
    'forwards.character-lint': 'invariant.config-custody',
    'prompts.known-open-only': 'invariant.prompt-state',
    'prompts.opt-in-hooks': 'invariant.runtime-boundary',
    'owner.verbs': 'invariant.verb-classification',
    'owner.verb-classification': 'invariant.verb-classification',
}
P2_TARGETS = {**{source: 'key:' + key for source, key in P2_KEYS.items()},
              **{source: 'rule:' + rule for source, (_, rule, _) in P2_RULES.items()},
              **{source: 'invariant:' + rule for source, rule in P2_INVARIANTS.items()}}
P3_TARGETS = {
    'preference.internal-pr-approval': 'rule:review.internal-approval',
    'preference.record-before-relay': 'invariant:invariant.owner-route',
    'authority.trusted-owner-route': 'invariant:invariant.owner-route',
    'authority.never-delegable-floor': 'invariant:invariant.never-delegable',
    'delegation.states': 'rule:delegation.owner-boxes',
    'delegation.revocation': 'rule:delegation.revocation',
    'delegation.followup-box': 'rule:delegation.owner-boxes',
    'delegation.answer-provenance': 'invariant:invariant.owner-route',
    'delegation.internal-approval-category': 'rule:delegation.taxonomy',
    'delegation.precedent-check': 'invariant:invariant.grants',
    **{'delegation.taxonomy.' + category: 'rule:delegation.taxonomy'
       for category in TAXONOMY if category != 'internal-pr-approval'},
}
# These rows represent runtime behavior, not the mere existence of a setting or
# standing-order paragraph. Remove entries only with the phase's runtime proof.
PENDING_RUNTIME = {
    'authority.one-writer': 'P3',
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


def rule_bodies(text):
    matches = list(MARKER.finditer(text))
    return {match.group(1): ' '.join(text[match.end():
            matches[index + 1].start() if index + 1 < len(matches) else len(text)].split())
            for index, match in enumerate(matches)}


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
        bodies = rule_bodies(self.rendered['queen']['text'])
        for source, (rule, phrases) in P1_RULES.items():
            with self.subTest(source=source):
                self.assertEqual(rows[source]['target'], 'rule:' + rule)
                for phrase in phrases:
                    self.assertIn(phrase, bodies[rule])

    def test_p2_targets_match_the_qualified_scope_and_resolve_offline(self):
        rows = catalog()
        by_source = {row['source']: row for row in rows}
        for source, target in P2_TARGETS.items():
            with self.subTest(source=source):
                self.assertEqual(by_source[source]['target'], target)
        self.assert_catalog(rows)

    def test_p2_rule_targets_preserve_the_declared_conversation_contract(self):
        bodies = {role: rule_bodies(result['text']) for role, result in self.rendered.items()}
        for source, (role, rule, phrases) in P2_RULES.items():
            with self.subTest(source=source):
                for phrase in phrases:
                    self.assertIn(phrase, bodies[role][rule])
        self.assertIn('A blank answer is not consent', bodies['queen']['conversation.no-prose-decisions'])
        self.assertIn('only when the durable decision list has no unanswered item',
                      bodies['queen']['conversation.requested-decisions'])

    def test_p2_box_values_match_the_optional_lint_boundaries(self):
        rows = {row['source']: row for row in catalog()}
        bounds = rows['boxes.option-bounds']['value']
        self.assertEqual(rows['preference.one-question-per-box']['value'],
                         {'questions_per_box': 1, 'blank_answer_is_consent': False})
        self.assertTrue(bounds['recommended_first'])
        for count in range(bounds['minimum'] - 1, bounds['maximum'] + 2):
            options = [{'label': 'Choice ' + str(index) + (' (Recommended)' if index == 0 else ''),
                        'description': 'A bounded alternative.'} for index in range(count)]
            if bounds['minimum'] <= count <= bounds['maximum']:
                lint_box('Which path should proceed?', options)
            else:
                with self.assertRaises(HookError):
                    lint_box('Which path should proceed?', options)
        options[0]['label'] = 'Choice 0'
        with self.assertRaises(HookError):
            lint_box('Which path should proceed?', options[:bounds['minimum']])

    def test_p2_verb_rows_match_runtime_classification_without_claiming_native_effects(self):
        rows = {row['source']: row for row in catalog()}
        classification = rows['owner.verb-classification']['value']
        self.assertEqual(set(classification['restrictive']), set(RESTRICTIONS) | {'bearings', 'decisions'})
        self.assertEqual(set(classification['confirmation_required']), WIDENING)
        verbs = rows['owner.verbs']['value']
        self.assertEqual(len(verbs), len(set(verbs)))
        self.assertEqual(set(verbs), set(RESTRICTIONS) | WIDENING | {'bearings', 'decisions'})

    def test_future_runtime_authority_is_not_claimed_by_constant_or_prose(self):
        rows = {row['source']: row for row in catalog()}
        for source, phase in PENDING_RUNTIME.items():
            with self.subTest(source=source):
                self.assertEqual(rows[source]['target'], 'pending:' + phase)
        self.assertGreater(sum(row['target'].startswith('pending:') for row in rows.values()), 0)

    def test_p3_mapped_targets_retain_the_branch_custody_gap(self):
        rows = catalog()
        by_source = {row['source']: row for row in rows}
        self.assertEqual(len(P3_TARGETS), 24)
        for source, target in P3_TARGETS.items():
            with self.subTest(source=source):
                self.assertEqual(by_source[source]['target'], target)
        self.assertEqual([row['source'] for row in rows if row['target'] == 'pending:P3'],
                         ['authority.one-writer'])
        self.assert_catalog(rows)

    def test_p3_category_inventory_matches_executable_vocabulary(self):
        rows = catalog()
        categories = [row['value'] for row in rows
                      if row['source'].startswith('delegation.taxonomy.')
                      or row['source'] == 'delegation.internal-approval-category']
        self.assertEqual(len(categories), len(set(categories)))
        self.assertEqual(set(categories), set(TAXONOMY))
        bodies = rule_bodies(self.rendered['queen']['text'])
        for category in categories:
            self.assertRegex(bodies['delegation.taxonomy'],
                             r'(?<![a-z0-9-])' + re.escape(category) + r'(?![a-z0-9-])')

    def test_p3_state_and_floor_inventory_match_runtime_constraints(self):
        rows = {row['source']: row for row in catalog()}
        self.assertEqual(rows['delegation.states']['value'], list(STATES))
        self.assertEqual(set(rows['authority.never-delegable-floor']['value']), set(NEVER_DELEGABLE))

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
