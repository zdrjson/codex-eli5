import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "sync-claude-eli5.yml"


class SyncWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")

    def test_schedule_and_manual_dispatch_are_configured(self):
        self.assertRegex(self.workflow, r'(?m)^\s+schedule:\s*$')
        self.assertRegex(self.workflow, r'(?m)^\s+- cron: "23 \*/6 \* \* \*"\s*$')
        self.assertRegex(self.workflow, r'(?m)^\s+workflow_dispatch:\s*$')

    def test_concurrency_prevents_overlapping_sync_runs(self):
        self.assertRegex(self.workflow, r'(?m)^concurrency:\s*$')
        self.assertRegex(self.workflow, r'(?m)^\s+group: sync-claude-eli5\s*$')
        self.assertRegex(self.workflow, r'(?m)^\s+cancel-in-progress: false\s*$')

    def test_permissions_are_explicit_and_minimal_for_the_workflow(self):
        permissions = re.search(
            r"(?ms)^permissions:\n(?P<body>(?:  [^\n]+\n)+)", self.workflow
        )
        self.assertIsNotNone(permissions)
        entries = {
            line.strip()
            for line in permissions.group("body").splitlines()
            if line.strip()
        }
        self.assertEqual(
            entries,
            {
                "contents: write",
                "pull-requests: write",
                "issues: write",
            },
        )

    def test_sync_runs_on_the_default_branch_and_writes_a_report(self):
        self.assertIn(
            "github.ref_name == github.event.repository.default_branch",
            self.workflow,
        )
        self.assertIn("python scripts/sync_claude_eli5.py", self.workflow)
        self.assertIn("--write", self.workflow)
        self.assertIn("--report \"$RUNNER_TEMP/claude-eli5-report.md\"", self.workflow)

    def test_safe_changed_update_runs_all_tests_before_publish(self):
        tests_at = self.workflow.index("- name: Run the complete regression suite")
        publish_at = self.workflow.index(
            "- name: Publish a SHA-pinned draft pull request"
        )
        self.assertLess(tests_at, publish_at)
        self.assertIn("python -m unittest discover -s tests -v", self.workflow)
        self.assertIn("steps.sync.outputs.changed == 'true'", self.workflow)
        self.assertIn("steps.sync.outputs.auto_sync_safe == 'true'", self.workflow)
        self.assertIn("steps.sync.outputs.applied == 'true'", self.workflow)
        self.assertIn("steps.tests.outcome == 'success'", self.workflow)

    def test_branch_and_commit_are_pinned_to_a_valid_upstream_sha(self):
        self.assertIn(
            '[[ ! "$UPSTREAM_COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]]', self.workflow
        )
        self.assertIn('SHORT_SHA="${UPSTREAM_COMMIT_SHA:0:12}"', self.workflow)
        self.assertIn(
            'SYNC_BRANCH="automation/claude-eli5-${SHORT_SHA}"', self.workflow
        )
        self.assertIn('git switch -c "$SYNC_BRANCH"', self.workflow)

    def test_only_generated_snapshot_and_reference_can_be_committed(self):
        self.assertIn(
            "SNAPSHOT_PATH: upstream/claude-eli5.snapshot.json", self.workflow
        )
        self.assertIn(
            "REFERENCE_PATH: plugins/codex-eli5/skills/eli5/references/claude-eli5.md",
            self.workflow,
        )
        self.assertIn('git add -- "$SNAPSHOT_PATH" "$REFERENCE_PATH"', self.workflow)
        self.assertIn('changed - allowed', self.workflow)
        self.assertIn('staged.issubset(expected)', self.workflow)

    def test_push_is_non_force_and_never_targets_main_directly(self):
        self.assertIn('git push --set-upstream origin "$SYNC_BRANCH"', self.workflow)
        self.assertNotRegex(self.workflow, r"(?m)^\s*git push[^\n]*\bmain\b")
        self.assertNotIn("--force", self.workflow)
        self.assertNotIn("force-with-lease", self.workflow)
        self.assertNotIn("gh pr merge", self.workflow)
        self.assertNotRegex(self.workflow, r"(?m)^\s*auto-merge:\s*")
        self.assertNotIn("pull_request_target", self.workflow)

    def test_pull_request_is_draft_and_same_sha_is_idempotent(self):
        self.assertIn("gh pr create", self.workflow)
        self.assertIn("--draft", self.workflow)
        self.assertIn("gh pr list", self.workflow)
        self.assertIn("git ls-remote --exit-code --heads origin", self.workflow)
        self.assertIn('if [[ -n "$OPEN_PR_URL" ]]', self.workflow)
        self.assertIn(
            "The SHA-pinned draft pull request already exists", self.workflow
        )

    def test_existing_sha_branch_is_checked_for_unexpected_files_and_drift(self):
        self.assertIn(
            '["git", "diff", "--name-only", "-z", f"{base}...{branch}"]',
            self.workflow,
        )
        self.assertIn(
            'git diff --quiet "refs/remotes/origin/$SYNC_BRANCH"', self.workflow
        )
        self.assertIn(
            "The existing SHA branch does not match the generated update",
            self.workflow,
        )

    def test_unsafe_or_failed_sync_uses_one_reopenable_attention_issue(self):
        self.assertIn(
            '[automation] Claude ELI5 upstream sync needs attention', self.workflow
        )
        self.assertIn("gh issue list --state all", self.workflow)
        self.assertIn('gh issue reopen "$ISSUE_NUMBER"', self.workflow)
        self.assertIn('gh issue comment "$ISSUE_NUMBER"', self.workflow)
        self.assertIn("gh issue create", self.workflow)
        self.assertIn("steps.sync.outcome == 'failure'", self.workflow)
        self.assertIn("steps.guard.outcome == 'failure'", self.workflow)
        self.assertIn("steps.tests.outcome == 'failure'", self.workflow)
        self.assertIn("steps.publish.outcome == 'failure'", self.workflow)
        self.assertIn("stored baseline was not advanced", self.workflow)

    def test_pr_failure_escalates_and_the_job_remains_failed(self):
        issue_at = self.workflow.index(
            "- name: Create or update the single attention issue"
        )
        preserve_at = self.workflow.index(
            "- name: Preserve the failed status after escalation"
        )
        self.assertLess(issue_at, preserve_at)
        self.assertRegex(
            self.workflow,
            r"(?s)Preserve the failed status after escalation.*?run: exit 1",
        )

    def test_upstream_outputs_and_report_are_never_evaluated_as_shell_code(self):
        lines = self.workflow.splitlines()
        run_blocks = []
        index = 0
        while index < len(lines):
            if lines[index] != "        run: |":
                index += 1
                continue
            index += 1
            block = []
            while index < len(lines):
                line = lines[index]
                if line and not line.startswith("          "):
                    break
                block.append(line[10:] if line else "")
                index += 1
            run_blocks.append("\n".join(block))
        self.assertTrue(run_blocks)
        joined = "\n".join(run_blocks)
        self.assertNotIn("${{ steps.sync.outputs.", joined)
        self.assertNotRegex(joined, r"(?m)^\s*(eval|source)\s")
        self.assertNotIn("bash -c", joined)
        self.assertNotIn("sh -c", joined)
        self.assertIn('cat "$RUNNER_TEMP/claude-eli5-report.md"', self.workflow)
        self.assertIn('GH_TOKEN: ${{ github.token }}', self.workflow)
        self.assertIn('GITHUB_TOKEN: ${{ github.token }}', self.workflow)
        self.assertNotIn("${{ secrets.", self.workflow)


if __name__ == "__main__":
    unittest.main()
