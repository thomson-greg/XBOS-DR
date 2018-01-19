import datetime, pytz
from datetime import timedelta
from xbos import get_client
from xbos.services.pundat import DataClient, make_dataframe

class EnergyConsumption:
	def __init__(self, now=datetime.datetime.now(pytz.timezone("America/Los_Angeles")), heat=4000, cool=4000, vent=500):
		self.heat = heat
		self.cool = cool
		self.vent = vent

		self.mode = "event_day_rates" # options are "server", "summer_rates", "winter_rates", "event_day_rates"
		self.now = now
		c = get_client(agent = '172.17.0.1:28589', entity="thanos.ent")
		#c = get_client()
		archiver = DataClient(c)

		energy_cost= "9dc5b5cd-8cb1-3dd3-b582-5ed6bf3f0083"

		uuids = [energy_cost]

		start = '"' + (now + timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M:%S') + ' PST"'
		end = '"' + (now - timedelta(hours=8)).strftime('%Y-%m-%d %H:%M:%S') + ' PST"'
		
																																																																																																																																																																																																																																																																																																																																																																																																																																																																																																				
		dfs = make_dataframe(archiver.window_uuids(uuids, end, start, '15min', timeout=120))

		for uid, df in dfs.items():
			
			if uid == uuids[0]:
				if 'mean' in df.columns:
					df = df[['mean']]
				df.columns = ['cost']
				
			dfs[uid] = df.resample('15min').mean()

		uid, self.df = dfs.items()[0]

	def calc_cost(self, action, time, period=15):
		if self.mode == "server":
			price = self.df['cost'][time]
		elif self.mode == "summer_rates":
			weekno = self.now.weekday()

			if weekno<5:
				temp_now = self.now + timedelta(minutes=time*period)
				if temp_now.time() >= datetime.time(8,30) or temp_now.time() < datetime.time(12,0):
					price = 0.231
				elif temp_now.time() >= datetime.time(12,0) or temp_now.time() < datetime.time(18,0):
					price = 0.254
				elif temp_now.time() >= datetime.time(18,0) or temp_now.time() < datetime.time(21,30):
					price = 0.231
				else:
					price = 0.203
			else:
				price = 0.203
		elif self.mode == "winter_rates":
			weekno = self.now.weekday()

			if weekno<5:
				temp_now = self.now + timedelta(minutes=time*period)
				if temp_now.time() >= datetime.time(8,30) or temp_now.time() < datetime.time(21,30):
					price = 0.221
				else:
					price = 0.20
			else:
				price = 0.20
		else:
			weekno = self.now.weekday()

			if weekno<5:
				temp_now = self.now + timedelta(minutes=time*period)
				if temp_now.time() >= datetime.time(8,30) or temp_now.time() < datetime.time(12,0):
					price = 0.231
				elif temp_now.time() >= datetime.time(12,0) or temp_now.time() < datetime.time(14,0):
					price = 0.254
				elif temp_now.time() >= datetime.time(14,0) or temp_now.time() < datetime.time(18,0):
					price = 0.854
				elif temp_now.time() >= datetime.time(18,0) or temp_now.time() < datetime.time(21,30):
					price = 0.231
				else:
					price = 0.203
			else:
				price = 0.203


		if action == 'Heating' or action == '2':
			return (self.heat / period * 60 / 1000)*price
		elif action == 'Cooling' or action == '1':
			return self.cool / period * 60 / 1000*price
		elif action == 'Ventilation':
			return self.vent / period * 60 / 1000*price
		elif action == 'Do Nothing' or action == '0':
			return 0
		else:
			print("picked wrong action")
			return 0