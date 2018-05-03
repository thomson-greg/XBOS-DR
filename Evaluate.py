import datetime
import numpy as np
import pandas as pd
from scipy.optimize import curve_fit
from sklearn.utils import shuffle
import matplotlib.pyplot as plt
import random

# daniel imports
from sklearn.base import BaseEstimator, RegressorMixin

from sklearn.metrics import mean_squared_error
from math import sqrt
from sklearn.model_selection import cross_val_score


class Evaluate:


	def __init__(self, day=5, month=2, year=2018, days_of_data = 30, prediction_hours=8):

		# starting time 
		self.starting_time_now = datetime.datetime(year=year, month=month, day=day, hour=0, minute=0, second=0, microsecond=0)
		
		# thermal_data is a pandas dataframe that contains:
		# time index
		# 'a1' is the heating action
		# 'a2' is the cooling action
		# 'tin' temperature at the start of the action
		# 't_next' temperature at the end of the action
		# 'tout' outside temperature (weather)
		# 'dt' how long did the action last
		# thermal_predictions is a pandas dataframe that contains:
		# time index
		# 'temp' themperature prediction for time indexed
		self.thermal_data, self.thermal_predictions = self.thermal_read()
		# days of data to go back to, keep it 30 cause data are limited
		self.days_of_data = days_of_data
		self.prediction_hours = prediction_hours


		# self.prediction, self.groundTruth_tin, self.rmse, self.mean, self.std = self.evaluate()


	################ Probably won't need to change these: ###################################
	# take the #max_actions first actions, sorted by 'dt' and 'datetime'
	def thermal_training(self, temp):
		max_actions = 200
		temp['temp_index'] = temp.index
		# TODO WHY WOULD WE SORT IN THIS ORDER (dt, temp_index)? WILL SORT BY DT FIRST
		temp = temp.sort_values(['temp_index', 'dt'], ascending=[True,True], na_position='first')
		final_df = pd.DataFrame()
		final_df = final_df.append(temp[temp['a1']==1][-max_actions:])
		final_df = final_df.append(temp[temp['a2']==1][-max_actions:])
		final_df = final_df.append(temp[(temp['a1']==0) & (temp['a2']==0)][-max_actions:])
		return shuffle(final_df)

	# thermal model function
	def func(self, X, c1, c2, c3, c4):
		Tin, a1, a2, Tout, dt = X
		return Tin + ( c1 * a1 *Tin + c2 * a2 *Tin + c3* (Tout - Tin) + c4) * dt

	# # thermal model function
	# def func(self, X, c1, c2, c3):
	# 	Tin, a1, a2, Tout, dt = X
	# 	return Tin + ( c1 * a1 * Tin + c2 * a2 * Tin + c3 * (Tout - Tin)) *dt

	# helper function, no need to change this
	def f1(self,row):
		"""For heating."""
		if row['action']==1.:
			val = 1
		else:
			val = 0
		return val

	def f2(self,row):
		"""For cooling."""
		if row['action']==2.:
			val = 1
		else:
			val = 0
		return val

	#read datasets and create pandas datagrames
	def thermal_read(self):
		thermal_data = pd.read_csv('thermal_data.csv', index_col=0, sep=';')
		thermal_data.index = pd.to_datetime(thermal_data.index)

		# ------------- CLEAN THE DATA -------------
		thermal_data = self.cleanData(thermal_data)
		# ------------- CLEAN THE DATA -------------

		# self.plotData(thermal_data)
		starting_time_now = self.starting_time_now

		thermal_data = thermal_data[thermal_data.index<=starting_time_now]
		thermal_data['a1'] = thermal_data.apply(self.f1,axis=1)
		thermal_data['a2'] = thermal_data.apply(self.f2,axis=1)
		
		thermal_predictions = pd.read_csv('weather_forecasts.csv', index_col=0, sep=';')
		thermal_predictions.index = pd.to_datetime(thermal_predictions.index, unit = 's')
		thermal_predictions = thermal_predictions.tz_localize('UTC').tz_convert('US/Pacific').tz_localize(None)

		return thermal_data, thermal_predictions

	#########################################################################################################

	# You will need to change these:

	# Starts with a given sequence of known temperatures and actions
	# Repeat these actions using our thermal model, to evaluate 
	def predict_th(self, popt, data, t_predictions):
		next_temp = data['tin'][0]
		return_list = [next_temp]
		for i in data[1:].index:
			
			next_temp = self.func([next_temp, \
								data.truncate(after=i).iloc[-1]['a1'],\
								data.truncate(after=i).iloc[-1]['a2'], \
								t_predictions.truncate(after=i).iloc[-1]['temp'], \
								data.truncate(after=i).iloc[-1]['dt']], *popt)
			return_list.append(next_temp)
		return return_list

	
	# this function starts from the latter day in the dataframe and uses predict_th going back in time each time 1-2 hours
	def evaluate(self):
		df = self.thermal_data.copy(deep=True)

		prediction_list = []
		ground_truth_list = []

		temp_now = df.index[-1]
		
		while temp_now > df.index[-1] - datetime.timedelta(days=self.days_of_data):

			temp = df[df.index <= temp_now]

			final_df = self.thermal_training(temp.copy(deep=True)) #these are the training data
			final_df = final_df.dropna(axis=0, how = 'any')

			popt, pcov = curve_fit(self.func, final_df[['tin', 'a1' , 'a2', 'tout', 'dt']].T.as_matrix(), final_df['t_next'].as_matrix()) # fit the data
			p = self.predict_th(popt, temp[-4*self.prediction_hours-1:], self.thermal_predictions) # use the thermal model to predict the temperatures for the next 8 hours
			prediction_list.append(p) # this is the list with all the predictions
			ground_truth_list.append(temp[-4*self.prediction_hours-1:]['tin'].tolist()) # this is the list with the ground truth
			temp_now = temp_now - datetime.timedelta(hours=random.randint(1,2))
			

		prediction = [i for i in prediction_list]
		groundTruth_tin = [i for i in ground_truth_list]

		rmse = np.sqrt(np.mean(np.square(np.subtract(prediction,groundTruth_tin)),axis=0))

		return prediction, groundTruth_tin, rmse, np.mean(np.subtract(prediction,groundTruth_tin),axis=0)[1], np.std(np.subtract(prediction,groundTruth_tin),axis=0)[1]

	# simple plot function
	def plot(self):
		sticks = []
		disc= 4
		for i in range(0, 4*self.prediction_hours+1, disc):
			if int(round(i/4))<10:
				hours = "0"+str(int(round(i/4)))
			else:
				hours = str(int(round(i/4)))
			if int(round(i%4))<10:
				minutes = "0"+str(int(round(i%4)))
			else:
				minutes = str(int(round(i%4)))
			sticks.append(hours+":"+minutes)

		print "Mean of first action: " + str(self.mean)
		print "Standard Deviation of first action: " + str(self.std)

		pos = np.arange(4*self.prediction_hours+1)
		ind = np.arange(0,4*self.prediction_hours+1)
		fig, ax = plt.subplots()
		ax.plot(ind,self.rmse,'-',label="ConfRoom")
		ax.set_xticks(pos[::disc])
		ax.set_xticklabels(sticks)
		ax.set_xlim(0, 4*self.prediction_hours)
		plt.xlabel('Predictive horizon (Hours)')
		plt.ylabel(r'RMSE (F)')
		plt.legend()
		plt.show()


	def cross_rmse_actions(self, action=-1):
		"""Evaluates the thermal model through cross validation. 
		_params:
			action: (int) The action by which to pre-filter training data and for which to find RMSE. -1 indicates no filter, 0 no action,
						1 heating, 2 cooling.
		returns:
			(int) RMSE for each fold of cross validation
		"""
		print("start cross validation with action = " + str(action))
		thermal = ThermalFit(scoreType=-1) #change score type here.
		if action == 0:
			X = self.thermal_data[(self.thermal_data['a1']==0) & (self.thermal_data['a2']==0)]
		elif action == 1:
			X = self.thermal_data[self.thermal_data['a1']==1]
		elif action == 2:
			X = self.thermal_data[self.thermal_data['a2']==1]
		else:
			X = self.thermal_data
		print("training data shape: " + str(X.shape))
		X = shuffle(X) # to get an even spread of all actions. 
		X.sort_index(inplace=True)
		# print(X.head())
		y = X['t_next']
		print(cross_val_score(thermal, X, y))
		print(ThermalFit.trivial_rmse)
		print("diff in trival and normal rmse: " + str(np.mean(ThermalFit.rmse) - np.mean(ThermalFit.trivial_rmse)))


	def cleanData(self, df, outputToCSV=False):
		# df.sort_index(inplace=True)
		prev = df.shape[0]

		# Clean data where there is a cooling or heating action and no change in temperature
		toRemove = df.loc[df['action']!=0]
		toRemove = toRemove.loc[(toRemove['tin'] == toRemove['t_next'])]
		df = df.drop(toRemove.index)

		# Clean data where there is heating action and start temp > end temp
		toRemove = df.loc[df['action']==1]
		toRemove = toRemove.loc[(toRemove['tin'] > toRemove['t_next'])]
		df = df.drop(toRemove.index)

		# Clean data where there is cooling action and start temp < end temp
		toRemove = df.loc[df['action']==2]
		toRemove = toRemove.loc[(toRemove['tin'] < toRemove['t_next'])]
		df = df.drop(toRemove.index)

		curr = df.shape[0]

		print("\n" + "Removed " + str(prev - curr) + " rows of bad data" + "\n")

		if (outputToCSV):
			df.to_csv('cleanData.csv')
		
		# print(df.index.name)
		# print(df.columns.values)

		return df

	# def plotData(self, df):
	# 	newDF = df.copy()
	# 	newDF = self.cleanData(newDF)
	# 	newDF = newDF.loc[df['action']==2]
	# 	newDF = newDF.drop(columns = ['dt', 'action', 'tout'])
	# 	newDF.plot()
	# 	plt.show()

	


class ThermalFit(BaseEstimator, RegressorMixin):
	# keeping track of all the rmse's computed with this model
	trivial_rmse = []
	rmse = []
	scoreTypeList = [] # to know which action each rmse belongs to.


	def __init__(self, scoreType=-1):
		'''
		_params:
			scoreType: (int) which actions to filter by when scoring. -1 indicates no filter, 0 no action,
						1 heating, 2 cooling.
		'''
		self.scoreType = scoreType

		self._params = None



		# thermal model function
	def _func(self, X, c1, c2, c3):
		Tin, a1, a2, Tout, dt = X
		return Tin + ( c1 * a1 *Tin + c2 * a2 *Tin + c3 * (Tout - Tin)) * dt	


	def fit(self, X, y=None):
		X = X.dropna(axis=0, how = 'any')

		popt, pcov = curve_fit(self._func, X[['tin', 'a1' , 'a2', 'tout', 'dt']].T.as_matrix(), y.as_matrix()) # fit the data
		self._params = popt
		print("Done Fitting")
		return self

	def predict(self, X, y=None):
		# only predicts next temperatures
		try:
			getattr(self, "_params")
		except AttributeError:
			raise RuntimeError("You must train classifer before predicting data!")

		res = [self._func([X.loc[date]['tin'], \
								X.loc[date]['a1'],\
								X.loc[date]['a2'], \
								X.loc[date]['tout'], \
								X.loc[date]['dt']], *self._params) 
				for date in X.index]
			
		return res


	def _normalizedRMSE(self, dt, prediction, y):
		'''Computes the RMSE with scaled differences to normalize to 15 min intervals.'''
		diff = prediction - y
		print("num less 15 minutes " + str((dt < 15).shape))
		diff_scaled = diff * 15. / dt # to offset for actions which were less than 15 min. makes everything a lot worse
		rmse = np.sqrt(np.mean(np.square(diff_scaled)))
		return rmse

	def score(self, X, y, sample_weight=None):
		ThermalFit.scoreTypeList.append(self.scoreType)

		if self.scoreType == 0:
			filter_arr = (X['a1']==0) & (X['a2']==0)
		elif self.scoreType == 1:
			filter_arr = X['a1']==1
		elif self.scoreType == 2:
			filter_arr = X['a2']==1
		else:
			filter_arr = np.ones(X['a1'].shape) == 1 

		X = X[filter_arr]
		y = y[filter_arr]

		print("score data shape: " + str(X.shape))
		
		prediction = self.predict(X) # only need to predict for relevant actions

		rmse = self._normalizedRMSE(X['dt'], prediction, y)

		# add normal RMSE for reference. 
		ThermalFit.rmse.append(rmse)

		# add trivial error for reference. 
		trivial_rmse = self._normalizedRMSE(X['dt'], X['tin'], y)
		ThermalFit.trivial_rmse.append(trivial_rmse)

		print("Done Scoring")
		return rmse


if __name__ == "__main__":

	print("Instantiate evalue")
	evaluator = Evaluate()
	print("start rmse cross")
	evaluator.cross_rmse_actions()
	# evaluator.plot()
