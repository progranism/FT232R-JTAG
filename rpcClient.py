# Copyright (C) 2011 by fpgaminer <fpgaminer@bitcoin-mining.com>
#                       fizzisist <fizzisist@fpgamining.com>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.

import httplib
import socket
import time
from base64 import b64encode
from json import dumps, loads
from urlparse import urlsplit
from threading import Thread
from Queue import Empty
from struct import pack

class NotAuthorized(Exception): pass
class RPCError(Exception): pass

# Socket wrapper to enable socket.TCP_NODELAY and KEEPALIVE
realsocket = socket.socket
def socketwrap(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
	sockobj = realsocket(family, type, proto)
	sockobj.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
	sockobj.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
	return sockobj
socket.socket = socketwrap

class RPCClient:
	
	NUM_RETRIES = 5
	
	def __init__(self, settings, logger, goldqueue):
		self.host = settings.url
		self.getwork_interval = settings.getwork_interval
		self.logger = logger
		self.goldqueue = goldqueue
		self.fpga_list = []
		self.proto = "http"
		self.postdata = {'method': 'getwork', 'id': 'json'}
		self.headers = {"User-Agent": 'x6500-miner',
		                "Authorization": 'Basic ' + b64encode(settings.worker),
		                "Content-Type": 'application/json'
		               }
		self.timeout = 5
		self.long_poll_timeout = 3600
		self.long_poll_max_askrate = 60 - self.timeout
		self.long_poll_active = False
		self.long_poll_url = ''
		self.lp_connection = None
		self.connection = None
		self.last_job = [None]*2
		self.getwork_thread = None
		self.longpoll_thread = None
	
	def start(self):
		# Start getwork thread
		self.getwork_thread = Thread(target=self.getwork_loop)
		self.getwork_thread.daemon = True
		self.getwork_thread.start()
		
		# Start long-polling thread:
		self.longpoll_thread = Thread(target=self.longpoll_loop)
		self.longpoll_thread.daemon = True
		self.longpoll_thread.start()

	def connect(self, proto, host, timeout):
		if proto == 'https': connector = httplib.HTTPSConnection
		else: connector = httplib.HTTPConnection
		return connector(host, strict=True, timeout=timeout)

	def request(self, connection, url, headers, data=None):
		result = response = None
		
		try:
			if data is not None:
				connection.request('POST', url, data, headers)
			else:
				connection.request('GET', url, headers=headers)

			response = connection.getresponse()

			if response.status == httplib.UNAUTHORIZED:
				raise NotAuthorized()
			
			self.long_poll_url = response.getheader('X-Long-Polling', '')
			#self.logger.reportDebug('LP URL: %s' % self.long_poll_url)
			
			#self.miner.update_time = bool(response.getheader('X-Roll-NTime', ''))
			
			result = loads(response.read())

			if result['error']:
				raise RPCError(result['error']['message'])

			return (connection, result)
		finally:
			if not result or not response or (response.version == 10 and response.getheader('connection', '') != 'keep-alive') or response.getheader('connection', '') == 'close':
				connection.close()
				connection = None

	def failure(self, msg):
		self.logger.log(msg)
		exit()

	def getwork(self, connection, fpgaID, data=None):
		try:
			if not connection:
				self.logger.reportDebug("Connecting to server...")
				connection = self.connect(self.proto, self.host, self.timeout)
				self.logger.reportConnected(True)
				#connection.set_debuglevel(1)
			if data is None:
				self.postdata['params']  = []
				#self.logger.reportDebug("%d: Requesting work..." % fpgaID)
			else:
				self.postdata['params'] = [data]
				#self.logger.reportDebug("%d: Submitting nonce..." % fpgaID)
			(connection, result) = self.request(connection, '/', self.headers, dumps(self.postdata))
			return (connection, result['result'])
		except NotAuthorized:
			self.failure('Wrong username or password.')
		except RPCError as e:
			self.logger.reportDebug("RPCError! %s" % e)
			return (connection, e)
		except IOError as e:
			self.logger.reportDebug("IOError! %s" % e)
		except ValueError as e:
			self.logger.reportDebug("ValueError! %s" % e)
		except httplib.HTTPException:
			#self.logger.reportDebug("HTTP Error!")
			pass
		return (None, None)
	
	def getNewJob(self, fpga, work=None):
		try:
			# Empty the job queue:
			while True:
				try:
					fpga.jobqueue.get(False)
				except Empty:
					break
			
			if work is None:
				(self.connection, work) = self.getwork(self.connection, fpga.id)
			
			fpga.putJob(work)
			fpga.last_job = time.time()
			return True
		except:
			self.logger.log("%d: Error getting work! Retrying..." % fpga.id)
			fpga.last_job = None
			return False

	def sendGold(self, gold):
		hexnonce = pack('I', long(gold.nonce)).encode('hex') # suggested by m0mchil
		data = gold.job.data[:128+24] + hexnonce + gold.job.data[128+24+8:]
		
		(self.connection, accepted) = self.getwork(self.connection, gold.fpgaID, data)
		if self.connection is None:
			return False
		
		self.logger.reportFound(hex(gold.nonce)[2:], accepted, gold.fpgaID)
		return True
		
	def queue_work(self, work):
		# Empty the gold queue:
		while True:
			try:
				self.goldqueue.get(False)
			except Empty:
				break
		for fpga in self.fpga_list:
			try:
				# A long-poll event returns a new job, so load that one on the first chain:
				self.getNewJob(fpga, work)
				# Clear that job so that getNewJob will fetch a new one when called on subsequent chains:
				work = None
			except:
				pass
	
	def getwork_loop(self):
		for fpga in self.fpga_list:
			self.getNewJob(fpga)
		
		while True:
			time.sleep(0.1)
			
			for fpga in self.fpga_list:
				if fpga.last_job is None or (time.time() - fpga.last_job) > self.getwork_interval:
					self.getNewJob(fpga)
			
			gold = None
			try:
				gold = self.goldqueue.get(False)
			except Empty:
				gold = None

			if gold is not None:
				retries_left = self.NUM_RETRIES
				success = self.sendGold(gold)
				while not success and retries_left > 0:
					self.logger.reportDebug("%d: Error sending nonce! Retrying..." % gold.fpgaID)
					success = self.sendGold(gold)
					retries_left -= 1
				if not success:
					self.logger.reportFound(hex(gold.nonce)[2:], False, gold.fpgaID)
	
	def longpoll_loop(self):
		last_host = None
		while True:
			time.sleep(1)
			url = self.long_poll_url
			if url != '':
				proto = self.proto
				host = self.host
				parsedUrl = urlsplit(url)
				if parsedUrl.scheme != '':
					proto = parsedUrl.scheme
				if parsedUrl.netloc != '':
					host = parsedUrl.netloc
					url = url[url.find(host) + len(host):]
					if url == '': url = '/'
				try:
					if host != last_host: self.close_lp_connection()
					if not self.lp_connection:
						self.lp_connection = self.connect(proto, host, self.long_poll_timeout)
						self.logger.reportLongPoll("connected to %s" % host)
						last_host = host
					
					self.long_poll_active = True
					(self.lp_connection, result) = self.request(self.lp_connection, url, self.headers)
					self.long_poll_active = False
					self.logger.reportLongPoll('new block %s%s' % (result['result']['data'][56:64], result['result']['data'][48:56]))
					self.queue_work(result['result'])
					
				except NotAuthorized:
					self.logger.reportLongPoll('wrong username or password')
				except RPCError as e:
					self.logger.reportLongPoll('RPCError! %s' % e)
				except IOError as e:
					self.logger.reportLongPoll('IOError! %s' % e)
					self.close_lp_connection()
				except httplib.HTTPException:
					self.logger.reportLongPoll('HTTPException!')
					self.close_lp_connection()
				except ValueError as e:
					self.logger.reportLongPoll('ValueError! %s' % e)
					self.close_lp_connection()
					
	def close_lp_connection(self):
		if self.lp_connection:
			self.lp_connection.close()
			self.lp_connection = None

