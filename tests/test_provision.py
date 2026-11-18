from pathlib import Path
import tempfile
import unittest
import urllib.error

from minecraft_manager.provision import client_pack, read_list, resolve_addons


def project(project_id, title, server, client):
    return {"id": project_id, "slug": title.lower().replace(" ", "-"), "title": title,
            "server_side": server, "client_side": client}


PROJECTS = {p["id"]: p for p in [
    project("API", "Fabric API", "optional", "optional"),       # optional on clients per Modrinth
    project("STORAGE", "Toms Storage", "required", "required"),  # content mod: both sides
    project("REC", "Rechiseled", "required", "required"),
    project("FUS", "Fusion", "unsupported", "required"),         # client-only label, but required
    project("SOD", "Sodium", "unsupported", "required"),         # client-only mod
    project("JEI", "JEI", "optional", "optional"),
    project("CFG", "MezzConfig", "optional", "optional"),
    project("SPAWN", "GetSpawners", "required", "unsupported"),  # server-only
    project("LITH", "Lithium", "optional", "optional"),
    project("OLD", "Old Mod", "required", "required"),
]}
SLUGS = {p["slug"]: p for p in PROJECTS.values()}


def project_info(name):
    return PROJECTS.get(name) or SLUGS[name]


def version(number, dependencies=()):
    return {
        "version_number": number,
        "version_type": "release",
        "files": [{"primary": True, "filename": f"{number}.jar", "url": f"https://cdn.modrinth.com/{number}.jar",
                   "size": 10, "hashes": {"sha1": "a" * 40, "sha512": "b" * 128}}],
        "dependencies": [{"dependency_type": "required", "project_id": d} for d in dependencies],
    }


VERSIONS = {
    "API": version("api-1"),
    "STORAGE": version("storage-1", ["API"]),
    "REC": version("rec-1", ["FUS"]),
    "FUS": version("fus-1"),
    "SOD": version("sod-1"),
    "JEI": version("jei-1", ["CFG"]),
    "CFG": version("cfg-1"),
    "SPAWN": version("spawn-1"),
    "LITH": version("lith-1"),
}


def resolve(*lines):
    entries = []
    for line in lines:
        words = line.split()
        entries.append((words[0], set(words[1:])))
    return resolve_addons(entries, "fabric", "26.3",
                          lookup=lambda i, *_: VERSIONS.get(i), project_info=project_info)


def titles(resolution, group):
    return sorted(resolution["nodes"][i]["info"]["title"] for i in resolution[group])


class ReadListTests(unittest.TestCase):
    def test_comments_tags_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mods.txt"
            path.write_text("# header\nlithium\n\njei client  # recipes\n")
            self.assertEqual(read_list(path), [("lithium", set()), ("jei", {"client"})])


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.result = resolve("toms-storage", "rechiseled", "sodium", "jei client", "getspawners", "lithium")

    def test_server_gets_listed_mods_and_dependencies_but_not_client_only_ones(self):
        self.assertEqual(
            titles(self.result, "server"),
            ["Fabric API", "Fusion", "GetSpawners", "JEI", "Lithium", "MezzConfig", "Rechiseled", "Toms Storage"],
        )

    def test_players_need_content_mods_and_everything_they_depend_on(self):
        # Fabric API is "optional" on clients per Modrinth, but Toms Storage needs it.
        self.assertEqual(titles(self.result, "required"), ["Fabric API", "Fusion", "Rechiseled", "Toms Storage"])

    def test_optional_player_mods_are_client_only_or_tagged(self):
        self.assertEqual(titles(self.result, "optional"), ["JEI", "MezzConfig", "Sodium"])

    def test_no_problems(self):
        self.assertEqual((self.result["problems"], self.result["warnings"]), ([], []))

    def test_missing_server_build_blocks_install(self):
        self.assertEqual(resolve("old-mod")["problems"], ["Old Mod: no fabric build for 26.3"])

    def test_unknown_project(self):
        def missing(name):
            raise urllib.error.HTTPError(name, 404, "Not Found", {}, None)
        result = resolve_addons([("nope", set())], "fabric", "26.3", lookup=lambda *_: None, project_info=missing)
        self.assertEqual(result["problems"], ["nope: not found on Modrinth"])


class ClientPackTests(unittest.TestCase):
    def test_pack_index_and_summary(self):
        index, summary = client_pack(resolve("toms-storage", "sodium"), "26.3", "0.20.1")
        self.assertEqual(index["dependencies"], {"minecraft": "26.3", "fabric-loader": "0.20.1"})
        paths = {f["path"]: f.get("env") for f in index["files"]}
        self.assertEqual(paths, {
            "mods/api-1.jar": None,
            "mods/storage-1.jar": None,
            "mods/sod-1.jar": {"client": "optional", "server": "optional"},
        })
        self.assertEqual([m["title"] for m in summary["required"]], ["Fabric API", "Toms Storage"])
        self.assertEqual([m["title"] for m in summary["optional"]], ["Sodium"])
        self.assertTrue(index["versionId"].startswith("26.3-"))


if __name__ == "__main__":
    unittest.main()
