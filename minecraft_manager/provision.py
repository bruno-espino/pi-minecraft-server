"""Download helpers for install.sh. Standard library only.

    python3 -m minecraft_manager.provision java-major VERSION
    python3 -m minecraft_manager.provision server-jar paper|fabric VERSION SERVER_DIR
    python3 -m minecraft_manager.provision addons paper|fabric VERSION LIST_FILE TARGET_DIR
"""

import hashlib
import json
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "pi-minecraft-server (github.com/bruno-espino/pi-minecraft-server)"
MANIFEST = ".managed-by-install.json"
BUILD_STAMP = ".server-build"
JAR_NAMES = {"paper": "paper.jar", "fabric": "fabric-server-launch.jar"}
MODRINTH_LOADERS = {"paper": ["paper", "spigot", "bukkit"], "fabric": ["fabric"]}


def fetch(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_json(url):
    return json.loads(fetch(url))


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
    """Project slugs or IDs, one per line; '#' starts a comment."""
    projects = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            projects.append(line)
    return projects


def modrinth_version(project, server_type, version):
    """Newest release (else newest pre-release) of a project for this server."""
    query = urllib.parse.urlencode({
        "loaders": json.dumps(MODRINTH_LOADERS[server_type]),
        "game_versions": json.dumps([version]),
    })
    versions = fetch_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(project)}/version?{query}")
    releases = [v for v in versions if v["version_type"] == "release"]
    return (releases or versions or [None])[0]


def resolve_addons(projects, server_type, version, lookup=None, project_info=None):
    """Resolve listed projects plus their required dependencies.

    Returns (chosen, problems): chosen maps project id to
    (title, version record); problems lists human-readable failures.
    """
    lookup = lookup or modrinth_version
    project_info = project_info or (lambda p: fetch_json(f"https://api.modrinth.com/v2/project/{urllib.parse.quote(p)}"))
    chosen, problems, seen = {}, [], set()
    queue = [(p, None) for p in projects]
    while queue:
        project, required_by = queue.pop(0)
        if project in seen:
            continue
        seen.add(project)
        try:
            info = project_info(project)
        except urllib.error.HTTPError:
            problems.append(f"{project}: not found on Modrinth")
            continue
        seen.add(info["id"])
        if info["id"] in chosen:
            continue
        if info.get("server_side") == "unsupported":
            print(f"  skip {info['title']}: client-only, players install it themselves")
            continue
        record = lookup(info["id"], server_type, version)
        if not record:
            suffix = f" (required by {required_by})" if required_by else ""
            problems.append(f"{info['title']}: no {server_type} build for {version}{suffix}")
            continue
        chosen[info["id"]] = (info["title"], record)
        for dependency in record.get("dependencies", []):
            if dependency["dependency_type"] == "required" and dependency.get("project_id"):
                queue.append((dependency["project_id"], info["title"]))
    return chosen, problems


def addons(server_type, version, list_file, target_dir):
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    projects = read_list(list_file)
    print(f"Resolving {len(projects)} {server_type} add-ons for {version} from {Path(list_file).name}")
    chosen, problems = resolve_addons(projects, server_type, version)
    if problems:
        raise SystemExit("Cannot install add-ons:\n  " + "\n  ".join(problems))

    manifest_path = target / MANIFEST
    previous = json.loads(manifest_path.read_text()) if manifest_path.is_file() else {}
    managed = {}
    for title, record in chosen.values():
        file = next((f for f in record["files"] if f["primary"]), record["files"][0])
        path = target / file["filename"]
        if not (path.is_file() and hashlib.sha512(path.read_bytes()).hexdigest() == file["hashes"]["sha512"]):
            write_verified(fetch(file["url"], timeout=300), path, sha512=file["hashes"]["sha512"])
        note = "" if record["version_type"] == "release" else f" ({record['version_type']})"
        print(f"  {title} {record['version_number']}{note}")
        managed[file["filename"]] = {"title": title, "version": record["version_number"]}

    for filename in set(previous) - set(managed):
        (target / filename).unlink(missing_ok=True)
        print(f"  removed {filename}")
    manifest_path.write_text(json.dumps(managed, indent=2, sort_keys=True) + "\n")
    unmanaged = sorted(p.name for p in target.glob("*.jar") if p.name not in managed)
    if unmanaged:
        print("  Also present, not managed by install.sh: " + ", ".join(unmanaged))


def main(argv):
    sys.stdout.reconfigure(line_buffering=True)
    commands = {
        "java-major": (1, lambda v: print(java_major(v))),
        "server-jar": (3, server_jar),
        "addons": (4, addons),
    }
    if not argv or argv[0] not in commands or len(argv) - 1 != commands[argv[0]][0]:
        raise SystemExit(__doc__)
    if argv[0] != "java-major" and argv[1] not in JAR_NAMES:
        raise SystemExit("server type must be paper or fabric")
    commands[argv[0]][1](*argv[1:])


if __name__ == "__main__":
    main(sys.argv[1:])
