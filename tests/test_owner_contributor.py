from unittest.mock import patch

from contributor_submit import TARGET, _fork_if_needed


def test_owner_is_not_a_fork():
    assert TARGET.split("/")[0] == "gaong5247-cmd"


def test_existing_non_owner_fork_is_checked():
    with patch("contributor_submit.run", return_value=TARGET) as mocked:
        assert _fork_if_needed("external-chess-user", {}) == (
            "external-chess-user/OpenFishtest"
        )
        assert mocked.call_count == 1
