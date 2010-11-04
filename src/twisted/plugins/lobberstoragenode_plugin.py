from twisted.application import service
from twisted.python import log
from twisted.application import internet

from lobber.storagenode import TorrentDownloader, LobberClient, TransmissionClient, TransmissionSweeper, DropboxWatcher
from twisted.python import usage
import os
from urlparse import urlparse
from twisted.internet import task, reactor
from zope.interface.declarations import implements
from twisted.plugin import IPlugin
import sys
from twisted.web import server
from pprint import pprint
from lobber.proxy import ReverseProxyTLSResource

class Options(usage.Options):

    optParameters = [
        ["stompUrl", "S", "stomp://localhost:61613","The STOMP protocol URL to use for notifications"],
        ["lobberKey", "k", None, "The Lobber application key to use"],
        ["torrentDir", "d", "torrents", "The directory where to store torrents"],
        ["lobberUrl", "u", "http://localhost:8000", "The Lobber URL prefix"],
        ['lobberHost',"h", None, "The host running both STOMP and https for lobber"],
        ['transmissionRpc','T',"http://transmission:transmission@localhost:9091","The RPC URL for transmission"],
        ['transmissionDownloadsDir','D',"/var/lib/transmission-daemon/downloads","The downloads directory for transmission"],
        ['removeLimit','r',0,"Remove torrent and data when this many other storage-nodes have the data (0=never remove)"],
        ['dropbox','D',None,"A directory to watch for new content"],
        ['acl','A',None,"Access Control List to apply to new torrents"]
    ]
    
    optFlags = [
        ['register','R',"Register new torrents with lobber"]
    ]
    
    def parseArgs(self,*args):
        self.urls = []
        self.destinations = []
        for x in args:
            if x.startswith("/"):
                self.destinations.append(x)
            else:
                self.urls.append(x)
        
        # always include the standard notify destination
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
            raise usage.UsageError, "Dropbox does not exist or is not a directory: %s" % self['dropbox']

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
        lobber = LobberClient(options['lobberUrl'], options['lobberKey'], options['torrentDir'].rstrip(os.sep))
        transmission = TransmissionClient(options['transmissionRpc'], options['transmissionDownloadsDir'])

        torrentDownloader = TorrentDownloader(lobber,transmission,options.destinations)
        stompService = internet.TCPClient(options['stomp_host'],options['stomp_port'],torrentDownloader)
        
        self.getter = {}
        for url in options.urls:
            log.msg("Pulling RSS/Torrent from "+url)
            self.getter[url] = task.LoopingCall(torrentDownloader.url_handler.load_url,url)
            self.getter[url].start(30,True)
        
        transmissionSweeper = TransmissionSweeper(lobber, transmission, remove_limit=options['removeLimit'])
        self.sweeper = task.LoopingCall(transmissionSweeper.clean_done)
        self.sweeper.start(30,True)

        if options['dropbox']:
            dropboxWatcher = DropboxWatcher(lobber,transmission,options['dropbox'],register=options['register'],acl=options['acl'])
            self.dropbox = task.LoopingCall(dropboxWatcher.watch_dropbox)
            self.dropbox.start(5,True)
        
        u = urlparse(options['lobberUrl'])
        pprint(u)
        tls = (u.scheme == 'https')
        proxy = server.Site(ReverseProxyTLSResource(u.hostname, u.port, '',tls=tls, headers={'X_LOBBER_KEY': options['lobberKey']}))
        reactor.listenTCP(8080, proxy,interface='127.0.0.1')
        return stompService
    
serviceMaker = MyServiceMaker()