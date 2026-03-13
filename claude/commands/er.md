# Eval Report -- Customer Input Quality

Generate a customer-facing input quality report for a single trace. This analyzes the quality of the field data provided by the technician, NOT the pipeline output quality. Written in plain language without internal jargon.

## Arguments

`$ARGUMENTS` is the trace_id. It may be a full Langfuse URL or just the ID string. Extract the trace ID (hex string).

## Step 1: Fetch Trace

Call `mcp__langfuse__fetch_trace` with trace_id, `include_observations=true`, `output_mode="full_json_file"`. Note the saved file path.

## Step 2: Analyze Input Quality

Read the saved trace JSON file. Work through three phases in order.

### Phase A: Inventory All Input Data (counts only, no scoring yet)

Before assessing quality, establish exactly what was submitted. Record:
- **Rooms:** total count in RoomsWithId output; how many have `app_room_id` non-null; how many have `user_instructions` with at least one entry
- **Room sources:** for each room check `room_source.source` -- count how many are "field_app", "floor_plan", or "description"
- **Photos:** count of `property_images` in trace input (0 = no photos submitted)
- **Floor plans:** count of `measurement_images` in trace input
- **Notes:** does the input `description` field contain `<NOTE>` records? Count them. Is `guidelines` non-null?
- **Moisture:** do any rooms have moisture monitoring readings? (look for moisture_monitoring arrays in the description)

This inventory is the ground truth. All scoring in Phase B must be consistent with these counts.

### Phase B: Assess Quality of Each Data Type

Use the Phase A inventory as the foundation.

#### Room Setup Quality
- How many rooms exist? How many have `app_room_id` values (vs null)?
- What is `room_source.source` for each room?
  - "field_app" = room was created in the app before running scope (ideal)
  - "description" = room was inferred from notes or photos only -- not set up in app first
  - All "description" = the field team ran scope without setting up the job first; rooms won't sync back to the field app
- Are room names descriptive (e.g., "Office 121") or generic (e.g., "Bedroom", "Room")?
- Are there organizational/documentation rooms mixed with real damage rooms?
- Do any real rooms have duplicate names without floor differentiation?

#### Field Notes Quality
- Does the description contain technician-written `<NOTE>` records about each room?
- Are there room-level `user_instructions` with content?
- Is there a `guidelines` field with project-level notes?
- Score: None / Minimal / Adequate / Detailed

#### Moisture Data Quality
- Are there moisture monitoring readings in any room?
- Are readings tied to specific rooms?
- How many affected rooms have moisture data vs total affected?
- Score: None / Partial / Complete

#### Photo Quality
- Total photo count (from Phase A inventory -- `property_images` count)
- Photos per room (are they evenly distributed or concentrated in one room?)
- Are photos tagged to the correct rooms? (Check PropertyImagesAggregator output -- if it found fixtures inconsistent with the tagged room type, photos may be mislabeled)
- Are there "Cause of Loss" photos showing the water or damage source?
- Score: None / Minimal / Adequate / Well-documented

#### Floor Plan Quality
- Count of `measurement_images` in input (from Phase A inventory)
- If floor plans were provided, check MeasurementImages output: what room names were extracted?
  - Are they labeled with actual room names (e.g., "Office 121", "Kitchen") or generic (e.g., "Room", "Bath", "Hall")?
  - Generic-only names = floor plan is present and processed but unlabeled -- measurements cannot be matched to named rooms
- Check RoomsWithId rooms array: for each room look at `match_method`:
  - "name_match" = room was matched to a labeled floor plan space (measurements assigned, measurements_available: true)
  - "description_only" = room sourced from notes/photos only, no floor plan measurement assigned (measurements_available: false)
- Count affected rooms with match_method="name_match" vs "description_only"
- Score:
  - None: No floor plans in input
  - Partial: Floor plan provided but rooms are unlabeled (most/all match_method="description_only"), OR floor plan covers only some areas
  - Complete: Floor plan provided with labeled rooms; most affected rooms have measurements assigned

#### Overall Input Completeness
- Score 1-5:
  - 1: Almost nothing (room list only, no notes/photos/moisture)
  - 2: Minimal (photos but no notes, or notes but no photos)
  - 3: Adequate (photos + some notes OR photos + floor plan)
  - 4: Good (photos + notes + floor plan + some moisture data)
  - 5: Excellent (all data types present and well-organized)

### Phase C: Cross-Check Against Pipeline's Own Data Quality Assessment

The generated output scope contains a `## Data Quality Notes` section. Read it. This is the pipeline's own enumeration of input gaps and is the most reliable source for identifying missing documentation. It lists:
- Rooms without photos (table)
- Rooms without technician notes (table)
- Rooms missing measurements (table)
- Floor plan validation issues (area discrepancies, unmatched rooms)

Cross-check: confirm that Phase A inventory counts and Phase B scoring are consistent with what the pipeline flagged. If the pipeline flagged 19 rooms as missing measurements, your report must reflect this. If it flagged a floor plan area discrepancy, note it. Any discrepancy between your Phase A/B analysis and the pipeline's Data Quality Notes is a signal to re-examine before writing the report.

## Step 3: Identify Impact on Scope Quality

For each quality gap found, describe how it affected the generated scope:
- Missing notes -> scope had to infer damage from photos only -> less accurate material identification
- Missing moisture data -> drying plan based on assumptions -> may over/under-scope equipment
- Mislabeled photos -> materials attributed to wrong rooms -> inflated or incorrect task lists
- No room IDs -> rooms may not sync back to the field app
- Missing floor plan -> room dimensions entirely absent -> all task quantities TBD
- Floor plan present but rooms unlabeled -> dimensions extracted but cannot be assigned to named rooms -> same TBD outcome as missing floor plan; equipment sizing impossible
- All rooms sourced from description -> no field app setup before scope was run -> rooms won't sync back to job in the field app

## Step 4: Write the Report

Read the existing `joe/docs/reports/scope-customer-input-report.md` file first. Then rewrite it with the new report entry prepended to the top, followed by `---`, followed by the previous file content (excluding any placeholder text if the file was empty/uninitialized). The file is a running log -- never delete prior entries.

File structure:
```
# Scope Input Quality Log

## Report: <trace_id> -- <date>

**Trace:** <trace_id>
**Date:** <trace_timestamp>
**Property:** <address or "Not specified">
**Loss Type:** <type>

## Overall Score: <1-5>/5 -- <label>

## Summary

<2-3 sentence plain-English summary of what data was provided and what was missing. No technical terms like "PropertyImages node" or "RoomsWithId". Use language like "field photos", "technician notes", "moisture readings", "floor plan sketches". Reference Phase C pipeline data quality findings if they add clarity.>

## What Was Provided

| Data Type | Status | Details |
|-----------|--------|---------|
| Room Setup | <Good/Fair/Poor> | <count> rooms, <with/without> unique IDs, sourced from <field_app/notes/mixed> |
| Structures | <Clean/Mixed/Org-heavy> | <X> submitted; <Y> real rooms, <Z> organizational (<list org item names>) |
| Field Notes | <Detailed/Minimal/None> | <description> |
| Moisture Readings | <Complete/Partial/None> | <description> |
| Photos | <Well-documented/Adequate/Minimal/None> | <count> photos across <n> rooms |
| Floor Plans | <Complete/Partial/None> | <count> floor plans; <labeled/unlabeled>; <n> of <total> affected rooms with measurements |
| Thermal Images | <N found/None> | Scan property_images for thermal/FLIR/IR indicators |
| 360 Photos | <N found/None> | Scan property_images for 360/panoramic indicators |
| Org Room Content | <Present/None> | Notes/photos in organizational rooms (Initial Visit, Cause of Loss, Data, Checklist) -- may not be in scope |

## Recommendations

<Numbered list of specific, actionable recommendations for the field team. Each recommendation:
- Written in plain, non-technical language
- Explains WHY it matters (what goes wrong without it)
- Is specific (not "add more data" but "for each room, add a note describing which materials are wet and what the flooring type is")>

## Impact on Generated Scope

<Specific description of how the input gaps affected the scope. Reference which parts are less reliable and why. If the pipeline's Data Quality Notes flagged specific rooms or issues, mention the scale (e.g., "all 19 affected rooms are missing measurements").>

---

<previous log entries>
```

## Step 5: Confirm

Reply in chat:
```
Input quality report written to joe/docs/reports/scope-customer-input-report.md
Score: <n>/5 -- <label>
Top issues: <1-2 sentence summary>
```
