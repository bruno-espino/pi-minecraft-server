from pathlib import Path
import tempfile
import unittest

from minecraft_manager.provision import read_list, resolve_addons

PROJECTS = {
    "fabric-api": {"id": "P7dR8mSH", "title": "Fabric API", "server_side": "required"},
    "P7dR8mSH": {"id": "P7dR8mSH", "title": "Fabric API", "server_side": "required"},
    "chunky": {"id": "fALzjamp", "title": "Chunky", "server_side": "required"},
    "sodium": {"id": "AANobbMI", "title": "Sodium", "server_side": "unsupported"},
    "old-mod": {"id": "OLD", "title": "Old Mod", "server_side": "optional"},
    "rechiseled": {"id": "REC", "title": "Rechiseled", "server_side": "required"},
    "FUS": {"id": "FUS", "title": "Fusion", "server_side": "unsupported"},
}


def project_info(name):
    return PROJECTS[name]


def version(number, dependencies=()):
    return {
        "version_number": number,
        "version_type": "release",
        "files": [],
        "dependencies": [{"dependency_type": "required", "project_id": d} for d in dependencies],
    }


VERSIONS = {
    "P7dR8mSH": version("0.166.2"),
    "fALzjamp": version("1.5.66", dependencies=["P7dR8mSH"]),
    "REC": version("1.2.6", dependencies=["FUS"]),
    "FUS": version("1.2.12"),
}


def lookup(project_id, server_type, game_version):
    return VERSIONS.get(project_id)


class ReadListTests(unittest.TestCase):
    def test_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mods.txt"
            path.write_text("# header\nlithium\n\nspark  # profiler\n")
            self.assertEqual(read_list(path), ["lithium", "spark"])


class ResolveAddonsTests(unittest.TestCase):
    def resolve(self, projects):
        return resolve_addons(projects, "fabric", "26.3", lookup=lookup, project_info=project_info)

    def test_required_dependency_is_added_once(self):
        chosen, problems = self.resolve(["chunky", "fabric-api"])
        self.assertEqual(problems, [])
        self.assertEqual(sorted(title for title, _ in chosen.values()), ["Chunky", "Fabric API"])

    def test_dependency_pulled_in_when_not_listed(self):
        chosen, _ = self.resolve(["chunky"])
        self.assertIn("P7dR8mSH", chosen)

    def test_client_only_mod_is_skipped(self):
        chosen, problems = self.resolve(["sodium"])
        self.assertEqual((chosen, problems), ({}, []))

    def test_client_only_dependency_is_still_installed(self):
        # Rechiseled requires Fusion on the server even though Modrinth marks
        # Fusion client-only; Fabric refuses to start without it.
        chosen, problems = self.resolve(["rechiseled"])
        self.assertEqual(problems, [])
        self.assertIn("FUS", chosen)

    def test_missing_build_is_reported(self):
        _, problems = self.resolve(["old-mod"])
        self.assertEqual(problems, ["Old Mod: no fabric build for 26.3"])


if __name__ == "__main__":
    unittest.main()
