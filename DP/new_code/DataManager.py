import os, datetime, pytz
import requests
import json
import yaml
from xbos import get_client
from xbos.services.hod import HodClient
from datetime import timedelta
from xbos.services import mdal
import pandas as pd


def f1(row):
	if row['action'] == 1.:
		val = 1
	else:
		val = 0
	return val


# if state is 2 we are doing cooling
def f2(row):
	if row['action'] == 2.:
		val = 1
	else:
		val = 0
	return val

def f3(row):
	if row['a'] > 0 and row['a']<=1.:
		return 1
	elif row['a']>1 and row['a']<=2.:
		return 2
	else:
		return 0

class DataManager:

	def __init__(self, yaml_filename, now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))):

		with open(yaml_filename, 'r') as ymlfile:
			cfg = yaml.load(ymlfile)

		self.zone = cfg["Data_Manager"]["Zone"]
		self.server = cfg["Data_Manager"]["Server"]
		self.entity = cfg["Data_Manager"]["Entity_File"]
		self.agent = cfg["Data_Manager"]["Agent_IP"]
		self.uuids = [cfg["Data_Manager"]["UUIDS"]["Thermostat_temperature"],
					  cfg["Data_Manager"]["UUIDS"]["Thermostat_state"],
					  cfg["Data_Manager"]["UUIDS"]["Temperature_Outside"]]
		self.wunderground_key =  cfg["Data_Manager"]["Wunderground_Key"]
		self.wunderground_place = cfg["Data_Manager"]["Wunderground_Place"]
		self.interval = cfg["Interval_Length"]
		self.now = now


	def preprocess_occ(self):

		if self.server:
			c = get_client(agent = self.agent, entity=self.entity)
		else:
			c = get_client()

		#this only works for ciee, check how it should be writen properly:
		hod = HodClient("ciee/hod", c)

		occ_query = """SELECT ?sensor ?uuid ?zone WHERE {
		  ?sensor rdf:type brick:Occupancy_Sensor .
		  ?sensor bf:isLocatedIn/bf:isPartOf ?zone .
		  ?sensor bf:uuid ?uuid .
		  ?zone rdf:type brick:HVAC_Zone
		};
		"""

		results = hod.do_query(occ_query)
		uuids = [[x['?zone'], x['?uuid']] for x in results['Rows']]

		query_list = []
		for i in uuids:
			if i[0] == self.zone:
				query_list.append(i[1])

		c = mdal.MDALClient("xbos/mdal")
		dfs = c.do_query({'Composition': query_list,
						  'Selectors': [mdal.MAX] * len(query_list),
						  'Time': {'T0': (self.now - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
								   'T1': self.now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
								   'WindowSize': str(self.interval) + 'min',
								   'Aligned': True}})

		dfs = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)

		df = dfs[[query_list[0]]]
		df.columns.values[0] = 'occ'
		df.is_copy = False
		df.columns = ['occ']
		for i in range(1, len(query_list)):
			df.loc[:, 'occ'] += dfs[query_list[i]]
		df.loc[:, 'occ'] = 1 * (df['occ'] > 0)

		return df.tz_localize(None)


	#problem with the time zone here, don't know why
	def preprocess_therm(self):

		if self.server:
			c = get_client(agent = self.agent, entity="thanos.ent")
		else:
			c = get_client()

		c = mdal.MDALClient("xbos/mdal", client=c)
		dfs = c.do_query({'Composition': self.uuids,
						  'Selectors': [mdal.MEAN, mdal.MAX, mdal.MEAN],
						  'Time': {'T0': '2017-07-21 00:00:00 UTC',
								   'T1': self.now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
								   'WindowSize': '1min',
								   'Aligned': True}})

		df = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)
		df = df.rename(columns={self.uuids[0]: 'tin', self.uuids[1]: 'a', self.uuids[2]:'t_out'})

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

		if not os.path.exists("weather.json"):
			weather = requests.get("http://api.wunderground.com/api/"+ self.wunderground_key+ "/hourly/q/pws:"+self.wunderground_place+".json")
			data = weather.json()
			with open('weather.json', 'w') as f:
				json.dump(data, f)

		myweather = json.load(open("weather.json"))
		if int(myweather['hourly_forecast'][0]["FCTTIME"]["hour"]) < \
			datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles")).hour:
			weather = requests.get("http://api.wunderground.com/api/" + self.wunderground_key + "/hourly/q/pws:" + self.wunderground_place + ".json")
			data = weather.json()
			with open('weather.json', 'w') as f:
				json.dump(data, f)
			myweather = json.load(open("weather.json"))

		weather_predictions = {}
		for data in myweather['hourly_forecast']:
			weather_predictions[int(data["FCTTIME"]["hour"])] = int(data["temp"]["english"])

		return weather_predictions

if __name__ == '__main__':
	dm = DataManager("config_south.yml")
	print dm.weather_fetch()
	print dm.preprocess_therm()
	print dm.preprocess_occ()
