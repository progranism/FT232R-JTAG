#!/usr/bin/python

import os

os.system('rmmod ftdi_sio')

import d2xx

devices = d2xx.listDevices()

for devicenum, serial in enumerate(devices):
	try: 
		h = d2xx.open(devicenum)
		h.close()
		isopen = True
	except:
		isopen = False
	
	print "%2d %s %s" % (devicenum, serial, '*' if isopen else '')

print "* means this device is currently available"
