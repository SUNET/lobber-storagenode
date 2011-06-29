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

python_version = int(''.join((str(i) for i in sys.version_info[0:3])))
if not python_version >= 266:
    raise SystemExit("Python >=2.6.6 not found.  Make sure you.")

try:
    import twisted
except ImportError:
    raise SystemExit("twisted not found.  Make sure you "
                     "have installed the Twisted core package. "
                     "Try \"sudo apt-get install python-twisted-core\".")
try:
    import twisted.web
except ImportError:
    raise SystemExit("twisted.web not found.  Make sure you "
                     "have installed the Twisted web package. "
                     "Try \"sudo apt-get install python-twisted-web\".")
try:
    import stompservice
except ImportError:
    raise SystemExit("stompservice not found.  Make sure you "
                     "have installed the stompservice Python module. "
                     "Try \"sudo pip install stompservice\".")
try:
    import feedparser
except ImportError:
    raise SystemExit("feedparser not found.  Make sure you "
                     "have installed the feedparser Python module."
                     "Try \"sudo pip install feedparser\".")
try:
    import transmissionrpc
except ImportError:
    raise SystemExit("transmissionrpc not found.  Make sure you "
                     "have installed the transmissionrpc Python module."
                     "Try \"sudo pip install transmissionrpc\".")

try:
    import OpenSSL
except ImportError:
    raise SystemExit("OpenSSL not found.  Make sure you "
                     "have installed the pyopenssl Python module."
                     "Try \"sudo pip install pyopenssl\".")

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
    print 'Please edit %s/%s before starting the storage node.' % (dst_dir,filename)

def install_debian_start_script():
    filename = 'lobberstoragenode'
    src_dir = '%s/scripts' % os.getcwd()
    dst_dir = '/etc/init.d'
    try:
        os.stat('%s/%s' % (dst_dir, filename))
    except OSError:
        shutil.copyfile('%s/%s' % (src_dir,filename),
                        '%s/%s' % (dst_dir,filename))
        os.chmod('%s/%s' % (dst_dir,filename), 0755)
    print 'Start the storage node with, sudo %s/%s start.' % (dst_dir,filename)
    
def install_darwin_start_script():
    bash_file = 'lobberstoragenode'
    plist_file = 'com.lobber.storagenode.start.plist'
    src_dir = '%s/scripts' % os.getcwd()
    bash_dst_dir = '/usr/local/bin'
    plist_dst_dir = '/Library/LaunchDaemons'
    try:
        os.stat('%s/%s' % (bash_dst_dir, bash_file))
    except OSError:
        shutil.copyfile('%s/%s' % (src_dir,bash_file),
                        '%s/%s' % (bash_dst_dir,bash_file))
        os.chmod('%s/%s' % (bash_dst_dir,bash_file), 0755)
    shutil.copyfile('%s/%s' % (src_dir,plist_file),
                        '%s/%s' % (plist_dst_dir,plist_file))    
    print 'Start the storage node with, %s/%s start.' % (bash_dst_dir,bash_file)

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
    # Install os specific start script
    if sys.platform == 'linux2':
        install_debian_start_script()
    elif sys.platform == 'darwin':
        install_darwin_start_script()
