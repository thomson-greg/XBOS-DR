import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

# daniel imports
from sklearn.base import BaseEstimator, RegressorMixin


# following model also works as a sklearn model.
class ThermalModel(BaseEstimator, RegressorMixin):
    # keeping track of all the rmse's computed with this class.
    trivial_rmse = []
    rmse = []
    scoreTypeList = []  # to know which action each rmse belongs to.

    def __init__(self, scoreType=-1):
        '''
        _params:
            scoreType: (int) which actions to filter by when scoring. -1 indicates no filter, 0 no action,
                        1 heating, 2 cooling.
        '''
        self.scoreType = scoreType

        self._params = None

    # thermal model function
    def _func(self, X, *coeff):
        """The polynomial with which we model the thermal model.
        :param X: pd.df with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all have to begin with "zone_temperature_" + "zone name"
        :param *coeff: the coefficients for the thermal model. Should be in order: a1, a2, (Tout - Tin), bias, zones coeffs. 
        """
        Tin, a1, a2, Tout, dt, zone_temperatures = X[0], X[1], X[2], X[3], X[4], X[5:]

        c1, c2, c3, c4, c_rest = coeff[0], coeff[1], coeff[2], coeff[3], coeff[4:]
        return Tin + (c1 * a1 * Tin + c2 * a2 * Tin + c3 * (Tout - Tin) + c4 +
                      sum([c * (zone_temp - Tin) for c, zone_temp in zip(c_rest, zone_temperatures)])) * dt

    def fit(self, X, y=None):
        """Needs to be called to fit the model. Will set self._params to coefficients. 
        :param X: pd.df with columns ('t_in', 'a1', 'a2', 't_out', 'dt') and all zone temperature where all have to begin with "zone_temperature_" + "zone name"
        :param y: the labels corresponding to the data. 
        :return self
        """
        zone_col = X.columns[["zone_temperature_" in col for col in X.columns]]
        filter_columns = ['t_in', 'a1', 'a2', 't_out', 'dt'] + list(zone_col)

        popt, pcov = curve_fit(self._func, X[filter_columns].T.as_matrix(), y.as_matrix(),
                               p0=np.ones(4 + len(
                                   zone_col)))  # fit the data. we start our guess with all ones for coefficients. Need to do so to be able to generalize to variable number of zones.
        self._params = popt
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

        zone_col = X.columns[["temperature_" in col for col in X.columns]]
        filter_columns = ['t_in', 'a1', 'a2', 't_out', 'dt'] + list(zone_col)

        res = [self._func(X.loc[date][filter_columns], *self._params)
               for date in X.index]

        return res

    def _normalizedRMSE(self, dt, prediction, y):
        '''Computes the RMSE with scaled differences to normalize to 15 min intervals.'''
        diff = prediction - y
        diff_scaled = diff * 15. / dt  # to offset for actions which were less than 15 min. makes everything a lot worse
        rmse = np.sqrt(np.mean(np.square(diff_scaled)))
        return rmse

    def score(self, X, y, sample_weight=None):
        """Scores the model on the dataset given by X and y."""
        ThermalModel.scoreTypeList.append(self.scoreType)  # filter by the action we want to score by
        if self.scoreType == 0:
            filter_arr = (X['a1'] == 0) & (X['a2'] == 0)
        elif self.scoreType == 1:
            filter_arr = X['a1'] == 1
        elif self.scoreType == 2:
            filter_arr = X['a2'] == 1
        else:
            filter_arr = np.ones(X['a1'].shape) == 1

        X = X[filter_arr]
        y = y[filter_arr]

        prediction = self.predict(X)  # only need to predict for relevant actions

        rmse = self._normalizedRMSE(X['dt'], prediction, y)

        # add model RMSE for reference.
        ThermalModel.rmse.append(rmse)

        # add trivial error for reference.
        trivial_rmse = self._normalizedRMSE(X['dt'], X['t_in'], y)
        ThermalModel.trivial_rmse.append(trivial_rmse)

        return rmse

class MPCThermalModel:
    def __init__(self, thermal_data, weather_predictions, now, interval_length, max_actions, thermal_precision):
        """
    
        :param thermal_data: {"zone": pd.df thermal data for zone}
        :param weather_predictions: pd.df for whole building
        :param now: 
        :param interval_length: 
        :param max_actions: 
        :param thermal_precision: 
        """
        self.zoneThermalModels = self.fit_zones(thermal_data)
        self.weather_predictions = weather_predictions
        self.now = now
        self.interval = interval_length # new for predictions. Will be fixed right?
        # TODO Make sure data starts now i guess? do we really care? We do need the current temperature though so we can keep constant throughout zones.
        self.zoneTemperatures = {zone: df.loc[now] for zone, df in thermal_data.items()} # we will keep the temperatures constant throughout the MPC as an approximation.

    def fit(self, data):
        """Assigns a thermal model to each zone"""
        zoneModels = {}
        for zone, val in data.items():
            zoneModels[zone] = ThermalModel().fit(val, val["t_next"])
        return zoneModels

    def predict(self, temperature, zone, time, action):
        """Predicts temperature for zone given."""
        X = {"dt":self.interval, "t_in": temperature, "a1": int(0<action<=1), "a2": int(1<action<=2) , "t_out": self.weather_predictions.loc[time]}
        for key_zone, val in self.zoneTemperatures.items():
            if key_zone != zone:
                X["zone_temperature_"+zone] = val
        #from_node.temps[i],action[i],from_node.time / self.interval, zone=i)
        return self.zoneThermalModels[zone].predict(pd.DataFrame(X))