import d2xx
import time

def safe_read(handle, count):
	while handle.getQueueStatus() < count:
		time.sleep(1)
		print "Waiting to read..."
	
	return handle.read(count)


print "Openning"
handle = d2xx.open(0)
handle.setBitMode(0x0F, 0)
handle.setBitMode(0x0F, 4)
handle.setBaudRate(3000000)

print "Write and read?"
handle.write("\x00"*100)
safe_read(handle, 100)

handle.setBitMode(0x0F, 0)
handle.setBitMode(0x0F, 1)


print "Writing"
CHUNK_SIZE = 4096*4
for i in range(16000000/CHUNK_SIZE):
	print "Wrote: ", handle.write("\x00"*CHUNK_SIZE)

print handle.getStatus()
print handle.getQueueStatus()

handle.setBitMode(0x0F, 0)
handle.setBitMode(0x0f, 4)
handle.purge(0)

print "Write and read?"
handle.write("\x00"*100)
safe_read(handle, 100)



handle.close()

