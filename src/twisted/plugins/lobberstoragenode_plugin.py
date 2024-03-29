import os
import sys
from urllib import splitnport
from urlparse import urlparse

from twisted.application import service
from twisted.python import log
from twisted.application import internet
from twisted.python import usage
from twisted.internet import task, reactor
from twisted.plugin import IPlugin
from twisted.web import server
from zope.interface.declarations import implements

from lobber.proxy import ReverseProxyTLSResource
from lobber.storagenode import TorrentDownloader, LobberClient, TransmissionClient, TransmissionSweeper, DropboxWatcher

class Options(usage.Options):

    optParameters = [
        ['announceUrl', 'a', None,
         "Announce URL (tracker) to use for new torrents"],
        ['acl', 'A', None,
         "Access Control List to apply to new torrents"],
        ['dropbox', 'b', None,
         "A directory to watch for new content"],
        ['torrentDir', 'd', 'torrents',
         "The directory where to store torrents"],
        ['transmissionDownloadsDir', 'D', '/var/lib/transmission-daemon/downloads',
         "The downloads directory for transmission"],
        ['lobberHost', 'h', None,
         "The host running both STOMP and https for lobber"],
        ['lobberKey', 'k', None,
         "The Lobber application key to use"],
        # -n in optFlags
        ['trackerProxyTrackerUrl', 'p', None,
         "Enable tracker proxying for given https tracker (HOST[:PORT])"],
        ['trackerProxyListenOn', 'P', 'localhost:8080',
         "Adress to bind the tracker proxy to"],
        ['removeLimit', 'r', 0,
         "Remove torrent and data when this many other storage-nodes have the data (0=never remove)"],
         # -R in optFlags
        ['stompUrl', 'S', 'stomp://localhost:61613',
         "The STOMP protocol URL to use for notifications"],
        ['transmissionRpc', 'T', 'http://transmission:transmission@localhost:9091',
         "The RPC URL for transmission"]
    ]
    
    optFlags = [
        ['standardNotifications', 'n',
         "Add standard notificiation destinations"],
        ['register', 'R',
         "Register new torrents with lobber"],
        ['keepData','B',
         "Serve data from the dropbox instead of moving it to the transmission data directory."]
    ]
    
    def parseArgs(self,*args):
        self.urls = []
        self.destinations = []
        for x in args:
            if x.startswith("/"):
                self.destinations.append(x)
            else:
                self.urls.append(x)
        if self['standardNotifications']:
            self.destinations.append("/torrents/notify")

    def postOptions(self):
        log.msg("postOptions")
        if self['lobberHost'] is not None:
            self['stompUrl'] = "stomp://%s:61613" % self['lobberHost']
            self['lobberUrl'] = "https://%s" % self['lobberHost']
            
        u = urlparse(self['stompUrl'])
        host = u.hostname
        port = u.port
        if not u.scheme == 'stomp':
            raise usage.UsageError, "Not a stomp:// URL: "+self['stompUrl']
        self['stomp_host'] = host
        self['stomp_port'] = int(port)
        
        if self['dropbox'] and not os.path.isdir(self['dropbox']):
            raise usage.UsageError, \
                  "Dropbox does not exist or is not a directory: %s" % self['dropbox']

class MyServiceMaker(object):
    implements(service.IServiceMaker, IPlugin)
    tapname = 'lobberstoragenode'
    description = "A Storage Node for Lobber"
    options = Options
    sweeper = None
    getter = {}
    dropbox = None

    def makeService(self, options):
        """
        Constructs a lobber storage node service
        """
        lobber = LobberClient(options['lobberUrl'],
                              options['lobberKey'],
                              options['torrentDir'].rstrip(os.sep),
                              options['announceUrl'])
        transmission = TransmissionClient(options['transmissionRpc'],
                                          options['transmissionDownloadsDir'])

        torrentDownloader = TorrentDownloader(lobber,transmission,
                                              options.destinations,
                                              options['trackerProxyTrackerUrl'],
                                              options['trackerProxyListenOn'])
        stompService = internet.TCPClient(options['stomp_host'],
                                          options['stomp_port'],
                                          torrentDownloader)
        
        self.getter = {}
        for url in options.urls:
            log.msg("Pulling RSS/Torrent from "+url)
            self.getter[url] = task.LoopingCall(torrentDownloader.url_handler.load_url,url)
            self.getter[url].start(30,True)
        
        transmissionSweeper = TransmissionSweeper(lobber, transmission,
                                                  remove_limit=options['removeLimit'])
        self.sweeper = task.LoopingCall(transmissionSweeper.clean_done)
        reactor.callLater(30/2, self.sweeper.start, 30, True)

        if options['dropbox']:
            dropboxWatcher = DropboxWatcher(lobber,transmission,
                                            options['dropbox'],
                                            register=options['register'],
                                            acl=options['acl'],
                                            move=not options['keepData'])
            self.dropbox = task.LoopingCall(dropboxWatcher.watch_dropbox)
            self.dropbox.start(5,True)

        if options['trackerProxyTrackerUrl']:
            netloc, path = urlparse(options['trackerProxyTrackerUrl'])[1:3]
            tracker_host, tracker_port = splitnport(netloc, 443)
            proxy = server.Site(
                ReverseProxyTLSResource(
                    tracker_host, 
                    tracker_port, 
                    '',
                    #path_rewrite=[['[^\?]+', path]],
                    tls=True,   # FIXME: Base on urlparse()[0].
                    headers={'X_LOBBER_KEY': options['lobberKey']}))
            bindto = options['trackerProxyListenOn'].split(':')
            bindto_host = bindto[0]
            bindto_port = int(bindto[1])
            reactor.listenTCP(bindto_port, proxy, interface=bindto_host)

        return stompService
    
serviceMaker = MyServiceMaker()
