import datetime, pytz
from datetime import timedelta

class Discomfort:
	def __init__(self, setpoints, now=datetime.datetime.utcnow().replace(tzinfo=pytz.timezone("UTC")).astimezone(tz=pytz.timezone("America/Los_Angeles"))):

		self.setpoints = setpoints
		self.temp_now = now

	def disc(self, t_in, occ, node_time, interval):
		"""
		Calculate discomfort given certain temperature, occupancy prob
		Parameters
		----------
		t_in :
		occ : probability of occupancy
		node_time : minutes after starting time
		interval : interval length

		Returns
		-------

		"""

		heating_setpoint = self.setpoints[node_time/interval][0]
		cooling_setpoint = self.setpoints[node_time/interval][1]

		# check which setpoint is the temperature closer to
		if abs(heating_setpoint - t_in) < abs(cooling_setpoint - t_in):
			discomfort = (heating_setpoint - t_in) ** 2.
		else:
			discomfort = (cooling_setpoint - t_in) ** 2.
		# return 0 if inside setpoints, discomfort*occupancy-probability else
		if t_in > heating_setpoint and t_in < cooling_setpoint:
			return 0
		else:
			return discomfort*occ*interval

if __name__ == '__main__':
	disc = Discomfort([[62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0], [62.0, 85.0]])
	print disc.disc(60, 0.8, 0, 15)