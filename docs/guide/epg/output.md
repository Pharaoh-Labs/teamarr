---
title: Output
parent: EPG
grand_parent: User Guide
nav_order: 8
docs_version: "2.7.0"
redirect_from:
  - /guide/epg.html
  - /guide/settings/epg/
  - /guide/settings/epg.html
---

# Output

**EPG → Output** configures the XMLTV file Teamarr writes: where it goes, how much it covers, default event durations, and the generator metadata embedded in it.

{: .note }
Running a generation, previewing the XML, and reviewing run history now live on the [Dashboard](../dashboard). This page is only the output *settings*.

## Output Path

Where to write the generated XMLTV file. Default: `./data/teamarr.xml`.

The file is also served live at a copyable **XMLTV URL** (e.g. `http://host:9195/api/v1/epg/xmltv`) — point Dispatcharr or a media player at that URL rather than the file path.

## Output Window

How many days of EPG data to include, and how many hours of already-started events to keep (so games still in progress aren't dropped from the guide).

## Default Durations

Default event durations (in hours) per sport, used when an event's real duration is unknown:

| Sport | Default | Sport | Default |
|-------|---------|-------|---------|
| Basketball | 3.0 | MMA | 5.0 |
| Football | 3.5 | Boxing | 4.0 |
| Hockey | 3.0 | Tennis | 3.0 |
| Baseball | 3.5 | Golf | 6.0 |
| Soccer | 2.5 | Cricket | 4.0 |

## XMLTV Generator Metadata

Customize the generator name and URL written into the XMLTV header (default `Teamarr` and the project GitHub URL). Some media servers use these to identify the EPG source.

## Related

- [Dashboard](../dashboard) — generate, preview, and review run history
- [Templates](templates) — shape the text and artwork inside each programme
- Scheduling (the generation cron) lives under [Settings → General](../settings/general)
