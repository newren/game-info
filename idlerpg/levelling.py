#!/usr/bin/env python

# Accuracy warnings:
#   * Penalties other than quitting and realm wide penalties are not included
#     (except parting, which is incorrectly treated like quitting), making
#     folks sometimes have a higher TTL than displayed.
#   * When logging stops, I don't know what has happened in the interim,
#     which makes it hard to guess the correct data; I can only tell what the
#     correct data is once logging restarts and messages about each user
#     come in giving me updated information.

from datetime import datetime, timedelta
from collections import defaultdict
import math
import re
import subprocess
import time

def convert_to_epoch(timestring):
  timetuple = datetime.strptime(timestring, '%Y-%m-%d %H:%M:%S').timetuple()
  return time.mktime(timetuple)
def convert_to_duration(days, hours, mins, secs):
  return 86400*int(days) + 3600*int(hours) + 60*int(mins) + int(secs)

def default_player():
  return {'level':0, 'timeleft':0, 'itemsum':0, 'alignment':'neutral',
          'online':None, 'last_logbreak_seen':0}

stats = defaultdict(default_player)
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

  # Given that we were told the time to the next level and know when we
  # were told that, determine how much time currently remains until that
  # character reaches the next level
  post_epoch = convert_to_epoch(postdate)
  post_delta = convert_to_duration(days, hours, mins, secs)
  now_delta = (post_epoch+post_delta)-now

  stats[who]['timeleft'] = now_delta

def stop_timeleft_as_of(who, post_epoch):
  if stats[who]['online']:
    stats[who]['timeleft'] += (now-post_epoch)

def adjust_timeleft_percentage(who, post_epoch, percentage):
  then_diff = (now-post_epoch)
  time_then_remaining = stats[who]['timeleft'] + then_diff
  stats[who]['timeleft'] = (1-percentage/100.0)*time_then_remaining - then_diff

def get_people_list(wholist):
  people = re.findall('[^, ]+', wholist)
  people.remove('and')
  return people

def reward_questers(quest_end, wholist):
  questers = get_people_list(wholist)
  for who in questers:
    adjust_timeleft_percentage(who, quest_end, 25)

with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  for line in f:
    #
    # Check for quest starting
    #
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>\s*(.*) have been chosen.*Participants must first reach", line)
    if m:
      quest_started, questers = m.groups()
      for who in get_people_list(questers):
        stats[who]['online'] = True
      continue
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>\s*(.*) have been chosen.*Quest to end in (\d+) days?, (\d{2}):(\d{2}):(\d{2})", line)
    if m:
      quest_started, questers, days, hours, mins, secs = m.groups()
      duration = convert_to_duration(days, hours, mins, secs)
      quest_time_left = convert_to_epoch(quest_started)+duration-now
      for who in get_people_list(questers):
        stats[who]['online'] = True
      continue

    #
    # Check for quest ending
    #
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*prudence and self-regard has brought the wrath of the gods upon the realm", line)
    if m:
      end = m.group(1)
      quest_started = None
      quest_time_left = None
      questers = None
      next_quest = convert_to_epoch(end)+43200
      for p in stats:
        if stats[p]['online']:
          stats[p]['timeleft'] += 15*1.14**stats[p]['level']
      continue
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*completed their journey", line)
    if m:
      end = m.group(1)
      beg_epoch = convert_to_epoch(quest_started)
      end_epoch = convert_to_epoch(end)
      quest_times.append(end_epoch-beg_epoch)
      reward_questers(end_epoch, questers)
      quest_started = None
      quest_time_left = None
      questers = None
      next_quest = end_epoch+21600
      continue
    m = re.match(r"([\d-]{10} [\d:]{8}) <idlerpg>.*have blessed the realm by completing their quest", line)
    if m:
      end = m.group(1)
      end_epoch = convert_to_epoch(end)
      reward_questers(end_epoch, questers)
      quest_started = None
      quest_time_left = None
      questers = None
      next_quest = end_epoch+21600
      continue

    #
    # Various checks for time-to-next-level
    #

    # Welcome X's new player Y, the Z! Next level in...
    m = re.match(postdate_re+r"Welcome (?P<nick>.*)'s new player (?P<who>.*), the .*! "+nextlvl_re, line)
    if m:
      who = m.group('who')
      player[m.group('nick')] = who
      # Defaults for level, itemsum, alignment are fine
      stats[who]['online'] = True
      handle_timeleft(m)
      continue

    # Y, the level W Z, is now online from nickname X. Next level in...
    m = re.match(postdate_re+r"(?P<who>.*), the level .*, is now online from nickname (?P<nick>.*). "+nextlvl_re, line)
    if m:
      who = m.group('who')
      player[m.group('nick')] = who
      stats[who]['online'] = True
      handle_timeleft(m)
      continue

    # Y, the Z, has attained level W! Next level in...
    m = re.match(postdate_re+r"(?P<who>.*), the .*, has attained level (?P<level>\d+)! "+nextlvl_re, line)
    if m:
      who = m.group('who')
      stats[who]['level'] = int(m.group('level'))
      handle_timeleft(m)
      continue

    # Y reaches next level in...
    #   Note: This is by far the most common message.  It is sent immediately
    #   after hourly battles, immediately after grid-collision battles, after
    #   immediately after godsends and calamaties, and immediately after a few
    #   other cases like Critical Strikes or light of their God or hand of God.
    m = re.match(postdate_re+r"(?P<who>.*) reaches "+nextlvl_re, line)
    if m:
      stats[m.group('who')]['online'] = True
      handle_timeleft(m)
      continue

    # Y, the level W Z, is #U! Next level in...
    m = re.match(postdate_re+r"(?P<who>.*?), the level .*, is #\d+! "+nextlvl_re, line)
    if m:
      if stats[m.group('who')]['online']:
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
      who = player.get(nick)
      if who in stats:
        stop_timeleft_as_of(who, post_epoch)
        if stats[who]['online']:
          stats[who]['timeleft'] += 20*1.14**stats[who]['level']
        stats[who]['online'] = False
      continue

    # I got disconnected somehow
    m = re.match(r'\*\*\*\* ENDING LOGGING AT (.*)', line)
    if m:
      enddate = m.group(1)
      timetuple = datetime.strptime(enddate, '%a %b %d %H:%M:%S %Y').timetuple()
      post_epoch = time.mktime(timetuple)
      for who in stats:
        stop_timeleft_as_of(who, post_epoch)
        if stats[who]['online'] != None:
          stats[who]['last_logbreak_seen'] = post_epoch
        stats[who]['online'] = None
      continue

    #
    # Check for itemsums
    #

    # Just a single user quitting
    m = re.match(postdate_re+r"(?P<attacker>.*) \[\d+/(?P<attacker_sum>\d+)\] has (?:challenged|come upon) (?P<defender>.*) \[\d+/(?P<defender_sum>\d+)\]", line)
    if m:
      postdate, attacker, attacker_sum, defender, defender_sum = m.groups()
      if attacker != 'idlerpg':
        stats[attacker]['itemsum'] = int(attacker_sum)
        stats[attacker]['online'] = True
      if defender != 'idlerpg':
        stats[defender]['itemsum'] = int(defender_sum)
        stats[defender]['online'] = True
      continue

    #
    # Check for alignment
    #

    # X has changed alignment to: \w+.
    m = re.match(postdate_re+r"(?P<who>.*) has changed alignment to: (.*)\.$", line)
    if m:
      postdate, who, align = m.groups()
      stats[who]['alignment'] = align
      continue

    #
    # Various adjustments to timeleft
    #

    # X is forsaken by their evil god. \d+ days...
    m = re.match(postdate_re+r'(.*?) is forsaken by their evil god. (\d+) days?, (\d{2}):(\d{2}):(\d{2})', line)
    if m:
      postdate, who, days, hours, mins, secs = m.groups()
      duration = convert_to_duration(days, hours, mins, secs)
      stats[who]['timeleft'] += duration
      stats[who]['alignment'] = 'evil'

    # X and Y have not let the iniquities of evil men.*them.  \d+% of their time
    m = re.match(postdate_re+r'(.*?) and (.*?) have not let the iniquities of evil men.*them. (\d+)% of their time is removed from their clocks', line)
    if m:
      postdate, who1, who2, percentage = m.groups()
      post_epoch = convert_to_epoch(postdate)
      adjust_timeleft_percentage(who1, post_epoch, int(percentage))
      adjust_timeleft_percentage(who2, post_epoch, int(percentage))
      stats[who1]['alignment'] = 'good'
      stats[who2]['alignment'] = 'good'

    # I, J, and K [.*] have team battled.* and (won|lost)!
    m = re.match(postdate_re+r'(.*?)\[.*?have team battled .*? and (won|lost)! (\d+) days?, (\d{2}):(\d{2}):(\d{2})', line)
    if m:
      postdate, team, result, days, hours, mins, secs = m.groups()
      members = re.findall('[^, ]+', team)
      members.remove('and')
      duration = convert_to_duration(days, hours, mins, secs)
      sign = -1 if (result == 'won') else 1
      for who in members:
        stats[who]['timeleft'] += sign*duration


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
             "; Participants: "+questers
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
    return "None; next should start in {}".format(time_format(next_quest-now))

def battle_burn(who):
  # FIXME: Really ought to handle being hit by critical strikes from others too
  oncount = sum([1 for x in stats if stats[x]['online']])
  odds_fight_per_day = 24.0/oncount  # every hour, 1.0 selected to start fight
  odds_fight_per_day += 1.5/oncount  # 1.5ish grid battles per day
  # team battles are basically a wash; the reward is equal to the loss, so the
  # only probabilistic difference is if your itemsum is higher or lower than
  # average making you more or less likely than 50% to win.
  percent_change = 0
  # Technically, grid battles cannot be against the 'idlerpg' user, which
  # means I should adjust odds_fight_per_day and odds_fight_this_opp to be
  # more precise, but meh -- it won't change things that much.
  for opp in stats:
    if opp == who or not stats[opp]['online']:
      continue
    gain = max(7,stats[opp]['level']/4)
    loss = max(7,stats[opp]['level']/7)
    odds_fight_this_opp = 1.0/oncount # oncount-1 other players, plus idlerpg
    odds_beat_opp = stats[who]['itemsum']/(stats[who]['itemsum']+stats[opp]['itemsum']+0.0)

    change_if_fight = odds_beat_opp*gain - (1-odds_beat_opp)*loss
    diff = change_if_fight*odds_fight_this_opp*odds_fight_per_day
    percent_change += diff
  if True: # Also handle idlerpg
    gain = 20
    loss = 10
    odds_fight_this_opp = 1.0/oncount # oncount-1 other players, plus idlerpg
    odds_beat_opp = stats[who]['itemsum']/(stats[who]['itemsum']+stats['idlerpg']['itemsum']+0.0)

    change_if_fight = odds_beat_opp*gain - (1-odds_beat_opp)*loss
    diff = change_if_fight*odds_fight_this_opp*odds_fight_per_day
    percent_change += diff
  return percent_change/100.0 * (stats[who]['timeleft']-43200)

def godsend_calamity_hog_burn(who):
  # 1/8 chance per day (per online user) of calamity
  # 1/4 chance per day (per online user) of godsend
  # 9/10 chance per day calamity or godsend will change ttl by 5-12%
  # 1/20 chance per day (per online user) of hog; which change ttl by
  #      5-75%; 20% chance bad and 80% good
  percent_calamity = .9*(1.0/8)*(.05+.12)/2
  percent_godsend  = .9*(1.0/4)*(.05+.12)/2
  percent_hog      = .05*       (.05+.75)/2*(.8-.2)
  overall_percentage = (percent_godsend-percent_calamity+percent_hog)
  return overall_percentage * (stats[who]['timeleft']-43200)

def alignment_burn(who):
  if stats[who]['alignment'] == 'good':
    good_and_online_count = sum([1 for x in stats
                   if stats[x]['online'] and stats[x]['alignment'] == 'good'])
    if good_and_online_count < 2:
      return 0
    percent = (.05+.12)/2
    odds = 2*(1.0/12)
    return odds*percent*(stats[who]['timeleft']-43200)
  elif stats[who]['alignment'] == 'evil':
    percent = (.01+.05)/2
    odds = .5*1.0/8
    return -odds*percent*(stats[who]['timeleft']-43200)
  else:
    return 0

def quest_burn(who):
  above_level_40 = sum([1 for x in stats
                        if stats[x]['online'] and stats[x]['level'] >= 40])
  if above_level_40 < 4:
    return 0
  location_quest_average = sum(quest_times)/len(quest_times)
  time_quest_average = 86400*1.5
  average_quest_time = (location_quest_average+time_quest_average)/2
  average_wait_time = 21600 # Assumes quests end successfully
  quests_per_day = 86400 / (average_quest_time + average_wait_time)
  odds_quest = 4.0/above_level_40
  return odds_quest * quests_per_day * .25 * stats[who]['timeleft']

def expected_ttl_burn(who): # How much time-to-level will decrease in next day
  # If they're not online, their time-to-level isn't going to decrease at all
  if not stats[who]['online']:
    return 0

  # If user has less than a day left, the fact that we tend to burn faster more
  # than a day's worth of time-to-level per day becomes a bit weird.  The
  # correct amount to report will depend upon what their ttl becomes after they
  # go to the next level.  For now, just pretend they'll burn at a flat rate
  # if they have less than half a day left
  if stats[who]['timeleft'] < 43200:
    return 86400

  # Print out ttl burn info
  #bb = battle_burn(who)
  #gchb = godsend_calamity_hog_burn(who)
  #ab = alignment_burn(who)
  #qb = quest_burn(who)
  #print '     {}'.format((who,bb,gchb,ab,qb,time_format(86400+bb+gchb+ab+qb)))

  # By default, if people wait a day, a day of time-to-level burns
  ttl_burn = 86400
  ttl_burn += battle_burn(who)
  ttl_burn += godsend_calamity_hog_burn(who)
  ttl_burn += alignment_burn(who)

  return ttl_burn

# Mark people as offline if they're unknown but their ttl suggests they
# should have already levelled by now
for who in stats:
  if stats[who]['online'] is None and \
     stats[who]['timeleft']+stats[who]['last_logbreak_seen'] < now:
    stats[who]['online'] = False

# Print out all the information we've collected
brkln="--- --- ---- ------------ ---- ------------ ---------"
print "Lvl On? ISum  Time-to-Lvl Algn ExpectedBurn character"
last = True
for who in sorted(stats, key=lambda x:(stats[x]['online'],stats[x]['timeleft'])):
  on = 'yes' if stats[who]['online'] else ('???'
             if stats[who]['online'] is None else 'no')
  assumed_on = bool(on=='yes')
  if assumed_on ^ last:
    print brkln
    last = assumed_on
  print('{:3d} {:3s} {:4d} {} {} {} {}'.format(
           stats[who]['level'],
           on,
           stats[who]['itemsum'],
           time_format(stats[who]['timeleft']),
           stats[who]['alignment'][0:4],
           time_format(expected_ttl_burn(who)),
           who))
print("Quest: "+quest_info(quest_started, quest_time_left, quest_times))
