## Nodes
- g1 | kitchen island, large, brown/dark brown, rectangular/blocky, has a countertop | v1_o1, v2_o5, v3_o5, v4_o1 | provisional
- g2 | wooden door, dark brown, double door style | v1_o5, v4_o3 | provisional
- g3 | wooden door, dark brown, double door style | v1_o6 | provisional
- g4 | stool, black, high, rectangular seat | v2_o6, v3_o6 | provisional
- g5 | stool, black, high, rectangular seat | v2_o7, v3_o7 | provisional
- g6 | floor, light brown wood planks | v2_o2, v3_o4, v4_o7 | provisional
- g22 | cabinets, white, modern, includes upper and lower sections | v2_o4, v4_o6 | provisional
- g23 | wall, lower/cabinets, white | v3_o3 | provisional
- g24 | upper cabinets, white, horizontal rows | v3_o8 | provisional
- g25 | lower cabinets, white, below counter | v3_o9 | provisional
- g8 | shelving unit, brown wood, multiple shelves | v3_o12 | provisional
- g9 | refrigerator, large, white, rectangular | v3_o10 | provisional
- g10 | pendant light, dark fixture, hanging | v1_o7 | provisional
- g11 | pendant light, dark fixture, hanging | v1_o8 | provisional
- g12 | pendant light, dark fixture, hanging | v1_o9 | provisional
- g13 | brown object, round, brown/tan | v1_o2 | unresolved
- g14 | orange object, round, orange | v1_o3 | unresolved
- g15 | grey/white object, rectangular/dish shape, grey/white | v1_o4 | unresolved
- g16 | blue box, blue, rectangular | v2_o8 | provisional
- g17 | red object, small | v2_o9 | unresolved
- g18 | brown basket, brown, woven/basket shape | v2_o10 | provisional
- g19 | red object, small | v2_o11 | unresolved
- g20 | small round object, reddish/brown, small | v4_o4 | unresolved
- g21 | small flat object, light colored, rectangular | v4_o5 | unresolved

## Edges
- e1 | (g13, on, g1) | physical | unresolved | observed | v1_r1 | none | The brown object is situated on the kitchen island countertop.
- e2 | (g14, on, g1) | physical | unresolved | observed | v1_r2 | none | The orange object is situated on the kitchen island countertop.
- e3 | (g15, on, g1) | physical | unresolved | observed | v1_r3 | none | The grey/white object is situated on the kitchen island countertop.
- e4 | (g2, image_left_of, g1) | view_1 | provisional | observed | v1_r4 | none | The wooden door on the left is positioned to the left of the kitchen island.
- e5 | (g1, image_left_of, g3) | view_1 | provisional | observed | v1_r5 | none | The kitchen island is to the left of the wooden door on the right.
- e6 | (g10, on, g1) | physical | provisional | observed | v1_r6 | none | The first pendant light hangs above the kitchen island.
- e7 | (g11, on, g1) | physical | provisional | observed | v1_r7 | none | The second pendant light hangs above the kitchen island.
- e8 | (g12, on, g1) | physical | provisional | observed | v1_r8 | none | The third pendant light hangs above the kitchen island.
- e9 | (g4, image_left_of, g5) | view_2 | provisional | observed | v2_r1 | none | Visual placement
- e10 | (g16, on, g1) | physical | provisional | observed | v2_r2 | none | Visual contact
- e11 | (g17, on, g1) | physical | unresolved | observed | v2_r3 | none | Visual contact
- e12 | (g18, on, g1) | physical | provisional | observed | v2_r4 | none | Visual contact
- e13 | (g19, on, g1) | physical | unresolved | observed | v2_r5 | none | Visual contact
- e14 | (g4, on, g1) | physical | provisional | observed | v2_r6 | none | Visual contact
- e15 | (g5, on, g1) | physical | provisional | observed | v2_r7 | none | Visual contact
- e16 | (g4, image_left_of, g5) | view_3 | provisional | observed | v3_r1 | none | Stool 1 is positioned to the left of Stool 2.
- e17 | (g1, on, g6) | physical | provisional | observed | v3_r2, v4_r5 | none | The kitchen island is situated on the wooden floor.; The kitchen island is resting on the wooden floor.
- e18 | (g8, on, g6) | physical | provisional | observed | v3_r7 | none | The shelving unit is placed on the wooden floor.
- e19 | (g2, image_left_of, g1) | view_4 | provisional | observed | v4_r4 | none | The door is located to the left of the kitchen island.

## Unresolved issues
- u1: Ambiguity a1; affected IDs g13, g20; missing evidence or conflict. Does the brown object (g13) match the small round object (g20)?
- u2: Ambiguity a2; affected IDs g14, g17, g19; missing evidence or conflict. Does the orange object (g14) match the small red objects (g17 or g19)?
- u3: Ambiguity a3; affected IDs g15, g21; missing evidence or conflict. Does the grey/white object (g15) match the small flat object (g21)?
- u4: Unresolved object mappings; affected IDs g13, g14, g15, g17, g19, g20, g21; missing evidence or conflict.

## Verification requests
- q1 | view_1 | v1_o2 | What is the color and shape of the brown object?
- q2 | view_1 | v1_o3 | What is the color of the orange object?
- q3 | view_1 | v1_o4 | Describe the shape and color of the grey/white object.
- q4 | view_4 | v4_o5 | What is the color and shape of the small flat object?