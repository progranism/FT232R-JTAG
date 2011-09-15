from jtag import JTAG
from BitstreamReader import BitFile, BitFileReadError
import time


# LSB first
def bits2int(bits):
	x = 0
	for i in range(len(bits)):
		x |= bits[i] << i
	return x

def bitstreamProgress(start_time, written, total):
	print "Completed: ", str((written * 1000 / total) * 0.1), "%"
	print str(written * 1.0 / (time.time() - start_time)), "B/s"



### Bitfile ###
print "Reading BIT file..."
bitfile = None

try:
	with open('bitstream/test_fpgaminer_top.bit', 'rb') as f:
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


with JTAG() as jtag:
	jtag.open(0)

	print "Discovering JTAG Chain ..."
	jtag.detect()

	print "Found %i devices ...\n" % jtag.deviceCount

	for idcode in jtag.idcodes:
		JTAG.decodeIdcode(idcode)
	
	print "\n"

	print "Beginning programming..."

	# Select the device
	jtag.reset()
	jtag.part(jtag.deviceCount-1)

	# Verify the IDCODE
	jtag.instruction(0x09)
	jtag.shift_ir()
	if bits2int(jtag.read_dr([0]*32)) & 0x0FFFFFFF != 0x0403d093:
		print "ERROR: The specified firmware was not designed for the attached device."
		exit()
	
	# Load with BYPASS
	jtag.instruction(0xFF)
	jtag.shift_ir()

	# Load with JPROGRAM
	jtag.instruction(0x0B)
	jtag.shift_ir()

	# Load with CFG_IN
	jtag.instruction(0x05)
	jtag.shift_ir()

	# Clock TCK for 10000 cycles
	jtag.runtest(10000)

	# Load with CFG_IN
	jtag.instruction(0x05)
	jtag.shift_ir()
	jtag.shift_dr([0]*32)
	jtag.instruction(0x05)
	jtag.shift_ir()

	jtag.flush()

	#print ord(bitfile.bitstream[5000])
	#bitfile.bitstream = bitfile.bitstream[0:5000] + chr(0x12) + bitfile.bitstream[5001:]

	# Load bitstream into CFG_IN
	jtag.bulk_shift_dr(bitfile.bitstream, bitstreamProgress)

	# Load with JSTART
	jtag.instruction(0x0C)
	jtag.shift_ir()
	print "a"

	# Let the device start
	jtag.runtest(24)
	print "b"
	
	# Load with Bypass
	jtag.instruction(0xFF)
	jtag.shift_ir()
	jtag.instruction(0xFF)
	jtag.shift_ir()
	print "c"

	# Load with JSTART
	jtag.instruction(0x0C)
	jtag.shift_ir()
	print "d"

	jtag.runtest(24)

	print "e"

	# Check done pin
	jtag.instruction(0xFF)
	# TODO: Figure this part out. & 0x20 should equal 0x20 to check the DONE pin ... ???
	print jtag.read_ir() # & 0x20 == 0x21
	jtag.instruction(0xFF)
	jtag.shift_ir()
	jtag.shift_dr([0])

	jtag.flush()
	
	

