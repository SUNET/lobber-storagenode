from lobber.retry import TwitterFailureTester, RetryingCall
from twisted.python import log
from twisted.web import client
from stompservice import StompClientFactory
import os,feedparser,json
from hashlib import sha1
import transmissionrpc
from urlparse import urlparse
from tempfile import NamedTemporaryFile
import shutil
import errno
from pprint import pformat, pprint
import itertools
import mimetools
import mimetypes
from datetime import timedelta
from datetime import date
import socket
from twisted.internet import reactor
from lobber.proxy import ReverseProxyTLSResource
from lobber.torrenttools import bdecode, bencode, make_meta_file

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
        if not os.path.isdir(path):
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
    log.err("logit:" % err)

class MultiPartForm(object):
    """Accumulate the data to be used when posting a form."""

    def __init__(self):
        self.form_fields = []
        self.files = []
        self.boundary = mimetools.choose_boundary()
        return
    
    def get_content_type(self):
        return 'multipart/form-data; boundary=%s' % self.boundary

    def add_field(self, name, value):
        """Add a simple field to the form data."""
        self.form_fields.append((name, value))
        return

    def add_file(self, fieldname, filename, fileHandle, mimetype=None):
        """Add a file to be uploaded."""
        body = fileHandle.read()
        if mimetype is None:
            mimetype = mimetypes.guess_type(filename)[0] or 'application/octet-stream'
        self.files.append((fieldname, filename, mimetype, body))
        return
    
    def __str__(self):
        """Return a string representing the form data, including attached files."""
        # Build a list of lists, each containing "lines" of the
        # request.  Each part is separated by a boundary string.
        # Once the list is built, return a string where each
        # line is separated by '\r\n'.  
        parts = []
        part_boundary = '--' + self.boundary
        
        # Add the form fields
        parts.extend(
            [ part_boundary,
              'Content-Disposition: form-data; name="%s"' % name,
              '',
              value,
            ]
            for name, value in self.form_fields
            )
        
        # Add the files to upload
        parts.extend(
            [ part_boundary,
              'Content-Disposition: file; name="%s"; filename="%s"' % \
                 (field_name, filename),
              'Content-Type: %s' % content_type,
              '',
              body,
            ]
            for field_name, filename, content_type, body in self.files
            )
        
        # Flatten the list and add closing boundary marker,
        # then return CR+LF separated data
        flattened = list(itertools.chain(*parts))
        flattened.append('--' + self.boundary + '--')
        flattened.append('')
        return '\r\n'.join(flattened)

class LobberClient:
    
    def __init__(self,
                 lobber_url="http://localhost:8000",
                 lobber_key=None,
                 torrent_dir="/tmp/lobber-torrents",
                 announce_url=None):
        self.lobber_url = lobber_url
        self.lobber_key = lobber_key
        self.torrent_dir = torrent_dir
        self.announce_url = announce_url
        
        mkdir_p(self.torrent_dir)
        
    def make_torrent(self,datapath,name=None,comment=None,expires=None):
        tmptf = NamedTemporaryFile(delete=False)
        
        if name is None:
            (head,tail) = os.path.split(datapath)
            name = tail
        if comment is None:
            comment = "%s" % name
        
        log.msg("Writing torrent file to %s" % tmptf.name)
        make_meta_file(datapath,
                                       self.announce_url,
                                       2**18,
                                       comment=comment,
                                       target=tmptf.name)
        torrent_file = tmptf.name
        log.msg("Made torrent file %s" % tmptf.name)
        
        return read_torrent(torrent_file), torrent_file

    def torrent_url(self,identity):
        return '%s/torrent/%d.torrent' % (self.lobber_url, identity)

    def url(self,path):
        u = "%s%s" % (self.lobber_url,path)
        return u.encode('ascii')

    def api_call(self,urlpath,page_handler=ignore,err_handler=logit,method='GET',content_type='text/html',body=None):
        r = RetryingCall(client.getPage,
                         self.url(urlpath),
                         method=method,
                         postdata=body,
                         agent="Lobber Storage Node/1.0",
                         headers={'X_LOBBER_KEY': self.lobber_key, 'Content-Type': content_type})
        d = r.start(failureTester=TwitterFailureTester())
        if err_handler:
            d.addErrback(err_handler)
        d.addCallback(page_handler)
        return d

class TransmissionClient:
    def __init__(self,rpcurl="http://transmission:transmission@localhost:9091",downloads_dir="/var/lib/transmission-daemon/downloads"):
        self.rpc = urlparse(rpcurl)
        self.downloads_dir = downloads_dir
        self.hashmap = {}           # hashmap[hash] --> torrent object
        
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
        except transmissionrpc.TransmissionError,msg:
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
            os.chmod(dst, 755)
            shutil.move(datapath, "%s%s%s" % (dst,os.sep,torrent_name))
        else:
            datapath_parts = datapath.split(os.sep)
            filename = datapath_parts.pop()
            parent = os.sep.join(datapath_parts)
            if filename != torrent_name:
                os.rename(datapath, "%s%s%s" % (parent,os.sep,torrent_name))
            dst = parent

        tc = self.client()
        try:
            tc.add_uri(torrent_file,download_dir=dst)
        except transmissionrpc.TransmissionError,msg:            
            log.err(msg)
        
        try:
            tc.verify(info_hash)
        except transmissionrpc.TransmissionError,msg:
            log.err(msg)
        
        return torrent_name, info_hash, dst


class cb_wrapper(object):
    def __init__(self, lobber, transmission, thing):
        self._lobber = lobber
        self._transmission = transmission
        self._thing = thing

    def _remove_torrent(self, t):
        lobber = self._lobber
        transmission = self._transmission
        log.err("remove_torrent: %d" % t.id)
        fn = "%s/%s.torrent" % (lobber.torrent_dir, t.hashString)
        if os.path.exists(fn):
            os.unlink(fn)
        tc = transmission.client()
        tc.stop(t.id)
        tc.remove(t.id, delete_data=True)
        shutil.rmtree(transmission.unique_path(t.hashString), True)

    def ok(self, data):
        log.err("cb_wrapper.ok: %s" % data)
        assert(isinstance(self._thing, tuple))
        assert(len(self._thing) == 2)
        pred, t = self._thing
        if pred(data):
            self._remove_torrent(t)

    def err(self, err):
        log.err("cb_wrapper.err: %s" % err)
        assert(isinstance(self._thing, transmissionrpc.Torrent))
        t = self._thing
        if err.value.status == '404':
            log.msg("Removing 404 torrent %d (%s)" % (t.id, repr(t)))
            self._remove_torrent(t)

class TransmissionSweeper:
    def __init__(self,lobber,transmission, remove_limit=0, entitlement="urn:x-lobber:storagenode"):
        self.transmission = transmission
        self.lobber = lobber
        self.remove_limit = remove_limit
        self.entitlement = entitlement
    
    def remove_if_done_p(self, data):
        if data:
            try:
                r = json.loads(data)
                log.msg("remove_if_done: %s" % pformat(r))
                if int(self.remove_limit) <= int(r['count']):
                    return True
            except Exception,err:
                log.err(err)
        return False
    
    def clean_done(self):
        self.transmission.hashmap = {}
        tc = self.transmission.client()
        for t in tc.list().values():
            #log.msg("clean_done [%d] %s %s %s" % (t.id,t.hashString,t.name,t.status))
            self.transmission.hashmap[t.hashString] = t
            tc.reannounce(t.id)
            tc.change(t.id,seedRatioMode=2,uploadLimited=False,downloadLimited=False)
            d = self.lobber.api_call("/torrent/exists/%s" % t.hashString,
                                     err_handler=cb_wrapper(
                                         self.lobber, self.transmission, t).err)
        if False:               # DEBUG
            for h, t in self.transmission.hashmap.iteritems():
                log.err("clean_done: hashmap[%s] = %s" % (h, t))
        
                
def _rewrite_url(url, new_addr, new_proto=None):
    from urllib import splittype, splithost
    proto, rest = splittype(url)
    addr = splithost(rest)[0]
    url = url.replace(addr, new_addr, 1)
    url = url.replace('/announce','/uannounce',1)
    if new_proto:
        url = url.replace(proto, new_proto, 1)
    return url

class TransmissionURLHandler:
    
    def __init__(self,lobber,transmission, tracker_url, proxy_addr):
        self.transmission = transmission
        self.lobber = lobber
        self.tracker_url = tracker_url
        self.proxy_addr = proxy_addr
    
    def torrent_file(self,info_hash):
        return self.lobber.torrent_dir+os.sep+info_hash+".torrent"
    
    def handle_page(self,data):
        if data.startswith("d8:announce"):
            (name,info_hash) = decode_torrent(data)
            log.msg("Got torrent with info_hash "+info_hash)
            fn = self.torrent_file(info_hash)
            if not os.path.exists(fn):
                if self.tracker_url and self.proxy_addr:
                    d = bdecode(data)
                    proxy_url = _rewrite_url(self.tracker_url, self.proxy_addr, 'http')
                    annl = d.get('announce-list') # List of list of strings.
                    if annl:
                        for l in annl:
                            while self.tracker_url in l:
                                l.remove(self.tracker_url)
                                l.insert(proxy_url)
                        data = bencode(d)
                    else:
                        ann = d.get('announce') # String
                        if ann and ann == self.tracker_url:
                            d['announce'] = proxy_url
                        data = bencode(d)
                f = open(fn,"w")
                f.write(data)
                f.close()
                log.msg("Wrote torrent with info_hash "+info_hash+" to file "+fn)
                self.transmission.download(fn)
        elif "<rss" in data:
            try:
                f = feedparser.parse(data)
                for e in f.entries:
                    self.load_url(e.link, True)
            except Exception,e:
                log.err(e)
        else:
            try:
                torrents = json.loads(data)
                for t in torrents:
                    fn = self.torrent_file(t['info_hash'])
                    if not os.path.exists(fn):
                        log.msg("adding %s from %s" % (t['label'],fn))
                        url = "%s%s.torrent" % (self.lobber.lobber_url,
                                                t['link'])
                        self.load_url(url, True)
            except ValueError:
                pass
            except Exception,e:
                log.err(e)
            
        return
    
    def load_url(self, url, retry=False):
        agent = 'Lobber Storage Node/1.0'
        headers = {'X_LOBBER_KEY': self.lobber.lobber_key}
        if retry:
            r = RetryingCall(client.getPage, url.encode('ascii'), agent=agent,
                             headers=headers)
            d = r.start(failureTester=TwitterFailureTester())
        else:
            d = client.getPage(url.encode('ascii'), agent=agent,
                               headers=headers)
        d.addCallback(self.handle_page)


class TorrentDownloader(StompClientFactory):

    def __init__(self,lobber,transmission,destinations=["/torrent/notify"],
                 tracker_url=None, proxy_addr=None):
        self.destinations = destinations
        self.url_handler = TransmissionURLHandler(lobber, transmission,
                                                  tracker_url, proxy_addr)
        self.lobber = lobber
        self.transmission = transmission

    def recv_connected(self, msg):
        for dst in self.destinations:
            log.msg("Subscribe to %s" % dst)
            self.subscribe(dst)

    def recv_message(self, msg):
        try:
            body = msg.get('body').strip()
        except Exception,err:
            log.err('recv_message: msg.get: %s' % repr(err))
        try:
            notice = json.loads(body)
        except Exception,err:
            log.err('recv_message: json.loads: %s' % repr(err))

        if notice is None:
            err.msg("recv_message: Got an unknown message: %s" % repr(msg))
            return
            
        log.err("recv_message: stomp msg: %s" % pformat(notice))
        for type, info in notice.iteritems():
            id = info[0]
            hashval = info[1].strip()
            if type == 'add':
                self.url_handler.load_url(self.lobber.torrent_url(id), True)
            if type == 'delete':
                t = self.transmission.hashmap.get(hashval)
                log.err("recv_message: t=%s" % repr(t))
                if t:
                    self.lobber.api_call(
                        "/torrent/exists/%s" % hashval,
                        err_handler=cb_wrapper(self.lobber, self.transmission, t).err)
                else:
                    log.err("recv_message: unable to delete unknown torrent %s" % hashval)
              
              
class DropboxWatcher:
    
    def __init__(self,lobber,transmission,dropbox,register=True,acl=None,publicAccess=False,move=True):
        self.lobber = lobber
        self.transmission = transmission
        self.dropbox = dropbox
        self.register = register
        self.acl = acl
        self.publicAccess = publicAccess
        self.move = move
    
    def kill_torrent(self,err,torrent_file_name):
        log.err("an error occured - %s - cancelling torrent upload" \
                % pformat(err))
        os.unlink(torrent_file_name)
        
    def start_torrent(self,data,torrent_file,data_file,move=True):
        log.msg("starting torrent...")
        log.msg(data)
        self.transmission.upload(torrent_file,data_file,move)
        os.unlink(torrent_file)
        
    def watch_dropbox(self):
        try:
            for fn in os.listdir(self.dropbox):
                tfn = "%s%s%s.torrent" % (self.dropbox,os.sep,fn)
                dfn = "%s%s%s" % (self.dropbox,os.sep,fn)
                log.msg("found %s" % dfn)
                if not fn.endswith(".torrent") and not os.path.exists(tfn):     
                    log.msg("making torrent from %s" % dfn)
                    log.msg(pformat(dfn))
                    torrent,torrent_file_name = self.lobber.make_torrent(dfn)
                    log.msg("renamed %s to %s" % (torrent_file_name,tfn))
                    shutil.move(torrent_file_name,tfn)
                    
                    if self.register:
                        form = MultiPartForm()
                        form.add_field("description","Uploaded by lobber storagenode on %s" % socket.getfqdn(socket.gethostname()))
                        form.add_field("expires",(timedelta(+10)+date.today()).isoformat())
                        t = "0"
                        if self.publicAccess:
                            t = "1"
                        form.add_field("publicAccess",t)
                        form.add_field("acl",self.acl)
                        form.add_file("file", tfn, file(tfn), "application/x-bittorrent")     
                        log.msg("registering torrent with lobber")
                        log.msg(form.__str__())
                        self.lobber.api_call("/torrent/add.json",
                                             method='POST',
                                             content_type=form.get_content_type(),
                                             body=form.__str__(),
                                             err_handler=lambda err: self.kill_torrent(err,tfn), # FIXME: does tfn work here?
                                             page_handler=lambda page: self.start_torrent(page,tfn,dfn,self.move)) # FIXME: do tfn and dfn work here?
                    else:
                        self.start_torrent("",tfn,dfn,self.move)
        except Exception, err:
            log.err(err)
            raise
