import pandas as pd
from datetime import timedelta
import numpy as np
import math

def mins_in_day(timestamp):
	return timestamp.hour * 60 + timestamp.minute

def hamming_distance(a, b):
	return np.count_nonzero(a != b)

# calculate and return the k most similar dates with today
def find_similar_days(training_data, now, observation_length, k, method=hamming_distance):
	min_time = training_data.index[0] + timedelta(minutes=observation_length)
	# Find moments in our dataset that have the same hour/minute and is_weekend() == weekend.

	selector = ((training_data.index.minute == now.minute) &
				(training_data.index.hour == now.hour) &
				(training_data.index > min_time))

	similar_moments = training_data[selector][:-1]
	obs_td = timedelta(minutes=observation_length)

	similar_moments['Similarity'] = [
		method(
			training_data[(training_data.index >= now - obs_td) &
							(training_data.index <= now)].get_values(),
			training_data[(training_data.index >= i - obs_td) &
							(training_data.index <= i)].get_values()
		) for i in similar_moments.index
		]

	indexes = (similar_moments.sort_values('Similarity', ascending=True).head(k).index)
	return indexes

# predict the expected occupancy prediction_time ahead
def predict(data, now, similar_moments, prediction_time, resample_time):

	prediction = np.zeros((int(math.ceil(prediction_time/resample_time)) + 1, len(data.columns)))
	for i in similar_moments:
		prediction += float(1.0 / float(len(similar_moments))) * data[(data.index >= i) & (data.index <= i + timedelta(minutes=prediction_time))]

	prediction[0] = data[data.index == now]
	time_index = pd.date_range(now, now+timedelta(minutes=prediction_time),freq='15T')
	return pd.DataFrame(data=prediction, index=time_index)



class Occupancy:
	def __init__(self, df):

		observation_length_addition = 4*60
		k = 5
		prediction_time = 4*60
		resample_time = 15
		now = df.index[-1]
		
		observation_length = mins_in_day(now) + observation_length_addition
		similar_moments = find_similar_days(df, now, observation_length, k)
		self.predictions = predict(df, now, similar_moments, prediction_time, resample_time)
		
	def occ(self, now_time):
		return self.predictions[0][now_time]

if __name__ == '__main__':
	from DataManager import DataManager
	dm = DataManager()
	occ = Occupancy(dm.preprocess_occ())
	print occ.occ(0)
