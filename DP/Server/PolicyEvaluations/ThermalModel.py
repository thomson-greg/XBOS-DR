import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

# daniel imports
from sklearn.base import BaseEstimator, RegressorMixin

import yaml
import pyaml


# following model also works as a sklearn model.
class ThermalModel(BaseEstimator, RegressorMixin):

    def __init__(self, scoreType=-1):
        '''
        _params:
            scoreType: (int) which actions to filter by when scoring. -1 indicates no filter, 0 no action,
                        1 heating, 2 cooling.
        '''
        self.scoreType = scoreType # instance variable because of how cross validation works with sklearn

        self._params = None
        self._params_order = None


        # NOTE: if wanting to use cross validation, put these as class variables. Also, change in score, e.g. self.model_error to ThermalModel.model_error
        # keeping track of all the rmse's computed with this class.
        # first four values are always the training data errors.
        self.baseline_error = []
        self.model_error = []
        self.scoreTypeList = []  # to know which action each rmse belongs to.
        self.betterThanBaseline = []

    # thermal model function
    def _func(self, X, *coeff):
        """The polynomial with which we model the thermal model.
        :param X: pd.df with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all have to begin with "zone_temperature_" + "zone name"
        :param *coeff: the coefficients for the thermal model. Should be in order: a1, a2, (Tout - Tin), bias, zones coeffs. 
        """
        Tin, a1, a2, Tout, dt, zone_temperatures = X[0], X[1], X[2], X[3], X[4], X[5:]

        c1, c2, c3, c4, c_rest = coeff[0], coeff[1], coeff[2], coeff[3], coeff[4:]

        first_half = c1 * a1 * Tin + c2 * a2 * Tin + c3 * (Tout - Tin) + c4
        second_half = 0
        for c, zone_temp in zip(c_rest, zone_temperatures):
            diff = zone_temp - Tin
            second_half += c * diff
        return Tin + (first_half + second_half) * dt

    def fit(self, X, y=None):
        """Needs to be called to fit the model. Will set self._params to coefficients. 
        :param X: pd.df with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all have to begin with "zone_temperature_" + "zone name"
        :param y: the labels corresponding to the data. 
        :return self
        """
        zone_col = X.columns[["zone_temperature_" in col for col in X.columns]]
        filter_columns = ['t_in', 'a1', 'a2', 't_out', 'dt'] + list(zone_col)

        # give mapping from params to coefficients
        self._params_order = filter_columns

        popt, pcov = curve_fit(self._func, X[filter_columns].T.as_matrix(), y.as_matrix(),
                               p0=np.ones(len(
                                   self._params_order)))  # fit the data. we start our guess with all ones for coefficients. Need to do so to be able to generalize to variable number of zones.
        self._params = popt
        # score training data
        for action in range(-1, 3):
            self.score(X, y, scoreType=action)
        #--------------------
        return self

    def predict(self, X, y=None):
        """Predicts the temperatures for each row in X.
        :param X: pd.df with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all have to begin with "zone_temperature_" + "zone name"
        :return (list) entry corresponding to prediction of row in X.
        """
        # only predicts next temperatures
        try:
            getattr(self, "_params")
        except AttributeError:
            raise RuntimeError("You must train classifer before predicting data!")

        # assumes that pandas gives the right order given that the indexing is in the right order.
        res = [self._func(X.loc[date][self._params_order], *self._params)
               for date in X.index]

        return res

    def _normalizedRMSE_STD(self, dt, prediction, y):
        '''Computes the RMSE with scaled differences to normalize to 15 min intervals.'''
        diff = prediction - y
        diff_scaled = diff * 15. / dt  # to offset for actions which were less than 15 min. makes everything a lot worse
        mean_error = np.mean(diff_scaled)
        rmse = np.sqrt(np.mean(np.square(diff_scaled)))
        # standard deviation of the error
        diff_std = np.sqrt(np.mean(np.square(diff_scaled - mean_error)))
        return mean_error, rmse, diff_std

    def score(self, X, y, sample_weight=None, scoreType = None):
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
    def __init__(self, thermal_data, interval_length):
        """
    
        :param thermal_data: {"zone": pd.df thermal data for zone}
        :param now: 
        :param interval_length: 
        :param max_actions: 
        :param thermal_precision: 
        """
        self.zoneThermalModels = self.fit_zones(thermal_data)
        self.interval = interval_length  # new for predictions. Will be fixed right?
        # TODO Make sure data starts now i guess? do we really care? We do need the current temperature though so we can keep constant throughout zones.
        self.zoneTemperatures = {zone: df.iloc[-1]["t_in"] for zone, df in
                                 thermal_data.items()}  # we will keep the temperatures constant throughout the MPC as an approximation.

    def set_zone_temperatures(self, zone_temps):
        # store curr temperature for every zone. Call whenever we are starting new interval.
        self.zoneTemperatures = zone_temps

    def fit_zones(self, data):
        """Assigns a thermal model to each zone.
        :param data: {zone: timeseries pd.df columns (t_in, dt, a1, a2, t_out, other_zone_temperatures)"""
        zoneModels = {}
        for zone, val in data.items():
            zoneModels[zone] = ThermalModel().fit(val, val["t_next"])
        return zoneModels

    def predict(self, temperature, zone, action, outside_temperature, interval=None):
        """Predicts temperature for zone given."""
        if interval is None:
            interval = self.interval
        X = {"dt": interval, "t_in": temperature, "a1": int(0 < action <= 1), "a2": int(1 < action <= 2),
             "t_out": outside_temperature}
        for key_zone, val in self.zoneTemperatures.items():
            if key_zone != zone:
                X["zone_temperature_" + key_zone] = val

        return self.zoneThermalModels[zone].predict(pd.DataFrame(X, index=[0]))

    def save_to_config(self):
        """saves the whole model to a yaml file."""
        config_dict = {}
        # store zone temperatures
        config_dict["Zone Temperatures"] = self.zoneTemperatures
        for zone in self.zoneThermalModels.keys():
            config_dict[zone] = {}
            zone_thermal_model = self.zoneThermalModels[zone]
            # store coefficients
            coefficients = {parameter_name: param for parameter_name, param in zip(zone_thermal_model._params_order, zone_thermal_model._params)}
            config_dict[zone]["coefficients"] = coefficients
            # store evaluations and RMSE's.
            config_dict[zone]["Evaluations"] = {}
            config_dict[zone]["Evaluations"]["Baseline"] = zone_thermal_model.baseline_error
            config_dict[zone]["Evaluations"]["Model"] = zone_thermal_model.model_error
            config_dict[zone]["Evaluations"]["ActionOrder"] = zone_thermal_model.scoreTypeList
            config_dict[zone]["Evaluations"]["Better Than Baseline"] = zone_thermal_model.betterThanBaseline


        with open("config_ThermalModel", 'wb') as ymlfile:
            pyaml.dump(config_dict, ymlfile)







if __name__ == '__main__':
    import pickle

    therm_data_file = open("zone_thermal_ciee")
    therm_data = pickle.load(therm_data_file)

    therm_data_file.close()

    mpcThermalModel = MPCThermalModel(therm_data, 15)
    #mpcThermalModel.save_to_config()
    print mpcThermalModel.zoneTemperatures
    print(mpcThermalModel.predict(70, "HVAC_Zone_Centralzone", 0, 70))
    #
    # thermal_model = open("thermal_model", "wb")
    # pickle.dump(mpcThermalModel, thermal_model)
    # thermal_model.close()
