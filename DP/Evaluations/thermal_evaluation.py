from xbos import get_client
from xbos.services.pundat import DataClient, make_dataframe
# from xbos.services.hod import HodClient

import datetime, pytz
import numpy as np
import pandas as pd

# from matplotlib.pyplot import step, xlim, ylim, show
import matplotlib.pyplot as plt
from datetime import timedelta
from random import randint
from scipy.optimize import curve_fit
from sklearn.utils import shuffle

def f1(row):
	if row['a'] > 0 and row['a']<=1:
		val = 1
	else:
		val = 0
	return val

def f2(row):
	if row['a']>1 and row['a']<=2:
		val = 1
	else:
		val = 0
	return val


def preprocess(temp_now):
	c = get_client()
	archiver = DataClient(c)

	
	north_temp = "c7e33fa6-f683-36e9-b97a-7f096e4b57d4"
	north_state = "5e55e5b1-007b-39fa-98b6-ae01baa6dccd"
	south_temp = "03099008-5224-3b61-b07e-eee445e64620"
	south_state = "dfb2b403-fd08-3e9b-bf3f-18c699ce40d6"
	central_temp = "c05385e5-a947-37a3-902e-f6ea45a43fe8"
	central_state = "187ed9b8-ee9b-3042-875e-088a08da37ae"
	east_temp = "b47ba370-bceb-39cf-9552-d1225d910039"
	east_state = "7e543d07-16d1-32bb-94af-95a01f4675f9"

	uuid_list = [[south_temp,south_state], [east_temp,east_state], [central_temp,central_state], [north_temp,north_state]]

	per_zone_temp_list = []
	for uuids in uuid_list:

		start = '"' + temp_now.strftime('%Y-%m-%d %H:%M:%S') + ' PST"'
		#end = '"' + (temp_now - timedelta(days=7)).strftime('%Y-%m-%d %H:%M:%S') + ' PST"'
		end = '"2017-7-20 00:00:00 PST"'

		dfs = make_dataframe(archiver.window_uuids(uuids, end, start, '15min', timeout=120))

		for uid, df in dfs.items():
					
			if uid == uuids[0]:
				if 'mean' in df.columns:
					df = df[['mean']]
				df.columns = ['tin']
			elif uid == uuids[1]:
				if 'max' in df.columns:
					df = df[['max']]
				df.columns = ['a']
				
			dfs[uid] = df.resample('15min').mean()

		df = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)
		df['a1'] = df.apply(f1, axis=1)
		df['a2'] = df.apply(f2, axis=1)
		df['tin']=df['tin'].replace(to_replace=0, method='pad')
		df['temp_next'] = df['tin'].shift(-1)
		df=df.dropna()
		
		# WE ARE NOT LEARNING VENTILATION RIGHT NOW
		
		df = df.tz_localize('UTC').tz_convert(pytz.timezone("America/Los_Angeles"))
		per_zone_temp_list.append(df[['tin', 'a1' , 'a2','temp_next']])
	return per_zone_temp_list

# $T^{IN}_{t+1}= c_1 * a^{H} * T^{IN}_{t} + c_2 * a^{C} * T^{IN}_{t} + c_3 * T^{IN}_{t}$
def func(X, c1, c2, c3):#, c4):
			Tin, a1, a2 = X
			return c1 * a1 * Tin + c2 * a2 * Tin + c3 * Tin #+ c4  * (1-a1)*(1-a2)

def predict(popt, data):
	next_temp = data['tin'][0]
	return_list = [next_temp]
	for i in data[1:].index:
		next_temp = func([next_temp, data[data.index==i]['a1'][0], data[data.index==i]['a2'][0]], *popt)
		return_list.append(next_temp)
	return return_list

zones = ['SouthZone', 'EastZone', 'CentralZone', 'NorthZone']
days_of_data = 30
prediction_hours = 8

temp_now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))
dfs = preprocess(temp_now)


sticks = []
disc= 4
for i in range(0, 4*prediction_hours+1, disc):
	if int(round(i/4))<10:
		hours = "0"+str(int(round(i/4)))
	else:
		hours = str(int(round(i/4)))
	if int(round(i%4))<10:
		minutes = "0"+str(int(round(i%4)))
	else:
		minutes = str(int(round(i%4)))
	sticks.append(hours+":"+minutes)

pos = np.arange(4*prediction_hours+1)
ind = np.arange(0,4*prediction_hours+1)
fig, ax = plt.subplots()

count = 0
max_action_count = 50
for df in dfs:
	print "Preparing next zone..."
	temp_now = df.index[-1]	

	prediction_list = []
	ground_truth_list = []
	

	while temp_now > df.index[-1] - timedelta(days=days_of_data):
		temp = df.ix[:temp_now]
		final_df = pd.DataFrame()
		flag = True
		heating_count = 0
		cooling_count = 0
		do_nothing_count = 0
		for idx in reversed(temp.index):
			if temp.at[idx, 'a1'] == 1 and heating_count <= max_action_count:
				if temp.at[idx, 'tin'] <= temp.at[idx, 'temp_next']:
					final_df = final_df.append(temp[temp.index==idx])
					heating_count += 1
			elif temp.at[idx, 'a2'] == 1 and cooling_count<max_action_count:
				if temp.at[idx, 'tin'] >= temp.at[idx, 'temp_next']:
					final_df = final_df.append(temp[temp.index==idx])
					cooling_count += 1
			elif temp.at[idx, 'a1'] == 0 and temp.at[idx, 'a2'] == 0 and do_nothing_count<max_action_count:
				final_df = final_df.append(temp[temp.index==idx])
				do_nothing_count += 1
			if heating_count>=max_action_count and cooling_count>=max_action_count\
			 and do_nothing_count>=max_action_count:
				flag = False
				break
		popt, pcov = curve_fit(func, final_df[['tin', 'a1' , 'a2']].T.as_matrix(), final_df['temp_next'].as_matrix())
		prediction_list.append(predict(popt, temp[-4*prediction_hours-1:]))
		
		ground_truth_list.append(temp[-4*prediction_hours-1:]['tin'].tolist())
		temp_now = temp_now - timedelta(hours=randint(1,2))
		

	prediction = [i for i in prediction_list]

	groundTruth_tin = [i for i in ground_truth_list]

	rmse = np.sqrt(np.mean(np.square(np.subtract(prediction,groundTruth_tin)),axis=0))

	ax.plot(ind,rmse,'-',label=zones[count])
	count += 1 


ax.set_xticks(pos[::disc])
ax.set_xticklabels(sticks)
ax.set_xlim(0, 4*prediction_hours)
#ax.legend(loc=4, ncol=3, numpoints=1, fancybox=False, framealpha=0.7)
plt.xlabel('Predictive horizon (Hours)')
plt.ylabel(r'RMSE (F)')
plt.legend()
plt.show()


#na apothikeuode ta diafora rmse gia na borw na dhmiourghsw th grafikh apo arxeio
