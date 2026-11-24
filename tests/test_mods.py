import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from v3nl.mods import all_mods, playsets, playset_mods, validate_mods


class ModTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a = self.root / "mod" / "alpha"
        self.b = self.root / "mod" / "beta"
        for d, name in [(self.a, "Alpha"), (self.b, "Beta")]:
            (d / ".metadata").mkdir(parents=True)
            (d / ".metadata" / "metadata.json").write_text(
                json.dumps({"id": name.lower(), "name": name, "version": "1"}), encoding="utf-8")
        db = sqlite3.connect(self.root / "launcher-v2.sqlite")
        db.executescript("""
            CREATE TABLE playsets (id TEXT, name TEXT, isActive INTEGER, isRemoved INTEGER);
            CREATE TABLE mods (id TEXT, displayName TEXT, name TEXT, version TEXT,
                               source TEXT, dirPath TEXT, repositoryPath TEXT, requiredVersion TEXT);
            CREATE TABLE playsets_mods (playsetId TEXT, modId TEXT, enabled INTEGER, position INTEGER);
        """)
        db.execute("INSERT INTO playsets VALUES ('p1','My Playset',1,0)")
        db.execute("INSERT INTO mods VALUES ('m1','Alpha','','1','local',?, '', '1.15.*')",(str(self.a),))
        db.execute("INSERT INTO mods VALUES ('m2','Beta','','1','local',?, '', '1.15.*')",(str(self.b),))
        db.execute("INSERT INTO playsets_mods VALUES ('p1','m2',1,10)")
        db.execute("INSERT INTO playsets_mods VALUES ('p1','m1',1,20)")
        db.commit()
        db.close()

    def test_import_playset_preserves_position_order(self):
        self.assertEqual([x.id for x in playsets(self.root)], ["p1"])
        picked, warnings = playset_mods(self.root, "p1")
        self.assertEqual([x.name for x in picked], ["Beta", "Alpha"])
        self.assertEqual(warnings, [])

    def test_merge_local_and_database_deduplicates(self):
        self.assertEqual(len(all_mods(self.root)), 2)

    def test_validate_rejects_bad_or_duplicate_folders(self):
        self.assertEqual(len(validate_mods([str(self.a), str(self.b)])), 2)
        with self.assertRaises(ValueError):
            validate_mods([str(self.a), str(self.a)])
        with self.assertRaises(FileNotFoundError):
            validate_mods([str(self.root / "missing")])
