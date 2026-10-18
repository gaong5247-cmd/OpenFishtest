"""Administrator-only workflow_dispatch recovery of an exact merged data PR.

Never execute contributor code. This entry point is separate from automatic PR
publication; PR payload flags cannot authorize quota exceptions.
"""
import json
import os
import re

from community_publish import GitHub, REPO, publication_plan
from community_submission import InvalidCommunitySubmission


def authorize(gh, event, env):
    if (env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'
            or env.get('GITHUB_REPOSITORY') != REPO
            or env.get('GITHUB_REF') != 'refs/heads/main'
            or env.get('GITHUB_WORKFLOW_REF') != f'{REPO}/.github/workflows/community-backfill.yml@refs/heads/main'):
        raise InvalidCommunitySubmission('Backfill requires the canonical main workflow_dispatch')
    inputs = event.get('inputs', {})
    number = str(inputs.get('pr_number', ''))
    head = inputs.get('expected_head_sha', '')
    reason = inputs.get('reason', '').strip()
    if not re.fullmatch(r'[1-9][0-9]{0,9}', number) or not re.fullmatch(r'[0-9a-f]{40}', head):
        raise InvalidCommunitySubmission('Specify a PR number and exact 40-character head SHA')
    if not 10 <= len(reason) <= 500:
        raise InvalidCommunitySubmission('An approval reason of 10-500 characters is required')
    actors = [env.get('GITHUB_ACTOR', ''), env.get('GITHUB_TRIGGERING_ACTOR', '')]
    for actor in set(actors):
        if not re.fullmatch(r'[A-Za-z0-9-]{1,39}', actor):
            raise InvalidCommunitySubmission('Cannot identify the approving administrator')
        permission = gh.get(f'repos/{REPO}/collaborators/{actor}/permission')
        if permission.get('permission') != 'admin':
            raise InvalidCommunitySubmission('Both original and rerun actors must be repository administrators')
    run_id = env.get('GITHUB_RUN_ID', '')
    if not run_id.isdigit():
        raise InvalidCommunitySubmission('Missing Actions audit run ID')
    return int(number), head, {
        'actor': actors[0], 'triggering_actor': actors[1], 'reason': reason,
        'expected_head_sha': head,
        'run_url': f'https://github.com/{REPO}/actions/runs/{run_id}',
        'run_attempt': env.get('GITHUB_RUN_ATTEMPT', '1'),
        'contributor_daily_limit_exception': True,
    }


def main():
    with open(os.environ['GITHUB_EVENT_PATH'], encoding='utf-8') as stream:
        event = json.load(stream)
    gh = GitHub(os.environ['GITHUB_TOKEN'], os.environ['GITHUB_REPOSITORY'])
    number, head, audit = authorize(gh, event, os.environ)
    pr = gh.get(f'repos/{REPO}/pulls/{number}')
    files, entry = publication_plan(gh, {'pull_request': pr}, merged_head=head)
    if entry['source_pr'] != number:
        raise InvalidCommunitySubmission('PR identity mismatch')
    entry['backfill'] = audit
    # Recheck administrator permissions immediately before the write as well.
    authorize(gh, event, os.environ)
    commit = gh.commit_publication(files, entry, approved_backfill=True)
    # Fail visibly if deployment fails. Repeated publication is rejected; use
    # the existing Pages dispatch to retry deployment without republishing.
    gh.deploy_pages()
    summary = {'commit': commit, 'source_pr': number, 'games': entry['games'], 'approval': audit}
    print(json.dumps(summary, ensure_ascii=True))
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as stream:
            stream.write(f"Published {entry['games']} games from PR #{number}.\n\nCommit: `{commit}`\n\n")
            stream.write(f"Approval audit is stored in the public index; run: {audit['run_url']}\n")


if __name__ == '__main__':
    main()
