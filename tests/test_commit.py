from pygit.commit import Commit, parse_commit, serialize_commit, build_identity


def test_build_identity_formats_positive_offset():
    result = build_identity("Ada Lovelace", "ada@example.com", 1700000000, 19800)
    assert result == "Ada Lovelace <ada@example.com> 1700000000 +0530"


def test_build_identity_formats_negative_offset():
    result = build_identity("Ada Lovelace", "ada@example.com", 1700000000, -18000)
    assert result == "Ada Lovelace <ada@example.com> 1700000000 -0500"


def test_commit_round_trips_no_parents():
    commit = Commit(
        tree="c" * 40, parents=[],
        author="Ada Lovelace <ada@example.com> 1700000000 +0000",
        committer="Ada Lovelace <ada@example.com> 1700000000 +0000",
        message="Root commit\n",
    )
    assert parse_commit(serialize_commit(commit)) == commit


def test_commit_round_trips_multiple_parents():
    commit = Commit(
        tree="d" * 40, parents=["e" * 40, "f" * 40],
        author="Ada Lovelace <ada@example.com> 1700000000 +0000",
        committer="Ada Lovelace <ada@example.com> 1700000000 +0000",
        message="Merge commit\n",
    )
    assert parse_commit(serialize_commit(commit)) == commit
