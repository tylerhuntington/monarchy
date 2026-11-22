"""Strict configuration boundary, deterministic resolution and private diagnostics."""
import copy
import json
import unittest

from monarchy.config import ConfigError, KEYS, defaults_digest, load, resolve, widening


class ConfigTests(unittest.TestCase):
    def test_cadence_window_and_no_progress_budget_have_explicit_defaults(self):
        config = resolve()
        self.assertEqual(config['cadence.reminder_start']['value'], '08:00')
        self.assertEqual(config['cadence.reminder_end']['value'], '20:00')
        self.assertEqual(config['failures.no_progress_limit']['value'], 2)
        self.assertEqual(resolve(owner={'failures.no_progress_limit': 1})[
            'failures.no_progress_limit']['value'], 1)
        self.assertEqual(resolve(owner={'failures.no_progress_limit': 3})[
            'failures.no_progress_limit']['value'], 2)

    def test_reminder_window_has_one_owner_home_and_increasing_clock_bounds(self):
        window = {'cadence.reminder_start': '09:00', 'cadence.reminder_end': '17:00'}
        config = resolve(owner=window)
        self.assertEqual(config['cadence.reminder_start']['layers'], ['owner'])
        self.assertEqual(config['cadence.reminder_end']['value'], '17:00')
        for layer in ('project', 'overrides'):
            with self.subTest(layer=layer), self.assertRaises(ConfigError):
                resolve(**{layer: window})
        for window in ({'cadence.reminder_start': '20:00'},
                       {'cadence.reminder_end': '08:00'},
                       {'cadence.reminder_start': '22:00', 'cadence.reminder_end': '06:00'},
                       {'cadence.reminder_start': '9:00'},
                       {'cadence.reminder_end': '24:00'}):
            with self.subTest(window=window), self.assertRaises(ConfigError):
                resolve(owner=window)
            with self.subTest(loader=window), self.assertRaises(ConfigError):
                load(json.dumps(window), 'owner')

    def test_no_progress_budget_rejects_boolean_fraction_and_out_of_bounds_values(self):
        for value in (True, 1.5, 0, -1, 11):
            with self.subTest(value=value), self.assertRaises(ConfigError):
                resolve(owner={'failures.no_progress_limit': value})

    def test_defaults_supply_recommended_profiles_and_runtime_limits(self):
        config = resolve()
        self.assertEqual(config['forwards.max_lines']['value'], 3)
        self.assertEqual(config['forwards.max_chars']['value'], 900)
        self.assertEqual(config['reports.max_lines']['value'], 5)
        self.assertEqual(config['reports.max_chars']['value'], 1200)
        self.assertEqual(config['failures.identical_limit']['value'], 2)
        self.assertEqual(config['voice.max_lines']['value'], 5)
        self.assertEqual(config['profiles.worker']['value'], {
            'agent': 'codex', 'model': 'gpt-6-astra', 'effort': 'ultra', 'fast_mode': True})
        self.assertEqual(config['profiles.queen']['value'], {
            'agent': 'claude', 'model': 'opus-5-5-1m', 'effort': 'xhigh', 'fast_mode': False})
        self.assertEqual(config['profiles.secretary']['value'], config['profiles.queen']['value'])
        self.assertEqual(config['profiles.worker']['layers'], ['defaults'])
        self.assertIsNone(config['voice.zone']['value'])

    def test_replace_keeps_one_home_and_provenance(self):
        result = resolve(owner={'voice.zone': 'UTC', '_why': {'voice.zone': 'Confirmed owner fact.'}},
                         project={'project.repository': 'example/project'})
        self.assertEqual(result['voice.zone'], {'value': 'UTC', 'layers': ['owner'],
                                              'why': {'owner': 'Confirmed owner fact.'}})
        self.assertEqual(result['project.repository']['value'], 'example/project')
        self.assertEqual(result['project.repository']['layers'], ['project'])

    def test_min_limits_can_only_tighten_default_and_preserve_contributors(self):
        result = resolve(owner={'backlog.builder_cap': 6}, project={'backlog.builder_cap': 4},
                         overrides={'backlog.builder_cap': 3})
        self.assertEqual(result['backlog.builder_cap']['value'], 3)
        self.assertEqual(result['backlog.builder_cap']['layers'], ['defaults', 'project', 'owner', 'overrides'])
        self.assertEqual(resolve(owner={'forwards.max_chars': 2000})['forwards.max_chars']['value'], 900)

    def test_additive_lists_cannot_remove_default_safety_floor(self):
        result = resolve(owner={'voice.forbidden_characters': ['!']},
                         project={'delegation.never': ['data-export']})
        self.assertEqual(result['voice.forbidden_characters']['value'], ['\u2014', '!'])
        self.assertIn('production-approval-or-rollout', result['delegation.never']['value'])
        self.assertIn('data-export', result['delegation.never']['value'])
        self.assertIn('secrets', resolve(project={'delegation.never': []})['delegation.never']['value'])

    def test_project_cannot_change_court_settings_even_if_restrictive(self):
        for data in ({'voice.zone': 'UTC'}, {'forwards.max_lines': 1}, {'reports.max_chars': 1},
                     {'profiles.queen': resolve()['profiles.queen']['value']}, {'court.paused': True},
                     {'orders.omit': []}):
            with self.subTest(keys=list(data)), self.assertRaises(ConfigError):
                resolve(project=data)

    def test_owner_cannot_change_project_facts_or_create_grants(self):
        for data in ({'project.repository': 'example/project'}, {'publish.brand_terms': ['EXAMPLE']},
                     {'grants.backlog': True}, {'delegation.states': {'internal-pr-approval': 'delegated'}},
                     {'backlog.active': True}):
            with self.subTest(keys=list(data)), self.assertRaises(ConfigError):
                resolve(owner=data)

    def test_overrides_are_explicitly_allowlisted_and_restrictive(self):
        self.assertTrue(resolve(overrides={'court.paused': True})['court.paused']['value'])
        for data in ({'court.paused': False}, {'court.stopped': False}, {'voice.zone': 'UTC'},
                     {'project.repository': 'example/project'}, {'profiles.worker': {}},
                     {'unknown': True}):
            with self.subTest(keys=list(data)), self.assertRaises(ConfigError):
                resolve(overrides=data)

    def test_strict_loader_rejects_duplicates_nonfinite_and_nonobjects(self):
        cases = ['{"voice.zone":"UTC","voice.zone":"UTC"}',
                 '{"profiles.worker":{"agent":"codex","agent":"claude"}}',
                 '{"forwards.max_lines":NaN}', '{"forwards.max_lines":Infinity}',
                 '{"forwards.max_lines":-Infinity}', '{"forwards.max_lines":1e999}',
                 '[]', 'null', 'true', '7', '{"voice.zone": "UTC",}',
                 '{"voice.zone": "UTC"} {}', '\ufeff{}', b'\xff',
                 '{"voice.zone":"\\ud800"}']
        for raw in cases:
            with self.subTest(raw_type=type(raw).__name__), self.assertRaises(ConfigError):
                load(raw, 'owner')

    def test_bool_float_and_out_of_bounds_numbers_are_not_integers(self):
        for value in (True, False, 1.0, '1', -1, 0, 100001, None):
            with self.subTest(type=type(value).__name__), self.assertRaises(ConfigError):
                resolve(owner={'forwards.max_lines': value})
        with self.assertRaises(ConfigError):
            resolve(owner={'archive.hold_hours': 23})

    def test_profiles_are_complete_typed_data_not_partial_merges(self):
        profile = {'agent': 'codex', 'model': 'confirmed-model', 'effort': 'high', 'fast_mode': False}
        self.assertEqual(resolve(owner={'profiles.worker': profile})['profiles.worker']['value'], profile)
        for bad in ({'model': 'selected'}, {**profile, 'extra': True},
                    {**profile, 'fast_mode': 1}, {**profile, 'model': '-option'},
                    {**profile, 'effort': ''}, {**profile, 'model': 'x' * 129}):
            with self.subTest(fields=sorted(bad)), self.assertRaises(ConfigError):
                resolve(owner={'profiles.worker': bad})

    def test_nested_settings_and_why_references_are_rejected(self):
        for data in ({'voice': {'zone': 'UTC'}}, {'orders.notes': {'queen': 'Use brief answers.'}},
                     {'_why': []}, {'_why': {'voice.zone': 'No matching value.'}},
                     {'voice.zone': 'UTC', '_why': {'voice.zone': 7}}):
            with self.subTest(keys=list(data)), self.assertRaises(ConfigError):
                resolve(owner=data)

    def test_notes_remain_flat_bounded_role_data(self):
        notes = {'orders.notes.queen': 'Owner-provided note\nwith two lines.'}
        self.assertEqual(resolve(owner=notes)['orders.notes.queen']['value'], notes['orders.notes.queen'])
        with self.assertRaises(ConfigError):
            resolve(owner={'orders.notes.queen': 'x' * 2049})

    def test_errors_do_not_echo_values_unknown_keys_or_nested_keys(self):
        secret = 'confidential-fixture-value'
        cases = [json.dumps({secret: True}), json.dumps({'voice.zone': secret}),
                 json.dumps({'profiles.worker': {secret: secret}}),
                 '{"' + secret + '":1,"' + secret + '":2}',
                 json.dumps({'voice.zone': 'UTC', '_why': {secret: secret}})]
        for raw in cases:
            with self.subTest(index=cases.index(raw)):
                try:
                    load(raw, 'owner')
                except ConfigError as error:
                    self.assertNotIn(secret, str(error))
                    self.assertIsNone(error.__cause__)
                else:
                    self.fail('invalid private input accepted')
        with self.assertRaisesRegex(ConfigError, 'forwards.max_lines'):
            load('{"forwards.max_lines":false}', 'owner')

    def test_resource_bounds_are_enforced_before_resolving(self):
        for raw in (' ' * 65537, '{"voice.zone":' + '[' * 1000 + '0' + ']' * 1000 + '}',
                    '{"forwards.max_lines":' + '9' * 10000 + '}'):
            with self.assertRaises(ConfigError):
                load(raw, 'owner')
        with self.assertRaises(ConfigError):
            resolve(project={'project.required_checks': ['x'] * 65})
        with self.assertRaises(ConfigError):
            resolve(project={'project.required_checks': ['x' * 257]})

    def test_invalid_layer_and_non_json_python_values_are_rejected(self):
        for layer in ('defaults', 'private-fixture-layer', None):
            with self.assertRaises(ConfigError):
                load('{}', layer)
        for value in (b'{}', [], set(), {'voice.zone': object()}, {'voice.zone': float('nan')},
                      {1: 'UTC'}):
            with self.subTest(type=type(value).__name__), self.assertRaises(ConfigError):
                resolve(owner=value)

    def test_repository_timezone_and_clock_formats_are_checked(self):
        for value in ('../project', 'example/..', 'example/project/path', 'git@example/project'):
            with self.assertRaises(ConfigError):
                resolve(project={'project.repository': value})
        for value in ('25:00', '6:57', '06:99'):
            with self.assertRaises(ConfigError):
                resolve(owner={'cadence.digest_time': value})
        self.assertEqual(resolve(owner={'voice.zone': 'UTC'})['voice.zone']['value'], 'UTC')

    def test_results_inputs_and_schema_defaults_do_not_share_mutable_values(self):
        owner = {'archive.protected_workspaces': ['private-fixture']}
        before = copy.deepcopy(owner)
        result = resolve(owner=owner)
        result['archive.protected_workspaces']['value'].append('changed')
        result['profiles.worker']['value']['model'] = 'mutated'
        self.assertEqual(owner, before)
        self.assertEqual(resolve(owner=owner)['archive.protected_workspaces']['value'], ['private-fixture'])
        self.assertEqual(resolve()['profiles.worker']['value']['model'], 'gpt-6-astra')
        self.assertEqual(KEYS['profiles.worker']['default']['model'], 'gpt-6-astra')

    def test_defaults_digest_covers_values_and_policy_schema_deterministically(self):
        first = defaults_digest()
        self.assertRegex(first, '^[a-f0-9]{64}$')
        self.assertEqual(first, defaults_digest())
        old = KEYS['forwards.max_lines']['default']
        try:
            KEYS['forwards.max_lines']['default'] = 2
            self.assertNotEqual(defaults_digest(), first)
        finally:
            KEYS['forwards.max_lines']['default'] = old

    def test_lists_are_unique_and_ordered_deterministically(self):
        result = resolve(owner={'voice.forbidden_characters': ['!', '!', '?']})
        self.assertEqual(result['voice.forbidden_characters']['value'], ['\u2014', '!', '?'])
        first = resolve(project={'project.required_checks': ['b', 'a']})
        second = resolve(project={'project.required_checks': ['b', 'a']})
        self.assertEqual(first, second)

    def test_load_and_resolve_share_the_same_validation(self):
        raw = '{"forwards.max_lines":2,"_why":{"forwards.max_lines":"Concise."}}'
        data = load(raw.encode(), 'owner')
        self.assertEqual(resolve(owner=data)['forwards.max_lines']['value'], 2)
        self.assertEqual(data['_why']['forwards.max_lines'], 'Concise.')

    def test_widening_project_changes_identify_the_required_review(self):
        before = {'project.required_checks': ['unit', 'review'], 'backlog.builder_cap': 2}
        tightened = {'project.required_checks': ['unit', 'review', 'integration'], 'backlog.builder_cap': 1}
        self.assertEqual(widening(before, tightened), [])
        self.assertEqual(widening(before, {'project.required_checks': ['unit'], 'backlog.builder_cap': 3}),
                         ['backlog.builder_cap', 'project.required_checks'])
        self.assertEqual(widening({'backlog.builder_cap': 2}, {}), ['backlog.builder_cap'])
        self.assertEqual(widening({'project.repository': 'example/one'},
                                 {'project.repository': 'example/two'}), ['project.repository'])

    def test_widening_ignores_explanation_only_changes_but_not_removed_safety(self):
        before = {'project.required_checks': ['unit'], '_why': {'project.required_checks': 'Required.'}}
        after = {'project.required_checks': ['unit'], '_why': {'project.required_checks': 'Still required.'}}
        self.assertEqual(widening(before, after), [])
        self.assertEqual(widening({'archive.protected_workspaces': ['fixture']}, {}, layer='owner'),
                         ['archive.protected_workspaces'])
        self.assertEqual(widening({}, {'court.paused': True}, layer='overrides'), [])
        self.assertEqual(widening({'court.paused': True}, {}, layer='overrides'), ['court.paused'])

    def test_omissions_cannot_remove_invariants(self):
        with self.assertRaises(ConfigError):
            resolve(owner={'orders.omit': ['invariant.never-delegable']})
