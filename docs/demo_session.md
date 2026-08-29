# Demonstrated Multi-Turn Sessions

One session per scenario type, replayed against the deterministic local
simulator in `evaluator/local_evaluator.py`. The evaluator's hidden target
and intent card are shown for readability; the agent never sees them.

Regenerate with the script in `docs/` or by replaying the evaluator loop.

## buying - `public_0001`

**Hidden target:** `B09PYB7B6Z` - QIAN0813 Celttic Knot Triple Moon Pentagram Pentacle Star Wicca Pendant Necklace Round Pagan Je

**Hidden hard constraints:** ['Material:alloy', 'Triple Moon Pentagram Symbol']

```text
turn 1
  shopper : I'm looking for Jewelry Necklaces. A key requirement is: Material:alloy.
  agent   : Got it - I've noted 'Material:alloy'. One more thing before I shortlist: is there any other detail that matters, such as a colour, a size, or a specific feature
  ask     : 'other'
  recs    : 0  (withheld - clarifying first)
turn 2
  shopper : For that, what matters is: Triple Moon Pentagram Symbol; The Triple Moon represents the Phases of the Moon which are linked to the three aspects of the Goddess 
  agent   : Based on 'Material:alloy' and 'Triple Moon Pentagram Symbol', here are my top picks. Is there anything else that matters - a material, colour, or a must-have fe
  ask     : 'other'
  recs    : 10  top3=['B09PYB7B6Z', 'B07SX1ZSNW', 'B0817Y931T']

  >>> HIT on turn 2 at rank 1
```

## browsing - `public_0006`

**Hidden target:** `B071F2Z7JG` - Pro Club Men's Heavyweight Mesh Basketball Shorts

**Hidden hard constraints:** ['polyester', '100% Polyester']

```text
turn 1
  shopper : I'm looking for Basketball Men, but I'm still exploring.
  agent   : I can see plenty of Basketball Men, so let me narrow it down before I show you a shortlist. Anything that matters - a material, colour, or a must-have feature?
  ask     : 'other'
  recs    : 0  (withheld - clarifying first)
turn 2
  shopper : For that, what matters is: polyester; 100% Polyester.
  agent   : Got it - I've noted 'polyester' and '100% Polyester'. One more thing before I shortlist: is there any other detail that matters, such as a colour, a size, or a 
  ask     : 'other'
  recs    : 0  (withheld - clarifying first)
turn 3
  shopper : For that, what matters is: Drawstring closure; High quality mesh for maximum breathability to keep you cool.
  agent   : Based on 'polyester' and '100% Polyester', here are my top picks. Is there anything else that matters - a material, colour, or a must-have feature?
  ask     : 'other'
  recs    : 10  top3=['B071F2Z7JG', 'B007023PU8', 'B001NCDFVA']

  >>> HIT on turn 3 at rank 1
```

## intent_override - `public_0002`

**Hidden target:** `B071X54486` - Hide & Drink, Rustic Handmade Full Grain Leather Men's Belt, Two Row Stitch Stylish Design - Ev

**Hidden hard constraints:** ['leather', '100% Leather']

```text
turn 1
  shopper : I'm looking for Accessories Belts. Buckle closure
  agent   : Got it - I've noted 'Buckle closure'. One more thing before I shortlist: is there any other detail that matters, such as a colour, a size, or a specific feature
  ask     : 'other'
  recs    : 0  (withheld - clarifying first)
turn 2
  shopper : For that, what matters is: leather; 100% Leather.
  agent   : Got it - I've noted 'leather' and '100% Leather'. One more thing before I shortlist: is there any other detail that matters, such as a colour, a size, or a spec
  ask     : 'other'
  recs    : 0  (withheld - clarifying first)
turn 3
  shopper : Actually, ignore my earlier preference. What I need is: leather.
  agent   : Based on 'Buckle closure' and 'leather', here are my top picks. Is there anything else that matters - a material, colour, or a must-have feature?
  ask     : 'other'
  recs    : 10  top3=['B08L13H7SY', 'B071X54486', 'B078HG9KCY']

  >>> HIT on turn 3 at rank 2
```

## boundary - `public_0035`

**Hidden target:** `B0BN6CCHB7` - Skechers Men's Go Max-Athletic Air Mesh Slip on Walking Shoe Sneaker

**Hidden hard constraints:** ['fabric', '100% Textile']

```text
turn 1
  shopper : I'm looking for Athletic Walking, but I'm still exploring.
  agent   : I can see plenty of Athletic Walking, so let me narrow it down before I show you a shortlist. Anything that matters - a material, colour, or a must-have feature
  ask     : 'other'
  recs    : 0  (withheld - clarifying first)
turn 2
  shopper : I don't have a preference for other; please use your judgment.
  agent   : I can see plenty of Athletic Walking, so let me narrow it down before I show you a shortlist. Anything that matters - a material, colour, or a must-have feature
  ask     : 'other'
  recs    : 0  (withheld - clarifying first)
turn 3
  shopper : For that, what matters is: fabric; 100% Textile.
  agent   : Based on 'fabric' and '100% Textile', here are my top picks. Is there anything else that matters - a material, colour, or a must-have feature?
  ask     : 'other'
  recs    : 10  top3=['B0BN6CCHB7', 'B00MES8EIQ', 'B078GTVCS6']

  >>> HIT on turn 3 at rank 1
```

