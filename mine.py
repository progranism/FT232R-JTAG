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
parser.add_option("-c", "--chain", type="int", dest="chain", default=0,
                  help="JTAG chain number, can be 0, 1, or 2 for both FPGAs on the board (default 0)")
parser.add_option("-i", "--interval", type="int", dest="getwork_interval", default=20,
                  help="Getwork interval in seconds (default 20)")
parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False,
                  help="Verbose logging")
parser.add_option("-p", "--pool", type="str", dest="pool",
                  help="URL for the pool, e.g. pool.com:8337")
parser.add_option("-u", "--user", type="str", dest="user",
                  help="Username and password for the pool, e.g. user:pass")
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

	#print "Read: %.04X" % byte

	if byte < 0x1000:
		return None

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

		if byte is None:
			jtag.tap.reset()
			return None

		if (byte & 0xF00) == 0b111100000000:
			break
	
	# We now have the first byte
	nonce = byte & 0xFF
	count = 1
	#print "Potential nonce, reading the rest..."
	while True:
		byte = fpgaReadByte(jtag)

		if byte is None:
			continue

		nonce |= (byte & 0xFF) << (count * 8)
		count += 1

		if (byte & 0xF00) == 0b000100000000:
			break

	jtag.tap.reset()

	#print "Nonce completely read: %.08X" % nonce

	return nonce

# TODO: This may not actually clear the queue, but should be correct most of the time.
def fpgaClearQueue(jtag):
	#print "Clearing queue..."

	while True:
		jtag.tap.reset()	# Gives extra time for the FPGA's FIFO to get the next byte ready.

		if fpgaReadNonce(jtag) is None:
			break
	
	#print "Queue cleared."

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

	#print "Loading job data..."

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
	
	logger.reportDebug("(FPGA%d) Job data loaded in %f seconds" % (jtag.chain, (time.time() - start_time)))

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
	print msg
	exit()

def getwork(connection, data=None):
	try:
		if not connection:
			connection = connect(proto, host, timeout)
			#connection.set_debuglevel(1)
		postdata['params'] = [data] if data is not None else []
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
	(connection, accepted) = getwork(connection, data)
	#rpc_lock.release()
	
	logger.reportFound(hex(gold.nonce)[2:], accepted, chain)
	return connection
	

def getworkloop(chain):
	connection = None
	(connection, work) = getwork(connection)
	if connection is not None:
		logger.reportConnected(True)
	if work is not None:
		job = Object()
		job.midstate = work['midstate']
		job.data = work['data']
		jobqueue[chain].put(job)
		if chain > 0:
			last_job = time.time() + settings.getwork_interval/2
		else:
			last_job = time.time()
	elif chain > 0:
		last_job = time.time() - settings.getwork_interval/2
	else:
		last_job = time.time() - settings.getwork_interval

	while True:
		#time.sleep(0.1)

		if last_job is None or (time.time() - last_job) > settings.getwork_interval:
			#rpc_lock.acquire()
			(connection, work) = getwork(connection)
			#rpc_lock.release()

			
			try:
				job = Object()
				job.midstate = work['midstate']
				job.data = work['data']
				jobqueue[chain].put(job)
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
	
	while True:
		#time.sleep(0.1)
		job = None
		try:
			job = jobqueue[chain].get(False)
		except Empty:
			job = None
		
		if job is not None:
			ft232r_lock.acquire()
			#t1 = time.time()
			if current_job is not None:
				nonce = fpgaReadNonce(jtag[chain])
			fpgaWriteJob(jtag[chain], job)
			#fpgaClearQueue(jtag[chain])
			ft232r_lock.release()
			if current_job is not None and nonce is not None:
				#logger.reportDebug("(FPGA%d) Golden nonce found" % chain)
				gold = Object()
				gold.job = current_job
				gold.nonce = nonce
				try:
					goldqueue[chain].put(gold, block=True, timeout=10)
				except Full:
					logger.log("(FPGA%d) Queue error! Lost a share!" % chain)
			current_job = job
			#print "Writing took %i seconds." % (time.time() - t1)
		
		if current_job is not None:
			ft232r_lock.acquire()
			#t1 = time.time()
			nonce = fpgaReadNonce(jtag[chain])
			ft232r_lock.release()
			#print "Reading took %i seconds." % (time.time() - t1)

			if nonce is not None:
				logger.reportDebug("(FPGA%d) Golden nonce found" % chain)
				gold = Object()
				gold.job = current_job
				gold.nonce = nonce
				try:
					goldqueue[chain].put(gold, block=True, timeout=10)
				except Full:
					logger.log("(FPGA%d) Queue error! Lost a share!" % chain)


proto = "http"
if settings.pool is None:
	print "ERROR: Pool not specified!"
	parser.print_usage()
	exit()
host = settings.pool
if settings.user is None:
	print "ERROR: User not specified!"
	parser.print_usage()
	exit()
postdata = {'method': 'getwork', 'id': 1}
headers = {"User-Agent": 'FPGAMiner', 
           "Authorization": 'Basic ' + b64encode(settings.user),
           "Content-Type": 'application/json'
          }
timeout = 5

logger = ConsoleLogger(settings.chain, settings.verbose)

try:
	with FT232R() as ft232r:
		portlist = FT232R_PortList(7, 6, 5, 4, 3, 2, 1, 0)
		ft232r.open(settings.devicenum, portlist)
		logger.log("Device %d opened" % settings.devicenum)
		
		if settings.chain == 0 or settings.chain == 1:
			chain_list = [settings.chain]
		elif settings.chain == 2:
			chain_list = [0, 1]
		else:
			logger.log("ERROR: Invalid chain option!")
			parser.print_usage()
			exit()
		
		jtag = []
		fpga_num = 0
		for chain in chain_list:
			jtag.append(JTAG(ft232r, portlist.chain_portlist(chain), chain))
			
			logger.reportDebug("Discovering JTAG chain %d ..." % chain)
			jtag[chain].detect()
			
			logger.reportDebug("Found %i device%s ..." % (jtag[chain].deviceCount,
				's' if jtag[chain].deviceCount != 1 else ''))

			for idcode in jtag[chain].idcodes:
				msg = "FPGA" + str(chain) + ": "
				msg += JTAG.decodeIdcode(idcode)
				logger.reportDebug(msg)
				fpga_num += 1
		
		logger.log("Connected to %d FPGAs" % fpga_num)
		
		getworkthread = []
		minethread = []
		
		jobqueue = []
		goldqueue = []
		
		ft232r_lock = Lock()
		rpc_lock = Lock()
		
		logger.start()
		for chain in chain_list:
			jobqueue.append(Queue())
			goldqueue.append(Queue())
			
			# Start HTTP thread(s)
			getworkthread.append(Thread(target=getworkloop, args=(chain,)))
			getworkthread[chain].daemon = True
			getworkthread[chain].start()
			
			# Start mining thread(s)
			minethread.append(Thread(target=mineloop, args=(chain,)))
			minethread[chain].daemon = True
			minethread[chain].start()
		
		while True:
			time.sleep(1)
			logger.updateStatus()
			for chain in chain_list:
				if not getworkthread[chain].isAlive():
					logger.log("Restarting getworkthread for chain %d" % chain)
					getworkthread[chain] = Thread(target=getworkloop, args=(chain,))
					getworkthread[chain].daemon = True
					getworkthread[chain].start()
				if not minethread[chain].isAlive():
					logger.log("Restarting minethread for chain %d" % chain)
					minethread[chain] = Thread(target=mineloop, args=(chain,))
					minethread[chain].daemon = True
					minethread[chain].start()
except KeyboardInterrupt:
	logger.log("Exiting...")
	logger.printSummary(settings)
