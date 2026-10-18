"""Administrator backfill authorization, immutable sources and quota regression."""
import base64
import copy
import json
from unittest.mock import Mock

import pytest

from community_backfill import authorize
from community_publish import GitHub, REPO, publication_plan
from community_submission import InvalidCommunitySubmission
from test_community_auto_publish import sample_data, _git_sha
from test_community_publisher_git import SimulatedGH, entry


def context():
    return ({'inputs': {'pr_number': '26', 'expected_head_sha': 'f'*40,
                        'reason': 'Recover approved existing games'}}, {
        'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REPOSITORY': REPO,
        'GITHUB_REF': 'refs/heads/main',
        'GITHUB_WORKFLOW_REF': f'{REPO}/.github/workflows/community-backfill.yml@refs/heads/main',
        'GITHUB_ACTOR': 'Owner', 'GITHUB_TRIGGERING_ACTOR': 'Owner',
        'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
    })


def test_admin_authorization_and_audit():
    event, env = context()
    gh = Mock()
    gh.get.return_value = {'permission': 'admin'}
    number, head, audit = authorize(gh, event, env)
    assert (number, head) == (26, 'f'*40)
    assert audit['actor'] == 'Owner' and audit['run_url'].endswith('/123')
    gh.get.assert_called_once_with(f'repos/{REPO}/collaborators/Owner/permission')


@pytest.mark.parametrize('key,value', [
    ('GITHUB_EVENT_NAME', 'pull_request_target'), ('GITHUB_REF', 'refs/heads/feature'),
    ('GITHUB_REPOSITORY', 'other/fork'), ('GITHUB_WORKFLOW_REF', 'other/workflow'),
    ('GITHUB_TRIGGERING_ACTOR', ''), ('GITHUB_RUN_ID', 'bad'),
])
def test_untrusted_execution_context_rejected(key, value):
    event, env = context()
    env[key] = value
    gh = Mock()
    gh.get.return_value = {'permission': 'admin'}
    with pytest.raises(InvalidCommunitySubmission):
        authorize(gh, event, env)


@pytest.mark.parametrize('permission', ['write', 'maintain', 'read', 'none', None])
def test_non_admin_cannot_approve_or_rerun(permission):
    event, env = context()
    env['GITHUB_TRIGGERING_ACTOR'] = 'Contributor'
    gh = Mock()
    gh.get.side_effect = lambda path: {'permission': permission if '/Contributor/' in path else 'admin'}
    with pytest.raises(InvalidCommunitySubmission, match='administrators'):
        authorize(gh, event, env)


@pytest.mark.parametrize('key,value', [('expected_head_sha', 'main'), ('pr_number', '0'), ('reason', '')])
def test_approval_must_pin_one_pr_and_head(key, value):
    event, env = context()
    event['inputs'][key] = value
    with pytest.raises(InvalidCommunitySubmission):
        authorize(Mock(), event, env)


def source():
    pgn, epd = sample_data()
    pr = {'number': 26, 'state': 'closed', 'merged': True, 'draft': False,
          'user': {'login': 'Owner'}, 'changed_files': 2,
          'head': {'sha': 'f'*40, 'repo': {'full_name': REPO}},
          'base': {'ref': 'main', 'repo': {'full_name': REPO}}}
    changes = [{'filename': f'submissions/{"a"*20}/{name}', 'status': 'added', 'sha': _git_sha(raw)}
               for name, raw in [('games.pgn', pgn), ('openings.epd', epd)]]
    gh = Mock()
    gh.repo = REPO
    def get(path):
        if '/contents/' in path:
            assert path.endswith('?ref=' + 'f'*40)
            return {'type': 'file', 'sha': changes[0 if '/games.pgn?' in path else 1]['sha']}
        return changes if '/files?' in path else pr
    gh.get.side_effect = get
    gh.blob_bytes.side_effect = lambda repo, sha, limit: pgn if sha == _git_sha(pgn) else epd
    return gh, pr, changes


def test_merged_backfill_uses_existing_validator_but_normal_path_still_rejects_closed():
    gh, pr, _ = source()
    files, result = publication_plan(gh, {'pull_request': pr}, merged_head='f'*40)
    assert result['games'] == 2 and result['source_pr'] == 26
    assert len(files) == 2 and result['verified'] is False
    with pytest.raises(InvalidCommunitySubmission):
        publication_plan(gh, {'pull_request': pr, 'approved_backfill': True})


@pytest.mark.parametrize('change', ['unmerged', 'head', 'base', 'draft', 'count', 'path', 'blob'])
def test_unsafe_merged_source_rejected(change):
    gh, pr, changes = source()
    if change == 'unmerged': pr['merged'] = False
    if change == 'head': pr['head']['sha'] = 'e'*40
    if change == 'base': pr['base']['ref'] = 'other'
    if change == 'draft': pr['draft'] = True
    if change == 'count': pr['changed_files'] = 3
    if change == 'path': changes[0]['filename'] = 'evil.py'
    if change == 'blob':
        original = gh.get.side_effect
        gh.get.side_effect = lambda path: {'type': 'file', 'sha': '0'*40} if '/contents/' in path else original(path)
    with pytest.raises(InvalidCommunitySubmission):
        publication_plan(gh, {'pull_request': pr}, merged_head='f'*40)


def test_source_changed_after_validation_rejected():
    gh, pr, _ = source()
    original = gh.get.side_effect
    calls = 0
    def get(path):
        nonlocal calls
        if path.endswith('/pulls/26'):
            calls += 1
            if calls == 2:
                changed = copy.deepcopy(pr)
                changed['head']['sha'] = '0'*40
                return changed
        return original(path)
    gh.get.side_effect = get
    with pytest.raises(InvalidCommunitySubmission):
        publication_plan(gh, {'pull_request': pr}, merged_head='f'*40)


def test_blob_integrity_still_checked():
    gh = Mock()
    gh.get.return_value = {'encoding': 'base64', 'size': 3, 'content': base64.b64encode(b'bad').decode()}
    with pytest.raises(InvalidCommunitySubmission, match='integrity'):
        GitHub.blob_bytes(gh, REPO, _git_sha(b'yes'), 10)


def test_explicit_backfill_exception_keeps_duplicates_global_limit_and_audit():
    files = {f'docs/data/community/{"a"*20}/{name}': b'data' for name in ('games.pgn', 'openings.epd')}
    rows = [entry(ident=f'{i:020x}') for i in range(1, 4)]
    new = entry()
    new['backfill'] = {'actor': 'Owner', 'reason': 'Approved recovery'}
    # Even a supplied metadata flag cannot change normal PR quotas.
    with pytest.raises(InvalidCommunitySubmission, match='Contributor daily'):
        GitHub.commit_publication(SimulatedGH({'entries': rows}), files, new)
    fake = SimulatedGH({'entries': rows})
    GitHub.commit_publication(fake, files, new, approved_backfill=True)
    index = json.loads(next(x for x in fake.writes if x.startswith(b'{')))
    assert index['entries'][0]['backfill'] == new['backfill']
    assert index['entries'][1:] == rows
    for existing, message in [(index['entries'], 'Duplicate'),
                              ([entry(ident=f'{i:020x}') for i in range(1, 21)], 'Community daily')]:
        with pytest.raises(InvalidCommunitySubmission, match=message):
            GitHub.commit_publication(SimulatedGH({'entries': existing}), files, new, approved_backfill=True)
