import io
import urllib.request


class ProtocolError(Exception):
    pass


def pkt_line(data):
    length = 4 + len(data)
    return f"{length:04x}".encode() + data


def pkt_flush():
    return b"0000"


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
            continue
        payload_len = length - 4
        payload = stream.read(payload_len)
        if len(payload) < payload_len:
            raise ProtocolError(
                f"truncated pkt-line payload (expected {payload_len}, got {len(payload)})"
            )
        result.append(payload)
    return result


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
        parts = ref_part.split(" ", 1)
        if len(parts) == 2:
            sha, name = parts
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
        stream.read(length - 4)
    return stream.read()


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
