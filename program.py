#!/usr/bin/python
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
from fpga import FPGA
import time
from optparse import OptionParser
from ConsoleLogger import ConsoleLogger

# Option parsing:
parser = OptionParser(usage="%prog [-d <devicenum>] [-c <chain>] <path-to-bitstream-file>")
parser.add_option("-d", "--devicenum", type="int", dest="devicenum", default=None,
                  help="Device number, optional. Opens the first available device by default")
parser.add_option("-c", "--chain", type="int", dest="chain", default=2,
                  help="JTAG chain number, can be 0, 1, or 2 for both FPGAs on the board (default 2)")
parser.add_option("-v", "--verbose", action="store_true", dest="verbose", default=False,
                  help="Verbose logging")
parser.add_option("-s", "--sleep", action="store_true", dest="sleep", default=False,
                  help="Put FPGAs to sleep after programming [EXPERIMENTAL]")
settings, args = parser.parse_args()

logger = ConsoleLogger(settings.verbose)

if len(args) == 0:
	logger.log("ERROR: No bitstream file specified!", False)
	parser.print_usage()
	exit()
	
### Bitfile ###
bitfileName = args[0]
logger.log("Opening bitstream file: " + bitfileName, False)
bitfile = None

try:
	bitfile = BitFile.read(bitfileName)
except BitFileReadError, e:
	print e
	exit()

logger.log("Bitstream file opened:", False)
logger.log(" Design Name: %s" % bitfile.designname, False)
logger.log(" Part Name: %s" % bitfile.part, False)
logger.log(" Date: %s" % bitfile.date, False)
logger.log(" Time: %s" % bitfile.time, False)
logger.log(" Bitstream Length: %d" % len(bitfile.bitstream), False)

fpga_list = []

with FT232R() as ft232r:
	portlist = FT232R_PortList(7, 6, 5, 4, 3, 2, 1, 0)
	if ft232r.open(settings.devicenum, portlist):
		logger.reportOpened(ft232r.devicenum, ft232r.serial)
	else:
		logger.log("ERROR: FT232R device not opened!", False)
		exit()
	
	if settings.chain == 0 or settings.chain == 1:
		fpga_list.append(FPGA(ft232r, settings.chain, logger))
	elif settings.chain == 2:
		fpga_list.append(FPGA(ft232r, 0, logger))
		fpga_list.append(FPGA(ft232r, 1, logger))
	else:
		logger.log("ERROR: Invalid chain option!", False)
		parser.print_usage()
		exit()
	
	for id, fpga in enumerate(fpga_list):
		fpga.id = id
		logger.reportDebug("Discovering FPGA %d ..." % id, False)
		fpga.detect()
		
		logger.reportDebug("Found %i device%s:" % (fpga.jtag.deviceCount,
			's' if fpga.jtag.deviceCount != 1 else ''), False)
		
		if fpga.jtag.deviceCount > 1:
			logger.log("Warning:", False)
			logger.log("This software currently supports only one device per chain.", False)
			logger.log("Only part 0 will be programmed.", False)

		for idcode in fpga.jtag.idcodes:
			msg = " FPGA" + str(id) + ": "
			msg += JTAG.decodeIdcode(idcode)
			logger.reportDebug(msg, False)
			if idcode & 0x0FFFFFFF != bitfile.idcode:
				raise BitFileMismatch
	
	logger.log("Connected to %d FPGAs" % len(fpga_list), False)
	
	if settings.chain == 2:
		jtag = JTAG(ft232r, settings.chain)
		jtag.deviceCount = 1
		jtag.idcodes = [bitfile.idcode]
		jtag._processIdcodes()
	else:
		jtag = fpga_list[settings.chain].jtag
	
	if bitfile.processed[settings.chain]:
		logger.log("Loading pre-processed bitstream...", False)
		start_time = time.time()
		processed_bitstream = BitFile.load_processed(bitfileName, settings.chain)
		logger.log("Loaded pre-processed bitstream in %f seconds" % (time.time() - start_time), False)
	else:
		logger.log("Pre-processing bitstream for chain = %d..." % settings.chain, False)
		start_time = time.time()
		processed_bitstream = BitFile.pre_process(bitfile.bitstream, jtag, settings.chain, logger.updateProgress)
		logger.log("Pre-processed bitstream in %f seconds" % (time.time() - start_time), False)
		logger.log("Saving pre-processed bitstream...", False)
		start_time = time.time()
		BitFile.save_processed(bitfileName, processed_bitstream, settings.chain)
		logger.log("Saved pre-processed bitstream in %f seconds" % (time.time() - start_time), False)
	
	logger.log("Beginning programming...", False)
	if settings.chain == 2:
		logger.log("Programming both FPGAs...", False)
	else:
		logger.log("Programming FPGA %d..." % settings.chain, False)
	start_time = time.time()
	FPGA.programBitstream(ft232r, jtag, logger, processed_bitstream)
	if settings.chain == 2:
		logger.log("Programmed both FPGAs in %f seconds" % (time.time() - start_time), False)
	else:
		logger.log("Programmed FPGA %d in %f seconds" % (settings.chain, time.time() - start_time), False)
	
	if settings.sleep:
		for fpga in fpga_list:
			fpga.sleep()
