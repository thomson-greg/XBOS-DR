import numpy as np
import pandas as pd

import yaml
from scipy.optimize import curve_fit
# daniel imports
from sklearn.base import BaseEstimator, RegressorMixin


# following model also works as a sklearn model.
class ThermalModel(BaseEstimator, RegressorMixin):
    def __init__(self, scoreType=-1, thermal_precision=2):
        '''
        _params:
            scoreType: (int) which actions to filter by when scoring. -1 indicates no filter, 0 no action,
                        1 heating, 2 cooling.
        :param thermal_precision: the number of decimal points when predicting.
        '''
        self.scoreType = scoreType  # instance variable because of how cross validation works with sklearn

        self._params = None
        self._params_order = None
        self._filter_columns = None  # order of columns by which to filter when predicting and fitting data.

        # NOTE: if wanting to use cross validation, put these as class variables.
        #  Also, change in score, e.g. self.model_error to ThermalModel.model_error
        # keeping track of all the rmse's computed with this class.
        # first four values are always the training data errors.
        self.baseline_error = []
        self.model_error = []
        self.scoreTypeList = []  # to know which action each rmse belongs to.
        self.betterThanBaseline = []

        self.thermalPrecision=thermal_precision
        self.learning_rate  = 0.01 # TODO make input and evaluate which one is best.

    # thermal model function
    def _func(self, X, *coeff):
        """The polynomial with which we model the thermal model.
        :param X: pd.df with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all 
        have to begin with "zone_temperature_" + "zone name"
        :param *coeff: the coefficients for the thermal model. Should be in order: Tin, a1, a2, (Tout - Tin),
         bias, zones coeffs (as given by self._params_order)
        """
        Tin, a1, a2, Tout, dt, zone_temperatures = X[0], X[1], X[2], X[3], X[4], X[5:]

        c1, c2, c3, c4, c_rest = coeff[0], coeff[1], coeff[2], coeff[3], coeff[4:]

        # putting together the function
        first_half = c1 * a1 * Tin + c2 * a2 * Tin + c3 * (Tout - Tin) + c4
        second_half = 0
        for c, zone_temp in zip(c_rest, zone_temperatures):
            diff = zone_temp - Tin
            second_half += c * diff
        return Tin + (first_half + second_half) * dt

    def _features(self, X):
        Tin, a1, a2, Tout, dt, zone_temperatures = X[0], X[1], X[2], X[3], X[4], X[5:]
        features = [a1, a2, Tout - Tin, 1]
        for zone_temp in zone_temperatures:
            features.append(zone_temp - Tin)

        return np.array(features)


    def fit(self, X, y=None):
        """Needs to be called to fit the model. Will set self._params to coefficients. 
        :param X: pd.df with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all have 
        to begin with "zone_temperature_" + "zone name"
        :param y: the labels corresponding to the data. As a pd.dataframe
        :return self
        """
        zone_col = X.columns[["zone_temperature_" in col for col in X.columns]]
        filter_columns = ['t_in', 'a1', 'a2', 't_out', 'dt'] + list(zone_col)

        # give mapping from params to coefficients and to store the order in which we get the columns.
        self._filter_columns = filter_columns
        self._params_order = ["a1", 'a2', 't_out', 'bias'] + list(zone_col)

        # fit the data. we start our guess with all ones for coefficients.
        # Need to do so to be able to generalize to variable number of zones.
        popt, pcov = curve_fit(self._func, X[filter_columns].T.as_matrix(), y.as_matrix(),
                               p0=np.ones(len(
                                   self._params_order)))
        self._params = np.array(popt)
        # score training data
        for action in range(-1, 3):
            self.score(X, y, scoreType=action)
        # --------------------
        return self

    def updateFit(self, X, y):
        """Adaptive Learning. The data given will all be given the same weight when learning.
        :param X: (pd.df) with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all have 
        to begin with "zone_temperature_" + "zone name
        :param y: (float)"""
        # fit the data. we start our guess with all ones for coefficients.
        # Need to do so to be able to generalize to variable number of zones.
        # NOTE: Using gradient decent $$self.params = self.param - self.learning_rate * 2 * (self._func(X, *params) - y) * features(X)
        loss = self._func(X[self._filter_columns].T.as_matrix(), *self._params)[0] - y
        adjust =  self.learning_rate * loss * self._features(X[self._filter_columns].T.as_matrix())
        self._params = np.array(self._params) - adjust


    def predict(self, X, y=None):
        """Predicts the temperatures for each row in X.
        :param X: pd.df/pd.Series with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperatures where all 
        have to begin with "zone_temperature_" + "zone name"
        :return (np.array) entry corresponding to prediction of row in X.
        """
        # only predicts next temperatures
        try:
            getattr(self, "_params")
        except AttributeError:
            raise RuntimeError("You must train classifer before predicting data!")

        # assumes that pandas returns df in order of indexing when doing X[self._filter_columns].
        predictions = self._func(X[self._filter_columns].T.as_matrix(), *self._params)

        return np.round(predictions, self.thermalPrecision)

    def _normalizedRMSE_STD(self, prediction, y, dt):
        '''Computes the RMSE with scaled differences to normalize to 15 min intervals.
        NOTE: Use method if you already have predictions.'''
        diff = prediction - y

        # to offset for actions which were less than 15 min. Normalizes to 15 min intervals.
        # TODO maybe make variable standard intervals.
        diff_scaled = diff * 15. / dt
        mean_error = np.mean(diff_scaled)
        rmse = np.sqrt(np.mean(np.square(diff_scaled)))
        # standard deviation of the error
        diff_std = np.sqrt(np.mean(np.square(diff_scaled - mean_error)))
        return mean_error, rmse, diff_std

    def score(self, X, y, sample_weight=None, scoreType=None):
        """Scores the model on the dataset given by X and y."""
        if scoreType is None:
            scoreType = self.scoreType
        assert scoreType in list(range(-1, 4))

        self.scoreTypeList.append(scoreType)  # filter by the action we want to score by
        if scoreType == 0:
            filter_arr = (X['a1'] == 0) & (X['a2'] == 0)
        elif scoreType == 1:
            filter_arr = X['a1'] == 1
        elif scoreType == 2:
            filter_arr = X['a2'] == 1
        else:
            filter_arr = np.ones(X['a1'].shape) == 1

        X = X[filter_arr]
        y = y[filter_arr]

        prediction = self.predict(X)  # only need to predict for relevant actions

        mean_error, rmse, std = self._normalizedRMSE_STD(X['dt'], prediction, y)

        # add model RMSE for reference.
        self.model_error.append({"mean": mean_error, "rmse": rmse, "std": std})

        # add trivial error for reference.
        trivial_mean_error, trivial_rmse, trivial_std = self._normalizedRMSE_STD(X['dt'], X['t_in'], y)
        self.baseline_error.append({"mean": trivial_mean_error, "rmse": trivial_rmse, "std": trivial_std})

        # to keep track of whether we are better than the baseline/trivial
        self.betterThanBaseline.append(trivial_rmse > rmse)

        return rmse


class MPCThermalModel:
    """Class specifically designed for the MPC process. A container class for ThermalModels for each class with functions
        designed to simplify usage."""
    def __init__(self, thermal_data, interval_length):
        """
        :param thermal_data: {"zone": pd.df thermal data for zone}
        :param interval_length: 
        """
        self.zoneThermalModels = self.fit_zones(thermal_data)
        self.interval = interval_length  # new for predictions. Will be fixed right?
        # we will keep the temperatures constant throughout the MPC as an approximation.
        self.zoneTemperatures = {zone: df.iloc[-1]["t_in"] for zone, df in
                                 thermal_data.items()}

        self.weatherPredictions = None  # store weather predictions for whole class

        self.lastAction = None # TODO Fix, absolute hack and not good. controller should store this.
        self.now = None

    # TODO Fix, absolute hack and not good. controller should store this.
    def setLastActionAndTime(self, action, now):
        self.lastAction = action
        self.now = now

    def setWeahterPredictions(self, weatherPredictions):
        self.weatherPredictions = weatherPredictions

    def setZoneTemperaturesAndFit(self, zone_temps, dt):
        # TODO will all zones have the same dt ?
        """
        store curr temperature for every zone. Call whenever we are starting new interval.
        :param zone_temps: {zone: temperature}
        :return: 
        """
        if self.lastAction is None or self.weatherPredictions is None:
            self.zoneTemperatures = zone_temps
            return
        # ('t_in', 'a1', 'a2', 't_out', 'dt') and all
        # zone
        # temperature
        action = self.lastAction
        t_out = self.weatherPredictions[self.now.hour]
        for zone in self.zoneTemperatures.keys():
            X = {"a1": int(0 < action <= 1), "a2": int(1 < action <= 2), "dt": dt, "t_out": t_out, "t_in": self.zoneTemperatures[zone]}

            # Not most loop efficient but fine for now.
            for key_zone, val in self.zoneTemperatures.items():
                if key_zone != zone:
                    X["zone_temperature_" + key_zone] = val
            y = zone_temps[zone]
            X = pd.DataFrame(X, index=[0])
            # online learning the new data
            self.zoneThermalModels[zone].updateFit(X, y)

        self.zoneTemperatures = zone_temps

    def fit_zones(self, data):
        """Assigns a thermal model to each zone.
        :param data: {zone: timeseries pd.df columns (t_in, dt, a1, a2, t_out, other_zone_temperatures)"""
        zoneModels = {}
        for zone, val in data.items():
            zoneModels[zone] = ThermalModel().fit(val, val["t_next"])
        return zoneModels

    def predict(self, t_in, zone, action, outside_temperature=None, interval=None, time=-1):
        """
        Predicts temperature for zone given.
        :param t_in: 
        :param zone: 
        :param action: 
        :param outside_temperature: 
        :param interval: 
        :param time: the hour index for self.weather_predictions. 
        TODO understand how we can use hours if we look at next days .(i.e. horizon extends over midnight.)
        :return: (array) predictions in order
        """
        if interval is None:
            interval = self.interval
        if outside_temperature is None:
            assert time != -1
            assert self.weatherPredictions is not None
            outside_temperature = self.weatherPredictions[time]

        X = {"dt": interval, "t_in": t_in, "a1": int(0 < action <= 1), "a2": int(1 < action <= 2),
             "t_out": outside_temperature}
        for key_zone, val in self.zoneTemperatures.items():
            if key_zone != zone:
                X["zone_temperature_" + key_zone] = val

        return self.zoneThermalModels[zone].predict(pd.DataFrame(X, index=[0]))

    def save_to_config(self):
        """saves the whole model to a yaml file."""
        config_dict = {}
        for zone in self.zoneThermalModels.keys():
            config_dict[zone] = {}
            # store zone temperatures
            config_dict[zone]["Zone Temperatures"] = self.zoneTemperatures
            zone_thermal_model = self.zoneThermalModels[zone]
            # store coefficients
            coefficients = {parameter_name: param for parameter_name, param in
                            zip(zone_thermal_model._params_order, zone_thermal_model._params)}
            config_dict[zone]["coefficients"] = coefficients
            # store evaluations and RMSE's.
            config_dict[zone]["Evaluations"] = {}
            config_dict[zone]["Evaluations"]["Baseline"] = zone_thermal_model.baseline_error
            config_dict[zone]["Evaluations"]["Model"] = zone_thermal_model.model_error
            config_dict[zone]["Evaluations"]["ActionOrder"] = zone_thermal_model.scoreTypeList
            config_dict[zone]["Evaluations"]["Better Than Baseline"] = zone_thermal_model.betterThanBaseline

        for zone, dict in config_dict.items():
            with open("../ZoneConfigs/thermal_model_" + zone, 'wb') as ymlfile:
                # TODO Note import pyaml here to get a pretty config file.
                pyaml.dump(config_dict[zone], ymlfile)


if __name__ == '__main__':


    with open("../Buildings/ciee/ZoneConfigs/HVAC_Zone_CentralZone.yml", 'r') as ymlfile:
        advise_cfg = yaml.load(ymlfile)

    import pickle

    therm_data_file = open("../Thermal Data/ciee_thermal_data_demo")
    therm_data = pickle.load(therm_data_file)

    therm_data_file.close()

    mpcThermalModel = MPCThermalModel(therm_data, 15)

    with open("../Thermal Data/thermal_model_demo", "wb") as f:
        pickle.dump(mpcThermalModel, f)
