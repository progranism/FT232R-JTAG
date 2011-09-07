from jtag import JTAG


with JTAG() as jtag:
	jtag.open(0)

	print "Discovering JTAG Chain ..."
	jtag.detect()

	print "Found %i devices ...\n" % jtag.deviceCount

	for idcode in jtag.idcodes:
		JTAG.decodeIdcode(idcode)
	
	print "\n"

	print "Beginning programming..."

	#jtag.

