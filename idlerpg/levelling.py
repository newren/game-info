#!/usr/bin/env python

from datetime import datetime, timedelta
import math
import re
import subprocess
import time

def convert_to_epoch(timestring):
  timetuple = datetime.strptime(timestring, '%Y-%m-%d %H:%M:%S').timetuple()
  return time.mktime(timetuple)
def convert_to_duration(days, hours, mins, secs):
  return 86400*int(days) + 3600*int(hours) + 60*int(mins) + int(secs)

level = {}
info = {}
quest_started = None
quest_times = []
now = time.time()

postdate_re="(?P<postdate>[\d-]{10} [\d:]{8}) <idlerpg>\t"
nextlvl_re="[Nn]ext level in (?P<days>\d+) days?, (?P<hours>\d{2}):(?P<mins>\d{2}):(?P<secs>\d{2})"

with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  for line in f:
    # Check for quest starting
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>\s*(.*) have been chosen.*Participants must first reach", line)
    if m:
      quest_started, questers = m.groups()
      
      continue
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>\s*(.*) have been chosen.*Quest to end in (\d+) days?, (\d{2}):(\d{2}):(\d{2})", line)
    if m:
      quest_started, questers, days, hours, mins, secs = m.groups()
      duration = convert_to_duration(days, hours, mins, secs)
      quest_time_left = convert_to_epoch(quest_started)+duration-now
      continue

    # Check for quest ending
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*prudence and self-regard has brought the wrath of the gods upon the realm", line)
    if m:
      quest_started = None
      quest_time_left = None
      questers = None
      continue
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*completed their journey", line)
    if m:
      end = m.group(1)
      beg_epoch = convert_to_epoch(quest_started)
      end_epoch = convert_to_epoch(end)
      quest_times.append(end_epoch-beg_epoch)
      quest_started = None
      quest_time_left = None
      questers = None
      continue
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*have blessed the realm by completing their quest", line)
    if m:
      end = m.group(1)
      quest_started = None
      quest_time_left = None
      questers = None
      continue

    # Check for levelling up
    m = re.search(r'(\S*),.*, has attained level (\d+)', line)
    if m:
      who, lvl = m.groups()
      level[who] = lvl
      continue

    # Check for notices about time to next level
      # Y reaches next level in...
      # Y, the Z, has attained level W! Next level in...
      # Y, the level W Z, is #U! Next level in...
      # Welcome X's new player Y, the Z! Next level in...
      # Y, the level W Z, is now online from nickname X. Next level in...
    m = re.match(postdate_re+r"(?:Welcome.*new player )?(.*?)[', ].*"+nextlvl_re, line)
    if not m:
      continue
    postdate, who, days, hours, mins, secs = m.groups()

    # If we've been told about time to next level, but don't know this
    # person's level yet, just skip this info.
    if who not in level:
      continue

    # Given that we were told the time to the next level and know when we
    # were told that, determine how much time currently remains until that
    # character reaches the next level
    post_epoch = convert_to_epoch(postdate)
    post_delta = convert_to_duration(days, hours, mins, secs)
    now_delta = (post_epoch+post_delta)-now

    # Guess whether the character is online based on time instead of trying
    # to parse "has left" messages (netsplits happen too, and thus I might not
    # get those messages); if the amount of time they have left is positive,
    # just assume they're online.  They're certainly not online if the amount
    # of time left is negative, because idlerpg would have levelled them up.
    online_guess = now_delta > 0 # now-post_epoch < post_delta
    second_guess = now-post_epoch < 2*86400

    info[who] = (level[who], now_delta, post_delta, online_guess)

def time_format(seconds):
  sign = '-' if seconds<0 else ' '
  seconds = -1*seconds if seconds < 0 else seconds
  days = int(seconds/86400)
  seconds = seconds%86400
  hours = int(seconds/3600)
  seconds = seconds%3600
  mins = int(seconds/60)
  seconds = int(seconds%60)
  daystr = sign+str(days)
  return '{:>4s}:{:02d}:{:02d}:{:02d}'.format(sign+str(days),hours,mins,seconds)

def quest_info(started, time_left, quest_times):
  if started:
    if time_left: # Time-based quest
      return "Will end in "+time_format(time_left)+\
             "Participants: "+questers
    else:
      import numpy
      beg_epoch = convert_to_epoch(started)
      early = (beg_epoch+numpy.min(quest_times)-now)
      likely = (beg_epoch+numpy.mean(quest_times)-now)
      early = time_format(beg_epoch+numpy.min(quest_times)-now)
      likely = time_format(beg_epoch+numpy.mean(quest_times)-now)
      return "May end in {}; most likely to end in {}".format(early, likely)+\
             "\nParticipants: "+questers
  else:
    return "None"

print "Lvl  Time-to-Lvl character"
print "--- ------------ ---------"
for who in sorted(info, key=lambda x:info[x][1]):
  level[who], now_delta, post_delta, online_guess = info[who]
  #if online_guess or True:  #info[who][2]: # online_guess
  #  print('{:>3s} {} {}'.format(level[who], time_format(post_delta), who))
  if online_guess:  #info[who][2]: # online_guess
    print('{:>3s} {} {}'.format(level[who], time_format(now_delta), who))
print("Quest: "+quest_info(quest_started, quest_time_left, quest_times))
