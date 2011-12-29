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
	
	def __init__(self, host, worker, logger, jobqueue):
		self.host = host
		self.logger = logger
		self.jobqueue = jobqueue
		self.chain_list = []
		self.proto = "http"
		self.postdata = {'method': 'getwork', 'id': 'json'}
		self.headers = {"User-Agent": 'x6500-miner',
		                "Authorization": 'Basic ' + b64encode(worker),
		                "Content-Type": 'application/json'
		               }
		self.timeout = 5
		self.long_poll_timeout = 3600
		self.long_poll_max_askrate = 60 - self.timeout
		self.long_poll_active = False
		self.long_poll_url = ''
		self.lp_connection = None
	
	def set_chain_list(self, chain_list):
		self.chain_list = chain_list

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

	def getwork(self, connection, chain, data=None):
		try:
			if not connection:
				self.logger.reportDebug("Connecting to server...")
				connection = self.connect(self.proto, self.host, self.timeout)
				#connection.set_debuglevel(1)
			if data is None:
				self.postdata['params']  = []
				#self.logger.reportDebug("(FPGA%d) Requesting work..." % chain)
			else:
				self.postdata['params'] = [data]
				#self.logger.reportDebug("(FPGA%d) Submitting nonce..." % chain)
			(connection, result) = self.request(connection, '/', self.headers, dumps(self.postdata))
			return (connection, result['result'])
		except NotAuthorized:
			failure('Wrong username or password.')
		except RPCError as e:
			self.logger.reportDebug("RPCError! %s" % e)
			return (None, None)
		except IOError as e:
			self.logger.reportDebug("IOError! %s" % e)
		except ValueError:
			self.logger.reportDebug("ValueError!")
		except httplib.HTTPException:
			#self.logger.reportDebug("HTTP Error!")
			pass
		return (None, None)

	def sendGold(self, connection, gold, chain):
		hexnonce = hex(gold.nonce)[8:10] + hex(gold.nonce)[6:8] + hex(gold.nonce)[4:6] + hex(gold.nonce)[2:4]
		data = gold.job.data[:128+24] + hexnonce + gold.job.data[128+24+8:]
		
		(connection, accepted) = self.getwork(connection, chain, data)
		if connection is None:
			return None
		
		self.logger.reportFound(hex(gold.nonce)[2:], accepted, chain)
		return connection
		
	def queue_work(self, work):
		for chain in self.chain_list:
			if work is None:
				(connection, work) = self.getwork(None, chain, None)
			try:
				job = Object()
				job.midstate = work['midstate']
				job.data = work['data']
				job.target = work['target']
				self.jobqueue[chain].put(job)
				self.logger.reportDebug("(FPGA%d) jobqueue loaded (%d)" % (chain, jobqueue[chain].qsize()))
				work = None
			except:
				self.logger.reportDebug("(FPGA%d) jobqueue not loaded!")
		
	def long_poll_thread(self):
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
				except ValueError:
					self.logger.reportLongPoll('ValueError!')
					self.close_lp_connection()
					
	def close_lp_connection(self):
		if self.lp_connection:
			self.lp_connection.close()
			self.lp_connection = None

