import argparse
import sys
import pathlib
import random
import builtins
from unittest import mock

import pytest
from _repobee import plugin
import repobee_plug as plug

from repobee_feedback import feedback

MASTER_REPO_NAMES = ("task-1", "task-2")
STUDENT_TEAMS = tuple(
    [
        plug.Team(members=members)
        for members in (["slarse"], ["glassey"], ["grundb", "glennol"])
    ]
)
STUDENT_TEAM_NAMES = tuple(map(str, STUDENT_TEAMS))

PASS_ISSUE = plug.Issue(title="Pass", body="Well done!\nAbsolutely flawless!")
KOMP_ISSUE = plug.Issue(
    title="Komplettering", body="Not perfect, you need to fix this."
)
FAIL_ISSUE = plug.Issue(title="Fail", body="Unfortunately, there are severe errors.")
ISSUES = (PASS_ISSUE, KOMP_ISSUE, FAIL_ISSUE)

random.seed(512)


def _write_issue(issue: plug.Issue, path: pathlib.Path):
    text = "{}\n{}".format(issue.title, issue.body)
    path.write_text(text, encoding=sys.getdefaultencoding())


def test_register():
    """Just test that there is no crash"""
    plugin.register_plugins([feedback])


@pytest.fixture
def parsed_args(tmp_path):
    return argparse.Namespace(
        students=list(STUDENT_TEAMS),
        master_repo_names=list(MASTER_REPO_NAMES),
        batch_mode=True,
        issues_dir=str(tmp_path),
    )


@pytest.fixture
def api_mock():
    return mock.MagicMock(spec=plug.API)


@pytest.fixture
def with_issues(tmp_path):
    """Create issue files in a temporary directory and return a list of (team,
    issue) tuples.
    """
    repo_names = plug.generate_repo_names(STUDENT_TEAM_NAMES, MASTER_REPO_NAMES)
    existing_issues = []
    for repo_name in repo_names:
        issue_file = tmp_path / "{}.md".format(repo_name)
        issue = random.choice(ISSUES)
        _write_issue(issue, issue_file)
        existing_issues.append((repo_name, issue))
    return existing_issues


class TestFeedbackCommand:
    def test_init(self):
        cmd = feedback.FeedbackCommand()
        assert isinstance(cmd, plug.Plugin)

    def test_create_extension_command(self):
        cmd = feedback.FeedbackCommand()
        ext = cmd.create_extension_command()

        assert isinstance(ext.parser, argparse.ArgumentParser)
        assert ext.name == "issue-feedback"
        assert ext.callback == feedback.callback
        assert ext.requires_api
        assert ext.requires_base_parsers


class TestCallback:
    """Tests for the primary callback."""

    def test_opens_issues_from_issues_dir(self, with_issues, parsed_args, api_mock):
        """Test that the callback calls the API.open_issue for the expected
        repos and issues, when the issues all exist and are well formed.
        """
        expected_calls = [
            mock.call(issue.title, issue.body, [repo_name])
            for repo_name, issue in with_issues
        ]

        feedback.callback(args=parsed_args, api=api_mock)

        api_mock.open_issue.assert_has_calls(expected_calls, any_order=True)

    def test_aborts_if_issue_is_missing(
        self, with_issues, parsed_args, api_mock, tmp_path
    ):
        """Test that the callback exits with a plug.PlugError if any of the
        expected issues is not found.
        """
        repo_without_issue = plug.generate_repo_name(
            STUDENT_TEAM_NAMES[-1], MASTER_REPO_NAMES[0]
        )
        missing_file = tmp_path / "{}.md".format(repo_without_issue)
        missing_file.unlink()

        with pytest.raises(plug.PlugError) as exc_info:
            feedback.callback(args=parsed_args, api=api_mock)

        assert str(missing_file) in str(exc_info.value)
        assert not api_mock.open_issue.called

    def test_opens_nothing_if_open_prompt_returns_false(
        self, with_issues, parsed_args, api_mock
    ):
        """Test that the callback does not attempt to open any issues if the
        'may I open' prompt returns false.
        """
        args_dict = vars(parsed_args)
        args_dict["batch_mode"] = False
        parsed_args_interactive = argparse.Namespace(**args_dict)

        with mock.patch(
            "builtins.input", return_value="n", autospec=True
        ) as input_mock:
            feedback.callback(args=parsed_args_interactive, api=api_mock)

        assert not api_mock.open_issue.called
