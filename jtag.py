# Usage Example:
# with JTAG() as jtag:
# 	blah blah blah ...
#

from TAP import TAP
import time


class NoDevicesDetected(Exception): pass
class IDCodesNotRead(Exception): pass
class ChainNotProperlyDetected(Exception): pass
class InvalidChain(Exception): pass
class WriteError(Exception): pass

class UnknownIDCode(Exception):
	def __init__(self, idcode):
		self.idcode = idcode
	def __str__(self):
		return repr(self.idcode)

# A dictionary, which allows us to look up a jtag device's IDCODE and see
# how big its Instruction Register is (how many bits). This is entered manually
# but could, in the future, be read automatically from a database of BSDL files.
irlength_lut = {0x403d093: 6, 0x401d093: 6, 0x4008093: 6, 0x5057093: 16, 0x5059093: 16};

class JTAG():
	def __init__(self, ft232r, portlist, chain):
		self.ft232r = ft232r
		self.chain = chain
		self.deviceCount = None
		self.idcodes = None
		self.irlengths = None
		self.current_instructions = [1] * 100	# Default is to put all possible devices into BYPASS. # TODO: Should be 1000
		self.current_part = 0
		self._tckcount = 0
		self.portlist = portlist
		self.debug = 0

		self.tap = TAP(self.jtagClock)
	
	def _log(self, msg, level=1):
		if level <= self.debug:
			print "  JTAG:", msg
	
	# Detect all devices on the JTAG chain. Call this after open.
	def detect(self):
		self.deviceCount = None
		self.idcodes = None
		self.irlengths = None

		self._readDeviceCount()
		self._readIdcodes()
		self._processIdcodes()

		self.reset()
		self.part(0)
		self.ft232r.flush()
	
	# Change the active part.
	def part(self, part):
		self.current_part = part
	
	def instruction(self, instruction):
		if self.irlengths is None:
			raise ChainNotProperlyDetected()

		start = sum(self.irlengths[self.current_part+1:])
		end = start + self.irlengths[self.current_part]

		for i in range(len(self.current_instructions)):
			if i >= start and i < end:
				self.current_instructions[i] = instruction & 1
				instruction >>= 1
			else:
				self.current_instructions[i] = 1

	# Reset JTAG chain
	def reset(self):
		total_ir = 100 # TODO: Should be 1000
		if self.irlengths is not None:
			total_ir = sum(self.irlengths)
			self._log("total_ir = " + str(total_ir), 2)

		self.current_instructions = [1] * total_ir
		#self.shift_ir()
		self.tap.reset()
	
	def shift_ir(self, read=False):
		self.tap.goto(TAP.SELECT_IR)
		self.tap.goto(TAP.SHIFT_IR)
		
		self._log("current_instructions = " + str(self.current_instructions), 2)

		for bit in self.current_instructions[:-1]:
			self.jtagClock(tdi=bit)
		self.jtagClock(tdi=self.current_instructions[-1], tms=1)

		self._tckcount = 0
		self.tap.goto(TAP.IDLE)

		if read:
			return self.read_tdo(len(self.current_instructions)+self._tckcount)[:-self._tckcount]
	
	def read_ir(self):
		return self.shift_ir(read=True)
	
	# TODO: Doesn't work correctly if not operating on the last device in the chain
	def shift_dr(self, bits, read=False):
		self.tap.goto(TAP.SELECT_DR)
		self.tap.goto(TAP.SHIFT_DR)

		bits += [0] * self.current_part

		for bit in bits[:-1]:
			self.jtagClock(tdi=bit)
		self.jtagClock(tdi=bits[-1], tms=1)

		self._tckcount = 0
		self.tap.goto(TAP.IDLE)

		if read:
			return self.read_tdo(len(bits)+self._tckcount)[:len(bits)-self.current_part]
	
	def read_dr(self, bits):
		return self.shift_dr(bits, read=True)
		
	def read_tdo(self, num):
		data = self.ft232r.read_data(num)
		self._log("read_tdo(%d): len(data) = %d" % (num, len(data)), 2)
		bits = []
		for n in range(len(data)/3):
			bits.append((ord(data[n*3+2]) >> self.portlist.tdo)&1)
		
		return bits
	
	# Clock TCK in the IDLE state for tckcount cycles
	def runtest(self, tckcount):
		self.tap.goto(TAP.IDLE)
		for i in range(tckcount):
			self.jtagClock(tms=0)
	
	# Use to shift lots of bytes into DR.
	# TODO: Assumes current_part is the last device in the chain.
	# TODO: Assumes data is MSB first.
	def bulk_shift_dr(self, data, progressCallback=None):
		self.tap.goto(TAP.SELECT_DR)
		self.tap.goto(TAP.SHIFT_DR)
		self.ft232r.flush()
		
		bytetotal = len(data)

		print "Pre-processing..."
		# Pre-process
		# TODO: Some way to cache this...
		start_time = time.time()
		chunk = ""
		chunks = []
		CHUNK_SIZE = 4096*4

		for b in data[:-1]:
			d = ord(b)
			
			for i in range(7, -1, -1):
				x = (d >> i) & 1
				chunk += self._formatJtagClock(tdi=x)

			if len(chunk) >= CHUNK_SIZE:
				chunks.append(chunk)
				chunk = ""

		last_bits = []
		d = ord(data[-1])
		for i in range(7, -1, -1):
			last_bits.append((d >> i) & 1)

		for i in range(self.current_part):
			last_bits.append(0)

		if len(chunk) > 0:
			chunks.append(chunk)

		print "Processed in %d secs." % (time.time() - start_time)
		self.ft232r._setAsyncMode()
		
		print "Writing..."
		written = 0
		start_time = time.time()
		
		for chunk in chunks:
			wrote = self.ft232r.handle.write(chunk)
			if wrote != len(chunk):
				raise WriteError()
			written += len(chunk) / 16
			
			if (written % (16 * 1024)) == 0 and progressCallback:
				progressCallback(start_time, time.time(), written, bytetotal)
		
		progressCallback(start_time, time.time(), written, bytetotal)
		
		print ""
		print "Loaded bitstream in %d secs." % (time.time() - start_time)
		
		self._log("Status: " + str(self.ft232r.handle.getStatus()))
		self._log("QueueStatus: " + str(self.ft232r.handle.getQueueStatus()))
		self.ft232r._setSyncMode()
		self.ft232r._purgeBuffers()
		self._log("Status: " + str(self.ft232r.handle.getStatus()))
		self._log("QueueStatus: " + str(self.ft232r.handle.getQueueStatus()))
		
		for bit in last_bits[:-1]:
			self.jtagClock(tdi=bit)
		self.jtagClock(tdi=last_bits[-1], tms=1)
		
		self.tap.goto(TAP.IDLE)
		self.ft232r.flush()
		self._log("Status: " + str(self.ft232r.handle.getStatus()))
		self._log("QueueStatus: " + str(self.ft232r.handle.getQueueStatus()))
	
	# Run a stress test of the JTAG chain to make sure communications
	# will run properly.
	# This amounts to running the readChain function a hundred times.
	# Communication failure will be seen as an exception.
	def stressTest(self, testcount=100):
		self._log("Stress testing...", 0)

		self.readChain()
		oldDeviceCount = self.deviceCount

		for i in range(testcount):
			self.readChain()

			if self.deviceCount != oldDeviceCount:
				FT232RJTAG_Exception("Stress Test Failed. Device count did not match between iterations.")

			complete = i * 100 / testcount
			old_complete = (i - 1) * 100 / testcount

			if (i > 0) and (complete > 0) and (complete != old_complete):
				self._log("%i%% Complete" % complete, 0)

		self._log("Stress test complete. Everything worked correctly.", 0)

	def _formatJtagClock(self, tms=0, tdi=0):
		return self._formatJtagState(0, tms, tdi) + self._formatJtagState(1, tms, tdi)
	
	def _formatJtagState(self, tck, tms, tdi):
		return self.portlist.format(tck, tms, tdi)

	def jtagClock(self, tms=0, tdi=0):		
		self.ft232r.write_buffer += self._formatJtagState(0, tms, tdi)
		self.ft232r.write_buffer += self._formatJtagState(1, tms, tdi)
		self.ft232r.write_buffer += self._formatJtagState(1, tms, tdi)

		self.tap.clocked(tms)
		self._tckcount += 1

	# TODO: Why is the data sent backwards!?!?!
	# NOTE: It seems that these are designed specifically for Xilinx's
	# weird bit ordering when writing to CFG registers. Most specifically,
	# bitstreams are sent MSB first.
	#def sendByte(self, val, last=True):
	#	for n in range(7, -1, -1):
	#		self.jtagClock((n == 0) & last, (val >> n) & 1)
	#
	#def readByte(self, val, last=True):
	#	result = 0
	#
	#	for n in range(7, -1, -1):
	#		bit = self.jtagClock((n == 0) & last, (val >> n) & 1)
	#		result |= bit << (7 - n)
	#
	#	return result

	def parseByte(self, bits):
		return (bits[7] << 7) | (bits[6] << 6) | (bits[5] << 5) | (bits[4] << 4) | (bits[3] << 3) | (bits[2] << 2) |  (bits[1] << 1) | bits[0]
	
	#def tapReset(self):
	#	for i in range(0, 6):
	#		self.jtagClock(tms=1)
	
	def _readDeviceCount(self):
		self.deviceCount = None

		#self.tap.reset()

		# Force BYPASS
		self.reset()
		self.part(0)

		# Force BYPASS
		self.shift_ir()
		#self.shiftIR([1]*100)	# Should be 1000

		# Flush DR registers
		self.shift_dr([0]*100)

		# Fill with 1s to detect chain length
		data = self.read_dr([1]*100)
		self._log("_readDeviceCount: len(data): " + str(len(data)), 2)

		# Now see how many devices there were.
		for i in range(0, len(data)-1):
			if data[i] == 1:
				self.deviceCount = i
				break

		if self.deviceCount is None or self.deviceCount == 0:
			self.deviceCount = None
			raise NoDevicesDetected()

	
	def _readIdcodes(self):
		if self.deviceCount is None:
			raise NoDevicesDetected()

		self.idcodes = []

		#self.tap.reset()
		self.reset()
		self.part(0)

		data = self.read_dr([1]*32*self.deviceCount)
		
		self._log("_readIdcodes: len(data): " + str(len(data)), 2)

		for d in range(self.deviceCount):
			idcode = self.parseByte(data[0:8])
			idcode |= self.parseByte(data[8:16]) << 8
			idcode |= self.parseByte(data[16:24]) << 16
			idcode |= self.parseByte(data[24:32]) << 24
			data = data[32:]

			self.idcodes.insert(0, idcode)

	def _processIdcodes(self):
		if self.idcodes is None:
			raise IDCodesNotRead()

		self.irlengths = []

		for idcode in self.idcodes:
			if (idcode & 0x0FFFFFFF) in irlength_lut:
				self.irlengths.append(irlength_lut[idcode & 0x0FFFFFFF])
			else:
				self.irlengths = None
				raise UnknownIDCode(idcode)
			

	@staticmethod
	def decodeIdcode(idcode):
		if (idcode & 1) != 1:
			print "Warning: Bit 0 of IDCODE is not 1. Not a valid Xilinx IDCODE."

		manuf = (idcode >> 1) & 0x07ff
		size = (idcode >> 12) & 0x01ff
		family = (idcode >> 21) & 0x007f
		rev = (idcode >> 28) & 0x000f

		print "Device ID: %.8X" % idcode
		print "Manuf: %x, Part Size: %x, Family Code: %x, Revision: %0d" % (manuf, size, family, rev)
	
#	def buildInstruction(self, deviceid, instruction):
#		if self.irlengths is None:
#			raise FT232RJTAG_Exception("IRLengths are unknown.")
#
#		result = []
#
#		for d in range(self.deviceCount - 1, -1, -1):
#			for i in range(0, self.irlengths[d]):
#				if d == deviceid:
#					result.append(instruction & 1)
#					instruction = instruction >> 1
#				else:
#					result.append(1)
#
#		return result
#	
#	# Load an instruction into a single device, BYPASSing the others.
#	# Leaves the TAP at IDLE.
#	def singleDeviceInstruction(self, deviceid, instruction):
#		self.tapReset()
#
#		self.jtagClock(tms=0)
#		self.jtagClock(tms=1)
#		self.jtagClock(tms=1)
#		self.jtagClock(tms=0)
#		self.jtagClock(tms=0)
#
#		bits = self.buildInstruction(deviceid, instruction)
#		#print bits, len(bits)
#		self.jtagWriteBits(bits, last=True)
#
#		self.jtagClock(tms=1)
#		self.jtagClock(tms=0)
	
	# TODO: Currently assumes that deviceid is the last device in the chain.
	# TODO: Assumes TAP is in IDLE state.
	# Leaves the device in IDLE state.
	#def shiftDR(self, deviceid, bits):
	#	self.jtagClock(tms=1)
	#	self.jtagClock(tms=0)
	#	self.jtagClock(tms=0)
#
#		readback = self.jtagWriteBits(bits, last=(self.deviceCount==1))
#		
#		for d in range(self.deviceCount-2):
#			self.jtagClock(tms=0)
#
#		if self.deviceCount > 1:
#			self.jtagClock(tms=1)
#
#		self.jtagClock(tms=1)
#		self.jtagClock(tms=0)
#
#		return readback

	# TODO: Perform in a single D2XX.Write call.
	# TODO: ^ Be careful not to fill the RX buffer (128 bytes).
#	def jtagWriteBits(self, bits, last=False):
#		readback = []
#
#		for b in bits[:-1]:
#			readback.append(self.jtagClock(tdi=b, tms=0))
#		readback.append(self.jtagClock(tdi=bits[-1], tms=(last&1)))
#
#		return readback
#
#	# Read the Configuration STAT register
#	def sendJprogram(self, deviceid):
#		if self.handle is None or self.irlengths is None:
#			raise FT232RJTAG_Exception("IRLengths is None.")
#
#		self.singleDeviceInstruction(deviceid, 0xB)
#
#		self.tapReset()
#		self.tapReset()
#		self.tapReset()
#		self.tapReset()



