from twisted.application import service
from twisted.internet.defer import Deferred
from lobber.retry import TwitterFailureTester, RetryingCall
from twisted.python import log
application = service.Application("Lobber Storage Node Agent")
from twisted.application import internet
from twisted.web import client
from pprint import pprint
from urllib2 import urlopen
from stompservice import StompClientFactory
import json
import os
import types

lobber = 'localhost'
if os.environ.has_key('LOBBER_HOST'):
   lobber = os.environ['LOBBER_HOST']

if os.environ.has_key('LOBBER_KEY'):
   lkey = os.environ['LOBBER_KEY']

class TransmissionClient(StompClientFactory):

   def recv_torrent(self,value,file):
       log.msg("recv_torrent: "+file)

   def recv_connected(self, msg):
        self.subscribe("/torrent/new")

   def recv_message(self, msg):
        body = msg.get('body').strip()
        info_hash = json.loads(body)
        if info_hash is None:
            return

        url = "http://"+lobber+":8000/torrents/"+info_hash.encode('ascii')+".torrent"+"?lkey="+lkey
        file = "/tmp/"+info_hash.encode('ascii')+".torrent"
        
        r = RetryingCall(client.downloadPage,url,file)
        d = r.start(failureTester=TwitterFailureTester())
        d.addCallback(self.recv_torrent,file)     
   
stompClientService = internet.TCPClient(lobber,61613,TransmissionClient())
stompClientService.setServiceParent(application)
