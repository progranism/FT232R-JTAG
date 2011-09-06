# Usage Example:
# with JTAG() as jtag:
# 	blah blah blah ...
#

from ft232r import FT232R, FT232R_PortList


class NoDevicesDetected(Exception): pass
class IDCodesNotRead(Exception): pass

class UnknownIDCode(Exception):
	def __init__(self, idcode):
		self.idcode = idcode
	def __str__(self):
		return repr(self.idcode)




# A dictionary, which allows us to look up a jtag device's IDCODE and see
# how big its Instruction Register is (how many bits). This is entered manually
# but could, in the future, be read automatically from a database of BSDL files.
irlength_lut = {0x403d093: 6, 0x401d093: 6, 0x5057093: 16, 0x5059093: 16};

class JTAG(FT232R):
	def __init__(self):
		FT232R.__init__(self)

		self.deviceCount = None
		self.idcodes = None
		self.irlengths = None
	
	def __enter__(self):
		return self

	# Be sure to close the opened handle, if there is one.
	# The device may become locked if we don't (requiring an unplug/plug cycle)
	def __exit__(self, exc_type, exc_value, traceback):
		self.close()

		return False

	def _log(self, msg, level=1):
		if level <= self.debug:
			print "FT232RJTAG: " + msg
	
	def open(self, devicenum):
		portlist = FT232R_PortList(3, 2, 1, 0)

		FT232R.open(self, devicenum, portlist)
	
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

	# TODO: Why is the data sent backwards!?!?!
	# NOTE: It seems that these are designed specifically for Xilinx's
	# weird bit ordering when reading various registers. Most specifically,
	# bitstreams are sent MSB first.
	def sendByte(self, val, last=True):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		for n in range(7, -1, -1):
			self.jtagClock((n == 0) & last, (val >> n) & 1)
	
	def readByte(self, val, last=True):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		result = 0

		for n in range(7, -1, -1):
			bit = self.jtagClock((n == 0) & last, (val >> n) & 1)
			result |= bit << (7 - n)

		return result

	def parseByte(self, bits):
		return (bits[7] << 7) | (bits[6] << 6) | (bits[5] << 5) | (bits[4] << 4) | (bits[3] << 3) | (bits[2] << 2) |  (bits[1] << 1) | bits[0]
	
	def tapReset(self):
		for i in range(0, 6):
			self.jtagClock(tms=1)
	
	def readChain(self):
		self.deviceCount = None
		self.idcodes = None
		self.irlengths = None

		self._readDeviceCount()
		self._readIdcodes()
		self._processIdcodes()
	
	def _readDeviceCount(self):
		self.deviceCount = None

		self.tapReset()
		# Shift-IR
		self.jtagClock(tms=0)
		self.jtagClock(tms=1)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		# Force BYPASS
		for i in range(0, 100):	# TODO should be 1000
			self.jtagClock(tms=0, tdi=1)
		self.jtagClock(tms=1, tdi=1)

		# Shift-DR
		self.jtagClock(tms=1, tdi=1)
		self.jtagClock(tms=1, tdi=1)
		self.jtagClock(tms=0, tdi=1)
		self.jtagClock(tms=0, tdi=1)

		# Flush DR registers
		for i in range(0, 100):
			self.jtagClock(tms=0, tdi=0)

		# Count the number of devices
		for i in range(0, 100):
			self.jtagClock(tms=0, tdi=1)

		self.tapReset()

		data = self.readTDO(106)

		for i in range(0, 100):
			if data[i] == 1:
				self.deviceCount = i
				break

		if self.deviceCount is None:
			raise NoDevicesDetected()

	
	def _readIdcodes(self):
		if self.deviceCount is None:
			raise NoDevicesDetected()

		self.idcodes = []

		self.tapReset()

		# Shift-DR
		self.jtagClock(tms=0)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		for d in range(0, self.deviceCount*32-1):
			self.jtagClock(tms=0, tdi=1)
		self.jtagClock(tms=1, tdi=1)

		self.tapReset()

		data = self.readTDO(self.deviceCount*32 + 6)

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
	
	def buildInstruction(self, deviceid, instruction):
		if self.irlengths is None:
			raise FT232RJTAG_Exception("IRLengths are unknown.")

		result = []

		for d in range(self.deviceCount - 1, -1, -1):
			for i in range(0, self.irlengths[d]):
				if d == deviceid:
					result.append(instruction & 1)
					instruction = instruction >> 1
				else:
					result.append(1)

		return result
	
	# Load an instruction into a single device, BYPASSing the others.
	# Leaves the TAP at IDLE.
	def singleDeviceInstruction(self, deviceid, instruction):
		self.tapReset()

		self.jtagClock(tms=0)
		self.jtagClock(tms=1)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		bits = self.buildInstruction(deviceid, instruction)
		#print bits, len(bits)
		self.jtagWriteBits(bits, last=True)

		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
	
	# TODO: Currently assumes that deviceid is the last device in the chain.
	# TODO: Assumes TAP is in IDLE state.
	# Leaves the device in IDLE state.
	def shiftDR(self, deviceid, bits):
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		readback = self.jtagWriteBits(bits, last=(self.deviceCount==1))
		
		for d in range(self.deviceCount-2):
			self.jtagClock(tms=0)

		if self.deviceCount > 1:
			self.jtagClock(tms=1)

		self.jtagClock(tms=1)
		self.jtagClock(tms=0)

		return readback

	# TODO: Perform in a single D2XX.Write call.
	# TODO: ^ Be careful not to fill the RX buffer (128 bytes).
	def jtagWriteBits(self, bits, last=False):
		readback = []

		for b in bits[:-1]:
			readback.append(self.jtagClock(tdi=b, tms=0))
		readback.append(self.jtagClock(tdi=bits[-1], tms=(last&1)))

		return readback

	# Read the Configuration STAT register
	def sendJprogram(self, deviceid):
		if self.handle is None or self.irlengths is None:
			raise FT232RJTAG_Exception("IRLengths is None.")

		self.singleDeviceInstruction(deviceid, 0xB)

		self.tapReset()
		self.tapReset()
		self.tapReset()
		self.tapReset()



