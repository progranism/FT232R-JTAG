class TAPStateError(Exception): pass

class TAP:
	TLR = 0
	IDLE = 1
	SELECT_DR = 2
	CAPTURE_DR = 3
	SHIFT_DR = 4
	EXIT1_DR = 5
	PAUSE_DR = 6
	EXIT2_DR = 7
	UPDATE_DR = 8
	SELECT_IR = 9
	CAPTURE_IR = 10
	SHIFT_IR = 11
	EXIT1_IR = 12
	PAUSE_IR = 13
	EXIT2_IR = 14
	UPDATE_IR = 15

	STR_TRANSLATE = ['TLR','IDLE','SELECT_DR','CAPTURE_DR','SHIFT_DR','EXIT1_DR','PAUSE_DR','EXIT2_DR','UPDATE_DR','SELECT_IR','CAPTURE_IR','SHIFT_IR','EXIT1_IR','PAUSE_IR','EXIT2_IR','UPDATE_IR']

	TRANSITIONS = {
		TLR: [IDLE, TLR],
		IDLE: [IDLE, SELECT_DR],
		SELECT_DR: [CAPTURE_DR, SELECT_IR],
		CAPTURE_DR: [SHIFT_DR, EXIT1_DR],
		SHIFT_DR: [SHIFT_DR, EXIT1_DR],
		EXIT1_DR: [PAUSE_DR, UPDATE_DR],
		PAUSE_DR: [PAUSE_DR, EXIT2_DR],
		EXIT2_DR: [SHIFT_DR, UPDATE_DR],
		UPDATE_DR: [IDLE, SELECT_DR],
		SELECT_IR: [CAPTURE_IR, TLR],
		CAPTURE_IR: [SHIFT_IR, EXIT1_IR],
		SHIFT_IR: [SHIFT_IR, EXIT1_IR],
		EXIT1_IR: [PAUSE_IR, UPDATE_IR],
		PAUSE_IR: [PAUSE_IR, EXIT2_IR],
		EXIT2_IR: [SHIFT_IR, UPDATE_IR],
		UPDATE_IR: [IDLE, SELECT_DR]
	}

	def __init__(self, jtagClock):
		self.jtagClock = jtagClock
		self.state = None
		self.debug = 0
	
	def reset(self):
		for i in range(6):
			self.jtagClock(tms=1)

		self.state = TAP.TLR
	
	def clocked(self, tms):
		if self.state is None:
			if self.debug:
				print "TAP-DEBUG: TMS clocked, but state is Unknown."
			return
		
		state = self.state
		self.state = TAP.TRANSITIONS[self.state][tms]

		print "TAP-DEBUG: Transitioned (%i) from %i to %i." % (tms, state, self.state)
	
	def shiftIR(self, bits):
		self.goto(TAP.SELECT_IR)
		self.goto(TAP.SHIFT_IR)

		for bit in bits[:-1]:
			self.jtagClock(tdi=bit)
		self.jtagClock(tdi=bits[-1], tms=1)

		self.goto(TAP.IDLE)
	
	def shiftDR(self, bits):
		self.goto(TAP.SELECT_DR)
		self.goto(TAP.SHIFT_DR)

		for bit in bits[:-1]:
			self.jtagClock(tdi=bit)
		self.jtagClock(tdi=bits[-1], tms=1)

		self.goto(TAP.IDLE)

	
	# When goto is called, we look at where we want to go and where we are.
	# Based on that we choose where to clock TMS low or high.
	# After that we see if we've reached our goal. If not, call goto again.
	# This recursive behavior keeps the function simple.
	def goto(self, state):
		# If state is Unknown, reset.
		if self.state is None:
			if self.debug:
				print "TAP-DEBUG: goto called, but state is Unknown. Resetting."
			self.reset()
		elif state == TAP.TLR:
			self.jtagClock(tms=1)
		elif self.state == TAP.TLR:
			self.jtagClock(tms=0)
		elif state == TAP.SELECT_DR:
			if self.state != TAP.IDLE:
				raise TAPStateError()

			self.jtagClock(tms=1)
		elif state == TAP.SELECT_IR:
			if self.state != TAP.IDLE:
				raise TAPStateError()

			self.jtagClock(tms=1)
			self.jtagClock(tms=1)
		elif state == TAP.SHIFT_DR:
			if self.state != TAP.SELECT_DR:
				raise TAPStateError()

			self.jtagClock(tms=0)
			self.jtagClock(tms=0)
		elif state == TAP.SHIFT_IR:
			if self.state != TAP.SELECT_IR:
				raise TAPStateError()

			self.jtagClock(tms=0)
			self.jtagClock(tms=0)
		elif state == TAP.IDLE:
			if self.state != TAP.EXIT1_DR or self.state != TAP.EXIT1_IR:
				raise TAPStateError()

			self.jtagClock(tms=1)
			self.jtagClock(tms=0)
		else:
			raise TAPStateError()


		if self.state != state:
			self.goto(state)
		
	
	

