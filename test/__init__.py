""" Common test routines. """

import os.path

from nattka.package import find_repository


def get_test_repo():
    conf_path = os.path.join(*__path__, 'conf')
    data_path = os.path.join(*__path__, 'data')
    return find_repository(data_path, conf_path)
