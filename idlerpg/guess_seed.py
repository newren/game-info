#!/usr/bin/env python

import math
import re
import sys

class Random:
  eps = sys.float_info.epsilon
  a = 0x5DEECE66D
  c = 0xB
  m = 2**48
  seed = None
  apower_cache = {}

  @staticmethod
  def calculate_interval(r,p):
    m,eps = Random.m, Random.eps
    return [int(math.ceil( (r+0.0)*m/p*(1-5*eps))),
            int(math.floor((r+1.0)*m/p*(1+5*eps)))]

  @staticmethod
  def initial_subinterval(r, p, intervals):
    a,c,m,eps = Random.a, Random.c, Random.m, Random.eps
    new_interval = Random.calculate_interval(r,p)
    assert new_interval[1] - new_interval[0] > 2*a
    for interval in intervals:
      s=interval[0]
      possibilities = []
      while s <= interval[1]:
        map2 = int((a*s+c)%m)
        if map2 < new_interval[0]:
          s += 1+int(math.ceil((new_interval[0]  -map2)/a*(1-5*eps)))
          map2 = int((a*s+c)%m)
          assert map2-a < new_interval[0]
          assert map2 > new_interval[0] and map2 < new_interval[1]
        if map2 > new_interval[1]:
          s += 1+int(math.ceil((new_interval[0]+m-map2)/a*(1-5*eps)))
          map2 = int((a*s+c)%m)
          assert map2-a < new_interval[0]
          assert map2 > new_interval[0] and map2 < new_interval[1]
        while map2 < new_interval[1]:
          yield s, s
          s += 1
          map2 += a

  @staticmethod
  def _calculate_interval_an_rest(r, p, n):
    interval = Random.calculate_interval(r,p)
    if n in Random.apower_cache:
      rest, an = Random.apower_cache[n]
    else:
      a,c,m = Random.a,Random.c,Random.m
      try:
        calced = max(x for x in Random.apower_cache.keys() if x < n)
        rest, an = Random.apower_cache[calced]
      except ValueError:
        calced = 0
        rest = c
        an = a
      for i in xrange(n-calced):
        rest = int((a*rest+c)%m)
        an = int((a*an)%m)
      Random.apower_cache[n] = (rest, an)
    return interval, an, rest

  @staticmethod
  def niter_matches(r, p, values, n):
    m = Random.m
    interval, an, rest = Random._calculate_interval_an_rest(r, p, n)

    for s, camefrom in values:
      map2 = int((an*s+rest)%m)
      if map2 > interval[0] and map2 < interval[1]:
        yield s, (camefrom,n)

  @staticmethod
  def niter_constrained_less(r, p, values, n):
    m = Random.m
    interval, an, rest = Random._calculate_interval_an_rest(r-1, p, n)

    for s, camefrom in values:
      map2 = int((an*s+rest)%m)
      if map2 < interval[1]:
        yield s, (camefrom,n+.1)

  def set_seed(self, seed):
    assert seed < self.m and seed > 0 and seed == int(seed)
    self.seed = seed

  def rand(self, value, ncalls = 1):
    for i in xrange(ncalls):
      self.seed = int((self.a*self.seed+self.c)%self.m)
    return (self.seed*value+0.0)/self.m

  def drand48(self):
    self.seed = int((self.a*self.seed+self.c)%self.m)
    return self.seed

def count_hops(initial_seed, final_seed):
  count = 1
  v = Random()
  v.set_seed(initial_seed)
  while v.drand48() != final_seed:
    count += 1
  return count

if False:
  seeds = []
  with open('channel-logs.txt') as f:
    for match in re.findall('Rand: ([0-9]+)$', f.read(), flags=re.MULTILINE):
      seeds.append(int(match))
  for i in xrange(len(seeds)-1):
    print "Hops from {:15d} to {:15d}: {:5d}".format(seeds[i], seeds[i+1], count_hops(*seeds[i:i+2]))
  hops1 = count_hops(39683077794122, 159171233202994)
  hops2 = count_hops(245341444106138, 132969526621058)
  raise SystemExit("Hops = {}, {}".format(hops1, hops2))

def check_values(values, hrc=0):
  v = Random()
  def check_value(v):
    assert int((v.seed*1327+0.0)/v.m) == 418
    assert int(v.rand(877)) == 227
    assert v.rand(50) < 1
    assert int(v.rand(20)) == 7
  #  for i in xrange(14367):
  #    assert v.rand(691200) >= 13
  #  #    raise SystemExit("Failed at {}".format(i))
  #  assert v.rand(115200) < 13
    assert v.rand(115200, 14371-4+hrc) < 13  # -4: four rand() calls above
    assert v.rand(10, 2) < 1
    assert int(v.rand(6)) == 4

    # dlaw [771/877] has challenged trogdor [217/365] in combat and won!
    # Do we get 771?
    maybe = [int(v.rand(877,100810 - 4 - (14371-4) - 2 - 1))]
    for i in xrange(10):  # What if we pretend there were some collisions?
      maybe.append(int(v.rand(877)))
    assert any(x == 771 for x in maybe)

  for x in values:
    v.set_seed(x)
    try:
      check_value(v)
    except AssertionError:
      print "Value {} (when hrc={}) is no good".format(x, hrc)
    else:
      print "Value {} (when hrc={}) works".format(x, hrc)

def compute_possibilities(hrc = 0):
  # hrc == hidden rand() calls, from collisions or whatever
  primary_interval = Random.calculate_interval(418,1327)
  secondary_intervals = Random.initial_subinterval(227, 877, [primary_interval])
  tertiary_intervals = Random.niter_constrained_less(1, 50,
                                                     secondary_intervals, 2)
  quaternary_intervals = Random.niter_matches(7, 20, tertiary_intervals, 3)

  quinary_intervals = Random.niter_constrained_less(13, 115200,
                                                    quaternary_intervals,
                                                    14371+hrc)
  senary_intervals = Random.niter_constrained_less(1, 10,
                                                   quinary_intervals,
                                                   14371+2+hrc)
  septenary_intervals = Random.niter_matches(4, 6, senary_intervals,
                                             14371+3+hrc)

  for value, camefrom in septenary_intervals:
    print "Working value for hrc=={} found: {}; camefrom: {}".format(hrc, value, camefrom)
    check_values([value], hrc)

# No solution when hrc in set(1,4,5)
check_values([88675141333930, 88730764249721], 0)
check_values([88732726299080], 2)
check_values([88759129600895], 3)
check_values([88832312860209], 6)
check_values([88730108276003], 8)
check_values([88723502212290, 88754264960240], 9)
check_values([88682430352412], 12)
check_values([88685261265828], 13)


#Working value for hrc==8 found: 88730108276003; camefrom: (((((88730108276003, 2.1), 3), 14379.1), 14381.1), 14382)
#Value 88730108276003 (when hrc=8) is no good
#Working value for hrc==9 found: 88723502212290; camefrom: (((((88723502212290, 2.1), 3), 14380.1), 14382.1), 14383)
#Value 88723502212290 (when hrc=9) is no good
#Working value for hrc==9 found: 88754264960240; camefrom: (((((88754264960240, 2.1), 3), 14380.1), 14382.1), 14383)
#Value 88754264960240 (when hrc=9) is no good
#Working value for hrc==12 found: 88682430352412; camefrom: (((((88682430352412, 2.1), 3), 14383.1), 14385.1), 14386)
#Value 88682430352412 (when hrc=12) is no good
#Working value for hrc==13 found: 88685261265828; camefrom: (((((88685261265828, 2.1), 3), 14384.1), 14386.1), 14387)
#Value 88685261265828 (when hrc=13) is no good
for hrc in xrange(0,15):
  compute_possibilities(hrc)
raise SystemExit("I quit.")


#2015-04-09 05:43:38 <idlerpg>   Sessile [418/1327] has challenged dlaw [227/877] in combat and won! 1 day, 00:54:47 is removed from Sessile's clock.
#2015-04-09 05:43:38 <idlerpg>   Sessile reaches next level in 4 days, 10:12:32.
#2015-04-09 05:43:38 <idlerpg>   Sessile has dealt dlaw a Critical Strike! 1 day, 10:24:22 is added to dlaw's clock.
#2015-04-09 05:43:38 <idlerpg>   dlaw reaches next level in 13 days, 09:07:30.
#2015-04-09 05:52:15 <idlerpg>   The local wizard imbued yzhou's pants with a Spirit of Fortitude! yzhou's set of leggings gains 10% effectiveness.
#2015-04-09 06:43:42 <idlerpg>   dlaw [771/877] has challenged trogdor [217/365] in combat and won! 1 day, 08:00:44 is removed from dlaw's clock.
#2015-04-09 06:43:42 <idlerpg>   dlaw reaches next level in 12 days, 00:06:43.
#
# So:
#  Inital battle:
#    418/1327
#    227/877
#    CS : 0/50 (1 out of 50, means given 50 roll a 0)
#    Gain : 12%  (7/20)
#
#  Rand calls:
#    There were four rand() calls left, once the battle numbers were to be
#    rolled (attacker roll, defender roll, critical strike, gain
#    percentage), before the next cycle would start.  The item improvement
#    came at 05:52:15, which at self_clock=3 seconds per cycle (with some
#    drift) in comparison to 05:43:38 means:
#        (52*60+15 - (43*60+38))/3.0 = 172.33333333333334
#    So it was 172 self_clock cycles later.  This occurred during the 172
#    later cycle, so 171 full cycles and part of the 172nd.  Now, each cycle
#    has 6+6*#online rand() calls assuming no events trigger and no
#    collisions, and there were 13 people online at the time.  Also, in the
#    cycle with the godsend, there are just 3 rand() calls (hog, team_battle,
#    calamity) before the godsend rand() call, so we
#    can compute that after the battle there were (assuming no collisions):
#        4 + 171*(6+6*13) + 3 = 4+171*84+3 = 14371
#    calls to rand before the yzhou pants godsend.
#
#  Item improvement:
#    godsend odds: rand((4*86400)/$opts{self_clock}) < $online
#                  rand(115200) < 13
#    rand(): choose player
#    rand(10) < 1: we'll do an item improvement
#    int(rand(6)) == 4: set of leggings chosen
#
#  Post-item improvement rand calls:
#    There are 1200 self_clock cycles between battles.  Since there are
#    6+6*#online rand() calls per cycle when no events are triggered and there
#    are no collisions, that means that there are
#      7200+7200*#online
#    rand() calls if there are no events or collisions.  We only had two
#    events (that we know of): a godsend event which added 3 rand() calls,
#    and the hourly battle, which added 7 more (the four discussed earlier,
#    plus choose attacker, choose defender, and choose whether to replace
#    defender with idlerpg).  So we expect
#      3+7+7200+7200*#online
#    rand() calls.  We already handled 14371+4 of them (+4 from item
#    improvement having four rand calls).  There were still
#    2+6*#online calls left in the 172nd cycle.  And then we had 1200-172
#    cycles left, plus the remaining 3 from the next hourly battle choosing
#    the combatants.  This means:
#      (14371+4) + (2+6*13) + (1200-172)*(6+6*13) + 3 = 100810
#    calls, and incidentally
#      7+3+7200+7200*13 = 100810
#    as well.  That brings us to the next battle.  If we just wanted to know
#    the number of calls between the godsend stuff completing and the next
#    battle roll, we'd just leave off the (14371+4) part and get:
#      (2+6*13) + (1200-172)*(6+6*13) + 3 = 86435
#    Again, this all assumes no collisions.


intervals = []
r = 418
p = 1327
interval = [(r+0.0)*m/p*(1-5*eps), (r+1.0)*m/p*(1+5*eps)]
r = 227
p = 877
new_interval = [(r+0.0)*m/p*(1-5*eps), (r+1.0)*m/p*(1+5*eps)]

s=math.ceil(interval[0])
possibilities = []
while s <= math.floor(interval[1]):
  map2 = (a*s+c)%m
  if map2 < new_interval[0]:
    s += math.ceil((new_interval[0]  -map2)/a*(1-5*eps))
  if map2 > new_interval[1]:
    s += math.ceil((new_interval[0]+m-map2)/a*(1-5*eps))
  if (a*s+c)%m < new_interval[0]:  # 1-5eps safety factor might be too much
    s += 1
  map2 = (a*s+c)%m
  assert map2 > new_interval[0] and map2 < new_interval[1]
  while map2 < new_interval[1]:
    possibilities.append(s)
    s += 1
    map2 += a


print len(possibilities)
print min(possibilities)
print max(possibilities)
print sum(possibilities)/len(possibilities)
print sum(interval)/2
print interval


x2 = (a*x1+c)%m
x1 = (x2*km-c)/a
