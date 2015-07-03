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
        while map2 <= new_interval[1] and s<=interval[1]:
          yield s, 1, ((s, 0), 1)
          s += 1
          map2 += a

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
        grouped_values = list(grouped_values) # need to iterate num_to_do times
        # Determine the number, n, of rand rolls we are checking
        for n in xrange(prev_n + min_rands, prev_n + min_rands + num_to_do):
          # Calculate (a^n % m) and (sum_i=0^n a^i*c)%m
          an, rest = Random._calculate_an_rest(n)
          # Iterate over grouped values (guaranteed prevn == prev_n)
          for s, prevn, camefrom in grouped_values:
            # Check whether this value works
            map2 = int((an*s+rest)%m)
            if map2 >= interval[0] and map2 <= interval[1]:
              yield s, n, (camefrom,n)
      # Get the next set of values to work on
      nextvalues = list(itertools.islice(values, 512))

  @staticmethod
  def niter_constrained_less(r, p, values, min_rands, num_to_do):
    # The ONLY difference between niter_matches and niter_constrained_less is:
    #   * the if-condition check on the map2 value
    m = Random.m
    interval = Random.calculate_interval(r,p)

    # Work on a set of values at a time
    nextvalues = list(itertools.islice(values, 512))
    while nextvalues:
      # Each item in the list is of the form (s, n, camefrom), we want to
      # group these by same values of n to avoid recalculation of an & rest
      for prev_n, grouped_values in itertools.groupby(nextvalues,
                                                      operator.itemgetter(1)):
        grouped_values = list(grouped_values) # need to iterate num_to_do times
        # Determine the number, n, of rand rolls we are checking
        for n in xrange(prev_n + min_rands, prev_n + min_rands + num_to_do):
          # Calculate (a^n % m) and (sum_i=0^n a^i*c)%m
          an, rest = Random._calculate_an_rest(n)
          # Iterate over grouped values (guaranteed prevn == prev_n)
          for s, prevn, camefrom in grouped_values:
            # Check whether this value works
            map2 = int((an*s+rest)%m)
            if map2 < interval[0]:
              yield s, n, (camefrom,n)
      # Get the next set of values to work on
      nextvalues = list(itertools.islice(values, 512))

  @staticmethod
  def compute_possibilities_helper(limiters, interval):
    nextiter = Random.initial_subinterval(limiters[1][1],limiters[1][2],
                                           [interval])
    for lvl in xrange(2,len(limiters)):
      if limiters[lvl][0] == 'equal':
        nextiter = Random.niter_matches(limiters[lvl][1], limiters[lvl][2],
                                        nextiter,
                                        limiters[lvl][3], limiters[lvl][4])
      elif limiters[lvl][0] == 'less':
        nextiter = Random.niter_constrained_less(
                                        limiters[lvl][1], limiters[lvl][2],
                                        nextiter,
                                        limiters[lvl][3], limiters[lvl][4])
      else:
        raise SystemExit("Invalid limiter type: "+limiters[lvl][0])
    return nextiter

  @staticmethod
  def compute_possibilities(limiters):
    def execute_on_subinterval(limiters, subinterval, result_queue):
      for result in Random.compute_possibilities_helper(limiters, subinterval):
        result_queue.put(result)

    assert limiters[0][0]=='equal' and limiters[0][3]==1 and limiters[0][4]==1
    assert limiters[1][0]=='equal' and limiters[1][3]==1 and limiters[1][4]==1
    primary = Random.calculate_interval(limiters[0][1],limiters[0][2])

    np = multiprocessing.cpu_count()/2
    per_proc_check = int(math.ceil((primary[1]-primary[0]+1.0)/np))

    result_queue = multiprocessing.Queue()
    procs = []
    for i in xrange(np):
      interval = [                primary[0]+(i+0)*per_proc_check,
                  min(primary[1], primary[0]+(i+1)*per_proc_check-1)]
      proc = multiprocessing.Process(target=execute_on_subinterval,
                                     args=(limiters, interval, result_queue))
      proc.start()
      procs.append(proc)
    for proc in procs:
      proc.join()
    result_queue.put('DONE')
    return iter(result_queue.get, 'DONE')

  @staticmethod
  def serial_compute_possibilities(limiters):
    assert limiters[0][0]=='equal' and limiters[0][3]==1 and limiters[0][4]==1
    assert limiters[1][0]=='equal' and limiters[1][3]==1 and limiters[1][4]==1

    primary = Random.calculate_interval(limiters[0][1],limiters[0][2])
    return Random.compute_possibilities_helper(limiters, primary)

  @staticmethod
  def compute_possibilities_from_hourly_battles(num_players, rolls):
    hrc = 10 # hidden rand calls, such as from map collisions or mystery rolls
    assert(len(rolls)%2==0)
    limiters =     [['equal', rolls[0][0], rolls[0][1], 1, 1]]
    limiters.append(['equal', rolls[1][0], rolls[1][1], 1, 1])
    for lvl in xrange(2,len(rolls),2):
      battle_rolls = 8 if rolls[lvl-2][0] > rolls[lvl-1][0] else 6
      limiters.append(['equal', rolls[lvl  ][0], rolls[lvl  ][1],
                                7200*(1+num_players)+battle_rolls-1, 1+hrc])
      limiters.append(['equal', rolls[lvl+1][0], rolls[lvl+1][1], 1, 1])
    return Random.compute_possibilities(limiters)

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

def handle_local_case_a():
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
  calculate_with_known_quantities()
  rolls = [[ 81,  353], [367,  439],
           [312,  439], [254,  440],
           [104,  353], [386,  440],
           [303,  353], [176,  439]]
  print(list(Random.compute_possibilities_from_hourly_battles(2, rolls)))
  # answer: [(64992717279993, 64821, ((((((((64992717279993, 0), 1), 21606), 21607), 43214), 43215), 64820), 64821))]
  raise SystemExit("done.")

def handle_original_case_b():
  #2015-04-18 21:56:39 <idlerpg>   yzhou [352/879] has challenged nebkor [567/581] in combat and lost! 0 days, 15:18:52 is added to yzhou's clock.
  #2015-04-18 21:56:42 <idlerpg>   yzhou reaches next level in 9 days, 18:05:38.
  #2015-04-18 22:56:37 <idlerpg>   j [611/987] has challenged yzhou [770/879] in combat and lost! 0 days, 08:08:03 is added to j's clock.
  #2015-04-18 22:56:37 <idlerpg>   j reaches next level in 3 days, 17:28:34.
  #2015-04-18 23:56:41 <idlerpg>   elijah [34/791] has challenged pef [224/889] in combat and lost! 0 days, 09:07:58 is added to elijah's clock.
  #2015-04-18 23:56:41 <idlerpg>   elijah reaches next level in 3 days, 20:09:35.
  #2015-04-19 00:56:44 <idlerpg>   Sessile [186/1327] has challenged kverdieck [556/693] in combat and lost! 0 days, 09:57:27 is added to Sessile's clock.
  #2015-04-19 00:56:44 <idlerpg>   Sessile reaches next level in 4 days, 13:31:57.
  #2015-04-19 01:23:13 <idlerpg>   j, kelsey, elijah, and yzhou have been chosen by the gods to rescue the beautiful princess Juliet from the grasp of the beast Grabthul. Participants must first reach [167,458], then [325,270].
  rolls = [[352,  879], [567,  581],
           [611,  987], [770,  879],
           [ 34,  791], [224,  889],
           [186, 1327], [556,  693]]
  print(list(Random.compute_possibilities_from_hourly_battles(13, rolls)))
  # answer: [(112858162602330, 302419, ((((((((112858162602330, 0), 1), 100806), 100807), 201612), 201613), 302418), 302419))]
  raise SystemExit("I quit.")

def handle_original_case_a():
  #2015-04-08 21:14:21 <idlerpg>   kverdieck, Sessile, elijah, and nebkor have been chosen by the gods to locate the centuries-lost tomes of the grim prophet Haplashak Mhadhu. Quest to end in 0 days, 14:31:59.
  #...
  #2015-04-09 05:43:38 <idlerpg>   Sessile [418/1327] has challenged dlaw [227/877] in combat and won! 1 day, 00:54:47 is removed from Sessile's clock.
  #2015-04-09 05:43:38 <idlerpg>   Sessile reaches next level in 4 days, 10:12:32.
  #2015-04-09 05:43:38 <idlerpg>   Sessile has dealt dlaw a Critical Strike! 1 day, 10:24:22 is added to dlaw's clock.
  #2015-04-09 05:43:38 <idlerpg>   dlaw reaches next level in 13 days, 09:07:30.
  #2015-04-09 05:52:15 <idlerpg>   The local wizard imbued yzhou's pants with a Spirit of Fortitude! yzhou's set of leggings gains 10% effectiveness.
  #2015-04-09 06:43:42 <idlerpg>   dlaw [771/877] has challenged trogdor [217/365] in combat and won! 1 day, 08:00:44 is removed from dlaw's clock.
  #2015-04-09 06:43:42 <idlerpg>   dlaw reaches next level in 12 days, 00:06:43.
  #2015-04-09 07:23:56 <idlerpg>   elijah met up with a mob hitman for not paying their bills. This terrible calamity has slowed them 0 days, 11:05:06 from level 72.
  #2015-04-09 07:23:56 <idlerpg>   elijah reaches next level in 9 days, 16:47:19.
  #2015-04-09 07:43:51 <idlerpg>   pef [701/889] has challenged amling [136/366] in combat and won! 0 days, 10:07:43 is removed from pef's clock.
  #2015-04-09 07:43:54 <idlerpg>   pef reaches next level in 3 days, 09:56:59.
  #
  # So:
  #  Inital battle:
  #    418/1327
  #    227/877
  #    CS : 0/50 (1 out of 50, means given 50 roll a 0)
  #    Gain : 12%  (7/20)
  # 13 players, 1 item godsend, 8 battle_rolls but 4 counted: ((1+13)*7200)+(3)+(8-4)
  # 13 players, 1 time calamity, 8 battle_rolls but 1 counted: ((1+13)*7200)+(3+31)+(8-1)
  limiters = [
              ['equal', 418, 1327, 1, 1],
              ['equal', 227,  877, 1, 1],
              # There IS a mystery rand() call in the version of challenge_opp()
              # running at Palantir and it comes BEFORE the crit-check.  So, the
              # crit-check rand() call is TWO after the defender rand() roll.
              ['less',    1,   50, 2, 1],
              ['equal',   7,   20, 1, 1],
              ['equal', 771,  877, ((1+13)*7200)+(3)+(8-4), 5],
              ['equal', 217,  365, 1, 1],
              ['equal', 701,  889, ((1+13)*7200)+(3+31)+(8-1), 5],
              ['equal', 136,  366, 1, 1]
             ]
  print(list(Random.compute_possibilities(limiters)))
  # answer: [(88813367205766, 201654, ((((((((88813367205766, 0), 1), 3), 4), 100811), 100812), 201653), 201654))]

  # The way I discovered the mystery rand() call was failing to find any solution
  # here, finding a solution with four sequential lost battles which uniformly
  # showed one more rand() call than expected.  That could have been "luck" from
  # random collisions, but advancing that rand seed forward to check for other
  # battles showed that the one extra roll always seemed to be there -- for both
  # wins and losses.  So I knew there was a mystery rand() call, though for some
  # reason I assumed it came after the crit-check and steal-check and whatnot.
  # Then I traced the rand seed backward to this particular battle only looking
  # at attacker and defender rolls.  That gave me a seed.  Using that seed, the
  # roll after the defender roll didn't satisfy the crit check.  Horribly
  # disappointed yet again, I checked the one after it to see if I at least
  # got 7/20.  When I saw the value 0.20, a light went on.  What if the mystery
  # roll where immediately after the defender roll?  Some simple checking showed
  # that this theory provided a solution:
  ## >>> doit(-22465140+0, 1327)
  ## 418.70627243430465
  ## >>> (doit.seed, doit.current_count)
  ## (88813367205766, -22465140)
  ## >>> doit(-22465140+1, 877)
  ## 227.48926350285697
  ## >>> doit(-22465140+3, 50)   # +3 because mystery roll is BEFORE crit-check
  ## 0.5181060083023326
  ## >>> doit(-22465140+4, 20)
  ## 7.265487860984905
  ## >>> doit(-22465140+100811, 877)         # 100811 obtained elsewhere
  ## 771.2186812479423
  ## >>> doit(-22465140+100812, 365)
  ## 217.38324898535328
  ## >>> doit(-22465140+100811+100842, 889)  # 100842 also obtained elsewhere
  ## 701.7135076356064
  ## >>> doit(-22465140+100811+100842+1, 366)
  ## 136.62686666197257
  raise SystemExit("I quit.")

def handle_early_april_case():
  rolls = [[597,  684], [ 79, 1208],
           [201,  439], [ 71,  553],
           [814,  904], [329,  835],
           [212,  553], [398,  439]]
  print(list(Random.compute_possibilities_from_hourly_battles(15, rolls)))
  # answer: [(245748858511197, 345628, ((((((((245748858511197, 0), 1), 115211), 115212), 230419), 230420), 345627), 345628))]
  raise SystemExit("done.")

def handle_funny_case():
  ##                                  2015-04-21 21:34:59 <idlerpg>  amling, kverdieck, Sessile, and yzhou have completed their journey! 25% of their burden is eliminated.
  ##                                  2015-04-21 21:53:59 <idlerpg>  yzhou [186/879] has come upon amling [94/369] and taken them in combat! 0 days, 08:54:32 is removed from yzhou's clock.
  ##                                  2015-04-21 21:53:59 <idlerpg>  yzhou reaches next level in 3 days, 00:04:55.
  ##  59570471548846   6852276  99784 2015-04-21 22:00:41 <idlerpg>  pef [188/889] has challenged yzhou [584/879] in combat and lost! 4 days, 20:55:24 is added to pef's clock.
  ##                                  2015-04-21 22:00:41 <idlerpg>  pef reaches next level in 53 days, 14:09:29.
  ## 122335122154465   6957173 104897 2015-04-21 23:00:44 <idlerpg>  kelsey [310/714] has challenged trogdor [187/418] in combat and won! 0 days, 08:50:06 is removed from kelsey's clock.
  ##                                  2015-04-21 23:00:44 <idlerpg>  kelsey reaches next level in 2 days, 23:29:01.
  ## 245036831844132   7068290 111117 2015-04-22 00:00:47 <idlerpg>  pef [773/889] has challenged elijah [274/791] in combat and won! 9 days, 02:18:23 is removed from pef's clock.
  ##                                  2015-04-22 00:00:47 <idlerpg>  pef reaches next level in 44 days, 09:51:00.
  ##  28883331871975   7176299 108009 2015-04-22 01:00:51 <idlerpg>  yzhou [90/879] has challenged pef [54/889] in combat and won! 0 days, 13:06:13 is removed from yzhou's clock.
  ##                                  2015-04-22 01:00:51 <idlerpg>  yzhou reaches next level in 2 days, 07:51:49.
  ## 256385259375727   7284307 108008 2015-04-22 02:00:55 <idlerpg>  nebkor [529/581] has challenged Sessile [79/1327] in combat and won! 5 days, 22:53:11 is removed from nebkor's clock.
  ##                                  2015-04-22 02:00:55 <idlerpg>  nebkor reaches next level in 23 days, 19:32:44.

  rolls = [[188,889], [584,879],
           [310,714], [187,418],
           [773,889], [274,791],
           [ 90,879], [ 54,889],
           [529,581], [ 79,1327]]
  print(list(Random.compute_possibilities_from_hourly_battles(15, rolls)))
  # answer: [(245748858511197, 345628, ((((((((245748858511197, 0), 1), 115211), 115212), 230419), 230420), 345627), 345628))]
  raise SystemExit("done.")

#handle_local_case_a()
#handle_original_case_b()
#handle_original_case_a()
#handle_early_april_case()
handle_funny_case()

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

# No solution when hrc in set(1,4,5)
check_values([88675141333930, 88730764249721], 0)
check_values([88732726299080], 2)
check_values([88759129600895], 3)
check_values([88832312860209], 6)
check_values([88730108276003], 8)
check_values([88723502212290, 88754264960240], 9)
check_values([88682430352412], 12)
check_values([88685261265828], 13)

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
