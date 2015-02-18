#!/usr/bin/env python

# Accuracy warnings:
#   * Multi-people changes (realm wide penalties, quest completions, team
#     battles) are not included in time updates
#   * Non-printed penalties (e.g. when someone leaves) are not included,
#     making offline folks always have a higher TTL than displayed
#   * There are two types of offline -- definitely offline and assumed
#     offline due to my logging stopping (e.g. me getting disconnected
#     due to computer rebooting).  This can result in weird sort ordering
#     for the offline folks.

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

level = {}    # who_string -> level_number
online = {}   # who_string -> boolean (well, False or True or None=unknown)
timeleft = {} # who_string -> seconds_left
itemsum = {}  # who_string -> latest_battle_itemsum
player = {}  # ircnick -> who_string
quest_started = None  # time_string or None
quest_times = []
now = time.time()

postdate_re="(?P<postdate>[\d-]{10} [\d:]{8}) <idlerpg>\t"
nextlvl_re="[Nn]ext level in (?P<days>\d+) days?, (?P<hours>\d{2}):(?P<mins>\d{2}):(?P<secs>\d{2})"

def handle_timeleft(m):
  postdate = m.group('postdate')
  who = m.group('who')
  days = m.group('days')
  hours = m.group('hours')
  mins = m.group('mins')
  secs = m.group('secs')

  # If we've been told about time to next level, but don't know this
  # person's level yet, just skip this info.
  if who not in level:
    return

  # Given that we were told the time to the next level and know when we
  # were told that, determine how much time currently remains until that
  # character reaches the next level
  post_epoch = convert_to_epoch(postdate)
  post_delta = convert_to_duration(days, hours, mins, secs)
  now_delta = (post_epoch+post_delta)-now

  timeleft[who] = now_delta

def adjust_timeleft(who, post_epoch):
  if who in timeleft and online[who]:
    timeleft[who] += (now-post_epoch)

with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  for line in f:
    #
    # Check for quest starting
    #
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

    #
    # Check for quest ending
    #
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

    #
    # Various checks for time-to-next-level
    #

    # Welcome X's new player Y, the Z! Next level in...
    m = re.match(postdate_re+r"Welcome (?P<nick>.*)'s new player (?P<who>.*), the .*! "+nextlvl_re, line)
    if m:
      who = m.group('who')
      level[who] = '0'
      itemsum[who] = 0
      online[who] = True
      player[m.group('nick')] = who
      handle_timeleft(m)
      continue

    # Y, the level W Z, is now online from nickname X. Next level in...
    m = re.match(postdate_re+r"(?P<who>.*), the level .*, is now online from nickname (?P<nick>.*). "+nextlvl_re, line)
    if m:
      who = m.group('who')
      online[who] = True
      player[m.group('nick')] = who
      handle_timeleft(m)
      continue

    # Y, the Z, has attained level W! Next level in...
    m = re.match(postdate_re+r"(?P<who>.*), the .*, has attained level (?P<level>\d+)! "+nextlvl_re, line)
    if m:
      who = m.group('who')
      level[who] = m.group('level')
      handle_timeleft(m)
      continue

    # Y reaches next level in...
    #   Note: This is by far the most common message.  It is sent immediately
    #   after hourly battles, immediately after grid-collision battles, after
    #   immediately after godsends and calamaties, and immediately after a few
    #   other cases like Critical Strikes or light of their God or hand of God.
    m = re.match(postdate_re+r"(?P<who>.*) reaches "+nextlvl_re, line)
    if m:
      online[m.group('who')] = True
      handle_timeleft(m)
      continue

    # Y, the level W Z, is #U! Next level in...
    m = re.match(postdate_re+r"(?P<who>.*?), the level .*, is #\d+! "+nextlvl_re, line)
    if m:
      if online.get(m.group('who'), False):
        handle_timeleft(m)
      continue

    #
    # Check for going offline
    #

    # Just a single user quitting
    m = re.match(r'(?P<postdate>[\d-]{10} [\d:]{8}) \*\s*(?P<nick>.*) has (?:quit|left)', line)
    if m:
      nick = m.group('nick')
      post_epoch = convert_to_epoch(m.group('postdate'))
      adjust_timeleft(player.get(nick), post_epoch)
      if nick in player:
        online[player[nick]] = False
      continue

    # I got disconnected somehow
    m = re.match(r'\*\*\*\* ENDING LOGGING AT (.*)', line)
    if m:
      enddate = m.group(1)
      timetuple = datetime.strptime(enddate, '%a %b %d %H:%M:%S %Y').timetuple()
      post_epoch = time.mktime(timetuple)
      for who in online:
        adjust_timeleft(who, post_epoch)
        online[who] = None
      continue

    #
    # Check for itemsums
    #

    # Just a single user quitting
    m = re.match(postdate_re+r"(?P<attacker>.*) \[\d+/(?P<attacker_sum>\d+)\] has (?:challenged|come upon) (?P<defender>.*) \[\d+/(?P<defender_sum>\d+)\]", line)
    if m:
      postdate, attacker, attacker_sum, defender, defender_sum = m.groups()
      itemsum[attacker] = int(attacker_sum)
      itemsum[defender] = int(defender_sum)
      continue

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
  return '{:>3s}:{:02d}:{:02d}:{:02d}'.format(sign+str(days),hours,mins,seconds)

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

print "Lvl On? ISum  Time-to-Lvl character"
print "--- --- ---- ------------ ---------"
for who in sorted(timeleft, key=lambda x:(online[x],timeleft[x])):
  print('{:>3s} {:3s} {:4d} {} {}'.format(level[who], 'yes' if online[who] else 'no', itemsum[who], time_format(timeleft[who]), who))
print("Quest: "+quest_info(quest_started, quest_time_left, quest_times))
# If last quest ended successfully, next will be 6 hours later; if last quest
# aborted due to penalized player, next will be 12 hours later.  Print that info?
