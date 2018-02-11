import sys
import yaml

try:
    yaml_filename = sys.argv[1]
except:
    sys.exit("Please specify the configuration file as: python2 controller.py config_file.yaml")

with open(yaml_filename, 'r') as ymlfile:
    cfg = yaml.load(ymlfile)

from Advise import Advise

adv = Advise(cfg)
action, temp = adv.advise()

print action
print temp
