"""GitHub REST create-ref event normalization tests.

A new branch generated with REST creates a branch CREATE event, not
necessarily a PUSH. The publisher must bind event branch + immutable SHA.
"""
import pytest

from community_direct_upload import (
    InvalidCommunitySubmission, normalize_create_event
)


def test_create_event_binds_sha_to_uploaded_branch():
    suffix = "ab" * 12
    sha = "c" * 40
    result = normalize_create_event(
        {"ref_type": "branch", "ref": "community-upload/" + suffix},
        ref="refs/heads/community-upload/" + suffix,
        sha=sha,
    )
    assert result["ref"] == "refs/heads/community-upload/" + suffix
    assert result["after"] == sha


@pytest.mark.parametrize("payload,ref,sha", [
    ({"ref_type":"tag","ref":"community-upload/"+"a"*24},
     "refs/tags/community-upload/"+"a"*24,"b"*40),
    ({"ref_type":"branch","ref":"community-upload/not-hex"},
     "refs/heads/community-upload/not-hex","b"*40),
    ({"ref_type":"branch","ref":"community-upload/"+"a"*24},
     "refs/heads/other/"+"a"*24,"b"*40),
    ({"ref_type":"branch","ref":"community-upload/"+"a"*24},
     "refs/heads/community-upload/"+"a"*24,"invalid"),
])
def test_create_event_rejects_mismatched_refs(payload,ref,sha):
    with pytest.raises(InvalidCommunitySubmission):
        normalize_create_event(payload, ref=ref, sha=sha)
