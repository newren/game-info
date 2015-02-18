#!/usr/bin/env python

from datetime import datetime, timedelta
import re
import time

def convert_to_epoch(timestring):
  timetuple = datetime.strptime(timestring, '%Y-%m-%d %H:%M:%S').timetuple()
  return time.mktime(timetuple)

alltimes = []
with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  begin = None
  for line in f:
    # Check for notices about time to next level
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*Participants must first reach", line)
    if m:
      begin = m.group(1)
      continue

    # Check for notices about time to next level
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*completed their journey", line)
    if not m:
      continue

    end = m.group(1)

    # Given that we were told the time to the next level and know when we
    # were told that, determine how much time currently remains until that
    # character reaches the next level
    beg_epoch = convert_to_epoch(begin)
    end_epoch = convert_to_epoch(end)
    alltimes.append(end_epoch-beg_epoch)
    begin = None

import numpy

print('Quest times, in seconds:')
print('min/mean/max = {} {} {}'.format(numpy.min(alltimes), numpy.mean(alltimes), numpy.max(alltimes)))
print('median = {}'.format(numpy.median(alltimes)))
print('stddev = {}'.format(numpy.std(alltimes)))
