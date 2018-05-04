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

		def in_between(now, start, end):
			if start < end:  # e.g., "07:00-23:00"
				return start <= now < end
			elif end < start:  # e.g., "23:00-07:00"
				return start <= now or now < end
			else:  # start == end
				return True  # consider it 24 hour interval


		now_time = (self.temp_now + timedelta(minutes=node_time)).time()
		for setpoint in self.setpoints:
			if in_between(now_time, datetime.time(int(setpoint[0].split(":")[0]), int(setpoint[0].split(":")[1])),
						  datetime.time(int(setpoint[1].split(":")[0]), int(setpoint[1].split(":")[1]))):
				heating_setpoint = setpoint[2]
				cooling_setpoint = setpoint[3]
				break

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
	disc = Discomfort([["00:00", "07:00", 62., 85.], ["07:00", "18:00", 70., 76.], ["18:00", "00:00", 62., 85.]])
	print disc.disc(60, 0.8, 0, 15)