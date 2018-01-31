#!/usr/bin/env python3
#
#  Copyright (C) 2017 Codethink Limited
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU Lesser General Public
#  License as published by the Free Software Foundation; either
#  version 2 of the License, or (at your option) any later version.
#
#  This library is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	 See the GNU
#  Lesser General Public License for more details.
#
#  You should have received a copy of the GNU Lesser General Public
#  License along with this library. If not, see <http://www.gnu.org/licenses/>.
#
#  Authors:
#        Tristan Maat <tristan.maat@codethink.co.uk>

import os

from .._artifactcache.tarcache import TarCache
from .._exceptions import PlatformError
from ..sandbox import SandboxChroot, SandboxUserChroot

from . import Platform


class Unix(Platform):

    def __init__(self, context, project):

        super().__init__(context, project)
        self._artifact_cache = TarCache(context)

        # Not necessarily 100% reliable, but we want to fail early.
        # if os.geteuid() != 0:
        #     raise PlatformError("Root privileges are required to run without bubblewrap.")

    @property
    def artifactcache(self):
        return self._artifact_cache

    def create_sandbox(self, *args, **kwargs):
        # We can optionally create a SandboxUserChroot
        return SandboxUserChroot(*args, **kwargs)
        # return SandboxChroot(*args, **kwargs)
