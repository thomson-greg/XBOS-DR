import datetime, pytz
from xbos import get_client
import yaml
import Utils
import pickle


def baseline(data, policy_array, prices_array, zones, popts, kwh):

	for zone in zones:
		OPs = []  # [i[0] for i in return_dict["occupancy"]]
		Tins = []  # [i for i in return_dict["temperature"]]
		Policy = []  # [i for i in return_dict["action"]]
		TinsUP = []  # [i for i in return_dict["cooling_stp"]]
		TinsDOWN = []  # [i for i in return_dict["heating_stp"]]
		Costs = []  # [i for i in return_dict["cost"]]#[sum(return_dict["cost"][:i]) for i in range(1, len(return_dict["cost"])+1)]
		Prices = []  # [i for i in return_dict["price"]]
		Discomforts = []  # [i for i in return_dict["discomfort"]]

		tnext = data[zone]["Tin"][0]

		for i, policy in enumerate(policy_array):
			STPH = policy[1]
			STPL = policy[0]
			price = prices_array[i]
			tin = tnext
			tout = data[zone]["Tout"][i]
			occ = data[zone]["Occ"][i]
			action = Utils.action(STPH, STPL, tin)
			cost = Utils.cost(action, price, *kwh)
			discomfort = Utils.discomfort(STPH, STPL, tin, occ)

			other_zones = []
			for z in [z for z in zones if z != zone]:
				other_zones.append(data[z]["Tin"][i])

			tnext = Utils.T_next([tin, action, tout, 1, other_zones], *popts)

			OPs.append(occ)
			Tins.append(tin)
			Policy.append(action)
			TinsUP.append(STPH)
			TinsDOWN.append(STPL)
			Costs.append(cost)
			Prices.append(price)
			Discomforts.append(discomfort)

		return_dict = {}
		return_dict["occupancy"] = OPs
		return_dict["discomfort"] = Discomforts
		return_dict["cost"] = Costs
		return_dict["temperature"] = Tins
		return_dict["action"] = Policy
		return_dict["price"] = Prices
		return_dict["heating_stp"] = TinsDOWN
		return_dict["cooling_stp"] = TinsUP
		with open( zone +'_b.pckl', 'wb') as fp:
			pickle.dump(return_dict, fp)

def reality(data, policy_array, prices_array, zones, kwh):

	for zone in zones:
		OPs = []  # [i[0] for i in return_dict["occupancy"]]
		Tins = []  # [i for i in return_dict["temperature"]]
		Policy = []  # [i for i in return_dict["action"]]
		TinsUP = []  # [i for i in return_dict["cooling_stp"]]
		TinsDOWN = []  # [i for i in return_dict["heating_stp"]]
		Costs = []  # [i for i in return_dict["cost"]]#[sum(return_dict["cost"][:i]) for i in range(1, len(return_dict["cost"])+1)]
		Prices = []  # [i for i in return_dict["price"]]
		Discomforts = []  # [i for i in return_dict["discomfort"]]


		for i, policy in enumerate(policy_array):
			STPH = policy[1]
			STPL = policy[0]
			price = prices_array[i]
			tin = data[zone]["Tin"][i]
			occ = data[zone]["Occ"][i]
			action = Utils.action(STPH, STPL, tin)
			cost = Utils.cost(action, price, *kwh)
			discomfort = Utils.discomfort(STPH, STPL, tin, occ)

			OPs.append(occ)
			Tins.append(tin)
			Policy.append(action)
			TinsUP.append(STPH)
			TinsDOWN.append(STPL)
			Costs.append(cost)
			Prices.append(price)
			Discomforts.append(discomfort)

		return_dict = {}
		return_dict["occupancy"] = OPs
		return_dict["discomfort"] = Discomforts
		return_dict["cost"] = Costs
		return_dict["temperature"] = Tins
		return_dict["action"] = Policy
		return_dict["price"] = Prices
		return_dict["heating_stp"] = TinsDOWN
		return_dict["cooling_stp"] = TinsUP
		with open( zone +'_r.pckl', 'wb') as fp:
			pickle.dump(return_dict, fp)

def relive(data, policy_array, prices_array, zones, popts, kwh):
	for zone in zones:
		OPs = []  # [i[0] for i in return_dict["occupancy"]]
		Tins = []  # [i for i in return_dict["temperature"]]
		Policy = []  # [i for i in return_dict["action"]]
		TinsUP = []  # [i for i in return_dict["cooling_stp"]]
		TinsDOWN = []  # [i for i in return_dict["heating_stp"]]
		Costs = []  # [i for i in return_dict["cost"]]#[sum(return_dict["cost"][:i]) for i in range(1, len(return_dict["cost"])+1)]
		Prices = []  # [i for i in return_dict["price"]]
		Discomforts = []  # [i for i in return_dict["discomfort"]]

		tnext = data[zone]["Tin"][0]

		for i, policy in enumerate(policy_array):
			STPH = policy[1]
			STPL = policy[0]
			price = prices_array[i]
			tin = tnext
			tout = data[zone]["Tout"][i]
			occ = data[zone]["Occ"][i]
			action = data[zone]["State"][i]
			cost = Utils.cost(action, price, *kwh)
			discomfort = Utils.discomfort(STPH, STPL, tin, occ)

			other_zones = []
			for z in [z for z in zones if z != zone]:
				other_zones.append(data[z]["Tin"][i])

			tnext = Utils.T_next([tin, action, tout, 1, other_zones], *popts)

			OPs.append(occ)
			Tins.append(tin)
			Policy.append(action)
			TinsUP.append(STPH)
			TinsDOWN.append(STPL)
			Costs.append(cost)
			Prices.append(price)
			Discomforts.append(discomfort)

		return_dict = {}
		return_dict["occupancy"] = OPs
		return_dict["discomfort"] = Discomforts
		return_dict["cost"] = Costs
		return_dict["temperature"] = Tins
		return_dict["action"] = Policy
		return_dict["price"] = Prices
		return_dict["heating_stp"] = TinsDOWN
		return_dict["cooling_stp"] = TinsUP
		with open( zone +'_rl.pckl', 'wb') as fp:
			pickle.dump(return_dict, fp)

with open("cost_config.yml", 'r') as ymlfile:
	cfg = yaml.load(ymlfile)

if cfg["Server"]:
	cli = get_client(agent=cfg["Agent_IP"], entity=cfg["Entity_File"])
else:
	cli = get_client()

zones = cfg["Zones"]

now = datetime.datetime.strptime(cfg["Start_Date"], '%Y-%m-%d %H:%M:%S').replace(tzinfo=pytz.timezone(cfg["Pytz_Timezone"]))
policy_array = Utils.policy_to_minute(cfg["Setpoint"], now)
prices_array = Utils.prices_per_minute(cfg["Pricing"][cfg["Pricing"]["Energy_Rates"]], now)
data = Utils.data_fetch(cfg, cli, zones)


"""
data = Utils.data_fetch(cfg, cli)
with open('temp.pckl', 'wb') as fp:
	pickle.dump(data, fp)
"""

popts = cfg["popts"]
kwh = cfg["kwh"]
baseline(data, policy_array, prices_array, zones, popts, kwh)
reality(data, policy_array, prices_array, zones, kwh)
relive(data, policy_array, prices_array, zones,popts, kwh)



