import datetime, pytz
import pandas as pd
from datetime import timedelta
from scipy.optimize import curve_fit
from sklearn.utils import shuffle

# WE ARE NOT LEARNING VENTILATION RIGHT NOW
def func(X, c1, c2, c3):
	Tin, a1, a2, Tout, dt = X
	return Tin + (c1 * a1 * Tin + c2 * a2 * Tin + c3 * (Tout - Tin)) * dt

class ThermalModel:

	def __init__(self, df, weather_predictions, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))):

		self.current_time = now
		self.weather_predictions = weather_predictions
		self.max_actions = 400
		self.thermal_precision = 400.
		self.interval_length = 15
		self.popt = self.fit(self.sample_thermal_data(df))

	def sample_thermal_data(self, df):
		max_actions = self.max_actions

		df['temp_index'] = df.index
		df = df.sort_values(['dt', 'temp_index'], ascending=[True, True], na_position='first')
		final_df = pd.DataFrame()
		final_df = final_df.append(df[df['a1'] == 1][-max_actions:])
		final_df = final_df.append(df[df['a2'] == 1][-max_actions:])
		final_df = final_df.append(df[(df['a1'] == 0) & (df['a2'] == 0)][-max_actions:])
		return shuffle(final_df)

	def fit(self, df):
		df = df.dropna()
		popt, pcov = curve_fit(func,
							   df[['tin', 'a1', 'a2', 'tout', 'dt']].T.as_matrix(),
							   df['t_next'].as_matrix())
		return popt
	# function that returns the t_next according to t_now and action
	def next_temperature(self, Tin, action, time, zone=0):
		if action == 'Heating' or action == '2':
			return round(func([Tin, 1, 0, self.weather_predictions[(self.current_time + timedelta(self.interval_length*time)).hour],
							   self.interval_length],
							  *self.popt) * self.thermal_precision) / self.thermal_precision
		elif action == 'Cooling' or action == '1':
			return round(func([Tin, 0, 1, self.weather_predictions[(self.current_time + timedelta(self.interval_length*time)).hour],
							   self.interval_length],
							  *self.popt) * self.thermal_precision) / self.thermal_precision
		else:
			return round(func([Tin, 0, 0, self.weather_predictions[(self.current_time + timedelta(self.interval_length*time)).hour],
							   self.interval_length],
							  *self.popt) * self.thermal_precision) / self.thermal_precision


if __name__ == '__main__':
	from DataManager import DataManager
	dm = DataManager()
	tm = ThermalModel(dm.preprocess_therm(), dm.weather_fetch())
	print tm.next_temperature(70, '2', 0)
