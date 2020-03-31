""" Common test routines. """

from pathlib import Path

from nattka.package import find_repository


def get_test_repo(path: Path = Path(__file__).parent):
    conf_path = path / 'conf'
    data_path = path / 'data'
    return find_repository(str(data_path), str(conf_path))
