"""Verify that the packaged Jobs Plugin has a registry-only locked dependency graph."""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

import tomllib

ROOT = Path(__file__).resolve().parents[2]
REGISTRY_SOURCE = "registry+https://github.com/rust-lang/crates.io-index"


class GateError(Exception):
    pass


def source_versions(root=ROOT):
    capability = tomllib.loads(
        (root / "crates/lenso-capability-jobs/Cargo.toml").read_text()
    )["package"]
    plugin = tomllib.loads((root / "crates/lenso-jobs-plugin/Cargo.toml").read_text())
    dependency = plugin["dependencies"]["lenso-capability-jobs"]
    workspace = tomllib.loads((root / "Cargo.toml").read_text())
    patch = workspace.get("patch", {}).get("crates-io", {}).get("lenso-capability-jobs")
    if (
        capability["publish"] is not True
        or plugin["package"]["publish"] is not True
        or dependency.get("version") != capability["version"]
        or "path" in dependency
        or not isinstance(patch, dict)
        or patch.get("path") != "crates/lenso-capability-jobs"
    ):
        raise GateError(
            "Jobs package manifests must use a registry dependency with a workspace-only local patch"
        )
    return plugin["package"]["version"], capability["version"]


def package_archive(plugin_version, no_verify=False):
    metadata = subprocess.run(
        ["cargo", "metadata", "--locked", "--no-deps", "--format-version", "1"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    target_dir = Path(json.loads(metadata.stdout)["target_directory"])
    command = ["cargo", "package", "--locked", "-p", "lenso-jobs-plugin"]
    if no_verify:
        command.append("--no-verify")
    subprocess.run(command, cwd=ROOT, check=True)
    archive = target_dir / "package" / f"lenso-jobs-plugin-{plugin_version}.crate"
    if not archive.is_file():
        raise GateError(f"cargo package did not create {archive}")
    return archive


def inspect_lock(lock_bytes, capability_version):
    lock = tomllib.loads(lock_bytes.decode("utf-8"))
    entries = [
        entry
        for entry in lock.get("package", [])
        if entry.get("name") == "lenso-capability-jobs"
    ]
    if len(entries) != 1 or entries[0].get("version") != capability_version:
        raise GateError(
            "archive lock must contain exactly one matching Jobs Capability version"
        )
    entry = entries[0]
    if entry.get("source") != REGISTRY_SOURCE:
        raise GateError(
            "archive lock resolves Jobs Capability from a workspace path, not crates.io"
        )
    if not re.fullmatch(r"[0-9a-f]{64}", entry.get("checksum", "")):
        raise GateError("archive lock has no valid Jobs Capability registry checksum")


def run_metadata(package_dir):
    result = subprocess.run(
        [
            "cargo",
            "metadata",
            "--manifest-path",
            str(package_dir / "Cargo.toml"),
            "--locked",
            "--format-version",
            "1",
        ],
        cwd=package_dir,
        env={**os.environ, "CARGO_TARGET_DIR": str(package_dir.parent / "target")},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateError(
            f"archived cargo metadata --locked failed:\n{result.stderr[-8000:]}"
        )
    return json.loads(result.stdout)


def verify_archive(
    archive, plugin_version, capability_version, metadata_runner=run_metadata
):
    prefix = f"lenso-jobs-plugin-{plugin_version}"
    with tempfile.TemporaryDirectory(prefix="lenso-jobs-package-gate-") as temporary:
        temporary_dir = Path(temporary)
        with tarfile.open(archive, "r:gz") as package:
            members = package.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)):
                raise GateError("archive contains duplicate paths")
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not path.parts
                    or path.parts[0] != prefix
                    or not (member.isfile() or member.isdir())
                ):
                    raise GateError(f"archive contains an unsafe member: {member.name}")
            package.extractall(temporary_dir, filter="data")

        package_dir = temporary_dir / prefix
        manifest_path = package_dir / "Cargo.toml"
        lock_path = package_dir / "Cargo.lock"
        if not manifest_path.is_file() or not lock_path.is_file():
            raise GateError("archive must contain Cargo.toml and Cargo.lock")
        manifest = tomllib.loads(manifest_path.read_text())
        if (
            manifest.get("package", {}).get("name") != "lenso-jobs-plugin"
            or manifest["package"].get("version") != plugin_version
        ):
            raise GateError("archive package identity differs from the release source")
        dependency = manifest.get("dependencies", {}).get("lenso-capability-jobs")
        if (
            not isinstance(dependency, dict)
            or dependency.get("version") != capability_version
        ):
            raise GateError("archive manifest has no exact Jobs Capability dependency")
        if "path" in dependency or manifest.get("patch"):
            raise GateError(
                "archive manifest contains a path dependency or registry patch"
            )

        lock_before = lock_path.read_bytes()
        inspect_lock(lock_before, capability_version)
        graph = metadata_runner(package_dir)
        if lock_path.read_bytes() != lock_before:
            raise GateError("archived cargo metadata changed Cargo.lock")
        matching = [
            item
            for item in graph.get("packages", [])
            if item.get("name") == "lenso-capability-jobs"
            and item.get("version") == capability_version
        ]
        if len(matching) != 1 or matching[0].get("source") != REGISTRY_SOURCE:
            raise GateError(
                "archived cargo metadata did not resolve Jobs Capability from crates.io"
            )
        roots = [
            item
            for item in graph.get("packages", [])
            if item.get("name") == "lenso-jobs-plugin"
            and item.get("version") == plugin_version
        ]
        if len(roots) != 1 or roots[0].get("source") is not None:
            raise GateError(
                "archived cargo metadata did not identify the local Jobs Plugin root"
            )
        if any(
            item is not roots[0] and item.get("source") != REGISTRY_SOURCE
            for item in graph["packages"]
        ):
            raise GateError(
                "archived cargo metadata contains a non-registry dependency"
            )

    archive_sha = hashlib.sha256(Path(archive).read_bytes()).hexdigest()
    lock_sha = hashlib.sha256(lock_before).hexdigest()
    print(f"Jobs archive: {archive} (sha256 {archive_sha})")
    print(f"Archived lock: sha256 {lock_sha}; Jobs Capability registry source verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--archive", type=Path, help="verify an existing .crate instead of packaging"
    )
    parser.add_argument(
        "--no-verify", action="store_true", help="skip cargo package build verification"
    )
    args = parser.parse_args()
    if args.archive and args.no_verify:
        parser.error("--no-verify only applies when packaging")
    try:
        plugin_version, capability_version = source_versions()
        archive = args.archive or package_archive(
            plugin_version, no_verify=args.no_verify
        )
        verify_archive(archive, plugin_version, capability_version)
    except (
        GateError,
        OSError,
        ValueError,
        tomllib.TOMLDecodeError,
        subprocess.CalledProcessError,
    ) as error:
        print(f"Jobs package consumer gate: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
