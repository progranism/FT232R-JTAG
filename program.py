from ft232r import FT232R, FT232R_PortList
from jtag import JTAG
from BitstreamReader import BitFile, BitFileReadError
import time
from optparse import OptionParser

# LSB first
def bits2int(bits):
	x = 0
	for i in range(len(bits)):
		x |= bits[i] << i
	return x

def bitstreamProgress(start_time, written, total):
	print "Completed: ", str((written * 1000 / total) * 0.1), "%"
	print str(written * 1.0 / (time.time() - start_time)), "B/s"

# Dictionary for looking up idcodes from device names:
idcode_lut = {'6slx150fgg484': 0x401d093}

# Option parsing:
parser = OptionParser(usage="%prog [-d <device>] [-c <chain>] <path-to-bitstream-file>")
parser.add_option("-d", "--device", type="int", dest="device", default=0,
                  help="Device number, default 0 (only needed if you have more than one board)")
parser.add_option("-c", "--chain", type="int", dest="chain", default=0,
                  help="JTAG chain number, can be 0, 1, or 2 for both FPGAs on the board (default 0)")
settings, args = parser.parse_args()

if len(args) == 0:
	print "ERROR: No bitstream file specified!"
	parser.print_usage()
	exit()
	
### Bitfile ###
bitfileName = args[0]
print "Opening bitstream file:", bitfileName
bitfile = None

try:
	with open(bitfileName, 'rb') as f:
		bitfile = BitFile.read(f)
except BitFileReadError, e:
	print e
	exit()

print "Bitstream file opened:"
print "      Design Name:", bitfile.designname
print "        Part Name:", bitfile.part
print "             Date:", bitfile.date
print "             Time:", bitfile.time
print " Bitstream Length:", len(bitfile.bitstream)
print ""


with FT232R() as ft232r:
	portlist = FT232R_PortList(7, 6, 5, 4, 3, 2, 1, 0)
	ft232r.open(settings.device, portlist)
	
	# TODO: make it program both FPGAs when settings.chain == 2
	if settings.chain == 0 or settings.chain == 1:
		jtag = JTAG(ft232r, settings.chain)
		print "Discovering JTAG chain %d ..." % chain
		jtag.detect()
		
		print "Found %i devices ...\n" % jtag.deviceCount

		for idcode in jtag.idcodes:
			JTAG.decodeIdcode(idcode)
		
		print ""
		print "Beginning programming..."
		
		# Select the device
		jtag.reset()
		jtag.part(jtag.deviceCount-1)
		
		# Verify the IDCODE
		jtag.instruction(0x09)
		jtag.shift_ir()
		if bits2int(jtag.read_dr([0]*32)) & 0x0FFFFFFF != idcode_lut[bitfile.part]:
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
		