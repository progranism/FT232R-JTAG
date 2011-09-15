# NOTE: Only use FT232RJTAG with the 'with' statement, ala:
# with FT232RJTAG() as jtag:
#      blah blah blah...
#
# This ensures that FT232R devices are properly closed,
# and don't end up in a locked or useless state.
# 

import d2xx
import time

BIT_TCK = 3# 7	# RI
BIT_TMS = 2#6	# DCD
BIT_TDI = 1#5	# DSR
BIT_TDO = 0#4	# DTR

# Spartan 6, -2, -3N, -3N speed grades
TMS_TDI_TSU = 10	# 10ns setup time before rising TCK
TMS_TDI_TH = 5.5	# 5.5ns hold time after rising TCK
TDO_VALID = 6.5		# 6.5ns after falling TCK, TDO becomes valid
TCK_MIN = 30		# TCK period must be at least 30ns (<33MHz)

DEFAULT_FREQUENCY = 100	# Hz

# Calculate actual TCK_MIn in seconds
#TCK_MIN = max(1.0 / DESIRED_FREQUENCY, TCK_MIN * 0.000000001)

# A dictionary, which allows us to look up a jtag device's IDCODE and see
# how big its Instruction Register is (how many bits). This is entered manually
# but could, in the future, be read automatically from a database of BSDL files.
irlength_lut = {0x403d093: 6, 0x401d093: 6, 0x5057093: 16, 0x5059093: 16};


class FT232RJTAG_Exception(Exception):
	def __init__(self, value):
		self.parameter = value
	def __str__(self):
		return repr(self.parameter)


class FT232RJTAG:
	def __init__(self):
		self.setFrequency(DEFAULT_FREQUENCY)

		self.handle = None
		self.deviceCount = None
		self.idcodes = None
		self.irlengths = None
		self.debug = 0
		self.synchronous = None
		self.async_record = None
	
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
		if self.handle:
			raise FT232RJTAG_Exception("A device is already open. Either call Close, or create another FT232RJTAG instance.")

		self.handle = d2xx.open(devicenum)
			
		if self.handle is not None:
			self._setSyncMode()
			self._purgeBuffers()	# Just in case
	
	def close(self):
		if self.handle is None:
			return

		self._log("Closing device...")

		try:
			self.handle.close()
		finally:
			self.handle = None

		self._log("Device closed.")
	
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

	# Purges the FT232R's buffers.
	def _purgeBuffers(self):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		self.handle.purge()
	
	# Put the FT232R into Synchronous mode.
	def _setSyncMode(self):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		self._log("Device entering Synchronous mode.")

		self.handle.setBitMode((1 << BIT_TCK) | (1 << BIT_TMS) | (1 << BIT_TDI), 0)
		self.handle.setBitMode((1 << BIT_TCK) | (1 << BIT_TMS) | (1 << BIT_TDI), 4)
		self._updateBaudrate()
		self.synchronous = True
	
	def _updateBaudrate(self):
		# Documentation says that we should set a baudrate 16 times lower than
		# the desired transfer speed (for bit-banging). However I found this to
		# not be the case. 3Mbaud is the maximum speed of the FT232RL
		self.handle.setBaudRate(3000000)
		#self.handle.setDivisor(0)	# Another way to set the maximum speed.

	
	# Put the FT232R into Asynchronous mode.
	def _setAsyncMode(self):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		self._log("Device entering Asynchronous mode.")

		self.handle.setBitMode((1 << BIT_TCK) | (1 << BIT_TMS) | (1 << BIT_TDI), 0)
		self.handle.setBitMode((1 << BIT_TCK) | (1 << BIT_TMS) | (1 << BIT_TDI), 1)
		self._updateBaudrate()
		self.synchronous = False
	
	def _formatJtagState(self, tck, tms, tdi):
		return chr(((tck&1) << BIT_TCK) | ((tms&1) << BIT_TMS) | ((tdi&1) << BIT_TDI))

	def _intJtagState(self, tck, tms, tdi):
		return ((tck&1) << BIT_TCK) | ((tms&1) << BIT_TMS) | ((tdi&1) << BIT_TDI)
	
	#def sendJtagState(self, tck, tms, tdi):
	#	if self.handle is None:
	#		return False
#
#		tck = tck & 1
#		tms = tms & 1
#		tdi = tdi & 1
#
#		try:
#			x = (tck << BIT_TCK) | (tms << BIT_TMS) | (tdi << BIT_TDI)
#			self.handle.write(chr(x))
#
#		except Exception, e:
#			print e
#			return False
#
#		return True
#	
#	def getJtagTdo(self):
#		if self.handle is None:
#			return None
#
#		tdo = None
#
#		try:
#			tdo = (self.handle.getBitMode() >> BIT_TDO) & 1
#
#		except Exception, e:
#			tdo = None
#			print e
#
#		return tdo
	
	# Perform a single JTAG clock, and return TDO.
	# Use for Synchronous mode.
	def jtagClock(self, tms=0, tdi=0):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		#self._log("jtagClock %i %i" % (tms, tdi), 0)

		# Bring clock low, high, and then keep high for an extra cycle.
		# In sync mode, FT232R reads just before setting the data,
		# hence the extra cycle to correctly read TDO (after tck goes high).
		data = self._formatJtagState(0, tms, tdi)
		data += self._formatJtagState(1, tms, tdi)

		if self.async_record is not None:
			self.async_record += data
			return None

		data += self._formatJtagState(1, tms, tdi)
		self.handle.write(data)

		# The last byte
		result = self.handle.read(3)

		return (ord(result[2]) >> BIT_TDO) & 1

		#self.sendJtagState(0, tms, tdi)
		#time.sleep(self.tck_min)
		#self.sendJtagState(1, tms, tdi)
		#time.sleep(self.tck_min)

		#return self.getJtagTdo()

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
	
	def tapReset(self):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		for i in range(0, 6):
			self.jtagClock(tms=1)
	
	def readChain(self):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		self.deviceCount = None
		self.idcodes = None
		self.irlengths = None

		self._readDeviceCount()
		self._readIdcodes()
		self._processIdcodes()
	
	def _readDeviceCount(self):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

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
			if self.jtagClock(tms=0, tdi=1) == 1:
				self.deviceCount = i
				break

		self.tapReset()

		if self.deviceCount is None:
			raise FT232RJTAG_Exception("Could not find any devices in the JTAG chain.")

	
	def _readIdcodes(self):
		if self.handle is None:
			raise FT232RJTAG_Exception("No device open.")

		if self.deviceCount is None:
			raise FT232RJTAG_Exception("Can't read IDCODEs until the device count is known.")

		self.idcodes = []

		self.tapReset()

		# Shift-DR
		self.jtagClock(tms=0)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		for d in range(0, self.deviceCount):
			idcode = self.readByte(0xFF, False)
			idcode |= self.readByte(0xFF, False) << 8
			idcode |= self.readByte(0xFF, False) << 16
			idcode |= self.readByte(0xFF, d == (self.deviceCount-1)) << 24

			self.idcodes.insert(0, idcode)

		self.tapReset()

	def _processIdcodes(self):
		if self.idcodes is None:
			raise FT232RJTAG_Exception("No IDCODEs have been read.")

		self.irlengths = []

		for idcode in self.idcodes:
			if (idcode & 0x0FFFFFFF) in irlength_lut:
				self.irlengths.append(irlength_lut[idcode & 0x0FFFFFFF])
			else:
				self.irlengths = None
				raise FT232RJTAG_Exception("Unknown IDCODE: %.8X. IRlength is unknown." % idcode)
			

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
	
	# Desired JTAG Frequency in Hz
	def setFrequency(self, freq):
		self.tck_min = max(1.0 / freq, TCK_MIN * 0.000000001)
	
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
	def readConfigStat(self, deviceid):
		if self.handle is None:
			return None

		if self.irlengths is None:
			return None

		extraDevices = deviceid

		self.tapReset()

		self.jtagClock(tms=0)
		self.jtagClock(tms=1)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		self.jtagWriteBits(self.buildInstruction(deviceid, 5))

		self.jtagClock(tms=1)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		for x in [0xAA, 0x99, 0x55, 0x66, 0x29, 0x01, 0x20, 0x00, 0x20, 0x00, 0x20, 0x00, 0x20]:
			self.sendByte(x, False)
		self.sendByte(0x00, extraDevices==0)

		for i in range(0, extraDevices):
			if i == (extraDevices-1):
				self.jtagClock(tdi=1, tms=1)
			else:
				self.jtagClock(tdi=1)

		self.jtagClock(tms=1)
		self.jtagClock(tms=1)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		self.jtagWriteBits(self.buildInstruction(deviceid, 4))

		self.jtagClock(tms=1)
		self.jtagClock(tms=1)
		self.jtagClock(tms=0)
		self.jtagClock(tms=0)

		stat = 0

		for i in range(0, 15+(len(self.irlengths)-deviceid)):
			stat = (stat << 1) | self.jtagClock()
		stat = (stat << 1) | self.jtagClock(tms=1)

		self.tapReset()

		return stat & 0xFFFF

	# Read the Configuration STAT register
	def sendJprogram(self, deviceid):
		if self.handle is None or self.irlengths is None:
			raise FT232RJTAG_Exception("IRLengths is None.")

		self.singleDeviceInstruction(deviceid, 0xB)

		self.tapReset()
		self.tapReset()
		self.tapReset()
		self.tapReset()

		


