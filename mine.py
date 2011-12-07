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

from ft232r import FT232R, FT232R_PortList
from jtag import JTAG
import time
from optparse import OptionParser
import traceback
from base64 import b64encode
from json import dumps, loads
from threading import Thread, Lock
from Queue import Queue, Empty
import httplib
import socket
from ConsoleLogger import ConsoleLogger

NUM_RETRIES = 5
USER_INSTRUCTION = 0b000010

# Option parsing:
parser = OptionParser(usage="%prog [-d <devicenum>] [-c <chain>] -p <pool-url> -u <user:pass>")
parser.add_option("-d", "--devicenum", type="int", dest="devicenum", default=0,
                  help="Device number, default 0 (only needed if you have more than one board)")
parser.add_option("-c", "--chain", type="int", dest="chain", default=2,
                  help="JTAG chain number, can be 0, 1, or 2 for both FPGAs on the board (default 2)")
parser.add_option("-i", "--interval", type="int", dest="getwork_interval", default=30,
                  help="Getwork interval in seconds (default 30)")
parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False,
                  help="Verbose logging")
parser.add_option("-u", "--url", type="str", dest="url",
                  help="URL for the pool or bitcoind server, e.g. pool.com:8337")
parser.add_option("-w", "--worker", type="str", dest="worker",
                  help="Worker username and password for the pool, e.g. user:pass")
settings, args = parser.parse_args()

# Socket wrapper to enable socket.TCP_NODELAY and KEEPALIVE
realsocket = socket.socket
def socketwrap(family=socket.AF_INET, type=socket.SOCK_STREAM, proto=0):
	sockobj = realsocket(family, type, proto)
	sockobj.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
	sockobj.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
	return sockobj
socket.socket = socketwrap

class NotAuthorized(Exception): pass
class RPCError(Exception): pass

class Object(object):
	pass

# Convert a hex string into an array of bytes
def hexstr2array(hexstr):
	arr = []

	for i in range(len(hexstr)/2):
		arr.append((int(hexstr[i*2], 16) << 4) | int(hexstr[i*2+1], 16))
	
	return arr

# Convert an integer to an array of bits.
# LSB first.
def int2bits(i, bits):
	result = []

	for n in range(bits):
		result.append(i & 1)
		i = i >> 1
	
	return result

# LSB first.
def bits2int(bits):
	x = 0

	for i in range(len(bits)):
		x |= bits[i] << i
	
	return x

def fpgaReadByte(jtag):
	bits = int2bits(0, 13)
	byte = bits2int(jtag.read_dr(bits))
	return byte

def fpgaReadNonce(jtag):
	jtag.tap.reset()
	jtag.instruction(USER_INSTRUCTION)
	jtag.shift_ir()

	# Sync to the beginning of a nonce.
	# The MSB is a VALID flag. If 0, data is invalid (queue empty).
	# The next 4-bits indicate which byte of the nonce we got.
	# 1111 is LSB, and then 0111, 0011, 0001.
	byte = None
	while True:
		byte = fpgaReadByte(jtag)

		if byte < 0x1000:
			jtag.tap.reset()
			return None
		
		#logger.reportDebug("(FPGA%d) Read: %04x" % (jtag.chain, byte))
		
		if (byte & 0xF00) == 0xF00:
			break
	
	# We now have the first byte
	nonce = byte & 0xFF
	count = 1
	timeout = 0
	#logger.reportDebug("(FPGA%d) Potential nonce, reading the rest..." % jtag.chain)
	while True:
		byte = fpgaReadByte(jtag)

		#logger.reportDebug("(FPGA%d) Read: %04x" % (jtag.chain, byte))
		
		if byte < 0x1000:
			jtag.tap.reset()
			return None

		nonce |= (byte & 0xFF) << (count * 8)
		count += 1

		if (byte & 0xF00) == 0x100:
			break

	jtag.tap.reset()

	#logger.reportDebug("Nonce completely read: %08x" % nonce)

	return nonce

# TODO: This may not actually clear the queue, but should be correct most of the time.
def fpgaClearQueue(jtag):
	logger.reportDebug("(FPGA%d) Clearing queue..." % jtag.chain)

	jtag.tap.reset()
	jtag.instruction(USER_INSTRUCTION)
	jtag.shift_ir()
	
	while True:
		if fpgaReadByte(jtag) < 0x1000:
			break
	
	jtag.tap.reset()
	
	logger.reportDebug("(FPGA%d) Queue cleared." % jtag.chain)

def fpgaWriteJob(jtag, job):
	# We need the 256-bit midstate, and 12 bytes from data.
	# The first 64 bytes of data are already hashed (hence midstate),
	# so we skip that. Of the last 64 bytes, 52 bytes are constant and
	# not needed by the FPGA.
	start_time = time.time()
	
	midstate = hexstr2array(job.midstate)
	data = hexstr2array(job.data)[64:64+12]

	# Job's hex strings are LSB first, and the FPGA wants them MSB first.
	midstate.reverse()
	data.reverse()

	#logger.reportDebug("(FPGA%d) Loading job data..." % jtag.chain)

	#start_time = time.time()
	#jtag._setAsyncMode()
	#jtag.async_record = ""
	
	jtag.instruction(USER_INSTRUCTION)
	jtag.shift_ir()

	data = midstate + data + [0]

	for i in range(len(data)):
		x = data[i]

		if i != 0:
			x = 0x100 | x
			
		jtag.shift_dr(int2bits(x, 13))
	
	jtag.tap.reset()

	#print "It took %f seconds to record async data." % (time.time() - start_time)

	ft232r.flush()

	#print "It took %.1f seconds to write data." % (time.time() - start_time)
	
	logger.reportDebug("(FPGA%d) Job data loaded in %.3f seconds" % (jtag.chain, (time.time() - start_time)))

def connect(proto, host, timeout):
	connector = httplib.HTTPSConnection if proto == 'https' else httplib.HTTPConnection

	return connector(host, strict=False, timeout=timeout)

def request(connection, url, headers, data=None):
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

def failure(msg):
	logger.log(msg)
	exit()

def getwork(connection, chain, data=None):
	try:
		if not connection:
			logger.reportDebug("(FPGA%d) Connecting..." % chain)
			connection = connect(proto, host, timeout)
			#connection.set_debuglevel(1)
		if data is None:
			postdata['params']  = []
			#logger.reportDebug("(FPGA%d) Requesting work..." % chain)
		else:
			postdata['params'] = [data]
			#logger.reportDebug("(FPGA%d) Submitting nonce..." % chain)
		(connection, result) = request(connection, '/', headers, dumps(postdata))
		return (connection, result['result'])
	except NotAuthorized:
		failure('Wrong username or password.')
	except RPCError as e:
		logger.reportDebug("RPCError! %s" % e)
		return (connection, e)
	except IOError:
		logger.reportDebug("IOError!")
	except ValueError:
		logger.reportDebug("ValueError!")
	except httplib.HTTPException:
		#logger.reportDebug("HTTP Error!")
		pass
	return (None, None)

def sendGold(connection, gold, chain):
	hexnonce = hex(gold.nonce)[8:10] + hex(gold.nonce)[6:8] + hex(gold.nonce)[4:6] + hex(gold.nonce)[2:4]
	data = gold.job.data[:128+24] + hexnonce + gold.job.data[128+24+8:]
	
	#rpc_lock.acquire()
	(connection, accepted) = getwork(connection, chain, data)
	#rpc_lock.release()
	
	logger.reportFound(hex(gold.nonce)[2:], accepted, chain)
	return connection
	

def getworkloop(chain):
	connection = None
	(connection, work) = getwork(connection, chain)
	if connection is not None:
		logger.reportConnected(True)
	last_job = None
	if work is not None:
		try:
			job = Object()
			job.midstate = work['midstate']
			job.data = work['data']
			jobqueue[chain].put(job)
			#logger.reportDebug("(FPGA%d) jobqueue loaded (%d)" % (chain, jobqueue[chain].qsize()))
			last_job = time.time()
		except:
			logger.log("(FPGA%d) Error getting work! Retrying..." % chain)
			last_job = None

	while True:
		time.sleep(0.1)

		if last_job is None or (time.time() - last_job) > settings.getwork_interval:
			#rpc_lock.acquire()
			(connection, work) = getwork(connection, chain)
			#rpc_lock.release()

			
			try:
				job = Object()
				job.midstate = work['midstate']
				job.data = work['data']
				jobqueue[chain].put(job)
				#logger.reportDebug("(FPGA%d) jobqueue loaded (%d)" % (chain, jobqueue[chain].qsize()))
				last_job = time.time()
			except:
				logger.log("(FPGA%d) Error getting work! Retrying..." % chain)
				last_job = None

		gold = None
		try:
			gold = goldqueue[chain].get(False)
		except Empty:
			gold = None

		if gold is not None:
			retries_left = NUM_RETRIES
			connection = sendGold(connection, gold, chain)
			while connection is None and retries_left > 0:
				connection = sendGold(connection, gold, chain)
				retries_left -= 1

def mineloop(chain):
	current_job = None
	ft232r_lock.acquire()
	fpgaClearQueue(jtag[chain])
	ft232r_lock.release()
	
	while True:
		time.sleep(0.1)
		job = None
		nonce = None
		
		try:
			#logger.reportDebug("(FPGA%d) Checking for new job..." % chain)
			job = jobqueue[chain].get(False)
		except Empty:
			job = None
		
		if job is not None:
			#logger.reportDebug("(FPGA%d) Loading new job..." % chain)
			ft232r_lock.acquire()
			if current_job is not None:
				#logger.reportDebug("(FPGA%d) Checking for nonce*..." % chain)
				nonce = fpgaReadNonce(jtag[chain])
			#logger.reportDebug("(FPGA%d) Writing job..." % chain)
			fpgaWriteJob(jtag[chain], job)
			#fpgaClearQueue(jtag[chain])
			ft232r_lock.release()
			if nonce is not None:
				logger.reportDebug("(FPGA%d) Golden nonce found" % chain)
				gold = Object()
				gold.job = current_job
				gold.nonce = nonce
				try:
					goldqueue[chain].put(gold, block=True, timeout=10)
					#logger.reportDebug("(FPGA%d) goldqueue loaded (%d)" % (chain, goldqueue[chain].qsize()))
				except Full:
					logger.log("(FPGA%d) Queue error! Lost a share!" % chain)
			#else:
			#	logger.reportDebug("(FPGA%d) No nonce found" % chain)
			current_job = job
		
		if current_job is not None:
			#logger.reportDebug("(FPGA%d) Checking for nonce..." % chain)
			ft232r_lock.acquire()
			nonce = fpgaReadNonce(jtag[chain])
			ft232r_lock.release()
			
			if nonce is not None:
				logger.reportDebug("(FPGA%d) Golden nonce found" % chain)
				gold = Object()
				gold.job = current_job
				gold.nonce = nonce
				try:
					goldqueue[chain].put(gold, block=True, timeout=10)
					#logger.reportDebug("(FPGA%d) goldqueue loaded (%d)" % (chain, goldqueue[chain].qsize()))
				except Full:
					logger.log("(FPGA%d) Queue error! Lost a share!" % chain)
			#else:
			#	logger.reportDebug("(FPGA%d) No nonce found" % chain)


proto = "http"
if settings.url is None:
	print "ERROR: URL not specified!"
	parser.print_usage()
	exit()
host = settings.url
if settings.worker is None:
	print "ERROR: Worker not specified!"
	parser.print_usage()
	exit()
postdata = {'method': 'getwork', 'id': 1}
headers = {"User-Agent": 'FPGAMiner', 
           "Authorization": 'Basic ' + b64encode(settings.worker),
           "Content-Type": 'application/json'
          }
timeout = 5

logger = ConsoleLogger(settings.chain, settings.verbose)

try:
	with FT232R() as ft232r:
		portlist = FT232R_PortList(7, 6, 5, 4, 3, 2, 1, 0)
		ft232r.open(settings.devicenum, portlist)
		logger.reportOpened(settings.devicenum, ft232r.serial)
		
		if settings.chain == 0 or settings.chain == 1:
			chain_list = [settings.chain]
		elif settings.chain == 2:
			chain_list = [0, 1]
		else:
			logger.log("ERROR: Invalid chain option!")
			parser.print_usage()
			exit()
		
		jtag = [None, None]
		fpga_num = 0
		for chain in chain_list:
			jtag[chain] = JTAG(ft232r, portlist.chain_portlist(chain), chain)
			
			logger.reportDebug("Discovering JTAG chain %d ..." % chain)
			jtag[chain].detect()
			
			logger.reportDebug("Found %i device%s ..." % (jtag[chain].deviceCount,
				's' if jtag[chain].deviceCount != 1 else ''))

			for idcode in jtag[chain].idcodes:
				msg = " FPGA" + str(chain) + ": "
				msg += JTAG.decodeIdcode(idcode)
				logger.reportDebug(msg)
				fpga_num += 1
		
		logger.log("Connected to %d FPGAs" % fpga_num)
		
		getworkthread = [None, None]
		minethread = [None, None]
		
		jobqueue = [None, None]
		goldqueue = [None, None]
		
		ft232r_lock = Lock()
		rpc_lock = Lock()
		
		logger.start()
		for chain in chain_list:
			jobqueue[chain] = Queue()
			goldqueue[chain] = Queue()
			
			# Start HTTP thread(s)
			getworkthread[chain] = Thread(target=getworkloop, args=(chain,))
			getworkthread[chain].daemon = True
			getworkthread[chain].start()
			
			# Start mining thread(s)
			minethread[chain] = Thread(target=mineloop, args=(chain,))
			minethread[chain].daemon = True
			minethread[chain].start()
		
		while True:
			time.sleep(1)
			logger.updateStatus()
			for chain in chain_list:
				if getworkthread[chain] is None or not getworkthread[chain].isAlive():
					logger.log("Restarting getworkthread for chain %d" % chain)
					getworkthread[chain] = Thread(target=getworkloop, args=(chain,))
					getworkthread[chain].daemon = True
					getworkthread[chain].start()
				if minethread[chain] is None or not minethread[chain].isAlive():
					logger.log("Restarting minethread for chain %d" % chain)
					minethread[chain] = Thread(target=mineloop, args=(chain,))
					minethread[chain].daemon = True
					minethread[chain].start()
except KeyboardInterrupt:
	logger.log("Exiting...")
	logger.printSummary(settings)
