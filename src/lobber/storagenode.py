from lobber.retry import TwitterFailureTester, RetryingCall
from twisted.python import log
from subprocess import call
from twisted.web import client
from stompservice import StompClientFactory
import os,feedparser,json
from BitTorrent.bencode import bdecode, bencode
from hashlib import sha1
import transmissionrpc
from urlparse import urlparse
from tempfile import NamedTemporaryFile
from deluge.metafile import make_meta_file
import shutil
import errno
from twisted.web.client import Agent
from twisted.internet import reactor
from twisted.web.http_headers import Headers
from pprint import pformat

def decode_torrent(data):
    """
    Return (name, hash) of torrent file.
    """
    info = bdecode(data)['info']
    return info['name'], sha1(bencode(info)).hexdigest()

def read_torrent(torrent_file):
    tfile = file(torrent_file)
    return decode_torrent(tfile.read())


def mkdir_p(path):
    try:
        os.makedirs(path)
    except OSError as exc: # Python >2.5
        if exc.errno == errno.EEXIST:
            pass
        else: 
            log.err()
            raise

def ignore(*args,**kwargs):
    return

def logit(err):
    log.err(err)

class LobberClient:
    
    def __init__(self,lobber_url="http://localhost:8000",lobber_key=None,torrent_dir="/tmp/lobber-torrents",announce_url=None):
        self.lobber_url = lobber_url
        self.lobber_key = lobber_key
        self.torrent_dir = torrent_dir
        self.announce_url = announce_url
        mkdir_p(self.torrent_dir)
        
    def make_torrent(self,datapath,name=None,comment=None,expires=None):
        tmptf = NamedTemporaryFile()
        datafile = file(datapath)
        if comment == None:
            comment = "%s" % name
        if name == None:
            name = datafile.name
        
        make_meta_file(name,self.announce_url, 2**18, comment=comment, target=tmptf)
        torrent_file = tmptf.name
        
        return read_torrent(torrent_file), torrent_file

    def torrent_url(self,identity):
        return '%s/torrent/%d.torrent' % (self.lobber_url, identity)

    def json_decode(self,data):
        try:
            return json.loads(data)
        except ValueError:
            return data

    def url(self,path):
        u = "%s%s" % (self.lobber_url,path)
        return u.encode('ascii')

    def api_call(self,urlpath,page_handler=ignore,err_handler=logit,*args,**kwargs):
        r = RetryingCall(client.getPage,self.url(urlpath),agent="Lobber Storage Node/1.0",headers={'X_LOBBER_KEY': self.lobber_key})
        d = r.start(failureTester=TwitterFailureTester())
        d.addCallback(self.json_decode)
        d.addErrback(err_handler)
        d.addCallback(page_handler,args,kwargs)
        return d

class TransmissionClient:
    def __init__(self,rpcurl="http://transmission:transmission@localhost:9091",downloads_dir="/var/lib/transmission-daemon/downloads"):
        self.rpc = urlparse(rpcurl)
        self.downloads_dir = downloads_dir
        
    def client(self):
        return transmissionrpc.Client(address=self.rpc.hostname,
                                        port=self.rpc.port,
                                        user=self.rpc.username,
                                        password=self.rpc.password)
    
    def unique_path(self,info_hash):
        return "%s%s%s" % (self.downloads_dir,os.sep,info_hash)
    
    def download(self,torrent_file,directory=None):
        if torrent_file == None:
            raise Exception("No torrent file provided")
        
        torrent_name,info_hash = read_torrent(torrent_file)  
        if directory == None:  
            directory = self.unique_path(info_hash)
            mkdir_p(directory)
        
        tc = self.client()
        status = None
        try:
            status = tc.add_uri(torrent_file,download_dir=directory)
        except transmissionrpc.transmission.TransmissionError,msg:
            status = msg
            log.msg(msg)
            pass
        return torrent_name, info_hash, directory, status
    
    def upload(self,torrent_file,datapath,move=True):
        if torrent_file == None:
            raise Exception("No torrent file provided")
        
        torrent_name, info_hash = read_torrent(torrent_file)
        if move:
            dst = self.unique_path(info_hash)
            if not os.path.isdir(dst):
                mkdir_p(dst)
            shutil.move(datapath, "%s%s%s" % (dst,os.sep,torrent_name))
        else:
            datapath_parts = datapath.split(os.sep)
            filename = datapath_parts.pop()
            parent = os.sep.join(datapath_parts)
            if filename != torrent_name:
                os.rename(datapath, "%s%s%s" % (parent,os.sep,torrent_name))
            dst = parent

        tc = self.client()
        status = None
        try:
            status = tc.add_uri(torrent_file,download_dir=dst)
        except transmissionrpc.transmission.TransmissionError,msg:
            status = msg
            log.msg(msg)
            pass
        return torrent_name, info_hash, dst, status

class TransmissionSweeper:
    def __init__(self,lobber,transmission, remove_limit=0):
        self.transmission = transmission
        self.lobber = lobber
        self.remove_limit = remove_limit
    
    def remove_if_done(self,r,args,kwargs):
        if int(self.remove_limit) <= int(r['count']):
            log.msg("Removing torrent %d" % args[0].id)
            os.unlink("%s/%s.torrent" % (self.lobber.torrent_dir,args[0].hashString))
            tc = self.transmission.client()
            tc.remove(args[0].id,delete_data=True)
    
    def remove_on_404(self,err,t):
        log.msg(pformat(err.value))
        if err.value.status == '404':
            log.msg("Removing unauthorized torrent %d" % t.id)
            os.unlink("%s/%s.torrent" % (self.lobber.torrent_dir,t.hashString))
            tc = self.transmission.client()
            tc.remove(t.id,delete_data=True)
    
    def clean_done(self):
        tc = self.transmission.client()
        for t in tc.list().values():
            log.msg("clean_done [%d] %s %s %s" % (t.id,t.hashString,t.name,t.status))
            tc.start(t.id)
            tc.change(t.id,seedRatioMode=2,uploadLimited=False,downloadLimited=False)
            if t.status == 'seeding':
                self.lobber.api_call("/torrent/ihave/%s" % t.hashString)
                if self.remove_limit > 0:
                    self.lobber.api_call("/torrent/hazcount/%s" % t.hashString, self.remove_if_done, self.logit, t)
            
    def clean_unauthorized(self):
        tc = self.transmission.client()
        for t in tc.list().values():
            log.msg("clean_unauthorized [%d] %s %s %s" % (t.id,t.hashString,t.name,t.status))
            self.lobber.api_call("/torrent/exists/%s" % t.hashString, ignore, lambda err: self.remove_on_404(err,t))
                
                
class TransmissionURLHandler:
    
    def __init__(self,lobber,transmission):
        self.transmission = transmission
        self.lobber = lobber
    
    def torrent_file(self,info_hash):
        return self.lobber.torrent_dir+os.sep+info_hash+".torrent"
    
    def handle_page(self,data):
        if data.startswith("d8:announce"):
            (name,info_hash) = decode_torrent(data)
            log.msg("Got torrent with info_hash "+info_hash)
            fn = self.torrent_file(info_hash)
            if not os.path.exists(fn):
                f = open(fn,"w")
                f.write(data)
                f.close()
                log.msg("Wrote torrent with info_hash "+info_hash+" to file "+fn)
                self.transmission.download(fn)
        elif "<rss" in data:
            try:
                f = feedparser.parse(data)
                for e in f.entries:
                    self.load_url_retry(e.link)
            except Exception,e:
                log.msg(e)
        else:
            try:
                torrents = json.loads(data)
                for t in torrents:
                    fn = self.torrent_file(t['info_hash'])
                    if not os.path.exists(fn):
                        log.msg("adding %s from %s" % (t['label'],fn))
                        self.load_url_retry("%s%s.torrent" % (self.lobber.lobber_url,t['link']))
            except Exception,e:
                log.msg(e)
            
        return
    
    def load_url(self,url):
        d = client.getPage(url.encode('ascii'),agent="Lobber Storage Node/1.0",headers={'X_LOBBER_KEY': self.lobber.lobber_key})
        d.addCallback(self.handle_page)
        return
    
    def load_url_retry(self,url):
        r = RetryingCall(client.getPage,url.encode('ascii'),agent="Lobber Storage Node/1.0",headers={'X_LOBBER_KEY': self.lobber.lobber_key})
        d = r.start(failureTester=TwitterFailureTester())
        d.addCallback(self.handle_page)
        return

class TorrentDownloader(StompClientFactory):

    def __init__(self,lobber,transmission,destinations=["/torrent/notify"]):
        self.destinations = destinations
        self.url_handler = TransmissionURLHandler(lobber, transmission)
        self.lobber = lobber
        self.transmission = transmission

    def remove_on_404_other(self,err,id,hashval):
        log.msg(pformat(err.value))
        if err.value.status == '404':
            log.msg("Purging removed torrent %d" % id)
            os.unlink("%s/%s.torrent" % (self.lobber.torrent_dir,hashval))
            tc = self.transmission.client()
            tc.remove(id,delete_data=True)

    def recv_connected(self, msg):
        for dst in self.destinations:
            self.subscribe(dst)

    def recv_message(self, msg):
        body = msg.get('body').strip()
        notice = json.loads(body)
        if notice is None:
            log.msg("Got an unknown message")
            return
        
        for type,info in notice.iteritems():
            id = info[0]
            hashval = info[1]
            if type == 'add':
                log.msg("add %d %s" % (id,hashval))
                self.url_handler.load_url_retry(self.lobber.torrent_url(id))
            
            if type == 'delete':
                log.msg("delete %d %s" % (id,hashval))
                self.lobber.api_call("/torrent/exists/%s" % hashval, ignore, lambda err: self.remove_on_404_other(err,id,hashval))
                    