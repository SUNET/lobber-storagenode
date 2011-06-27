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
import os
import shutil

try:
    import twisted
except ImportError:
    raise SystemExit("twisted not found.  Make sure you "
                     "have installed the Twisted core package.")

from distutils.core import setup

def install_conf():
    filename = 'config'
    src_dir = '%s/conf' % os.getcwd()
    dst_dir = '/etc/lobberstoragenode'
    try:
        os.mkdir(dst_dir)
    except OSError:
        pass
    try:
        os.stat('%s/%s' % (dst_dir, filename))
    except OSError:
        shutil.copyfile('%s/%s' % (src_dir,filename), 
                        '%s/%s' % (dst_dir,filename))
                        
def install_start_script():
    filename = 'lobberstoragenode'
    src_dir = '%s/scripts' % os.getcwd()
    dst_dir = '/etc/init.d'
    try:
        os.stat('%s/%s' % (dst_dir, filename))
    except OSError:
        shutil.copyfile('%s/%s' % (src_dir,filename),
                        '%s/%s' % (dst_dir,filename))
        os.chmod('%s/%s' % (dst_dir,filename), 0755)

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
        version='0.6',
        package_dir={'': 'src'},
        description="Lobber Storage Node",
        author=__author__,
        author_email="leifj@sunet.se",
        url="https://portal.nordu.net/display/LOBBER/Lobber",
        requires=['stompservice','feedparser','transmissionrpc'],
        packages=[
            "lobber",
            "twisted.plugins",
        ],
        package_data={
            'twisted': ['plugins/lobberstoragenode_plugin.py'],
        },
        **extraMeta)
    
    refresh_plugin_cache()
    install_conf()
    install_start_script()
