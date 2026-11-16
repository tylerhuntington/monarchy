"""Pinned, self-contained skill archives. This module never installs or runs skills.

Paths are opened beneath explicit roots with no symlink traversal. Archives carry
read-only file modes; consumers must still treat their contents as instructions,
not executable code or grants of authority. Hashes establish integrity, not trust.
"""

from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
import uuid
import zipfile
import zlib


REGISTRY_PATH = ".agents/skills/registry.json"
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_ARCHIVE_BYTES = 20 * 1024 * 1024
MAX_FILES = 256
_NAME = re.compile(r"monarchy-[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_VERSION = re.compile(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\Z")
_HASH = re.compile(r"[a-f0-9]{64}\Z")


class InvalidPackage(ValueError):
    """A source, pin, destination or archive violates the package contract."""


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise InvalidPackage("Duplicate JSON key: " + key)
        value[key] = item
    return value


def _json(data):
    try:
        return json.loads(data, object_pairs_hook=_unique_object)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise InvalidPackage("Invalid package JSON") from error


def _keys(value, required):
    if not isinstance(value, dict) or set(value) != set(required):
        raise InvalidPackage("Unexpected object fields; expected " + ", ".join(sorted(required)))


def _hash(value):
    if not isinstance(value, str) or not _HASH.fullmatch(value):
        raise InvalidPackage("Expected a full lowercase SHA-256 digest")
    return value


def _path(value):
    if not isinstance(value, str) or not value or len(value) > 512:
        raise InvalidPackage("Expected a bounded relative path")
    if any(ord(char) < 32 or ord(char) == 127 or char in '\\:*?<>|"' for char in value):
        raise InvalidPackage("Unsafe path: " + value)
    parts = value.split("/")
    if any(part in ("", ".", "..") or part.endswith((" ", ".")) for part in parts):
        raise InvalidPackage("Unsafe path: " + value)
    # These names alias devices on Windows, even when the producer is Unix.
    reserved = {"con", "prn", "aux", "nul"} | {f"{prefix}{n}" for prefix in ("com", "lpt") for n in range(1, 10)}
    if any(part.split(".")[0].casefold() in reserved for part in parts):
        raise InvalidPackage("Reserved path: " + value)
    return value


def _paths(values):
    seen = set()
    for value in values:
        folded = unicodedata.normalize("NFC", _path(value)).casefold()
        if folded in seen:
            raise InvalidPackage("Duplicate or case-colliding path: " + value)
        seen.add(folded)
    for value in seen:
        parts = value.split("/")
        if any("/".join(parts[:index]) in seen for index in range(1, len(parts))):
            raise InvalidPackage("File and directory path collision")


@contextmanager
def _directory(path):
    """Open every directory component without following links, including the root."""
    absolute = Path(os.path.abspath(os.fspath(path)))
    descriptor = None
    try:
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        descriptor = os.open(absolute.anchor, flags)
        for part in absolute.parts[1:]:
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        yield descriptor
    except OSError as error:
        raise InvalidPackage("Cannot open directory without following links: " + str(path)) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _read(root_descriptor, relative, limit=MAX_FILE_BYTES):
    parts = _path(relative).split("/")
    directory = os.dup(root_descriptor)
    descriptor = None
    try:
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        descriptor = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            raise InvalidPackage("Expected one bounded regular file: " + relative)
        chunks = []
        size = 0
        while size <= limit:
            chunk = os.read(descriptor, min(65536, limit + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
        after = os.fstat(descriptor)
        stamp = lambda item: (item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if size > limit or size != before.st_size or stamp(before) != stamp(after):
            raise InvalidPackage("File changed during read or exceeds size limit: " + relative)
        return b"".join(chunks)
    except OSError as error:
        raise InvalidPackage("Cannot safely read file: " + relative) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(directory)


def _validate_registry(value):
    _keys(value, {"schema_version", "package_version", "skills"})
    if type(value["schema_version"]) is not int or value["schema_version"] != 1:
        raise InvalidPackage("Unsupported registry schema version")
    if not isinstance(value["package_version"], str) or not _VERSION.fullmatch(value["package_version"]):
        raise InvalidPackage("Invalid package version")
    if not isinstance(value["skills"], list) or not 1 <= len(value["skills"]) <= 64:
        raise InvalidPackage("Expected a bounded, nonempty skill registry")
    names, paths = set(), []
    for entry in value["skills"]:
        _keys(entry, {"name", "version", "entrypoint", "files"})
        name = entry["name"]
        if not isinstance(name, str) or not _NAME.fullmatch(name) or name in names:
            raise InvalidPackage("Invalid or duplicate skill name")
        names.add(name)
        if not isinstance(entry["version"], str) or not _VERSION.fullmatch(entry["version"]):
            raise InvalidPackage("Invalid skill version")
        prefix = f".agents/skills/{name}/"
        if entry["entrypoint"] != prefix + "SKILL.md":
            raise InvalidPackage("Skill entrypoint must be its own SKILL.md")
        if not isinstance(entry["files"], list) or not 1 <= len(entry["files"]) <= MAX_FILES:
            raise InvalidPackage("Expected a bounded, nonempty file declaration")
        own_paths = []
        for item in entry["files"]:
            _keys(item, {"path", "sha256"})
            path = _path(item["path"])
            if not path.startswith(prefix):
                raise InvalidPackage("Resource must stay within its declared skill")
            _hash(item["sha256"])
            own_paths.append(path)
        if entry["entrypoint"] not in own_paths:
            raise InvalidPackage("Entrypoint missing from pinned files")
        paths.extend(own_paths)
    _paths(paths)
    if len(paths) > MAX_FILES - 2:
        raise InvalidPackage("Registry declares too many files")
    return value


def load_registry(root):
    """Read and validate registry structure without loading or executing skills."""
    with _directory(root) as descriptor:
        return _validate_registry(_json(_read(descriptor, REGISTRY_PATH)))


def _write_archive(destination, data):
    path = Path(destination)
    _path(path.name)
    with _directory(path.parent) as directory:
        temporary = ".monarchy-package-" + uuid.uuid4().hex
        descriptor = None
        created = False
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory)
            created = True
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = None
                stream.write(data)
                stream.flush()
                os.fchmod(stream.fileno(), 0o444)
                os.fsync(stream.fileno())
            # Link publishes the complete archive atomically and refuses an existing name.
            os.link(temporary, path.name, src_dir_fd=directory, dst_dir_fd=directory,
                    follow_symlinks=False)
            os.fsync(directory)
        except OSError as error:
            raise InvalidPackage("Cannot publish archive; destination must be new: " + str(destination)) from error
        finally:
            if descriptor is not None:
                os.close(descriptor)
            if created:
                os.unlink(temporary, dir_fd=directory)


def build_package(root, skill_names, destination, *, expected_hashes=None,
                  context_root=None, context_files=None):
    """Build an explicit read-only ZIP and return its manifest; never overwrite.

    ``expected_hashes`` optionally pins the registry and/or selected source files
    by root-relative path. ``context_files`` maps explicit project-relative paths
    to required SHA-256 hashes and must accompany ``context_root``. No directory
    is copied recursively. The caller chooses the policy files and checks that
    they are appropriate for the worker; the builder cannot establish authority.
    """
    if not isinstance(skill_names, (list, tuple)) or not skill_names:
        raise InvalidPackage("Select at least one skill")
    if any(not isinstance(name, str) for name in skill_names) or len(set(skill_names)) != len(skill_names):
        raise InvalidPackage("Skill selection must be unique names")
    if (context_root is None) != (context_files is None):
        raise InvalidPackage("Provide context_root and context_files together")
    if expected_hashes is None:
        expected_hashes = {}
    if not isinstance(expected_hashes, dict):
        raise InvalidPackage("expected_hashes must map paths to digests")
    for path, pin in expected_hashes.items():
        _path(path)
        _hash(pin)
    payload, source_hashes, selected = {}, {}, []
    with _directory(root) as directory:
        registry_bytes = _read(directory, REGISTRY_PATH)
        registry = _validate_registry(_json(registry_bytes))
        available = {entry["name"]: entry for entry in registry["skills"]}
        if any(name not in available for name in skill_names):
            raise InvalidPackage("Selected skill is not in the registry")
        payload["registry.json"] = registry_bytes
        source_hashes[REGISTRY_PATH] = _sha(registry_bytes)
        for name in sorted(skill_names):
            entry = available[name]
            package_files = []
            for item in sorted(entry["files"], key=lambda item: item["path"]):
                raw = _read(directory, item["path"])
                source_hashes[item["path"]] = _sha(raw)
                if source_hashes[item["path"]] != item["sha256"]:
                    raise InvalidPackage("Source no longer matches registry pin: " + item["path"])
                archive_path = item["path"].removeprefix(".agents/")
                payload[archive_path] = raw
                package_files.append(archive_path)
            selected.append({"name": name, "version": entry["version"],
                             "entrypoint": entry["entrypoint"].removeprefix(".agents/"),
                             "files": package_files})
    if any(path not in source_hashes or source_hashes[path] != pin for path, pin in expected_hashes.items()):
        raise InvalidPackage("A caller pin is missing or does not match the selected source")
    project_paths = []
    if context_files is not None:
        if not isinstance(context_files, dict) or not context_files:
            raise InvalidPackage("Select explicit, nonempty project context files")
        _paths(context_files)
        with _directory(context_root) as directory:
            for path, pin in sorted(context_files.items()):
                raw = _read(directory, path)
                if _sha(raw) != _hash(pin):
                    raise InvalidPackage("Project context no longer matches pin: " + path)
                archive_path = "project/" + path
                payload[archive_path] = raw
                project_paths.append(archive_path)
    _paths(payload)
    if len(payload) + 1 > MAX_FILES or sum(map(len, payload.values())) > MAX_TOTAL_BYTES:
        raise InvalidPackage("Package exceeds limits")
    manifest = {"schema_version": 1, "package_version": registry["package_version"],
                "registry_sha256": _sha(registry_bytes), "skills": selected,
                "project_context": project_paths,
                "files": [{"path": path, "sha256": _sha(raw), "size": len(raw)}
                          for path, raw in sorted(payload.items())]}
    payload["manifest.json"] = _json_bytes(manifest)
    if (len(payload["manifest.json"]) > MAX_FILE_BYTES
            or sum(map(len, payload.values())) > MAX_TOTAL_BYTES):
        raise InvalidPackage("Package including manifest exceeds limits")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
        for path, raw in sorted(payload.items()):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | 0o444) << 16
            archive.writestr(info, raw)
    data = buffer.getvalue()
    if len(data) > MAX_ARCHIVE_BYTES:
        raise InvalidPackage("Archive exceeds size limit")
    _write_archive(destination, data)
    return manifest


def inspect_package(archive, *, expected_sha256=None):
    """Verify an archive without extracting it, optionally against a trusted pin.

    A self-consistent archive is not necessarily trusted. Supply the SHA-256 from
    the task brief to bind it to the package selected by the dispatcher.
    """
    path = Path(archive)
    with _directory(path.parent) as directory:
        raw = _read(directory, path.name, MAX_ARCHIVE_BYTES)
    if expected_sha256 is not None and _sha(raw) != _hash(expected_sha256):
        raise InvalidPackage("Archive does not match the expected SHA-256")
    payload = {}
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as source:
            items = source.infolist()
            if not 2 <= len(items) <= MAX_FILES:
                raise InvalidPackage("Archive file count exceeds limits")
            _paths(item.filename for item in items)
            if sum(item.file_size for item in items) > MAX_TOTAL_BYTES:
                raise InvalidPackage("Archive expanded size exceeds limit")
            for item in items:
                mode = item.external_attr >> 16
                if (item.create_system != 3 or not stat.S_ISREG(mode) or stat.S_IMODE(mode) != 0o444
                        or item.file_size > MAX_FILE_BYTES or item.flag_bits & 1
                        or item.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                    raise InvalidPackage("Archive member is not a bounded, read-only regular file")
                payload[item.filename] = source.read(item)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, OSError, EOFError, zlib.error) as error:
        raise InvalidPackage("Invalid archive") from error
    if "manifest.json" not in payload or "registry.json" not in payload:
        raise InvalidPackage("Archive is missing its manifest or registry")
    manifest = _json(payload.pop("manifest.json"))
    _keys(manifest, {"schema_version", "package_version", "registry_sha256", "skills", "project_context", "files"})
    if type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1:
        raise InvalidPackage("Unsupported package schema version")
    if not isinstance(manifest["files"], list) or len(manifest["files"]) != len(payload):
        raise InvalidPackage("Manifest file list is incomplete")
    declared = []
    for item in manifest["files"]:
        _keys(item, {"path", "sha256", "size"})
        name = _path(item["path"])
        if (name not in payload or _sha(payload[name]) != _hash(item["sha256"])
                or type(item["size"]) is not int or len(payload[name]) != item["size"]):
            raise InvalidPackage("Archive file failed its manifest pin")
        declared.append(name)
    _paths(declared)
    registry = _validate_registry(_json(payload["registry.json"]))
    if (manifest["registry_sha256"] != _sha(payload["registry.json"])
            or manifest["package_version"] != registry["package_version"]):
        raise InvalidPackage("Archive registry pin or version mismatch")
    available = {entry["name"]: entry for entry in registry["skills"]}
    if not isinstance(manifest["skills"], list) or not manifest["skills"]:
        raise InvalidPackage("Archive must select at least one skill")
    expected_paths, names = {"registry.json"}, set()
    for entry in manifest["skills"]:
        _keys(entry, {"name", "version", "entrypoint", "files"})
        name = entry["name"]
        if not isinstance(name, str) or name not in available or name in names:
            raise InvalidPackage("Invalid archive skill selection")
        names.add(name)
        original = available[name]
        mapped_files = {item["path"].removeprefix(".agents/"): item["sha256"] for item in original["files"]}
        if (entry["version"] != original["version"]
                or entry["entrypoint"] != original["entrypoint"].removeprefix(".agents/")
                or not isinstance(entry["files"], list) or entry["files"] != sorted(mapped_files)):
            raise InvalidPackage("Archive selection differs from pinned registry")
        for file, pin in mapped_files.items():
            if file not in payload or _sha(payload[file]) != pin:
                raise InvalidPackage("Skill content differs from pinned registry")
        expected_paths.update(mapped_files)
    if not isinstance(manifest["project_context"], list):
        raise InvalidPackage("Invalid project context list")
    _paths(manifest["project_context"])
    for file in manifest["project_context"]:
        if not file.startswith("project/"):
            raise InvalidPackage("Project context must stay in its own archive directory")
    expected_paths.update(manifest["project_context"])
    if expected_paths != set(payload):
        raise InvalidPackage("Archive contains missing or undeclared resources")
    return manifest
