# Copyright (C) 2011 by fpgaminer <fpgaminer@bitcoin-mining.com>
#                       fizzisist <fizzisist@fpgamining.com>
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

from ft232r import FT232R, FT232R_PortList
from jtag import JTAG
from BitstreamReader import BitFile, BitFileReadError, BitFileMismatch
import time
from optparse import OptionParser
from ConsoleLogger import ConsoleLogger

# Option parsing:
parser = OptionParser(usage="%prog [-d <devicenum>] [-c <chain>] <path-to-bitstream-file>")
parser.add_option("-d", "--devicenum", type="int", dest="devicenum", default=0,
                  help="Device number, default 0 (only needed if you have more than one board)")
parser.add_option("-c", "--chain", type="int", dest="chain", default=0,
                  help="JTAG chain number, can be 0, 1, or 2 for both FPGAs on the board (default 0)")
parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False,
                  help="Verbose logging")
settings, args = parser.parse_args()

# LSB first
def bits2int(bits):
	x = 0
	for i in range(len(bits)):
		x |= bits[i] << i
	return x

def bitstreamProgress(start_time, now_time, written, total):
	message = "Completed: %.1f%% [%.1f kB/s]\r" % (100.0 * written / total, 0.001 * written  / (now_time - start_time))
	print message,

def programBitstream(ft232r, jtag, chain, processed_bitstream):
	# Select the device
	jtag.reset()
	jtag.part(jtag.deviceCount-1)
	
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
	jtag.load_bitstream(processed_bitstream)

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

logger = ConsoleLogger(settings.chain, settings.verbose)

if len(args) == 0:
	logger.log("ERROR: No bitstream file specified!")
	parser.print_usage()
	exit()
	
### Bitfile ###
bitfileName = args[0]
logger.log("Opening bitstream file: " + bitfileName)
bitfile = None

try:
	bitfile = BitFile.read(bitfileName)
except BitFileReadError, e:
	print e
	exit()

logger.log("Bitstream file opened:")
logger.log("      Design Name: %s" % bitfile.designname)
logger.log("        Part Name: %s" % bitfile.part)
logger.log("             Date: %s" % bitfile.date)
logger.log("             Time: %s" % bitfile.time)
logger.log(" Bitstream Length: %d" % len(bitfile.bitstream))

with FT232R() as ft232r:
	portlist = FT232R_PortList(7, 6, 5, 4, 3, 2, 1, 0)
	ft232r.open(settings.devicenum, portlist)
	
	if settings.chain == 2:
		chain_list = [0,1]
	elif settings.chain == 0 or settings.chain == 1:
		chain_list = [settings.chain]
	else:
		logger.log("ERROR: Invalid chain option!")
		parser.print_usage()
		exit()
	
	jtag = [None, None]
	
	for chain in chain_list:
		jtag[chain] = JTAG(ft232r, portlist.chain_portlist(chain), chain)
		logger.log("Discovering JTAG chain %d ..." % chain)
		jtag[chain].detect()
		
		logger.log("Found %i device%s:" % (jtag[chain].deviceCount,
		                                   's' if jtag[chain].deviceCount != 1 else ''))
		
		for idcode in jtag[chain].idcodes:
			logger.log(JTAG.decodeIdcode(idcode))
			if idcode & 0x0FFFFFFF != bitfile.idcode:
				raise BitFileMismatch
	
	if bitfile.processed:
		logger.log("Loading pre-processed bitstream...")
		start_time = time.time()
		processed_bitstreams = BitFile.load_processed(bitfileName)
		logger.log("Loaded pre-processed bitstream in %f seconds" % (time.time() - start_time))
	else:
		logger.log("Pre-processing bitstream...")
		start_time = time.time()
		processed_bitstreams = BitFile.pre_process(bitfile.bitstream, jtag, chain_list)
		logger.log("Pre-processed bitstream in %f seconds" % (time.time() - start_time))
		logger.log("Saving pre-processed bitstream...")
		start_time = time.time()
		BitFile.save_processed(processed_bitstreams, bitfileName)
		logger.log("Saved pre-processed bitstream in %f seconds" % (time.time() - start_time))
	
	logger.log("Beginning programming...")
	for chain in chain_list:
		logger.log("Programming FPGA %d..." % chain)
		start_time = time.time()
		programBitstream(ft232r, jtag[chain], chain, processed_bitstreams[chain])
		logger.log("Programmed FPGA %d in %f seconds" % (chain, time.time() - start_time))
