"""Download helpers for install.sh. Standard library only.

    python3 -m minecraft_manager.provision java-major VERSION
    python3 -m minecraft_manager.provision java-install MAJOR TARGET_DIR
    python3 -m minecraft_manager.provision server-jar paper|fabric VERSION SERVER_DIR
    python3 -m minecraft_manager.provision addons paper|fabric VERSION LIST_FILE TARGET_DIR [--update]
"""

import hashlib
import http.client
import io
import json
from pathlib import Path
import platform
import re
import shutil
import struct
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

USER_AGENT = "pi-minecraft-server (github.com/bruno-espino/pi-minecraft-server)"
MANIFEST = ".managed-by-install.json"
BUILD_STAMP = ".server-build"
CLIENT_PACK = "client-pack.mrpack"
CLIENT_SUMMARY = "client-mods.json"
JAR_NAMES = {"paper": "paper.jar", "fabric": "fabric-server-launch.jar"}
MODRINTH_LOADERS = {"paper": ["paper", "spigot", "bukkit"], "fabric": ["fabric"]}


def fetch(url, timeout=60, attempts=3, data=None):
    """GET (or POST JSON data to) a URL, retrying dropped connections; 4xx/5xx are not retried."""
    headers = {"User-Agent": USER_AGENT}
    if data is not None:
        data, headers["Content-Type"] = json.dumps(data).encode(), "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError:
            raise
        except (urllib.error.URLError, http.client.HTTPException, OSError) as error:
            if attempt == attempts:
                raise SystemExit(f"download failed after {attempts} attempts: {url} ({error})") from error
            time.sleep(2 * attempt)


def fetch_json(url, data=None):
    return json.loads(fetch(url, data=data))


def write_verified(data, target, sha256=None, sha512=None):
    """Write bytes atomically after checking any checksum provided."""
    for algorithm, expected in (("sha256", sha256), ("sha512", sha512)):
        if expected and hashlib.new(algorithm, data).hexdigest() != expected:
            raise SystemExit(f"checksum mismatch for {target.name}")
    partial = target.with_name(target.name + ".part")
    partial.write_bytes(data)
    partial.replace(target)


# --- Java -------------------------------------------------------------------

def java_major(version):
    manifest = fetch_json("https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")
    entry = next((v for v in manifest["versions"] if v["id"] == version), None)
    if not entry:
        raise SystemExit(f"Minecraft {version} is not a known release")
    return fetch_json(entry["url"])["javaVersion"]["majorVersion"]


JAVA_ARCHES = {"aarch64": "aarch64", "arm64": "aarch64", "x86_64": "x64", "amd64": "x64"}


def java_arch(machine=None, pointer_bits=None):
    """Adoptium's name for this machine, or None when there is no 64-bit build.

    A 32-bit OS on a 64-bit Pi still reports aarch64 (the kernel is 64-bit),
    so the size of a pointer in this Python decides.
    """
    machine = (machine or platform.machine()).lower()
    pointer_bits = pointer_bits or struct.calcsize("P") * 8
    return JAVA_ARCHES.get(machine) if pointer_bits == 64 else None


def extract_tar(data, target):
    """Unpack a .tar.gz into TARGET, refusing members that would land outside it."""
    target = Path(target)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        members = archive.getmembers()
        for member in members:
            path = (target / member.name).resolve()
            if not path.is_relative_to(target.resolve()) or not (
                member.isfile() or member.isdir() or member.issym()
            ):
                raise SystemExit(f"unsafe entry in the Java archive: {member.name}")
            if member.issym():
                link = (path.parent / member.linkname).resolve()
                if not link.is_relative_to(target.resolve()):
                    raise SystemExit(f"unsafe link in the Java archive: {member.name}")
        if hasattr(tarfile, "data_filter"):  # Python 3.12+, and needed from 3.14
            archive.extractall(target, members=members, filter="data")
        else:
            archive.extractall(target, members=members)


def java_install(major, target_dir, lookup=fetch_json, download=fetch):
    """Install the newest Eclipse Temurin JRE MAJOR under TARGET_DIR and print its java.

    Each release gets its own directory; older ones are removed unless a
    running process still uses them (the server picks up the new one on restart).
    """
    arch = java_arch()
    if not arch:
        raise SystemExit(
            f"there is no Java {major} download for this system ({platform.machine()}, "
            f"{struct.calcsize('P') * 8}-bit); Minecraft needs a 64-bit OS such as 64-bit Raspberry Pi OS"
        )
    assets = lookup(
        f"https://api.adoptium.net/v3/assets/latest/{int(major)}/hotspot"
        f"?architecture={arch}&image_type=jre&os=linux&vendor=eclipse"
    )
    if not assets:
        raise SystemExit(f"Adoptium has no Java {major} for {arch}")
    release, package = assets[0]["release_name"], assets[0]["binary"]["package"]
    target = Path(target_dir)
    home = target / f"{release}-jre"
    java = home / "bin" / "java"
    if not java.is_file():
        print(f"Downloading Java {release} ({package['size'] // 1_000_000} MB)...", file=sys.stderr)
        data = download(package["link"], timeout=600)
        if hashlib.sha256(data).hexdigest() != package["checksum"]:
            raise SystemExit(f"checksum mismatch for {package['name']}")
        target.mkdir(parents=True, exist_ok=True)
        staging = target / f".{release}.part"
        shutil.rmtree(staging, ignore_errors=True)
        staging.mkdir()
        extract_tar(data, staging)
        top = [entry for entry in staging.iterdir() if (entry / "bin" / "java").is_file()]
        if len(top) != 1:
            raise SystemExit(f"unexpected layout in {package['name']}")
        top[0].replace(home)
        shutil.rmtree(staging)
    busy = running_executables()
    for old in target.glob("*-jre"):
        if old != home and not any(exe.is_relative_to(old) for exe in busy):
            shutil.rmtree(old)
            print(f"Removed the older Java {old.name.removesuffix('-jre')}", file=sys.stderr)
    print(java)


def running_executables():
    """Executables of the processes this user can see."""
    paths = []
    for exe in Path("/proc").glob("[0-9]*/exe"):
        try:
            paths.append(exe.resolve(strict=True))
        except OSError:
            pass
    return paths


# --- Server jar -------------------------------------------------------------

def paper_build(version):
    builds = fetch_json(f"https://fill.papermc.io/v3/projects/paper/versions/{version}/builds")
    stable = next((b for b in builds if b.get("channel") == "STABLE"), None)
    if not stable:
        raise SystemExit(f"Paper has no stable build for {version} yet")
    download = stable["downloads"]["server:default"]
    return f"paper {version} build {stable['id']}", download["url"], download["checksums"]["sha256"]


def fabric_build(version):
    loaders = fetch_json(f"https://meta.fabricmc.net/v2/versions/loader/{urllib.parse.quote(version)}")
    loader = next((l["loader"]["version"] for l in loaders if l["loader"]["stable"]), None)
    if not loader:
        raise SystemExit(f"Fabric does not support Minecraft {version} yet")
    installers = fetch_json("https://meta.fabricmc.net/v2/versions/installer")
    installer = next(i["version"] for i in installers if i["stable"])
    url = f"https://meta.fabricmc.net/v2/versions/loader/{version}/{loader}/{installer}/server/jar"
    return f"fabric {version} loader {loader} installer {installer}", url, None


def server_jar(server_type, version, server_dir):
    server_dir = Path(server_dir)
    label, url, sha256 = (paper_build if server_type == "paper" else fabric_build)(version)
    stamp = server_dir / BUILD_STAMP
    jar = server_dir / JAR_NAMES[server_type]
    if jar.is_file() and stamp.is_file() and stamp.read_text().strip() == label:
        print(f"Server jar is current: {label}")
        return
    write_verified(fetch(url, timeout=300), jar, sha256=sha256)
    stamp.write_text(label + "\n")
    print(f"Downloaded {label}")


# --- Mods and plugins from Modrinth -----------------------------------------

def read_list(path):
    """(project, tags) pairs, one project per line; '#' starts a comment.

    A line may add tags after the project name. `client` offers the mod to
    players as optional (for example a recipe viewer like `jei client`).
    """
    entries = []
    for line in Path(path).read_text().splitlines():
        words = line.split("#", 1)[0].split()
        if words:
            entries.append((words[0], set(words[1:])))
    return entries


def modrinth_version(project, server_type, version):
    """Newest release (else newest pre-release) of a project for this server."""
    query = urllib.parse.urlencode({
        "loaders": json.dumps(MODRINTH_LOADERS[server_type]),
        "game_versions": json.dumps([version]),
    })
    versions = fetch_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project)}/version?{query}")
    releases = [v for v in versions if v["version_type"] == "release"]
    return (releases or versions or [None])[0]


def read_lock(path, server_type, version):
    """Pinned Modrinth version ids by project id, if the lock is for this server and version."""
    try:
        lock = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    if lock.get("server") != server_type or lock.get("minecraft") != version:
        return {}
    return lock.get("versions", {})


def write_lock(path, resolution, server_type, version):
    """Record the exact version of every add-on, for the server and the player pack."""
    nodes = resolution["nodes"]
    versions = {
        node_id: nodes[node_id]["record"]["id"]
        for node_id in sorted(resolution["server"] | resolution["required"] | resolution["optional"])
        if nodes[node_id]["record"] and "id" in nodes[node_id]["record"]
    }
    lock = {"server": server_type, "minecraft": version, "versions": versions}
    Path(path).write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")


def installed_versions(target, server_dir, lookup_hashes=None):
    """Version ids of the managed jars and the player pack, found by hash on Modrinth.

    Seeds the first lock of an existing install, so creating it changes nothing.
    """
    target, server_dir = Path(target), Path(server_dir)
    hashes = []
    manifest = target / MANIFEST
    if manifest.is_file():
        for filename in json.loads(manifest.read_text()):
            if (target / filename).is_file():
                hashes.append(hashlib.sha512((target / filename).read_bytes()).hexdigest())
    pack = server_dir / CLIENT_PACK
    if pack.is_file():
        with zipfile.ZipFile(pack) as archive:
            index = json.loads(archive.read("modrinth.index.json"))
        hashes += [f["hashes"]["sha512"] for f in index.get("files", [])]
    if not hashes:
        return {}
    lookup_hashes = lookup_hashes or (lambda body: fetch_json("https://api.modrinth.com/v2/version_files", body))
    found = lookup_hashes({"hashes": sorted(set(hashes)), "algorithm": "sha512"})
    return {record["project_id"]: record["id"] for record in found.values()}


def pinned_lookup(pins, fetch_version=None, newest=None):
    """A resolve_addons lookup that uses the pinned version of a project when there is one."""
    fetch_version = fetch_version or (lambda i: fetch_json(f"https://api.modrinth.com/v2/version/{i}"))
    newest = newest or modrinth_version

    def lookup(project_id, server_type, version):
        if project_id in pins:
            try:
                return fetch_version(pins[project_id])
            except urllib.error.HTTPError:
                print(f"  pinned version of {project_id} is gone from Modrinth; using the newest")
        return newest(project_id, server_type, version)

    return lookup


def resolve_addons(entries, server_type, version, lookup=None, project_info=None):
    """Resolve listed projects and their required dependencies.

    entries are (project, tags) pairs from read_list. Returns a dict with
    `nodes` (project id -> info, version record, dependency ids) and id sets:
    `server` to install on the server, `required` and `optional` for players.
    `problems` block installation; `warnings` only concern player mods.
    """
    lookup = lookup or modrinth_version
    project_info = project_info or (lambda p: fetch_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(p)}"))
    nodes, ids, parents, problems, seen = {}, {}, {}, [], set()
    queue = [(name, None) for name, _ in entries]
    while queue:
        name, parent = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        try:
            info = project_info(name)
        except urllib.error.HTTPError:
            problems.append(f"{name}: not found on Modrinth")
            continue
        seen.add(info["id"])
        ids[name] = info["id"]
        if info["id"] in nodes:
            continue
        parents[info["id"]] = parent
        record = lookup(info["id"], server_type, version)
        deps = [
            d["project_id"] for d in (record or {}).get("dependencies", [])
            if d["dependency_type"] == "required" and d.get("project_id")
        ]
        nodes[info["id"]] = {"info": info, "record": record, "deps": deps}
        queue += [(dep, info["title"]) for dep in deps]

    def side(node_id, key):
        return nodes[node_id]["info"].get(key, "optional")

    def closure(roots):
        found, stack = set(), list(roots)
        while stack:
            node_id = stack.pop()
            if node_id in nodes and node_id not in found:
                found.add(node_id)
                stack += nodes[node_id]["deps"]
        return found

    roots = [(ids[name], tags) for name, tags in entries if name in ids]
    # Client-only mods listed directly are skipped on the server, but a
    # required dependency is always installed: Fabric refuses to start when a
    # declared dependency is missing, whatever Modrinth's label says.
    server = closure(i for i, _ in roots if side(i, "server_side") != "unsupported")
    # Players need what the untagged server mods need on clients. A `client`
    # tag makes a mod optional for players even when Modrinth says clients
    # require it (a minimap), unless an untagged mod depends on it.
    untagged = closure(
        i for i, tags in roots if side(i, "server_side") != "unsupported" and "client" not in tags
    )
    required = closure(i for i in untagged if side(i, "client_side") == "required")
    optional = closure(
        i for i, tags in roots if side(i, "server_side") == "unsupported" or "client" in tags
    ) - required
    required = {i for i in required if side(i, "client_side") != "unsupported"}
    optional = {i for i in optional if side(i, "client_side") != "unsupported"}

    warnings = []
    for node_id in sorted(server | required | optional):
        if nodes[node_id]["record"]:
            continue
        title = nodes[node_id]["info"]["title"]
        parent = parents.get(node_id)
        message = f"{title}: no {server_type} build for {version}" + (f" (required by {parent})" if parent else "")
        (problems if node_id in server else warnings).append(message)
    return {
        "nodes": nodes, "server": server, "required": required, "optional": optional,
        "problems": problems, "warnings": warnings,
    }


def primary_file(record):
    return next((f for f in record["files"] if f["primary"]), record["files"][0])


def client_pack(resolution, version, loader):
    """Build a Modrinth modpack index and a summary of what players need."""
    nodes, files, summary = resolution["nodes"], [], {"required": [], "optional": []}
    for group in ("required", "optional"):
        for node_id in sorted(resolution[group], key=lambda i: nodes[i]["info"]["title"].lower()):
            info, record = nodes[node_id]["info"], nodes[node_id]["record"]
            if not record:
                continue
            file = primary_file(record)
            entry = {
                "path": f"mods/{file['filename']}",
                "hashes": {"sha1": file["hashes"]["sha1"], "sha512": file["hashes"]["sha512"]},
                "downloads": [file["url"]],
                "fileSize": file["size"],
            }
            if group == "optional":
                entry["env"] = {"client": "optional", "server": "optional"}
            files.append(entry)
            summary[group].append({
                "title": info["title"],
                "url": f"https://modrinth.com/mod/{info.get('slug', node_id)}",
                "version": record["version_number"],
            })
    digest = hashlib.sha1(json.dumps(files, sort_keys=True).encode()).hexdigest()[:8]
    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": f"{version}-{digest}",
        "name": f"Minecraft {version} server mods",
        "files": files,
        "dependencies": {"minecraft": version, "fabric-loader": loader},
    }
    summary.update(minecraft=version, loader=loader, pack_version=index["versionId"])
    return index, summary


def addons(server_type, version, list_file, target_dir, *flags):
    """Install the listed add-ons. Versions stay pinned in the list's .lock file
    (mods.lock) until --update, a new Minecraft version, or a new project in the list."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    entries = read_list(list_file)
    lock = Path(list_file).with_suffix(".lock")
    pins = {} if "--update" in flags else read_lock(lock, server_type, version)
    if not pins and not lock.exists() and "--update" not in flags:
        pins = installed_versions(target, target.parent)
    action = "Updating" if "--update" in flags else "Resolving"
    print(f"{action} {len(entries)} {server_type} add-ons for {version} from {Path(list_file).name}")
    resolution = resolve_addons(entries, server_type, version, lookup=pinned_lookup(pins))
    if resolution["problems"]:
        raise SystemExit("Cannot install add-ons:\n  " + "\n  ".join(resolution["problems"]))
    for warning in resolution["warnings"]:
        print(f"  warning: {warning}; left out of the player pack")

    manifest_path = target / MANIFEST
    previous = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    managed = {}
    nodes = resolution["nodes"]
    for node_id in sorted(resolution["server"], key=lambda i: nodes[i]["info"]["title"].lower()):
        title, record = nodes[node_id]["info"]["title"], nodes[node_id]["record"]
        file = primary_file(record)
        path = target / file["filename"]
        if not (path.is_file() and hashlib.sha512(path.read_bytes()).hexdigest() == file["hashes"]["sha512"]):
            write_verified(fetch(file["url"], timeout=300), path, sha512=file["hashes"]["sha512"])
        note = "" if record["version_type"] == "release" else f" ({record['version_type']})"
        if pins and pins.get(node_id) != record.get("id"):
            note += " (new)" if node_id not in pins else " (updated)"
        print(f"  {title} {record['version_number']}{note}")
        managed[file["filename"]] = {"title": title, "version": record["version_number"]}

    for filename in set(previous) - set(managed):
        (target / filename).unlink(missing_ok=True)
        print(f"  removed {filename}")
    manifest_path.write_text(json.dumps(managed, indent=2, sort_keys=True) + "\n")
    unmanaged = sorted(p.name for p in target.glob("*.jar") if p.name not in managed)
    if unmanaged:
        print("  Also present, not managed by install.sh: " + ", ".join(unmanaged))
    players_only = (resolution["required"] | resolution["optional"]) - resolution["server"]
    for node_id in sorted(players_only, key=lambda i: nodes[i]["info"]["title"].lower()):
        print(f"  {nodes[node_id]['info']['title']}: client-only, offered to players")
    if server_type == "fabric":
        write_client_pack(resolution, version, target.parent)
    write_lock(lock, resolution, server_type, version)


def write_client_pack(resolution, version, server_dir):
    """Write the players' modpack (server/client-pack.mrpack) and its summary."""
    stamp = server_dir / BUILD_STAMP
    match = re.search(r"loader (\S+)", stamp.read_text()) if stamp.is_file() else None
    if not match:
        print("  No Fabric loader version recorded; skipping the player pack")
        return
    index, summary = client_pack(resolution, version, match.group(1))
    partial = server_dir / (CLIENT_PACK + ".part")
    with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as pack:
        pack.writestr("modrinth.index.json", json.dumps(index, indent=2))
    partial.replace(server_dir / CLIENT_PACK)
    (server_dir / CLIENT_SUMMARY).write_text(json.dumps(summary, indent=2) + "\n")
    print(f"Player pack: {len(summary['required'])} required and {len(summary['optional'])} optional mods "
          f"in {server_dir.name}/{CLIENT_PACK}")


def main(argv):
    sys.stdout.reconfigure(line_buffering=True)
    commands = {
        "java-major": (1, lambda v: print(java_major(v))),
        "java-install": (2, java_install),
        "server-jar": (3, server_jar),
        "addons": (4, addons),
    }
    flags = [a for a in argv[1:] if a == "--update"] if argv[:1] == ["addons"] else []
    argv = [a for a in argv if a not in flags]
    if not argv or argv[0] not in commands or len(argv) - 1 != commands[argv[0]][0]:
        raise SystemExit(__doc__)
    if argv[0] not in ("java-major", "java-install") and argv[1] not in JAR_NAMES:
        raise SystemExit("server type must be paper or fabric")
    commands[argv[0]][1](*argv[1:], *flags)


if __name__ == "__main__":
    main(sys.argv[1:])
