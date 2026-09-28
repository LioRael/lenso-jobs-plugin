import importlib.util
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).with_name("package-consumer-gate.py")
SPEC = importlib.util.spec_from_file_location("package_consumer_gate", SCRIPT)
GATE = importlib.util.module_from_spec(SPEC)
sys.dont_write_bytecode = True
SPEC.loader.exec_module(GATE)


class PackageConsumerGateTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.package = self.root / "lenso-jobs-plugin-0.1.8"
        self.package.mkdir()
        (self.package / "Cargo.toml").write_text(
            '[package]\nname = "lenso-jobs-plugin"\nversion = "0.1.8"\n'
            '[dependencies.lenso-capability-jobs]\nversion = "0.1.6"\n'
        )
        (self.package / "Cargo.lock").write_text(
            "version = 3\n"
            '[[package]]\nname = "lenso-capability-jobs"\nversion = "0.1.6"\n'
            f'source = "{GATE.REGISTRY_SOURCE}"\n'
            f'checksum = "{"a" * 64}"\n'
        )
        self.archive = self.root / "lenso-jobs-plugin-0.1.8.crate"

    def pack(self):
        with tarfile.open(self.archive, "w:gz") as package:
            package.add(self.package, arcname=self.package.name)

    @staticmethod
    def metadata(package_dir):
        return {
            "packages": [
                {"name": "lenso-jobs-plugin", "version": "0.1.8", "source": None},
                {
                    "name": "lenso-capability-jobs",
                    "version": "0.1.6",
                    "source": GATE.REGISTRY_SOURCE,
                },
            ]
        }

    def verify(self, metadata_runner=None):
        GATE.verify_archive(
            self.archive,
            "0.1.8",
            "0.1.6",
            metadata_runner or self.metadata,
        )

    def test_accepts_registry_lock_without_mutation(self):
        self.pack()
        self.verify()

    def test_rejects_workspace_path_lock(self):
        lock = self.package / "Cargo.lock"
        lock.write_text(
            lock.read_text().replace(f'source = "{GATE.REGISTRY_SOURCE}"\n', "")
        )
        self.pack()
        with self.assertRaisesRegex(GATE.GateError, "workspace path"):
            self.verify()

    def test_rejects_missing_checksum(self):
        lock = self.package / "Cargo.lock"
        lock.write_text(lock.read_text().replace(f'checksum = "{"a" * 64}"\n', ""))
        self.pack()
        with self.assertRaisesRegex(GATE.GateError, "checksum"):
            self.verify()

    def test_rejects_metadata_lock_mutation(self):
        self.pack()

        def mutate(package_dir):
            with (package_dir / "Cargo.lock").open("a") as lock:
                lock.write("\n")
            return self.metadata(package_dir)

        with self.assertRaisesRegex(GATE.GateError, "changed Cargo.lock"):
            self.verify(mutate)

    def test_rejects_nonregistry_metadata_graph(self):
        self.pack()

        def path_graph(package_dir):
            graph = self.metadata(package_dir)
            graph["packages"][1]["source"] = None
            return graph

        with self.assertRaisesRegex(GATE.GateError, "did not resolve"):
            self.verify(path_graph)

    def test_rejects_other_path_dependency(self):
        self.pack()

        def path_graph(package_dir):
            graph = self.metadata(package_dir)
            graph["packages"].append(
                {"name": "other", "version": "1.0.0", "source": None}
            )
            return graph

        with self.assertRaisesRegex(GATE.GateError, "non-registry dependency"):
            self.verify(path_graph)

    def test_rejects_archived_path_dependency(self):
        manifest = self.package / "Cargo.toml"
        manifest.write_text(
            manifest.read_text() + 'path = "../lenso-capability-jobs"\n'
        )
        self.pack()
        with self.assertRaisesRegex(GATE.GateError, "path dependency"):
            self.verify()

    def test_registry_dependency_keeps_local_workspace_patch(self):
        capability = self.root / "crates" / "lenso-capability-jobs"
        plugin = self.root / "crates" / "lenso-jobs-plugin"
        capability.mkdir(parents=True)
        plugin.mkdir()
        (capability / "Cargo.toml").write_text(
            '[package]\nname = "lenso-capability-jobs"\nversion = "0.1.6"\npublish = true\n'
        )
        (plugin / "Cargo.toml").write_text(
            '[package]\nname = "lenso-jobs-plugin"\nversion = "0.1.8"\npublish = true\n'
            '[dependencies.lenso-capability-jobs]\nversion = "0.1.6"\n'
        )
        (self.root / "Cargo.toml").write_text(
            '[patch.crates-io]\n'
            'lenso-capability-jobs = { path = "crates/lenso-capability-jobs" }\n'
        )
        self.assertEqual(GATE.source_versions(self.root), ("0.1.8", "0.1.6"))

    def test_repository_manifests_satisfy_package_gate(self):
        self.assertEqual(GATE.source_versions(), ("0.1.8", "0.1.6"))


if __name__ == "__main__":
    unittest.main()
