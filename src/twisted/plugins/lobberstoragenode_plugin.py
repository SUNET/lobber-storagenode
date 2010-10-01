from twisted.application import service
from twisted.python import log
from twisted.application import internet

from lobber.storagenode import TorrentDownloader, LobberClient, TransmissionClient, TransmissionSweeper
from twisted.python import usage
import os
from urlparse import urlparse
from twisted.internet import task
from zope.interface.declarations import implements
from twisted.plugin import IPlugin
import sys

class Options(usage.Options):

    optParameters = [
        ["stompUrl", "S", "stomp://localhost:61613","The STOMP protocol URL to use for notifications"],
        ["lobberKey", "k", None, "The Lobber application key to use"],
        ["torrentDir", "d", "torrents", "The directory where to store torrents"],
        ["lobberUrl", "u", "http://localhost:8000", "The Lobber URL prefix"],
        ['lobberHost',"h", None, "The host running both STOMP and https for lobber"],
        ['transmissionRpc','T',"http://transmission:transmission@localhost:9091","The RPC URL for transmission"],
        ['transmissionDownloadsDir','D',"/var/lib/transmission-daemon/downloads","The downloads directory for transmission"],
        ['removeLimit','r',0,"Remove torrent and data when this many other storage-nodes have the data (0=never remove)"]
    ]
    
    def parseArgs(self,*args):
        self.urls = []
        self.destinations = []
        for x in args:
            if x.startswith("/"):
                self.destinations.append(x)
            else:
                self.urls.append(x)

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

class MyServiceMaker(object):
    implements(service.IServiceMaker, IPlugin)
    tapname = 'lobberstoragenode'
    description = "A Storage Node for Lobber"
    options = Options
    sweeper = None
    getter = {}

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
        self.sweeper = task.LoopingCall(transmissionSweeper.sweep)
        self.sweeper.start(30,True)
        
        return stompService
    
serviceMaker = MyServiceMaker()