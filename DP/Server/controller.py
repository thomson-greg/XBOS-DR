import datetime
import math
import sys
import threading
import time

import pytz
import yaml

from DataManager import DataManager
from NormalSchedule import NormalSchedule

sys.path.insert(0, 'MPC')
from Advise import Advise
from ThermalModel import *


from xbos import get_client
from xbos.services.hod import HodClient
from xbos.devices.thermostat import Thermostat


# the main controller
def hvac_control(cfg, advise_cfg, tstats, client, thermal_model, zone):
    now = datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))
    try:
        tstat = tstats[zone]
        dataManager = DataManager(cfg, advise_cfg, client, zone, now=now)
        tstat_temperature = tstat.temperature
        safety_constraints = dataManager.safety_constraints()
        # need to set weather predictions for every loop and set current zone temperatures and fit the model given the new data (if possible).
        # NOTE: call setZoneTemperaturesAndFit before setWeahterPredictions
        thermal_model.setZoneTemperaturesAndFit({dict_zone: dict_tstat.temperature for dict_zone, dict_tstat in tstats.items()}, dt=15)
        thermal_model.setWeahterPredictions(dataManager.weather_fetch())
        adv = Advise([zone],  # array because we might use more than one zone. Multiclass approach.
                     now.astimezone(tz=pytz.timezone(cfg["Pytz_Timezone"])),
                     dataManager.preprocess_occ(),
                     [tstat_temperature],
                     thermal_model,
                     dataManager.prices(),
                     advise_cfg["Advise"]["General_Lambda"],
                     advise_cfg["Advise"]["DR_Lambda"],
                     advise_cfg["Advise"]["Interval_Length"],
                     advise_cfg["Advise"]["MPCPredictiveHorizon"],
                     advise_cfg["Advise"]["Print_Graph"],
                     advise_cfg["Advise"]["Heating_Consumption"],
                     advise_cfg["Advise"]["Cooling_Consumption"],
                     advise_cfg["Advise"]["Ventilation_Consumption"],
                     advise_cfg["Advise"]["Thermal_Precision"],
                     advise_cfg["Advise"]["Occupancy_Obs_Len_Addition"],
                     dataManager.building_setpoints(),
                     advise_cfg["Advise"]["Occupancy_Sensors"],
                     safety_constraints)

        action = adv.advise()
        thermal_model.setLastActionAndTime(action, now.astimezone(tz=pytz.timezone(cfg["Pytz_Timezone"]))) # TODO Fix, absolute hack and not good. controller should store this.


    except Exception as exception:
        # TODO Find a better way for exceptions
        e = sys.exc_info()
        print exception
        return False

    # action "0" is Do Nothing, action "1" is Heating, action "2" is Cooling
    if action == "0":
        heating_setpoint = tstat_temperature - advise_cfg["Advise"]["Minimum_Comfortband_Height"] / 2.
        cooling_setpoint = tstat_temperature + advise_cfg["Advise"]["Minimum_Comfortband_Height"] / 2.
        if heating_setpoint < safety_constraints[0][0]:
            heating_setpoint = safety_constraints[0][0]

            if (cooling_setpoint - heating_setpoint) < advise_cfg["Advise"]["Minimum_Comfortband_Height"]:
                cooling_setpoint = min(safety_constraints[0][1], heating_setpoint + advise_cfg["Advise"]["Minimum_Comfortband_Height"])

        elif cooling_setpoint > safety_constraints[0][1]:
            cooling_setpoint = safety_constraints[0][1]

            if (cooling_setpoint - heating_setpoint) < advise_cfg["Advise"]["Minimum_Comfortband_Height"]:
                heating_setpoint = max(safety_constraints[0][0],
                                       cooling_setpoint - advise_cfg["Advise"]["Minimum_Comfortband_Height"])

        p = {"override": True, "heating_setpoint": heating_setpoint, "cooling_setpoint": cooling_setpoint, "mode": 3}
        print "Doing nothing"

    # TODO Rethink how we set setpoints for heating and cooling
    elif action == "1":
        heating_setpoint = tstat_temperature + 2*advise_cfg["Advise"]["Hysterisis"]
        cooling_setpoint = heating_setpoint + advise_cfg["Advise"]["Minimum_Comfortband_Height"]


        if cooling_setpoint > safety_constraints[0][1]:
            cooling_setpoint = safety_constraints[0][1]

            #making sure we are in the comfortband
            if (cooling_setpoint - heating_setpoint) < advise_cfg["Advise"]["Minimum_Comfortband_Height"]:
                heating_setpoint = max(safety_constraints[0][0],
                                       cooling_setpoint - advise_cfg["Advise"]["Minimum_Comfortband_Height"])


        p = {"override": True, "heating_setpoint": heating_setpoint, "cooling_setpoint": cooling_setpoint, "mode": 3}
        print "Heating"

    elif action == "2":
        cooling_setpoint = tstat_temperature - 2*advise_cfg["Advise"]["Hysterisis"]
        heating_setpoint = cooling_setpoint - advise_cfg["Advise"]["Minimum_Comfortband_Height"]


        if heating_setpoint < safety_constraints[0][0]:
            heating_setpoint = safety_constraints[0][0]

            #making sure we are in the comfortband
            if (cooling_setpoint - heating_setpoint) < advise_cfg["Advise"]["Minimum_Comfortband_Height"]:
                cooling_setpoint = min(safety_constraints[0][1], heating_setpoint + advise_cfg["Advise"]["Minimum_Comfortband_Height"])

        p = {"override": True, "heating_setpoint": heating_setpoint, "cooling_setpoint": cooling_setpoint, "mode": 3}
        print "Cooling"
    else:
        print "Problem with action."
        return False

    print("Zone: " + zone + ", action: " + str(p))

    # try to commit the changes to the thermostat, if it doesnt work 10 times in a row ignore and try again later

    for i in range(advise_cfg["Advise"]["Thermostat_Write_Tries"]):
        try:
            # TODO uncomment for actual MPC
            tstat.write(p)
            break
        except:
            if i == advise_cfg["Advise"]["Thermostat_Write_Tries"] - 1:
                e = sys.exc_info()[0]
                print e
                return False
            continue

    return True


class ZoneThread(threading.Thread):
    def __init__(self, cfg_filename, tstats, zone, client, thermal_model):
        threading.Thread.__init__(self)
        self.cfg_filename = cfg_filename
        self.tstats = tstats
        self.zone = zone
        self.client = client

        self.thermal_model = thermal_model

    def run(self):

        starttime = time.time()
        while True:
            try:
                with open(self.cfg_filename, 'r') as ymlfile:
                    cfg = yaml.load(ymlfile)
                with open("Buildings/" + cfg["Building"] + "/ZoneConfigs/" + self.zone + ".yml", 'r') as ymlfile:
                    advise_cfg = yaml.load(ymlfile)
            except:
                print "There is no " + self.zone + ".yml file under ZoneConfigs folder."
                return  # TODO MAKE THIS RUN NORMAL SCHEDULE SOMEHOW WHEN NO ZONE CONFIG EXISTS

            if advise_cfg["Advise"]["MPC"]:
                count = 0
                while not hvac_control(cfg, advise_cfg, self.tstats, self.client, self.thermal_model, self.zone):
                    time.sleep(10)
                    count += 1
                    if count == advise_cfg["Advise"]["Thermostat_Write_Tries"]:
                        print("Problem with MPC, entering normal schedule.")
                        normal_schedule = NormalSchedule(cfg, tstat, advise_cfg)
                        normal_schedule.normal_schedule()
                        break
            else:
                normal_schedule = NormalSchedule(cfg, self.tstats[zone], advise_cfg)
                normal_schedule.normal_schedule()
            print datetime.datetime.now()
            time.sleep(60. * float(advise_cfg["Advise"]["Interval_Length"]) - (
            (time.time() - starttime) % (60. * float(advise_cfg["Advise"]["Interval_Length"]))))


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

    # TODO Uncomment when final
    # controller_dataManager = ControllerDataManager(cfg, client)
    # # initialize and fit thermal model
    # thermal_data = controller_dataManager.thermal_data()

    import pickle

    with open("Thermal Data/ciee_thermal_data_demo", "r") as f:
        thermal_data = pickle.load(f)

    # TODO INTERVAL SHOULD NOT BE IN config_file.yml, THERE SHOULD BE A DIFFERENT INTERVAL FOR EACH ZONE
    # TODO Add thermal precision from config.
    thermal_model = MPCThermalModel(thermal_data, interval_length=cfg["Interval_Length"], thermal_precision=cfg["Thermal_Precision"])
    # with open("Thermal Data/thermal_model_demo", 'r') as f:
    #     thermal_model = pickle.load(f)
    # -------------------


    with open(yaml_filename, 'r') as ymlfile:
        cfg = yaml.load(ymlfile)

    hc = HodClient("xbos/hod", client)

    q = """SELECT ?uri ?zone FROM %s WHERE {
        ?tstat rdf:type/rdfs:subClassOf* brick:Thermostat .
        ?tstat bf:uri ?uri .
        ?tstat bf:controls/bf:feeds ?zone .
        };""" % cfg["Building"]

    threads = []
    tstat_query_data = hc.do_query(q)['Rows']
    tstats = {tstat["?zone"]: Thermostat(client, tstat["?uri"]) for tstat in tstat_query_data}
    for zone, tstat in tstats.items():
        print tstat
        thread = ZoneThread(yaml_filename, tstats, zone, client, thermal_model)
        thread.start()
        threads.append(thread)

    for t in threads:
        t.join()
