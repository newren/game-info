#!/usr/bin/env python

from collections import defaultdict
from datetime import datetime
import re
import sys
import time

import matplotlib.pyplot as plt
import numpy as np

def convert_to_epoch(datestring):
  year = '2015 ' if datestring.startswith('Jan') else '2014 '
  return time.mktime(datetime.strptime(year+datestring, '%Y %b %d %H:%M:%S').timetuple())

for_whom = sys.argv[1] if len(sys.argv) > 1 else None
remaining = defaultdict(list)
x = []
y = []
with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  for line in f:
    if 'reaches next level' in line:
      m = re.match(r'([A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2}) <idlerpg>\s*([A-Za-z]*) reaches next level in (\d+) days?, (\d{2}):(\d{2}):(\d{2})', line)
      if not m:
        break
      date, who, days, hours, minutes, seconds = m.groups()
      if for_whom and who != for_whom:
        continue
      remnant = int(days)*86400+int(hours)*3600+int(minutes)*60+int(seconds)
      if remnant < 86400:
        continue
      remaining[who].append((convert_to_epoch(date), remnant))
    elif 'has attained' in line:
      m = re.match(r'([A-Z][a-z]{2} \d{2} \d{2}:\d{2}:\d{2}) <idlerpg>\s*([A-Za-z]*),.*, has attained', line)
      if not m:
        raise SystemExit("BLAH: "+line)
      date, who = m.groups()
      if for_whom and who != for_whom:
        continue
      finished = convert_to_epoch(date)
      for milepost,timeleft in remaining[who]:
        took = finished-milepost
        assert took > 0
        #x.append(took)
        #y.append(timeleft)
        x.append(timeleft)
        y.append(timeleft/took)
      remaining[who] = []

plt.figure()
plt.scatter(x,y)
#plt.plot(x,x)
plt.plot(np.array(x),[1.0 for elem in y])
plt.tight_layout()

xvalues = np.arange(min(x), max(x)+1, (max(x)-min(x))/10)
xlabels = ['{:4.1f}'.format(xv/86400.0) for xv in xvalues]
plt.xticks(xvalues, xlabels)

#yvalues = np.arange(min(y), max(y)+1, (max(y)-min(y))/10)
#ylabels = ['{:4.1f}'.format(y/86400.0) for y in yvalues]
#plt.yticks(yvalues, ylabels)
#
#plt.xlabel('Actual time, days')
#plt.ylabel('Projected time')

plt.xlabel('Projected Time')
plt.ylabel('Project/Actual Time')
plt.title('Projected vs Actual TTL')

m,b = np.polyfit(x, y, 1)
plt.plot(x, m*np.array(x)+b, 'r')
plt.tight_layout()
#print("{:20s}: {:6.3f}x + {:5.3f}".format(for_whom, m*86400,b))

A = np.vstack([x]).T
y_minus_1 = [i-1.0 for i in y]
m = np.linalg.lstsq(A, y_minus_1)[0][0]
print("{:20s}: {:6.3f}x + 1".format(for_whom, 86400*m))
plt.plot(x, m*np.array(x)+1, 'g')

#plt.show()
