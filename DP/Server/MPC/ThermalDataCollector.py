
# coding: utf-8

# In[3]:


import pandas as pd 
import numpy as np
import pickle
import datetime
import time
from collections import defaultdict

from xbos import get_client
from xbos.services import mdal
from xbos.services.hod import HodClient
from xbos.devices.thermostat import Thermostat


# In[4]:

class ThermalDataCollector:

    def __init__(self, client, building):

        thermostat_query = """SELECT ?zone ?uri FROM %s WHERE { 
                  ?tstat rdf:type brick:Thermostat .
                  ?tstat bf:hasLocation/bf:isPartOf ?location_zone .
                  ?location_zone rdf:type brick:HVAC_Zone .
                  ?tstat bf:controls ?RTU .
                  ?RTU rdf:type brick:RTU . 
                  ?RTU bf:feeds ?zone. 
                  ?zone rdf:type brick:HVAC_Zone . 
                  ?tstat bf:uri ?uri.
                };"""

        self.client = get_client()
        self.building = building

        hod_client = HodClient("xbos/hod", self.client)

        thermostat_query_data = hod_client.do_query(thermostat_query % self.building)["Rows"]

        self.tstats = {tstat["?zone"]: Thermostat(client, tstat["?uri"]) for tstat in thermostat_query_data}

        self.COOLING_ACTION = lambda tstat: {"heating_setpoint": 50, "cooling_setpoint": 65, "override": True,
                                             "mode": 3}
        self.HEATING_ACTION = lambda tstat: {"heating_setpoint": 80, "cooling_setpoint": 95, "override": True,
                                             "mode": 3}
        self.NO_ACTION = lambda tstat: {"heating_setpoint": tstat.temperature - 5,
                                        "cooling_setpoint": tstat.temperature + 5,
                                        "override": True, "mode": 3}

    def gatherZoneData(self, tstat):
        data = {  "heating_setpoint": tstat.heating_setpoint,
                  "cooling_setpoint": tstat.cooling_setpoint,
                  "state": tstat.state,
                  "temperature": tstat.temperature}
        return data

    def loopAction(self, tstats, action_messages, interval, dt, flag_function=lambda :True, stop_time = datetime.datetime(year=2018, month=5, day=28, hour=14, minute=30)):
        """
        :param tstats: {zone: tstat object}
        :param action_messages: {zone: action dictionary}
        :param interval: how long to execute action in minutes
        :param dt: how often to record data and rewrite message in minutes
        :param flag_function: a function with no parameters that can also halt the while loop. 
                        For now we use functions which determine whether we have reached setpoint temperatures
        :param stop_time: Time at which to stop everything. In UTC. Usually when work begins. 
        returns: {zone: pd.df columns:["heating_setpoint",
                  "cooling_setpoint",
                  "state",
                  "temperature", "dt"] index=time right after all actions were written to thermostats (freq=dt)},
                  (array) (expected cooling_setpoint, recorded cooling_setpoint,
                   expected heating_setpoint, recorded heating set_point, time, zone) records if someone was interfering with the setpoints."""
        start_time = time.time()
        recorded_data = defaultdict(list)
        recorded_setpoint_changes = []
        while time.time() - start_time < 60*interval and flag_function() and (datetime.datetime.utcnow() < stop_time):
            try:
                # potential improvement is to make the times more accurate
                run_time = time.time()
                for zone, action in action_messages.items():
                    tstats[zone].write(action(tstats[zone]))
                    if tstat.heating_setpoint != action["heating_setpoint"] or tstat.cooling_setpoint != action["cooling_setpoint"]:
                        recorded_setpoint_changes.append((action["cooling_setpoint"], tstat.cooling_setpoint,
                                                          action["heating_setpoint"], tstat.heating_setpoint,
                                                          datetime.datetime.utcnow(), zone))

                # using dt as we assume it will be, (i.e. runtime less than dt). We can infer later if it differs.
                time_data = {"time": datetime.datetime.utcnow(), "dt": dt}
                for zone, tstat in tstats.items():
                    row = self.gatherZoneData(tstat)
                    row.update(time_data)
                    recorded_data[zone].append(row)
            except:
                print("Error writing to Thermostat at time", datetime.datetime.utcnow())

            # usually iteration of loop takes less than 0.1 seconds.
            if dt*60 - (time.time() - run_time) < 0:
                print("Warning: An iteration of the loop took too long. At utc_time: ", time_data["time"])
            time.sleep(max(dt*60 - (time.time() - run_time), 0))

        dataframe_data = {}
        for zone, data in recorded_data.items():
            data = pd.DataFrame(data).set_index('time')
            dataframe_data[zone] = data
        return dataframe_data, recorded_setpoint_changes


    def control(self, tstats, interval=30, dt=1):
        zone_order = tstats.keys() # establishes order in which to perform actions.

        action_order = {"0":self.NO_ACTION, "1": self.HEATING_ACTION, "2": self.COOLING_ACTION} # in dictionary so we can shuffle easier if wanted.

        # control one zone. All others do nothing.
        final_data = {}
        for action_zone in zone_order:
            zone_data = defaultdict(list)
            for i in range(3):
                # don't do anything for no action.
                if i == 0:
                    continue

                print("Started action %s in zone %s at time %s" % (str(i), action_zone, datetime.datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S')))
                # re setting since I want to store data all the time. Just to make sure we aren't loosing anything.
                zone_data = defaultdict(list)

                action = action_order[str(i)]

                # set action for each zone
                action_messages = {}
                for zone in zone_order:
                    if zone == action_zone:
                        action_messages[zone] = action
                    else:
                        action_messages[zone] = action_order[str(0)] # no action
                # using the zone_tsat for flag_function. Basically, we are heating or cooling, only stop when we have reached the setpoint.
                zone_tstat = tstats[action_zone]

                # TODO Note, override the interval for now. Could put this in function parameters
                # lambda function SHOULD BE A COSTUM FUNCTION FROM OUTSIDE OF THIS FUNCTION.
                interval = 90 if i != 0 else 15
                zone_action_msg = action_messages[action_zone]
                action_data, recorded_setpoint_changes = self.loopAction(tstats, action_messages, interval, dt, lambda : (not ((zone_action_msg(zone_tstat)["heating_setpoint"] + 2) < zone_tstat.temperature < (zone_action_msg(zone_tstat)["cooling_setpoint"] - 2))) or (i ==0))

                for zone, df in action_data.items():
                    if zone == action_zone:
                        df["action"] = np.ones(df.shape[0]) * i
                    else:
                        df["action"] = np.ones(df.shape[0]) * 0
                    zone_data[zone].append(df)
                if recorded_setpoint_changes != []:
                    print("The following were recorded setpoint changes:" , recorded_setpoint_changes)

                print("Done with action: ", i)
                with open("./Freezing_"+self.building+ "/"+ str(i) + ";"+  action_zone + ";" + datetime.datetime.utcnow().strftime('%Y-%m-%d_%H-%M-%S'), "wb") as f:
                    pickle.dump({"zone": action_zone, "action": i, "data": zone_data}, f)

            print("done with zone", action_zone)
    #         for zone, arr in zone_data.items():
    #             final_data[zone] = pd.DataFrame(arr)
    #         print(final_data)

if __name__ == '__main__':
    import sys, yaml
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

    collector = ThermalDataCollector(client, cfg["Building"])
    collector.control(collector.tstats, interval = 30., dt = 30/60.)






