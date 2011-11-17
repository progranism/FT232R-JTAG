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

import d2xx
import time

def safe_read(handle, count):
	while handle.getQueueStatus() < count:
		time.sleep(1)
		print "Waiting to read..."
	
	return handle.read(count)


print "Opening"
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

