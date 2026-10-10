import io
import struct
import hashlib
import zlib
from unittest.mock import patch, MagicMock

import pytest

from pygit.remote import set_remote, get_remote_url
from pygit.repository import create_repo
from pygit.objects import hash_object
from pygit.http import pkt_line, pkt_flush


@pytest.fixture()
def repo(tmp_path):
    return create_repo(str(tmp_path))


def test_set_and_get_remote_url(repo):
    set_remote(repo, "origin", "https://example.com/repo.git")
    assert get_remote_url(repo, "origin") == "https://example.com/repo.git"


def test_get_remote_url_missing_raises(repo):
    with pytest.raises(ValueError, match="no remote"):
        get_remote_url(repo, "nonexistent")


def test_set_remote_overwrite(repo):
    set_remote(repo, "origin", "https://old.com/repo.git")
    set_remote(repo, "origin", "https://new.com/repo.git")
    assert get_remote_url(repo, "origin") == "https://new.com/repo.git"


def test_set_multiple_remotes(repo):
    set_remote(repo, "origin", "https://a.com/r.git")
    set_remote(repo, "upstream", "https://b.com/r.git")
    assert get_remote_url(repo, "origin") == "https://a.com/r.git"
    assert get_remote_url(repo, "upstream") == "https://b.com/r.git"


def _empty_pack():
    body = b"PACK" + struct.pack(">II", 2, 0)
    body += hashlib.sha1(body).digest()
    return body


def _blob_pack(content):
    compressed = zlib.compress(content)
    from pygit.pack import encode_object_header, OBJ_BLOB
    header = encode_object_header(OBJ_BLOB, len(content))
    entry = header + compressed
    sha_bytes = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\x00" + content).digest()
    pack_body = b"PACK" + struct.pack(">II", 2, 1) + entry
    pack_body += hashlib.sha1(pack_body).digest()
    return pack_body, sha_bytes.hex()


def _make_urlopen_mock(refs, pack_data):
    from pygit.http import pkt_line, pkt_flush
    def side_effect(req, *a, **kw):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "info/refs" in url:
            body = io.BytesIO()
            svc = "git-upload-pack"
            body.write(pkt_line(f"# service={svc}\n".encode()))
            body.write(pkt_flush())
            first = True
            for refname, sha in refs.items():
                if first:
                    line = f"{sha} {refname}\0ofs-delta\n".encode()
                    first = False
                else:
                    line = f"{sha} {refname}\n".encode()
                body.write(pkt_line(line))
            body.write(pkt_flush())
            raw = body.getvalue()
            mock_resp = MagicMock()
            mock_resp.read.return_value = raw
            mock_resp.headers = {"Content-Type": "application/x-git-upload-pack-advertisement"}
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp
        else:
            resp_body = pkt_line(b"NAK\n") + pkt_flush() + pack_data
            mock_resp = MagicMock()
            mock_resp.read.return_value = resp_body
            mock_resp.headers = {"Content-Type": "application/x-git-upload-pack-result"}
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp
    return side_effect


def test_fetch_from_remote_writes_tracking_refs(repo, tmp_path):
    from pygit.fetch import fetch_from_remote
    from pygit.refs import resolve_ref
    set_remote(repo, "origin", "https://example.com/r.git")
    sha = "a" * 40
    refs = {"refs/heads/main": sha}
    with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(refs, _empty_pack())):
        updated = fetch_from_remote(repo, "origin")
    assert "refs/remotes/origin/main" in updated
    assert resolve_ref(repo, "refs/remotes/origin/main") == sha


def test_fetch_from_remote_no_new_objects_skips_pack(repo):
    from pygit.fetch import fetch_from_remote
    set_remote(repo, "origin", "https://example.com/r.git")
    sha = hash_object(repo, b"existing", "blob", write=True)
    refs = {"refs/heads/main": sha}
    called_upload_pack = []
    def side_effect(req, *a, **kw):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "info/refs" in url:
            body = io.BytesIO()
            svc = "git-upload-pack"
            body.write(pkt_line(f"# service={svc}\n".encode()))
            body.write(pkt_flush())
            body.write(pkt_line(f"{sha} refs/heads/main\0ofs-delta\n".encode()))
            body.write(pkt_flush())
            raw = body.getvalue()
            mock_resp = MagicMock()
            mock_resp.read.return_value = raw
            mock_resp.headers = {"Content-Type": "application/x-git-upload-pack-advertisement"}
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp
        else:
            called_upload_pack.append(True)
            mock_resp = MagicMock()
            mock_resp.read.return_value = pkt_line(b"NAK\n") + pkt_flush() + _empty_pack()
            mock_resp.headers = {"Content-Type": "application/x-git-upload-pack-result"}
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp
    with patch("urllib.request.urlopen", side_effect=side_effect):
        updated = fetch_from_remote(repo, "origin")
    assert not called_upload_pack


def test_pull_already_up_to_date(repo):
    from pygit.porcelain import pull
    from pygit.refs import write_ref, resolve_ref
    sha = hash_object(repo, b"commit content", "blob", write=True)
    write_ref(repo, "refs/heads/main", sha)
    write_ref(repo, "refs/remotes/origin/main", sha)
    set_remote(repo, "origin", "https://example.com/r.git")
    refs = {"refs/heads/main": sha}
    with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(refs, _empty_pack())):
        result = pull(repo, "origin", "main")
    assert result == "Already up to date."


def test_pull_diverged_raises(repo):
    from pygit.porcelain import pull
    from pygit.refs import write_ref
    from pygit.commit import Commit, serialize_commit
    import time
    identity = "Test User <t@t.com> 0 +0000"
    blob = hash_object(repo, b"data", "blob", write=True)
    from pygit.tree import TreeEntry, serialize_tree
    tree_data = serialize_tree([TreeEntry("100644", "f", blob)])
    tree = hash_object(repo, tree_data, "tree", write=True)
    c1 = Commit(tree=tree, parents=[], author=identity, committer=identity, message="c1\n")
    sha1 = hash_object(repo, serialize_commit(c1), "commit", write=True)
    c2 = Commit(tree=tree, parents=[], author=identity, committer=identity, message="c2\n")
    sha2 = hash_object(repo, serialize_commit(c2), "commit", write=True)
    write_ref(repo, "refs/heads/main", sha1)
    write_ref(repo, "refs/remotes/origin/main", sha2)
    set_remote(repo, "origin", "https://example.com/r.git")
    refs = {"refs/heads/main": sha2}
    with patch("urllib.request.urlopen", side_effect=_make_urlopen_mock(refs, _empty_pack())):
        with pytest.raises(ValueError, match="diverged"):
            pull(repo, "origin", "main")
