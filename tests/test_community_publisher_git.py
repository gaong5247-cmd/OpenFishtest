"""Trusted publisher Git tree / rate limit regression tests (no network)."""
import datetime as dt
from unittest.mock import Mock

import pytest

from community_publish import (
    GitHub, InvalidCommunitySubmission, APIError, MAX_PER_CONTRIBUTOR_DAILY,
)


def entry(submitter="Alice", timestamp=None, ident="a"*20):
    return {
        "id": ident,
        "contributor": submitter,
        "submitted_at": timestamp or dt.datetime.now(
            dt.timezone.utc
        ).isoformat(timespec="seconds"),
        "games": 2,
        "pgn_path": f"docs/data/community/{ident}/games.pgn",
        "epd_path": f"docs/data/community/{ident}/openings.epd",
        "verified": False,
    }


class SimulatedGH:
    """Exercise the exact main-branch Git API publication contract."""
    def __init__(self, existing=None, conflict=False):
        self.repo="gaong5247-cmd/OpenFishtest"
        self.writes=[]
        self.index=existing or {"version":1,"entries":[]}
        self.conflict=conflict
        self.patches=[]
        self.posted=[]
        self.blob_number=0

    def write_blob(self, raw):
        assert isinstance(raw, bytes)
        self.writes.append(raw)
        self.blob_number+=1
        return f"{self.blob_number:040x}"

    def current_head(self):
        return "a"*40,"b"*40

    def verify_no_overwrite(self, entry_id):
        assert len(entry_id)==20
        self.writes.append(b"checked:"+entry_id.encode())

    def index_for_main(self):
        return self.index

    def post(self, path, payload):
        self.posted.append((path,payload))
        if path.endswith("/git/trees"):
            assert payload["base_tree"]=="b"*40
            assert {e["path"] for e in payload["tree"]} == {
                "docs/data/community/"+("a"*20)+"/games.pgn",
                "docs/data/community/"+("a"*20)+"/openings.epd",
                "docs/data/community/index.json",
            }
            for item in payload["tree"]:
                assert item["mode"]=="100644"
            return {"sha":"c"*40}
        if path.endswith("/git/commits"):
            assert payload["tree"]=="c"*40
            assert payload["parents"] == ["a"*40]
            return {"sha":"d"*40}
        raise AssertionError(path)

    def patch(self, path, payload):
        self.patches.append((path,payload))
        if self.conflict:
            self.conflict=False
            raise APIError(409,"Concurrent main branch update")
        assert path.endswith("/git/refs/heads/main")
        assert payload["force"] is False
        return {}


def test_atomic_publication_of_only_canonical_data():
    fake=SimulatedGH()
    pgn=b'[Event "safe"]\n\n1. e4 e5 1-0\n'
    files={
        f"docs/data/community/{'a'*20}/games.pgn":pgn,
        f"docs/data/community/{'a'*20}/openings.epd":b"legal epd\n",
    }
    commit=GitHub.commit_publication(fake,files,entry())
    assert commit=="d"*40
    assert len(fake.patches)==1
    index=[value for value in fake.writes if value.startswith(b"{")][-1]
    import json
    metadata=json.loads(index)
    assert metadata["entries"][0]["verified"] is False
    assert metadata["entries"][0]["contributor"] == "Alice"
    assert len(metadata["entries"]) == 1


def test_rejects_duplicate_id_and_daily_quota():
    new=entry()
    for old_items in [
        [new],
        [entry(ident=f"{x:020x}") for x in range(1, MAX_PER_CONTRIBUTOR_DAILY+1)]
    ]:
        fake=SimulatedGH({"version":1,"entries":old_items})
        with pytest.raises(InvalidCommunitySubmission):
            GitHub.commit_publication(fake, {
                f"docs/data/community/{'a'*20}/games.pgn":b"pgn",
                f"docs/data/community/{'a'*20}/openings.epd":b"epd"
            },new)
        assert not fake.patches


def test_concurrent_ref_update_retries_without_forcing():
    fake=SimulatedGH(conflict=True)
    files={
        f"docs/data/community/{'a'*20}/games.pgn":b"pgn",
        f"docs/data/community/{'a'*20}/openings.epd":b"epd"
    }
    assert GitHub.commit_publication(fake,files,entry())=="d"*40
    assert len(fake.patches)==2
    assert all(value["force"] is False for _,value in fake.patches)
