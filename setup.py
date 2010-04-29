#!/usr/bin/env python

'''setup.py for lobber storage node.

This is an extension of the Twisted finger tutorial demonstrating how
to package the Twisted application as an installable Python package and
twistd plugin (consider it "Step 12" if you like).

Uses twisted.python.dist.setup() to make this package installable as
a Twisted Application Plugin.

After installation the application should be manageable as a twistd
command.

For example, to start it in the foreground enter:
$ twistd -n finger

To view the options for finger enter:
$ twistd finger --help
'''

__author__ = 'Leif Johansson'


import sys

try:
    import twisted
except ImportError:
    raise SystemExit("twisted not found.  Make sure you "
                     "have installed the Twisted core package.")

from distutils.core import setup

def refresh_plugin_cache():
    from twisted.plugin import IPlugin, getPlugins
    list(getPlugins(IPlugin))

if __name__ == '__main__':
    
    if sys.version_info[:2] >= (2, 4):
        extraMeta = dict(
            classifiers=[
                "Development Status :: 4 - Beta",
                "Environment :: No Input/Output (Daemon)",
                "Programming Language :: Python",
            ])
    else:
        extraMeta = {}

    setup(
        name="lobberstoragenode",
        version='0.4',
        package_dir={'': 'src'},
        description="Lobber Storage Node",
        author=__author__,
        author_email="leifj@sunet.se",
        url="http://lobber.se",
        requires=['stompservice','feedparser'],
        packages=[
            "lobber",
            "twisted.plugins",
        ],
        package_data={
            'twisted': ['plugins/lobberstoragenode_plugin.py'],
        },
        **extraMeta)
    
    refresh_plugin_cache()
