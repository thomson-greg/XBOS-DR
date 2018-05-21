import datetime
import math
import pytz
import sys
import threading
import time

import yaml
from DataManager import DataManager
from ControllerDataManager import ControllerDataManager
from NormalSchedule import NormalSchedule



sys.path.insert(0, 'MPC')
from Advise import Advise
from xbos import get_client
from xbos.services.hod import HodClient
from xbos.devices.thermostat import Thermostat

from ThermalModel import MPCThermalModel


# TODO only one zone at a time, making multizone comes soon

# the main controller
def hvac_control(cfg, advise_cfg, tstat, client, thermal_model, zone):
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))
    try:
        dataManager = DataManager(cfg, advise_cfg, client, now=now)

        tstat_temp = tstat.temperature

        setpoints_array = dataManager.building_setpoints()
        adv = Advise(now.astimezone(tz=pytz.timezone(cfg["Pytz_Timezone"])),
                     dataManager.preprocess_occ(),
                     [tstat_temp], # assuming we are only working with one zone. should be change if we do multizone.
                     thermal_model,
                     dataManager.weather_fetch(),
                     dataManager.prices(),
                     advise_cfg["Advise"]["Lambda"],
                     cfg["Interval_Length"],
                     advise_cfg["Advise"]["Hours"],
                     advise_cfg["Advise"]["Print_Graph"],
                     advise_cfg["Advise"]["Heating_Consumption"],
                     advise_cfg["Advise"]["Cooling_Consumption"],
                     advise_cfg["Advise"]["Occupancy_Obs_Len_Addition"],
                     setpoints_array)
        action = adv.advise()

    except:
        e = sys.exc_info()[0]
        print
        e
        return False

    heating_setpoint = setpoints_array[0][0]
    cooling_setpoint = setpoints_array[0][1]
    # action "0" is Do Nothing, action "1" is Cooling, action "2" is Heating
    if action == "0":
        p = {"override": True, "heating_setpoint": math.floor(temp - 0.1) - 1,
             "cooling_setpoint": math.ceil(temp + 0.1) + 1, "mode": 3}
        print
        "Doing nothing"
        print
        p

    elif action == "1":
        p = {"override": True, "heating_setpoint": heating_setpoint, "cooling_setpoint": math.floor(temp - 0.1) - 1,
             "mode": 3}
        print
        "Heating"
        print
        p

    elif action == "2":
        p = {"override": True, "heating_setpoint": math.ceil(temp + 0.1) + 1, "cooling_setpoint": cooling_setpoint,
             "mode": 3}
        print
        "Cooling"
        print


    else:
        print
        "Problem with action."
        return False

    # try to commit the changes to the thermostat, if it doesnt work 10 times in a row ignore and try again later

    for i in range(cfg["Thermostat_Write_Tries"]):
        try:
            tstat.write(p)
            break
        except:
            if i == cfg["Thermostat_Write_Tries"] - 1:
                e = sys.exc_info()[0]
                print
                e
                return False
            continue

    return True


class ZoneThread(threading.Thread):
    def __init__(self, cfg, tstats, zone, client, thermal_model):
        threading.Thread.__init__(self)
        self.cfg = cfg
        self.tstats = tstats
        self.zone = zone
        self.client = client

        self.thermal_model = thermal_model

    def run(self):

        try:
            with open('ZoneConfigs/' + self.zone + '.yml', 'r') as ymlfile:
                advise_cfg = yaml.load(ymlfile)
        except:
            print
            "There is no " + self.zone + ".yml file under ZoneConfigs folder."
            return

        count = 0
        while not hvac_control(self.cfg, advise_cfg, self.tstats, self.client, self.thermal_model, self.zone) and count < self.cfg[
            "Thermostat_Write_Tries"]:
            time.sleep(10)
            count += 1
            if count == self.cfg["Thermostat_Write_Tries"]:
                print("Problem with MPC, entering normal schedule.")
                normal_schedule = NormalSchedule(cfg, tstat)
                normal_schedule.normal_schedule()
                break


if __name__ == '__main__':

    # read from config file
    try:
        yaml_filename = sys.argv[1]
    except:
        sys.exit("Please specify the configuration file as: python2 controller.py config_file.yaml")

    with open(yaml_filename, 'r') as ymlfile:
        cfg = yaml.load(ymlfile)

    if cfg["Server"]:
        client = get_client(agent=cfg["Agent_IP"], entity=cfg["Entity_File"])
    else:
        client = get_client()

    starttime = time.time()

    controller_dataManager = ControllerDataManager(cfg, client)
    # initialize and fit thermal model
    thermal_data = controller_dataManager.thermal_data()

    thermal_model = MPCThermalModel(thermal_data, interval_length=cfg["Interval_Length"])
    # -------------------


    while True:

        with open(yaml_filename, 'r') as ymlfile:
            cfg = yaml.load(ymlfile)

        hc = HodClient(cfg["Hod_Client"], client)

        q = """SELECT ?uri ?zone WHERE {
			?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
			?tstat bf:uri ?uri .
			?tstat bf:controls/bf:feeds ?zone .
		};
		"""

        threads = []
        tstats = {}
        for tstat in hc.do_query(q)['Rows']:
            tstats[tstat["?zone"]] = Thermostat(client, tstat["?uri"])

        # assuming we get here every 15 min.
        thermal_model.set_zone_temperatures({zone: t.temperature for zone, t in tstats.items()})

        for zone, tstat in tstats.items():
            print
            tstat
            thread = ZoneThread(cfg, tstats, zone, client, thermal_model)
            thread.start()
            threads.append(thread)

        for t in threads:
            t.join()

        print
        datetime.datetime.now()
        time.sleep(60. * 15. - ((time.time() - starttime) % (60. * 15.)))
