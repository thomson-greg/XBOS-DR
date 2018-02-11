import numpy as np
import yaml
import sys

import Occupancy

from gurobipy import *


def get_config():
    try:
        yaml_filename = sys.argv[1]
    except:
        sys.exit("Please specify the configuration file as: python2 controller.py config_file.yaml")

    with open(yaml_filename, 'r') as ymlfile:
        cfg = yaml.load(ymlfile)
    return cfg


def get_config_file(file):
    with open(file, 'r') as ymlfile:
        cfg = yaml.load(ymlfile)
    return cfg


class LinearZones:
    def __init__(self, config):
        """:param:
        config: The config file which has all the fields which are used in the current init. example: config_ciee.yml"""
        self.numZones = len(config["Zones"])
        self.deltaTime = config["interval_Length"]
        self.numHours = config["hours"]
        self.numTimesSteps = self.numHours / self.deltaTime


        self.priceBuy = config["priceBuy"]  # look at DP EnergyConsumption.py
        self.priceSell = config["priceSell"]  # set to zero for now since we won't sell energy in the US.

        # TODO Note changed logic in script for this. maxCooling when action is negative and vice versa.
        # TODO for now use a scalar which populates array. Array used for generality
        self.maxPowerHeating = config["maxPowerHeating"] * np.ones((self.numZones, self.numTimesSteps))
        self.maxPowerCooling = config["maxPowerCooling"] * np.ones((self.numZones, self.numTimesSteps))


        self.peakCost = config["peakCost"]  # peak_cost dollars/kW


        # The last peak demands
        self.lastPeakDemand = config["lastPeakDemand"]  # TODO needs to be filled in.

        # will be used to get the temperature setpoints.
        # Intended matrix (numZones x numTimesSteps) for generality.
        self.temperatureHighSet = config["maximum_Safety_Temp"] * np.ones((self.numZones, self.numTimesSteps))
        self.temperatureLowSet = config["minimum_Safety_Temp"] * np.ones((self.numZones, self.numTimesSteps))

        # TODO: set up with config
        self.leakageRate = np.ones(
            self.numZones)  # TODO Thermal model implement as in paper "AEC of Electricity-base Space Heating Systems" for each zone.



        # This is the heating efficiency parameter. Should be an array where the index is the corresponding zone.
        self.heatingEff = np.ones(self.numZones)  # For now it doesn't do anything.

        # Will represent the probability of occupation.
        # is intended to return a matrix where the row represents the ith zone and column the jth time-step.
        self.occupationModel = [Occupancy(get_config_file(zone)).predictions.values() for zone in config["Zones"]]

        # will be used to get the outside temperature.
        # is intended to return a matrix where the row represents the ith zone and column the jth time-step.
        self.outTemperature = np.zeros(self.numZones, self.numTimesSteps)  # "TODO. Ask Gabe."


        # The prediction of the power consumption of the building as a numZones x numTimesSteps matrix.
        self.powerModel = np.zeros(self.numZones,
                                   self.numTimesSteps)  # TODO work later. for now set to zero to only evaluate heating."

        # TODO Look into the weighing of each objective term.
        # discounting variable.
        # array numTimeSteps.
        self.discounting = np.ones(self.numTimesSteps)  # TODO Check if right. But leave as one.

        # comfort and cost balancing
        self.comfortBalancing = np.ones(self.numZones) - 0.1111  # TODO Implement for cost (1-\lambda). Think about it

        # the linear programming solver from gurobipy.
        self.model = Model("solver")

        # setting the thermal model. Matrix (zones x timeSteps)
        self.inTemperature = np.array([[
            self.model.addVar("Temperature_in_zone{" + str(z) + "}_time{" + str(t) + "}") for t in
            range(self.numTimesSteps)
        ] for z in range(self.numZones)])

        # We changed the following commented out section to have only self.action.
        '''
        the variables for the linear program. They control heat or cool. For now we will use binary variables.
        # has dimension numZone x numTimeSteps.
        self.heat = np.array([[self.model.addVar(
            vtype=GRB.BINARY, name="heat_zone{" + str(zone) + "}_time{" + str(time) + "}") for time in
            range(self.numTimesSteps)]
            for zone in range(self.numZones)])

        self.cool = np.array([[self.model.addVar(
            vtype=GRB.BINARY, name="cool_zone{" + str(zone) + "}_time{" + str(time) + "}") for time in
            range(self.numTimesSteps)]
            for zone in range(self.numZones)])
        '''

        # This will be the eventual action to be taken.
        # We constraint -self.maxPowerCooling <= self.action <= self.maxPowerHeating and self.action is continuous.
        # It indicates how much power we should use for cooling or heating.
        self.action = np.array(
            [[self.model.addVar(lb=-self.maxPowerCooling[zone, time], ub=self.maxPowerHeating[zone, time],
                                name="cool_zone{" + str(zone) + "}_time{" + str(time) + "}") for time
              in
              range(self.numTimesSteps)]
             for zone in range(self.numZones)])

        # Discomfort array of the linear program where index is the zone. Used for objective.
        self.discomfort = np.array([[self.model.addVar(
            name="discomfort_zone{" + str(zone) + "}" + "_time{" + time + "}") for time in range(self.numTimesSteps)]
                                   for zone in range(self.numZones)])

        # Heating Consumption matrix of LP without powerModel. numZones x numTimeSteps.
        self.heatingConsumption = np.array([
            [
                self.model.addVar(
                    name="heating_consumption_zone{" + str(zone) + "}_time{" + str(t) + "}")
                for t in range(self.numTimesSteps)]
            for zone in range(self.numZones)])

        # Right now as total energy consumptions. One entry if for consumption if sold and the other for
        # if bought
        self.totalConsumption = np.array([
            [
                [self.model.addVar(
                    name="consumption_sell_zone{" + str(zone) + "}_time{" + str(t) + "}"),
                    self.model.addVar(
                        name="consumption_buy_zone{" + str(zone) + "}_time{" + str(t) + "}")
                ]
                for t in range(self.numTimesSteps)]
            for zone in range(self.numZones)])

        # The peak demand charge for the given time period.
        self.peakCharge = self.model.addVar(name="peakDemandCharge")

    # following commented code was used for old action implementaiton.
    '''
    def constrain_action(self):
        """Constraints the actions, in case I make them non Binary. TODO Upper and lower bounds can actually be set in 
        the addVar step"""
        for z in range(self.numZones):
            for t in range(self.numTimesSteps):
                self.model.addConstr(self.cool[z][t] >= 0)
                self.model.addConstr(self.cool[z][t] <= 1)

                self.model.addConstr(self.heat[z][t] >= 0)
                self.model.addConstr(self.heat[z][t] <= 1)

                self.model.addConstr(self.heat[z][t] - self.cool[z][t] >= -1)
                self.model.addConstr(self.heat[z][t] - self.cool[z][t] <= 1)
    '''

    def set_objective(self):
        # TODO Fix occupancy
        obj = LinExpr()
        obj += self.discomfort.dot(self.comfortBalancing)  # add the discomfort term
        obj += self.totalConsumption
        temp_rev = self.totalConsumption[:, 0] * self.priceSell  # setting the revenue we might make.
        temp_cost = self.totalConsumption[:, 1] * self.priceBuy  # setting the cost we might have to pay.
        obj += temp_rev.dot(self.discounting) + temp_cost.dot(self.discounting)  # cost term added
        obj += self.peakCharge / self.deltaTime * self.peakCost * 1 / self.numTimesSteps  # add demand charge term from paper "Smart Charge"

        self.model.setObjective(obj, GRB.MAXIMIZE)

    def set_discomfort(self):
        """Set the constraints for the discomfort. If in temperature is inside the setpoint temperature band, 
        then we have no discomfort. If it is beyond the band, then we have a linear discomfort as a function of the 
        distance from the closest setpoint. The expected discomfort (where we multiply by probability of occupation) is
        handled in the objective."""
        for zone in range(self.numZones):
            for time in range(self.numTimesSteps):
                self.model.addConstr(self.discomfort[zone][time] >= (self.inTemperature - self.temperatureHighSet))
                self.model.addConstr(self.discomfort[zone][time] >= (self.temperatureLowSet - self.inTemperature))
                self.model.addConstr(self.discomfort[zone][time] >= 0)

    def set_heating_consumption(self):
        """Set the consumption for heating/cooling for every zone at every time step. Needs to be done because
        we can have negative valued actions."""
        for z in range(self.numZones):
            for t in range(self.numTimesSteps):
                # using the abs value trick. if we are cooling then
                # self.action < 0 and -self.action*const > self.action*const. self.action has units of power.
                self.model.addConstr(
                    self.totalConsumption[z][t] >= -self.action[z][t] * self.deltaTime)
                self.model.addConstr(
                    self.heatingConsumption[z][t] >= self.action[z][t] * self.deltaTime)

    def set_total_consumption(self):
        """Set consumption for the whole building on time-step level. Sets energy quantities."""
        Cons_C = [sum(self.heatingConsumption[:, t]) for t in self.numTimesSteps]  # TODO might not work like this.
        for t in range(self.numTimesSteps):
            # setting totalConsumption[0] to min of (0, Cons_C(t) - R'_C,t)
            self.model.addConstr(self.totalConsumption[t][0] <= 0)
            self.model.addConstr(self.totalConsumption[t][0] <= Cons_C[t] - sum(
                self.powerModel[:, t]))  # assuming sum works as intended.

            # setting totalConsumption[1] to max of (0, Cons_C(t) - R'_C,t)
            self.model.addConstr(self.totalConsumption[t][1] >= 0)
            self.model.addConstr(self.totalConsumption[t][1] >= Cons_C[t] - sum(
                self.powerModel[:, t]))  # assuming sum works as intended.

    def set_peak_charge(self):
        """Sets the peak demand consumption over all zones and all times in the given time frame.
         For any further computation with power, just divide by self.deltaTime."""
        self.model.addConstr(self.peakCharge >= 0)  # added to make sure we never go below 0 and we are only charged.
        self.model.addConstr(self.peakCharge >= self.lastPeakDemand)  # Can't get lower than the last peak consumption.
        # TODO check if right. had misconception
        for t in range(self.numTimesSteps):
            self.model.addConstr(self.peakCharge >= self.totalConsumption[t][1])

    def set_temperature_in(self):
        """Set the temperatureIn in self.model for the linear program as it depends on both self.heat and self.cool.
        Formula: $$$T^{in}(zone, time) = T^{in}(zone, 0)*(\prod_{i=0}^{t-1}\gamma^{time}(zone)) + 
                    \sum_{i=0}^{time-1} \epsilon(zone, i)* \prod_{k=i+1}^{t-1}\gamma(zone, k)$$$
        where $$$\epsilon(zone, time) = (self.action(zone, time) + 
                self.leakageRate(zone, time)*T^{out}(zone, time))*self.deltaTime$$$
        and where $$$\gamma(zone, time) = (1-self.leakageRate(zone,time)) * self.deltaTime$$$"""

        def get_gamma(zone, time):
            return 1 - self.leakageRate[zone][time] * self.deltaTime

        def get_epsilon(zone, time):
            # self.action already includes the power to be used.
            return (self.action[zone][time] +
                    self.leakageRate[zone][time] * self.outTemperature[zone][time]) * self.deltaTime

        # stores the last epsilon and gamma values so i don't have to recompute them
        last_gamma_temperature = np.array([self.inTemperature[z][0] * get_gamma(z, 0) for z in range(self.numZones)])
        last_epsilon_gamma_sum = np.array([get_epsilon(z, 0) for z in range(self.numZones)])

        for z in range(self.numZones):
            for t in range(1, self.numTimesSteps):
                self.model.addConstr(self.inTemperature[z][t] ==
                                     last_epsilon_gamma_sum[z] + last_gamma_temperature[z])
                # setting the terms for the next constraint. Follows naturally from recursive form from the paper
                # "AEC of Electricity-based Space Heating Systems".
                last_epsilon_gamma_sum[z] = last_epsilon_gamma_sum[z] * get_gamma(z, t) + get_epsilon(z, t)
                last_gamma_temperature[z] *= get_gamma(z, t)


if __name__ == "__main__":
    cfg = get_config()
    LP = LinearZones(cfg)

