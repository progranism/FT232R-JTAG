from ft232rjtag import FT232RJTAG
from BitstreamReader import BitFile, BitFileReadError
import time
import traceback
import struct


### BitFile ###
print "Reading BIT file..."
bitfile = None

try:
	with open('bitstream/fpgaminer_USER1_50MH.bit', 'rb') as f:
		bitfile = BitFile.read(f)

except BitFileReadError, e:
	print e
	exit()

print "Design Name:\t", bitfile.designname
print "Part Name:\t", bitfile.part
print "Date:\t", bitfile.date
print "Time:\t", bitfile.time
print "Bitstream Length:\t", len(bitfile.bitstream)
print "\n"


### JTAG ###
with FT232RJTAG() as jtag:
	jtag.open(0)
	#if not jtag.open(0):
	#	print "Unable to open the JTAG communication device. Is the board attached by USB?"
	#	exit()

	print "Discovering JTAG Chain..."
	idcodes = jtag.readChain()

	print "There are %i devices in the JTAG chain." % len(jtag.idcodes)

	for idcode in jtag.idcodes:
		FT232RJTAG.decodeIdcode(idcode)

	if jtag.irlengths is None:
		print "Not all devices in the chain are known. Cannot program."
		jtag.close()
		exit()

	print "\n"

	#print jtag.readConfigStat(2)

	#jtag.tapReset()

	# Shift-IR
	#jtag.jtagClock(tms=0)
	#jtag.jtagClock(tms=1)
	#jtag.jtagClock(tms=1)
	#jtag.jtagClock(tms=0)
	#jtag.jtagClock(tms=0)
	
	# Build instruction
	# TODO: Construct based on the device chain
	#jtag.jtagClock(tdi=1)
	#jtag.jtagClock(tdi=0)
	#jtag.jtagClock(tdi=0)
	#jtag.jtagClock(tdi=1)
	#jtag.jtagClock(tdi=0)
	#jtag.jtagClock(tdi=0)
	#
	#for i in range(0, 31):
	#	jtag.jtagClock(tdi=1)
	#
	#jtag.jtagClock(tdi=1,tms=1)
	#
	#jtag.jtagClock(tms=1, tdi=1)
	#jtag.jtagClock(tms=1, tdi=1)
	#jtag.jtagClock(tms=0, tdi=1)
	#jtag.jtagClock(tms=0, tdi=1)
	#
	## Flush DR registers
	#print "0x%.2X" % jtag.readByte(0xFF, False)
	#print "0x%.2X" % jtag.readByte(0xFF, False)
	#print "0x%.2X" % jtag.readByte(0xFF, False)
	#print "0x%.2X" % jtag.readByte(0xFF, False)
	#
	#print jtag.readByte(0xFF, False)
	#print jtag.readByte(0xFF, False)
	#print jtag.readByte(0xFF, False)
	#print jtag.readByte(0xFF, False)
	#
	#print jtag.readByte(0xFF, False)
	#print jtag.readByte(0xFF, False)
	#print jtag.readByte(0xFF, False)
	#print jtag.readByte(0xFF, True)
	#
	#jtag.tapReset()
	

	print "Beginning programming..."

	jtag.sendJprogram(2)

	jtag.tapReset()

	# Shift-IR
	#jtag.jtagClock(tms=0)
	#jtag.jtagClock(tms=1)
	#jtag.jtagClock(tms=1)
	#jtag.jtagClock(tms=0)
	#jtag.jtagClock(tms=0)

	# CFG_IN
	jtag.singleDeviceInstruction(jtag.deviceCount-1, 0b000101)

	# Build instruction - CFG_IN
	# TODO: Construct based on the device chain
	#jtag.jtagClock(tdi=1)
	#jtag.jtagClock(tdi=0)
	#jtag.jtagClock(tdi=1)
	#jtag.jtagClock(tdi=0)
	#jtag.jtagClock(tdi=0)
	#jtag.jtagClock(tdi=0)

	#for i in range(0, 31):
	#	jtag.jtagClock(tdi=1)

	#jtag.jtagClock(tdi=1,tms=1)

	# Shift-DR
	#jtag.jtagClock(tms=1, tdi=1)
	jtag.jtagClock(tms=1, tdi=1)
	jtag.jtagClock(tms=0, tdi=1)
	jtag.jtagClock(tms=0, tdi=1)


	bytetotal = len(bitfile.bitstream)

	jtagstr = ""

	(rxlen, txlen, events) = jtag.handle.getStatus()
	print rxlen, txlen, events

	jtag._setAsyncMode()

	# Prepare all data to be transfered
	chunk = None
	chunk_i = 0
	data_chunks = []
	CHUNK_SIZE = 4096*4

	start_time = time.time()

	for n in range(0, bytetotal):
		d = ord(bitfile.bitstream[n])

		if chunk is None:
			bytesleft = (bytetotal - n) * 16
			chunk = bytearray(min(CHUNK_SIZE, bytesleft))

		for i in range(7, -1, -1):
			x = (d >> i) & 1
			chunk[chunk_i] = jtag._intJtagState(0, 0, x)
			chunk[chunk_i+1] = jtag._intJtagState(1, 0, x)
			chunk_i += 2

		if chunk_i == CHUNK_SIZE:
			data_chunks.append(chunk.decode())
			chunk_i = 0
			chunk = None
	
	if chunk is not None:
		data_chunks.append(chunk.decode())

		#jtagstr += struct.pack("=16c", jtag._formatJtagState(0, 0, (d>>7)&1), jtag._formatJtagState(1, 0, (d>>7)&1), jtag._formatJtagState(0, 0, (d>>6)&1), jtag._formatJtagState(1, 0, (d>>6)&1), jtag._formatJtagState(0, 0, (d>>5)&1), jtag._formatJtagState(1, 0, (d>>5)&1), jtag._formatJtagState(0, 0, (d>>4)&1), jtag._formatJtagState(1, 0, (d>>4)&1), jtag._formatJtagState(0, 0, (d>>3)&1), jtag._formatJtagState(1, 0, (d>>3)&1), jtag._formatJtagState(0, 0, (d>>2)&1), jtag._formatJtagState(1, 0, (d>>2)&1), jtag._formatJtagState(0, 0, (d>>1)&1), jtag._formatJtagState(1, 0, (d>>1)&1), jtag._formatJtagState(0, 0, (d)&1), jtag._formatJtagState(1, 0, (d)&1))

		#for i in range(7, -1, -1):
		#	x = (d >> i) & 1
		#	jtagstr += struct.pack("=cccccccccccccccc", jtag._intJtagState(0, 0, ), jtag._intJtagState(1, 0, x))
		#	#jtagstr += jtag._formatJtagState(0, 0, (d >> i) & 1) + jtag._formatJtagState(1, 0, (d >> i) & 1)
	
		#if len(jtagstr) == 1024:
		#	data_chunks.append(jtagstr)
		#	jtagstr = ""
	
	#if len(jtagstr) > 0:
	#	data_chunks.append(jtagstr)
	
	print "Pre-processing took %i seconds." % int(time.time() - start_time)

	# Now transfer all data to the FPGA
	written = 0
	last_time = time.time()
	for n in range(len(data_chunks)):
		chunk = data_chunks[n]

		jtag.handle.write(chunk)
		written += len(chunk) / 16

		if (written % (16 * 1024)) == 0:
			print "Completed: ", str((written * 1000 / bytetotal) * 0.1), "%"
			print str(written * 1.0 / (time.time() - last_time)), "B/s"

			#(rxlen, txlen, events) = jtag.handle.getStatus()
			#print rxlen, txlen, events

	print "Total Time: %i secs." % int(time.time() - last_time)
	print "Last write"

	#if len(jtagstr) > 0:
	#	jtag.handle.write(jtagstr)
	
	(rxlen, txlen, events) = jtag.handle.getStatus()
	print rxlen, txlen, events
	
	print "Switching modes..."
	jtag._purgeBuffers()
	jtag._setSyncMode()
	print "Mode switched."

	#jtag.tck_min = old_sleep

	# An extra two shifts because of the other two devices
	jtag.jtagClock(tdi=1, tms=0)
	jtag.jtagClock(tdi=1, tms=1)


	jtag.jtagClock(tms=1)	# Update-DR
	jtag.jtagClock(tms=1)	# Select-DR
	jtag.jtagClock(tms=1)	# Select-IR
	jtag.jtagClock(tms=0)	# Shift-IR
	jtag.jtagClock(tms=0)	# Shift-IR

	# J-START
	jtag.jtagClock(tms=0, tdi=0)
	jtag.jtagClock(tms=0, tdi=0)
	jtag.jtagClock(tms=0, tdi=1)
	jtag.jtagClock(tms=0, tdi=1)
	jtag.jtagClock(tms=0, tdi=0)
	jtag.jtagClock(tms=0, tdi=0)

	for i in range(0, 31):
		jtag.jtagClock(tdi=1)

	jtag.jtagClock(tdi=1,tms=1)

	jtag.jtagClock(tms=1)	# Update-IR

	# Go to RTI and clock there for at least 16 cycles
	for n in range(0, 17):
		jtag.jtagClock(tms=0)

	# Move to TLR. Device should now be functional.
	jtag.jtagClock(tms=1)
	jtag.jtagClock(tms=1)
	jtag.jtagClock(tms=1)
	jtag.jtagClock(tms=1)

	print "Programming complete!?!?"

	#print jtag.readConfigStat(2)



#jtag.close()

print "Finished"

