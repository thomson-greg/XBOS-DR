import datetime, time, math, pytz, os, sys
import pandas as pd

from Advise import Advise

from xbos import get_client
from xbos.services.hod import HodClientHTTP
from xbos.devices.thermostat import Thermostat
from xbos.services.pundat import DataClient, make_dataframe

client = get_client(agent = '172.17.0.1:28589', entity="thanos.ent")
#client = get_client()
hc = HodClientHTTP("http://ciee.cal-sdb.org")

q = """SELECT ?uri ?zone WHERE {
	?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
	?tstat bf:uri ?uri .
	?tstat bf:controls/bf:feeds ?zone .
};
"""

filename = "thermostat_changes.txt"

zones = {}
for tstat in hc.do_query(q):
	print tstat
	zones[tstat["?zone"]] = Thermostat(client, tstat["?uri"])

normal_zones = ["EastZone"]

def workday():
	p = {"override": True, "heating_setpoint": 70., "cooling_setpoint": 76.}
	print "workday",datetime.datetime.now()
	for z in normal_zones:
		print z,p
		zones[z].write(p)
def workday_inactive():
	p = {"override": True, "heating_setpoint": 62., "cooling_setpoint": 85.}
	print "workday inactive",datetime.datetime.now()
	for z in normal_zones:
		print z,p
		zones[z].write(p)

def normal_schedule():

	weekno = datetime.datetime.today().replace(tzinfo=pytz.timezone("America/Los_Angeles")).weekday()

	if weekno<5:
		now = datetime.datetime.now(pytz.timezone("America/Los_Angeles"))
		now_time = now.time()

		if now_time >= datetime.time(18,0) or now_time < datetime.time(7,0):
			workday_inactive()
		else:
			workday()
	else:
		workday_inactive()

def hvac_control(): 
	try:

		c = get_client(agent = '172.17.0.1:28589', entity="thanos.ent")
		#c = get_client()
		archiver = DataClient(c)

		east_high = "d38446d4-32cc-34bd-b293-0a3871a6759b"
		east_low = "e4d39723-5907-35bd-a9b2-fc57b58b3779"
		east_mode = "3bc7ce21-2384-3ebe-aedd-8c2822b5a10c"

		uuids = [east_high, east_low, east_mode]

		temp_now = datetime.datetime.now(pytz.timezone("America/Los_Angeles"))

		start = '"' + temp_now.strftime('%Y-%m-%d %H:%M:%S') + ' PST"'
		end = '"' + (temp_now - datetime.timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S') + ' PST"'
		

		dfs = make_dataframe(archiver.window_uuids(uuids, end, start, '1min', timeout=120))

		for uid, df in dfs.items():
			
			if uid == uuids[0]:
				if 'mean' in df.columns:
					df = df[['mean']]
				df.columns = ['t_high']
			elif uid == uuids[1]:
				if 'mean' in df.columns:
					df = df[['mean']]
				df.columns = ['t_low']
			elif uid == uuids[2]:
				if 'mean' in df.columns:
					df = df[['mean']]
				df.columns = ['mode']
			dfs[uid] = df.resample('1min').mean()
				
		df = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)
	except:
		e = sys.exc_info()[0]
		print e
		return False

	try:
		f = open(filename, 'a')
		f.write("Did read: " + str(df['t_low'][-1]) + ", " + str(df['t_high'][-1]) + ", " + str(df['mode'][-1]) + "\n")
		f.close()
	except:
		print "Could not document changes."

	weekno = temp_now.weekday()

	if weekno<5:
		now = datetime.datetime.now(pytz.timezone("America/Los_Angeles"))
		now_time = now.time()

		if now_time >= datetime.time(18,0) or now_time < datetime.time(7,0):
			heating_setpoint = 62.
			cooling_setpoint = 85.
		else:
			heating_setpoint = 70.
			cooling_setpoint = 76.
	else:
		heating_setpoint = 62.
		cooling_setpoint = 85.

	try:
		adv = Advise()
		action, temp = adv.advise()
		temp = float(temp)
	except:
		e = sys.exc_info()[0]
		print e
		return False

	if action == "0":
		p = {"override": True, "heating_setpoint": math.floor(temp-0.1), "cooling_setpoint": math.ceil(temp+0.1), "mode": 3}
		print p
		try:
			f = open(filename, 'a')
			f.write("Did write: " + str(math.floor(temp-0.1)) + ", " + str(math.ceil(temp+0.1)) + ", " + str(3) +"\n")
			f.close()
		except:
			print "Could not document changes."
			
	elif action == "1":
		p = {"override": True, "heating_setpoint": heating_setpoint, "cooling_setpoint": math.floor(temp-0.1), "mode": 3}
		print p
		try:
			f = open(filename, 'a')
			f.write("Did write: " + str(heating_setpoint) + ", " + str(math.floor(temp-0.1)) + ", " + str(3) + "\n")
			f.close()
		except:
			print "Could not document changes."
		
	elif action == "2":
		p = {"override": True, "heating_setpoint": math.ceil(temp+0.1), "cooling_setpoint": cooling_setpoint, "mode": 3}
		print p
		try:
			f = open(filename, 'a')
			f.write("Did write: " + str(math.ceil(temp+0.1)) + ", " + str(cooling_setpoint) + ", " + str(3) + "\n")
			f.close()
		except:
			print "Could not document changes."
	else:
		print "Problem with action."
		return False

	for z in normal_zones:
			for i in range(10):
				try:
					zones[z].write(p)
					break
				except:
					if i == 9:
						e = sys.exc_info()[0]
						print e
						return False
					continue
	return True

if __name__ == '__main__':
	if not os.path.exists(filename):
		f = open(filename   , 'w')
		f.close()
		
	starttime=time.time()
	while True:
		if not hvac_control():
			print("Problem with MPC, entering normal schedule.")
			normal_schedule()
		time.sleep(60.*15. - ((time.time() - starttime) % (60.*15.)))