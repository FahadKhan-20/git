# Smart HTTP protocol implementation plan

Spec: `docs/superpowers/specs/2026-07-29-smart-http-design.md`

Each task: failing test → minimal code → passing test. No commits, no PRs today.
No inline code comments or docstrings in `pygit/` source files.

---

## Task 1 — `pkt_line`, `pkt_flush`, `ProtocolError`

### Tests (`tests/test_http.py`, new file)

```python
import io
import pytest
from pygit.http import pkt_line, pkt_flush, read_pkt_lines, ProtocolError


def test_pkt_line_empty():
    assert pkt_line(b"") == b"0004"


def test_pkt_line_short():
    # "hello\n" = 6 bytes, total = 10 = 0x000a
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
```

### Implementation (`pygit/http.py`, new file)

```python
class ProtocolError(Exception):
    pass


def pkt_line(data):
    length = 4 + len(data)
    return f"{length:04x}".encode() + data


def pkt_flush():
    return b"0000"
```

---

## Task 2 — `read_pkt_lines`

### Tests (append to `tests/test_http.py`)

```python
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
    # says length 10 (0x000a = 10 total, 6 payload) but only has 3 payload bytes
    with pytest.raises(ProtocolError):
        read_pkt_lines(io.BytesIO(b"000ahel"))
```

### Implementation (append to `pygit/http.py`)

```python
def read_pkt_lines(stream):
    result = []
    while True:
        raw = stream.read(4)
        if not raw:
            break
        if len(raw) < 4:
            raise ProtocolError(f"truncated pkt-line length: {raw!r}")
        try:
            length = int(raw, 16)
        except ValueError:
            raise ProtocolError(f"invalid pkt-line length: {raw!r}")
        if length == 0:
            result.append(None)
            continue
        if length == 1:
            continue  # delim packet (protocol v2), skip
        payload_len = length - 4
        payload = stream.read(payload_len)
        if len(payload) < payload_len:
            raise ProtocolError(f"truncated pkt-line payload (expected {payload_len}, got {len(payload)})")
        result.append(payload)
    return result
```

---

## Task 3 — `discover_refs` (mocked HTTP)

### Tests (append to `tests/test_http.py`)

```python
from unittest.mock import patch, MagicMock
from pygit.http import discover_refs


def _make_response(body: bytes, content_type: str):
    resp = MagicMock()
    resp.read.return_value = body
    resp.headers = {"Content-Type": content_type}
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _build_advertisement(service, refs, caps):
    import io
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
```

### Implementation (append to `pygit/http.py`)

```python
import io
import urllib.request


def _parse_advertisement(body, expected_service):
    stream = io.BytesIO(body)
    lines = read_pkt_lines(stream)
    if not lines or lines[0] is None:
        raise ProtocolError("empty advertisement")
    svc_line = lines[0].decode(errors="replace").strip()
    if svc_line != f"# service={expected_service}":
        raise ProtocolError(f"unexpected service line: {svc_line!r}")
    if len(lines) < 2 or lines[1] is not None:
        raise ProtocolError("missing flush after service line")
    refs = {}
    caps = set()
    first = True
    for line in lines[2:]:
        if line is None:
            continue
        text = line.decode(errors="replace").rstrip("\n")
        if first:
            if "\0" in text:
                ref_part, cap_part = text.split("\0", 1)
                caps = set(cap_part.split())
            else:
                ref_part = text
            first = False
        else:
            ref_part = text
        sha, name = ref_part.split(" ", 1)
        refs[name] = sha
    return refs, caps


def discover_refs(url):
    svc = "git-upload-pack"
    req = urllib.request.Request(
        url.rstrip("/") + f"/info/refs?service={svc}",
        headers={"Git-Protocol": "version=1"},
    )
    with urllib.request.urlopen(req) as resp:
        ct = resp.headers.get("Content-Type", "")
        if ct != f"application/x-{svc}-advertisement":
            raise ProtocolError(f"unexpected Content-Type: {ct!r}")
        body = resp.read()
    return _parse_advertisement(body, svc)


def discover_refs_receive(url):
    svc = "git-receive-pack"
    req = urllib.request.Request(
        url.rstrip("/") + f"/info/refs?service={svc}",
        headers={"Git-Protocol": "version=1"},
    )
    with urllib.request.urlopen(req) as resp:
        ct = resp.headers.get("Content-Type", "")
        if ct != f"application/x-{svc}-advertisement":
            raise ProtocolError(f"unexpected Content-Type: {ct!r}")
        body = resp.read()
    return _parse_advertisement(body, svc)
```

---

## Task 4 — `fetch_pack` (mocked HTTP)

### Tests (append to `tests/test_http.py`)

```python
import hashlib
import struct
from pygit.http import fetch_pack


def _empty_pack():
    body = b"PACK" + struct.pack(">II", 2, 0)
    body += hashlib.sha1(body).digest()
    return body


def _make_fetch_response(pack_data):
    # Server sends: NAK\n pkt-line, then flush, then raw pack bytes
    body = pkt_line(b"NAK\n") + pkt_flush() + pack_data
    return body


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
```

### Implementation (append to `pygit/http.py`)

```python
def fetch_pack(url, wants, haves=()):
    svc = "git-upload-pack"
    body = b""
    for sha in wants:
        body += pkt_line(f"want {sha}\n".encode())
    for sha in haves:
        body += pkt_line(f"have {sha}\n".encode())
    body += pkt_flush()
    body += pkt_line(b"done\n")
    req = urllib.request.Request(
        url.rstrip("/") + f"/{svc}",
        data=body,
        headers={
            "Content-Type": f"application/x-{svc}-request",
            "Accept": f"application/x-{svc}-result",
        },
    )
    with urllib.request.urlopen(req) as resp:
        ct = resp.headers.get("Content-Type", "")
        if ct != f"application/x-{svc}-result":
            raise ProtocolError(f"unexpected Content-Type: {ct!r}")
        raw = resp.read()
    stream = io.BytesIO(raw)
    lines = []
    while True:
        length_bytes = stream.read(4)
        if not length_bytes:
            break
        try:
            length = int(length_bytes, 16)
        except ValueError:
            raise ProtocolError(f"invalid pkt-line length: {length_bytes!r}")
        if length == 0:
            break
        payload = stream.read(length - 4)
        lines.append(payload)
    return stream.read()
```

---

## Task 5 — `send_pack` (mocked HTTP)

### Tests (append to `tests/test_http.py`)

```python
from pygit.http import send_pack


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
```

### Implementation (append to `pygit/http.py`)

```python
def send_pack(url, ref_updates, pack_data):
    svc = "git-receive-pack"
    body = b""
    for old_sha, new_sha, refname in ref_updates:
        body += pkt_line(f"{old_sha} {new_sha} {refname}\n".encode())
    body += pkt_flush()
    body += pack_data
    req = urllib.request.Request(
        url.rstrip("/") + f"/{svc}",
        data=body,
        headers={
            "Content-Type": f"application/x-{svc}-request",
            "Accept": f"application/x-{svc}-result",
        },
    )
    with urllib.request.urlopen(req) as resp:
        ct = resp.headers.get("Content-Type", "")
        if ct != f"application/x-{svc}-result":
            raise ProtocolError(f"unexpected Content-Type: {ct!r}")
        raw = resp.read()
    result = {}
    for line in read_pkt_lines(io.BytesIO(raw)):
        if line is None:
            continue
        text = line.decode(errors="replace").rstrip("\n")
        if text.startswith("ok "):
            result[text[3:]] = None
        elif text.startswith("ng "):
            parts = text[3:].split(" ", 1)
            result[parts[0]] = parts[1] if len(parts) > 1 else ""
    return result
```

---

## Task 6 — `discover_refs_receive` (mocked HTTP)

### Tests (append to `tests/test_http.py`)

```python
from pygit.http import discover_refs_receive


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
```

---

## Task 7 — README update

### Changes to `README.md`

1. After the "## Reading packed objects" section, add:

```markdown
## Wire protocol

pygit implements the Git Smart HTTP transport layer (`pygit/http.py`) as the foundation for
`clone`, `fetch`, and `push`. All Git network traffic uses **pkt-line framing**: each message is a
4-hex-digit length prefix (the total byte count including the prefix itself) followed by the
payload; `0000` is a flush packet marking message boundaries. On top of that, two request/response
pairs cover the protocol:

- **Ref discovery** (`GET /info/refs?service=git-upload-pack` or `git-receive-pack`) — the server
  advertises its refs and capabilities in a structured pkt-line response.
- **`upload-pack`** (`POST /git-upload-pack`) — the client sends `want`/`have`/`done` pkt-lines
  and receives a packfile response; this is what `fetch` and `clone` use.
- **`receive-pack`** (`POST /git-receive-pack`) — the client sends ref-update commands plus a
  packfile; this is what `push` uses.

`clone`, `fetch`, and `push` commands are not yet exposed as CLI commands — that is sub-projects 3
and 4.
```

2. Add to "## Known limitations":

```
- Smart HTTP protocol primitives are implemented (`http.py`), but `clone`, `fetch`, and `push` are not yet wired up as CLI commands — those are sub-projects 3 and 4.
```
