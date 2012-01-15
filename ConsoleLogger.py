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
	prefixes = 'kMGTP'
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
	
def formatTime(seconds):
	"""Take a number of seconds and turn it into a string like 32m18s"""
	minutes = int(seconds / 60)
	hours = int(minutes / 60)
	days = int(hours / 24)
	weeks = int(days / 7)
	seconds = seconds % 60
	minutes = minutes % 60
	hours = hours % 24
	days = days % 7
	
	time_string = ''
	if weeks > 0:
		time_string += '%dw' % weeks
	if days > 0:
		time_string += '%dd' % days
	if hours > 0:
		time_string += '%dh' % hours
	if minutes > 0:
		time_string += '%dm' % minutes
	if hours < 1:
		# hide the seconds when we're over an hour
		time_string += '%ds' % seconds
	
	return time_string
	
class ConsoleLogger(object):
	"""This class will handle printing messages to the console."""

	TIME_FORMAT = '%Y-%m-%d %H:%M:%S |'

	UPDATE_TIME = 1.0

	SPARKLINE_LENGTH = 30 # number of bins to display of the sparkline
	SPARKLINE_BINSIZE = 6 # number of mins for each bin of the sparkline

	def __init__(self, verbose=False): 
		self.fpga_list = []
		self.verbose = verbose
		self.lastUpdate = time() - 1
		self.start_time = time()
		self.rate = []
		self.last_rate_update = time()
		self.recent_valids = 0
		self.total_valids = 0
		self.sparkline = ''
		self.lineLength = 0
		self.connectionType = None
		self.connected = False
		self.print_lock = Lock()

	def start(self):
		self.start_time = time()
		self.last_rate_update = time()
	
	def getRate(self):
		if time() > self.last_rate_update + self.SPARKLINE_BINSIZE * 60:
			recent_secs = time() - self.last_rate_update
			recent_rate = self.recent_valids * pow(2, 32) / recent_secs
			if len(self.rate) < self.SPARKLINE_LENGTH:
				 self.rate.append(recent_rate)
			else:
				 self.rate.pop(0)
				 self.rate.append(recent_rate)
			self.recent_valids = 0
			#self.sparkline = self.makeSparkline()
			self.last_rate_update = time()

		secs = time() - self.last_rate_update
		if secs > 0:
			if self.recent_valids > 0 or self.total_valids == 0:
					current_rate = self.recent_valids * pow(2, 32) / secs
			else:
				current_rate = pow(2, 32) / secs
		elif len(self.rate) > 0:
			current_rate = sum(self.rate) / len(self.rate)
		else:
			current_rate = 0
		current_rate += sum(self.rate)
		current_rate /= len(self.rate) + 1
		return current_rate
	  
	def makeSparkline(self):
		'''Make a simple graph of hashrate over time.
		Inspired by: https://github.com/holman/spark
		'''
		#ticks = (u'▁', u'▂', u'▃', u'▄', u'▅', u'▆', u'▇')
		ticks = ('0', '1', '2', '3', '4', '5', '6', '7', '8', '9')
		sparkline = ''
		max_rate = max(self.rate)
		for rate in self.rate:
			if max_rate > 0:
				 rate = int(len(ticks) * rate / max_rate) - 1
			else:
				 rate = 0
			sparkline += ticks[rate]
		return sparkline
		
	def reportOpened(self, devicenum, serial):
		self.devicenum = devicenum
		self.serial = serial
		self.log('Device %d opened (%s)' % (devicenum, serial), False)
	  
	def reportType(self, type):
		self.connectionType = type

	def reportBlock(self, block):
		self.log('Currently on block: ' + str(block))
	
	def reportNonce(self, fpgaID):
		self.fpga_list[fpgaID].nonce_count += 1
		self.reportDebug('%d: Golden nonce found' % fpgaID)
	  
	def reportFound(self, hash, accepted, fpgaID):
		if accepted is not None and accepted == True:
			self.fpga_list[fpgaID].accepted_count += 1
		else:
			self.fpga_list[fpgaID].rejected_count += 1
			accepted = False

		if self.verbose:
			self.log('%d: %s %s' % (fpgaID, 'accepted' if accepted else 'rejected', 
				 hash))
		else:
			self.log('%s %s' % ('accepted' if accepted else 'rejected', 
				 hash))
	
	def reportValid(self, fpgaID):
		self.fpga_list[fpgaID].valid_count += 1
		self.recent_valids += 1
		self.total_valids += 1
	
	def reportError(self, hash, fpgaID):
		self.fpga_list[fpgaID].invalid_count += 1
		if self.verbose:
			self.log('%d: %s invalid!!' % (fpgaID, hash))
		else:
			self.log('%s invalid!!' % hash)
	
	def reportMsg(self, message):
		self.log(('MSG: ' + message), True, True)
		
	def reportLongPoll(self, message):
		self.log('Long-poll: %s' % message)

	def reportConnected(self, connected):
		if connected and not self.connected:
			self.log('Connected to server')
			self.connected = True
		elif not connected and self.connected:
			self.log('Disconnected from server')
			self.connected = False

	def reportConnectionFailed(self):
		self.log('Failed to connect, retrying...')

	def reportDebug(self, message, update=True):
		if self.verbose:
			self.log(message, update)
			
	def printSummary(self, settings):
		self.say('Run Summary:', True, True)
		self.say('-------------', True, True)
		self.say('Device: %d' % self.devicenum, True, True)
		self.say('Serial: %s' % self.serial, True, True)
		self.say('Number of FPGAs: %d' % len(self.fpga_list), True, True)
		secs = time() - self.start_time
		self.say('Running time: %s' % formatTime(secs), True, True)
		if secs <= 0:
			secs = 1
		self.say('Getwork interval: %d secs' % settings.getwork_interval, True, True)
		total_nonces = 0
		total_valids = 0
		total_accepted = 0
		for fpga in self.fpga_list:
			nonces = fpga.nonce_count
			valids = fpga.valid_count
			invalids = fpga.invalid_count
			accepted = fpga.accepted_count
			rejected = fpga.rejected_count
			
			try:
				rejected_pct = 100. * rejected / (rejected+accepted)
			except ZeroDivisionError:
				rejected_pct = 0
			
			try:
				invalid_pct = 100. * invalids / nonces
			except ZeroDivisionError:
				invalid_pct = 0
			
			total_nonces += nonces
			total_valids += valids
			total_accepted += accepted
			
			self.say('FPGA %d:' % fpga.id, True, True)
			self.say('  Accepted: %d' % accepted, True, True)
			self.say('  Rejected: %d (%.2f%%)' % (rejected, rejected_pct), True, True)
			self.say('  Invalid: %d (%.2f%%)' % (invalids, invalid_pct), True, True)
			
			self.say('  Hashrate (all nonces): %sH/s' % (formatNumber(pow(2,32)*nonces/(secs*1000))),
			         True, True)
			self.say('  Hashrate (valid nonces): %sH/s' % (formatNumber(pow(2,32)*valids/(secs*1000))),
			         True, True)
			self.say('  Hashrate (accepted shares): %sH/s' % (formatNumber(pow(2,32)*accepted/(secs*1000))),
			         True, True)
		
		self.say('Total hashrate for device: %sH/s / %sH/s / %sH/s' % (
		         formatNumber(pow(2,32)*total_nonces/(secs*1000)),
		         formatNumber(pow(2,32)*total_valids/(secs*1000)),
				 formatNumber(pow(2,32)*total_accepted/(secs*1000))),
		         True, True)
	  
	def updateStatus(self, force=False):
		#only update if last update was more than UPDATE_TIME seconds ago
		dt = time() - self.lastUpdate
		if force or dt > self.UPDATE_TIME:
			status = '%sH/s' % formatNumber(self.getRate()/1000) # TODO: Give some indication of the quality of the hashrate estimate (sig. figures?)
			if self.verbose:
				for fpga in self.fpga_list:
					acc = fpga.accepted_count
					rej = fpga.rejected_count
					tot = fpga.nonce_count
					inv = fpga.invalid_count
					try:
						rej_pct = 100.*rej/(acc+rej)
					except ZeroDivisionError:
						rej_pct = 0
					try:
						inv_pct = 100.*inv/tot
					except ZeroDivisionError:
						inv_pct = 0
					status += ' | %d: %d/%d/%d %.1f%%/%.1f%%' % (fpga.id, acc, rej, inv, rej_pct, inv_pct)
				status += ' | ' + formatTime(time()-self.start_time)
				status += ' | ' + self.serial
			else:
				acc = sum([fpga.accepted_count for fpga in self.fpga_list])
				rej = sum([fpga.accepted_count for fpga in self.fpga_list])
				tot = sum([fpga.accepted_count for fpga in self.fpga_list])
				inv = sum([fpga.accepted_count for fpga in self.fpga_list])
				try:
					rej_pct = 100.*rej/(acc+rej)
				except ZeroDivisionError:
					rej_pct = 0
				try:
					inv_pct = 100.*inv/tot
				except ZeroDivisionError:
					inv_pct = 0
				status += ' | %d/%d/%d %.2f%%/%.2f%%' % (acc, rej, inv, rej_pct, inv_pct)
				#status += ' ' + self.sparkline
			self.say(status)
			self.lastUpdate = time()
	
	def updateProgress(self, start_time, now_time, written, total):
		try:
			percent_complete = 100. * written / total
		except ZeroDivisionError:
			percent_complete = 0
		try:
			speed = written / (1000 * (now_time - start_time))
		except ZeroDivisionError:
			speed = 0
		try:
			remaining_sec = 100 * (now_time - start_time) / percent_complete
		except ZeroDivisionError:
			remaining_sec = 0
		remaining_sec -= now_time - start_time
		status = "Completed: %.1f%% [%sB/s] [%s remaining]" % (percent_complete, formatNumber(speed), formatTime(remaining_sec))
		self.say(status)
	  
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
	  
