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
from collections import defaultdict, deque, Counter
import argparse
import math
import operator
import re
import subprocess
import time

current_time = time.time()  # Yeah, yeah, globals are bad.  *shrug*
now = current_time

def convert_to_epoch(timestring):
  timetuple = datetime.strptime(timestring, '%Y-%m-%d %H:%M:%S').timetuple()
  return time.mktime(timetuple)
def convert_to_duration(days, hours, mins, secs):
  return 86400*int(days) + 3600*int(hours) + 60*int(mins) + int(secs)

def default_player():
  return {'level':0, 'timeleft':0, 'itemsum':0, 'alignment':'neutral',
          'online':None, 'stronline':'no', 'last_logbreak_seen':0}

class IdlerpgStats(defaultdict):
  def __init__(self, max_recent_count = 100):
    super(IdlerpgStats, self).__init__(default_player)
    self.player = {}  # ircnick -> who_string
    self.recent = {'attackers'  : deque(maxlen=max_recent_count),
                   'questers'   : deque(maxlen=max_recent_count),
                   'godsends'   : deque(maxlen=max_recent_count),
                   'calamities' : deque(maxlen=max_recent_count),
                   'hogs'       : deque(maxlen=max_recent_count),
                  }
    self.quest_started = None  # time_string or None
    self.quest_times = []
    self.quest_started = None
    self.quest_time_left = None
    self.questers = None
    self.next_quest = 0
    self.last_line = None
    self.levels = defaultdict(list)

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

  def apply_attribute_modifications(self, attrib_list_changes):
    if attrib_list_changes:
      what = attrib_list_changes.split(':')
      if len(what)%2 != 1:
        raise SystemExit("Correct format: comma-sep-userlist[:attribN:valueN]*")
      userlist = what[0].split(',')
      for i in xrange(1,len(what),2):
        attrib,value = what[i],what[i+1]
        try:
          value = int(value)
        except ValueError:
          pass
        for who in userlist:
          if attrib == 'alignment':
            rpgstats.change_alignment(who, value)
          else:
            rpgstats[who][attrib] = value

  def next_lines(self, f):
    if self.last_line:
      yield self.last_line
    for line in f:
      self.last_line = line
      yield line

  def parse_lines(self, f):
    nextlvl_re="[Nn]ext level in (?P<days>\d+) days?, (?P<hours>\d{2}):(?P<mins>\d{2}):(?P<secs>\d{2})"
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
      m = re.match("(?P<postdate>[\d-]{10} [\d:]{8}) <idlerpg>\t(.*)$", line)
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
          self.recent['questers'].append(who)
        continue
      m = re.match(r"(.*) have been chosen.*Quest to end in (\d+) days?, (\d{2}):(\d{2}):(\d{2})", line)
      if m:
        self.questers, days, hours, mins, secs = m.groups()
        self.quest_started = epoch
        duration = convert_to_duration(days, hours, mins, secs)
        self.quest_time_left = self.quest_started+duration-now
        for who in IdlerpgStats.get_people_list(self.questers):
          self[who]['online'] = True
          self.recent['questers'].append(who)
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
        self.levels[who].append((0, epoch))
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
        self.levels[who].append((m.group('level'), epoch))
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

      # Two individuals battling, either due to time (1/hour) or space (grid)
      m = re.match(r"(?P<attacker>.*) \[\d+/(?P<attacker_sum>\d+)\] has (?:challenged|come upon) (?P<defender>.*) \[\d+/(?P<defender_sum>\d+)\]", line)
      if m:
        attacker, attacker_sum, defender, defender_sum = m.groups()
        self.recent['attackers'].append(attacker)
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
      # Check for godsends, calamities, and hogs
      #
      m = re.match('(?P<who>\w+).*gains 10% of its effectiveness', line)
      if m:
        self.recent['godsends'].append(m.group('who'))
        continue
      m = re.match('(?P<who>\w+).*wondrous godsend has accelerated', line)
      if m:
        self.recent['godsends'].append(m.group('who'))
        continue
      m = re.match('(?P<who>\w+).*loses 10% of its effectiveness', line)
      if m:
        self.recent['calamities'].append(m.group('who'))
        continue
      m = re.match('(?P<who>\w+).*terrible calamity has slowed them', line)
      if m:
        self.recent['calamities'].append(m.group('who'))
        continue
      m = re.match('.*hand of God carried (?P<who>\w+).*toward level', line)
      if m:
        self.recent['hogs'].append(m.group('who'))
        continue
      m = re.match('Thereupon.*consumed (?P<who>\w+) with fire, slowing', line)
      if m:
        self.recent['hogs'].append(m.group('who'))
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
      self[who]['stronline'] = 'yes' if self[who]['online'] else (
                               '???' if self[who]['online'] is None else 'no')


  def parse(self, fileobj):
    try:
      self.parse_lines(f)
    except StopIteration:
      pass
    self.update_offline()

def time_format(seconds):
  if seconds == float('inf'):
    seconds = 86400*100-1  # 100 days - 1 second, basically infinity
    #return "     Never  "
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
  oncount = sum([1 for x in stats if stats[x]['online']])
  odds_fight_per_day = 0
  if stats[who]['level'] >= 45:
    odds_fight_per_day += 24.0/oncount # every hour, 1.0 selected to start fight
  odds_fight_per_day += 1.5/oncount  # 1.5ish grid battles/day, from past stats
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
    odds_beat_opp = stats[who]['itemsum']/(stats[who]['itemsum']+stats[opp]['itemsum']+1e-25)
    change_if_fight = odds_beat_opp*gain - (1-odds_beat_opp)*loss
    diff = change_if_fight*odds_fight_this_opp*odds_fight_per_day
    percent_change += diff
  if True: # Also handle idlerpg
    idlerpg_sum = 1+max(stats[x]['itemsum'] for x in stats)
    gain = 20
    loss = 10
    odds_fight_this_opp = 1.0/oncount # oncount-1 other players, plus idlerpg
    odds_beat_opp = stats[who]['itemsum']/(stats[who]['itemsum']+idlerpg_sum+0.0)

    change_if_fight = odds_beat_opp*gain - (1-odds_beat_opp)*loss
    diff = change_if_fight*odds_fight_this_opp*odds_fight_per_day
    percent_change += diff
  return percent_change/100.0

def critical_strike_rate(stats,who):
  oncount = sum([1 for x in stats if stats[x]['online']])
  crit_factor = {'good':1.0/50, 'neutral':1.0/35, 'evil':1.0/20}
  odds_fight_per_day = 24.0/oncount  # every hour, 1.0 selected to start fight
  odds_fight_per_day += 1.5/oncount  # 1.5ish grid battles per day
  rate = 0
  for opp in stats:
    if opp == who or not stats[opp]['online']:
      continue
    odds_fight_this_opp = 1.0/oncount # oncount-1 other players, plus idlerpg
    odds_beaten_by_opp = stats[opp]['itemsum']/(stats[who]['itemsum']+stats[opp]['itemsum']+0.0)

    odds_lose = odds_fight_per_day*odds_fight_this_opp*odds_beaten_by_opp
    rate += odds_lose * crit_factor[stats[opp]['alignment']] * 15.0/100

  return rate

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
  return overall_percentage

def alignment_burn(stats, who):
  if stats[who]['alignment'] == 'good':
    good_and_online_count = sum([1 for x in stats
                   if stats[x]['online'] and stats[x]['alignment'] == 'good'])
    if good_and_online_count < 2:
      return 0
    percent = (.05+.12)/2
    odds = 2*(1.0/12)
    return odds*percent
  elif stats[who]['alignment'] == 'evil':
    percent = (.01+.05)/2
    odds = .5*1.0/8
    return -odds*percent
  else:
    return 0

def quest_burn(stats, who):
  above_level_40 = sum([1 for x in stats
                        if stats[x]['online'] and stats[x]['level'] >= 40])
  if above_level_40 < 4:
    return 0, 0, 0

  # Determine average quest duration
  location_quest_average = sum(stats.quest_times)/len(stats.quest_times)
  time_quest_average = 86400*1.5
  average_quest_time = (location_quest_average*12.0+time_quest_average*5.0)/17

  # Find various odds of folks a,b,c being involved or not
  odds_a = 4.0/above_level_40
  odds_not_a_but_b = (4.0*(above_level_40-4))/(
                      above_level_40*(above_level_40-1))
  odds_a_and_c =  (4.0*3)/((above_level_40)*(above_level_40-1))
  odds_not_a_not_b_but_c = (4.0*(above_level_40-4)*(above_level_40-5))/(
                      (above_level_40)*(above_level_40-1)*(above_level_40-2))
  odds_c = odds_a_and_c + odds_not_a_not_b_but_c # not_a_but_b_and_c ignored

  # Determine quests per day
  fail_quest_percentage = odds_not_a_but_b
  average_wait_time = 21600*(1+fail_quest_percentage)  # Yes '+', after simplify
  quests_per_day = 86400 / (average_quest_time + average_wait_time)

  # Determine antiburn
  pen = min(86400*7, 15*1.14**stats[who]['level'])
  antiburn = pen*quests_per_day*fail_quest_percentage

  # Find rates and return them
  idlerpg = (sum(ord(x) for x in who) == 621)
  optimistic_rate = quests_per_day * odds_a * .25
  expected_rate   = quests_per_day * odds_c * .25
  if stats[who]['level'] < 40:
    return 0, 0, antiburn
  elif idlerpg:
    return optimistic_rate, optimistic_rate, antiburn
  else:
    return optimistic_rate, expected_rate, antiburn

def solve_ttl_to_0(ttl, r, p):
  # ttl in seconds, burn_rate in days, antiburn in seconds; get common units
  ttl /= 86400.0
  p /= 86400.0

  # Compute ttl_burn_time
  if p > 1: # Can't complete (in positive time)
    return float('inf')
  ttl_burn_time = (-1/r)*math.log((1-p)/(r*ttl+1-p))

  # Switch back to seconds
  return ttl_burn_time * 86400

def advance_by_time(original_ttl, r, p, time_advance):
  # ttl,p,time_advance in seconds; burn_rate in days; get common units
  original_ttl /= 86400.0
  p /= 86400.0
  time_advance /= 86400

  # Do the computation
  result = (original_ttl+(1-p)/r)*math.exp(-r*time_advance) - (1-p)/r

  # Convert back to seconds, and return it
  result *= 86400
  return result

def get_burn_rates(stats, who):
  burn_rate = 0
  burn_rate += battle_burn(stats, who)
  burn_rate += godsend_calamity_hog_burn(stats, who)
  burn_rate += alignment_burn(stats, who)
  quest_default_br, quest_tweaked_br, antiburn = quest_burn(stats, who)

  return burn_rate + quest_default_br, burn_rate + quest_tweaked_br, antiburn

def expected_ttl(stats, who): # How much time-to-level decrease in next day
  if 'expected_ttls' in stats[who]:
    return stats[who]['expected_ttls']
  cur_ttl = stats[who]['timeleft']

  optimal_burn_rate, expected_burn_rate, antiburn = get_burn_rates(stats, who)

  ttl1 = solve_ttl_to_0(cur_ttl, optimal_burn_rate, 0)
  ttl2 = solve_ttl_to_0(cur_ttl, expected_burn_rate, antiburn)
  return ttl1, ttl2

def print_summary_info(rpgstats):
  # Print out all the information we've collected
  brkln="--- --- ---- ------------ ---- ------------ ------------ ---------"
  print "Lvl On? ISum  Time-to-Lvl Algn   Optimistic Expected TTL character"
  last = True
  for who in sorted(rpgstats, key=lambda x:(rpgstats[x]['stronline'],rpgstats[x]['timeleft'])):
    on = rpgstats[who]['stronline']
    assumed_on = bool(on=='yes')
    if assumed_on ^ last:
      print brkln
      last = assumed_on
    ettl1, ettl2 = expected_ttl(rpgstats, who)
    print('{:3d} {:3s} {:4d} {} {} {} {} {}'.format(
             rpgstats[who]['level'],
             on,
             rpgstats[who]['itemsum'],
             time_format(rpgstats[who]['timeleft']),
             rpgstats[who]['alignment'][0:4],
             time_format(ettl1),
             time_format(ettl2),
             who))
  print("Quest: "+quest_info(rpgstats))

def compute_burn_info(rpgstats, who):
  bb = battle_burn(rpgstats, who)
  gchb = godsend_calamity_hog_burn(rpgstats, who)
  ab = alignment_burn(rpgstats, who)
  qbdef, qbtweak, antiburn = quest_burn(rpgstats, who)
  combdef = bb+gchb+ab+qbdef
  combtweak = bb+gchb+ab+qbtweak
  critrate = critical_strike_rate(rpgstats,who)
  return (bb, gchb, ab, qbdef, combdef, qbtweak, combtweak, antiburn/86400, critrate)

def print_detailed_burn_info(rpgstats):
  print "Battle g/c/hog align  quest Comb'd    qmod Comb'd  Xburn CritS  Character"
  print "------ ------ ------ ------ ------  ------ ------  ----- -----  ---------"
  for who in sorted(rpgstats, key=lambda x:rpgstats[x]['itemsum']):
    if 'burnrates' in rpgstats[who]:
      burnrates = rpgstats[who]['burnrates']
    else:
      burnrates = compute_burn_info(rpgstats, who)
    print '{:6.3f} {:6.3f} {:6.3f} {:6.3f} {:6.3f}  {:6.3f} {:6.3f}  {:5.2f} {:5.3f}  '.format(*burnrates)+who

def print_recent(iterable):
  # Print out recent battlers and counts
  acount = Counter(iterable)
  print "Count Individual"
  print "----- ----------"
  for who in sorted(acount, key=lambda x:acount[x], reverse=True):
    print "{:5d} {}".format(acount[who], who)

def plot_levels(rpgstats):
  import matplotlib.pyplot as plt
  import numpy as np

  plt.figure()
  folks = [x for x in rpgstats.levels.keys() if rpgstats[x]['online'] and rpgstats[x]['level'] > 60]
  for who in folks: # ('elijah',): #
    level,when = zip(*rpgstats.levels[who])
    plt.plot(when,level)
  xmin, xmax = plt.xlim()
  xvalues = np.arange(xmin, xmax+1, (xmax-xmin)/10)
  xlabels = [datetime.fromtimestamp(x).date().isoformat() for x in xvalues]
  plt.xticks( xvalues, xlabels, rotation=90 )
  plt.tight_layout()
  plt.legend(folks, loc='upper left')
  plt.autoscale('tight')
  plt.ylim(ymin=50)

  plt.show()

def print_next_levelling(stats):
  def basic_time_to_level(level):
    return 600*1.16**min(level,60) + 86400*max(level-60, 0)
  onliners = [who for who in stats if stats[who]['online']]

  cur = now
  ettl = {}
  br = {}
  ab = {}
  while True:
    minpair = (float('inf'), None)
    # Find the burn rate, antiburn, and expected ttl for each player
    # as well as the player with least expected ttl
    for who in onliners:
      br1, br2, antiburn = get_burn_rates(stats, who)
      br[who] = br2
      ab[who] = antiburn
      ettl[who] = solve_ttl_to_0(stats[who]['timeleft'], br2, antiburn)
      if ettl[who] < minpair[0]:
        minpair = ettl[who], who

    # Advance time by least expected ttl
    t_adv, who_adv = minpair
    if who_adv is None:
      raise SystemExit("No more levelling.")
    cur += t_adv

    # Advance each player forward in time by least expected ttl
    for who in onliners:
      stats[who]['timeleft'] = advance_by_time(stats[who]['timeleft'], br[who],
                                               ab[who], t_adv)
    # Advance specified player to next level
    stats[who_adv]['level'] += 1
    stats[who_adv]['timeleft'] = basic_time_to_level(stats[who_adv]['level'])

    # Notify that who_adv is expected to level at the given time
    timestr = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(cur))
    print("{} {:3d} {}".format(timestr, stats[who_adv]['level'], who_adv))

def parse_args(rpgstats, irclog):
  # A few helper functions for calling rpgstats.parse(irclog) and keeping
  # track of whether and how many times we have done so.
  def ensure_parsed(stats, log, count=1):
    if ensure_parsed.count < count:
      stats.parse(log)
      ensure_parsed.count += 1
  ensure_parsed.count = 0
  def force_parse(stats, log):
    stats.parse(log)
    ensure_parsed.count += 1

  comparisons = []
  def copy_for_comparison(stats):
    def default_player_copy():
      basic_dict = default_player()
      basic_dict['burnrates'] = (0,0,0,0,0,0,0,0,0)
      basic_dict['expected_ttls'] = (0,0)
      return basic_dict
    mycopy = defaultdict(default_player_copy)
    for who in stats:
      mycopy[who] = stats[who].copy()
    for who in stats:
      mycopy[who]['expected_ttls'] = expected_ttl(stats, who)
      mycopy[who]['burnrates'] = compute_burn_info(stats, who)
    comparisons.append(mycopy)

  class ParseEndTime(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      global now
      now = current_time if values == 'now' else convert_to_epoch(values)
      force_parse(rpgstats, irclog)
  class TweakStats(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      ensure_parsed(rpgstats, irclog)
      rpgstats.apply_attribute_modifications(values)
  class RecordForComparison(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      num_compares = getattr(namespace, self.dest)+1
      setattr(namespace, self.dest, num_compares)
      ensure_parsed(rpgstats, irclog, count=num_compares)
      copy_for_comparison(rpgstats)

  parser = argparse.ArgumentParser(description='Frobnicate the unobtanium')
  parser.add_argument('--until', type=str, action=ParseEndTime,
                      help='Get state of channel until this specified time (default: now)')
  parser.add_argument('--whatif', type=str, action=TweakStats,
                      help='Changes; comma-sep-userlist[:attribN:valueN]*')
  parser.add_argument('--show', type=str, default='summary',
                      choices=['summary', 'burninfo', 'recent', 'levelling',
                               'plot_levelling', 'bad'],
                      help='Which kind of info to show')
  parser.add_argument('--compare', action=RecordForComparison,
                      default=0, nargs=0,
                      help='Record stats for comparison')
  args = parser.parse_args()
  ensure_parsed(rpgstats, irclog)
  if len(comparisons) > 2:
    raise SystemExit("Error: Can only meaningfully handle two --compare flags")
  elif len(comparisons) == 2:
    for who in rpgstats:
      rpgstats[who]['level']    = comparisons[1][who]['level'] - \
                                  comparisons[0][who]['level']
      rpgstats[who]['timeleft'] = comparisons[1][who]['timeleft'] - \
                                  comparisons[0][who]['timeleft']
      rpgstats[who]['itemsum']  = comparisons[1][who]['itemsum'] - \
                                  comparisons[0][who]['itemsum']
      rpgstats[who]['expected_ttls'] = tuple(operator.sub(*x) for x in
                                zip(comparisons[1][who]['expected_ttls'],
                                    comparisons[0][who]['expected_ttls']))
      rpgstats[who]['burnrates'] = tuple(operator.sub(*x) for x in
                                zip(comparisons[1][who]['burnrates'],
                                    comparisons[0][who]['burnrates']))
      if comparisons[1][who]['alignment'] != comparisons[0][who]['alignment']:
        rpgstats[who]['alignment'] = comparisons[0][who]['alignment'][0] + \
                              '->' + comparisons[1][who]['alignment'][0]
      if comparisons[1][who]['stronline'] != comparisons[0][who]['stronline']:
        rpgstats[who]['stronline'] = comparisons[0][who]['stronline'][0] + \
                                     '>' + \
                                     comparisons[1][who]['stronline'][0]
  else:
    pass # Don't need to do anything special
  return args.show


rpgstats = IdlerpgStats(40)
with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  show = parse_args(rpgstats, f)
if show == 'summary':
  print_summary_info(rpgstats)
elif show == 'burninfo':
  print_detailed_burn_info(rpgstats)
elif show == 'recent':
  print_recent(rpgstats.recent['attackers'])
  print_recent(rpgstats.recent['questers'])
  print_recent(rpgstats.recent['godsends'])
  print_recent(rpgstats.recent['calamities'])
  print_recent(rpgstats.recent['hogs'])
elif show == 'levelling':
  print_next_levelling(rpgstats)
elif show == 'plot_levelling':
  plot_levels(rpgstats)
else:
  raise SystemExit("Unrecognized --show flag: "+args.show)
