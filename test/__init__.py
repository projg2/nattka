""" Common test routines. """

import os.path

from nattka.package import find_repository


assert len(__path__) == 1


def get_test_repo(path: str = __path__[0]):
    conf_path = os.path.join(path, 'conf')
    data_path = os.path.join(path, 'data')
    return find_repository(data_path, conf_path)
