import datetime, pytz, sys
import yaml
import msgpack

from xbos import get_client
from xbos.services.hod import HodClientHTTP
from xbos.devices.thermostat import Thermostat

# TODO DR EVENT needs fixing

class NormalSchedule:

	def __init__(self, cfg, t_stat, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))):

		self.simpleDr = cfg["SimpleDR"]
		self.server = cfg["Server"]
		self.entity = cfg["Entity_File"]
		self.agent = cfg["Agent_IP"]
		self.tries = cfg["Thermostat_Write_Tries"]
		self.now = now.astimezone(tz=pytz.timezone(cfg["Pytz_Timezone"]))

		# query server to get the available zones
		if self.server:
			client = get_client(agent=self.agent, entity=self.entity)
		else:
			client = get_client()
		hc = HodClientHTTP("http://ciee.cal-sdb.org")

		q = """SELECT ?uri ?zone WHERE {
			?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
			?tstat bf:uri ?uri .
			?tstat bf:controls/bf:feeds ?zone .
		};
		"""

		self.tstat = t_stat


	def workday(self):
		p = {"override": True, "heating_setpoint": 70., "cooling_setpoint": 76., "mode": 3}
		print "workday", datetime.datetime.now()

		print p

		for i in range(self.tries):
			try:
				self.tstat.write(p)
				break
			except:
				if i == self.tries-1:
					e = sys.exc_info()[0]
					print e
				continue


	def workday_inactive(self):
		p = {"override": True, "heating_setpoint": 62., "cooling_setpoint": 85., "mode": 3}
		print "workday inactive", datetime.datetime.now()

		print p

		for i in range(self.tries):
			try:
				self.tstat.write(p)
				break
			except:
				if i == self.tries-1:
					e = sys.exc_info()[0]
					print e
				continue


	# in case that the mpc doesnt work properly run this
	def normal_schedule(self):

		if self.simpleDr == True:
			if self.server:
				c = get_client(agent=self.agent, entity=self.entity)
			else:
				c = get_client()
			msg = c.query("xbos/events/dr/s.dr/sdb/i.xbos.dr_signal/signal/signal")[0]
			for po in msg.payload_objects:
				if po.type_dotted == (2, 9, 9, 9):
					data = msgpack.unpackb(po.content)
			print "DR EVENT"

		weekno = self.now.weekday()

		if weekno < 5:

			now_time = self.now.time()
			if now_time >= datetime.time(18, 0) or now_time < datetime.time(7, 0):
				self.workday_inactive()
			else:
				# ind=(now_time.hour+8)%24
				ind = (now_time.hour) % 24
				#print data[ind]
				if self.simpleDr == True and data[ind]['Price'] > 0.8:
					self.workday_inactive()
				else:
					self.workday()
		else:
			self.workday_inactive()


# if __name__ == '__main__':
#
# 	with open("config_south.yml", 'r') as ymlfile:
# 		cfg = yaml.load(ymlfile)
#
# 	if cfg["Data_Manager"]["Server"]:
# 		client = get_client(agent=cfg["Data_Manager"]["Agent_IP"], entity=cfg["Data_Manager"]["Entity_File"])
# 	else:
# 		client = get_client()
# 	hc = HodClientHTTP("http://ciee.cal-sdb.org")
#
# 	q = """SELECT ?uri ?zone WHERE {
# 		?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
# 		?tstat bf:uri ?uri .
# 		?tstat bf:controls/bf:feeds ?zone .
# 	};
# 	"""
#
# 	tstats = {}
# 	for tstat in hc.do_query(q):
# 		print tstat
# 		tstats[tstat["?zone"]] = Thermostat(client, tstat["?uri"])
#
# 	normal_zones = [cfg["Data_Manager"]["Zone"]]
#
# 	ns = NormalSchedule(cfg, tstats, normal_zones)
# 	ns.normal_schedule()
