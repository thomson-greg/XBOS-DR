import datetime, pytz
import pandas as pd
from datetime import timedelta
from scipy.optimize import curve_fit
from sklearn.utils import shuffle

# TODO learn ventilation?
# TODO find better padding function?

# WE ARE NOT LEARNING VENTILATION RIGHT NOW
def func(X, c1, c2, c3):
	"""
	This is the thermal model method
	"""
	Tin, a1, a2, Tout, dt = X
	return Tin + (c1 * a1 * Tin + c2 * a2 * Tin + c3 * (Tout - Tin)) * dt

# This is the Thermal Model class
class ThermalModel:

	def __init__(self, df, weather_predictions, max_actions = 400, thermal_precision=400., interval_length= 15,
				 now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))):
		"""
		Thermal Model Constructor
		"""
		# data initialization, all constants will be read from yaml configuration file
		self.current_time = now
		self.weather_predictions = weather_predictions
		self.max_actions = max_actions # maximum number of samples per action for the curve fit
		self.thermal_precision = thermal_precision
		self.interval_length = interval_length
		self.popt = self.fit(self.sample_thermal_data(df)) # optimization constants

	def sample_thermal_data(self, df):
		"""
		Method that chooses the best samples for the thermal model.
		"""
		max_actions = self.max_actions

		df['temp_index'] = df.index
		df = df.sort_values(['dt', 'temp_index'], ascending=[True, True], na_position='first')
		final_df = pd.DataFrame()
		final_df = final_df.append(df[df['a1'] == 1][-max_actions:])
		final_df = final_df.append(df[df['a2'] == 1][-max_actions:])
		final_df = final_df.append(df[(df['a1'] == 0) & (df['a2'] == 0)][-max_actions:])
		return shuffle(final_df)

	def fit(self, df):
		"""
		Method that fits the data and returns the optimized parameters
		"""
		df = df.dropna()
		popt, pcov = curve_fit(func,
							   df[['tin', 'a1', 'a2', 'tout', 'dt']].T.as_matrix(),
							   df['t_next'].as_matrix())
		return popt

	def next_temperature(self, Tin, action, time, zone=0):
		"""
		# Method that returns the predicted temperature of the building after interval_length minutes
		"""
		if action == 'Heating' or action == '1':
			return round(func([Tin, 1, 0, self.weather_predictions[(self.current_time + timedelta(self.interval_length*time)).hour],
							   self.interval_length],
							  *self.popt) * self.thermal_precision) / self.thermal_precision
		elif action == 'Cooling' or action == '2':
			return round(func([Tin, 0, 1, self.weather_predictions[(self.current_time + timedelta(self.interval_length*time)).hour],
							   self.interval_length],
							  *self.popt) * self.thermal_precision) / self.thermal_precision
		else:
			return round(func([Tin, 0, 0, self.weather_predictions[(self.current_time + timedelta(self.interval_length*time)).hour],
							   self.interval_length],
							  *self.popt) * self.thermal_precision) / self.thermal_precision


if __name__ == '__main__':
	import yaml
	import sys

	sys.path.insert(0, '..')
	from DataManager import DataManager
	from xbos import get_client

	with open("../config_file.yml", 'r') as ymlfile:
		cfg = yaml.load(ymlfile)

	with open("../Buildings/ciee/ZoneConfigs/CentralZone.yml", 'r') as ymlfile:
		advise_cfg = yaml.load(ymlfile)

	if cfg["Server"]:
		c = get_client(agent=cfg["Agent_IP"], entity=cfg["Entity_File"])
	else:
		c = get_client()

	dm = DataManager(cfg, advise_cfg, c)
	tm = ThermalModel(dm.preprocess_therm(), dm.weather_fetch())
	print tm.next_temperature(70, '1', 0)
