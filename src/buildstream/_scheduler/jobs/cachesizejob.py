#  Copyright (C) 2018 Codethink Limited
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
#  Author:
#        Tristan Daniël Maat <tristan.maat@codethink.co.uk>
#
from .job import Job, JobStatus, ChildJob


class CacheSizeJob(Job):
    def __init__(self, *args, complete_cb, **kwargs):
        super().__init__(*args, **kwargs)
        self._complete_cb = complete_cb

        context = self._scheduler.context
        self._casquota = context.get_casquota()

    def parent_complete(self, status, result):
        if status == JobStatus.OK:
            self._casquota.set_cache_size(result)

        if self._complete_cb:
            self._complete_cb(status, result)

    def create_child_job(self):
        return ChildCacheSizeJob(self._scheduler.context._casquota)


class ChildCacheSizeJob(ChildJob):
    def __init__(self, casquota):
        super().__init__()
        self._casquota = casquota

    def child_process(self):
        return self._casquota.compute_cache_size()

    def child_process_data(self):
        return {}