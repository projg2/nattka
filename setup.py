#!/usr/bin/env python
# (c) 2020 Michał Górny
# 2-clause BSD license

from setuptools import setup

from nattka import __version__


setup(
    name='nattka',
    version=__version__,
    description='A New Arch Tester Toolkit (open source replacement '
                'for stable-bot)',

    author='Michał Górny',
    author_email='mgorny@gentoo.org',
    license='BSD',
    url='http://github.com/mgorny/nattka',

    packages=['nattka'],
    entry_points={
        'console_scripts': [
            'nattka=nattka.cli:setuptools_main',
        ],
    },

    classifiers=[
        'Development Status :: 3 - Alpha',
        'Environment :: Console',
        'Environment :: No Input/Output (Daemon)',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: BSD License',
        'Operating System :: POSIX',
        'Programming Language :: Python :: 3 :: Only',
        'Topic :: Software Development :: Testing',
    ]
)
