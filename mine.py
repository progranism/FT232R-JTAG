from ft232r import FT232R, FT232R_PortList
from jtag import JTAG
import time
from optparse import OptionParser
import traceback
from base64 import b64encode
from json import dumps, loads
from threading import Thread
from Queue import Queue, Empty
import httplib
import socket

# Option parsing:
parser = OptionParser(usage="%prog [-d <devicenum>] [-c <chain>] -p <pool-url> -u <user:pass>")
parser.add_option("-d", "--devicenum", type="int", dest="devicenum", default=0,
                  help="Device number, default 0 (only needed if you have more than one board)")
parser.add_option("-c", "--chain", type="int", dest="chain", default=0,
                  help="JTAG chain number, can be 0, 1, or 2 for both FPGAs on the board (default 0)")
parser.add_option("-p", "--pool", type="str", dest="pool",
                  help="URL for the pool, e.g. mining.eligius.st:8337")
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
	byte = bits2int(jtag.shift_dr(bits, True))

	print "Read: %.04X" % byte

	if byte < 0x1000:
		return None

	return byte

def fpgaReadNonce(jtag):
	jtag.instruction(USER_INSTRUCTION)

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
	print "Potential nonce, reading the rest..."
	while True:
		byte = fpgaReadByte(jtag)

		if byte is None:
			continue

		nonce |= (byte & 0xFF) << (count * 8)
		count += 1

		if (byte & 0xF00) == 0b000100000000:
			break

	jtag.tap.reset()

	print "Nonce completely read: %.08X" % nonce

	return nonce

# TODO: This may not actually clear the queue, but should be correct most of the time.
def fpgaClearQueue(jtag):
	print "Clearing queue..."

	while True:
		jtag.tap.reset()	# Gives extra time for the FPGA's FIFO to get the next byte ready.

		if fpgaReadNonce(jtag) is None:
			break
	
	print "Queue cleared."

def fpgaWriteJob(jtag, job):
	# We need the 256-bit midstate, and 12 bytes from data.
	# The first 64 bytes of data are already hashed (hence midstate),
	# so we skip that. Of the last 64 bytes, 52 bytes are constant and
	# not needed by the FPGA.
	midstate = hexstr2array(job.midstate)
	data = hexstr2array(job.data)[64:64+12]

	# Job's hex strings are LSB first, and the FPGA wants them MSB first.
	midstate.reverse()
	data.reverse()

	print "Loading job data..."

	start_time = time.time()
	#jtag._setAsyncMode()
	#jtag.async_record = ""

	jtag.instruction(USER_INSTRUCTION)

	data = midstate + data + [0]

	for i in range(len(data)):
		x = data[i]

		if i != 0:
			x = 0x100 | x

		jtag.shift_dr(int2bits(x, 13))
	
	jtag.tap.reset()

	#print "It took %f seconds to record async data." % (time.time() - start_time)

	start_time = time.time()
	
	ft232r.flush()

	print "It took %.1f seconds to write data." % (time.time() - start_time)

	print "Job data loaded."


# 
#def readNonce(jtag):
#	jtag.singleDeviceInstruction(jtag.deviceCount-1, USER_INSTRUCTION)
#
#	data = jtag.shiftDR(jtag.deviceCount-1, int2bits(0, 13))
#	nonce = bits2int(data)
#
#	jtag.tapReset()
#
#	return "%.04X" % nonce

def connect(proto, host, timeout):
	connector = httplib.HTTPSConnection if proto == 'https' else httplib.HTTPConnection

	return connector(host, strict=True, timeout=timeout)

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

		postdata['params'] = [data] if data is not None else []
		(connection, result) = request(connection, '/', headers, dumps(postdata))

		return (connection, result['result'])
	except NotAuthorized:
		failure('Wrong username or password.')
	except RPCError as e:
		print e
	except (IOError, httplib.HTTPException, ValueError):
		print "Problems communicating with bitcoin RPC."
	
	return (connection, None)

def sendGold(connection, gold):
	hexnonce = hex(gold.nonce)[8:10] + hex(gold.nonce)[6:8] + hex(gold.nonce)[4:6] + hex(gold.nonce)[2:4]
	data = gold.job.data[:128+24] + hexnonce + gold.job.data[128+24+8:]

	print "Nonce: ", gold.nonce
	print "Hexnonce: ", hexnonce
	print "Original Data: " + gold.job.data
	print "Nonced Data: " + data

	(connection, accepted) = getwork(connection, data)
	if accepted is not None:
		if accepted == True:
			print "accepted"
		else:
			print "_rejected_"
	
	return connection
	

def getworkloop():
	connection = None
	last_job = None

	while True:
		time.sleep(0.1)

		if last_job is None or (time.time() - last_job) > 20:
			last_job = time.time()

			(connection, work) = getwork(connection)

			if work is not None:
				job = Object()
				job.midstate = work['midstate']
				job.data = work['data']

				jobqueue.put(job)

		gold = None
		try:
			gold = goldqueue.get(False)
		except Empty:
			gold = None

		if gold is not None:
			print "SUBMITTING GOLDEN TICKET"
			connection = sendGold(connection, gold)




USER_INSTRUCTION = 0b000010
current_job = None

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
postdata = {'method': 'getwork', 'id': 'json'}
headers = {"User-Agent": 'Bitcoin Dominator ALPHA', "Authorization": 'Basic ' + b64encode(settings.user)}
timeout = 5

jobqueue = Queue()
goldqueue = Queue()


with FT232R() as ft232r:
	portlist = FT232R_PortList(7, 6, 5, 4, 3, 2, 1, 0)
	ft232r.open(settings.devicenum, portlist)
	
	if settings.chain == 0 or settings.chain == 1:
		jtag = JTAG(ft232r, portlist.chain_portlist(settings.chain), settings.chain)
		
		print "Discovering JTAG chain %d ..." % settings.chain
		jtag.detect()
		
		print "Found %i devices ...\n" % jtag.deviceCount

		for idcode in jtag.idcodes:
			JTAG.decodeIdcode(idcode)
		print ""
		
		# Start HTTP thread
		thread = Thread(target=getworkloop)
		thread.daemon = True
		thread.start()

		#job = Object()
		#job.midstate = "90f741afb3ab06f1a582c5c85ee7a561912b25a7cd09c060a89b3c2a73a48e22"
		#job.data = "000000014cc2c57c7905fd399965282c87fe259e7da366e035dc087a0000141f000000006427b6492f2b052578fb4bc23655ca4e8b9e2b9b69c88041b2ac8c771571d1be4de695931a2694217a33330e000000800000000000000000000000000000000000000000000000000000000000000000000000000000000080020000"
		#jobqueue.put(job)

		while True:
			time.sleep(1.1)

			job = None

			try:
				job = jobqueue.get(False)
			except Empty:
				job = None

			if job is not None:
				t1 = time.time()
				fpgaWriteJob(jtag, job)
				fpgaClearQueue(jtag)
				current_job = job
				print "Writing took %i seconds." % (time.time() - t1)
			
			if current_job is not None:
				t1 = time.time()
				nonce = fpgaReadNonce(jtag)
				print "Reading took %i seconds." % (time.time() - t1)

				if nonce is not None:
					print "FOUND GOLDEN TICKET"
					gold = Object()
					gold.job = current_job
					gold.nonce = nonce

					goldqueue.put(gold)

				#time.sleep(1)
				#print readNonce(jtag)

				#fpgaReadNonce(jtag)
				#fpgaClearQueue(jtag)
				#fpgaWriteJob(jtag, job)

#def readyForUser2(jtag):
#	jtag.tapReset()
#
#	jtag.jtagClock(tms=0)
#	jtag.jtagClock(tms=1)
#	jtag.jtagClock(tms=1)
#	jtag.jtagClock(tms=0)
#	jtag.jtagClock(tms=0)
#
#	jtag.jtagClock(tdi=0)
#	jtag.jtagClock(tdi=1)
#	jtag.jtagClock(tdi=0)
#	jtag.jtagClock(tdi=0)
#	jtag.jtagClock(tdi=0)
#	jtag.jtagClock(tdi=0)
#
#	for i in range(0, 31):
#		jtag.jtagClock(tdi=1)
#
#	jtag.jtagClock(tdi=1,tms=1)
#
#	# Shift-DR
#	jtag.jtagClock(tms=1, tdi=1)
#	jtag.jtagClock(tms=1, tdi=1)
#	jtag.jtagClock(tms=0, tdi=1)
#	jtag.jtagClock(tms=0, tdi=1)
#
#readyForUser2(jtag)
#
#data = midstate + data + [0]
#
#for i in range(0, len(data)):
#	x = data[i]
#
#	if i != 0:
#		x = 0x100 | x
#	
#	for j in range(13):
#		jtag.jtagClock(tdi=(x&1))
#		x >>= 1
#	
#	jtag.jtagClock(tdi=0)
#	jtag.jtagClock(tdi=0, tms=1)
#	jtag.jtagClock(tdi=0, tms=1)
#	jtag.jtagClock(tdi=0, tms=1)
#	jtag.jtagClock(tdi=0, tms=0)
#	jtag.jtagClock(tdi=0, tms=0)
#
#jtag.tapReset()
#
#print "Test data loaded.\n"
#
#def readNonce(jtag):
#	readyForUser2(jtag)
#
#	x = 0
#
#	for i in range(0, 13):
#		x |= jtag.jtagClock(tdi=0) << i
#	
#	jtag.jtagClock(tdi=0)
#	jtag.jtagClock(tdi=0, tms=1)
#
#	jtag.tapReset()
#
#	return "%.04X" % x
#
#
#while True:
#	time.sleep(1)
#	print readNonce(jtag)
#
#jtag.close()
#
#
