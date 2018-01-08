import time, os, datetime, pytz
import urllib2
import json

def weather_fetch():
	myweather = json.load(urllib2.urlopen("http://api.wunderground.com/api/147c8cec00fcd16d/hourly/q/pws:KCABERKE67.json"))
	weather_file = open("weather.txt", "a")
	weather_file.write("\n"+datetime.datetime.now(pytz.timezone("America/Los_Angeles")).strftime('%Y-%m-%d %H:%M:%S') + " PST\n")
	weather_file.write("epoch;temp;condition;wspd;wdir;wdir_degrees;humidity\n")
	weather_file.close()


	for data in myweather['hourly_forecast']:
		epoch = data["FCTTIME"]["epoch"]
		temp = data["temp"]["english"]
		condition = data["condition"]
		wspd = data["wspd"]["english"]
		wdir = data["wdir"]["dir"]
		wdir_degrees = data["wdir"]["degrees"]
		humidity = data["humidity"]

		weather_file = open("weather.txt", "a")
		weather_file.write(str(epoch)+";"+str(temp)+";"+str(condition)+";"+str(wspd)+";"\
						   +str(wdir)+";"+str(wdir_degrees)+";"+str(humidity)+"\n")
		weather_file.close()


if __name__ == '__main__':
	if not os.path.exists("weather.txt"):
		weather_file = open("weather.txt", "w")
		weather_file.close()
	
	starttime= time.time()
	while True:
		weather_fetch()
		time.sleep(60.*60.*3. - ((time.time() - starttime) % (60.*60.*3.)))
