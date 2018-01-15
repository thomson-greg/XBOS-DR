import numpy as np

from gurobipy import *

from Discomfort import Discomfort
from EnergyConsumption import EnergyConsumption
from Occupation import Occupation
from Safety import Safety
from ThermalModel import ThermalModel



class LinearZones:
    def __init__(self, priceBuy, priceSell, maxPower, numZones, numTimesSteps):
        """
        :param priceBuy: A function of time and HVAC-Zone which returns the cost to buy a kilowatt at the given time and 
        for the given zone. (Matrix zone x time)
        :param priceSell: A function of time and HVAC-Zone which returns the revenue of selling a kilowatt at the given time and 
        for the given zone. (Matrix zone x time)
        :param maxPower: A matrix (zone x time) indicating the maxPower to be used for heating in any zone at any time.
        :param numZones: The number of HVAC zones.
        :param numTimesSteps: The number of times steps from now to Horizon.
        """
        self.priceBuy = priceBuy
        self.priceSell = priceSell
        self.maxPower = maxPower

        self.numZones = numZones
        self.numTimesSteps = numTimesSteps

        self.leakageRate = "TODO" # implement as in paper "AEC of Electricity-base Space Heating Systems"

        # To calculate the energy used.
        self.deltaTime = "TODO"

        # setting the thermal model.
        # TODO will need to update to make it only depend on heating actions and get a matrix
        self.inTemperature = "TODO"

        # Will represent the probability of occupation.
        # is intended to return a matrix where the row represents the ith zone and column the jth time-step.
        self.occupationModel = Occupation()

        # will be used to get the outside temperature.
        # is intended to return a matrix where the row represents the ith zone and column the jth time-step.
        self.outsideTemperatureModel = "TODO"

        # will be used to get the temperature setpoints.
        # is intended to return a matrix where the row represents the ith zone and column the jth time-step.
        self.temperatureSetpointModel = "TODO"

        # The prediction of the power consumption of the building as a numZones x numTimesSteps matrix.
        self.powerModel = "TODO"

        # discounting variable.
        # has dimension numZone x numTimeSteps. Where each row is for a zone and each column for timeStep from now.
        self.discounting = np.ones(self.numZones, self.numTimesSteps)  # TODO Determine which rate

        # the linear programming solver from gurobipy.
        self.model = Model("solver")

        # the variables for the linear program. They control heat or cool. For now we will use binary variables.
        # has dimension numZone x numTimeSteps. Where each row is for a zone and each column for timeStep from now.
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
            vtype=GRB.VAR, name="discomfort_zone{" + str(zone) + "}") for zone in range(self.numZones)])

        # Heating Consumption matrix of LP without powerModel. numZones x numTimeSteps. One entry if for consumption if sold and the other for
        # if bought
        self.heatingConsumption = np.array([
            [
                self.model.addVar(
                vtype=GRB.VAR, name="consumption_zone{" + str(zone) + "}_time{" + str(t) + "}")
                for t in range(self.numTimesSteps)]
                for zone in range(self.numZones)])

        # TODO Fix this. DON'T NEED VARIABLES FOR THIS. ONLY FOR HEATING/COOLING.
        self.totalConsumption = np.array([
            [
                self.model.addVar(
                vtype=GRB.VAR, name="consumption_zone{" + str(zone) + "}_time{" + str(t) + "}")
                for t in range(self.numTimesSteps)]
                for zone in range(self.numZones)])

        # The last peak demands
        self.lastPeakDemand = "TODO" # needs to be filled in.

        # The peak demand charge for the given time period.
        self.peakCharge = self.model.addVar(vtype=GBR.VAR, name="peakDemandCharge")

        # This is the heating efficiency parameter. Should be an array where the index is the corresponding zone.
        self.heatingEff = "TODO"

    def constrainAction(self):
        """Constraints the actions, in case I make them non Binary."""
        for z in range(self.numZones):
            for t in range(self.numTimesSteps):
                self.model.addConstr(self.cool[z][t] >= 0)
                self.model.addConstr(self.cool[z][t] <= 1)

                self.model.addConstr(self.heat[z][t] >= 0)
                self.model.addConstr(self.heat[z][t] <= 1)

                self.model.addConstr(self.heat[z][t] - self.cool[z][t] >= -1)
                self.model.addConstr(self.heat[z][t] - self.cool[z][t] <= 1)




    def setObjective(self):




    def setDiscomfort(self):
        """Set the constraints for the discomfort. We are setting the total discomfort of a zone from now till the
        end of the time horizon, since the objective in the paper has a double sum which can be interchanged."""
        TDiff = self.temperatureIn - self.temperatureSetpoint
        for zone in range(self.numZones):
            # have to set two constraints to work with abs() values. We would actually like to work with the
            # absolute value temperature difference, which is not allowed in LP's. So, we use a trick
            # where we want the variable to be greater or equal to both the difference and negated difference.
            # A picture of the real number line might help to see why this trick works.
            self.model.addConstr(self.discomfort[zone] >= self.occupationModel[zone].dot(TDiff[zone])) # TODO fix the occupation model and how they are multiplied
            self.model.addConstr(
                self.discomfort[zone] >= -self.occupationModel[zone].dot(TDiff[zone]))  # TODO fix the occupation model and how they are multiplied

    def setHeatingConsumption(self):
        """Set the consumption for heating/cooling for every zone at every time step. """
        for z in range(self.numZones):
            for t in range(self.numTimesSteps):
                # using abs value trick.
                self.model.addConstr(self.heatingConsumption[z][t] >= -self.action[z][t]*self.maxPower[z][t]*self.deltaTime)
                self.model.addConstr(self.heatingConsumption[z][t] >= self.action[z][t]*self.maxPower[z][t]*self.deltaTime)

    def setTotalConsumption(self):
        """Set consumption for the whole building on time-step level."""
        Cons_C = [sum(self.heatingConsumption[:, t]) for t in self.numTimesSteps] # TODO might not work like this.
        for t in range(self.numTimesSteps):
            # setting min of (0, Cons_C(t) - R'_C,t)
            self.model.addConstr(self.heatingConsumption[t][0] <= 0)
            self.model.addConstr(self.heatingConsumption[t][0] <= Cons_C[t] - sum(self.powerModel[:, t])) # assuming sum works as intended.

            # setting max of (0, Cons_C(t) - R'_C,t)
            self.model.addConstr(self.heatingConsumption[t][1] >= 0)
            self.model.addConstr(self.heatingConsumption[t][1] >= Cons_C[t] - sum(self.powerModel[:, t])) # assuming sum works as intended.


    def setPeakCharge(self):
        """Sets the peak demand consumption over all zones and all times in the given time frame. This only set the 
        peak consumption. For any further computation with power, just divide by self.deltaTime."""
        self.model.addConstr(self.peakCharge >= 0) # added to make sure we never go below 0 and we are only charged.
        self.model.addConstr(self.peakCharge >= self.lastPeakDemand) # Can't get lower than the last peak consumption.

        for z in range(self.numZones):
            for t in range(self.numTimesSteps):
                # TODO Check if this is how we want to model the exchange.
                self.model.addConstr(self.peakCharge >= self.heatingConsumption[z][t] - self.powerModel[z][t])


    def setTemperatureIn(self):
        """Set the temperatureIn in self.model for the linear program as it depends on both self.heat and self.cool."""
        for t in range(self.numTimesSteps):
            for z in range(self.numZones):



    def setTemperatureSetpoint(self):
        self.temperatureSetpoint = "TODO"


