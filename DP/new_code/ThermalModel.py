import datetime, pytz
import pandas as pd
from datetime import timedelta
from scipy.optimize import curve_fit
from sklearn.utils import shuffle

# WE ARE NOT LEARNING VENTILATION RIGHT NOW
# This is the thermal model function
def func(X, c1, c2, c3):
	Tin, a1, a2, Tout, dt = X
	return Tin + (c1 * a1 * Tin + c2 * a2 * Tin + c3 * (Tout - Tin)) * dt

# This is the Thermal Model class
class ThermalModel:

	#Thermal Model Constructor
	#Inputs : df - PandasDataframe, weather_predictions - Dictionary
	def __init__(self, df, weather_predictions, max_actions = 400, thermal_precision=400., interval_length= 15,
				 now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))):
		# data initialization, all constants will be read from yaml configuration file
		self.current_time = now
		self.weather_predictions = weather_predictions
		self.max_actions = max_actions # maximum number of samples per action for the curve fit
		self.thermal_precision = thermal_precision
		self.interval_length = interval_length
		self.popt = self.fit(self.sample_thermal_data(df)) # optimization constants

	# Method that chooses the best samples for the thermal model.
	# Input/Output is a Pandas Dataframe.
	def sample_thermal_data(self, df):
		max_actions = self.max_actions

		df['temp_index'] = df.index
		df = df.sort_values(['dt', 'temp_index'], ascending=[True, True], na_position='first')
		final_df = pd.DataFrame()
		final_df = final_df.append(df[df['a1'] == 1][-max_actions:])
		final_df = final_df.append(df[df['a2'] == 1][-max_actions:])
		final_df = final_df.append(df[(df['a1'] == 0) & (df['a2'] == 0)][-max_actions:])
		return shuffle(final_df)

	# Method that fits the data and returns the optimized parameters
	def fit(self, df):
		df = df.dropna()
		popt, pcov = curve_fit(func,
							   df[['tin', 'a1', 'a2', 'tout', 'dt']].T.as_matrix(),
							   df['t_next'].as_matrix())
		return popt

	# Function that returns the predicted temperature of the building after interval_length minutes
	#
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
