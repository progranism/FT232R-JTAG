# Copyright (C) 2011-2012 by fizzisist <fizzisist@fpgamining.com>
#                            fpgaminer <fpgaminer@bitcoin-mining.com>
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

from Queue import Queue, Empty, Full
from jtag import JTAG
import time

class Object(object):
	pass

# JTAG instructions:
USER_INSTRUCTION = 0b000010
JSHUTDOWN        = 0b001101
JSTART           = 0b001100
JPROGRAM         = 0b001011
CFG_IN           = 0b000101
CFG_OUT          = 0b000100
BYPASS           = 0b111111
USERCODE	 = 0b001000


def hexstr2array(hexstr):
	"""Convert a hex string into an array of bytes"""
	arr = []
	for i in range(len(hexstr)/2):
		arr.append((int(hexstr[i*2], 16) << 4) | int(hexstr[i*2+1], 16))
	return arr

def int2bits(i, bits):
	"""Convert an integer to an array of bits, LSB first."""
	result = []
	for n in range(bits):
		result.append(i & 1)
		i = i >> 1
	return result

def bits2int(bits):
	"""Convert an array of bits to an integer, LSB first."""
	x = 0
	for i in range(len(bits)):
		x |= bits[i] << i
	return x

def jtagcomm_checksum(bits):
	checksum = 1

	for x in bits:
		checksum ^= x
	return [checksum]


class FPGA:
	def __init__(self, ft232r, chain, logger):
		self.jobqueue = Queue()
		self.ft232r = ft232r
		self.chain = chain
		self.jtag = JTAG(ft232r, chain)
		self.logger = logger
		self.id = -1
		
		self.current_job = None
		self.last_job = 0
		
		self.nonce_count = 0
		self.valid_count = 0
		self.invalid_count = 0
		self.accepted_count = 0
		self.rejected_count = 0
		self.recent_valids = 0
		
		self.asleep = True

		self.firmware_rev = 0
	
	def detect(self):
		with self.ft232r.lock:
			self.jtag.detect()

			# Always use the last part in the chain
			if self.jtag.deviceCount > 0:
				self.jtag.part(self.jtag.deviceCount-1)

				usercode = self._readUserCode()

				if usercode == 0xFFFFFFFF:
					self.firmware_rev = 0
				else:
					self.firmware_rev = (usercode >> 8) & 0xFF

	# Read the FPGA's USERCODE register, which gets set by the firmware
	# In our case this should be 0xFFFFFFFF for all old firmware revs,
	# and 0x4224???? for newer revs. The 2nd byte determines firmware rev/version,
	# and the 1st byte determines firmware build.
	def _readUserCode(self):
		with self.ft232r.lock:
			if self.asleep: self.wake()
			self.jtag.tap.reset()
			self.jtag.instruction(USERCODE)
			self.jtag.shift_ir()
			usercode = bits2int(self.jtag.read_dr(int2bits(0, 32)))

		return usercode

	# Old JTAG Comm:
	def _readByte(self):
		bits = int2bits(0, 13)
		byte = bits2int(self.jtag.read_dr(bits))
		return byte

	# New JTAG Comm
	# Read a 32-bit register
	def _readRegister(self, address):
		address = address & 0xF

		with self.ft232r.lock:
			if self.asleep: self.wake()
			self.jtag.tap.reset()
			self.jtag.instruction(USER_INSTRUCTION)
			self.jtag.shift_ir()

			# Tell the FPGA what address we would like to read
			data = int2bits(address, 5)
			data = data + jtagcomm_checksum(data)
			self.jtag.shift_dr(data)

			# Now read back the register
			data = self.jtag.read_dr(int2bits(0, 32))
			data = bits2int(data)

			self.jtag.tap.reset()

		return data

	# Write a single 32-bit register
	# If doing multiple writes, this won't be as efficient
	def _writeRegister(self, address, data):
		address = address & 0xF
		data = data & 0xFFFFFFFF

		with self.ft232r.lock:
			if self.asleep: self.wake()
			self.jtag.tap.reset()
			self.jtag.instruction(USER_INSTRUCTION)
			self.jtag.shift_ir()

			# Tell the FPGA what address we would like to write
			# and the data.
			data = int2bits(data, 32) + int2bits(address, 4) + [1]
			data = data + jtagcomm_checksum(data)
			self.jtag.shift_dr(data)

			self.jtag.tap.reset()
			self.ft232r.flush()
	
	# TODO: Remove backwards compatibility in a future rev.
	def _old_readNonce(self):
		with self.ft232r.lock:
			if self.asleep: self.wake()
			self.jtag.tap.reset()
			self.jtag.instruction(USER_INSTRUCTION)
			self.jtag.shift_ir()
			self.asleep = False

			# Sync to the beginning of a nonce.
			# The MSB is a VALID flag. If 0, data is invalid (queue empty).
			# The next 4-bits indicate which byte of the nonce we got.
			# 1111 is LSB, and then 0111, 0011, 0001.
			byte = None
			while True:
				byte = self._readByte()

				# check data valid bit:
				if byte < 0x1000:
					self.jtag.tap.reset()
					return None
				
				#self.logger.reportDebug("%d: Read: %04x" % (self.id, byte))
				
				# check byte counter:
				if (byte & 0xF00) == 0xF00:
					break
			
			# We now have the first byte
			nonce = byte & 0xFF
			count = 1
			#self.logger.reportDebug("%d: Potential nonce, reading the rest..." % self.id)
			while True:
				byte = self._readByte()
				
				#self.logger.reportDebug("%d: Read: %04x" % (self.id, byte))
				
				# check data valid bit:
				if byte < 0x1000:
					self.jtag.tap.reset()
					return None
				
				# check byte counter:
				if (byte & 0xF00) >> 8 != (0xF >> count):
					self.jtag.tap.reset()
					return None
				
				nonce |= (byte & 0xFF) << (count * 8)
				count += 1
				
				if (byte & 0xF00) == 0x100:
					break

			self.jtag.tap.reset()

		#self.logger.reportDebug("%d: Nonce completely read: %08x" % (self.id, nonce))

		return nonce
	
	# TODO: This may not actually clear the queue, but should be correct most of the time.
	def _old_clearQueue(self):
		with self.ft232r.lock:
			if self.asleep: self.wake()
			self.jtag.tap.reset()
			self.jtag.instruction(USER_INSTRUCTION)
			self.jtag.shift_ir()
			self.asleep = False
			
			self.logger.reportDebug("%d: Clearing queue..." % self.id)
			while True:
				if self._readByte() < 0x1000:
					break
			self.jtag.tap.reset()
		
		self.logger.reportDebug("%d: Queue cleared" % self.id)
	
	def _old_writeJob(self, job):
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

		with self.ft232r.lock:
			#self.logger.reportDebug("%d: Loading job data..." % self.id)
			
			if self.asleep: self.wake()
			self.jtag.tap.reset()
			self.jtag.instruction(USER_INSTRUCTION)
			self.jtag.shift_ir()

			data = midstate + data + [0]

			for i in range(len(data)):
				x = data[i]

				if i != 0:
					x = 0x100 | x
					
				self.jtag.shift_dr(int2bits(x, 13))
			
			self.jtag.tap.reset()

			self.ft232r.flush()
		
		#self.logger.reportDebug("%d: Job data loaded in %.3f seconds" % (self.id, time.time() - start_time))
		self.logger.reportDebug("%d: Job data loaded" % self.id)
	
	def _readNonce(self):
		nonce = self._readRegister(0xE)

		if nonce == 0x00000000:
			return None
		return nonce
	
	def _clearQueue(self):
		self.logger.reportDebug("%d: Clearing queue..." % self.id)
		while True:
			if self.readNonce() is None:
				break
		
		self.logger.reportDebug("%d: Queue cleared" % self.id)
	
	# TODO: We should add readback checks here to make sure the job is written correctly
	def _writeJob(self, job):
		# We need the 256-bit midstate, and 12 bytes from data.
		# The first 64 bytes of data are already hashed (hence midstate),
		# so we skip that. Of the last 64 bytes, 52 bytes are constant and
		# not needed by the FPGA.
		
		start_time = time.time()
		
		midstate = hexstr2array(job.midstate)
		data = hexstr2array(job.data)[64:64+12]

		data = midstate + data

		# Job's hex strings are LSB first, and the FPGA wants them MSB first.
		#midstate.reverse()
		#data.reverse()

		with self.ft232r.lock:
			#self.logger.reportDebug("%d: Loading job data..." % self.id)
			
			if self.asleep: self.wake()
			self.jtag.tap.reset()
			self.jtag.instruction(USER_INSTRUCTION)
			self.jtag.shift_ir()

			for i in range(11):
				addr = i + 1
				x = int2bits(data[i*4], 8)
				x += int2bits(data[i*4+1], 8)
				x += int2bits(data[i*4+2], 8)
				x += int2bits(data[i*4+3], 8)
				x += int2bits(addr, 4)
				x += [1]
				x = x + jtagcomm_checksum(x)
				self.jtag.shift_dr(x)

			self.jtag.tap.reset()
			self.ft232r.flush()
		
		#self.logger.reportDebug("%d: Job data loaded in %.3f seconds" % (self.id, time.time() - start_time))
		self.logger.reportDebug("%d: Job data loaded" % self.id)
	
	def readNonce(self):
		if self.firmware_rev == 0:
			return self._old_readNonce()
		else:
			return self._readNonce()
	
	def clearQueue(self):
		if self.firmware_rev == 0:
			return self._old_clearQueue()
		else:
			return self._clearQueue()
	
	def writeJob(self, job):
		if self.firmware_rev == 0:
			return self._old_writeJob(job)
		else:
			return self._writeJob(job)
	
	def getJob(self):
		try:
			#logger.reportDebug("%d: Checking for new job..." % fpga.id)
			return self.jobqueue.get(False)
		except Empty:
			return None
	
	def putJob(self, work):
		job = Object()
		job.midstate = work['midstate']
		job.data = work['data']
		job.target = work['target']
		self.jobqueue.put(job)
		#self.logger.reportDebug("%d: jobqueue loaded (%d)" % (fpga.id, self.jobqueue.qsize()))
	
	def sleep(self):
		with self.ft232r.lock:
			self.logger.reportDebug("%d: Going to sleep..." % self.id)
			
			self.jtag.tap.reset()
			self.jtag.instruction(JSHUTDOWN)
			self.jtag.shift_ir()
			self.jtag.runtest(24)
			self.jtag.tap.reset()
			
			self.ft232r.flush()
		
		self.asleep = True
	
	def wake(self):
		with self.ft232r.lock:
			self.logger.reportDebug("%d: Waking up..." % self.id)
		
			self.jtag.tap.reset()
			self.jtag.instruction(JSTART)
			self.jtag.shift_ir()
			self.jtag.runtest(24)
			self.jtag.instruction(BYPASS)
			self.jtag.shift_ir()
			self.jtag.instruction(BYPASS)
			self.jtag.shift_ir()
			self.jtag.instruction(JSTART)
			self.jtag.shift_ir()
			self.jtag.runtest(24)
			self.jtag.tap.reset()
			
			self.ft232r.flush()
		
		self.asleep = False
	
	@staticmethod
	def programBitstream(ft232r, jtag, logger, processed_bitstream):
		with ft232r.lock:
			# Select the device
			jtag.reset()
			jtag.part(jtag.deviceCount-1)
			
			jtag.instruction(BYPASS) 
			jtag.shift_ir()

			jtag.instruction(JPROGRAM)
			jtag.shift_ir()

			jtag.instruction(CFG_IN)
			jtag.shift_ir()

			# Clock TCK for 10000 cycles
			jtag.runtest(10000)

			jtag.instruction(CFG_IN)
			jtag.shift_ir()
			jtag.shift_dr([0]*32)
			jtag.instruction(CFG_IN)
			jtag.shift_ir()

			ft232r.flush()
			
			# Load bitstream into CFG_IN
			jtag.load_bitstream(processed_bitstream, logger.updateProgress)

			jtag.instruction(JSTART)
			jtag.shift_ir()

			# Let the device start
			jtag.runtest(24)
			
			jtag.instruction(BYPASS)
			jtag.shift_ir()
			jtag.instruction(BYPASS)
			jtag.shift_ir()

			jtag.instruction(JSTART)
			jtag.shift_ir()

			jtag.runtest(24)
			
			# Check done pin
			#jtag.instruction(BYPASS)
			# TODO: Figure this part out. & 0x20 should equal 0x20 to check the DONE pin ... ???
			#print jtag.read_ir() # & 0x20 == 0x21
			#jtag.instruction(BYPASS)
			#jtag.shift_ir()
			#jtag.shift_dr([0])

			ft232r.flush()
