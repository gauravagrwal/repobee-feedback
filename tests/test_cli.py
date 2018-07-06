import os
import sys
import string
import tempfile
from unittest.mock import MagicMock, PropertyMock
from contextlib import contextmanager
import pytest

import gits_pet
from gits_pet import cli
from gits_pet import git
from gits_pet import tuples

USER = 'slarse'
ORG_NAME = 'test-org'
GITHUB_BASE_URL = 'https://some_enterprise_host/api/v3'
STUDENTS = tuple(string.ascii_lowercase)
ISSUE_PATH = 'some/issue/path'
ISSUE = tuples.Issue(title="Best title", body="This is the body of the issue.")

BASE_ARGS = ['-g', GITHUB_BASE_URL, '-o', ORG_NAME]

GENERATE_REPO_URL = lambda repo_name:\
        "https://some_enterprise_host/{}/{}".format(ORG_NAME, repo_name)

REPO_NAMES = ('week-1', 'week-2')
BASE_PUSH_ARGS = ['-u', USER, '-mn', *REPO_NAMES]
COMPLETE_PUSH_ARGS = [*BASE_ARGS, *BASE_PUSH_ARGS]


@pytest.fixture(autouse=True)
def api_instance_mock(mocker):
    instance_mock = MagicMock(spec=gits_pet.github_api.GitHubAPI)
    instance_mock.get_repo_urls.side_effect = lambda repo_names: list(map(GENERATE_REPO_URL, repo_names))
    return instance_mock


@pytest.fixture(autouse=True)
def api_class_mock(mocker, api_instance_mock):
    class_mock = mocker.patch('gits_pet.github_api.GitHubAPI', autospec=True)
    class_mock.return_value = api_instance_mock
    return class_mock


@pytest.fixture(autouse=True)
def admin_mock(mocker):
    return mocker.patch('gits_pet.admin', autospec=True)


@pytest.fixture(autouse=True)
def isfile_mock(request, mocker):
    if 'noisfilemock' in request.keywords:
        return
    isfile = lambda path: path != cli.DEFAULT_CONFIG_FILE
    return mocker.patch('os.path.isfile', autospec=True, side_effect=isfile)


@pytest.fixture()
def read_issue_mock(mocker):
    """Mock util.read_issue that only accepts ISSUE_PATH as a valid file."""

    def read_issue(path):
        if path != ISSUE_PATH:
            raise ValueError("not a file")
        return ISSUE

    return mocker.patch(
        'gits_pet.util.read_issue', autospec=True, side_effect=read_issue)


@contextmanager
def _students_file(populate: bool = True):
    """A contextmanager that yields a student file. The file is populated
    with the STUDENTS tuple by default, with one element on each line.

    Args:
        populate: If true, the file is populated with the students in the
        STUDENTS tuple.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        with tempfile.NamedTemporaryFile(
                mode="w",
                encoding=sys.getdefaultencoding(),
                dir=tmpdir,
                delete=False) as file:
            if populate:
                file.writelines(
                    "{}{}".format(student, os.linesep) for student in STUDENTS)
                file.flush()
        yield file


@pytest.fixture()
def students_file():
    with _students_file() as file:
        yield file


@pytest.fixture()
def empty_students_file():
    with _students_file(populate=False) as file:
        yield file


class TestStudentParsing:
    """Tests for the parsers that use the `--students` and `--students-file` arguments.

    Currently these are:

        cli.SETUP_PARSER
        cli.UPDATE_PARSER
        cli.OPEN_ISSUE_PARSER
        cli.CLOSE_ISSUE_PARSER
    """

    STUDENT_PARSING_PARAMS = ('parser, extra_args', [
        (cli.SETUP_PARSER, BASE_PUSH_ARGS),
        (cli.UPDATE_PARSER, BASE_PUSH_ARGS),
        (cli.CLOSE_ISSUE_PARSER, ['-mn', *REPO_NAMES, '-r', 'some-regex']),
        (cli.OPEN_ISSUE_PARSER, ['-mn', *REPO_NAMES, '-i', ISSUE_PATH]),
    ])
    STUDENT_PARSING_IDS = [
        "|".join([str(val) for val in line])
        for line in STUDENT_PARSING_PARAMS[1]
    ]

    @pytest.mark.parametrize(*STUDENT_PARSING_PARAMS, ids=STUDENT_PARSING_IDS)
    def test_parser_listing_students(self, read_issue_mock, parser,
                                     extra_args):
        """Test that the different subparsers parse arguments corectly when
        students are listed directly on the command line.
        """
        sys_args = [parser, *BASE_ARGS, '-s', *STUDENTS, *extra_args]

        parsed_args, _ = cli.parse_args(sys_args)

        assert parsed_args.students == list(STUDENTS)

    @pytest.mark.parametrize(*STUDENT_PARSING_PARAMS, ids=STUDENT_PARSING_IDS)
    def test_parser_student_file(self, students_file, read_issue_mock, parser,
                                 extra_args):
        """Test that the different subparsers read students correctly from
        file.
        """
        sys_args = [parser, *BASE_ARGS, '-sf', students_file.name, *extra_args]

        parsed_args, _ = cli.parse_args(sys_args)

        assert parsed_args.students == list(STUDENTS)

    @pytest.mark.parametrize(*STUDENT_PARSING_PARAMS, ids=STUDENT_PARSING_IDS)
    def test_student_parsers_raise_on_empty_student_file(
            self, read_issue_mock, empty_students_file, parser, extra_args):
        """Test that an error is raised if the student file is empty."""
        sys_args = [
            parser, *BASE_ARGS, '-sf', empty_students_file.name, *extra_args
        ]

        with pytest.raises(cli.FileError) as exc_info:
            cli.parse_args(sys_args)

        assert "is empty" in str(exc_info)

    @pytest.mark.parametrize(*STUDENT_PARSING_PARAMS, ids=STUDENT_PARSING_IDS)
    def test_parsers_raise_if_both_file_and_listing(
            read_issue_mock, students_file, parser, extra_args):
        """Test that the student subparsers raise if students are both listed
        on the CLI, and a file is specified.
        """
        sys_args = [
            parser, *BASE_ARGS, '-sf', students_file.name, '-s', *STUDENTS,
            *extra_args
        ]

        with pytest.raises(SystemExit) as exc_info:
            cli.parse_args(sys_args)


def assert_base_push_args(parsed_args, api):
    """Assert that the parsed arguments are consistend with the
    BASE_PUSH_ARGS.
    """
    assert parsed_args.org_name == ORG_NAME
    assert parsed_args.github_base_url == GITHUB_BASE_URL
    assert parsed_args.user == USER
    assert parsed_args.master_repo_names == list(REPO_NAMES)
    assert parsed_args.master_repo_urls == list(
        map(GENERATE_REPO_URL, REPO_NAMES))
    api.assert_called_once_with(GITHUB_BASE_URL, git.OAUTH_TOKEN, ORG_NAME)


@pytest.fixture
def config_mock(mocker, isfile_mock, students_file):
    with tempfile.TemporaryDirectory() as tmpdir:
        with tempfile.NamedTemporaryFile(
                mode="w",
                encoding=sys.getdefaultencoding(),
                dir=tmpdir,
                delete=False) as file:
            isfile = isfile_mock.side_effect
            isfile_mock.side_effect = lambda path: isfile(path) or path == file.name
            file.write(
                os.linesep.join([
                    "[DEFAULT]",
                    "github_base_url = {}".format(GITHUB_BASE_URL),
                    "user = {}".format(USER), "org_name = {}".format(ORG_NAME),
                    "students_file = {}".format(students_file.name)
                ]))
            file.flush()

        read_config = gits_pet.cli._read_config
        mocker.patch(
            'gits_pet.cli._read_config',
            side_effect=lambda _: read_config(file.name))
        yield file


def assert_config_args(parser, parsed_args):
    """Asserts that the configured arguments are correct."""
    assert parsed_args.github_base_url == GITHUB_BASE_URL
    assert parsed_args.students == list(STUDENTS)
    assert parsed_args.org_name == ORG_NAME

    if parser in [cli.SETUP_PARSER, cli.UPDATE_PARSER]:
        assert parsed_args.user == USER


class TestConfig:
    """Tests that the configuration works properly."""

    @pytest.mark.parametrize(
        'parser, extra_args',
        [(cli.SETUP_PARSER, ['-mn', *REPO_NAMES]),
         (cli.UPDATE_PARSER, ['-mn', *REPO_NAMES]),
         (cli.OPEN_ISSUE_PARSER, ['-mn', *REPO_NAMES, '-i', ISSUE_PATH])])
    def test_full_config(self, config_mock, read_issue_mock, parser,
                         extra_args):
        """Test that a fully configured file works. This means that
        github_base_url, org_name, user and student list are all
        preconfigured.
        """
        sys_args = [parser, *extra_args]

        parsed_args, _ = cli.parse_args(sys_args)
        assert_config_args(parser, parsed_args)

    # TODO test that not having github_base_url, org_name, user or students_file
    # in the config makes them required!


class TestSetupAndUpdateParsers:
    """Tests SETUP_PARSER and UPDATE_PARSER."""

    @pytest.mark.parametrize('parser', [cli.SETUP_PARSER, cli.UPDATE_PARSER])
    def test_happy_path(self, api_class_mock, parser):
        """Tests standard operation of the parsers."""
        sys_args = [parser, *COMPLETE_PUSH_ARGS, '-s', *STUDENTS]

        parsed_args, _ = cli.parse_args(sys_args)

        assert_base_push_args(parsed_args, api_class_mock)