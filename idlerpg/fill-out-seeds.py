#!/usr/bin/env python

import itertools
import operator
import re
import subprocess

def rand48(seed, ntimes=1):
  a, m = 0x5DEECE66D, 2**48
  for i in xrange(ntimes):
    seed = int((a*seed+0xB)%m)
  return seed
def rand48inv(seed, ntimes=1):
  ainv, m = 246154705703781, 2**48
  for i in xrange(ntimes):
    seed = int(ainv*(seed-0xB)%m)
  return seed
def fl(seed):
  return (seed+0.0)/2**48

solved_seed = 112858162602330
solved_time = '2015-04-18 21:56:39'
solved_num_players = 13

def rand(count, mult):
  change = count-rand.current_count
  if change<0:
    rand.seed = rand48inv(rand.seed, -change)
  else:
    rand.seed = rand48(rand.seed, change)
  rand.current_count = count
  return fl(rand.seed)*mult

rand.seed = solved_seed
rand.current_count = 0

seed = {}
output = subprocess.check_output(['grep', '-A999999', 'BEGIN.LOGGING.*Wed Apr  1',
                          '/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log'])
all_lines = output.splitlines()


solved_idx = None
user_count_changes = [0]*len(all_lines)
for idx,line in enumerate(all_lines):
  if line.startswith(solved_time):
    solved_idx = idx
  if 'has joined' in line:
    user_count_changes[idx] = 1
  elif 'has quit' in line:
    user_count_changes[idx] = -1

def advance_seed(line, cur_players, direction=1):
  global last_count
  print "Called advance_seed with {}, {}".format(cur_players, direction)+line
  assert cur_players > 0
  possible_seeds = []
  m = re.match(r"(?P<attacker>.*) \[(?P<attacker_roll>\d+)/(?P<attacker_sum>\d+)\] has challenged (?P<defender>.*) \[(?P<defender_roll>\d+)/(?P<defender_sum>\d+)\]", line)
  if not m:
    return

  attacker, aroll, asum, defender, droll, dsum = m.groups()
  aroll, asum, droll, dsum = int(aroll), int(asum), int(droll), int(dsum)
  for x in xrange(last_count+(cur_players-2)*7200-(cur_players*3),
                  last_count+(cur_players+2)*7200,
                  direction):
    if int(rand(x+1, dsum)) == droll and int(rand(x, asum)) == aroll:
      possible_seeds.append((rand.seed, rand.current_count))

  found_seed = (len(possible_seeds) == 1)
  if not found_seed:
    if possible_seeds == [(281054668518238, 5531492), (281074565486939, 5541999)]:
      bla = possible_seeds.pop(0)
      print possible_seeds
      found_seed = True
    if possible_seeds == [(21299609081788, 9585114), (21432503642072, 9591670)]:
      bla = possible_seeds.pop(0)
      print possible_seeds
      found_seed = True
  if not found_seed:
    last = 0
    if len(possible_seeds) > 1:
      for key,value in sorted(seed.iteritems(), key=lambda x:x[1][1]):
        print value[1]-last, value, key
        last = value[1]
      print len(possible_seeds)
      if len(possible_seeds) > 0:
        print possible_seeds
      print last_count
      print [last_count+(0+cur_players)*7200, last_count+(2+cur_players)*7200]
      raise SystemExit("Failed to find {} solution with {} players: {}".format("unique" if len(possible_seeds) else "a", cur_players, line))
    else:
      for x in itertools.count(last_count+(cur_players+2)*7200, direction):
        if int(rand(x+1, dsum)) == droll and int(rand(x, asum)) == aroll:
          solution = (rand.seed, rand.current_count)
          seed[line] = solution
          relative_range = (x-last_count)/7200.0 - cur_players
          last_count = rand.current_count
          break
      import sys
      sys.stderr.write("Failed to find {} solution with {} players; went ahead by {}: {}\n".format("unique" if len(possible_seeds) else "a", cur_players, relative_range, line))
  else:
    seed[line] = possible_seeds[0]
    last_count = seed[line][1]

last_count = 0
cur_players = solved_num_players
for x in xrange(solved_idx+1, len(all_lines)):
  line = all_lines[x]
  cur_players += user_count_changes[idx]
  if 'has attained' not in all_lines[x-1]:
    advance_seed(line, cur_players, 1)
last_count = 0
cur_players = solved_num_players
for x in xrange(solved_idx-1, 0, -1):
  line = all_lines[x]
  cur_players += user_count_changes[idx]
  if 'has attained' not in all_lines[x-1]:
    advance_seed(line, cur_players, -1)
  
for line in all_lines:
  if line in seed:
    randseed, randcount = seed[line]
    print "{:15d} {:9d} {:6d} {}".format(randseed, randcount,
                                         randcount-last_count, line)
    last_count = randcount
  else:
    print " "*33+line
