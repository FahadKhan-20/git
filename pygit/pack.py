import hashlib
import os
import struct
import zlib
from pygit.repository import repo_path

OBJ_COMMIT = 1
OBJ_TREE = 2
OBJ_BLOB = 3
OBJ_TAG = 4
OBJ_OFS_DELTA = 6
OBJ_REF_DELTA = 7

TYPE_NAMES = {
    OBJ_COMMIT: "commit",
    OBJ_TREE: "tree",
    OBJ_BLOB: "blob",
    OBJ_TAG: "tag",
}


class InvalidPackError(Exception):
    pass


def parse_object_header(data, offset):
    byte = data[offset]
    type_id = (byte >> 4) & 0x7
    size = byte & 0x0F
    shift = 4
    offset += 1
    while byte & 0x80:
        byte = data[offset]
        size |= (byte & 0x7F) << shift
        shift += 7
        offset += 1
    return type_id, size, offset


def parse_ofs_delta_offset(data, offset):
    byte = data[offset]
    value = byte & 0x7F
    offset += 1
    while byte & 0x80:
        byte = data[offset]
        value = ((value + 1) << 7) | (byte & 0x7F)
        offset += 1
    return value, offset


def _read_delta_varint(data, offset):
    value = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not (byte & 0x80):
            break
    return value, offset


def apply_delta(base, delta):
    base_size, offset = _read_delta_varint(delta, 0)
    result_size, offset = _read_delta_varint(delta, offset)
    if base_size != len(base):
        raise InvalidPackError("delta base size does not match actual base length")
    output = bytearray()
    n = len(delta)
    while offset < n:
        instruction = delta[offset]
        offset += 1
        if instruction & 0x80:
            copy_offset = 0
            copy_size = 0
            for bit in range(4):
                if instruction & (1 << bit):
                    copy_offset |= delta[offset] << (8 * bit)
                    offset += 1
            for bit in range(3):
                if instruction & (1 << (4 + bit)):
                    copy_size |= delta[offset] << (8 * bit)
                    offset += 1
            if copy_size == 0:
                copy_size = 0x10000
            output += base[copy_offset:copy_offset + copy_size]
        elif instruction != 0:
            output += delta[offset:offset + instruction]
            offset += instruction
        else:
            raise InvalidPackError("delta instruction byte 0 is reserved/invalid")
    if len(output) != result_size:
        raise InvalidPackError("delta result size does not match reconstructed length")
    return bytes(output)


IDX_MAGIC = b"\xff\x74\x4f\x63"


def list_pack_files(repo):
    pack_dir = repo_path(repo, "objects", "pack")
    if not os.path.isdir(pack_dir):
        return []
    names = set()
    for name in os.listdir(pack_dir):
        if name.endswith(".idx"):
            names.add(name[:-len(".idx")])
    return sorted(names)


def read_pack_index(idx_path):
    with open(idx_path, "rb") as f:
        data = f.read()
    magic, version = struct.unpack(">4sI", data[:8])
    if magic != IDX_MAGIC or version != 2:
        raise InvalidPackError(f"unsupported pack index format: {idx_path}")
    fanout = struct.unpack(">256I", data[8:8 + 256 * 4])
    count = fanout[255]
    shas_start = 8 + 256 * 4
    shas_end = shas_start + count * 20
    offsets_start = shas_end + count * 4
    result = {}
    for i in range(count):
        sha = data[shas_start + i * 20: shas_start + i * 20 + 20].hex()
        offset = struct.unpack(">I", data[offsets_start + i * 4: offsets_start + i * 4 + 4])[0]
        if offset & 0x80000000:
            raise InvalidPackError("64-bit pack offsets are not supported")
        result[sha] = offset
    return result


_TYPE_ID_BY_NAME = {"commit": OBJ_COMMIT, "tree": OBJ_TREE, "blob": OBJ_BLOB, "tag": OBJ_TAG}


def _decompress_at(data, offset):
    decompressor = zlib.decompressobj()
    remaining = data[offset:]
    content = decompressor.decompress(remaining)
    content += decompressor.flush()
    consumed = len(remaining) - len(decompressor.unused_data)
    return content, offset + consumed


def _resolve_at_offset(repo, pack_data, sha_to_offset, offset, memo):
    if offset in memo:
        return memo[offset]
    type_id, size, header_end = parse_object_header(pack_data, offset)
    if type_id in (OBJ_COMMIT, OBJ_TREE, OBJ_BLOB, OBJ_TAG):
        content, _ = _decompress_at(pack_data, header_end)
        if len(content) != size:
            raise InvalidPackError(f"object at offset {offset} has wrong size")
        result = (type_id, content)
    elif type_id == OBJ_OFS_DELTA:
        rel_offset, delta_start = parse_ofs_delta_offset(pack_data, header_end)
        base_type, base_content = _resolve_at_offset(repo, pack_data, sha_to_offset, offset - rel_offset, memo)
        delta_content, _ = _decompress_at(pack_data, delta_start)
        if len(delta_content) != size:
            raise InvalidPackError(f"delta at offset {offset} has wrong size")
        result = (base_type, apply_delta(base_content, delta_content))
    elif type_id == OBJ_REF_DELTA:
        base_sha = pack_data[header_end:header_end + 20].hex()
        delta_start = header_end + 20
        if base_sha in sha_to_offset:
            base_type, base_content = _resolve_at_offset(repo, pack_data, sha_to_offset, sha_to_offset[base_sha], memo)
        else:
            from pygit.objects import read_object
            base_type_name, base_content = read_object(repo, base_sha)
            base_type = _TYPE_ID_BY_NAME[base_type_name]
        delta_content, _ = _decompress_at(pack_data, delta_start)
        if len(delta_content) != size:
            raise InvalidPackError(f"delta at offset {offset} has wrong size")
        result = (base_type, apply_delta(base_content, delta_content))
    else:
        raise InvalidPackError(f"unsupported pack object type {type_id} at offset {offset}")
    memo[offset] = result
    return result


def read_object_from_packs(repo, sha):
    for basename in list_pack_files(repo):
        idx_path = repo_path(repo, "objects", "pack", basename + ".idx")
        sha_to_offset = read_pack_index(idx_path)
        if sha in sha_to_offset:
            pack_path = repo_path(repo, "objects", "pack", basename + ".pack")
            with open(pack_path, "rb") as f:
                pack_data = f.read()
            type_id, content = _resolve_at_offset(repo, pack_data, sha_to_offset, sha_to_offset[sha], {})
            return TYPE_NAMES[type_id], content

def encode_object_header(type_id, size):
    first = (type_id << 4) | (size & 0x0F)
    size >>= 4
    if size == 0:
        return bytes([first])
    result = bytes([first | 0x80])
    while size:
        chunk = size & 0x7F
        size >>= 7
        result += bytes([chunk | (0x80 if size else 0)])
    return result


def _write_idx(shas_sorted, offsets, entries, pack_sha_bytes, idx_path):
    fanout = [0] * 256
    for sha in shas_sorted:
        first_byte = int(sha[:2], 16)
        for b in range(first_byte, 256):
            fanout[b] += 1
    body = bytearray()
    body += b"\xff\x74\x4f\x63"
    body += struct.pack(">I", 2)
    for count in fanout:
        body += struct.pack(">I", count)
    for sha in shas_sorted:
        body += bytes.fromhex(sha)
    sha_to_entry = {sha: (hdr, comp) for sha, hdr, comp in entries}
    for sha in shas_sorted:
        hdr, compressed = sha_to_entry[sha]
        body += struct.pack(">I", zlib.crc32(hdr + compressed) & 0xFFFFFFFF)
    for sha in shas_sorted:
        body += struct.pack(">I", offsets[sha])
    body += pack_sha_bytes
    body += hashlib.sha1(body).digest()
    with open(idx_path, "wb") as f:
        f.write(body)


def write_pack(repo, shas, pack_path, idx_path):
    from pygit.objects import read_object
    shas_sorted = sorted(set(shas))
    entries = []
    for sha in shas_sorted:
        type_name, content = read_object(repo, sha)
        type_id = _TYPE_ID_BY_NAME[type_name]
        header = encode_object_header(type_id, len(content))
        compressed = zlib.compress(content)
        entries.append((sha, header, compressed))
    body = bytearray()
    body += b"PACK"
    body += struct.pack(">II", 2, len(entries))
    offsets = {}
    for sha, header, compressed in entries:
        offsets[sha] = len(body)
        body += header
        body += compressed
    pack_sha = hashlib.sha1(body).digest()
    body += pack_sha
    with open(pack_path, "wb") as f:
        f.write(body)
    _write_idx(shas_sorted, offsets, entries, pack_sha, idx_path)
    return pack_sha.hex()


def index_pack(pack_path, idx_path):
    with open(pack_path, "rb") as f:
        pack_data = f.read()
    magic, version, count = struct.unpack(">4sII", pack_data[:12])
    if magic != b"PACK" or version != 2:
        raise InvalidPackError(f"unsupported pack file: {pack_path}")
    pack_sha_bytes = pack_data[-20:]
    shas_sorted = []
    offsets = {}
    entries = []
    cursor = 12
    for _ in range(count):
        entry_offset = cursor
        type_id, size, header_end = parse_object_header(pack_data, cursor)
        if type_id in (OBJ_OFS_DELTA, OBJ_REF_DELTA):
            raise InvalidPackError("index_pack does not support delta entries")
        decomp = zlib.decompressobj()
        remaining = pack_data[header_end:]
        full_content = decomp.decompress(remaining)
        full_content += decomp.flush()
        consumed = len(remaining) - len(decomp.unused_data)
        compressed = pack_data[header_end: header_end + consumed]
        cursor = header_end + consumed
        type_name = TYPE_NAMES[type_id]
        hdr = f"{type_name} {len(full_content)}\0".encode()
        sha = hashlib.sha1(hdr + full_content).hexdigest()
        shas_sorted.append(sha)
        offsets[sha] = entry_offset
        header_bytes = encode_object_header(type_id, size)
        entries.append((sha, header_bytes, compressed))
    shas_sorted.sort()
    _write_idx(shas_sorted, offsets, entries, pack_sha_bytes, idx_path)
