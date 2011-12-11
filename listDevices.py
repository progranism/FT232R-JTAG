import d2xx

devices = d2xx.listDevices()

for d, serial in enumerate(devices):
	if len(devices) > 100:
		print "%3d %s" % (d, serial)
	elif len(devices) > 10:
		print "%2d %s" % (d, serial)
	else:
		print "%d %s" % (d, serial)
