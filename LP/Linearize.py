import numpy as np

from gurobipy import *

from Occupation import Occupation


class LinearZones:
    def __init__(self, priceBuy, priceSell, maxPower, numZones, numTimesSteps, total_time, peak_cost):
        """
        :param priceBuy: A function of time and HVAC-Zone which returns the cost to buy a kilowatt at the given time and 
        for the given zone. (Matrix zone x time)
        :param priceSell: A function of time and HVAC-Zone which returns the revenue of selling a kilowatt at the given time and 
        for the given zone. (Matrix zone x time)
        :param maxPower: A matrix (zone x time) indicating the maxPower to be used for heating in any zone at any time.
        :param numZones: The number of HVAC zones.
        :param numTimesSteps: The number of times steps from now to Horizon.
        :param total_time: The total time in minutes of the timeframe.
        :param peak_cost: The cost at which the peak consumption is priced. 
        """
        self.priceBuy = priceBuy
        self.priceSell = priceSell
        self.maxPower = maxPower
        self.numZones = numZones
        self.numTimesSteps = numTimesSteps
        self.peakCost = peak_cost

        self.leakageRate = np.ones(self.numZones)  # implement as in paper "AEC of Electricity-base Space Heating Systems" for each zone.

        # To calculate energy from power.
        self.deltaTime = float(total_time)/self.numTimesSteps

        # This is the heating efficiency parameter. Should be an array where the index is the corresponding zone.
        self.heatingEff = np.ones(self.numZones)  #  "TODO"

        # Will represent the probability of occupation.
        # is intended to return a matrix where the row represents the ith zone and column the jth time-step.
        self.occupationModel = Occupation()

        # will be used to get the outside temperature.
        # is intended to return a matrix where the row represents the ith zone and column the jth time-step.
        self.outTemperature = "TODO"

        # will be used to get the temperature setpoints.
        # A matrix (numZones x numTimesSteps)
        self.temperatureSetpoint = "TODO"

        # The prediction of the power consumption of the building as a numZones x numTimesSteps matrix.
        self.powerModel = "TODO"

        # TODO Look into the weighing of each objective term.
        # discounting variable.
        # array numTimeSteps.
        self.discounting = np.ones(self.numTimesSteps)  # TODO Determine which rate just for zones.

        # comfort and cost balancing
        self.comfortBalancing = np.ones(self.numZones)  # TODO determine how we weigh the discomfort to cost balancing.

        # the linear programming solver from gurobipy.
        self.model = Model("solver")

        # setting the thermal model. Matrix (zones x timeSteps)
        self.inTemperature = np.array([[
            self.model.addVar("Temperature_in_zone{" + str(z) + "}_time{" + str(t) + "}") for t in range(self.numTimesSteps)
        ] for z in range(self.numZones)])

        # the variables for the linear program. They control heat or cool. For now we will use binary variables.
        # has dimension numZone x numTimeSteps.
        self.heat = np.array([[self.model.addVar(
            vtype=GRB.BINARY, name="heat_zone{"+str(zone)+"}_time{" + str(time) +"}") for time in range(self.numTimesSteps)]
            for zone in range(self.numZones)])

        self.cool = np.array([[self.model.addVar(
            vtype=GRB.BINARY, name="cool_zone{"+str(zone)+"}_time{" + str(time) +"}") for time in range(self.numTimesSteps)]
            for zone in range(self.numZones)])

        # This will be the eventual action to be taken. TODO Do i need a loop?
        self.action = self.heat - self.cool

        # Discomfort array of the linear program where index is the zone. Used for objective.
        self.discomfort = np.array([self.model.addVar(
            name="discomfort_zone{" + str(zone) + "}") for zone in range(self.numZones)])

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


        # The last peak demands
        self.lastPeakDemand = 0  # TODO needs to be filled in.

        # The peak demand charge for the given time period.
        self.peakCharge = self.model.addVar(name="peakDemandCharge")

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

    def set_objective(self):
        obj = LinExpr()
        obj += self.discomfort.dot(self.comfortBalancing)  # add the discomfort term
        obj += self.totalConsumption
        temp_rev = self.totalConsumption[:, 0] * self.priceSell  # setting the revenue we might make.
        temp_cost = self.totalConsumption[:, 1] * self.priceBuy  # setting the cost we might have to pay.
        obj += temp_rev.dot(self.discounting) + temp_cost.dot(self.discounting)  # cost term added
        obj += self.peakCharge/self.deltaTime * self.peakCost * 1/self.numTimesSteps  # add demand charge term from paper "Smart Charge"

        self.model.setObjective(obj, GRB.MAXIMIZE)

    def set_discomfort(self):
        """Set the constraints for the discomfort. We are setting the total discomfort of a zone from now till the
        end of the time horizon, since the objective in the paper has a double sum which can be interchanged."""
        TDiff = (self.temperatureIn - self.temperatureSetpoint)*self.discounting  # use discounting variable here for discomfort
        for zone in range(self.numZones):
            # have to set two constraints to work with abs() values. We would actually like to work with the
            # absolute value temperature difference, which is not allowed in LP's. So, we use a trick
            # where we want the variable to be greater or equal to both the difference and negated difference.
            # A picture of the real number line might help to see why this trick works.
            self.model.addConstr(self.discomfort[zone] >= self.occupationModel[zone].dot(TDiff[zone])) # TODO fix the occupation model and how they are multiplied
            self.model.addConstr(
                self.discomfort[zone] >= -self.occupationModel[zone].dot(TDiff[zone]))  # TODO fix the occupation model and how they are multiplied

    def set_heating_consumption(self):
        """Set the consumption for heating/cooling for every zone at every time step. Needs to be done because
        we can have negative valued actions."""
        for z in range(self.numZones):
            for t in range(self.numTimesSteps):
                # using abs value trick.
                self.model.addConstr(self.heatingConsumption[z][t] >= -self.action[z][t]*self.maxPower[z][t]*self.deltaTime)
                self.model.addConstr(self.heatingConsumption[z][t] >= self.action[z][t]*self.maxPower[z][t]*self.deltaTime)

    def set_total_consumption(self):
        """Set consumption for the whole building on time-step level. Sets energy quantities."""
        Cons_C = [sum(self.heatingConsumption[:, t]) for t in self.numTimesSteps] # TODO might not work like this.
        for t in range(self.numTimesSteps):
            # setting min of (0, Cons_C(t) - R'_C,t)
            self.model.addConstr(self.heatingConsumption[t][0] <= 0)
            self.model.addConstr(self.heatingConsumption[t][0] <= Cons_C[t] - sum(self.powerModel[:, t])) # assuming sum works as intended.

            # setting max of (0, Cons_C(t) - R'_C,t)
            self.model.addConstr(self.heatingConsumption[t][1] >= 0)
            self.model.addConstr(self.heatingConsumption[t][1] >= Cons_C[t] - sum(self.powerModel[:, t])) # assuming sum works as intended.

    def set_peak_charge(self):
        """Sets the peak demand consumption over all zones and all times in the given time frame.
         For any further computation with power, just divide by self.deltaTime."""
        self.model.addConstr(self.peakCharge >= 0) # added to make sure we never go below 0 and we are only charged.
        self.model.addConstr(self.peakCharge >= self.lastPeakDemand) # Can't get lower than the last peak consumption.

        for z in range(self.numZones):
            for t in range(self.numTimesSteps):
                # TODO Check if this is how we want to model the exchange.
                self.model.addConstr(self.peakCharge >= self.heatingConsumption[z][t] - self.powerModel[z][t])

    def set_temperature_in(self):
        """Set the temperatureIn in self.model for the linear program as it depends on both self.heat and self.cool.
        Formula: $$$T^{in}(zone, time) = T^{in}(zone, 0)*(\prod_{i=0}^{t-1}\gamma^{time}(zone)) + 
                    \sum_{i=0}^{time-1} \epsilon(zone, i)* \prod_{k=i+1}^{t-1}\gamma(zone, k)$$$
        where $$$\epsilon(zone, time) = (self.maxPower(zone, time)*self.action(zone, time) + 
                self.leakageRate(zone, time)*T^{out}(zone, time))*self.deltaTime$$$
        and where $$$\gamma(zone, time) = (1-self.leakageRate(zone,time)) * self.deltaTime$$$"""
        def get_gamma(zone, time):
            return 1 - self.leakageRate[zone][time] * self.deltaTime

        def get_epsilon(zone, time):
            return (self.maxPower[zone][time]*self.action[zone][time] + \
                   self.leakageRate[zone][time]*self.outTemperature[zone][time])*self.deltaTime

        # stores the last epsilon and gamma values so i don't have to recompute them
        last_gamma_temperature = np.array([self.inTemperature[z][0]*get_gamma(z, 0) for z in range(self.numZones)])
        last_epsilon_gamma_sum = np.array([get_epsilon(z, 0) for z in range(self.numZones)])

        for z in range(self.numZones):
            for t in range(1, self.numTimesSteps):
                self.model.addConstr(self.inTemperature[z][t] ==
                                     last_epsilon_gamma_sum[z] + last_gamma_temperature[z])
                # setting the terms for the next constraint. Follows naturally from recursive form from the paper
                # "AEC of Electricity-based Space Heating Systems".
                last_epsilon_gamma_sum[z] = last_epsilon_gamma_sum[z] * get_gamma(z, t) + get_epsilon(z, t)
                last_gamma_temperature[z] *= get_gamma(z, t)


    def setTemperatureSetpoint(self):
        self.temperatureSetpoint = "TODO"


