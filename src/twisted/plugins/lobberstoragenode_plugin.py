from twisted.application import service
from twisted.python import log
from twisted.application import internet

from lobber.storagenode import TransmissionURLHandler, TorrentDownloader
from twisted.python import usage
import os
from urlparse import urlparse
from twisted.internet import task
from zope.interface.declarations import implements
from twisted.plugin import IPlugin
from pprint import pprint

class Options(usage.Options):

    optParameters = [
        ["stompUrl", "S", "stomp://localhost:61613","The STOMP protocol URL to use for notifications"],
        ["lobberKey", "k", None, "The Lobber application key to use"],
        ["torrentDir", "d", "torrents", "The directory where to store torrents"],
        ["lobberUrl", "u", "http://localhost:8000/torrents", "The Lobber URL prefix"],
        ['lobberHost',"h", None, "The host running both STOMP and https for lobber"]
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

    def makeService(self, options):
        """
        Constructs a lobber storage node service
        """
        dl = TransmissionURLHandler(torrent_dir=options['torrentDir'].rstrip(os.sep),
                                    lobber_key=options['lobberKey'])

        torrentDownloader = TorrentDownloader(options.destinations,dl,options['lobberUrl'])
        stompService = internet.TCPClient(options['stomp_host'],options['stomp_port'],torrentDownloader)
        
        getter = {}
        for url in options.urls:
            log.msg("Pulling data from "+url)
            getter[url] = task.LoopingCall(dl.load_url,url)
            getter[url].start(10,True)
            
        return stompService
    
serviceMaker = MyServiceMaker()