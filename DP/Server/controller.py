import datetime, time, math, pytz, os, sys
import pandas as pd
import yaml
from NormalSchedule import NormalSchedule
from DataManager import DataManager
from Advise import Advise

from xbos import get_client
from xbos.services.hod import HodClientHTTP
from xbos.services.hod import HodClient
from xbos.devices.thermostat import Thermostat

# TODO only one zone at a time, making multizone comes soon

filename = "thermostat_changes.txt"  # file in which the thermostat changes are recorded

# the main controller
def hvac_control(cfg, tstats, normal_zones):

	now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))

	dataManager = DataManager(cfg, now=now)

	t_high, t_low, t_mode = dataManager.thermostat_setpoints()
	# document the "before" state
	try:
		f = open(filename, 'a')
		f.write("Did read: " + str(t_low) + ", " + str(t_high) + ", " + str(t_mode) + "\n")
		f.close()
	except:
		print "Could not document changes."


	# choose the apropriate setpoints according to weekday and time
	try:
		now_time = now.astimezone(tz=pytz.timezone(cfg["Data_Manager"]["Pytz_Timezone"])).time()
		for setpoint in cfg["Advise"]["Setpoint"]:
			if now_time >= datetime.time(int(setpoint[0].split(":")[0]), int(setpoint[0].split(":")[1])) and \
				now_time < datetime.time(int(setpoint[1].split(":")[0]), int(setpoint[1].split(":")[1])):
				heating_setpoint = setpoint[2]
				cooling_setpoint = setpoint[3]
				break
	except:
		"Problem with setting the setpoints."
		return False

	try:
		Prep_Therm = dataManager.preprocess_therm()
		adv = Advise(now.astimezone(tz=pytz.timezone(cfg["Data_Manager"]["Pytz_Timezone"])),
					 dataManager.preprocess_occ(),
					 Prep_Therm,
					 dataManager.weather_fetch(),
					 cfg["Energy_rates"],
					 cfg["Advise"]["Lambda"],
					 cfg["Interval_Length"],
					 cfg["Advise"]["Hours"],
					 cfg["Advise"]["Print_Graph"],
					 cfg["Advise"]["Maximum_Safety_Temp"],
					 cfg["Advise"]["Minimum_Safety_Temp"],
					 cfg["Advise"]["Heating_Consumption"],
					 cfg["Advise"]["Cooling_Consumption"],
					 cfg["Advise"]["Max_Actions"],
					 cfg["Advise"]["Thermal_Precision"],
					 cfg["Advise"]["Occupancy_Obs_Len_Addition"],
					 cfg["Advise"]["Setpoint"])
		action = adv.advise()
		temp = float(Prep_Therm['t_next'][-1])
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
			for i in range(cfg["Thermostat_Write_Tries"]):
				try:
					tstats[z].write(p)
					break
				except:
					if i == 9:
						e = sys.exc_info()[0]
						print e
						return False
					continue
	return True

if __name__ == '__main__':

	# read from config file
	try:
		yaml_filename = sys.argv[1]
	except:
		sys.exit("Please specify the configuration file as: python2 controller.py config_file.yaml")

	with open(yaml_filename, 'r') as ymlfile:
		cfg = yaml.load(ymlfile)

	if not os.path.exists(filename):
		f = open(filename   , 'w')
		f.close()

	if cfg["Data_Manager"]["Server"]:
		client = get_client(agent=cfg["Data_Manager"]["Agent_IP"], entity=cfg["Data_Manager"]["Entity_File"])
	else:
		client = get_client()
	hc = HodClient(cfg["Data_Manager"]["Hod_Client"], client)

	q = """SELECT ?uri ?zone WHERE {
		?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
		?tstat bf:uri ?uri .
		?tstat bf:controls/bf:feeds ?zone .
	};
	"""

	tstats = {}
	for tstat in hc.do_query(q)['Rows']:
		print tstat
		tstats[tstat["?zone"]] = Thermostat(client, tstat["?uri"])

	normal_zones = [cfg["Data_Manager"]["Zone"]]

	starttime=time.time()
	while True:

		with open(yaml_filename, 'r') as ymlfile:
			cfg = yaml.load(ymlfile)

		if not hvac_control(cfg, tstats, normal_zones):
			print("Problem with MPC, entering normal schedule.")
			normal_schedule = NormalSchedule(cfg, tstats, normal_zones)
			normal_schedule.normal_schedule()

		print datetime.datetime.now()
		time.sleep(60.*15. - ((time.time() - starttime) % (60.*15.)))
