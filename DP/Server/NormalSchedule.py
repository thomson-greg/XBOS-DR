import datetime
import pytz
import sys

from DataManager import DataManager


# TODO DR EVENT needs fixing

class NormalSchedule:
    def __init__(self, cfg, t_stat, advise_cfg, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))):
        self.cfg = cfg
        self.advise_cfg = advise_cfg
        self.now = now.astimezone(tz=pytz.timezone(cfg["Pytz_Timezone"]))
        self.tstat = t_stat
        self.zone = advise_cfg["Zone"]


    # in case that the mpc doesnt work properly run this
    def normal_schedule(self):

        def in_between(now, start, end):
            if start < end:
                return start <= now < end
            elif end < start:
                return start <= now or now < end
            else:
                return True

        setpoints_array = self.advise_cfg["Advise"]["Baseline"][self.now.weekday()]

        for j in setpoints_array:
            if in_between(self.now.time(), datetime.time(int(j[0].split(":")[0]), int(j[0].split(":")[1])),
                          datetime.time(int(j[1].split(":")[0]), int(j[1].split(":")[1]))):
                SetpointLow = j[2]
                SetpointHigh = j[3]
                break

        dataManager = DataManager(self.cfg, self.advise_cfg, None, now=self.now, zone=self.zone)
        Safety_temps = dataManager.safety_constraints()

        if not isinstance(SetpointLow, (int, float, long)):
            SetpointLow = Safety_temps[0][0]
        if not isinstance(SetpointHigh, (int, float, long)):
            SetpointHigh = Safety_temps[0][1]

        if self.cfg["Pricing"][
            "DR"] or self.now.weekday() == 4:  # TODO REMOVE ALLWAYS HAVING DR ON FRIDAY WHEN DR SUBSCRIBE IS IMPLEMENTED
            SetpointHigh += self.advise_cfg["Advise"]["Baseline_Dr_Extend_Percent"] / 100. * SetpointHigh
            SetpointLow -= self.advise_cfg["Advise"]["Baseline_Dr_Extend_Percent"] / 100. * SetpointLow


        if SetpointLow < Safety_temps[0][0]:
            SetpointLow = Safety_temps[0][0]
            SetpointHigh = SetpointLow + self.advise_cfg["Advise"]["Minimum_Comfortband_Height"]
        elif SetpointHigh > Safety_temps[0][1]:
            SetpointHigh = Safety_temps[0][1]
            SetpointLow = SetpointHigh - self.advise_cfg["Advise"]["Minimum_Comfortband_Height"]

        p = {"override": True, "heating_setpoint": SetpointLow, "cooling_setpoint": SetpointHigh, "mode": 3}

        for i in range(self.advise_cfg["Advise"]["Thermostat_Write_Tries"]):
            try:
                # TODO Uncomment later
                self.tstat.write(p)
                print("For zone: %s writing Baseline: %s" % (self.zone, str(p)))
                break
            except:
                if i == self.advise_cfg["Advise"]["Thermostat_Write_Tries"] - 1:
                    e = sys.exc_info()[0]
                    print e
                    return
                continue


if __name__ == '__main__':

    import yaml

    with open("config_file.yml", 'r') as ymlfile:
        cfg = yaml.load(ymlfile)

    from xbos import get_client
    from xbos.services.hod import HodClient

    if cfg["Server"]:
        client = get_client(agent=cfg["Agent_IP"], entity=cfg["Entity_File"])
    else:
        client = get_client()

    hc = HodClient(cfg["Building"] + "/hod", client)

    q = """SELECT ?uri ?zone WHERE {
		?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
		?tstat bf:uri ?uri .
		?tstat bf:controls/bf:feeds ?zone .
	};
	"""

    from xbos.devices.thermostat import Thermostat

    threads = []
    for tstat in hc.do_query(q)['Rows']:
        print tstat
        with open("Buildings/" + cfg["Building"] + "/ZoneConfigs/" + tstat["?zone"] + ".yml", 'r') as ymlfile:
            advise_cfg = yaml.load(ymlfile)
        NS = NormalSchedule(cfg, Thermostat(client, tstat["?uri"]), advise_cfg)
        NS.normal_schedule()
