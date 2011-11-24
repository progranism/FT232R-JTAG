	# -*- coding: utf-8 -*-

	# Copyright (C) 2011 by jedi95 <jedi95@gmail.com> and 
	#								CFSworks <CFSworks@gmail.com>
	#								fizzisist <fizzisist@fpgamining.com>
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

import sys
from time import time
from datetime import datetime
from threading import Lock

def formatNumber(n):
	"""Format a positive integer in a more readable fashion."""
	if n < 0:
	  raise ValueError('can only format positive integers')
	prefixes = 'KMGTP'
	whole = str(int(n))
	decimal = ''
	i = 0
	while len(whole) > 3:
		if i + 1 < len(prefixes):
			decimal = '.%s' % whole[-3:-1]
			whole = whole[:-3]
			i += 1
		else:
			break
	return '%s%s %s' % (whole, decimal, prefixes[i])
	  
class ConsoleLogger(object):
	"""This class will handle printing messages to the console."""

	TIME_FORMAT = '[%Y-%m-%d %H:%M:%S]'

	UPDATE_TIME = 1.0

	SPARKLINE_LENGTH = 10 # number of bins to display of the sparkline
	SPARKLINE_BINSIZE = 5 # number of mins for each bin of the sparkline

	def __init__(self, chain=0, verbose=False): 
		self.chain = chain
		if chain == 2:
			self.chain_list = [0, 1]
		elif chain >= 0 and chain < 2:
			self.chain_list = [chain]
		else:
			Exception('Invalid chain option (%d)!' % chain)
		self.verbose = verbose
		self.lastUpdate = time() - 1
		self.start_time = time()
		self.rate = []
		self.last_rate_update = time()
		self.accepted = [0, 0]
		self.invalid = [0, 0]
		self.recent_shares = 0
		self.sparkline = ''
		self.lineLength = 0
		self.connectionType = None
		self.connected = False
		self.print_lock = Lock()

	def start(self):
		self.start_time = time()
	
	def getRate(self):
		if time() > self.last_rate_update + self.SPARKLINE_BINSIZE * 60:
			recent_secs = time() - self.last_rate_update
			recent_rate = self.recent_shares * pow(2, 32) / recent_secs
			if len(self.rate) < self.SPARKLINE_LENGTH:
				 self.rate.append(recent_rate)
			else:
				 self.rate.pop(0)
				 self.rate.append(recent_rate)
			self.recent_shares = 0
			self.sparkline = self.makeSparkline()
			self.last_rate_update = time()

		secs = time() - self.last_rate_update
		if secs > 0:
			current_rate = self.recent_shares * pow(2, 32) / secs
		else:
			current_rate = 0
		current_rate += sum(self.rate)
		current_rate /= len(self.rate) + 1
		return current_rate
	  
	def makeSparkline(self):
		'''Make a simple graph of hashrate over time.
		Inspired by: https://github.com/holman/spark
		'''
		ticks = (u'▁', u'▂', u'▃', u'▄', u'▅', u'▆', u'▇', u'█')
		sparkline = ''
		max_rate = max(self.rate)
		for rate in self.rate:
			if max_rate > 0:
				 rate = int(len(ticks) * rate / max_rate) - 1
			else:
				 rate = 0
			sparkline += ticks[rate]
		return sparkline
	  
	def reportType(self, type):
		self.connectionType = type

	def reportBlock(self, block):
		self.log('Currently on block: ' + str(block))
	  
	def reportFound(self, hash, accepted, chain=0):
		if accepted is not None and accepted == True:
			self.accepted[chain] += 1
		else:
			self.invalid[chain] += 1
			accepted = False
			
		self.recent_shares += 1

		if self.verbose:
			self.log('(FPGA%d) %s %s' % (chain, 'accepted' if accepted else 'rejected', 
				 hash))
		else:
			self.log('%s %s' % ('accepted' if accepted else 'rejected', 
				 hash))
			
	def reportMsg(self, message):
		self.log(('MSG: ' + message), True, True)

	def reportConnected(self, connected):
		if connected and not self.connected:
			self.log('Connected to server')
			self.connected = True
		elif not connected and self.connected:
			self.log('Disconnected from server')
			self.connected = False

	def reportConnectionFailed(self):
		self.log('Failed to connect, retrying...')

	def reportDebug(self, message):
		if self.verbose:
			self.log(message)
			
	def printSummary(self, devicenum):
		self.log('Run Summary:')
		self.log('-------------')
		self.log('Device: %d' % devicenum)
		self.log('Number of FPGAs: %d' % len(self.chain_list))
		self.log('JTAG chain: %d' % self.chain)
		secs = time() - self.start_time
		self.log('Running time: %d mins' % (secs/60))
		total_nonces = 0
		for chain in chain_list:
			acc = self.accepted[chain]
			rej = self.invalid[chain]
			total = acc + rej
			total_nonces += total
			self.log(' Chain %d:' % chain)
			self.log(' Accepted: %d' % acc)
			self.log(' Rejected: %d (%.2f%%)' % (rej, (100. * rej / total)))
			self.log(' Total: %d' % total)
			self.log(' Accepted hashrate: %sH/s' % (formatNumber(pow(2,32)*acc/(secs*1000))))
			self.log(' Total hashrate: %sH/s' % (formatNumber(pow(2,32)*total/(secs*1000))))
		self.log('Total hashrate for device: %sH/s' % (formatNumber(pow(2,32)*total_nonces/(secs*1000))))
	  
	def updateStatus(self, force=False):
		#only update if last update was more than UPDATE_TIME seconds ago
		dt = time() - self.lastUpdate
		if force or dt > self.UPDATE_TIME:
			status = '[%sH/s]' % formatNumber(self.getRate()/1000)
			if self.verbose:
				 for chain in self.chain_list:
					  status += ' [FPGA%d: %d/%d]' % (chain, self.accepted[chain], self.invalid[chain])
				 status += ' [%d nonces/' % (sum(self.accepted)+sum(self.invalid))
				 status += '%d min]' % ((time()-self.start_time)/60)
			else:
				 status += ' [%d/%d]' % (sum(self.accepted), sum(self.invalid))
			#status += ' ' + self.sparkline
			self.say(status)
			self.lastUpdate = time()
	  
	def say(self, message, newLine=False, hideTimestamp=False):
		#add new line if requested
		if newLine:
			message += '\n'
			if hideTimestamp:
				 timestamp = ''
			else:
				 timestamp = datetime.now().strftime(self.TIME_FORMAT) + ' '
				 
			message = timestamp + message

		#wait until nothing else is being printed
		self.print_lock.acquire()

		#erase the previous line
		if self.lineLength > 0:
			sys.stdout.write('\b \b' * self.lineLength)
			sys.stdout.write(' ' * self.lineLength)
			sys.stdout.write('\b \b' * self.lineLength)

		#print the line
		sys.stdout.write(message)
		sys.stdout.flush()

		self.print_lock.release()

		#cache the current line length
		if newLine:
			self.lineLength = 0
		else:
			self.lineLength = len(message)

	def log(self, message, update=True, hideTimestamp=False):
		self.say(message, True, hideTimestamp)
		if update:
			self.updateStatus(True)
	  
