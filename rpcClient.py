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
from base64 import b64encode
from json import dumps, loads

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
	
	def __init__(self, host, worker, logger):
		self.host = host
		self.logger = logger
		self.connection = None
		self.proto = "http"
		self.postdata = {'method': 'getwork', 'id': 'json'}
		self.headers = {"User-Agent": 'x6500-miner',
		                "Authorization": 'Basic ' + b64encode(worker),
		                "Content-Type": 'application/json'
		               }
		self.timeout = 5

	def connect(self):
		connector = httplib.HTTPSConnection if self.proto == 'https' else httplib.HTTPConnection
		return connector(self.host, strict=False, timeout=self.timeout)

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
				connection = self.connect()
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
			return (connection, e)
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
	