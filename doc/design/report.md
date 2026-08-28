## stage r1: improve target starbash.toml

improve target 'about' info - so that (in a future stage) we can use that info to generate nice reports.S

* most of these improvements will be driven from/in the existing _generate_report() - improve what it emits for about
* on a per session basis we want:
  * equipment used (see below for details)
  * relevant metadata
* on a per frame basis we want similar per frame data (see below)
* note: i also want you to make ProcessedTarget more of a domain-model class rather than just a file reader/writer.  in particlar:
  * these new list of session-infos should be exposed internally as ProcessedTarget.sessions_info. you will need to define/
  use new dataclasses for SessionInfo and FrameInfo I think.


so for example the current about section looks like:

```
# About the target and processing - this section is auto geneated each starbash processing run...
[about]

summary = """
Processed data for Sh2 91.
Generated from 6 imaging sessions.
Total of 19.67 hours of exposure.
Filters used: HaOiii.
Observation dates: 2026-08-09, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-25, 2026-08-26.
"""
S
target.id = "Sh2 91"
target.ra = "19 35 44"
target.dec = "+29 51 09"
```

after this change it will approximately (ai feel free to tweak) look like:
```
# About the target and processing - this section is auto geneated each starbash processing run...
[about]

summary = """
Processed data for Sh2 91.
Generated from 6 imaging sessions.
Total of 19.67 hours of exposure.
Filters used: HaOiii.
Observation dates: 2026-08-09, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-25, 2026-08-26.
"""

target.id = "Sh2 91"
target.ra = "19 35 44"
target.dec = "+29 51 09"

sessions = [
    { date=..., equipment=session-eq-info, subs=subs-info},
    { date=..., equipment=session-eq-info, subs=subs-info}
]
```

where session-eq-info comes from the session info we've collected from our db and matching that with 'equipment' from src/starbash/defaults/starbash.toml.
also it should use the existing session metadata to get:

    FOCALLEN = 600.0 (example values from db)
    FOCRATIO = 7.5
    GAIN = 100
    XPIXSZ = 3.76
    YPIXSZ = 3.76

example session-eq-info:

    equipment = { 
        telescope = a full equipment record as matched from our defaults
        ...
    }
    metadata = {
        FOCALLEN = 600.0 (example values from db)
        FOCRATIO = 7.5
        GAIN = 100
        XPIXSZ = 3.76
        YPIXSZ = 3.76        
    }

example subs-info (one for each frame in that session):

    metadata = {
        DEWPOINT = 12.2 (example values from db)
        HUMIDITY = 94.0
        AMBTEMP = 13.1
        WINDGUST = 5.400432
        WINDSPD = 2.200176
        CCD-TEMP = -9.9
        wFWHM = -1 (not yet in db - just emit -1 for now)      
    }

