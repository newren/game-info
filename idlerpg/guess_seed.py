#!/usr/bin/env python

import math
import sys

eps = sys.float_info.epsilon
a = 0x5DEECE66D
c = 0xB
m = 2**48

def calculate_interval(r,p):
  return [int(math.ceil( (r+0.0)*m/p*(1-5*eps))),
          int(math.floor((r+1.0)*m/p*(1+5*eps)))]

def subinterval_provider(r, p, intervals):
  new_interval = calculate_interval(r,p)
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

def calculate_interval_an_rest(r, p, n):
  interval = calculate_interval(r,p)
  rest = c
  an = a
  for i in xrange(n-1):
    rest = int((a*rest+c)%m)
    an = int((a*an)%m)
  return interval, an, rest

def niter_matches(r, p, values, n):
  interval, an, rest = calculate_interval_an_rest(r, p, n)

  for s, camefrom in values:
    map2 = int((an*s+rest)%m)
    if map2 > interval[0] and map2 < interval[1]:
      yield s, (camefrom,n)

def niter_constrained_less(r, p, values, n):
  interval, an, rest = calculate_interval_an_rest(r-1, p, n)

  for s, camefrom in values:
    map2 = int((an*s+rest)%m)
    if map2 < interval[1]:
      yield s, (camefrom,n+.1)
  

primary_interval = calculate_interval(418,1327)
secondary_intervals = subinterval_provider(227, 877, [primary_interval])
tertiary_intervals = niter_constrained_less(1, 50, secondary_intervals, 2)
quaternary_intervals = niter_matches(7, 20, tertiary_intervals, 3)

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
#    The item improvement came at 05:52:15, which at self_clock=3 seconds
#    per cycle (with some drift) in comparison to 05:43:38 means:
#        (52*60+15 - (43*60+38))/3.0 = 172.33333333333334
#    So it was 172 self_clock cycles later.  This occurred during the 172
#    later cycle, so 171 full cycles and part of the 172nd.  Now, each cycle
#    has 6+6*#online rand() calls assuming no events trigger and no
#    collisions, and there were 13 people online at the time.  Also, the check
#    for godsends is the fourth rand() call in a cycle (for cycle 172), so we
#    can compute that after the battle there were (assuming no collisions):
#        171*(6+6*13) + 4 = 171*84+4 = 14368
#    calls to rand between the battle rand() calls and the yzhou pants godsend.
#
#  Item improvement:
#    godsend odds: rand((4*86400)/$opts{self_clock}) < $online
#                  rand(115200) < 13
#    rand(): choose player
#    rand(10) < 1: we'll do an item improvement
#    int(rand(6)) == 4: set of leggings chosen

quinary_intervals = niter_constrained_less(13, 115200, quaternary_intervals, 3+14368)
senary_intervals = niter_constrained_less(1, 10, quinary_intervals, 3+14368+2)
septenary_intervals = niter_matches(4, 6, senary_intervals, 3+14368+3)

'''
eps = sys.float_info.epsilon
a = 0x5DEECE66D
c = 0xB
m = 2**48
'''

for value, camefrom in septenary_intervals:
  print "Working value found: {}; camefrom: {}".format(value, camefrom)
raise SystemExit("I quit.")

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
