import d2xx
import struct
from TAP import TAP
import time


DEFAULT_FREQUENCY = 3000000


class DeviceNotOpened(Exception): pass


# Information about which of the 8 GPIO pins to use.
class FT232R_PortList:
	def __init__(self, tck0, tms0, tdi0, tdo0, tck1, tms1, tdi1, tdo1):
		self.tck0 = tck0
		self.tms0 = tms0
		self.tdi0 = tdi0
		self.tdo0 = tdo0
		self.tck1 = tck1
		self.tms1 = tms1
		self.tdi1 = tdi1
		self.tdo1 = tdo1
	
	def output_mask(self):
		return (1 << self.tck0) | (1 << self.tms0) | (1 << self.tdi0) | \
		       (1 << self.tck1) | (1 << self.tms1) | (1 << self.tdi1)

	def format(self, tck, tms, tdi, chain=0):
		# chain is the JTAG chain: 0 or 1, or 2 for both
		if( chain == 0 ):
			return struct.pack('=c', chr(((tck&1) << self.tck0) | 
			                             ((tms&1) << self.tms0) | 
			                             ((tdi&1) << self.tdi0)))
		if( chain == 1 ):
			return struct.pack('=c', chr(((tck&1) << self.tck1) | 
			                             ((tms&1) << self.tms1) | 
			                             ((tdi&1) << self.tdi1)))
		if( chain == 2 ):
			return struct.pack('=c', chr(((tck&1) << self.tck0) | 
			                             ((tms&1) << self.tms0) | 
			                             ((tdi&1) << self.tdi0) |
			                             ((tck&1) << self.tck1) | 
			                             ((tms&1) << self.tms1) | 
			                             ((tdi&1) << self.tdi1)))


class FT232R:
	def __init__(self):
		self.tap = TAP(self.jtagClock)
		self.handle = None
		self.debug = 0
		self.synchronous = None
		self.write_buffer = ""
		self.portlist = None
		self._tckcount = 0
	
	def _log(self, msg, level=1):
		if level <= self.debug:
			print "FT232R-JTAG: " + msg
	
	def open(self, devicenum, portlist):
		if self.handle is not None:
			self.close()

		self._log("Opening device %i" % devicenum)

		self.handle = d2xx.open(devicenum)

		if self.handle is not None:
			self.portlist = portlist
			self._setBaudRate(DEFAULT_FREQUENCY)
			self._setSyncMode()
			self._purgeBuffers()
	
	def close(self):
		if self.handle is None:
			return

		self._log("Closing device...")

		try:
			self.handle.close()
		finally:
			self.handle = None

		self._log("Device closed.")
	
	# Purges the FT232R's buffers.
	def _purgeBuffers(self):
		if self.handle is None:
			raise DeviceNotOpened()

		self.handle.purge(0)
	
	def _setBaudRate(self, rate):
		self._log("Setting baudrate to %i" % rate)

		# Documentation says that we should set a baudrate 16 times lower than
		# the desired transfer speed (for bit-banging). However I found this to
		# not be the case. 3Mbaud is the maximum speed of the FT232RL
		self.handle.setBaudRate(rate)
		#self.handle.setDivisor(0)	# Another way to set the maximum speed.
	
	# Put the FT232R into Synchronous mode.
	def _setSyncMode(self):
		if self.handle is None:
			raise DeviceNotOpened()

		self._log("Device entering Synchronous mode.")

		self.handle.setBitMode(self.portlist.output_mask(), 0)
		self.handle.setBitMode(self.portlist.output_mask(), 4)
		self.synchronous = True

	
	# Put the FT232R into Asynchronous mode.
	def _setAsyncMode(self):
		if self.handle is None:
			raise DeviceNotOpened()

		self._log("Device entering Asynchronous mode.")

		self.handle.setBitMode(self.portlist.output_mask(), 0)
		self.handle.setBitMode(self.portlist.output_mask(), 1)
		self.synchronous = False
	
	def _formatJtagState(self, tck, tms, tdi, chain=0):
		return self.portlist.format(tck, tms, tdi, chain)

	def jtagClock(self, tms=0, tdi=0, chain=0):
		if self.handle is None:
			raise DeviceNotOpened()
		
		self.write_buffer += self._formatJtagState(0, tms, tdi, chain)
		self.write_buffer += self._formatJtagState(1, tms, tdi, chain)
		self.write_buffer += self._formatJtagState(1, tms, tdi, chain)

		self.tap.clocked(tms)
		self._tckcount += 1
	
	def flush(self):
		self._setAsyncMode()
		while len(self.write_buffer) > 0:
			self.handle.write(self.write_buffer[:4096])
			self.write_buffer = self.write_buffer[4096:]
		self._setSyncMode()
		self._purgeBuffers()
	
	# Read the last num bits of TDO.
	def readTDO(self, num, chain=0):
		if num == 0:
			flush()
			return []

		# Repeat the last byte so we can read the last bit of TDO.
		write_buffer = self.write_buffer[-(num*3):]
		self.write_buffer = self.write_buffer[:-(num*3)]

		# Write all data that we don't care about.
		if len(self.write_buffer) > 0:
			print "Flushing out %i" % len(self.write_buffer)
			self.flush()
			self._purgeBuffers()

		bits = []

		while len(write_buffer) > 0:
			written = min(len(write_buffer), 3072)

			print written
			print len(write_buffer)
			print "Wrote: ", self.handle.write(write_buffer[:written])
			write_buffer = write_buffer[written:]
			print self.handle.getStatus()
			print self.handle.getQueueStatus()

			while self.handle.getQueueStatus() < written:
				time.sleep(1)
				print self.handle.getQueueStatus()
			read = self.handle.read(written)

			for n in range(written/3):
				if( chain == 0 ):
					bits.append((ord(read[n*3+2]) >> self.portlist.tdo0)&1)
				elif( chain == 1 ):
					bits.append((ord(read[n*3+2]) >> self.portlist.tdo1)&1)

		return bits
	
#	def shiftIR(self, bits):
#		self.tap.goto(TAP.SELECT_IR)
#		self.tap.goto(TAP.SHIFT_IR)
#
#		for bit in bits[:-1]:
#			self.jtagClock(tdi=bit)
#		self.jtagClock(tdi=bits[-1], tms=1)
#
#		self.tap.goto(TAP.IDLE)
#	
#	def shiftDR(self, bits, read=False):
#		self.tap.goto(TAP.SELECT_DR)
#		self.tap.goto(TAP.SHIFT_DR)
#
#		for bit in bits[:-1]:
#			self.jtagClock(tdi=bit)
#		self.jtagClock(tdi=bits[-1], tms=1)
#
#		t1 = self.tckcount
#		self.tap.goto(TAP.IDLE)
#
#		if read:
#			return self.readTDO(len(bits)+self.tckcount-t1)[:len(bits)]
#	
#	def readDR(self, bits):
#		return self.shiftDR(bits, True)


	
	



