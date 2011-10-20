from ft232rjtag import FT232RJTAG

with FT232RJTAG() as jtag:
	jtag.open(0)
	#if not jtag.open(0):
	#print "Unable to open the JTAG communication device. Is the board attached by USB?"
	#exit()

	jtag.stressTest()

