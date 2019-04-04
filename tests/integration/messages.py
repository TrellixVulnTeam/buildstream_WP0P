#
#  Copyright (C) 2018 Codethink Limited
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
#  Authors: Tristan Maat <tristan.maat@codethink.co.uk>
#

import os
import pytest

from buildstream2 import _yaml
from buildstream2._exceptions import ErrorDomain
from buildstream2.testing import cli_integration as cli
from tests.testutils.site import HAVE_SANDBOX


pytestmark = pytest.mark.integration


# Project directory
DATA_DIR = os.path.join(
    os.path.dirname(os.path.realpath(__file__)),
    "project",
)


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason='Only available with a functioning sandbox')
def test_disable_message_lines(cli, datafiles):
    project = str(datafiles)
    element_path = os.path.join(project, 'elements')
    element_name = 'message.bst'

    element = {
        'kind': 'manual',
        'depends': [{
            'filename': 'base.bst'
        }],
        'config': {
            'build-commands':
            ['echo "Silly message"'],
            'strip-commands': []
        }
    }

    os.makedirs(os.path.dirname(os.path.join(element_path, element_name)), exist_ok=True)
    _yaml.dump(element, os.path.join(element_path, element_name))

    # First we check that we get the "Silly message"
    result = cli.run(project=project, args=["build", element_name])
    result.assert_success()
    assert 'echo "Silly message"' in result.stderr

    # Let's now build it again, but with --message-lines 0
    cli.remove_artifact_from_cache(project, element_name)
    result = cli.run(project=project, args=["--message-lines", "0",
                                            "build", element_name])
    result.assert_success()
    assert "Message contains " not in result.stderr


@pytest.mark.datafiles(DATA_DIR)
@pytest.mark.skipif(not HAVE_SANDBOX, reason='Only available with a functioning sandbox')
def test_disable_error_lines(cli, datafiles):
    project = str(datafiles)
    element_path = os.path.join(project, 'elements')
    element_name = 'message.bst'

    element = {
        'kind': 'manual',
        'depends': [{
            'filename': 'base.bst'
        }],
        'config': {
            'build-commands':
            ['This is a syntax error > >'],
            'strip-commands': []
        }
    }

    os.makedirs(os.path.dirname(os.path.join(element_path, element_name)), exist_ok=True)
    _yaml.dump(element, os.path.join(element_path, element_name))

    # First we check that we get the syntax error
    result = cli.run(project=project, args=["--error-lines", "0",
                                            "build", element_name])
    result.assert_main_error(ErrorDomain.STREAM, None)
    assert "This is a syntax error" in result.stderr

    # Let's now build it again, but with --error-lines 0
    cli.remove_artifact_from_cache(project, element_name)
    result = cli.run(project=project, args=["--error-lines", "0",
                                            "build", element_name])
    result.assert_main_error(ErrorDomain.STREAM, None)
    assert "Printing the last" not in result.stderr