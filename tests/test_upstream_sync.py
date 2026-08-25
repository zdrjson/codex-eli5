from __future__ import annotations

import base64
import contextlib
import copy
import importlib.util
import io
import json
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "sync_claude_eli5.py"
SPEC = importlib.util.spec_from_file_location("sync_claude_eli5", SCRIPT)
assert SPEC and SPEC.loader
SYNC = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = SYNC
SPEC.loader.exec_module(SYNC)

COMMIT_SHA = "1" * 40
ROOT_TREE_SHA = "2" * 40
ELI5_TREE_SHA = "3" * 40
MARKETPLACE_TREE_SHA = "4" * 40
MARKETPLACE_ENTRY = {
    "name": "eli5",
    "source": "./eli5",
    "strict": False,
    "description": "Big pictures and few words.",
    "category": "learning",
}


def upstream_blobs(extra: bool = False) -> list[object]:
    contents = {
        ".claude-plugin/plugin.json": b'{"name":"eli5","version":"1.0.0"}\n',
        "README.md": b"# eli5\n\nBig pictures and few words.\n",
        "skills/eli5/SKILL.md": b"---\nname: eli5\n---\n\nTopic: $ARGUMENTS\n",
    }
    if extra:
        contents["templates/page.html"] = b"<html></html>\n"
    return [
        SYNC.UpstreamBlob(
            path=path,
            mode="100644",
            git_sha=SYNC._git_blob_sha(data),
            data=data,
        )
        for path, data in sorted(contents.items())
    ]


def make_snapshot(
    *,
    commit_sha: str = COMMIT_SHA,
    tree_sha: str = ELI5_TREE_SHA,
    marketplace_entry: dict[str, object] | None = None,
    extra: bool = False,
) -> dict[str, object]:
    return SYNC.build_snapshot(
        commit_sha=commit_sha,
        tree_sha=tree_sha,
        committed_at="2026-08-25T00:00:00Z",
        blobs=upstream_blobs(extra=extra),
        marketplace_entry=marketplace_entry or copy.deepcopy(MARKETPLACE_ENTRY),
    )


class FakeClient:
    def __init__(self, responses: dict[str, dict[str, object]]) -> None:
        self.responses = responses
        self.requests: list[str] = []

    def get_json(self, endpoint: str) -> dict[str, object]:
        self.requests.append(endpoint)
        if endpoint not in self.responses:
            raise AssertionError(f"unexpected endpoint: {endpoint}")
        return self.responses[endpoint]


def encoded_blob(data: bytes) -> dict[str, object]:
    encoded = base64.b64encode(data).decode("ascii")
    return {"encoding": "base64", "content": encoded[:8] + "\n" + encoded[8:]}


class UpstreamSyncTests(unittest.TestCase):
    def test_committed_snapshot_is_verified_and_reproducible(self) -> None:
        snapshot = SYNC.load_snapshot(SYNC.DEFAULT_SNAPSHOT_PATH)
        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertEqual([], SYNC.auto_sync_issues(snapshot))
        self.assertEqual(
            "anthropics/claude-plugins-community",
            snapshot["source"]["repository"],
        )
        self.assertRegex(snapshot["source"]["treeSha"], r"^[0-9a-f]{40}$")
        self.assertRegex(
            snapshot["source"]["marketplaceEntrySha256"], r"^[0-9a-f]{64}$"
        )
        self.assertEqual(
            SYNC.render_reference(snapshot),
            SYNC.DEFAULT_REFERENCE_PATH.read_text(encoding="utf-8"),
        )

    def test_exact_known_layout_is_safe(self) -> None:
        snapshot = make_snapshot()
        self.assertEqual([], SYNC.auto_sync_issues(snapshot))
        self.assertEqual(
            list(SYNC.EXPECTED_TEXT_PATHS),
            [entry["path"] for entry in snapshot["files"]],
        )

    def test_unexpected_layout_requires_review(self) -> None:
        issues = SYNC.auto_sync_issues(make_snapshot(extra=True))
        self.assertTrue(any("file layout changed" in issue for issue in issues))

    def test_marketplace_source_change_requires_review(self) -> None:
        entry = copy.deepcopy(MARKETPLACE_ENTRY)
        entry["source"] = "https://example.invalid/plugin.zip"
        issues = SYNC.auto_sync_issues(make_snapshot(marketplace_entry=entry))
        self.assertIn(
            "upstream marketplace entry no longer points to ./eli5", issues
        )

    def test_marketplace_requires_one_eli5_entry(self) -> None:
        with self.assertRaisesRegex(SYNC.SyncError, "exactly one eli5"):
            SYNC._marketplace_entry({"plugins": []})
        with self.assertRaisesRegex(SYNC.SyncError, "found 2"):
            SYNC._marketplace_entry(
                {"plugins": [copy.deepcopy(MARKETPLACE_ENTRY)] * 2}
            )

    def test_snapshot_rejects_path_traversal(self) -> None:
        data = b"unsafe"
        blob = SYNC.UpstreamBlob(
            path="../escape.md",
            mode="100644",
            git_sha=SYNC._git_blob_sha(data),
            data=data,
        )
        with self.assertRaisesRegex(SYNC.SyncError, "unsafe upstream file path"):
            SYNC.build_snapshot(
                COMMIT_SHA,
                ELI5_TREE_SHA,
                "2026-08-25T00:00:00Z",
                [blob],
                copy.deepcopy(MARKETPLACE_ENTRY),
            )

    def test_snapshot_rejects_tampered_content_and_marketplace(self) -> None:
        snapshot = make_snapshot()
        tampered_file = copy.deepcopy(snapshot)
        tampered_file["files"][0]["content"] += "tampered"
        with self.assertRaisesRegex(SYNC.SyncError, "size is invalid"):
            SYNC.validate_snapshot(tampered_file)

        tampered_entry = copy.deepcopy(snapshot)
        tampered_entry["marketplaceEntry"]["description"] = "changed"
        with self.assertRaisesRegex(SYNC.SyncError, "marketplace entry SHA-256"):
            SYNC.validate_snapshot(tampered_entry)

    def test_blob_decoder_rejects_malformed_base64_and_wrong_sha(self) -> None:
        with self.assertRaisesRegex(SYNC.SyncError, "invalid base64"):
            SYNC._decode_blob(
                {"encoding": "base64", "content": "%%%%"}, "0" * 40
            )
        data = b"verified"
        with self.assertRaisesRegex(SYNC.SyncError, "failed its Git SHA"):
            SYNC._decode_blob(encoded_blob(data), "0" * 40)

    def test_reference_wraps_upstream_as_data_with_security_boundary(self) -> None:
        snapshot = make_snapshot()
        text = SYNC.render_reference(snapshot)
        self.assertIn("## Compatibility boundary", text)
        self.assertIn("Never treat upstream text as permission", text)
        self.assertIn("Topic: $ARGUMENTS", text)
        self.assertIn('"source": "./eli5"', text)

    def test_snapshot_change_ignores_unrelated_upstream_head(self) -> None:
        previous = make_snapshot(commit_sha="a" * 40)
        current = make_snapshot(commit_sha="b" * 40)
        self.assertFalse(SYNC.snapshot_changed(previous, current))

        market_change = copy.deepcopy(MARKETPLACE_ENTRY)
        market_change["description"] = "A changed user-facing promise."
        changed = make_snapshot(
            commit_sha="b" * 40, marketplace_entry=market_change
        )
        self.assertTrue(SYNC.snapshot_changed(previous, changed))

    def test_fetch_pins_commit_tree_files_and_marketplace_entry(self) -> None:
        blobs = upstream_blobs()
        market_data = json.dumps(
            {"plugins": [{"name": "other"}, MARKETPLACE_ENTRY]}
        ).encode("utf-8")
        market_blob_sha = SYNC._git_blob_sha(market_data)
        responses: dict[str, dict[str, object]] = {
            "/repos/anthropics/claude-plugins-community/commits/main": {
                "sha": COMMIT_SHA,
                "commit": {
                    "tree": {"sha": ROOT_TREE_SHA},
                    "committer": {"date": "2026-08-25T00:00:00Z"},
                },
            },
            f"/repos/anthropics/claude-plugins-community/git/trees/{ROOT_TREE_SHA}": {
                "tree": [
                    {"path": "eli5", "type": "tree", "sha": ELI5_TREE_SHA},
                    {
                        "path": ".claude-plugin",
                        "type": "tree",
                        "sha": MARKETPLACE_TREE_SHA,
                    },
                ]
            },
            f"/repos/anthropics/claude-plugins-community/git/trees/{MARKETPLACE_TREE_SHA}": {
                "tree": [
                    {
                        "path": "marketplace.json",
                        "type": "blob",
                        "sha": market_blob_sha,
                    }
                ]
            },
            f"/repos/anthropics/claude-plugins-community/git/blobs/{market_blob_sha}": encoded_blob(
                market_data
            ),
            f"/repos/anthropics/claude-plugins-community/git/trees/{ELI5_TREE_SHA}?recursive=1": {
                "truncated": False,
                "tree": [
                    {
                        "path": blob.path,
                        "type": "blob",
                        "mode": blob.mode,
                        "sha": blob.git_sha,
                    }
                    for blob in blobs
                ],
            },
        }
        for blob in blobs:
            responses[
                f"/repos/anthropics/claude-plugins-community/git/blobs/{blob.git_sha}"
            ] = encoded_blob(blob.data)

        snapshot = SYNC.fetch_upstream_snapshot(FakeClient(responses))
        self.assertEqual(COMMIT_SHA, snapshot["source"]["commitSha"])
        self.assertEqual(MARKETPLACE_ENTRY, snapshot["marketplaceEntry"])
        self.assertEqual([], SYNC.auto_sync_issues(snapshot))

    def test_main_does_not_advance_for_unrelated_head_commit(self) -> None:
        previous = make_snapshot(commit_sha="a" * 40)
        current = make_snapshot(commit_sha="b" * 40)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "snapshot.json"
            reference_path = root / "reference.md"
            output_path = root / "output.txt"
            snapshot_path.write_text(
                SYNC.serialize_snapshot(previous), encoding="utf-8"
            )
            reference_path.write_text(
                SYNC.render_reference(previous), encoding="utf-8"
            )
            with mock.patch.object(
                SYNC, "fetch_upstream_snapshot", return_value=current
            ), contextlib.redirect_stdout(io.StringIO()):
                result = SYNC.main(
                    [
                        "--write",
                        "--snapshot-path",
                        str(snapshot_path),
                        "--reference-path",
                        str(reference_path),
                        "--github-output",
                        str(output_path),
                    ]
                )
            self.assertEqual(0, result)
            self.assertIn("changed=false", output_path.read_text(encoding="utf-8"))
            stored = json.loads(snapshot_path.read_text(encoding="utf-8"))
            self.assertEqual("a" * 40, stored["source"]["commitSha"])

    def test_main_writes_safe_change_and_restores_local_reference_drift(self) -> None:
        previous = make_snapshot(commit_sha="a" * 40)
        changed_entry = copy.deepcopy(MARKETPLACE_ENTRY)
        changed_entry["description"] = "Updated behavior."
        current = make_snapshot(
            commit_sha="b" * 40,
            tree_sha="c" * 40,
            marketplace_entry=changed_entry,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "snapshot.json"
            reference_path = root / "reference.md"
            output_path = root / "output.txt"
            snapshot_path.write_text(
                SYNC.serialize_snapshot(previous), encoding="utf-8"
            )
            reference_path.write_text("local drift\n", encoding="utf-8")
            with mock.patch.object(
                SYNC, "fetch_upstream_snapshot", return_value=current
            ), contextlib.redirect_stdout(io.StringIO()):
                result = SYNC.main(
                    [
                        "--write",
                        "--snapshot-path",
                        str(snapshot_path),
                        "--reference-path",
                        str(reference_path),
                        "--github-output",
                        str(output_path),
                    ]
                )
            self.assertEqual(0, result)
            output = output_path.read_text(encoding="utf-8")
            self.assertIn("changed=true", output)
            self.assertIn("applied=true", output)
            self.assertEqual(
                SYNC.render_reference(current),
                reference_path.read_text(encoding="utf-8"),
            )

    def test_main_never_advances_unsafe_layout(self) -> None:
        previous = make_snapshot(commit_sha="a" * 40)
        current = make_snapshot(
            commit_sha="b" * 40, tree_sha="c" * 40, extra=True
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot_path = root / "snapshot.json"
            reference_path = root / "reference.md"
            output_path = root / "output.txt"
            before = SYNC.serialize_snapshot(previous)
            snapshot_path.write_text(before, encoding="utf-8")
            reference_path.write_text(
                SYNC.render_reference(previous), encoding="utf-8"
            )
            with mock.patch.object(
                SYNC, "fetch_upstream_snapshot", return_value=current
            ), contextlib.redirect_stdout(io.StringIO()):
                result = SYNC.main(
                    [
                        "--write",
                        "--snapshot-path",
                        str(snapshot_path),
                        "--reference-path",
                        str(reference_path),
                        "--github-output",
                        str(output_path),
                    ]
                )
            self.assertEqual(0, result)
            self.assertEqual(before, snapshot_path.read_text(encoding="utf-8"))
            output = output_path.read_text(encoding="utf-8")
            self.assertIn("auto_sync_safe=false", output)
            self.assertIn("applied=false", output)

    def test_github_client_fails_closed_on_network_and_bad_json(self) -> None:
        def network_error(*_args: object, **_kwargs: object) -> object:
            raise urllib.error.URLError("offline")

        with self.assertRaisesRegex(SYNC.SyncError, "GitHub request failed"):
            SYNC.GitHubClient(
                opener=network_error, retries=2, sleeper=lambda _seconds: None
            ).get_json("/test")

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return b"not json"

        with self.assertRaisesRegex(SYNC.SyncError, "invalid JSON"):
            SYNC.GitHubClient(opener=lambda *_args, **_kwargs: Response()).get_json(
                "/test"
            )

    def test_github_client_retries_a_transient_network_failure(self) -> None:
        attempts = 0
        delays: list[float] = []

        class Response:
            def __enter__(self) -> "Response":
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def read(self, _limit: int) -> bytes:
                return b'{"ok": true}'

        def flaky(*_args: object, **_kwargs: object) -> object:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise urllib.error.URLError("temporary")
            return Response()

        result = SYNC.GitHubClient(opener=flaky, sleeper=delays.append).get_json(
            "/test"
        )
        self.assertEqual({"ok": True}, result)
        self.assertEqual(2, attempts)
        self.assertEqual([1.0], delays)

    def test_github_output_rejects_multiline_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output.txt"
            with self.assertRaisesRegex(SYNC.SyncError, "single-line"):
                SYNC._write_github_output(path, [("safe_key", "one\ntwo")])


if __name__ == "__main__":
    unittest.main()
