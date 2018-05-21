import datetime
import json
import os
import pytz
from datetime import timedelta

import pandas as pd
import numpy as np
import requests
from xbos import get_client
from xbos.services import mdal
from xbos.services.hod import HodClient


# TODO add energy data acquisition
# TODO FIX DAYLIGHT TIME CHANGE PROBLEMS


class DataManager:
    """
    # Class that handles all the data fetching and some of the preprocess
    """

    def __init__(self, building, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))):

        self.pytz_timezone = pytz.timezone("America/Los_Angeles")
        self.building = building
        self.interval = 15
        self.now = now

        self.window_size = 1 # 1 min windosize for mdal.


        self.client = get_client()

        self.hod_client = HodClient("xbos/hod", self.client)  # TODO hopefully i could incorporate this into the query.

    def preprocess_occ(self):
        """
        Returns the required dataframe for the occupancy predictions
        -------
        Pandas DataFrame
        """
        # this only works for ciee, check how it should be writen properly:
        hod = HodClient(self.cfg["Data_Manager"]["Hod_Client"], self.client)

        occ_query = """SELECT ?sensor ?uuid ?zone WHERE {
		  ?sensor rdf:type brick:Occupancy_Sensor .
		  ?sensor bf:isLocatedIn/bf:isPartOf ?zone .
		  ?sensor bf:uuid ?uuid .
		  ?zone rdf:type brick:HVAC_Zone
		};
		"""  # get all the occupancy sensors uuids

        results = hod.do_query(occ_query)  # run the query
        uuids = [[x['?zone'], x['?uuid']] for x in results['Rows']]  # unpack

        # only choose the sensors for the zone specified in cfg
        query_list = []
        for i in uuids:
            if i[0] == self.zone:
                query_list.append(i[1])

        # get the sensor data
        c = mdal.MDALClient("xbos/mdal")
        dfs = c.do_query({'Composition': query_list,
                          'Selectors': [mdal.MAX] * len(query_list),
                          'Time': {'T0': (self.now - timedelta(days=25)).strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                                   'T1': self.now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                                   'WindowSize': str(self.interval) + 'min',
                                   'Aligned': True}})

        dfs = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)

        df = dfs[[query_list[0]]]
        df.columns.values[0] = 'occ'
        df.is_copy = False
        df.columns = ['occ']
        # perform OR on the data, if one sensor is activated, the whole zone is considered occupied
        for i in range(1, len(query_list)):
            df.loc[:, 'occ'] += dfs[query_list[i]]
        df.loc[:, 'occ'] = 1 * (df['occ'] > 0)

        return df.tz_localize(None)

    def weather_fetch(self):
        from dateutil import parser
        coordinates = self.controller_cfg["Coordinates"]

        if not os.path.exists("weather.json"):
            temp = requests.get("https://api.weather.gov/points/" + coordinates).json()
            weather = requests.get(temp["properties"]["forecastHourly"])
            data = weather.json()
            with open('weather.json', 'w') as f:
                json.dump(data, f)

        myweather = json.load(open("weather.json"))
        json_start = parser.parse(myweather["properties"]["periods"][0]["startTime"])
        if (json_start.hour < self.now.astimezone(tz=pytz.timezone(self.pytz_timezone)).hour) or \
                (datetime.datetime(json_start.year, json_start.month, json_start.day).replace(
                    tzinfo=pytz.timezone(self.pytz_timezone)) <
                     datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(
                         tz=pytz.timezone(self.pytz_timezone))):
            temp = requests.get("https://api.weather.gov/points/" + coordinates).json()
            weather = requests.get(temp["properties"]["forecastHourly"])
            data = weather.json()
            with open('weather.json', 'w') as f:
                json.dump(data, f)
            myweather = json.load(open("weather.json"))

        weather_predictions = {}

        for i, data in enumerate(myweather["properties"]["periods"]):
            hour = parser.parse(data["startTime"]).hour
            weather_predictions[hour] = int(data["temperature"])
            if i == self.horizon:
                break

        return weather_predictions

    def thermostat_setpoints(self):

        uuids = [self.cfg["Data_Manager"]["UUIDS"]['Thermostat_high'],
                 self.cfg["Data_Manager"]["UUIDS"]['Thermostat_low'],
                 self.cfg["Data_Manager"]["UUIDS"]['Thermostat_mode']]

        c = mdal.MDALClient("xbos/mdal", client=self.client)
        dfs = c.do_query({'Composition': uuids,
                          'Selectors': [mdal.MEAN, mdal.MEAN, mdal.MEAN],
                          'Time': {'T0': (self.now - timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                                   'T1': self.now.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                                   'WindowSize': '1min',
                                   'Aligned': True}})

        df = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)
        df = df.rename(columns={uuids[0]: 'T_High', uuids[1]: 'T_Low', uuids[2]: 'T_Mode'})

        return df['T_High'][-1], df['T_Low'][-1], df['T_Mode'][-1]


if __name__ == '__main__':
    import yaml

    from xbos.services.hod import HodClient

    hc = HodClient("xbos/hod")

    q2 = """
    SELECT * WHERE {
        ?sites rdf:type brick:Site.
    };"""
    hd_res = hc.do_query(q2)["Rows"]


    dm = DataManager("ciee")
    # print dm.weather_fetch()
    import pickle
    if True:
        start = datetime.datetime(year=2018, day=1, month=1)
        end = datetime.datetime(year=2018, day=1, month=3)
        if False:
            for b in hd_res[7:]:
                bldg = b["?sites"]
                print(bldg)

                dm.building = bldg
                z = dm.thermal_data(start, end)
                zone_file = open("zone_thermal_" + dm.building, 'wb')
                pickle.dump(z, zone_file)
                zone_file.close()
        else:
            z = dm.thermal_data(start, end)
            zone_file = open("zone_thermal_" + dm.building, 'wb')
            pickle.dump(z, zone_file)
            zone_file.close()




# print dm.preprocess_occ()
# print dm.thermostat_setpoints()

#rsf fails.
