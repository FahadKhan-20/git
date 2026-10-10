import os
import struct
import zlib

from pygit.http import discover_refs, fetch_pack
from pygit.objects import hash_object, read_object
from pygit.pack import (
    InvalidPackError,
    _decompress_at,
    _TYPE_ID_BY_NAME,
    TYPE_NAMES,
    parse_object_header,
    index_pack,
    OBJ_OFS_DELTA,
    OBJ_REF_DELTA,
)
from pygit.refs import write_ref
from pygit.remote import get_remote_url
from pygit.repository import repo_path

_UNPACK_LIMIT = 20


def _has_object(repo, sha):
    try:
        read_object(repo, sha)
        return True
    except Exception:
        return False


def _unpack_pack(repo, pack_data):
    magic, version, count = struct.unpack(">4sII", pack_data[:12])
    if magic != b"PACK" or version != 2:
        raise InvalidPackError("invalid pack header from server")
    cursor = 12
    for _ in range(count):
        entry_offset = cursor
        type_id, size, header_end = parse_object_header(pack_data, cursor)
        if type_id in (OBJ_OFS_DELTA, OBJ_REF_DELTA):
            cursor = header_end
            decomp = zlib.decompressobj()
            remaining = pack_data[cursor:]
            decomp.decompress(remaining)
            decomp.flush()
            consumed = len(remaining) - len(decomp.unused_data)
            cursor += consumed
            continue
        content, next_offset = _decompress_at(pack_data, header_end)
        cursor = next_offset
        type_name = TYPE_NAMES[type_id]
        hash_object(repo, content, type_name, write=True)


def _store_pack(repo, pack_data):
    pack_dir = repo_path(repo, "objects", "pack")
    os.makedirs(pack_dir, exist_ok=True)
    tmp_pack = os.path.join(pack_dir, "_fetch_tmp.pack")
    tmp_idx = os.path.join(pack_dir, "_fetch_tmp.idx")
    with open(tmp_pack, "wb") as f:
        f.write(pack_data)
    index_pack(tmp_pack, tmp_idx)
    import hashlib
    pack_sha = pack_data[-20:].hex()
    basename = f"pack-{pack_sha}"
    import shutil
    shutil.move(tmp_pack, os.path.join(pack_dir, basename + ".pack"))
    shutil.move(tmp_idx, os.path.join(pack_dir, basename + ".idx"))


def fetch_from_remote(repo, remote_name="origin"):
    url = get_remote_url(repo, remote_name)
    remote_refs, caps = discover_refs(url)
    wants = [sha for sha in remote_refs.values() if not _has_object(repo, sha)]
    if wants:
        pack_data = fetch_pack(url, wants)
        magic, version, count = struct.unpack(">4sII", pack_data[:12])
        if count <= _UNPACK_LIMIT:
            _unpack_pack(repo, pack_data)
        else:
            _store_pack(repo, pack_data)
    updated = {}
    for refname, sha in remote_refs.items():
        if not refname.startswith("refs/heads/"):
            continue
        branch = refname[len("refs/heads/"):]
        tracking_ref = f"refs/remotes/{remote_name}/{branch}"
        write_ref(repo, tracking_ref, sha)
        updated[tracking_ref] = sha
    return updated
