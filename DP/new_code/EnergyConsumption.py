import datetime, pytz
from datetime import timedelta

# TODO ask someone what is going wrong with the price archiver
# TODO add energy prediction capabilities

class EnergyConsumption:

	def __init__(self, mode, interval, energy_df=None, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles")), heat=0.075, cool=1.25, vent=0.02):

		self.interval = interval
		self.heat = heat
		self.cool = cool
		self.vent = vent
		self.mode = mode
		self.now = now
		self.df = energy_df

	def calc_cost(self, action, time):

		now = self.now + timedelta(minutes=time*self.interval)
		weekno = now.weekday()
		# not implemented yet, needs fixing from the archiver
		# (always says 0, problem unless energy its free and noone informed me)
		if self.mode == "server":
			price = self.df['cost'][time]
		elif self.mode == "summer_rates":

			if weekno<5:
				if now.time() >= datetime.time(8,30) and now.time() < datetime.time(12,0):
					price = 0.231
				elif now.time() >= datetime.time(12,0) and now.time() < datetime.time(18,0):
					price = 0.254
				elif now.time() >= datetime.time(18,0) and now.time() < datetime.time(21,30):
					price = 0.231
				else:
					price = 0.203
			else:
				price = 0.203
		elif self.mode == "winter_rates":

			if weekno<5:
				if now.time() >= datetime.time(8,30) and now.time() < datetime.time(21,30):
					price = 0.221
				else:
					price = 0.20
			else:
				price = 0.20
		else: #peak charges

			if weekno<5:
				if self.now.time() >= datetime.time(8,30) and self.now.time() < datetime.time(12,0):
					price = 0.231
				elif self.now.time() >= datetime.time(12,0) and self.now.time() < datetime.time(14,0):
					price = 0.254
				elif self.now.time() >= datetime.time(14,0) and self.now.time() < datetime.time(18,0):
					price = 0.854
				elif self.now.time() >= datetime.time(18,0) and self.now.time() < datetime.time(21,30):
					price = 0.231
				else:
					price = 0.203
			else:
				price = 0.203


		if action == 'Heating' or action == '2':
			return (self.heat * float(self.interval) / 60.)*price
		elif action == 'Cooling' or action == '1':
			return (self.cool * float(self.interval) / 60.)*price
		elif action == 'Ventilation':
			return (self.vent * float(self.interval) / 60.)*price
		elif action == 'Do Nothing' or action == '0':
			return 0
		else:
			print("picked wrong action")
			return 0

if __name__ == '__main__':
	en_cons = EnergyConsumption("winter_rates")
	print en_cons.calc_cost("1", 0)