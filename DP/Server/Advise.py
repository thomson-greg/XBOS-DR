import networkx as nx
import numpy as np
import yaml

from ThermalModel import ThermalModel
from Occupancy import Occupancy
from Discomfort import Discomfort
from Safety import Safety
from EnergyConsumption import EnergyConsumption
import datetime
import pytz

from utils import plotly_figure
import plotly.offline as py



class Node:
	"""
	# this is a Node of the graph for the shortest path
	"""
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


class EVA:
	def __init__(self, current_time, l, pred_window, interval, discomfort,
				 thermal, occupancy, safety, energy, root=Node([75], 0), noZones=1):
		"""
		Constructor of the Evaluation Class
		The EVA class contains the shortest path algorithm and its utility functions
		Parameters
		----------
		current_time : datetime.datetime
		l : float (0 - 1)
		pred_window : int
		interval : int
		discomfort : Discomfort
		thermal : ThermalModel
		occupancy : Occupancy
		safety : Safety
		energy : EnergyConsumption
		root : Node
		noZones : int
		"""
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

	def get_real_time(self, node_time):
		"""
		util function that converts from relevant time to real time
		Parameters
		----------
		node_time : int

		Returns
		-------
		int
		"""
		return self.current_time + datetime.timedelta(minutes=node_time)

	# the shortest path algorithm
	def shortest_path(self, from_node):
		"""
		Creates the graph using DFS and calculates the shortest path

		Parameters
		----------
		from_node : node being examined right now
		"""

		# add the final nodes when algorithm goes past the target prediction time
		if self.get_real_time(from_node.time) >= self.target:
			self.g.add_node(from_node, usage_cost=0, best_action=None)
			return

		# create the action set (0 is for do nothing, 1 is for cooling, 2 is for heating)
		action_set = self.safety.safety_actions(from_node.temps)
		
		# iterate for each available action
		for action in action_set:
			
			# predict temperature and energy cost of action
			new_temperature = []
			consumption = []
			for i in range(self.noZones):
				new_temperature.append(self.th.next_temperature(from_node.temps[i],
																action[i],
																from_node.time/self.interval, zone=i))
				consumption.append(self.energy.calc_cost(action[i], from_node.time/self.interval))
				
			if self.safety.safety_check(new_temperature) and len(action_set) > 1:
				continue

			# create the node that describes the predicted data
			new_node = Node(
				temps=new_temperature,
				time=from_node.time + self.interval
			)

			# calculate interval discomfort
			discomfort = [0] * self.noZones

			for i in range(self.noZones):
				discomfort[i] = self.disc.disc((from_node.temps[i] + new_temperature[i])/2.,
											   self.occ.occ(from_node.time/self.interval),
											   from_node.time,
											   self.interval)

			# create node if the new node is not already in graph
			# recursively run shortest path for the new node
			if new_node not in self.g:
				self.g.add_node(new_node, usage_cost=np.inf, best_action=None)
				self.shortest_path(new_node)

			# need to find a way to get the consumption and discomfort values between [0,1]
			interval_overall_cost = ((1 - self.l) * (sum(consumption))) + (self.l * (sum(discomfort)))

			this_path_cost = self.g.node[new_node]['usage_cost'] + interval_overall_cost

			# add the edge connecting this state to the previous
			self.g.add_edge(from_node, new_node, action=action)

			# choose the shortest path
			if this_path_cost <= self.g.node[from_node]['usage_cost']:
				if this_path_cost == self.g.node[from_node]['usage_cost'] and self.g.node[from_node]['best_action'] == '0':
					continue
				self.g.add_node(from_node, best_action=new_node, usage_cost=this_path_cost)


	def reconstruct_path(self, graph=None):
		"""
		Util function that reconstructs the best action path
		Parameters
		----------
		graph : networkx graph

		Returns
		-------
		List
		"""
		if graph is None:
			graph = self.g

		cur = self.root
		path = [cur]

		while graph.node[cur]['best_action'] is not None:
			cur = graph.node[cur]['best_action']
			path.append(cur)

		return path

class Advise:
	# the Advise class initializes all the Models and runs the shortest path algorithm
	def __init__(self, current_time, occupancy_data, thermal_data, weather_predictions,
				 prices, lamda, interval, predictions_hours, plot_bool,
				 max_safe_temp, min_safe_temp, heating_cons, cooling_cons, max_actions,
				 thermal_precision, occ_obs_len_addition, setpoints):

		self.plot =plot_bool
		self.current_time = current_time
		
		# initialize all models
		disc = Discomfort(setpoints, now=self.current_time)
		th = ThermalModel(thermal_data, weather_predictions, now=self.current_time, interval_length=interval,
						  max_actions=max_actions, thermal_precision=thermal_precision)
		occ = Occupancy(occupancy_data, interval, predictions_hours, occ_obs_len_addition)
		safety = Safety(max_temperature=max_safe_temp, min_temperature=min_safe_temp, noZones=1)
		energy = EnergyConsumption(prices, interval, now=self.current_time,
								   heat=heating_cons, cool=cooling_cons)
		
		Zones_Starting_Temps = [thermal_data['t_next'][-1]]
		self.root = Node(Zones_Starting_Temps, 0)

		# initialize the shortest path model
		self.advise_unit = EVA(
			current_time=self.current_time,
			l = lamda,
			pred_window=predictions_hours * 60 / interval,
			interval= interval,
			discomfort=disc,
			thermal=th,
			occupancy=occ,
			safety=safety,
			energy=energy,
			root=self.root,
		)	

	def advise(self):
		"""
		function that runs the shortest path algorithm and returns the action produced by the mpc
		Returns
		-------
		String
		"""
		self.advise_unit.shortest_path(self.root)
		path = self.advise_unit.reconstruct_path()
		action = self.advise_unit.g[path[0]][path[1]]['action']

		if self.plot:
			fig = plotly_figure(self.advise_unit.g, path=path)
			py.plot(fig)

		return action

if __name__ == '__main__':
	from DataManager import DataManager
	from xbos import get_client
	with open("config_file.yml", 'r') as ymlfile:
		cfg = yaml.load(ymlfile)

	with open("ZoneConfigs/CentralZone.yml", 'r') as ymlfile:
		advise_cfg = yaml.load(ymlfile)

	if cfg["Server"]:
		c = get_client(agent=cfg["Agent_IP"], entity=cfg["Entity_File"])
	else:
		c = get_client()

	dm = DataManager(cfg, advise_cfg, c)

	adv = Advise(datetime.datetime.utcnow().replace(tzinfo=pytz.utc).astimezone(tz=pytz.timezone("America/Los_Angeles")),
				 dm.preprocess_occ(), dm.preprocess_therm(), dm.weather_fetch(),
				 dm.prices(), 0.995, 15, 1, False,
				 87, 55, 0.075, 1.25, 400, 400., 4,
				 dm.building_setpoints())

	print adv.advise()
	