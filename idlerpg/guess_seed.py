#!/usr/bin/env python

import functools
import itertools
import operator
import math
import re
import sys
from collections import Counter
import multiprocessing

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
      map2 = int((a*s+c)%m)
      while s <= interval[1]:
        if map2 < new_interval[0]:
          s += 1+int(math.ceil((new_interval[0]  -map2)/a*(1-5*eps)))
          map2 = int((a*s+c)%m)
          assert map2-a < new_interval[0]
          assert map2 > new_interval[0] and map2 < new_interval[1]
        if map2 > new_interval[1]:
          s += 1+int(math.ceil((new_interval[0]+m-map2)/a*(1-5*eps)))
          if s > interval[1]:
            return
          map2 = int((a*s+c)%m)
          assert map2-a < new_interval[0]
          assert map2 > new_interval[0] and map2 < new_interval[1]
        while map2 < new_interval[1]:
          yield s, 1, s
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
  def _calculate_an_rest(n):
    if n in Random.apower_cache:
      rest, an = Random.apower_cache[n]
    else:
      a,c,m = Random.a,Random.c,Random.m
      try:
        calced = max(x for x in Random.apower_cache.keys() if x < n)
        rest, an = Random.apower_cache[calced]
      except ValueError:
        calced = 1
        rest = c
        an = a
      for i in xrange(n-calced):
        rest = int((a*rest+c)%m)
        an = int((a*an)%m)
      Random.apower_cache[n] = (rest, an)
    return an, rest

  @staticmethod
  def niter_matches(r, p, values, min_rands, num_to_do):
    m = Random.m
    interval = Random.calculate_interval(r,p)

    # Work on a set of values at a time
    nextvalues = list(itertools.islice(values, 512))
    while nextvalues:
      # Each item in the list is of the form (s, n, camefrom), we want to
      # group these by same values of n to avoid recalculation of an & rest
      for prev_n, grouped_values in itertools.groupby(nextvalues,
                                                      operator.itemgetter(1)):
        # Determine the number, n, of rand rolls we are checking
        for n in xrange(prev_n + min_rands, prev_n + min_rands + num_to_do):
          # Calculate (a^n % m) and (sum_i=0^n a^i*c)%m
          an, rest = Random._calculate_an_rest(n)
          # Iterate over grouped values (guaranteed prevn == prev_n)
          for s, prevn, camefrom in grouped_values:
            # Check whether this value works
            map2 = int((an*s+rest)%m)
            if map2 > interval[0] and map2 < interval[1]:
              yield s, n, (camefrom,n)
      # Get the next set of values to work on
      nextvalues = list(itertools.islice(values, 512))

  @staticmethod
  def nth_call_matches(r, p, n, value):
    m = Random.m
    interval, an, rest = Random._calculate_interval_an_rest(r, p, n)

    s = value
    map2 = int((an*s+rest)%m)
    if map2 > interval[0] and map2 < interval[1]:
      return True
    return False

  @staticmethod
  def foobar(r, p, n, extran, values):
    m = Random.m

    for s, prev_n, camefrom in values:
      for j in xrange(extran):
        cur_n = prev_n+n+j
        interval, an, rest = Random._calculate_interval_an_rest(r, p, cur_n)
        map2 = int((an*s+rest)%m)
        if map2 > interval[0] and map2 < interval[1]:
          yield s, cur_n, (camefrom,cur_n)

  @staticmethod
  def compute_possibles(matches):
    sentinel = 'DONE'
    def execute(func, input_queue, output_queues):
      for result in func(iter(input_queue.get, sentinel)):
        for output in output_queues:
          output.put(result)
      for output in output_queues:
        output.put(sentinel)

    assert matches[0][0]=='equal' and matches[0][3]==0 and matches[0][4]==1
    assert matches[1][0]=='equal' and matches[1][3]==1 and matches[1][4]==1

    qs = []
    for i in xrange(len(matches)):
      qs.append(multiprocessing.Queue())
      pass
    primary = Random.calculate_interval(matches[0][1],matches[0][2])
    qs[0].put(primary)
    qs[0].put(sentinel)
    ps = []
    proc = multiprocessing.Process(target=functools.partial(
                            execute,
                            functools.partial(Random.initial_subinterval,
                                              matches[1][1], matches[1][2]),
                            qs[0], [qs[1]]))
    proc.start()
    ps.append(proc)
    for i in xrange(2,len(matches)):
      style, r, p, n, extra_n = matches[i]
      proc = multiprocessing.Process(target=functools.partial(
                              execute,
                              functools.partial(Random.foobar,
                                                r, p, n, extra_n),
                              qs[i-1], [qs[i]]))
      proc.start()
      ps.append(proc)
    for item in iter(qs[len(matches)-1].get, sentinel):
      print item


  @staticmethod
  def compute_possibilities(matches):
    calls = Counter()
    def handle_level(lvl, base_n, value):
      calls[lvl] += 1
      if lvl == len(matches):
        print "Found match: {}".format(value)
        return
      r, p, base_inc, num_to_do = matches[lvl][1:]
      for j in xrange(base_n+base_inc, base_n+base_inc+num_to_do):
        if Random.nth_call_matches(r, p, j, value):
          handle_level(lvl+1, j, value)

    assert matches[0][0]=='equal' and matches[0][3]==0 and matches[0][4]==1
    assert matches[1][0]=='equal' and matches[1][3]==1 and matches[1][4]==1

    primary = Random.calculate_interval(matches[0][1],matches[0][2])
    secondary = Random.initial_subinterval(matches[1][1],matches[1][2],
                                           [primary])
    for value, camefrom in secondary:
      handle_level(2, 1, value)
    for x in calls:
      print "Calls to handle_level[{}] = {}".format(x, calls[x])

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

def calc_rand48(seed, ntimes):
  for i in xrange(ntimes):
    seed = int((Random.a*seed+Random.c)%Random.m)
  return seed
def count_hops(initial_seed, final_seed):
  count = 1
  v = Random()
  v.set_seed(initial_seed)
  while v.drand48() != final_seed:
    count += 1
  return count

#<idlerpg> Rand: 224491502306380
#<idlerpg> newren [81/353] has challenged other [367/439] in combat and lost! 0 days, 06:19:44 is added to newren's clock.
#<idlerpg> newren reaches next level in 4 days, 00:44:39.
#<idlerpg> Rand: 126166889533354
#<idlerpg> other [312/439] has challenged idlerpg [254/440] in combat and won! 0 days, 07:25:49 is removed from other's clock.
#<idlerpg> other reaches next level in 1 day, 05:43:16.
#<idlerpg> Rand: 265930535560594
#<idlerpg> newren [104/353] has challenged idlerpg [386/440] in combat and lost! 0 days, 08:40:10 is added to newren's clock.
#<idlerpg> newren reaches next level in 3 days, 23:21:56.
#<idlerpg> Rand: 277450753605568
#<idlerpg> newren [303/353] has challenged other [176/439] in combat and won! 0 days, 10:22:48 is removed from newren's clock.
#<idlerpg> newren reaches next level in 3 days, 11:59:02.

def calculate_with_known_quantities():
  randcounts=[224491502306380,126166889533354,265930535560594,277450753605568]
  for pair in zip(randcounts, randcounts[1:]):
    print(pair)
    print "Hops: {}, 3-after: {}".format(count_hops(pair[0], pair[1]),
                                         calc_rand48(pair[0], 3))
  v = Random()
  v.set_seed(224491502306380)
  assert  81 == int(v.rand(353, 3)); print(v.seed)
  assert 367 == int(v.rand(439, 1)); print(v.seed)
  assert 312 == int(v.rand(439, 21606-1)); print(v.seed)
  assert 254 == int(v.rand(440, 1)); print(v.seed)
  assert 104 == int(v.rand(353, 21608-1)); print(v.seed)
  assert 386 == int(v.rand(440, 1)); print(v.seed)
  assert 303 == int(v.rand(353, 21606-1)); print(v.seed)
  assert 176 == int(v.rand(439, 1)); print(v.seed)
  print "Basic checks passed"

def faster_compute():
  primary_interval = Random.calculate_interval(81,353)
  secondary_intervals = Random.initial_subinterval(367, 439, [primary_interval])
  tertiary_intervals = Random.niter_matches(312, 439,
                                            secondary_intervals, 21606-1, 2)
  quaternary_intervals = Random.niter_matches(254, 440,
                                              tertiary_intervals, 1, 2)
  quinary_intervals = Random.niter_matches(104, 353,
                                           quaternary_intervals, 21608-1, 2)
  senary_intervals = Random.niter_matches(386, 440,
                                          quinary_intervals, 1, 2)
  septenary_intervals = Random.niter_matches(303, 353,
                                             senary_intervals, 21606-1, 2)
  octenary_intervals = Random.niter_matches(176, 439,
                                            septenary_intervals, 1, 2)
  return octenary_intervals

def slower_compute():
  Random.compute_possibilities([['equal',   81,  35300, 0,        1],
                                ['equal',  367,  439, 1,        1],
                                ['equal',  312,  439, 21606-1,  1],
                                ['equal',  254,  440, 1,        1],
                                ['equal',  104,  353, 21608-2,  1],
                                ['equal',  386,  440, 1,        1],
                                ['equal',  303,  353, 21606-2,  1],
                                ['equal',  176,  439, 1,        1]])

calculate_with_known_quantities()
fast = True
if fast:
  print(list(faster_compute()))
else:
  slower_compute()
raise SystemExit("done.")

#2015-04-18 21:56:39 <idlerpg>   yzhou [352/879] has challenged nebkor [567/581] in combat and lost! 0 days, 15:18:52 is added to yzhou's clock.
#2015-04-18 21:56:42 <idlerpg>   yzhou reaches next level in 9 days, 18:05:38.
#2015-04-18 22:56:37 <idlerpg>   j [611/987] has challenged yzhou [770/879] in combat and lost! 0 days, 08:08:03 is added to j's clock.
#2015-04-18 22:56:37 <idlerpg>   j reaches next level in 3 days, 17:28:34.
#2015-04-18 23:56:41 <idlerpg>   elijah [34/791] has challenged pef [224/889] in combat and lost! 0 days, 09:07:58 is added to elijah's clock.
#2015-04-18 23:56:41 <idlerpg>   elijah reaches next level in 3 days, 20:09:35.
#2015-04-19 00:56:44 <idlerpg>   Sessile [186/1327] has challenged kverdieck [556/693] in combat and lost! 0 days, 09:57:27 is added to Sessile's clock.
#2015-04-19 00:56:44 <idlerpg>   Sessile reaches next level in 4 days, 13:31:57.
#2015-04-19 01:23:13 <idlerpg>   j, kelsey, elijah, and yzhou have been chosen by the gods to rescue the beautiful princess Juliet from the grasp of the beast Grabthul. Participants must first reach [167,458], then [325,270].

Random.compute_possibles([['equal',  352,  879, 0,        1],
                              ['equal',  567,  581, 1,        1],
                              ['equal',  611,  987, 100805-1, 1],
                              ['equal',  770,  879, 1,        1],
                              ['equal',   34,  791, 100805-1, 1],
                              ['equal',  224,  889, 1,        1],
                              ['equal',  186, 1327, 100805-1, 1],
                              ['equal',  556,  693, 1,        1]])
raise SystemExit("done.")

Random.compute_possibilities([['equal',  352,  879, 0,        1],
                              ['equal',  567,  581, 1,        1],
                              ['equal',  611,  987, 100805-1, 1],
                              ['equal',  770,  879, 1,        1],
                              ['equal',   34,  791, 100805-1, 1],
                              ['equal',  224,  889, 1,        1],
                              ['equal',  186, 1327, 100805-1, 1],
                              ['equal',  556,  693, 1,        1]])
print "Hello world"
compute_alternate_possibilities()
raise SystemExit("I quit")

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
