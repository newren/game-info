#!/usr/bin/env python

import operator

for player_level in xrange(1,100+1):
  expected_value = 0
  def handle_special_item(item_type, average_special_level):
    global expected_value
    odds = 1.0/40 # 0.025
    expected_value *= (1-odds)
    expected_value += odds*average_special_level
  for item_level in xrange(1, int(player_level*1.5)+1):
    odds_at_least_this_level = 1.4**(-item_level/4.0)
    nothigher = reduce(operator.mul, [1-1.4**(-x/4.0) for x in xrange(item_level+1, int(player_level*1.5)+1)], 1)
    expected_value += item_level * odds_at_least_this_level * nothigher
  if player_level >= 25:
    handle_special_item('helm', 62)
    handle_special_item('ring', 62)
  if player_level >= 30:
    handle_special_item('tunic', 87)
  if player_level >= 35:
    handle_special_item('amulet', 112)
  if player_level >= 40:
    handle_special_item('weapon', 162)
  if player_level >= 45:
    handle_special_item('weapon', 187.5)
  if player_level >= 48:
    handle_special_item('boots', 275)
  if player_level >= 52:
    handle_special_item('weapon', 325)
    
  print("{}: {}".format(player_level, expected_value))
