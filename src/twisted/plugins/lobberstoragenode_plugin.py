from twisted.application import service
from twisted.python import log
from twisted.application import internet

from lobber.storagenode import URLHandler, TorrentDownloader
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
        ["script","s","ls -l", "The script to run on all received torrents"]
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
        u = urlparse(self['stompUrl'])
        pprint(u)
        hostport = u.path.lstrip('/')
        (host,port) = hostport.split(':')
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
        dl = URLHandler(options['torrentDir'].rstrip(os.sep),options['script'])

        torrentDownloader = TorrentDownloader(options.destinations,dl,options['lobberUrl'],options['lobberKey'])
        stompService = internet.TCPClient(options['stomp_host'],options['stomp_port'],torrentDownloader)
        
        getter = {}
        for url in options.urls:
            log.msg("Pulling data from "+url)
            getter[url] = task.LoopingCall(dl.load_url,url)
            getter[url].start(10,True)
            
        return stompService
    
serviceMaker = MyServiceMaker()