#
#  Copyright (C) 2018 Codethink Limited
#  Copyright (C) 2018 Bloomberg Finance LP
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library. If not, see <http://www.gnu.org/licenses/>.
#
#  Authors: Tristan Van Berkom <tristan.vanberkom@codethink.co.uk>
#           Tristan Maat <tristan.maat@codethink.co.uk>
#           Chandan Singh <csingh43@bloomberg.net>
#           Phillip Smyth <phillip.smyth@codethink.co.uk>
#           Jonathan Maw <jonathan.maw@codethink.co.uk>
#           Richard Maw <richard.maw@codethink.co.uk>
#           William Salmon <will.salmon@codethink.co.uk>
#           Angelos Evripiotis <jevripiotis@bloomberg.net>
#

import os
import stat
import pytest
import shutil
import subprocess
from ruamel.yaml.comments import CommentedSet
from tests.testutils import cli, create_repo, ALL_REPO_KINDS, wait_for_cache_granularity

from buildstream import _yaml
from buildstream._exceptions import ErrorDomain, LoadError, LoadErrorReason
from buildstream._workspaces import BST_WORKSPACE_FORMAT_VERSION

repo_kinds = [(kind) for kind in ALL_REPO_KINDS]

# Project directory
DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "project",
)


class WorkspaceCreater():
    def __init__(self, cli, tmpdir, datafiles, project_path=None):
        self.cli = cli
        self.tmpdir = tmpdir
        self.datafiles = datafiles

        if not project_path:
            project_path = os.path.join(datafiles.dirname, datafiles.basename)
        else:
            shutil.copytree(os.path.join(datafiles.dirname, datafiles.basename), project_path)

        self.project_path = project_path
        self.bin_files_path = os.path.join(project_path, 'files', 'bin-files')

        self.workspace_cmd = os.path.join(self.project_path, 'workspace_cmd')

    def create_workspace_element(self, kind, track, suffix='', workspace_dir=None,
                                 element_attrs=None):
        element_name = 'workspace-test-{}{}.bst'.format(kind, suffix)
        element_path = os.path.join(self.project_path, 'elements')
        if not workspace_dir:
            workspace_dir = os.path.join(self.workspace_cmd, element_name)
            if workspace_dir[-4:] == '.bst':
                workspace_dir = workspace_dir[:-4]

        # Create our repo object of the given source type with
        # the bin files, and then collect the initial ref.
        repo = create_repo(kind, str(self.tmpdir))
        ref = repo.create(self.bin_files_path)
        if track:
            ref = None

        # Write out our test target
        element = {
            'kind': 'import',
            'sources': [
                repo.source_config(ref=ref)
            ]
        }
        if element_attrs:
            element = {**element, **element_attrs}
        _yaml.dump(element,
                   os.path.join(element_path,
                                element_name))
        return element_name, element_path, workspace_dir

    def create_workspace_elements(self, kinds, track, suffixs=None, workspace_dir_usr=None,
                                  element_attrs=None):

        element_tuples = []

        if suffixs is None:
            suffixs = ['', ] * len(kinds)
        else:
            if len(suffixs) != len(kinds):
                raise "terable error"

        for suffix, kind in zip(suffixs, kinds):
            element_name, element_path, workspace_dir = \
                self.create_workspace_element(kind, track, suffix, workspace_dir_usr,
                                              element_attrs)

            # Assert that there is no reference, a track & fetch is needed
            state = self.cli.get_element_state(self.project_path, element_name)
            if track:
                assert state == 'no reference'
            else:
                assert state == 'fetch needed'
            element_tuples.append((element_name, workspace_dir))

        return element_tuples

    def open_workspaces(self, kinds, track, suffixs=None, workspace_dir=None,
                        element_attrs=None):

        element_tuples = self.create_workspace_elements(kinds, track, suffixs, workspace_dir,
                                                        element_attrs)
        os.makedirs(self.workspace_cmd, exist_ok=True)

        # Now open the workspace, this should have the effect of automatically
        # tracking & fetching the source from the repo.
        args = ['workspace', 'open']
        if track:
            args.append('--track')
        if workspace_dir is not None:
            assert len(element_tuples) == 1, "test logic error"
            _, workspace_dir = element_tuples[0]
            args.extend(['--directory', workspace_dir])

        args.extend([element_name for element_name, workspace_dir_suffix in element_tuples])
        result = self.cli.run(cwd=self.workspace_cmd, project=self.project_path, args=args)

        result.assert_success()

        for element_name, workspace_dir in element_tuples:
            # Assert that we are now buildable because the source is
            # now cached.
            assert self.cli.get_element_state(self.project_path, element_name) == 'buildable'

            # Check that the executable hello file is found in the workspace
            filename = os.path.join(workspace_dir, 'usr', 'bin', 'hello')
            assert os.path.exists(filename)

        return element_tuples


def open_workspace(cli, tmpdir, datafiles, kind, track, suffix='', workspace_dir=None,
                   project_path=None, element_attrs=None):
    workspace_object = WorkspaceCreater(cli, tmpdir, datafiles, project_path)
    workspaces = workspace_object.open_workspaces((kind, ), track, (suffix, ), workspace_dir,
                                                  element_attrs)
    assert len(workspaces) == 1
    element_name, workspace = workspaces[0]
    return element_name, workspace_object.project_path, workspace


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
def test_open(cli, tmpdir, datafiles, kind):
    open_workspace(cli, tmpdir, datafiles, kind, False)


@pytest.mark.datafiles(DATA_DIR)
def test_open_bzr_customize(cli, tmpdir, datafiles):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, "bzr", False)

    # Check that the .bzr dir exists
    bzrdir = os.path.join(workspace, ".bzr")
    assert(os.path.isdir(bzrdir))

    # Check that the correct origin branch is set
    element_config = _yaml.load(os.path.join(project, "elements", element_name))
    source_config = element_config['sources'][0]
    output = subprocess.check_output(["bzr", "info"], cwd=workspace)
    stripped_url = source_config['url'].lstrip("file:///")
    expected_output_str = ("checkout of branch: /{}/{}"
                           .format(stripped_url, source_config['track']))
    assert(expected_output_str in str(output))


@pytest.mark.datafiles(DATA_DIR)
def test_open_multi(cli, tmpdir, datafiles):

    workspace_object = WorkspaceCreater(cli, tmpdir, datafiles)
    workspaces = workspace_object.open_workspaces(repo_kinds, False)

    for (elname, workspace), kind in zip(workspaces, repo_kinds):
        assert kind in elname
        workspace_lsdir = os.listdir(workspace)
        if kind == 'git':
            assert('.git' in workspace_lsdir)
        elif kind == 'bzr':
            assert('.bzr' in workspace_lsdir)
        else:
            assert not ('.git' in workspace_lsdir)
            assert not ('.bzr' in workspace_lsdir)


@pytest.mark.datafiles(DATA_DIR)
def test_open_multi_unwritable(cli, tmpdir, datafiles):
    workspace_object = WorkspaceCreater(cli, tmpdir, datafiles)

    element_tuples = workspace_object.create_workspace_elements(repo_kinds, False, repo_kinds)
    os.makedirs(workspace_object.workspace_cmd, exist_ok=True)

    # Now open the workspace, this should have the effect of automatically
    # tracking & fetching the source from the repo.
    args = ['workspace', 'open']
    args.extend([element_name for element_name, workspace_dir_suffix in element_tuples])
    cli.configure({'workspacedir': workspace_object.workspace_cmd})

    cwdstat = os.stat(workspace_object.workspace_cmd)
    try:
        os.chmod(workspace_object.workspace_cmd, cwdstat.st_mode - stat.S_IWRITE)
        result = workspace_object.cli.run(project=workspace_object.project_path, args=args)
    finally:
        # Using this finally to make sure we always put thing back how they should be.
        os.chmod(workspace_object.workspace_cmd, cwdstat.st_mode)

    result.assert_main_error(ErrorDomain.STREAM, None)
    # Normally we avoid checking stderr in favour of using the mechine readable result.assert_main_error
    # But Tristan was very keen that the names of the elements left needing workspaces were present in the out put
    assert (" ".join([element_name for element_name, workspace_dir_suffix in element_tuples[1:]]) in result.stderr)


@pytest.mark.datafiles(DATA_DIR)
def test_open_multi_with_directory(cli, tmpdir, datafiles):
    workspace_object = WorkspaceCreater(cli, tmpdir, datafiles)

    element_tuples = workspace_object.create_workspace_elements(repo_kinds, False, repo_kinds)
    os.makedirs(workspace_object.workspace_cmd, exist_ok=True)

    # Now open the workspace, this should have the effect of automatically
    # tracking & fetching the source from the repo.
    args = ['workspace', 'open']
    args.extend(['--directory', 'any/dir/should/fail'])

    args.extend([element_name for element_name, workspace_dir_suffix in element_tuples])
    result = workspace_object.cli.run(cwd=workspace_object.workspace_cmd, project=workspace_object.project_path,
                                      args=args)

    result.assert_main_error(ErrorDomain.STREAM, 'directory-with-multiple-elements')


@pytest.mark.datafiles(DATA_DIR)
def test_open_defaultlocation(cli, tmpdir, datafiles):
    workspace_object = WorkspaceCreater(cli, tmpdir, datafiles)

    ((element_name, workspace_dir), ) = workspace_object.create_workspace_elements(['git'], False, ['git'])
    os.makedirs(workspace_object.workspace_cmd, exist_ok=True)

    # Now open the workspace, this should have the effect of automatically
    # tracking & fetching the source from the repo.
    args = ['workspace', 'open']
    args.append(element_name)

    # In the other tests we set the cmd to workspace_object.workspace_cmd with the optional
    # argument, cwd for the workspace_object.cli.run function. But hear we set the default
    # workspace location to workspace_object.workspace_cmd and run the cli.run function with
    # no cwd option so that it runs in the project directory.
    cli.configure({'workspacedir': workspace_object.workspace_cmd})
    result = workspace_object.cli.run(project=workspace_object.project_path,
                                      args=args)

    result.assert_success()

    assert cli.get_element_state(workspace_object.project_path, element_name) == 'buildable'

    # Check that the executable hello file is found in the workspace
    # even though the cli.run function was not run with cwd = workspace_object.workspace_cmd
    # the workspace should be created in there as we used the 'workspacedir' configuration
    # option.
    filename = os.path.join(workspace_dir, 'usr', 'bin', 'hello')
    assert os.path.exists(filename)


@pytest.mark.datafiles(DATA_DIR)
def test_open_defaultlocation_exists(cli, tmpdir, datafiles):
    workspace_object = WorkspaceCreater(cli, tmpdir, datafiles)

    ((element_name, workspace_dir), ) = workspace_object.create_workspace_elements(['git'], False, ['git'])
    os.makedirs(workspace_object.workspace_cmd, exist_ok=True)

    with open(workspace_dir, 'w') as fl:
        fl.write('foo')

    # Now open the workspace, this should have the effect of automatically
    # tracking & fetching the source from the repo.
    args = ['workspace', 'open']
    args.append(element_name)

    # In the other tests we set the cmd to workspace_object.workspace_cmd with the optional
    # argument, cwd for the workspace_object.cli.run function. But hear we set the default
    # workspace location to workspace_object.workspace_cmd and run the cli.run function with
    # no cwd option so that it runs in the project directory.
    cli.configure({'workspacedir': workspace_object.workspace_cmd})
    result = workspace_object.cli.run(project=workspace_object.project_path,
                                      args=args)

    result.assert_main_error(ErrorDomain.STREAM, 'bad-directory')


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
def test_open_track(cli, tmpdir, datafiles, kind):
    open_workspace(cli, tmpdir, datafiles, kind, True)


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
def test_open_force(cli, tmpdir, datafiles, kind):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, kind, False)

    # Close the workspace
    result = cli.run(project=project, args=[
        'workspace', 'close', element_name
    ])
    result.assert_success()

    # Assert the workspace dir still exists
    assert os.path.exists(workspace)

    # Now open the workspace again with --force, this should happily succeed
    result = cli.run(project=project, args=[
        'workspace', 'open', '--force', '--directory', workspace, element_name
    ])
    result.assert_success()


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
def test_open_force_open(cli, tmpdir, datafiles, kind):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, kind, False)

    # Assert the workspace dir exists
    assert os.path.exists(workspace)

    # Now open the workspace again with --force, this should happily succeed
    result = cli.run(project=project, args=[
        'workspace', 'open', '--force', '--directory', workspace, element_name
    ])
    result.assert_success()


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
def test_open_force_different_workspace(cli, tmpdir, datafiles, kind):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, kind, False, "-alpha")

    # Assert the workspace dir exists
    assert os.path.exists(workspace)

    hello_path = os.path.join(workspace, 'usr', 'bin', 'hello')
    hello1_path = os.path.join(workspace, 'usr', 'bin', 'hello1')

    tmpdir = os.path.join(str(tmpdir), "-beta")
    shutil.move(hello_path, hello1_path)
    element_name2, project2, workspace2 = open_workspace(cli, tmpdir, datafiles, kind, False, "-beta")

    # Assert the workspace dir exists
    assert os.path.exists(workspace2)

    # Assert that workspace 1 contains the modified file
    assert os.path.exists(hello1_path)

    # Assert that workspace 2 contains the unmodified file
    assert os.path.exists(os.path.join(workspace2, 'usr', 'bin', 'hello'))

    # Now open the workspace again with --force, this should happily succeed
    result = cli.run(project=project, args=[
        'workspace', 'open', '--force', '--directory', workspace, element_name2
    ])

    # Assert that the file in workspace 1 has been replaced
    # With the file from workspace 2
    assert os.path.exists(hello_path)
    assert not os.path.exists(hello1_path)

    result.assert_success()


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
def test_close(cli, tmpdir, datafiles, kind):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, kind, False)

    # Close the workspace
    result = cli.run(project=project, args=[
        'workspace', 'close', '--remove-dir', '--assume-yes', element_name
    ])
    result.assert_success()

    # Assert the workspace dir has been deleted
    assert not os.path.exists(workspace)


@pytest.mark.datafiles(DATA_DIR)
def test_close_external_after_move_project(cli, tmpdir, datafiles):
    workspace_dir = os.path.join(str(tmpdir), "workspace")
    project_path = os.path.join(str(tmpdir), 'initial_project')
    element_name, _, _ = open_workspace(cli, tmpdir, datafiles, 'git', False, "", workspace_dir, project_path)
    assert os.path.exists(workspace_dir)
    moved_dir = os.path.join(str(tmpdir), 'external_project')
    shutil.move(project_path, moved_dir)
    assert os.path.exists(moved_dir)

    # Close the workspace
    result = cli.run(project=moved_dir, args=[
        'workspace', 'close', '--remove-dir', '--assume-yes', element_name
    ])
    result.assert_success()

    # Assert the workspace dir has been deleted
    assert not os.path.exists(workspace_dir)


@pytest.mark.datafiles(DATA_DIR)
def test_close_internal_after_move_project(cli, tmpdir, datafiles):
    initial_dir = os.path.join(str(tmpdir), 'initial_project')
    initial_workspace = os.path.join(initial_dir, 'workspace')
    element_name, _, _ = open_workspace(cli, tmpdir, datafiles, 'git', False,
                                        workspace_dir=initial_workspace, project_path=initial_dir)
    moved_dir = os.path.join(str(tmpdir), 'internal_project')
    shutil.move(initial_dir, moved_dir)
    assert os.path.exists(moved_dir)

    # Close the workspace
    result = cli.run(project=moved_dir, args=[
        'workspace', 'close', '--remove-dir', '--assume-yes', element_name
    ])
    result.assert_success()

    # Assert the workspace dir has been deleted
    workspace = os.path.join(moved_dir, 'workspace')
    assert not os.path.exists(workspace)


@pytest.mark.datafiles(DATA_DIR)
def test_close_removed(cli, tmpdir, datafiles):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, 'git', False)

    # Remove it first, closing the workspace should work
    shutil.rmtree(workspace)

    # Close the workspace
    result = cli.run(project=project, args=[
        'workspace', 'close', element_name
    ])
    result.assert_success()

    # Assert the workspace dir has been deleted
    assert not os.path.exists(workspace)


@pytest.mark.datafiles(DATA_DIR)
def test_close_nonexistant_element(cli, tmpdir, datafiles):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, 'git', False)
    element_path = os.path.join(datafiles.dirname, datafiles.basename, 'elements', element_name)

    # First brutally remove the element.bst file, ensuring that
    # the element does not exist anymore in the project where
    # we want to close the workspace.
    os.remove(element_path)

    # Close the workspace
    result = cli.run(project=project, args=[
        'workspace', 'close', '--remove-dir', '--assume-yes', element_name
    ])
    result.assert_success()

    # Assert the workspace dir has been deleted
    assert not os.path.exists(workspace)


@pytest.mark.datafiles(DATA_DIR)
def test_close_multiple(cli, tmpdir, datafiles):
    tmpdir_alpha = os.path.join(str(tmpdir), 'alpha')
    tmpdir_beta = os.path.join(str(tmpdir), 'beta')
    alpha, project, workspace_alpha = open_workspace(
        cli, tmpdir_alpha, datafiles, 'git', False, suffix='-alpha')
    beta, project, workspace_beta = open_workspace(
        cli, tmpdir_beta, datafiles, 'git', False, suffix='-beta')

    # Close the workspaces
    result = cli.run(project=project, args=[
        'workspace', 'close', '--remove-dir', '--assume-yes', alpha, beta
    ])
    result.assert_success()

    # Assert the workspace dirs have been deleted
    assert not os.path.exists(workspace_alpha)
    assert not os.path.exists(workspace_beta)


@pytest.mark.datafiles(DATA_DIR)
def test_close_all(cli, tmpdir, datafiles):
    tmpdir_alpha = os.path.join(str(tmpdir), 'alpha')
    tmpdir_beta = os.path.join(str(tmpdir), 'beta')
    alpha, project, workspace_alpha = open_workspace(
        cli, tmpdir_alpha, datafiles, 'git', False, suffix='-alpha')
    beta, project, workspace_beta = open_workspace(
        cli, tmpdir_beta, datafiles, 'git', False, suffix='-beta')

    # Close the workspaces
    result = cli.run(project=project, args=[
        'workspace', 'close', '--remove-dir', '--assume-yes', '--all'
    ])
    result.assert_success()

    # Assert the workspace dirs have been deleted
    assert not os.path.exists(workspace_alpha)
    assert not os.path.exists(workspace_beta)


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("scenario", [
    {'assume_yes': True, 'no_prompt': True},
    {'assume_yes': False, 'no_prompt': True},
    # Covered by test_close: {'assume_yes': True, 'no_prompt': False},
    {'assume_yes': False, 'no_prompt': False},
])
def test_close_remove_dir_prompt(cli, tmpdir, datafiles, scenario):

    assume_yes, no_prompt = scenario['assume_yes'], scenario['no_prompt']

    element_name, project, workspace = open_workspace(
        cli, tmpdir, datafiles, 'git', track=False)

    workspace_args = [
        'workspace', 'close', '--remove-dir', element_name
    ]

    if assume_yes:
        workspace_args.append('--assume-yes')

    if no_prompt:
        cli.configure(
            {'prompt': {'really-workspace-close-remove-dir': 'yes'}}
        )

    result = cli.run(project=project, args=workspace_args)

    if assume_yes or no_prompt:
        result.assert_success()
        assert not os.path.exists(workspace)
    else:
        result.assert_main_error(
            ErrorDomain.APP,
            'aborted-destructive-non-interactive-not-confirmed')
        assert os.path.exists(workspace)


@pytest.mark.datafiles(DATA_DIR)
def test_reset(cli, tmpdir, datafiles):
    # Open the workspace
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, 'git', False)

    # Modify workspace
    shutil.rmtree(os.path.join(workspace, 'usr', 'bin'))
    os.makedirs(os.path.join(workspace, 'etc'))
    with open(os.path.join(workspace, 'etc', 'pony.conf'), 'w') as f:
        f.write("PONY='pink'")

    # Now reset the open workspace, this should have the
    # effect of reverting our changes.
    result = cli.run(project=project, args=[
        'workspace', 'reset', '--assume-yes', element_name
    ])
    result.assert_success()
    assert os.path.exists(os.path.join(workspace, 'usr', 'bin', 'hello'))
    assert not os.path.exists(os.path.join(workspace, 'etc', 'pony.conf'))


@pytest.mark.datafiles(DATA_DIR)
def test_reset_multiple(cli, tmpdir, datafiles):
    # Open the workspaces
    tmpdir_alpha = os.path.join(str(tmpdir), 'alpha')
    tmpdir_beta = os.path.join(str(tmpdir), 'beta')
    alpha, project, workspace_alpha = open_workspace(
        cli, tmpdir_alpha, datafiles, 'git', False, suffix='-alpha')
    beta, project, workspace_beta = open_workspace(
        cli, tmpdir_beta, datafiles, 'git', False, suffix='-beta')

    # Modify workspaces
    shutil.rmtree(os.path.join(workspace_alpha, 'usr', 'bin'))
    os.makedirs(os.path.join(workspace_beta, 'etc'))
    with open(os.path.join(workspace_beta, 'etc', 'pony.conf'), 'w') as f:
        f.write("PONY='pink'")

    # Now reset the open workspaces, this should have the
    # effect of reverting our changes.
    result = cli.run(project=project, args=[
        'workspace', 'reset', '--assume-yes', alpha, beta,
    ])
    result.assert_success()
    assert os.path.exists(os.path.join(workspace_alpha, 'usr', 'bin', 'hello'))
    assert not os.path.exists(os.path.join(workspace_beta, 'etc', 'pony.conf'))


@pytest.mark.datafiles(DATA_DIR)
def test_reset_all(cli, tmpdir, datafiles):
    # Open the workspaces
    tmpdir_alpha = os.path.join(str(tmpdir), 'alpha')
    tmpdir_beta = os.path.join(str(tmpdir), 'beta')
    alpha, project, workspace_alpha = open_workspace(
        cli, tmpdir_alpha, datafiles, 'git', False, suffix='-alpha')
    beta, project, workspace_beta = open_workspace(
        cli, tmpdir_beta, datafiles, 'git', False, suffix='-beta')

    # Modify workspaces
    shutil.rmtree(os.path.join(workspace_alpha, 'usr', 'bin'))
    os.makedirs(os.path.join(workspace_beta, 'etc'))
    with open(os.path.join(workspace_beta, 'etc', 'pony.conf'), 'w') as f:
        f.write("PONY='pink'")

    # Now reset the open workspace, this should have the
    # effect of reverting our changes.
    result = cli.run(project=project, args=[
        'workspace', 'reset', '--assume-yes', '--all'
    ])
    result.assert_success()
    assert os.path.exists(os.path.join(workspace_alpha, 'usr', 'bin', 'hello'))
    assert not os.path.exists(os.path.join(workspace_beta, 'etc', 'pony.conf'))


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("scenario", [
    {'assume_yes': True, 'no_prompt': True},
    {'assume_yes': False, 'no_prompt': True},
    # Covered by test_reset: {'assume_yes': True, 'no_prompt': False},
    {'assume_yes': False, 'no_prompt': False},
])
def test_reset_prompt(cli, tmpdir, datafiles, scenario):

    assume_yes, no_prompt = scenario['assume_yes'], scenario['no_prompt']

    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, 'git', False)

    # Make a change to revert.
    os.makedirs(os.path.join(workspace, 'etc'))
    with open(os.path.join(workspace, 'etc', 'pony.conf'), 'w') as f:
        f.write("PONY='pink'")

    workspace_args = [
        'workspace', 'reset', element_name
    ]

    if assume_yes:
        workspace_args.append('--assume-yes')

    if no_prompt:
        cli.configure(
            {'prompt': {'really-workspace-reset-hard': 'yes'}}
        )

    result = cli.run(project=project, args=workspace_args)

    if assume_yes or no_prompt:
        result.assert_success()
        assert not os.path.exists(os.path.join(workspace, 'etc', 'pony.conf'))
    else:
        result.assert_main_error(
            ErrorDomain.APP,
            'aborted-destructive-non-interactive-not-confirmed')
        assert os.path.exists(os.path.join(workspace, 'etc', 'pony.conf'))


@pytest.mark.datafiles(DATA_DIR)
def test_list(cli, tmpdir, datafiles):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, 'git', False)

    # Now list the workspaces
    result = cli.run(project=project, args=[
        'workspace', 'list'
    ])
    result.assert_success()

    loaded = _yaml.load_data(result.output)
    assert isinstance(loaded.get('workspaces'), list)
    workspaces = loaded['workspaces']
    assert len(workspaces) == 1

    space = workspaces[0]
    assert space['element'] == element_name
    assert space['directory'] == workspace


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
@pytest.mark.parametrize("strict", [("strict"), ("non-strict")])
def test_build(cli, tmpdir, datafiles, kind, strict):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, kind, False)
    checkout = os.path.join(str(tmpdir), 'checkout')

    # Modify workspace
    shutil.rmtree(os.path.join(workspace, 'usr', 'bin'))
    os.makedirs(os.path.join(workspace, 'etc'))
    with open(os.path.join(workspace, 'etc', 'pony.conf'), 'w') as f:
        f.write("PONY='pink'")

    # Configure strict mode
    strict_mode = True
    if strict != 'strict':
        strict_mode = False
    cli.configure({
        'projects': {
            'test': {
                'strict': strict_mode
            }
        }
    })

    # Build modified workspace
    assert cli.get_element_state(project, element_name) == 'buildable'
    assert cli.get_element_key(project, element_name) == "{:?<64}".format('')
    result = cli.run(project=project, args=['build', element_name])
    result.assert_success()
    assert cli.get_element_state(project, element_name) == 'cached'
    assert cli.get_element_key(project, element_name) != "{:?<64}".format('')

    # Checkout the result
    result = cli.run(project=project, args=[
        'checkout', element_name, checkout
    ])
    result.assert_success()

    # Check that the pony.conf from the modified workspace exists
    filename = os.path.join(checkout, 'etc', 'pony.conf')
    assert os.path.exists(filename)

    # Check that the original /usr/bin/hello is not in the checkout
    assert not os.path.exists(os.path.join(checkout, 'usr', 'bin', 'hello'))


@pytest.mark.datafiles(DATA_DIR)
def test_buildable_no_ref(cli, tmpdir, datafiles):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    element_name = 'workspace-test-no-ref.bst'
    element_path = os.path.join(project, 'elements')

    # Write out our test target without any source ref
    repo = create_repo('git', str(tmpdir))
    element = {
        'kind': 'import',
        'sources': [
            repo.source_config()
        ]
    }
    _yaml.dump(element,
               os.path.join(element_path,
                            element_name))

    # Assert that this target is not buildable when no workspace is associated.
    assert cli.get_element_state(project, element_name) == 'no reference'

    # Now open the workspace. We don't need to checkout the source though.
    workspace = os.path.join(str(tmpdir), 'workspace-no-ref')
    os.makedirs(workspace)
    args = ['workspace', 'open', '--no-checkout', '--directory', workspace, element_name]
    result = cli.run(project=project, args=args)
    result.assert_success()

    # Assert that the target is now buildable.
    assert cli.get_element_state(project, element_name) == 'buildable'


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("modification", [("addfile"), ("removefile"), ("modifyfile")])
@pytest.mark.parametrize("strict", [("strict"), ("non-strict")])
def test_detect_modifications(cli, tmpdir, datafiles, modification, strict):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, 'git', False)
    checkout = os.path.join(str(tmpdir), 'checkout')

    # Configure strict mode
    strict_mode = True
    if strict != 'strict':
        strict_mode = False
    cli.configure({
        'projects': {
            'test': {
                'strict': strict_mode
            }
        }
    })

    # Build clean workspace
    assert cli.get_element_state(project, element_name) == 'buildable'
    assert cli.get_element_key(project, element_name) == "{:?<64}".format('')
    result = cli.run(project=project, args=['build', element_name])
    result.assert_success()
    assert cli.get_element_state(project, element_name) == 'cached'
    assert cli.get_element_key(project, element_name) != "{:?<64}".format('')

    wait_for_cache_granularity()

    # Modify the workspace in various different ways, ensuring we
    # properly detect the changes.
    #
    if modification == 'addfile':
        os.makedirs(os.path.join(workspace, 'etc'))
        with open(os.path.join(workspace, 'etc', 'pony.conf'), 'w') as f:
            f.write("PONY='pink'")
    elif modification == 'removefile':
        os.remove(os.path.join(workspace, 'usr', 'bin', 'hello'))
    elif modification == 'modifyfile':
        with open(os.path.join(workspace, 'usr', 'bin', 'hello'), 'w') as f:
            f.write('cookie')
    else:
        # This cannot be reached
        assert 0

    # First assert that the state is properly detected
    assert cli.get_element_state(project, element_name) == 'buildable'
    assert cli.get_element_key(project, element_name) == "{:?<64}".format('')

    # Since there are different things going on at `bst build` time
    # than `bst show` time, we also want to build / checkout again,
    # and ensure that the result contains what we expect.
    result = cli.run(project=project, args=['build', element_name])
    result.assert_success()
    assert cli.get_element_state(project, element_name) == 'cached'
    assert cli.get_element_key(project, element_name) != "{:?<64}".format('')

    # Checkout the result
    result = cli.run(project=project, args=[
        'checkout', element_name, checkout
    ])
    result.assert_success()

    # Check the result for the changes we made
    #
    if modification == 'addfile':
        filename = os.path.join(checkout, 'etc', 'pony.conf')
        assert os.path.exists(filename)
    elif modification == 'removefile':
        assert not os.path.exists(os.path.join(checkout, 'usr', 'bin', 'hello'))
    elif modification == 'modifyfile':
        with open(os.path.join(workspace, 'usr', 'bin', 'hello'), 'r') as f:
            data = f.read()
            assert data == 'cookie'
    else:
        # This cannot be reached
        assert 0


# Ensure that various versions that should not be accepted raise a
# LoadError.INVALID_DATA
@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("workspace_cfg", [
    # Test loading a negative workspace version
    {"format-version": -1},
    # Test loading version 0 with two sources
    {
        "format-version": 0,
        "alpha.bst": {
            0: "/workspaces/bravo",
            1: "/workspaces/charlie",
        }
    },
    # Test loading a version with decimals
    {"format-version": 0.5},
    # Test loading a future version
    {"format-version": BST_WORKSPACE_FORMAT_VERSION + 1}
])
def test_list_unsupported_workspace(cli, tmpdir, datafiles, workspace_cfg):
    project = os.path.join(datafiles.dirname, datafiles.basename)
    bin_files_path = os.path.join(project, 'files', 'bin-files')
    element_path = os.path.join(project, 'elements')
    element_name = 'workspace-version.bst'
    os.makedirs(os.path.join(project, '.bst'))
    workspace_config_path = os.path.join(project, '.bst', 'workspaces.yml')

    _yaml.dump(workspace_cfg, workspace_config_path)

    result = cli.run(project=project, args=['workspace', 'list'])
    result.assert_main_error(ErrorDomain.LOAD, LoadErrorReason.INVALID_DATA)


# Ensure that various versions that should be accepted are parsed
# correctly.
@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("workspace_cfg,expected", [
    # Test loading version 0 without a dict
    ({
        "alpha.bst": "/workspaces/bravo"
    }, {
        "format-version": BST_WORKSPACE_FORMAT_VERSION,
        "workspaces": {
            "alpha.bst": {
                "prepared": False,
                "path": "/workspaces/bravo",
                "running_files": {}
            }
        }
    }),
    # Test loading version 0 with only one source
    ({
        "alpha.bst": {
            0: "/workspaces/bravo"
        }
    }, {
        "format-version": BST_WORKSPACE_FORMAT_VERSION,
        "workspaces": {
            "alpha.bst": {
                "prepared": False,
                "path": "/workspaces/bravo",
                "running_files": {}
            }
        }
    }),
    # Test loading version 1
    ({
        "format-version": 1,
        "workspaces": {
            "alpha.bst": {
                "path": "/workspaces/bravo"
            }
        }
    }, {
        "format-version": BST_WORKSPACE_FORMAT_VERSION,
        "workspaces": {
            "alpha.bst": {
                "prepared": False,
                "path": "/workspaces/bravo",
                "running_files": {}
            }
        }
    }),
    # Test loading version 2
    ({
        "format-version": 2,
        "workspaces": {
            "alpha.bst": {
                "path": "/workspaces/bravo",
                "last_successful": "some_key",
                "running_files": {
                    "beta.bst": ["some_file"]
                }
            }
        }
    }, {
        "format-version": BST_WORKSPACE_FORMAT_VERSION,
        "workspaces": {
            "alpha.bst": {
                "prepared": False,
                "path": "/workspaces/bravo",
                "last_successful": "some_key",
                "running_files": {
                    "beta.bst": ["some_file"]
                }
            }
        }
    }),
    # Test loading version 3
    ({
        "format-version": 3,
        "workspaces": {
            "alpha.bst": {
                "prepared": True,
                "path": "/workspaces/bravo",
                "running_files": {}
            }
        }
    }, {
        "format-version": BST_WORKSPACE_FORMAT_VERSION,
        "workspaces": {
            "alpha.bst": {
                "prepared": True,
                "path": "/workspaces/bravo",
                "running_files": {}
            }
        }
    })
])
def test_list_supported_workspace(cli, tmpdir, datafiles, workspace_cfg, expected):
    def parse_dict_as_yaml(node):
        tempfile = os.path.join(str(tmpdir), 'yaml_dump')
        _yaml.dump(node, tempfile)
        return _yaml.node_sanitize(_yaml.load(tempfile))

    project = os.path.join(datafiles.dirname, datafiles.basename)
    os.makedirs(os.path.join(project, '.bst'))
    workspace_config_path = os.path.join(project, '.bst', 'workspaces.yml')

    _yaml.dump(workspace_cfg, workspace_config_path)

    # Check that we can still read workspace config that is in old format
    result = cli.run(project=project, args=['workspace', 'list'])
    result.assert_success()

    loaded_config = _yaml.node_sanitize(_yaml.load(workspace_config_path))

    # Check that workspace config remains the same if no modifications
    # to workspaces were made
    assert loaded_config == parse_dict_as_yaml(workspace_cfg)

    # Create a test bst file
    bin_files_path = os.path.join(project, 'files', 'bin-files')
    element_path = os.path.join(project, 'elements')
    element_name = 'workspace-test.bst'
    workspace = os.path.join(str(tmpdir), 'workspace')

    # Create our repo object of the given source type with
    # the bin files, and then collect the initial ref.
    #
    repo = create_repo('git', str(tmpdir))
    ref = repo.create(bin_files_path)

    # Write out our test target
    element = {
        'kind': 'import',
        'sources': [
            repo.source_config(ref=ref)
        ]
    }
    _yaml.dump(element,
               os.path.join(element_path,
                            element_name))

    # Make a change to the workspaces file
    result = cli.run(project=project, args=['workspace', 'open', '--directory', workspace, element_name])
    result.assert_success()
    result = cli.run(
        project=project, args=['workspace', 'close', '--remove-dir', '--assume-yes', element_name])
    result.assert_success()

    # Check that workspace config is converted correctly if necessary
    loaded_config = _yaml.node_sanitize(_yaml.load(workspace_config_path))
    assert loaded_config == parse_dict_as_yaml(expected)


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("kind", repo_kinds)
def test_inconsitent_pipeline_message(cli, tmpdir, datafiles, kind):
    element_name, project, workspace = open_workspace(cli, tmpdir, datafiles, kind, False)

    shutil.rmtree(workspace)

    result = cli.run(project=project, args=[
        'build', element_name
    ])
    result.assert_main_error(ErrorDomain.PIPELINE, "inconsistent-pipeline-workspaced")


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.parametrize("strict", [("strict"), ("non-strict")])
def test_cache_key_workspace_in_dependencies(cli, tmpdir, datafiles, strict):
    checkout = os.path.join(str(tmpdir), 'checkout')
    element_name, project, workspace = open_workspace(cli, os.path.join(str(tmpdir), 'repo-a'),
                                                      datafiles, 'git', False)

    element_path = os.path.join(project, 'elements')
    back_dep_element_name = 'workspace-test-back-dep.bst'

    # Write out our test target
    element = {
        'kind': 'compose',
        'depends': [
            {
                'filename': element_name,
                'type': 'build'
            }
        ]
    }
    _yaml.dump(element,
               os.path.join(element_path,
                            back_dep_element_name))

    # Modify workspace
    shutil.rmtree(os.path.join(workspace, 'usr', 'bin'))
    os.makedirs(os.path.join(workspace, 'etc'))
    with open(os.path.join(workspace, 'etc', 'pony.conf'), 'w') as f:
        f.write("PONY='pink'")

    # Configure strict mode
    strict_mode = True
    if strict != 'strict':
        strict_mode = False
    cli.configure({
        'projects': {
            'test': {
                'strict': strict_mode
            }
        }
    })

    # Build artifact with dependency's modified workspace
    assert cli.get_element_state(project, element_name) == 'buildable'
    assert cli.get_element_key(project, element_name) == "{:?<64}".format('')
    assert cli.get_element_state(project, back_dep_element_name) == 'waiting'
    assert cli.get_element_key(project, back_dep_element_name) == "{:?<64}".format('')
    result = cli.run(project=project, args=['build', back_dep_element_name])
    result.assert_success()
    assert cli.get_element_state(project, element_name) == 'cached'
    assert cli.get_element_key(project, element_name) != "{:?<64}".format('')
    assert cli.get_element_state(project, back_dep_element_name) == 'cached'
    assert cli.get_element_key(project, back_dep_element_name) != "{:?<64}".format('')
    result = cli.run(project=project, args=['build', back_dep_element_name])
    result.assert_success()

    # Checkout the result
    result = cli.run(project=project, args=[
        'checkout', back_dep_element_name, checkout
    ])
    result.assert_success()

    # Check that the pony.conf from the modified workspace exists
    filename = os.path.join(checkout, 'etc', 'pony.conf')
    assert os.path.exists(filename)

    # Check that the original /usr/bin/hello is not in the checkout
    assert not os.path.exists(os.path.join(checkout, 'usr', 'bin', 'hello'))


@pytest.mark.datafiles(DATA_DIR)
def test_multiple_failed_builds(cli, tmpdir, datafiles):
    element_config = {
        "kind": "manual",
        "config": {
            "configure-commands": [
                "unknown_command_that_will_fail"
            ]
        }
    }
    element_name, project, _ = open_workspace(cli, tmpdir, datafiles,
                                              "git", False, element_attrs=element_config)

    for _ in range(2):
        result = cli.run(project=project, args=["build", element_name])
        assert "BUG" not in result.stderr
        assert cli.get_element_state(project, element_name) != "cached"
