import hashlib
import io
import struct
from unittest.mock import MagicMock, patch

import pytest

from pygit.http import (
    ProtocolError,
    discover_refs,
    discover_refs_receive,
    fetch_pack,
    pkt_flush,
    pkt_line,
    read_pkt_lines,
    send_pack,
)


def test_pkt_line_empty():
    assert pkt_line(b"") == b"0004"


def test_pkt_line_short():
    assert pkt_line(b"hello\n") == b"000ahello\n"


def test_pkt_line_longer():
    payload = b"want " + b"a" * 40 + b"\n"
    result = pkt_line(payload)
    length = int(result[:4], 16)
    assert length == 4 + len(payload)
    assert result[4:] == payload


def test_pkt_flush():
    assert pkt_flush() == b"0000"


def test_pkt_line_roundtrip_via_read():
    data = pkt_line(b"hello\n") + pkt_flush() + pkt_line(b"world\n") + pkt_flush()
    lines = read_pkt_lines(io.BytesIO(data))
    assert lines == [b"hello\n", None, b"world\n", None]


def test_read_pkt_lines_empty_stream():
    assert read_pkt_lines(io.BytesIO(b"")) == []


def test_read_pkt_lines_single_flush():
    assert read_pkt_lines(io.BytesIO(b"0000")) == [None]


def test_read_pkt_lines_sequence():
    raw = pkt_line(b"ref1\n") + pkt_flush() + pkt_line(b"ref2\n")
    result = read_pkt_lines(io.BytesIO(raw))
    assert result == [b"ref1\n", None, b"ref2\n"]


def test_read_pkt_lines_bad_hex_raises():
    with pytest.raises(ProtocolError):
        read_pkt_lines(io.BytesIO(b"ZZZZ"))


def test_read_pkt_lines_truncated_raises():
    with pytest.raises(ProtocolError):
        read_pkt_lines(io.BytesIO(b"000ahel"))


def _make_response(body, content_type):
    resp = MagicMock()
    resp.read.return_value = body
    resp.headers = {"Content-Type": content_type}
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _build_advertisement(service, refs, caps):
    body = io.BytesIO()
    svc_line = f"# service={service}\n".encode()
    body.write(pkt_line(svc_line))
    body.write(pkt_flush())
    first = True
    for sha, name in refs:
        if first:
            line = f"{sha} {name}\0{' '.join(caps)}\n".encode()
            first = False
        else:
            line = f"{sha} {name}\n".encode()
        body.write(pkt_line(line))
    body.write(pkt_flush())
    return body.getvalue()


def test_discover_refs_returns_refs_and_caps():
    sha = "a" * 40
    body = _build_advertisement(
        "git-upload-pack",
        [(sha, "refs/heads/main")],
        ["multi_ack", "side-band-64k"],
    )
    resp = _make_response(body, "application/x-git-upload-pack-advertisement")
    with patch("urllib.request.urlopen", return_value=resp):
        refs, caps = discover_refs("https://example.com/repo.git")
    assert refs == {"refs/heads/main": sha}
    assert "multi_ack" in caps
    assert "side-band-64k" in caps


def test_discover_refs_multiple_refs():
    sha1, sha2 = "a" * 40, "b" * 40
    body = _build_advertisement(
        "git-upload-pack",
        [(sha1, "refs/heads/main"), (sha2, "refs/heads/dev")],
        ["ofs-delta"],
    )
    resp = _make_response(body, "application/x-git-upload-pack-advertisement")
    with patch("urllib.request.urlopen", return_value=resp):
        refs, caps = discover_refs("https://example.com/repo.git")
    assert refs["refs/heads/main"] == sha1
    assert refs["refs/heads/dev"] == sha2


def test_discover_refs_wrong_content_type_raises():
    resp = _make_response(b"not a git server", "text/html")
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(ProtocolError):
            discover_refs("https://example.com/repo.git")


def _empty_pack():
    body = b"PACK" + struct.pack(">II", 2, 0)
    body += hashlib.sha1(body).digest()
    return body


def _make_fetch_response(pack_data):
    return pkt_line(b"NAK\n") + pkt_flush() + pack_data


def test_fetch_pack_returns_pack_bytes():
    pack = _empty_pack()
    body = _make_fetch_response(pack)
    resp = _make_response(body, "application/x-git-upload-pack-result")
    sha = "a" * 40
    with patch("urllib.request.urlopen", return_value=resp):
        result = fetch_pack("https://example.com/repo.git", [sha])
    assert result == pack


def test_fetch_pack_wrong_content_type_raises():
    resp = _make_response(b"", "text/html")
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(ProtocolError):
            fetch_pack("https://example.com/repo.git", ["a" * 40])


def test_fetch_pack_empty_wants_returns_empty_pack():
    pack = _empty_pack()
    body = pkt_line(b"NAK\n") + pkt_flush() + pack
    resp = _make_response(body, "application/x-git-upload-pack-result")
    with patch("urllib.request.urlopen", return_value=resp):
        result = fetch_pack("https://example.com/repo.git", [])
    assert result == pack


def _make_send_response(ok_refs, ng_refs=None):
    body = b""
    for ref in ok_refs:
        body += pkt_line(f"ok {ref}\n".encode())
    for ref, reason in (ng_refs or {}).items():
        body += pkt_line(f"ng {ref} {reason}\n".encode())
    body += pkt_flush()
    return body


def test_send_pack_ok():
    body = _make_send_response(["refs/heads/main"])
    resp = _make_response(body, "application/x-git-receive-pack-result")
    zero = "0" * 40
    sha = "a" * 40
    pack = _empty_pack()
    with patch("urllib.request.urlopen", return_value=resp):
        result = send_pack(
            "https://example.com/repo.git",
            [(zero, sha, "refs/heads/main")],
            pack,
        )
    assert result == {"refs/heads/main": None}


def test_send_pack_ng():
    body = _make_send_response([], ng_refs={"refs/heads/main": "non-fast-forward"})
    resp = _make_response(body, "application/x-git-receive-pack-result")
    zero = "0" * 40
    sha = "a" * 40
    pack = _empty_pack()
    with patch("urllib.request.urlopen", return_value=resp):
        result = send_pack(
            "https://example.com/repo.git",
            [(zero, sha, "refs/heads/main")],
            pack,
        )
    assert result == {"refs/heads/main": "non-fast-forward"}


def test_send_pack_wrong_content_type_raises():
    resp = _make_response(b"", "text/html")
    with patch("urllib.request.urlopen", return_value=resp):
        with pytest.raises(ProtocolError):
            send_pack("https://example.com/repo.git", [], _empty_pack())


def test_discover_refs_receive_returns_refs():
    sha = "c" * 40
    body = _build_advertisement(
        "git-receive-pack",
        [(sha, "refs/heads/main")],
        ["delete-refs", "report-status"],
    )
    resp = _make_response(body, "application/x-git-receive-pack-advertisement")
    with patch("urllib.request.urlopen", return_value=resp):
        refs, caps = discover_refs_receive("https://example.com/repo.git")
    assert refs == {"refs/heads/main": sha}
    assert "delete-refs" in caps
