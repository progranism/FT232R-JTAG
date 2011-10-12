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

def bitstreamProgress(start_time, now_time, written, total):
	message = "Completed: %.1f%% [%.1f kB/s]\r" % (100.0 * written / total, 0.001 * written  / (now_time - start_time))
	if written/total < 1:
		print message,
	else:
		print message

def programBitstream(ft232r, chain, bitfile):
	jtag = JTAG(ft232r, portlist.chain_portlist(settings.chain), settings.chain)
	print "Discovering JTAG chain %d ..." % settings.chain
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
	if bits2int(jtag.read_dr([0]*32))  & 0x0FFFFFFF != bitfile.idcode:
		print "ERROR: The specified bitstream was not designed for the attached device."
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

	ft232r.flush()

	#print ord(bitfile.bitstream[5000])
	#bitfile.bitstream = bitfile.bitstream[0:5000] + chr(0x12) + bitfile.bitstream[5001:]

	# Load bitstream into CFG_IN
	jtag.bulk_shift_dr(bitfile.bitstream, bitstreamProgress)

	# Load with JSTART
	jtag.instruction(0x0C)
	jtag.shift_ir()

	# Let the device start
	jtag.runtest(24)
	
	# Load with Bypass
	jtag.instruction(0xFF)
	jtag.shift_ir()
	jtag.instruction(0xFF)
	jtag.shift_ir()

	# Load with JSTART
	jtag.instruction(0x0C)
	jtag.shift_ir()

	jtag.runtest(24)
	
	# Check done pin
#		jtag.instruction(0xFF)
	# TODO: Figure this part out. & 0x20 should equal 0x20 to check the DONE pin ... ???
#		print jtag.read_ir() # & 0x20 == 0x21
#		jtag.instruction(0xFF)
#		jtag.shift_ir()
#		jtag.shift_dr([0])

	ft232r.flush()
	
	print "Done!"


# Option parsing:
parser = OptionParser(usage="%prog [-d <devicenum>] [-c <chain>] <path-to-bitstream-file>")
parser.add_option("-d", "--devicenum", type="int", dest="devicenum", default=0,
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
	ft232r.open(settings.devicenum, portlist)
	
	if settings.chain == 2:
		programBitstream(ft232r, 0, bitfile)
		programBitstream(ft232r, 1, bitfile)
	elif settings.chain == 0 or settings.chain == 1:
		programBitstream(ft232r, settings.chain, bitfile)
	else:
		print "ERROR: Invalid chain option!"
		parser.print_usage()
		exit()
