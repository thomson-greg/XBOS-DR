import datetime, pytz
import pandas as pd
from scipy.optimize import curve_fit
from datetime import timedelta
from xbos import get_client
from xbos.services.pundat import DataClient, make_dataframe
from sklearn.utils import shuffle

# WE ARE NOT LEARNING VENTILATION RIGHT NOW
# $T^{IN}_{t+1}= c_1 * a^{H} * T^{IN}_{t} + c_2 * a^{C} * T^{IN}_{t} + c_3 * T^{IN}_{t}$
def func(X, c1, c2, c3):#, c4):
	Tin, a1, a2 = X
	return c1 * a1 * Tin + c2 * a2 * Tin + c3 * Tin #+ c4  * (1-a1)*(1-a2)

class ThermalModel:

	def __init__(self, cfg, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))):

		self.current_time = now
		self.df = self.preprocess_thermal(cfg)
		self.popt, pcov = curve_fit(func, self.df[['tin', 'a1' , 'a2']].T.as_matrix(), self.df['temp_next'].as_matrix())

	# function that returns the t_next according to t_now and action
	def next_temperature(self, Tin, action, zone=0):
		if action == 'Heating' or action == '2':
			return round(func([Tin, 1, 0], *self.popt) * 400) / 400.0
		elif action == 'Cooling' or action == '1':
			return round(func([Tin, 0, 1], *self.popt) * 400) / 400.0
		else:
			return round(func([Tin, 0, 0], *self.popt) * 400) / 400.0

	# function that makes all the necessary preprocess to the data that are fitted into the model
	def preprocess_thermal(self, cfg):

		# if state is 1 we are doing heating
		def f1(row):
			if row['a'] > 0 and row['a']<=1:
				val = 1
			else:
				val = 0
			return val

		# if state is 2 we are doing cooling
		def f2(row):
			if row['a']>1 and row['a']<=2:
				val = 1
			else:
				val = 0
			return val

		final_df = pd.DataFrame()
		flag = True
		heating_count = 0
		cooling_count = 0
		do_nothing_count = 0
		max_action_count = 50
		month_count = 0
		while flag:

			# query the server for the thermostat state and temperature

			if  cfg['Server']:
				c = get_client(agent = '172.17.0.1:28589', entity="thanos.ent")
			else:
				c = get_client()
			archiver = DataClient(c)

			uuids = [cfg['UUIDS']['thermostat_temperature'], cfg['UUIDS']['thermostat_state']]

			temp_now = self.current_time

			start = '"' + (temp_now + timedelta(minutes=15) - timedelta(days = (month_count)*30)).strftime('%Y-%m-%d %H:%M:%S') + ' PST"'
			end = '"' + (temp_now - timedelta(days = (month_count+1)*30)).strftime('%Y-%m-%d %H:%M:%S') + ' PST"'

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
			
			for idx in reversed(df.index):
				if df.at[idx, 'a1'] == 1 and heating_count <= max_action_count:
					if df.at[idx, 'tin'] <= df.at[idx, 'temp_next']:
						final_df = final_df.append(df[df.index==idx])
						heating_count += 1
				elif df.at[idx, 'a2'] == 1 and cooling_count<max_action_count:
					if df.at[idx, 'tin'] >= df.at[idx, 'temp_next']:
						final_df = final_df.append(df[df.index==idx])
						cooling_count += 1
				elif df.at[idx, 'a1'] == 0 and df.at[idx, 'a2'] == 0 and do_nothing_count<max_action_count:
					final_df = final_df.append(df[df.index==idx])
					do_nothing_count += 1
				if heating_count>=max_action_count and cooling_count>=max_action_count\
				 and do_nothing_count>=max_action_count:
					flag = False
					break
			month_count+=1
		
		return shuffle(final_df)
