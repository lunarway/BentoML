# Copyright 2019 Atalaya Tech, Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys

from gunicorn.app.base import BaseApplication
from gunicorn.six import iteritems

from bentoml import config
from bentoml.archive import load
from bentoml.server import BentoAPIServer
from bentoml.server.bento_api_server import Router
from bentoml.server.utils import get_bento_recommend_gunicorn_worker_count
from bentoml.utils.usage_stats import track_server
from gunicorn import util
from flask import Response
from prometheus_client import generate_latest, CollectorRegistry, multiprocess, CONTENT_TYPE_LATEST


class GunicornRouter(Router):

    @classmethod
    def metrics_view_func(cls):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        data = generate_latest(registry)
        return Response(data, mimetype=CONTENT_TYPE_LATEST)


class GunicornBentoServer(BaseApplication):  # pylint: disable=abstract-method
    """
    A custom Gunicorn application.

    Usage::

        >>> from bentoml.server.gunicorn_server import GunicornBentoServer
        >>>
        >>> gunicorn_app = GunicornBentoServer(bento_archive_path, port=5000)
        >>> gunicorn_app.run()

    :param app: a Flask app, flask.Flask.app
    :param port: the port you want to run gunicorn server on
    :param workers: number of worker processes
    """

    def __init__(
        self, bento_archive_path, port=None, num_of_workers=None, timeout=None
    ):
        self.bento_archive_path = bento_archive_path
        self.port = port or config("apiserver").getint("default_port")
        self.num_of_workers = (
            num_of_workers
            or config("apiserver").getint("default_gunicorn_workers_count")
            or get_bento_recommend_gunicorn_worker_count()
        )
        self.timeout = timeout or config("apiserver").getint("default_timeout")

        self.options = {
            "workers": self.num_of_workers,
            "bind": "%s:%s" % ("0.0.0.0", self.port),
            "timeout": self.timeout,
        }

        super(GunicornBentoServer, self).__init__()

    def get_config_from_module_name(self, module_name):
        return vars(util.import_module(module_name))

    def load_config_from_module_name(self, module_name):
        """
        Loads the configuration file: the file is a python file, otherwise raise an RuntimeError
        Exception or stop the process if the configuration file contains a syntax error.
        """

        cfg = self.get_config_from_module_name(module_name)

        for k, v in cfg.items():
            # Ignore unknown names
            if k not in self.cfg.settings:
                continue
            try:
                self.cfg.set(k.lower(), v)
            except:
                print("Invalid value for %s: %s\n" % (k, v), file=sys.stderr)
                sys.stderr.flush()
                raise

        return cfg

    def load_config(self):
        self.load_config_from_module_name('bentoml.server.gunicorn_config')

        gunicorn_config = dict(
            [
                (key, value)
                for key, value in iteritems(self.options)
                if key in self.cfg.settings and value is not None
            ]
        )
        for key, value in iteritems(gunicorn_config):
            self.cfg.set(key.lower(), value)

    def load(self):
        bento_service = load(self.bento_archive_path)
        api_server = BentoAPIServer(bento_service, router=GunicornRouter(), port=self.port)
        return api_server.app

    def run(self):
        track_server('gunicorn', {"number_of_workers": self.num_of_workers})
        super(GunicornBentoServer, self).run()
