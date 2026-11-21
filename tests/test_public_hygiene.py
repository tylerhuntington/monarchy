"""Fail before public release when maintained text includes private source facts."""
import hashlib
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_REPO = 'tylerhuntington/monarchy'
# Only digests of prohibited private identifiers are retained in public source.
PRIVATE_DIGESTS = {
    'a7de55ae7e824fe85ae75574d4609cc2b4361c297da88c6fe7202a60d9cf47fb',
    'fe14a0b3ff71923c2017961464f73958b3e13170ad5694768245a77e2cf712f9',
    '88b1cd6bde2ba482db337eec84c5d4cecdfaa819f22b59b3aa648d22ec5e3ea0',
    '0ba487dfcf4a93d392fc84023abcbb8356d2c189e2fb444c7deed69f9b0a7182',
}
ISSUE_LINK = re.compile(r'https?://github\.com/([^/\s]+)/([^/\s]+)/(?:issues|pull)/[0-9]+', re.I)
EMAIL = re.compile(r'(?<![\w.+-])[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}(?![\w.-])')


def violations(text):
    errors = set()
    for match in ISSUE_LINK.finditer(text):
        if '/'.join(match.groups()).casefold() != PUBLIC_REPO.casefold():
            errors.add('outside issue link')
    for match in EMAIL.finditer(text):
        if match.group() == 'git' + '@github.com' and text[match.end():].startswith(':'):
            continue  # SSH URL syntax, not a personal email address.
        errors.add('email address')
    tokens = [token.strip('.') for token in re.findall(r'[\w@.+/-]+', text.casefold())]
    for index in range(len(tokens)):
        for length in range(1, 5):
            phrase = ' '.join(tokens[index:index + length])
            if hashlib.sha256(phrase.encode()).hexdigest() in PRIVATE_DIGESTS:
                errors.add('private identifier')
        for part in tokens[index].split('/'):
            if hashlib.sha256(part.strip('.').encode()).hexdigest() in PRIVATE_DIGESTS:
                errors.add('private identifier')
    return errors


def maintained_text(path):
    # Upstream source/licenses keep their legally required attribution. Private
    # royalty state is gitignored and must never be added to the public repository.
    return (path.as_posix() != 'vendor/firstmate/LICENSE' and
            (path.suffix in {'.md', '.json', '.py', '.yaml', '.yml', '.sh', '.txt', '.toml'}
             or path.name in {'LICENSE', 'Makefile'}))


class PublicHygieneTests(unittest.TestCase):
    def test_maintained_public_text(self):
        files = subprocess.check_output(
            ['git', 'ls-files', '-z', '--cached', '--others', '--exclude-standard'], cwd=ROOT
        ).decode().split('\0')
        failures = []
        for name in sorted(set(files) - {''}):
            path = Path(name)
            if not maintained_text(path) or not (ROOT / path).is_file():
                continue
            for line, text in enumerate((ROOT / path).read_text().splitlines(), 1):
                if violations(text):
                    failures.append('{}:{}: {}'.format(name, line, ', '.join(sorted(violations(text)))))
        self.assertEqual(failures, [], '\n'.join(failures))

    def test_scope_keeps_first_party_wrappers_and_preserves_upstream_license(self):
        self.assertTrue(maintained_text(Path('assets/README.md')))
        self.assertTrue(maintained_text(Path('vendor/firstmate/README.md')))
        self.assertTrue(maintained_text(Path('vendor/firstmate/manifest.json')))
        self.assertFalse(maintained_text(Path('vendor/firstmate/LICENSE')))
        self.assertFalse(maintained_text(Path('vendor/firstmate/source.tar.gz')))

    def test_external_issue_links_fail_without_echoing_the_value(self):
        private_link = 'https://' + 'github.com/example/private/issues/42'
        self.assertEqual(violations(private_link), {'outside issue link'})

    def test_email_fails_but_ssh_remote_is_preserved(self):
        self.assertEqual(violations('someone' + '@' + 'example.org'), {'email address'})
        self.assertEqual(violations('git@github.com:example/project.git'), set())

    def test_public_tracking_links_are_allowed(self):
        self.assertEqual(violations('https://github.com/' + PUBLIC_REPO + '/issues/22'), set())

    def test_private_digest_matches_without_storing_identifier(self):
        synthetic = 'private-synthetic-fixture'
        digest = hashlib.sha256(synthetic.encode()).hexdigest()
        PRIVATE_DIGESTS.add(digest)
        try:
            self.assertIn('private identifier', violations(synthetic))
            self.assertIn('private identifier', violations('Do not publish ' + synthetic + '.'))
            self.assertIn('private identifier', violations('A path: owner/' + synthetic + '.'))
        finally:
            PRIVATE_DIGESTS.remove(digest)
