# Camera language and spatial blocking

Use this bundled reference before asset generation. It contains the shot-language rules required by this Skill; do not depend on a separate storyboard Skill.

## 1. Describe a camera, not only a picture

Every shot plan must answer these questions:

1. **Where is the camera?** Name its physical position: behind the crew, starboard exterior, eye level on deck, overhead, and so on.
2. **Where does it face?** Name the world target, not just “forward.”
3. **What is the environment axis?** Draw a line from the near point to the far point/vanishing point.
4. **What do the subjects do in world space?** Turn a wheel, run aft, reach a telegraph, brace against a rail.
5. **How does that world action project onto the frame?** Record the screen path and scale change.
6. **What visual anchor carries the viewer into the next shot?** Window, doorway, moving hand, hull, railing, or another physical prop.

If these answers are missing, a visually attractive frame can still be spatially wrong.

## 2. Shot vocabulary

| Shot | Framing | Use |
|---|---|---|
| ECU | detail only | decisive prop, impact detail |
| CU | face or single action fills frame | emotion, hand/lever action |
| MCU | head and shoulders | reaction and command |
| MS | waist up | character action and interaction |
| MLS | knees up | walking, bracing, body mechanics |
| LS | full body in environment | blocking and movement path |
| WS | environment dominates | geography and scale |
| EWS | vast environment | epic scale or isolation |

Angles: eye level is neutral; high angle reduces power; low angle increases power/threat; Dutch angle signals instability; over-the-shoulder or rear-observer framing places the viewer with a character and must preserve that character as a foreground anchor.

Movements: **pan/tilt** rotate the camera; **dolly/truck/crane** move it through space; **zoom** changes focal length without moving the camera. Do not label a crop enlargement as a dolly unless parallax and occlusion change as the camera advances.

## 3. Axes and perspective

Declare the environment axis as two image points: near → far. The far point is normally the vanishing point.

- Movement **toward** the vanishing point travels deeper into the scene and the subject must get smaller.
- Movement **away from** the vanishing point approaches the camera and the subject must get larger.
- A horizontal subject path is valid only when the world path is genuinely transverse to the depth axis and the frame establishes that crossing.
- Feet, contact shadows, railings, door frames, deck seams, and floorboards are evidence of the world plane. Use them to place the path.
- Foreground occluders must pass in front of subjects; distant subjects must be occluded by nearer architecture when their paths cross.

### Common failure: vertical environment, horizontal runner

If a deck or corridor recedes from the bottom of frame toward the top, its projected direction is vertical or diagonal. A person running along that deck cannot stay at one scale and slide horizontally. Animate the feet along the deck axis, reduce scale toward the far end, and let rails/davits occlude the figure as appropriate.

## 4. Character blocking and action density

For a scene with several people, write three staggered action layers:

- **Primary:** the action that changes the story state.
- **Secondary:** another character reacts to or assists the primary action.
- **Tertiary:** a background/environment response that confirms urgency or consequence.

Give each layer its own start frame, path, pivot, and cadence. Do not make a crowd share one transform. Do not use camera shake as a replacement for acting.

For a bridge warning, a valid causal chain could be:

1. lookout/commander sees the obstacle and points;
2. helmsman rotates the wheel and shifts body weight;
3. telegraph operator reaches and pulls the engine control while a loose chart or lamp reacts.

## 5. Eyeline and observer framing

When the camera is behind characters looking forward:

- keep shoulders, heads, or hands in the foreground to establish the observer position;
- place the obstacle inside the forward viewing sector, normally between or beyond those anchors;
- point faces/hands toward the same target;
- keep the next shot near the target's screen position for an eyeline match;
- move through the physical window/door opening if the next shot continues outside.

Do not show an obstacle only through a side window when the story says the crew sees it dead ahead. Do not cut from a rear observer view to an unrelated side profile without a visible camera move or neutral re-establishing shot.

## 6. Continuity rules

- **180-degree rule:** keep the camera on one side of the action axis. Cross only through a visible camera move or neutral shot.
- **Screen direction:** preserve left/right or near/far travel across shots unless the subject visibly turns.
- **Eyeline match:** show the viewed object from the viewer's approximate direction.
- **Match on action:** continue the same action phase across the boundary.
- **Match on geometry:** keep a window, doorway, railing, horizon, or vanishing point aligned through the handoff.
- **Occlusion transition:** the occluder must physically cover the frame before the new space replaces it.

## 7. Required `shot-plan.json` shape

Use frame numbers and canvas coordinates:

```json
{
  "canvas": {"width": 1920, "height": 1080},
  "fps": 30,
  "frame_count": 450,
  "shots": [
    {
      "id": "S01",
      "frames": [1, 90],
      "human_scene": true,
      "multi_character_scene": true,
      "framing": {
        "size": "WS-to-MS",
        "angle": "eye-level rear observer",
        "camera_position": "behind bridge crew on centerline",
        "camera_facing": "forward through center windshield",
        "lens_behavior": "dolly-in with increasing parallax"
      },
      "space": {
        "environment_axis": [[960, 980], [960, 330]],
        "vanishing_point": [960, 330],
        "screen_direction": "near-to-far",
        "foreground_anchor": "crew shoulders and helm",
        "eyeline_target": "iceberg beyond forward windshield"
      },
      "blocking": [
        {
          "id": "helmsman",
          "role": "primary",
          "action": "turns wheel and braces",
          "movement_constraint": "stationary",
          "path": [[1, 820, 950, 1.0], [90, 810, 950, 1.0]]
        },
        {
          "id": "commander",
          "role": "secondary",
          "action": "steps forward and points",
          "movement_constraint": "along-environment-axis",
          "path": [[18, 1180, 940, 1.0], [82, 1110, 690, 0.82]]
        },
        {
          "id": "telegraph",
          "role": "tertiary",
          "action": "reaches and pulls engine lever",
          "movement_constraint": "free",
          "path": [[34, 1500, 900, 1.0], [76, 1450, 850, 1.0]]
        }
      ],
      "handoff": {
        "type": "camera-through-window",
        "anchor": "center windshield and iceberg",
        "motion_vector": [0, -1]
      }
    }
  ]
}
```

Use `movement_constraint: "along-environment-axis"` when a person or vehicle moves along a deck, corridor, road, or room depth. Use `stationary` for a pivoting figure and `free` only when the action is genuinely transverse or local.

## 8. Reject before rendering

- Camera position says “behind,” but the frame is side-on or front-facing.
- Eyelines point at different targets.
- Obstacle placement contradicts the forward viewing sector.
- Environment recedes vertically while subjects slide horizontally at constant scale.
- All characters start, stop, and jitter together.
- A transition depends on a dissolve instead of a physical match or motivated cut.
- A close-up appears before the wide shot establishes geography.
