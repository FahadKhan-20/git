# pygit Smart HTTP protocol

## Goal

Implement the Git Smart HTTP transport layer in a new module `pygit/http.py`, providing the
protocol primitives that `clone`, `fetch`, and `push` will build on top of.

This is phase 2 of the "packfiles + network protocol" block. Phase 1 (pack reading + writing) is
complete. This phase adds:

- **pkt-line framing** — the byte-level wire format used for all Git protocol messages.
- **ref discovery** (`/info/refs?service=git-upload-pack` and `/info/refs?service=git-receive-pack`)
  — request the server's advertised refs and capabilities.
- **`upload-pack` negotiation** (client side) — send `want`/`have`/`done` lines, receive the
  server's packfile response. This is what `fetch` and `clone` use.
- **`receive-pack` negotiation** (client side) — send ref-update commands + a packfile,
  receive the server's report. This is what `push` uses.

This phase does **not** implement the `clone`, `fetch`, or `push` porcelain commands (those are
sub-projects 3 and 4 which build on top of this layer). It implements only the transport protocol
itself, so it can be tested directly against a real Git HTTP server.

## Non-goals

- Protocol v2 (`version=2` capability). This phase implements protocol v1 only, which is what
  most public Git servers still speak by default. Protocol v2 is a separate upgrade.
- SSH transport. HTTP only.
- Authentication (Basic, OAuth, credential helpers). URLs with embedded credentials
  (`https://user:pass@host/repo`) are supported; interactive prompting is not.
- HTTP redirects beyond what `urllib` handles automatically.
- Resumable / partial fetches (shallow clone is not in scope here).
- Server-side implementation (we are the client only).

## Architecture

A new module `pygit/http.py` implements the protocol layer. It has no dependency on any other
`pygit` module except `pack.py` (for constructing the packfile payload on push). The plumbing and
porcelain commands that eventually call it will live in separate modules (`clone.py`, `fetch.py`,
`push.py`) added in sub-projects 3 and 4.

```
pygit/
  http.py     # new: pkt-line framing, ref discovery, upload-pack, receive-pack client
```

## pkt-line framing

Every message in the Git wire protocol (both request and response) is a sequence of **pkt-lines**:

- A pkt-line is a 4-hex-digit big-endian length (the total byte count of the line including the
  4-byte prefix itself), followed by that many bytes of payload.
- The length `0000` is a **flush packet** — a message boundary with zero payload.
- The length `0001` is a **delim packet** (protocol v2 only — not used here).
- The minimum non-flush, non-delim length is `0005` (4 + 1 byte of payload).
- Maximum payload length: 65520 bytes (so maximum total line length is `ffff` = 65535).

```python
# pygit/http.py

def pkt_line(data: bytes) -> bytes:
    """Encode one payload into a pkt-line (length prefix + data)."""

def pkt_flush() -> bytes:
    """Return the 4-byte flush packet b'0000'."""

def read_pkt_lines(stream) -> list[bytes | None]:
    """
    Read pkt-lines from a binary stream until EOF.
    Returns a list where each element is either a payload bytes object
    or None (representing a flush packet). Raises ProtocolError on
    malformed length fields.
    """
```

## Ref discovery

Git Smart HTTP ref discovery is a two-step HTTP exchange:

**Step 1 — service discovery** (`GET /info/refs?service=<svc>`):

The server responds with:
- HTTP 200, `Content-Type: application/x-git-<svc>-advertisement`
- Body: one pkt-line `# service=git-<svc>\n`, then a flush packet `0000`, then the ref list.

The ref list is a sequence of pkt-lines, each:
- First line (capabilities): `<sha> <refname>\0<cap1> <cap2> ...\n`
- Subsequent lines: `<sha> <refname>\n`
- Terminated by a flush packet.

**Step 2 result** — a dict `{refname: sha}` plus a set of server capability strings.

```python
def discover_refs(url: str) -> tuple[dict[str, str], set[str]]:
    """
    Perform Smart HTTP ref discovery for the upload-pack service.
    Returns ({refname: sha40}, {capability_string}).
    Raises ProtocolError if the server response is not a valid Smart HTTP advertisement.
    """

def discover_refs_receive(url: str) -> tuple[dict[str, str], set[str]]:
    """Same as discover_refs but for the receive-pack service."""
```

## upload-pack negotiation (fetch/clone)

After ref discovery, the client sends a `POST` to `<url>/git-upload-pack`:

- Content-Type: `application/x-git-upload-pack-request`
- Body: a sequence of `want <sha40>\n` pkt-lines (one per object the client wants),
  then optionally `have <sha40>\n` lines (objects the client already has, to minimise transfer),
  then a flush packet, then a `done\n` pkt-line.

The server streams back a packfile prefixed by `NAK\n` (if no common base was found) or
`ACK <sha40>\n` lines, then the raw pack data.

```python
def fetch_pack(url: str, wants: list[str], haves: list[str] = ()) -> bytes:
    """
    Perform a upload-pack negotiation. Returns the raw .pack bytes
    received from the server. Raises ProtocolError on protocol errors.
    """
```

## receive-pack negotiation (push)

After ref discovery, the client sends a `POST` to `<url>/git-receive-pack`:

- Content-Type: `application/x-git-receive-pack-request`
- Body: one pkt-line per ref to update:
  `<old-sha> <new-sha> <refname>\n`
  (for a new ref, `old-sha` is forty `0`s; for a deletion, `new-sha` is forty `0`s),
  then a flush packet, then the raw packfile bytes.

The server responds with a sequence of `ok <refname>\n` / `ng <refname> <reason>\n` lines,
followed by a flush packet.

```python
def send_pack(url: str, ref_updates: list[tuple[str, str, str]], pack_data: bytes) -> dict[str, str | None]:
    """
    Perform a receive-pack push. ref_updates is a list of
    (old_sha, new_sha, refname) tuples. pack_data is the raw pack bytes.
    Returns {refname: None if ok, reason_str if rejected}.
    Raises ProtocolError on HTTP or protocol errors.
    """
```

## Error handling

- A new exception `ProtocolError(Exception)` is raised for any protocol violation: wrong
  `Content-Type`, unexpected HTTP status code, malformed pkt-line length, truncated stream.
- Network errors from `urllib` (`URLError`, `HTTPError`) are allowed to propagate unwrapped —
  callers can catch them if they need to.
- A server that responds with HTTP 401 raises `ProtocolError` with a clear message — credential
  handling is explicitly out of scope.

## Public interface summary

```python
# pygit/http.py

class ProtocolError(Exception): ...

def pkt_line(data: bytes) -> bytes: ...
def pkt_flush() -> bytes: ...
def read_pkt_lines(stream) -> list[bytes | None]: ...

def discover_refs(url: str) -> tuple[dict[str, str], set[str]]: ...
def discover_refs_receive(url: str) -> tuple[dict[str, str], set[str]]: ...
def fetch_pack(url: str, wants: list[str], haves: list[str] = ()) -> bytes: ...
def send_pack(url: str, ref_updates: list[tuple[str, str, str]], pack_data: bytes) -> dict[str, str | None]: ...
```

All functions use `urllib.request` from the stdlib — no third-party HTTP library is needed.

## Testing strategy

### Unit tests (no network required)

All protocol logic is testable with hand-built byte strings:

- `pkt_line`: assert that `pkt_line(b"hello\n")` equals `b"000bhello\n"` (length = 4 + 6 = 10 =
  `000a`... wait: `hello\n` is 6 bytes, total = 10 = `000a`). Test empty payload, max-length
  payload, multi-line sequences.
- `pkt_flush`: assert returns exactly `b"0000"`.
- `read_pkt_lines`: feed a `io.BytesIO` with a hand-built sequence of pkt-lines including a flush
  in the middle; assert the returned list is correct with `None` at the flush position. Test
  truncated input (raises `ProtocolError`), bad hex (raises `ProtocolError`).
- `discover_refs`: mock the HTTP response using `unittest.mock.patch` on `urllib.request.urlopen`
  to return a hand-built advertisement body; assert the returned dict and capability set are
  correct.
- `fetch_pack`: mock `urlopen`; feed it a hand-built response body beginning with `NAK\n` then
  a minimal valid pack (the 12-byte empty pack: `PACK\x00\x00\x00\x02\x00\x00\x00\x00` + SHA-1
  of those 12 bytes); assert the returned bytes equal the pack portion.
- `send_pack`: mock `urlopen` to return a hand-built `ok refs/heads/main\n` response; assert the
  returned dict is `{"refs/heads/main": None}`.

### Interop tests (skipped if network unavailable or no real git on PATH)

- Use `git daemon --base-path=. --export-all --enable=receive-pack` launched as a background
  subprocess (or test against `file://` protocol if `git upload-pack` supports that path) to
  avoid any dependency on internet connectivity.
- Alternatively, use `git http-backend` with a local WSGI/CGI server (more complex but more
  realistic). Given the complexity, these tests are `pytest.mark.skip` by default and only
  enabled with `--run-network-tests` flag, keeping CI fast.
- The primary interop validation bar is that `git clone` of a pack produced by `fetch_pack` gives
  the correct objects (tested in sub-project 3 once `clone` exists).

## Documentation

`README.md` gains a short "Wire protocol" section after "Reading packed objects", describing the
pkt-line format and the Smart HTTP flow at the same high level as the existing sections.
Note that `clone`/`fetch`/`push` commands are not yet exposed (those are sub-projects 3 and 4).
The "Known limitations" list gains:
> Smart HTTP protocol primitives (`http.py`) are implemented, but `clone`, `fetch`, and `push`
> commands are not yet wired up — that is sub-projects 3 and 4.
