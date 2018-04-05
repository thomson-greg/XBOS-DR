import networkx as nx
import numpy as np

from ThermalModel import ThermalModel
from Occupancy import Occupancy
from Discomfort import Discomfort
from Safety import Safety
from EnergyConsumption import EnergyConsumption
import datetime
import pytz

from utils import plotly_figure
import plotly.offline as py

#this is a Node of the graph
class Node:
	def __init__(self, temps, time):
		self.temps = temps
		self.time = time

	def __hash__(self):
		return hash((' '.join(str(e) for e in self.temps), self.time))

	def __eq__(self, other):
		return isinstance(other, self.__class__) \
				and self.temps == other.temps \
				and self.time == other.time

	def __repr__(self):
		return "{0}-{1}".format(self.time, self.temps)

# The EVA class contains the shortest path algorithm and its utility functions 
class EVA:
	def __init__(self, current_time, l, pred_window, interval,
				root=Node([75], 0), noZones=1, discomfort=None,
				thermal=None, occupancy=None, safety=None, energy=None):

		# initialize class constants
		self.noZones = noZones
		self.current_time = current_time
		self.l = l
		self.g = nx.DiGraph()
		self.interval = interval
		self.root = root
		self.target = self.get_real_time(pred_window * interval)

		self.billing_period = 30 * 24 * 60 / interval  # 30 days

		self.disc = discomfort
		self.th = thermal
		self.occ = occupancy
		self.safety = safety
		self.energy = energy

		self.g.add_node(root, usage_cost=np.inf, best_action=None)

	# util function that convers from integer that converts from relevant time to real time
	def get_real_time(self, node_time):
		return self.current_time + datetime.timedelta(minutes=node_time)

	# the shortest path algorithm
	def shortest_path(self, from_node):
		"""
		Creates the graph using DFS while we determine the best path
		:param from_node: the node we are currently on
		"""

		# add the final nodes when algorithm goes past the target prediction time 
		if self.get_real_time(from_node.time) >= self.target:
			self.g.add_node(from_node, usage_cost=0, best_action=None)
			return

		#create the action set (0 is for do nothing, 1 is for cooling, 2 is for heating)
		action_set = self.safety.safety_actions(from_node.temps)
		
		#iterate for each available action
		for action in action_set:
			
			# predict temperature and energy consumption of action
			new_temperature = []
			consumption = []
			for i in range(self.noZones):
				new_temperature.append(self.th.next_temperature(from_node.temps[i], action[i], from_node.time/self.interval, zone=i))
				consumption.append(self.energy.calc_cost(action[i], from_node.time/self.interval))
				
			if self.safety.safety_check(new_temperature) and len(action_set) > 1:
				continue

			# create the node that describes the predicted data
			new_node = Node(
				temps=new_temperature,
				time=from_node.time + self.interval
			)

			#calculate interval discomfort
			discomfort = [0] * self.noZones

			for i in range(self.noZones):
				discomfort[i] = self.disc.disc((from_node.temps[i] + new_temperature[i])/2., self.occ.occ(from_node.time/self.interval), from_node.time, self.interval)

			# create node if the new node is not allready in graph
			# recursively run shortest path for the new node
			if new_node not in self.g:
				self.g.add_node(new_node, usage_cost=np.inf, best_action=None)
				self.shortest_path(new_node)

			#need to find a way to get the consumption and discomfort values between [0,1]
			interval_overall_cost = ((1 - self.l) * (sum(consumption))) + (self.l * (sum(discomfort)))

			this_path_cost = self.g.node[new_node]['usage_cost'] + interval_overall_cost

			# add the edge connecting this state to the previous
			self.g.add_edge(from_node, new_node, action=action)

			# choose the shortest path
			if this_path_cost <= self.g.node[from_node]['usage_cost']:
				if this_path_cost == self.g.node[from_node]['usage_cost'] and self.g.node[from_node]['best_action'] == '0':
					continue
				self.g.add_node(from_node, best_action=new_node, usage_cost=this_path_cost)

	# util function that recostructs the best action path
	def reconstruct_path(self, graph=None):
		if graph is None:
			graph = self.g

		cur = self.root
		path = [cur]

		while graph.node[cur]['best_action'] is not None:
			cur = graph.node[cur]['best_action']
			path.append(cur)

		return path

# the Advise class initializes all the 
class Advise:
	def __init__(self, current_time, starting_temp, occupancy_data, thermal_data, weather_predictions,
				 energy_cost_schedule, lamda, interval, predictions_hours, plot_bool,
				 max_safe_temp, min_safe_temp, heating_cons, cooling_cons):

		# initialize constants

		Lambda = lamda
		Interval_Length = interval  # in minutes
		Hours = predictions_hours
		Intervals = Hours * 60 / Interval_Length
		No_Of_Zones = 1 #ignore this
		Maximum_Safety_Temp, Minimum_Safety_Temp = max_safe_temp, min_safe_temp
		Heating_Consumption = heating_cons  # watts
		Cooling_Consumption = cooling_cons  # watts
		

		self.plot =plot_bool
		self.current_time = current_time
		# collect data for the thermal model
		
		# initialize all models
		disc = Discomfort(now=self.current_time)
		th = ThermalModel(thermal_data, weather_predictions, now=self.current_time)
		occ = Occupancy(occupancy_data)
		safety = Safety(max_temperature=Maximum_Safety_Temp, min_temperature=Minimum_Safety_Temp, noZones=No_Of_Zones)
		energy = EnergyConsumption(energy_cost_schedule, now=self.current_time, heat=Heating_Consumption, cool=Cooling_Consumption)
		
		Zones_Starting_Temps = [thermal_data['t_next'][-1]]
		self.root = Node(Zones_Starting_Temps, 0)

		# initialize the shortest path model
		self.advise_unit = EVA(
			current_time=self.current_time,
			l=Lambda,
			pred_window=Intervals,
			interval= Interval_Length,
			root=self.root,
			noZones=No_Of_Zones,
			discomfort=disc,
			thermal=th,
			occupancy=occ,
			safety=safety,
			energy=energy
		)	

	# function that runs the shortest path algorithm and returns the action produced by the mpc
	def advise(self):
		self.advise_unit.shortest_path(self.root)
		path = self.advise_unit.reconstruct_path()
		action = self.advise_unit.g[path[0]][path[1]]['action']
		#max_demand = self.advise_unit.g.node[path[0]]['max_demand']

		if self.plot:
			fig = plotly_figure(self.advise_unit.g, path=path)
			py.plot(fig)

		return action

if __name__ == '__main__':
	from DataManager import DataManager
	dm = DataManager("config_south.yml")

	adv = Advise(datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles")),
				 60, dm.preprocess_occ(), dm.preprocess_therm(), dm.weather_fetch(),
				 "winter_rates", 0.99995, 15, 1, True,
				 87, 55, 0.075, 1.25)

	print adv.advise()