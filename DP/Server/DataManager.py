import os, datetime, pytz
import requests
import json
from xbos import get_client
from xbos.services.hod import HodClient
from datetime import timedelta
from xbos.services import mdal
import pandas as pd
import yaml
from copy import copy

# TODO add energy data acquisition
# TODO FIX DAYLIGHT TIME CHANGE PROBLEMS


class DataManager:
	"""
	# Class that handles all the data fetching and some of the preprocess
	"""
	def __init__(self, controller_cfg, advise_cfg, client, now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))):

		self.controller_cfg = controller_cfg
		self.advise_cfg = advise_cfg
		self.pytz_timezone = controller_cfg["Pytz_Timezone"]
		self.zone = advise_cfg["Data_Manager"]["Zone"]
		self.interval = controller_cfg["Interval_Length"]
		self.now = now
		self.horizon = advise_cfg["Advise"]["Hours"]
		self.c = client


	def preprocess_occ(self):
		"""
		Returns the required dataframe for the occupancy predictions
		-------
		Pandas DataFrame
		"""

		if self.advise_cfg["Advise"]["Sensors"]:
			hod = HodClient(self.controller_cfg["Building"]+"/hod", self.c)

			occ_query = """SELECT ?sensor ?uuid ?zone WHERE {
			  ?sensor rdf:type brick:Occupancy_Sensor .
			  ?sensor bf:isLocatedIn/bf:isPartOf ?zone .
			  ?sensor bf:uuid ?uuid .
			  ?zone rdf:type brick:HVAC_Zone
			};
			""" # get all the occupancy sensors uuids

			results = hod.do_query(occ_query) # run the query
			uuids = [[x['?zone'], x['?uuid']] for x in results['Rows']] # unpack

			# only choose the sensors for the zone specified in cfg
			query_list = []
			for i in uuids:
				if i[0] == self.zone:
					query_list.append(i[1])

			# get the sensor data
			c = mdal.MDALClient("xbos/mdal", client=self.c)
			dfs = c.do_query({'Composition': query_list,
							  'Selectors': [mdal.MAX] * len(query_list),
							  'Time': {'T0': (self.now - timedelta(days=25)).strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
									   'T1': self.now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
									   'WindowSize': str(self.interval) + 'min',
									   'Aligned': True}})

			dfs = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)

			df = dfs[[query_list[0]]]
			df.columns.values[0] = 'occ'
			df.is_copy = False
			df.columns = ['occ']
			# perform OR on the data, if one sensor is activated, the whole zone is considered occupied
			for i in range(1, len(query_list)):
				df.loc[:, 'occ'] += dfs[query_list[i]]
			df.loc[:, 'occ'] = 1 * (df['occ'] > 0)

			return df.tz_localize(None)
		else:
			occupancy_array = self.advise_cfg["Advise"]["Occupancy_Schedule"]

			def in_between(now, start, end):
				if start < end:
					return start <= now < end
				elif end < start:
					return start <= now or now < end
				else:
					return True

			now_time = self.now.astimezone(tz=pytz.timezone(self.controller_cfg["Pytz_Timezone"]))
			occupancy = []

			while now_time <= self.now + timedelta(hours=self.horizon):
				i = now_time.weekday()

				for j in occupancy_array[i]:
					if in_between(now_time.time(), datetime.time(int(j[0].split(":")[0]), int(j[0].split(":")[1])),
								  datetime.time(int(j[1].split(":")[0]), int(j[1].split(":")[1]))):
						occupancy.append(j[2])
						break

				now_time += timedelta(minutes=self.interval)

			return occupancy




	def preprocess_therm(self):

		#TODO get this done automated.
		def f1(row):
			"""
			helper function to format the thermal model dataframe
			"""
			if row['action'] == 1.:
				val = 1
			else:
				val = 0
			return val

		# if state is 2 we are doing cooling
		def f2(row):
			"""
			helper function to format the thermal model dataframe
			"""
			if row['action'] == 2.:
				val = 1
			else:
				val = 0
			return val

		def f3(row):
			"""
			helper function to format the thermal model dataframe
			"""
			if row['a'] > 0 and row['a'] <= 1.:
				return 1
			elif row['a'] > 1 and row['a'] <= 2.:
				return 2
			else:
				return 0

		uuids = [self.advise_cfg["Data_Manager"]["UUIDS"]["Thermostat_temperature"],
				 self.advise_cfg["Data_Manager"]["UUIDS"]["Thermostat_state"],
				 self.advise_cfg["Data_Manager"]["UUIDS"]["Temperature_Outside"]]

		# get the thermostat data
		c = mdal.MDALClient("xbos/mdal", client=self.c)
		dfs = c.do_query({'Composition': uuids,
						  'Selectors': [mdal.MEAN, mdal.MAX, mdal.MEAN],
						  'Time': {'T0': (self.now - timedelta(days=100)).strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
								   'T1': self.now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
								   'WindowSize': '1min',
								   'Aligned': True}})

		df = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)
		df = df.rename(columns={uuids[0]: 'tin', uuids[1]: 'a', uuids[2]:'t_out'})

		# thermal data preprocess starts here
		# TODO should we really make assumptions ?

		df = df.fillna(method='pad')
		df['a'] = df.apply(f3, axis=1)
		df['tin'] = df['tin'].replace(to_replace=0, method='pad')
		df['t_out'] = df['t_out'].replace(to_replace=0, method='pad')
		df.dropna()

		df['change_of_action'] = (df['a'].diff(1) != 0).astype('int').cumsum()

		listerino = []
		for j in df.change_of_action.unique():
			for dfs in [df[df['change_of_action'] == j][i:i + self.interval] for i in
						range(0, df[df['change_of_action'] == j].shape[0], self.interval)]:
				listerino.append({'time': dfs.index[0],
								  'tin': dfs['tin'][0],
								  't_next': dfs['tin'][-1],
								  'dt': dfs.shape[0],
								  'tout': dfs['t_out'][0],
								  'action': dfs['a'][0]})
		df = pd.DataFrame(listerino).set_index('time')
		df['a1'] = df.apply(f1, axis=1)
		df['a2'] = df.apply(f2, axis=1)
		return df.tz_localize(None)

	def weather_fetch(self):
		from dateutil import parser
		coordinates = self.controller_cfg["Coordinates"]  # TODO place this in the config file

		if not os.path.exists("weather.json"):
			temp = requests.get("https://api.weather.gov/points/" + coordinates).json()
			weather = requests.get(temp["properties"]["forecastHourly"])
			data = weather.json()
			with open('weather.json', 'w') as f:
				json.dump(data, f)

		myweather = json.load(open("weather.json"))
		json_start = parser.parse(myweather["properties"]["periods"][0]["startTime"])
		if (json_start.hour < self.now.astimezone(tz=pytz.timezone(self.pytz_timezone)).hour) or \
				(datetime.datetime(json_start.year, json_start.month, json_start.day).replace(tzinfo=pytz.timezone(self.pytz_timezone)) <
				 datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(
					 tz=pytz.timezone(self.pytz_timezone))):
			temp = requests.get("https://api.weather.gov/points/" + coordinates).json()
			weather = requests.get(temp["properties"]["forecastHourly"])
			data = weather.json()
			with open('weather.json', 'w') as f:
				json.dump(data, f)
			myweather = json.load(open("weather.json"))

		weather_predictions = {}

		for i, data in enumerate(myweather["properties"]["periods"]):
			hour = parser.parse(data["startTime"]).hour
			weather_predictions[hour] = int(data["temperature"])
			if i == self.horizon:
				break

		return weather_predictions

	def thermostat_setpoints(self):

		uuids = [self.advise_cfg["Data_Manager"]["UUIDS"]['Thermostat_high'],
				 self.advise_cfg["Data_Manager"]["UUIDS"]['Thermostat_low'],
				 self.advise_cfg["Data_Manager"]["UUIDS"]['Thermostat_mode']]

		c = mdal.MDALClient("xbos/mdal", client=self.c)
		dfs = c.do_query({'Composition': uuids,
						  'Selectors': [mdal.MEAN, mdal.MEAN, mdal.MEAN],
						  'Time': {'T0': (self.now - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
								   'T1': self.now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
								   'WindowSize': '1min',
								   'Aligned': True}})

		df = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)
		df = df.rename(columns={uuids[0]: 'T_High', uuids[1]: 'T_Low', uuids[2]: 'T_Mode'})

		return df['T_High'][-1], df['T_Low'][-1], df['T_Mode'][-1]

	def prices(self):

		price_array = self.controller_cfg["Pricing"][self.controller_cfg["Pricing"]["Energy_Rates"]]

		def in_between(now, start, end):
			if start < end:
				return start <= now < end
			elif end < start:
				return start <= now or now < end
			else:
				return True

		if self.controller_cfg["Pricing"]["Energy_Rates"] == "Server":
			# not implemented yet, needs fixing from the archiver
			# (always says 0, problem unless energy its free and noone informed me)
			raise ValueError('SERVER MODE IS NOT YET IMPLEMENTED FOR ENERGY PRICING')
		else:
			now_time = self.now.astimezone(tz=pytz.timezone(self.controller_cfg["Pytz_Timezone"]))
			pricing = []

			DR_start_time = [int(self.controller_cfg["Pricing"]["DR_Start"].split(":")[0]),
							 int(self.controller_cfg["Pricing"]["DR_Start"].split(":")[1])]
			DR_finish_time = [int(self.controller_cfg["Pricing"]["DR_Finish"].split(":")[0]),
							 int(self.controller_cfg["Pricing"]["DR_Finish"].split(":")[1])]

			while now_time <= self.now + timedelta(hours = self.horizon):
				i = 1 if now_time.weekday() >= 5 or self.controller_cfg["Pricing"]["Holiday"] else 0
				for j in price_array[i]:
					if in_between(now_time.time(), datetime.time(DR_start_time[0], DR_start_time[1]), datetime.time(DR_finish_time[0], DR_finish_time[1])) and \
						(self.controller_cfg["Pricing"]["DR"] or now_time.weekday()==4):
						pricing.append(self.controller_cfg["Pricing"]["DR_Price"])
					elif in_between(now_time.time(), datetime.time(int(j[0].split(":")[0]), int(j[0].split(":")[1])),
								  datetime.time(int(j[1].split(":")[0]), int(j[1].split(":")[1]))):
						pricing.append(j[2])
						break

				now_time += timedelta(minutes=self.interval)

		return pricing

	def building_setpoints(self):

		setpoints_array = self.advise_cfg["Advise"]["Setpoints"]
		def in_between(now, start, end):
			if start < end:
				return start <= now < end
			elif end < start:
				return start <= now or now < end
			else:
				return True

		now_time = self.now.astimezone(tz=pytz.timezone(self.controller_cfg["Pytz_Timezone"]))
		setpoints = []

		while now_time <= self.now + timedelta(hours=self.horizon):
			i = now_time.weekday()

			for j in setpoints_array[i]:
				if in_between(now_time.time(), datetime.time(int(j[0].split(":")[0]), int(j[0].split(":")[1])),
							  datetime.time(int(j[1].split(":")[0]), int(j[1].split(":")[1]))):
					setpoints.append([j[2], j[3]])
					break

			now_time += timedelta(minutes=self.interval)

		return setpoints

if __name__ == '__main__':

	with open("config_file.yml", 'r') as ymlfile:
		cfg = yaml.load(ymlfile)

	with open("Buildings/"+cfg["Building"]+"/ZoneConfigs/CentralZone.yml", 'r') as ymlfile:
		advise_cfg = yaml.load(ymlfile)

	if cfg["Server"]:
		c = get_client(agent=cfg["Agent_IP"], entity=cfg["Entity_File"])
	else:
		c = get_client()

	dm = DataManager(cfg, advise_cfg, c)
	print dm.weather_fetch()
	print dm.preprocess_therm()
	print dm.preprocess_occ()
	print dm.thermostat_setpoints()
	print dm.prices()
	print dm.building_setpoints()