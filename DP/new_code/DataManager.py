import datetime
import json
import os
import pytz
from datetime import timedelta

import pandas as pd
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

    def __init__(self, cfg, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC"))):

        self.cfg = cfg
        self.pytz_timezone = cfg["Data_Manager"]["Pytz_Timezone"]
        self.zone = cfg["Data_Manager"]["Zone"]
        self.building = cfg["Data_Manager"]["Building"]
        self.interval = cfg["Interval_Length"]
        self.now = now

        if cfg["Data_Manager"]["Server"]:
            self.client = get_client(agent=cfg["Data_Manager"]["Agent_IP"], entity=cfg["Data_Manager"]["Entity_File"])
        else:
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

    def _get_thermal_data(self, start, end):
        """Get thermostat status and temperature and outside temperature for thermal model.
        :param start: (datetime) time to start.
        :param end: (datetime) time to end.
        :return dict{zone: pd.df columns["tin", "a"]}, pd.df columns["tout"]. Timerseries are the same for both with same freq."""

        # following queries are for the whole building.
        thermostat_status_query = """SELECT ?zone ?uuid FROM %s WHERE { 
		  ?tstat rdf:type brick:Thermostat .
		  ?tstat bf:hasLocation/bf:isPartOf ?location_zone .
		  ?location_zone rdf:type brick:HVAC_Zone .
		  ?tstat bf:controls ?RTU .
		  ?RTU rdf:type brick:RTU . 
		  ?RTU bf:feeds ?zone. 
		  ?zone rdf:type brick:HVAC_Zone . 
		  ?status_point bf:isPointOf ?tstat .
		  ?status_point rdf:type brick:Thermostat_Status .
		  ?status_point bf:uuid ?uuid.
		};"""

        thermostat_temperature_query = """SELECT ?zone ?uuid FROM %s WHERE { 
		  ?tstat rdf:type brick:Thermostat .
		  ?tstat bf:hasLocation/bf:isPartOf ?location_zone .
		  ?location_zone rdf:type brick:HVAC_Zone .
		  ?tstat bf:controls ?RTU .
		  ?RTU rdf:type brick:RTU . 
		  ?RTU bf:feeds ?zone. 
		  ?zone rdf:type brick:HVAC_Zone . 
		  ?thermostat_point bf:isPointOf ?tstat .
		  ?thermostat_point rdf:type brick:Temperature_Sensor .
		  ?thermostat_point bf:uuid ?uuid.
		};"""

        outside_temperature_query = """SELECT ?weather_station ?uuid FROM %s WHERE {
			?weather_station rdf:type brick:Weather_Temperature_Sensor.
			?weather_station bf:uuid ?uuid.
		};"""

        temp_thermostat_query_data = {
            "tstat_temperature": self.hod_client.do_query(thermostat_temperature_query % self.building)["Rows"],
            "tstat_action": self.hod_client.do_query(thermostat_status_query % self.building)["Rows"],
        }

        # give the thermostat query data better structure for later loop. Can index by zone and then get uuids for each
        # thermostat attribute.
        thermostat_query_data = {}
        for tstat_attr, attr_dicts in temp_thermostat_query_data.items():
            for dict in attr_dicts:
                if dict["?zone"] not in thermostat_query_data:
                    thermostat_query_data[dict["?zone"]] = {}
                thermostat_query_data[dict["?zone"]][tstat_attr] = dict["?uuid"]

        # get outside temperature data
        outside_temperature_query_data = self.hod_client.do_query(outside_temperature_query % self.building)["Rows"][
            0]  # TODO for now taking the first weather station. Should be determined based on metadata.
        c = mdal.MDALClient("xbos/mdal", client=self.client)
        outside_temperature_data = c.do_query({
            'Composition': ["1c467b79-b314-3c1e-83e6-ea5e7048c37b"], # uuid from Mr.Plotter. should use outside_temperature_query_data["?uuid"],
            'Selectors': [mdal.MEAN]
            , 'Time': {'T0': start.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                       'T1': end.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                       'WindowSize': '1min',
                       'Aligned': True}})
        outside_temperature_data = outside_temperature_data["df"] # since only data for one uuid
        outside_temperature_data.columns = ["t_out"]

        # get the data for the thermostats for each zone.
        zone_thermal_data = {}
        for zone, dict in thermostat_query_data.items():
            # get the thermostat data
            dfs = c.do_query({'Composition': [dict["tstat_temperature"], dict["tstat_action"]],
                              'Selectors': [mdal.MEAN, mdal.MAX]
                                 , 'Time': {'T0': start.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                                           'T1': end.strftime('%Y-%m-%d %H:%M:%S') + ' UTC',
                                           'WindowSize': '1min',
                                            'Aligned': True}})
            df = pd.concat([dframe for uid, dframe in dfs.items()], axis=1)

            zone_thermal_data[zone] = df.rename(columns={dict["tstat_temperature"]: 't_in', dict["tstat_action"]: 'a'})

        return zone_thermal_data, outside_temperature_data


    def preprocess_thermal_data(self, zone_data, outside_data):
        """Preprocesses the data for the thermal model.
        :param zone_data: dict{zone: pd.df columns["tin", "a"]}
        :param outside_data: pd.df columns["tout"]. 
        Note: Timerseries are the same for zone_data and outside_dataa with same freq. 
        
        :returns {zone: pd.df columns: t_in', 't_next', 'dt','t_out', 'action', 'a1', 'a2', [other mean zone temperatures]}
                 where t_out and zone temperatures are the mean values over the intervals. 
                 a1 is whether heating and a2 whether cooling."""


        # thermal data preprocess starts here
        def f1(row):
            """
            helper function to format the thermal model dataframe
            """
            if row['action'] == 1.:
                val = 1
            else:
                val = 0
            return val

        # if state is 2 we are doing cooling
        def f2(row):
            """
            helper function to format the thermal model dataframe
            """
            if row['action'] == 2.:
                val = 1
            else:
                val = 0
            return val

        def f3(row):
            """
            helper function to format the thermal model dataframe
            """
            if 0 < row['a'] <= 1:
                return 1
            elif 1 < row['a'] <= 2:
                return 2
            else:
                return 0

        all_temperatures = pd.concat([tstat_df["t_in"] for tstat_df in zone_data.values()], axis=1)
        all_temperatures.columns = ["temperature_" + zone for zone in zone_data.keys()]
        zone_thermal_model_data = {}

        for zone in zone_data.keys():
            actions = zone_data[zone]["a"]
            thermal_model_data = pd.concat([all_temperatures, actions, outside_data], axis=1)  # should be copied data
            thermal_model_data = thermal_model_data.rename(columns={"temperature_" + zone: "t_in"})

            thermal_model_data['a'] = thermal_model_data.apply(f3, axis=1)

            # prepares final data type.
            thermal_model_data['change_of_action'] = (thermal_model_data['a'].diff(1) != 0).astype(
                'int').cumsum()  # given a row it's the number of times we have had an action change up till then. e.g. from nothing to heating.
            # This is accomplished by taking the difference of two consecutive rows and checking if their difference is 0 meaning that they had the same action.

            # following adds the fields "time", "dt" etc such that we accumulate all values where we have consecutively the same action.
            # maximally we group terms of total interval length 15
            data_list = []
            for j in thermal_model_data.change_of_action.unique():
                for i in range(0, thermal_model_data[thermal_model_data['change_of_action'] == j].shape[0], self.interval):
                    for dfs in [thermal_model_data[thermal_model_data['change_of_action'] == j][i:i + self.interval]]:
                        # we only look at intervals where the last and first value for T_in are not Nan.
                        dfs.dropna(subset=["t_in"])
                        zone_col_filter = ["temperature_" in col for col in dfs.columns]
                        temp_data_dict = {'time': dfs.index[0],
                                          't_in': dfs['t_in'][0],
                                          't_next': dfs['t_in'][-1],
                                          'dt': dfs.index[-1] - dfs.index[0],
                                          't_out': dfs['t_out'].mean(), # mean does not count Nan values
                                          'action': dfs['a'][0]}
                        for zone in dfs.columns[zone_col_filter]:
                            # mean does not count Nan values
                            temp_data_dict[zone] = dfs[zone].mean()
                        data_list.append(temp_data_dict)



            thermal_model_data = pd.DataFrame(data_list).set_index('time')
            thermal_model_data['a1'] = thermal_model_data.apply(f1, axis=1)
            thermal_model_data['a2'] = thermal_model_data.apply(f2, axis=1)
            thermal_model_data = thermal_model_data.dropna() # final drop. Mostly if the whole interval for the zones or t_out were nan.
            zone_thermal_model_data[zone] = thermal_model_data.tz_localize(None)
        return zone_thermal_model_data

    def weather_fetch(self):

        wunderground_key = self.cfg["Data_Manager"]["Wunderground_Key"]
        wunderground_place = self.cfg["Data_Manager"]["Wunderground_Place"]

        if not os.path.exists("weather.json"):
            weather = requests.get(
                "http://api.wunderground.com/api/" + wunderground_key + "/hourly/q/pws:" + wunderground_place + ".json")
            data = weather.json()
            with open('weather.json', 'w') as f:
                json.dump(data, f)

        myweather = json.load(open("weather.json"))
        if int(myweather['hourly_forecast'][0]["FCTTIME"]["hour"]) < \
                self.now.astimezone(tz=pytz.timezone(self.pytz_timezone)).hour:
            weather = requests.get(
                "http://api.wunderground.com/api/" + wunderground_key + "/hourly/q/pws:" + wunderground_place + ".json")
            data = weather.json()
            with open('weather.json', 'w') as f:
                json.dump(data, f)
            myweather = json.load(open("weather.json"))

        weather_predictions = {}
        for data in myweather['hourly_forecast']:
            weather_predictions[int(data["FCTTIME"]["hour"])] = int(data["temp"]["english"])

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

    with open("config_south.yml", 'r') as ymlfile:
        cfg = yaml.load(ymlfile)

    dm = DataManager(cfg)
    # print dm.weather_fetch()
    import pickle
    if False:
        start = datetime.datetime(year=2018, day=10, month=1)
        end = datetime.datetime(year=2018, day=20, month=1)

        zone_file = open("zone_thermal", 'wb')
        outside_file = open("outside_temperature", 'wb')
        z, o = dm._get_thermal_data(start, end)
        pickle.dump(z, zone_file)
        pickle.dump(o, outside_file)
        zone_file.close()
        outside_file.close()

    if True:

        zone_file = open("zone_thermal", 'r')
        outside_file = open("outside_temperature", 'r')

        z, o = pickle.load(zone_file), pickle.load(outside_file)
        zone_file.close()
        outside_file.close()

        print(dm.preprocess_thermal_data(z, o))
# print dm.preprocess_occ()
# print dm.thermostat_setpoints()
