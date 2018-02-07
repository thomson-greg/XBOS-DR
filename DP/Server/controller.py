import datetime, time, math, pytz, os, sys
import pandas as pd
import yaml
import msgpack

from Advise import Advise

from xbos import get_client
from xbos.services.hod import HodClientHTTP
from xbos.devices.thermostat import Thermostat
from xbos.services.pundat import DataClient, make_dataframe

# read from config file
try:
	yaml_filename = sys.argv[1]
except:
	sys.exit("Please specify the configuration file as: python2 controller.py config_file.yaml")

with open(yaml_filename, 'r') as ymlfile:
	cfg = yaml.load(ymlfile)

# query server to get the available zones
if  cfg['Server']:
	client = get_client(agent = '172.17.0.1:28589', entity="thanos.ent")
else:
	client = get_client()
hc = HodClientHTTP("http://ciee.cal-sdb.org")

q = """SELECT ?uri ?zone WHERE {
	?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
	?tstat bf:uri ?uri .
	?tstat bf:controls/bf:feeds ?zone .
};
"""

zones = {}
for tstat in hc.do_query(q):
	print tstat
	zones[tstat["?zone"]] = Thermostat(client, tstat["?uri"])

normal_zones = [cfg['zone']]


filename = "thermostat_changes.txt" # file in which the thermostat changes are recorded


def workday():
	p = {"override": True, "heating_setpoint": 70., "cooling_setpoint": 76., "mode": 3}
	print "workday",datetime.datetime.now()
	#for z in normal_zones:
		#print z,p
		#zones[z].write(p)

	for z in normal_zones:
		print z,p
		
		for i in range(10):
			try:
				zones[z].write(p)
				break
			except:
				if i == 9:
					e = sys.exc_info()[0]
					print e
				continue

def workday_inactive():
	p = {"override": True, "heating_setpoint": 62., "cooling_setpoint": 85., "mode": 3}
	print "workday inactive",datetime.datetime.now()
	for z in normal_zones:
		print z,p

		for i in range(10):
			try:
				zones[z].write(p)
				break
			except:
				if i == 9:
					e = sys.exc_info()[0]
					print e
				continue

# in case that the mpc doesnt work properly run this
def normal_schedule(SimpleDR=False):
	if SimpleDR==True:
		if  cfg['Server']:
			c = get_client(agent = '172.17.0.1:28589', entity="thanos.ent")
		else:
			c = get_client()
		msg = c.query("xbos/events/dr/s.dr/sdb/i.xbos.dr_signal/signal/signal")[0]
		for po in msg.payload_objects:
			if po.type_dotted == (2,9,9,9):
				data = msgpack.unpackb(po.content)
		print "DR EVENT", data




	weekno = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles")).weekday()

	if weekno<5:
		now = datetime.datetime.now(pytz.timezone("America/Los_Angeles"))
		now_time = now.time()

		if now_time >= datetime.time(18,0) or now_time < datetime.time(7,0):
			workday_inactive()
		else:
			#ind=(now_time.hour+8)%24
			ind=(now_time.hour)%24
			print data[ind]
			if SimpleDR==True and data[ind]['Price']>0.8:
				workday_inactive()
			else:
				workday()
	else:
		workday_inactive()

# the main controller
def hvac_control(): 
	try:

		# query the server to lean the current setpoints and the state of the thermostat
		if  cfg['Server']:
			c = get_client(agent = '172.17.0.1:28589', entity="thanos.ent")
		else:
			c = get_client()
		archiver = DataClient(c)

		uuids = [cfg['UUIDS']['thermostat_high'], cfg['UUIDS']['thermostat_low'], cfg['UUIDS']['thermostat_mode']]

		temp_now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))

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

	# document the "before" state
	try:
		f = open(filename, 'a')
		f.write("Did read: " + str(df['t_low'][-1]) + ", " + str(df['t_high'][-1]) + ", " + str(df['mode'][-1]) + "\n")
		f.close()
	except:
		print "Could not document changes."

	# choose the apropriate setpoints according to weekday and time
	weekno = temp_now.weekday()

	if weekno<5:
		now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))
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
		adv = Advise(cfg)
		action, temp = adv.advise()
		temp = float(temp)
	except:
		e = sys.exc_info()[0]
		print e
		return False

	# action "0" is Do Nothing, action "1" is Cooling, action "2" is Heating
	if action == "0":
		p = {"override": True, "heating_setpoint": math.floor(temp-0.1)-1, "cooling_setpoint": math.ceil(temp+0.1)+1, "mode": 3}
		print "Doing nothing"
		print p

		# document changes
		try:
			f = open(filename, 'a')
			f.write("Did write: " + str(math.floor(temp-0.1)-1) + ", " + str(math.ceil(temp+0.1)+1) + ", " + str(3) +"\n")
			f.close()
		except:
			print "Could not document changes."
			
	elif action == "1":
		p = {"override": True, "heating_setpoint": heating_setpoint, "cooling_setpoint": math.floor(temp-0.1), "mode": 3}
		print "Heating"
		print p

		# document changes
		try:
			f = open(filename, 'a')
			f.write("Did write: " + str(heating_setpoint) + ", " + str(math.floor(temp-0.1)) + ", " + str(3) + "\n")
			f.close()
		except:
			print "Could not document changes."
		
	elif action == "2":
		p = {"override": True, "heating_setpoint": math.ceil(temp+0.1), "cooling_setpoint": cooling_setpoint, "mode": 3}
		print "Cooling"
		print p

		# document changes
		try:
			f = open(filename, 'a')
			f.write("Did write: " + str(math.ceil(temp+0.1)) + ", " + str(cooling_setpoint) + ", " + str(3) + "\n")
			f.close()
		except:
			print "Could not document changes."
	else:
		print "Problem with action."
		return False

	# try to commit the changes to the thermostat, if it doesnt work 10 times in a row ignore and try again later
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

	SimpleDR = cfg['SimpleDR']

	if not os.path.exists(filename):
		f = open(filename   , 'w')
		f.close()

	starttime=time.time()
	while True:

		if not SimpleDR:
			if not hvac_control():
				print("Problem with MPC, entering normal schedule.")
				normal_schedule()
		else:
			normal_schedule(SimpleDR)

		print datetime.datetime.now()
		time.sleep(60.*15. - ((time.time() - starttime) % (60.*15.)))
