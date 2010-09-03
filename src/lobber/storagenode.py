from lobber.retry import TwitterFailureTester, RetryingCall
from twisted.python import log
from subprocess import call
from twisted.web import client
from stompservice import StompClientFactory
import os,feedparser,json
from BitTorrent.bencode import bdecode, bencode
from hashlib import sha1
from pprint import pprint
import transmissionrpc
from urlparse import urlparse

def _torrent_info(data):
    """
    Return (name, hash) of torrent file.
    """
    info = bdecode(data)['info']
    return info['name'], sha1(bencode(info)).hexdigest()

class TransmissionURLHandler:
    
    def __init__(self,torrent_dir=None,downloads_dir="/var/lib/transmission-daemon/downloads",transmissionrpc="http://transmission:transmission@locahost:9091",lobber_key=None):
        self.torrent_dir = torrent_dir
        self.downloads_dir = downloads_dir
        self.transmissionrpc = urlparse(transmissionrpc)
        self.lobber_key = lobber_key
        self.tc = transmissionrpc.Client(address=self.transmissionrpc.hostname,
                                        port=self.transmissionrpc.port,
                                        user=self.transmissionrpc.username(),
                                        password=self.transmissionrpc.password())
    
    def add_torrent(self,path,info_hash):
        if path is not None:
            dir = path+os.pathsep+info_hash
            os.mkdir(dir)
            #os.chown(dir, 'debian-transmission', 'debian-transmission')
            self.tc.add_uri(path,download_dir=dir)
            
    
    def handle_page(self,data):
        if data.startswith("d8:announce"):
            (name,info_hash) = _torrent_info(data)
            log.msg("Got torrent with info_hash "+info_hash)
            fn = self.torrent_dir+os.sep+info_hash+".torrent"
            if not os.path.exists(fn):
                f = open(fn,"w")
                f.write(data)
                f.close()
                log.msg("Wrote torrent with info_hash "+info_hash+" to file "+fn)
                self.add_torrent(fn,info_hash)
        
        if "<rss" in data:
            try:
                f = feedparser.parse(data)
                for e in f.entries:
                    self.load_url_retry(e.link.encode('ascii'))
            except Exception,e:
                log.msg(e)
            
        return
    
    def load_url(self,url):
        d = client.getPage(url,agent="Lobber Storage Node/1.0",headers={'X_LOBBER_KEY': self.lobber_key})
        d.addCallback(self.handle_page)
        return
    
    def load_url_retry(self,url):
        r = RetryingCall(client.getPage,url,agent="Lobber Storage Node/1.0",headers={'X_LOBBER_KEY': self.lobber_key})
        d = r.start(failureTester=TwitterFailureTester())
        d.addCallback(self.handle_page)
        return

class TorrentDownloader(StompClientFactory):

    def __init__(self,
                 destinations=["/torrent/new"],
                 url_handler=TransmissionURLHandler("/tmp"),
                 lobber_url="http://localhost:8080"):
        self.destinations = destinations
        self.url_handler = url_handler
        self.lobber_url = lobber_url

    def recv_connected(self, msg):
        for dst in self.destinations:
            self.subscribe(dst)

    def recv_message(self, msg):
        body = msg.get('body').strip()
        id = json.loads(body)
        if id is None:
            log.msg("Got an unknown message")
            return
             
        url = self.lobber_url + "/torrent/" + id.encode('ascii') + ".torrent"
        self.url_handler.load_url_retry(url)
