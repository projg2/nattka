""" Common test routines. """

import os.path

import pkgcore.config


def get_test_repo():
    data_path = os.path.join(*__path__, 'data')
    c = pkgcore.config.load_config()
    domain = c.get_default('domain')
    return domain.find_repo(data_path, config=c, configure=False)
