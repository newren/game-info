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
          'online':None, 'stronline':'no', 'last_logbreak_seen':0,
          'attack_stats':[0,0,0],
          'total_time_stats':[0,0,0], 'alignment_stats':[0,0,0]
}

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
    self.questers = []
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
    self.ensure_online(who, epoch)

  def adjust_total_time_by_alignment(self, who, epoch, increase):
    factor = 1 if increase else -1
    index = {'good':0, 'neutral':1, 'evil':2}[self[who]['alignment']]
    self[who]['total_time_stats'][index] += factor*(now-epoch)

  def ensure_offline(self, who, epoch, known_offline=True):
    if self[who]['online']:
      self[who]['timeleft'] += (now-epoch)
      self.adjust_total_time_by_alignment(who, epoch, increase=False)
    self[who]['online'] = (False if known_offline else None)

  def ensure_online(self, who, epoch):
    if not self[who]['online']:
      self.adjust_total_time_by_alignment(who, epoch, increase=True)
    self[who]['online'] = True

  def adjust_timeleft_percentage(self, who, post_epoch, percentage):
    then_diff = (now-post_epoch)
    time_then_remaining = self[who]['timeleft'] + then_diff
    self[who]['timeleft'] = (1-percentage/100.0)*time_then_remaining - then_diff

  @staticmethod
  def get_people_list(wholist):
    if not wholist:
      return []
    people = re.findall('[^, ]+', wholist)
    people.remove('and')
    return people

  def record_questers(self, questers, epoch):
    # Record the quest beginning
    self.questers = questers
    self.quest_started = epoch

    # Make sure folks are recorded as online
    for who in questers:
      self.ensure_online(who, epoch)
      self.recent['questers'].append(who)

  def quest_ended(self, quest_end, successful):
    # Reward for a successful quest
    if successful:
      wait_period = 21600  # 6 hours
      for who in self.questers:
        self.adjust_timeleft_percentage(who, quest_end, 25)
    # Or penalty for an unsuccessful one
    else:
      wait_period = 43200  # 12 hours
      for p in self:
        if self[p]['online']:
          self[p]['timeleft'] += 15*1.14**self[p]['level']
    # Record that there is no active quest
    self.quest_started = None
    self.quest_time_left = None
    self.questers = []
    self.next_quest = quest_end+wait_period

  def change_alignment(self, who, align, epoch):
    if self[who]['alignment'] == align:
      return
    factor = {'good':1.1, 'neutral':1.0, 'evil':0.9}
    self.adjust_total_time_by_alignment(who, epoch, increase=False)
    self[who]['alignment'], old = align, self[who]['alignment']
    self[who]['itemsum'] = int(self[who]['itemsum']*factor[align]/factor[old])
    self.adjust_total_time_by_alignment(who, epoch, increase=True)

  def apply_attribute_modifications(self, attrib_list_changes, epoch):
    if attrib_list_changes:
      what = attrib_list_changes.split(':')
      if len(what)%2 != 1:
        raise SystemExit("Correct format: comma-sep-userlist[:attribN:valueN]*")
      userlist = what[0].split(',')
      for i in xrange(1,len(what),2):
        attrib,value = what[i],what[i+1]
        try:
          value = eval(value)  # Security schmecurity
        except NameError: # Happens when value is 'good' or 'evil' w/o quotes
          pass
        for who in userlist:
          if attrib == 'alignment':
            rpgstats.change_alignment(who, value, epoch)
          else:
            rpgstats[who][attrib] = value
      self.update_offline()

  def next_lines(self, f):
    if self.last_line:
      yield self.last_line
    for line in f:
      self.last_line = line
      yield line

  def parse_lines(self, f):
    last_leveller = None
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
          if self[who]['online']:
            self[who]['timeleft'] += 20*1.14**self[who]['level']
          self.ensure_offline(who, post_epoch, known_offline=True)
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
          if self[who]['online'] != None:
            self[who]['last_logbreak_seen'] = post_epoch
          self.ensure_offline(who, post_epoch, known_offline=False)
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
        self.record_questers(IdlerpgStats.get_people_list(m.group(1)), epoch)
        continue
      m = re.match(r"(.*) have been chosen.*Quest to end in (\d+) days?, (\d{2}):(\d{2}):(\d{2})", line)
      if m:
        quester_list, days, hours, mins, secs = m.groups()
        self.record_questers(IdlerpgStats.get_people_list(quester_list), epoch)
        duration = convert_to_duration(days, hours, mins, secs)
        self.quest_time_left = self.quest_started+duration-now
        continue

      #
      # Check for quest ending
      #
      m = re.match(r".*prudence and self-regard has brought the wrath of the gods upon the realm", line)
      if m:
        self.quest_ended(epoch, successful=False)
        continue
      m = re.match(r".*completed their journey", line)
      if m:
        self.quest_times.append(epoch-self.quest_started)
        self.quest_ended(epoch, successful=True)
        continue
      m = re.match(r".*have blessed the realm by completing their quest", line)
      if m:
        self.quest_ended(epoch, successful=True)
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
        continue

      # Y, the level W Z, is now online from nickname X. Next level in...
      m = re.match(r"(?P<who>.*), the level .*, is now online from nickname (?P<nick>.*). "+nextlvl_re, line)
      if m:
        who = m.group('who')
        self.player[m.group('nick')] = who
        self.handle_timeleft(m, epoch)
        continue

      # Y, the Z, has attained level W! Next level in...
      m = re.match(r"(?P<who>.*), the .*, has attained level (?P<level>\d+)! "+nextlvl_re, line)
      if m:
        who = m.group('who')
        last_leveller = who
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
      m = re.match(r"(?P<attacker>.*) \[\d+/(?P<attacker_sum>\d+)\] has (?P<battle_type>challenged|come upon) (?P<defender>.*) \[\d+/(?P<defender_sum>\d+)\]", line)
      if m:
        attacker, attacker_sum, battle_type, defender, defender_sum = m.groups()
        self.recent['attackers'].append(attacker)
        if defender != 'idlerpg':
          self[defender]['itemsum'] = int(defender_sum)
          self.ensure_online(defender, epoch)
        if attacker != 'idlerpg':
          self[attacker]['itemsum'] = int(attacker_sum)
          self.ensure_online(attacker, epoch)
          if attacker != last_leveller:
            if battle_type == 'challenged':
              possibles = [x for x in self
                           if self[x]['online'] and self[x]['level'] >= 45]
            elif battle_type == 'come upon':
              possibles = [x for x in self if self[x]['online']
                                           and x not in self.questers]
            for x in possibles:
              self[x]['attack_stats'][0] += 1.0/len(possibles)
              self[x]['attack_stats'][1] += 1
            self[attacker]['attack_stats'][2] += 1
          last_leveller = None
        continue

      #
      # Check for alignment
      #

      # X has changed alignment to: \w+.
      m = re.match(r"(?P<who>.*) has changed alignment to: (.*)\.$", line)
      if m:
        who, align = m.groups()
        self.change_alignment(who, align, epoch)
        continue

      # X stole Y's level \d+ .* while they were sleeping!...
      m = re.match(r"(?P<who>.*) stole (?P<victim>.*)'s level (?P<newlvl>\d+) (?P<item>.*) while they were sleeping! .* leaves their old level (?P<oldlvl>\d+) .* behind, which .* then takes.", line)
      if m:
        thief, victim, newlvl, item, oldlvl = m.groups()
        change = int(newlvl)-int(oldlvl)
        self.change_alignment(thief,  'evil', epoch)
        self.change_alignment(victim, 'good', epoch)
        self[thief]['alignment_stats'][2] += 1
        factor = {'good':1.1, 'neutral':1.0, 'evil':0.9}
        self[thief]['itemsum']  += factor[self[thief]['alignment']] *change
        self[victim]['itemsum'] -= factor[self[victim]['alignment']]*change

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
        self.change_alignment(who, 'evil', epoch)
        self[who]['alignment_stats'][1] += 1

      # X and Y have not let the iniquities of evil men.*them.  \d+% of their time
      m = re.match(r'(.*?) and (.*?) have not let the iniquities of evil men.*them.*(\d+)% of their time is removed from their clocks', line)
      if m:
        who1, who2, percentage = m.groups()
        self.adjust_timeleft_percentage(who1, epoch, int(percentage))
        self.adjust_timeleft_percentage(who2, epoch, int(percentage))
        self.change_alignment(who1, 'good', epoch)
        self.change_alignment(who2, 'good', epoch)
        self[who1]['alignment_stats'][0] += 1
        self[who2]['alignment_stats'][0] += 1

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
  if math.isinf(seconds) or math.isnan(seconds):
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
             "; Participants: "+','.join(stats.questers)
    else:
      import numpy
      early = time_format(stats.quest_started+numpy.min(stats.quest_times)-now)
      likly = time_format(stats.quest_started+numpy.mean(stats.quest_times)-now)
      return "May end in {}; most likely to end in {}".format(early, likly)+\
             "\nParticipants: "+','.join(stats.questers)
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

def solve_for_flat_slope(ttl, r, p):
  # ttl,p in seconds; burn_rate in days; get common units
  ttl /= 86400.0
  p /= 86400.0

  # Do the computation, convert back to seconds, and return it
  return (p-1)/r * 86400

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

def print_recent_attacker_stats(stats):
  print "Battle statistics: number of times as attacker"
  print "actual  mean  stddev #stdevs character"
  print "------ ------ ------ ------- ---------"
  statinfo = {}
  for who in sorted(stats, key=lambda x:stats[x]['level']):
    # Assume Binomial distribution.  Granted, number of people online and at
    # or above level 45 changes slightly with time making this inexact, but
    # the mean is still correct and we can get an "average" probability p by
    # dividing Np by N, and then just use that.
    Np, N, actual = stats[who]['attack_stats']
    p = Np/N if N != 0 else 0
    mean = Np
    sd = math.sqrt(Np*(1-p)) # stddev, for binomial distribution
    # Compute how many stddevs the actual is away from mean
    Nsds = (actual-mean)/sd if sd > 0 else 0
    statinfo[who] = (actual, mean, sd, Nsds)
  for who in sorted(statinfo, key=lambda x:statinfo[x][3]):
    print "{:6d} {:6.2f} {:6.2f} {:7.3f} ".format(*statinfo[who]) + who

def print_recent_alignment_stats(stats):
  print "Alignment statistics: number of times benefit from alignment"
  print "pray mean stddev #stdevs 4sak mean stddev #stdevs stls #stdevs character"
  print "---- ---- ------ ------- ---- ---- ------ ------- ---- ------- ---------"
  statinfo = {}
  for who in sorted(stats, key=lambda x:stats[x]['level']):
    #print who, stats[who]['alignment_stats'], stats[who]['total_time_stats']

    # Assume Binomial distribution.  Granted, number of people online and at
    # or above level 45 changes slightly with time making this inexact, but
    # the mean is still correct and we can get an "average" probability p by
    # dividing Np by N, and then just use that.
    good_bless_count, evil_forsake_count, evil_steal_count = \
      stats[who]['alignment_stats']
    time_online_good, time_online_neutral, time_online_evil = \
      stats[who]['total_time_stats']

    mean_good = 2*time_online_good/86400.0/12 # Twice every 12 days
    mean_evil = time_online_evil/86400.0/16 # 1/16 days for both forsake,steal

    # Since these are checked every self_clock seconds, these binomial
    # distributions are close enough to the poisson distribution limit
    # that we'll just round off and treat it as the latter for the
    # stddev calculations.
    std_good = math.sqrt(mean_good)
    std_evil = math.sqrt(mean_evil)

    # Compute how many stddevs the actual is away from mean
    Nsds_good    = (good_bless_count  -mean_good)/std_good if std_good>0 else 0
    Nsds_forsake = (evil_forsake_count-mean_evil)/std_evil if std_evil>0 else 0
    Nsds_steal   = (evil_steal_count  -mean_evil)/std_evil if std_evil>0 else 0

    statinfo[who] = (good_bless_count,   mean_good, std_good, Nsds_good,
                     evil_forsake_count, mean_evil, std_evil, Nsds_forsake,
                     evil_steal_count,   Nsds_steal)
  for who in sorted(statinfo, key=lambda x:statinfo[x][3]):
    print "{:4d} {:4.1f} {:6.2f} {:7.3f} {:4d} {:4.1f} {:6.2f} {:7.3f} {:4d} {:7.3f} ".format(*statinfo[who]) + who

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

def show_quit_strategy(stats, quitters):
  penalties = {}
  for who in stats:
    if not stats[who]['online']:
      continue
    penrate = 16 if who == quitters[0] else 15
    mult = 0.75 if who in quitters else 1
    penalty = min(penrate*1.14**stats[who]['level'], 7*86400)
    br1, br2, ab = get_burn_rates(stats, who)

    ettl_finish_opt = solve_ttl_to_0(mult*stats[who]['timeleft'], br1, 0)
    ettl_quit_opt = solve_ttl_to_0(penalty+stats[who]['timeleft'], br1, 0)

    ettl_finish_exp = solve_ttl_to_0(mult*stats[who]['timeleft'], br2, ab)
    ettl_quit_exp = solve_ttl_to_0(penalty+stats[who]['timeleft'], br2, ab)
    penalties[who] = (ettl_quit_opt-ettl_finish_opt,
                      ettl_quit_exp-ettl_finish_exp)

  print "Lvl XtraOptimstc XtraExpected character"
  print "--- ------------ ------------ ---------"
  for who in sorted(penalties, key=lambda x:penalties[x][1]):
    print('{:3d} {} {} {}'.format(
             stats[who]['level'],
             time_format(penalties[who][0]),
             time_format(penalties[who][1]),
             who))

def show_flat_slopes(stats):
  penalties = {}
  print "Lvl FlatOptimstc FlatExpected character"
  print "--- ------------ ------------ ---------"
  for who in sorted(stats, key=lambda x:stats[x]['level']):
    #if not stats[who]['online']:
    #  continue
    br1, br2, ab = get_burn_rates(stats, who)

    flat_ttl_opt = solve_for_flat_slope(stats[who]['timeleft'], br1, 0)
    flat_ttl_exp = solve_for_flat_slope(stats[who]['timeleft'], br2, ab)

    print('{:3d} {} {} {}'.format(
             stats[who]['level'],
             time_format(flat_ttl_opt),
             time_format(flat_ttl_exp),
             who))

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
      mycopy[who]['attack_stats']     = stats[who]['attack_stats'][:]
      mycopy[who]['total_time_stats'] = stats[who]['total_time_stats'][:]
      mycopy[who]['alignment_stats']  = stats[who]['alignment_stats'][:]
    for who in stats:
      mycopy[who]['expected_ttls'] = expected_ttl(stats, who)
      mycopy[who]['burnrates'] = compute_burn_info(stats, who)
    comparisons.append(mycopy)

  class ParseEndTime(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      global now
      new_time = current_time if values == 'now' else convert_to_epoch(values)
      old_time, now = now, new_time
      for who in rpgstats:
        if rpgstats[who]['online']:
          rpgstats[who]['timeleft'] -= (new_time-old_time)
          rpgstats.adjust_total_time_by_alignment(who, old_time, increase=True)
      force_parse(rpgstats, irclog)
  class TweakStats(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
      ensure_parsed(rpgstats, irclog)
      rpgstats.apply_attribute_modifications(values, now)
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
                               'plot_levelling', 'flat_slopes'],
                      help='Which kind of info to show')
  parser.add_argument('--quit-strategy', type=str, nargs='?', const='',
                      metavar='QUITTER(S)',
                      help='Show how much everyone will be set back if a quest'
                           ' is quit right now.  Comma-separated QUITTER(s) '
                           'lose out on 25%% bonus.  quitter1 gets p16 instead '
                           'of p15.  Current questers assumed if none specifed,'
                           ' but none get the p16 penalty.')
  parser.add_argument('--compare', action=RecordForComparison,
                      default=0, nargs=0,
                      help='Record stats for comparison')
  args = parser.parse_args()
  ensure_parsed(rpgstats, irclog)
  if args.quit_strategy is not None:
    args.show = 'quit-strategy'
    if not args.quit_strategy:
      questers = rpgstats.questers[:]
      priority_quitters = ('elijah','Atychiphobe')
      for person in priority_quitters:
        if person in questers:
          questers.remove(person)
          questers.insert(0,person)
          break
      args.quit_strategy = ','.join(questers)
      if not any(x in questers for x in priority_quitters):
        args.quit_strategy = ','+args.quit_strategy
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
      rpgstats[who]['attack_stats'] = list(operator.sub(*x) for x in
                                zip(comparisons[1][who]['attack_stats'],
                                    comparisons[0][who]['attack_stats']))
      rpgstats[who]['total_time_stats'] = list(operator.sub(*x) for x in
                                zip(comparisons[1][who]['total_time_stats'],
                                    comparisons[0][who]['total_time_stats']))
      rpgstats[who]['alignment_stats'] = list(operator.sub(*x) for x in
                                zip(comparisons[1][who]['alignment_stats'],
                                    comparisons[0][who]['alignment_stats']))
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
  return args


rpgstats = IdlerpgStats(40)
with open('/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log') as f:
  args = parse_args(rpgstats, f)
if args.show == 'summary':
  print_summary_info(rpgstats)
elif args.show == 'burninfo':
  print_detailed_burn_info(rpgstats)
elif args.show == 'recent':
  print_recent(rpgstats.recent['attackers'])
  print_recent(rpgstats.recent['questers'])
  print_recent(rpgstats.recent['godsends'])
  print_recent(rpgstats.recent['calamities'])
  print_recent(rpgstats.recent['hogs'])
  print_recent_attacker_stats(rpgstats)
  print_recent_alignment_stats(rpgstats)
elif args.show == 'levelling':
  print_next_levelling(rpgstats)
elif args.show == 'plot_levelling':
  plot_levels(rpgstats)
elif args.show == 'quit-strategy':
  show_quit_strategy(rpgstats, args.quit_strategy.split(','))
elif args.show == 'flat_slopes':
  show_flat_slopes(rpgstats)
else:
  raise SystemExit("Unrecognized --show flag: "+args.show)
