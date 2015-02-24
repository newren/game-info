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
import argparse
import math
import re
import subprocess
import time

now = time.time()

def parse_args():
  global now
  parser = argparse.ArgumentParser(description='Frobnicate the unobtanium')
  parser.add_argument('--until', type=str,
                      help='Get state of channel until this specified time (default: now)')
  args = parser.parse_args()
  if args.until:
    now = convert_to_epoch(args.until)

def convert_to_epoch(timestring):
  timetuple = datetime.strptime(timestring, '%Y-%m-%d %H:%M:%S').timetuple()
  return time.mktime(timetuple)
def convert_to_duration(days, hours, mins, secs):
  return 86400*int(days) + 3600*int(hours) + 60*int(mins) + int(secs)

def default_player():
  return {'level':0, 'timeleft':0, 'itemsum':0, 'alignment':'neutral',
          'online':None, 'last_logbreak_seen':0}

parse_args()
postdate_re="(?P<postdate>[\d-]{10} [\d:]{8}) <idlerpg>\t"
nextlvl_re="[Nn]ext level in (?P<days>\d+) days?, (?P<hours>\d{2}):(?P<mins>\d{2}):(?P<secs>\d{2})"

class IdlerpgStats(defaultdict):
  def __init__(self):
    super(IdlerpgStats, self).__init__(default_player)
    self.player = {}  # ircnick -> who_string
    self.quest_started = None  # time_string or None
    self.quest_times = []
    self.quest_started = None
    self.quest_time_left = None
    self.questers = None
    self.next_quest = 0
    self.last_line = None

  def handle_timeleft(self, m, epoch):
    who = m.group('who')
    days = m.group('days')
    hours = m.group('hours')
    mins = m.group('mins')
    secs = m.group('secs')

    # Given that we were told the time to the next level and know when we
    # were told that, determine how much time currently remains until that
    # character reaches the next level
    post_delta = convert_to_duration(days, hours, mins, secs)
    now_delta = (epoch+post_delta)-now

    self[who]['timeleft'] = now_delta

  def stop_timeleft_as_of(self, who, post_epoch):
    if self[who]['online']:
      self[who]['timeleft'] += (now-post_epoch)

  def adjust_timeleft_percentage(self, who, post_epoch, percentage):
    then_diff = (now-post_epoch)
    time_then_remaining = self[who]['timeleft'] + then_diff
    self[who]['timeleft'] = (1-percentage/100.0)*time_then_remaining - then_diff

  @staticmethod
  def get_people_list(wholist):
    people = re.findall('[^, ]+', wholist)
    people.remove('and')
    return people

  def reward_questers(self, quest_end, questers_string):
    for who in IdlerpgStats.get_people_list(questers_string):
      self.adjust_timeleft_percentage(who, quest_end, 25)

  def change_alignment(self, who, align):
    factor = {'good':1.1, 'neutral':1.0, 'evil':0.9}
    self[who]['alignment'], old = align, self[who]['alignment']
    self[who]['itemsum'] = int(self[who]['itemsum']*factor[align]/factor[old])

  def next_lines(self, f):
    if self.last_line:
      yield self.last_line
    for line in f:
      self.last_line = line
      yield line

  def parse_lines(self, f):
    for line in self.next_lines(f):
      #
      # Check for going offline
      #

      # Just a single user quitting
      m = re.match(r'(?P<postdate>[\d-]{10} [\d:]{8}) \*\s*(?P<nick>.*) has (?:quit|left)', line)
      if m:
        nick = m.group('nick')
        post_epoch = convert_to_epoch(m.group('postdate'))
        if post_epoch > now:
          break
        who = self.player.get(nick)
        if who in self:
          self.stop_timeleft_as_of(who, post_epoch)
          if self[who]['online']:
            self[who]['timeleft'] += 20*1.14**self[who]['level']
          self[who]['online'] = False
        continue

      # I got disconnected somehow
      m = re.match(r'\*\*\*\* ENDING LOGGING AT (.*)', line)
      if m:
        enddate = m.group(1)
        timetuple = datetime.strptime(enddate, '%a %b %d %H:%M:%S %Y').timetuple()
        post_epoch = time.mktime(timetuple)
        if post_epoch > now:
          break
        for who in self:
          self.stop_timeleft_as_of(who, post_epoch)
          if self[who]['online'] != None:
            self[who]['last_logbreak_seen'] = post_epoch
          self[who]['online'] = None
        continue

      #
      # ALL CASES: Get the time of the post, and the remainder of the line
      #
      m = re.match(postdate_re+"(.*)$", line)
      if not m:
        continue
      postdate, line = m.groups()
      epoch = convert_to_epoch(postdate)
      if epoch > now:
        break

      #
      # Check for quest starting
      #
      m = re.match("(.*) have been chosen.*Participants must first reach", line)
      if m:
        self.questers = m.group(1)
        self.quest_started = epoch
        for who in IdlerpgStats.get_people_list(self.questers):
          self[who]['online'] = True
        continue
      m = re.match(r"(.*) have been chosen.*Quest to end in (\d+) days?, (\d{2}):(\d{2}):(\d{2})", line)
      if m:
        self.questers, days, hours, mins, secs = m.groups()
        self.quest_started = epoch
        duration = convert_to_duration(days, hours, mins, secs)
        self.quest_time_left = self.quest_started+duration-now
        for who in IdlerpgStats.get_people_list(self.questers):
          self[who]['online'] = True
        continue

      #
      # Check for quest ending
      #
      m = re.match(r".*prudence and self-regard has brought the wrath of the gods upon the realm", line)
      if m:
        self.quest_started = None
        self.quest_time_left = None
        self.questers = None
        self.next_quest = epoch+43200
        for p in self:
          if self[p]['online']:
            self[p]['timeleft'] += 15*1.14**self[p]['level']
        continue
      m = re.match(r".*completed their journey", line)
      if m:
        self.quest_times.append(epoch-self.quest_started)
        self.reward_questers(epoch, self.questers)
        self.quest_started = None
        self.quest_time_left = None
        self.questers = None
        self.next_quest = epoch+21600
        continue
      m = re.match(r".*have blessed the realm by completing their quest", line)
      if m:
        self.reward_questers(epoch, self.questers)
        self.quest_started = None
        self.quest_time_left = None
        self.questers = None
        self.next_quest = epoch+21600
        continue

      #
      # Various checks for time-to-next-level
      #

      # Welcome X's new player Y, the Z! Next level in...
      m = re.match(r"Welcome (?P<nick>.*)'s new player (?P<who>.*), the .*! "+nextlvl_re, line)
      if m:
        self.handle_timeleft(m, epoch)
        who = m.group('who')
        self.player[m.group('nick')] = who
        # Defaults for level, itemsum, alignment are fine
        self[who]['online'] = True
        continue

      # Y, the level W Z, is now online from nickname X. Next level in...
      m = re.match(r"(?P<who>.*), the level .*, is now online from nickname (?P<nick>.*). "+nextlvl_re, line)
      if m:
        who = m.group('who')
        self.player[m.group('nick')] = who
        self[who]['online'] = True
        self.handle_timeleft(m, epoch)
        continue

      # Y, the Z, has attained level W! Next level in...
      m = re.match(r"(?P<who>.*), the .*, has attained level (?P<level>\d+)! "+nextlvl_re, line)
      if m:
        who = m.group('who')
        self[who]['level'] = int(m.group('level'))
        self.handle_timeleft(m, epoch)
        continue

      # Y reaches next level in...
      #   Note: This is by far the most common message.  It is sent immediately
      #   after hourly battles, immediately after grid-collision battles, after
      #   immediately after godsends and calamaties, and immediately after a few
      #   other cases like Critical Strikes or light of their God or hand of God.
      m = re.match(r"(?P<who>.*) reaches "+nextlvl_re, line)
      if m:
        self[m.group('who')]['online'] = True
        self.handle_timeleft(m, epoch)
        continue

      # Y, the level W Z, is #U! Next level in...
      m = re.match(r"(?P<who>.*?), the level .*, is #\d+! "+nextlvl_re, line)
      if m:
        if self[m.group('who')]['online']:
          self.handle_timeleft(m, epoch)
        continue

      #
      # Check for itemsums
      #

      # Just a single user quitting
      m = re.match(r"(?P<attacker>.*) \[\d+/(?P<attacker_sum>\d+)\] has (?:challenged|come upon) (?P<defender>.*) \[\d+/(?P<defender_sum>\d+)\]", line)
      if m:
        attacker, attacker_sum, defender, defender_sum = m.groups()
        if attacker != 'idlerpg':
          self[attacker]['itemsum'] = int(attacker_sum)
          self[attacker]['online'] = True
        if defender != 'idlerpg':
          self[defender]['itemsum'] = int(defender_sum)
          self[defender]['online'] = True
        continue

      #
      # Check for alignment
      #

      # X has changed alignment to: \w+.
      m = re.match(r"(?P<who>.*) has changed alignment to: (.*)\.$", line)
      if m:
        who, align = m.groups()
        self.change_alignment(who, align)
        continue

      #
      # Various adjustments to timeleft
      #

      # X is forsaken by their evil god. \d+ days...
      m = re.match(r'(.*?) is forsaken by their evil god. (\d+) days?, (\d{2}):(\d{2}):(\d{2})', line)
      if m:
        who, days, hours, mins, secs = m.groups()
        duration = convert_to_duration(days, hours, mins, secs)
        self[who]['timeleft'] += duration
        self[who]['alignment'] = 'evil'

      # X and Y have not let the iniquities of evil men.*them.  \d+% of their time
      m = re.match(r'(.*?) and (.*?) have not let the iniquities of evil men.*them. (\d+)% of their time is removed from their clocks', line)
      if m:
        who1, who2, percentage = m.groups()
        self.adjust_timeleft_percentage(who1, epoch, int(percentage))
        self.adjust_timeleft_percentage(who2, epoch, int(percentage))
        self[who1]['alignment'] = 'good'
        self[who2]['alignment'] = 'good'

      # I, J, and K [.*] have team battled.* and (won|lost)!
      m = re.match(r'(.*?)\[.*?have team battled .*? and (won|lost)! (\d+) days?, (\d{2}):(\d{2}):(\d{2})', line)
      if m:
        team, result, days, hours, mins, secs = m.groups()
        members = re.findall('[^, ]+', team)
        members.remove('and')
        duration = convert_to_duration(days, hours, mins, secs)
        sign = -1 if (result == 'won') else 1
        for who in members:
          self[who]['timeleft'] += sign*duration

  def update_offline(self):
    # Mark people as offline if they're unknown but their ttl suggests they
    # should have already levelled by now
    for who in self:
      if self[who]['online'] is None and \
         self[who]['timeleft']+self[who]['last_logbreak_seen'] < now:
        self[who]['online'] = False


  def parse(self, fileobj):
    try:
      self.parse_lines(f)
    except StopIteration:
      pass
    self.update_offline()

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

def quest_info(stats):
  if stats.quest_started:
    if stats.quest_time_left: # Time-based quest
      return "Will end in "+time_format(stats.quest_time_left)+\
             "; Participants: "+stats.questers
    else:
      import numpy
      early = time_format(stats.quest_started+numpy.min(stats.quest_times)-now)
      likly = time_format(stats.quest_started+numpy.mean(stats.quest_times)-now)
      return "May end in {}; most likely to end in {}".format(early, likly)+\
             "\nParticipants: "+stats.questers
  else:
    next_start = time_format(stats.next_quest-now)
    return "None; next should start in "+next_start

def battle_burn(stats, who):
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

def godsend_calamity_hog_burn(stats, who):
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

def alignment_burn(stats, who):
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

def quest_burn(stats, who):
  above_level_40 = sum([1 for x in stats
                        if stats[x]['online'] and stats[x]['level'] >= 40])
  if above_level_40 < 4:
    return 0
  location_quest_average = sum(stats.quest_times)/len(stats.quest_times)
  time_quest_average = 86400*1.5
  average_quest_time = (location_quest_average+time_quest_average)/2
  average_wait_time = 21600 # Assumes quests end successfully
  quests_per_day = 86400 / (average_quest_time + average_wait_time)
  odds_quest = 4.0/above_level_40
  return odds_quest * quests_per_day * .25 * stats[who]['timeleft']

def expected_ttl_burn(stats, who): # How much time-to-level decrease in next day
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
  #bb = battle_burn(stats, who)
  #gchb = godsend_calamity_hog_burn(stats, who)
  #ab = alignment_burn(stats, who)
  #qb = quest_burn(stats, who)
  #print '     {}'.format((who,bb,gchb,ab,qb,time_format(86400+bb+gchb+ab+qb)))

  # By default, if people wait a day, a day of time-to-level burns
  ttl_burn = 86400
  ttl_burn += battle_burn(stats, who)
  ttl_burn += godsend_calamity_hog_burn(stats, who)
  ttl_burn += alignment_burn(stats, who)

  return ttl_burn

rpgstats = IdlerpgStats()
with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  rpgstats.parse(f)

# Print out all the information we've collected
brkln="--- --- ---- ------------ ---- ------------ ---------"
print "Lvl On? ISum  Time-to-Lvl Algn ExpectedBurn character"
last = True
for who in sorted(rpgstats, key=lambda x:(rpgstats[x]['online'],rpgstats[x]['timeleft'])):
  on = 'yes' if rpgstats[who]['online'] else ('???'
             if rpgstats[who]['online'] is None else 'no')
  assumed_on = bool(on=='yes')
  if assumed_on ^ last:
    print brkln
    last = assumed_on
  print('{:3d} {:3s} {:4d} {} {} {} {}'.format(
           rpgstats[who]['level'],
           on,
           rpgstats[who]['itemsum'],
           time_format(rpgstats[who]['timeleft']),
           rpgstats[who]['alignment'][0:4],
           time_format(expected_ttl_burn(rpgstats, who)),
           who))
print("Quest: "+quest_info(rpgstats))
