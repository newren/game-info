#!/usr/bin/env python

from collections import defaultdict
import re
import subprocess

#output = subprocess.check_output(['grep', '-A999999', 'BEGIN.LOGGING.*Wed Apr  1',
#                          '/home/newren/.xchat2/xchatlogs/Palantir-#idlerpg.log'])
output = subprocess.check_output(['cat',
                          '/home/newren/irclogs/Palantir/#idlerpg.log'])
groups = []
everyone = set()
for line in output.splitlines():
  m = re.match(".*<@idlerpg>\s*(.*) have been chosen", line)
  if m:
    participants = re.split(', (?:and )?', m.group(1))
    groups.append(participants)
    for who in participants:
      everyone.add(who)

order = []
folks_left = set([x for x in everyone])
while folks_left:
  possibles = set([x for x in folks_left])
  for group in groups:
    for i in xrange(1,len(group)):
      if group[i] in possibles:
        possibles.remove(group[i])
  #if len(possibles) != 1:
  #  print order
  #  raise SystemExit("Not uniq: {}".format(possibles))
  #else:
  if True:
    order.append([who for who in possibles])
    for who in possibles:
      folks_left.remove(who)
      for group in groups:
        if who in group:
          group.remove(who)
if all(len(x) == 1 for x in order):
  print "Found order: {}".format([x[0] for x in order])
else:
  print "Non-unique order: {}".format([x[0] if len(x)==1 else x for x in order])
raise SystemExit("I quit")

groups = {}
if False:
    for i, who in enumerate(participants):
      if who not in groups:
        groups[who] = [[], [], [], []]
      groups[who][i].append(participants)
order = []
for who in groups:
  if [len(groups[who][i]) for i in xrange(1, 4)] == [0, 0, 0]:
    order.append(who)
print order
#print groups
    
