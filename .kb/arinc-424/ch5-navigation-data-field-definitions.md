## 5 NAVIGATION DATA - FIELD DEFINITIONS

This chapter introduces field definitions for navigation data records used in the Chapter 4 records. It lists revision items (5.1 through 5.8) describing STAR/Profile Descent coding rules: STARs ending in vectors to final approach (VM leg) code the Airport/Heliport Record identifier in the Waypoint Ident field of the STAR Record; item 5.2 deleted by Supplement 19; STARs not beginning at a source fix use the closest named fix as the initial fix (IF leg); STARs/Profile Descents lacking crossing altitudes on intermediate fixes carry a computed vertical angle on the last leg for a constant descent path meeting minimum enroute altitudes; a STAR with a single path from origination to termination fix is coded Route Type 2; STARs repeated with different Runway/Helipad Identifiers in the Transition Identifier are coded Runway Transition Route Type 3, while those repeated with different Fix Identifiers are coded Enroute Transition Route Type 1; an Arrival Route overlapping an Approach Transition to the same runway/helipad is coded in full per source documentation; a STAR consisting only of Enroute Transitions may add a single IF leg as Route Type 2 on the common last fix per Section 5.11, with partial STAR coding permitted when most Enroute Transitions share an end fix.

## 5.1 General

Chapter 5 defines the content of each field used in the Chapter 4 records, presenting for every field: Field Name, abbreviation (when different from the Field Name), Field Definition/Description, Source/Content, field Length (character count), Character Type (alpha, numeric, or alpha/numeric), and Examples where relevant. General formatting rules apply to all fields: numeric fields and the numeric parts of latitude, longitude, magnetic variation, negative elevation, and station declination fields are right justified with leading zeros; alpha and alpha/numeric fields are left justified; blank field content is defined as alpha/numeric content.

| Activity   | Mtgs      | Mtg-Days (Total)   | Expected Start Date   | Expected Completion Date   |
|------------|-----------|--------------------|-----------------------|----------------------------|
| Document a | # of mtgs | # of mtg days      | mm/yyyy               | mm/yyyy                    |
| Document b | # of mtgs | # of mtg days      | mm/yyyy               | mm/yyyy                    |

## 5.2 Record Type (S/T)

The Record Type field (S/T) indicates whether a record's data are standard (suitable for universal application) or tailored (included in the master file for a single user's specific purpose, per Section 1.2). The field contains S for standard and T for tailored data. Used on all records; length 1 character; alpha.

## 5.3 Customer/Area Code (CUST/AREA)

The Customer/Area Code field (CUST/AREA) allows standard records to be categorized by geographical AREA and tailored records by airline, airline subset, or other customer code; some record types do not follow geographical boundaries and have no AREA. AREA Codes are derived from Figure 5-1; airline codes come from ICAO Doc 8585 (three-letter code) or the IATA Airline Coding Directory (two-character code), with a unique code established if none exists in these documents. On Company Route and Preferred Route Records, an additional AREA field points to the AREA containing the Route Segment; for records not following geographical boundaries the field is blank, and for Preferred Routes it contains PDR. Used on all records with content as defined; length 3 characters max; alpha/numeric. Examples: Areas USA, CAN, EUR; Customer UAL, DAL, DLH, AA8, DL3, LH8; Preferred Routes PDR.

## 5.4 Section Code (SEC CODE)

The Section Code field (SEC CODE) defines the major section of the navigation system database in which a record resides, per the encoding scheme in Table 5-1. Used on all records; length 1 character; alpha.

## 5.5 Subsection Code (SUB CODE)

The Subsection Code field (SUB CODE) defines the specific part of the database's major section in which a record resides. Records that reference other records within the database (fix information in Holdings, Enroute Airways, Airport/Heliport SID/STAR/Approach, Communications, Airport/Heliport MSA, Airport/Heliport TAA, Company Routes, Enroute Airway Restrictions, Preferred Routes, and Alternate Records) use the Section/Subsection Codes together with the record identifier to make the reference: the Section Code defines the major database section, the Subsection Code identifies the exact section (file), and the fix (record) is then located within that file. Content follows the Section and Subsection Encoding Scheme in Table 5-1. Used on all records; length 1 character; alpha.

| Section Code   | Section Name   | Subsection Code                     | Subsection Name                                                                                                                                                                                                                          |
|----------------|----------------|-------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| A              | MORA           | S                                   | Grid MORA                                                                                                                                                                                                                                |
| D              | Navaid         | Blank B T                           | VHF Navaid NDB Navaid TACAN Duplicates                                                                                                                                                                                                   |
| E              | Enroute        | A M P R S T U                       | Waypoints Airway Markers Holding Patterns Airways and Routes Special Activity Areas Preferred Routes Airway Restrictions                                                                                                                 |
| H              | Heliport       | A C D E F H K S P                   | Reference Points Terminal Waypoints SIDs STARs Approach Procedures Helipads TAA MSA SBAS Path Point                                                                                                                                      |
| P              | Airport        | A B C D E F G H I K L M N P Q R S T | Reference Points Gates Terminal Waypoints SIDs STARs Approach Procedures Runways Helipads Localizer/Glideslope TAA MLS Localizer Marker Terminal NDB SBAS Path Point GBAS Path Point Flt Planning ARR/DEP MSA GLS Station Communications |
| R              | Company Routes | V Blank A H                         | Company Routes (Master Airline File) Alternate Records (Master Helicopter File)                                                                                                                                                          |
| T              | Tables         | C G V                               | Helicopter operation Routes Cruising Tables Geographical Reference Communication Type                                                                                                                                                    |
| U              | Airspace       | C F R                               | Controlled Airspace FIR/UIR Restrictive Airspace                                                                                                                                                                                         |

## 5.6 Airport/Heliport Identifier (ARPT/HELI IDENT)

The Airport Identifier and Heliport Identifier fields identify the airport or heliport to which the record's data relates. Content is derived from official government sources: the four-character ICAO Location Identifier when published; the three- or four-character Domestic Identifier when no ICAO identifier exists; the supplied procedure location identifier for Point in Space procedures not tied to an Airport or Heliport; and, on Airport/Heliport Flight Planning Continuation Records, the Airport/Heliport Identifier owning the referenced terminal controlled airspace. Note: within the continental United States, in addition to using published ICAO identifiers, data suppliers may append the character K to certain Domestic Identifiers to form an ICAO look-alike four-character identifier.

## 5.6-x74 COMMENTARY

Where no officially published identifier exists, a data supplier may create a unique, temporary, unofficial identifier for Tailored Data only, with the data user's knowledge and concurrence; such temporary identifiers should be coordinated among data suppliers before release where possible. For Point in Space procedures at a location that is not an Airport or Heliport, the procedure-design-provided identifier is used. This Airport/Heliport Identifier is distinct from the more familiar two- or three-character ATA/IATA identifiers used by airlines for non-navigation purposes; those are included in the ARINC 424 database per Section 5.107. The field is used on Airport Identifier records (VHF Navaid, NDB Navaid, Airport Terminal Waypoint, Airport, Airport Gate, Airport SID/STAR/Approach, Runway, Airport/Heliport Localizer, Airport/Heliport Localizer Marker, Holding Pattern, Airport Communications, Airport/Heliport MLS, GLS, Airport MSA, Airport TAA, Path Point, Flight Planning Arrival/Departure Data, GLS Record, Airport Helipad Records, and Enroute Airway Restriction/Company Route), analogous Heliport Identifier records, and Point in Space Procedure Location Identifier records (Heliport, Heliport Terminal Waypoint, Heliport SID/STAR/Approach, Heliport MSA, Heliport Path Point, Heliport Helipad Records). Length: 4 characters maximum; alpha/numeric. Examples: KJFK, DMIA, 9Y9, CYUL, EDDF, 53Y, CA14.

## 5.7 Route Type (RT TYPE)

The Route Type field (RT TYPE) defines the type of Enroute Airway, Preferred Route, or Airport/Heliport SID/STAR/Approach Route to which a record belongs. For Airport and Heliport SID/STAR/Approach Routes, Route Type includes a primary route type plus up to two route type qualifiers. Content for approach procedures follows: Table 5-2 (Enroute Airway Records: Airline Airway A, Control C, Direct Route D, Helicopter Airways H, Officially Designated Airways O, RNAV/RNP Airways R, Undesignated ATS Route S, TACAN Airway T); Table 5-3 (Route Qualifier Content, covering GNSS/DME/DME/IRU requirements, FRT, Parallel Offset, TOAC, and PBN Nav Specs such as RNAV 1/2/5/10, RNP 0.3/1/2/4, A-RNP, B-RNAV, P-RNAV, VOR/DME RNAV; Note 1: code N marks a non-RNAV/RNP segment within an RNAV/RNP airway, Route Type R, with Qualifiers 1 and 2 blank); Table 5-4 (Preferred Route Records: North American Routes for North Atlantic Traffic C, Preferential Routes D, PACOTS J, TACAN Routes-Australia M, Non-common Portion N, Preferred/Preferential Overflight Routes O, Preferred Routes P, TOS S, TEC T); and Table 5-5 (Airport SID (PD)/Heliport SID (HD) Records: Engine Out SID 0, SID Runway Transition 1, SID/SID Common Route 2, SID Enroute Transition 3, Vector SID Runway Transition T, Vector SID Enroute Transition V). Supplement 22 revisions: Table 5-2 added RNP and ICAO PBN Nav Spec content; Table 5-3 was newly added for Route Qualifier Content (other tables renumbered); Table 5-6 (Airport and Heliport SID Record) had Note 6 deleted and RNP 1 or RNAV 1 PBN Nav Spec added to Qualifier Description; Table 5-7 (Airport STAR/Heliport STAR) added Note 2 for RNAV PBN Nav Spec under Qualifier 2, added an RNP PBN Nav Qualifier Description with Note 3, deleted Note 4 in the RNP AR Qualifier, and added RNP 1 or RNAV 1 PBN Nav Spec; Table 5-8 (Airport Approach/Heliport Approach) deleted the GBAS Procedure Qualifier Description to align with the ICAO definition and updated Note 2 to remove the GLS procedures reference.

| Airway Type                                                           | Field Content   |
|-----------------------------------------------------------------------|-----------------|
| Airline Airway (Tailored Data)                                        | A               |
| Control                                                               | C               |
| Direct Route                                                          | D               |
| Helicopter Airways                                                    | H               |
| Officially Designated Airways, except RNAV, RNP or Helicopter Airways | O               |
| RNAV or RNP Airways (ICAO PBN Nav Spec)                               | R               |
| Undesignated ATS Route                                                | S               |
| TACAN Airway                                                          | T               |

| Qualifier Description                     | Qualifier 1 Field Content   | Qualifier 2 Field Content   | Qualifier 3 Field Content   |
|-------------------------------------------|-----------------------------|-----------------------------|-----------------------------|
| GNSS Required                             | G                           |                             |                             |
| GNSS or DME/DME/IRU Required              | F                           |                             |                             |
| GNSS, DME/DME/IRU or DME/DME Required     | A                           |                             |                             |
| Equipment requirements unspecified        | U                           |                             |                             |
| FRT Required                              |                             | R                           |                             |
| Parallel Offset Required                  |                             | P                           |                             |
| TOAC Required                             |                             | T                           |                             |
| RNAV 10 PBN Nav Spec                      |                             |                             | W                           |
| RNAV 5 PBN Nav Spec                       |                             |                             | Z                           |
| RNAV 2 PBN Nav Spec                       |                             |                             | Y                           |
| RNAV 1 PBN Nav Spec                       |                             |                             | X                           |
| B RNAV                                    |                             |                             | B                           |
| P RNAV                                    |                             |                             | P                           |
| RNP 4 PBN Nav Spec                        |                             |                             | C                           |
| RNP 2 PBN Nav Spec                        |                             |                             | D                           |
| RNP 1 PBN Nav Spec                        |                             |                             | E                           |
| A-RNP (Advanced RNP) PBN Nav Spec         |                             |                             | A                           |
| RNP 0.3 PBN Nav Spec                      |                             |                             | G                           |
| PBN Nav Spec unspecified                  |                             |                             | U                           |
| VOR/DME RNAV                              |                             |                             | V                           |
| Non RNAV/RNP segment in a RNAV/RNP airway |                             |                             | N (Note 1)                  |

| Route Type Description                                                | Field Content   |
|-----------------------------------------------------------------------|-----------------|
| North American Routes for North Atlantic Traffic                      | C               |
| Common Portion                                                        |                 |
| Preferential Routes                                                   | D               |
| Pacific Oceanic Transition Routes (PACOTS)                            | J               |
| TACAN Routes - Australia                                              | M               |
| North American Routes for North Atlantic Traffic - Non-common Portion | N               |
| Preferred/Preferential Overflight Routes                              | O               |
| Preferred Routes                                                      | P               |
| Traffic Orientation System Routes (TOS)                               | S               |
| Tower Enroute Control Routes (TEC)                                    | T               |

| SID Route Type Description    | Field Content   |
|-------------------------------|-----------------|
| Engine Out SID                | 0               |
| SID Runway Transition         | 1               |
| SID or SID Common Route       | 2               |
| SID Enroute Transition        | 3               |
| Vector SID Runway Transition  | T               |
| Vector SID Enroute Transition | V               |

## 5.7-x75 Table 5-6 - Airport and Heliport SID Record

Table 5-6 (Airport/Heliport SID) qualifiers include DME Required (D), GNSS Required (G), Radar Required (R), Helicopter SID from Runway (H), and Point-in-Space (PinS) SID (P) as Qualifier 1; RNAV PBN Nav Spec (D), RNP PBN Nav Spec (E), FMS Required (F), Conventional Departures (G), and PinS Departure Proceed Visually/VFR (W/X) as Qualifier 2; and RNAV/RNP PBN Nav Spec levels (Z, Y, X, B, P, D, E, F, A, G, M, U, V) as Qualifier 3. Notes clarify: with Qualifier 2 = E, Qualifier 3 must be D, E, F, A, G, or U (Note 1); RNAV departures use Qualifier 3 Z, Y, X, B, P, M, or U for PBN, or U/V for non-PBN (Note 2); F marks government-designated FMS departures (Note 3); Qualifier 3 F marks RNP AR procedures (implied GNSS required), usable with SID route type 0 (RNP AR Engine Out SID) or types 1-3 if the SID transition is AR (Note 4); Qualifiers W/X imply Database Supported RNAV required, pairing with Qualifier 1 P and SID route types 1-3 (Note 5). Table 5-7 defines STAR Route Type (Enroute Transition 1, STAR/Common Route 2, Runway Transition 3) and Qualifiers mirroring SID Qualifier 1 (DME/Radar/GNSS Required, Helicopter STAR to Runway, Continuous Descent STAR) and similar Qualifier 2/3 PBN content, with FMS-designated Arrivals (Note 1), RNAV Arrival PBN mapping (Note 2), and RNP Arrival PBN mapping (Note 3). Table 5-8 lists Approach Route Type codes (Approach Transition A, Localizer/Backcourse B, VORDME D, FMS F, IGS G, RNP-titled H, ILS I, GLS J, Localizer Only L, MLS M, NDB N, GPS P, NDB+DME Q, RNAV-titled R, VOR via VORDME/VORTAC S, TACAN T, SDF U, VOR V, LDA X, Missed Approach Z), listed alphabetically without priority; Route Type R denotes procedures titled RNAV, Route Type H denotes procedures titled RNP (Note 1). Commentary clarifies that old titles (RNAV (GPS), RNAV (GNSS), RNAV (RNP)) are coded Route Type R, new RNP-titled procedures (RNP, RNP (AR)) are coded Route Type H, and new RNAV-titled procedures (RNAV, RNAV (AR)) remain Route Type R. Table 5-9 lists Approach Qualifiers (Qualifier 3 PBN specs X/E/H/G/A/F and RNAV Visual B; Qualifier 1 sensor requirements D, J, N, P, R, T, U, V, W; Qualifier 2 minimums/procedure types A, B, E, C, H, I, L, S, V, W, X), with eleven notes covering: Qualifier 1/2 consistency across transitions and Qualifier 3 rules (Note 1); Route Type R/H usage and RHO-RHO/RHO-THETA/GNSS-based RNP coding (Note 2); Qualifier 2 S/H meaning straight-in with possible separate circle-to-land minimums (Note 3); Qualifier 1 W meaning SBAS-only navigation requiring the FAS Data Block, with worked examples (Note 4); Qualifier 1 D/N not used with RNAV/RNP Route Types H/R or DME-option Route Types D/Q (Note 5); Qualifier 2 A/B/E restricted to Missed Approach Route Type Z, while C/S/H/I/L apply to any other Route Type (Note 6); Qualifier 2 H/I only on Airport Approach (PF) Records (Note 7); Qualifier 3 F = RNP AR, A = A-RNP without AR, H = basic RNP, E/X usable on transitions for non-RNAV/RNP approaches (Note 8); Qualifier 2 L for Heliport/Airport Procedure Records where source gives Helicopter Minimums without Straight-In/Circle-To-Land distinction (Note 9); Qualifier 2 V only with Qualifier 1 B (Note 10); Qualifier 2 W/X only with Qualifier 1 J, P, R, U, V, or W (Note 11). The field is used on Enroute Airways, Airport/Heliport SID/STAR/Approach, Preferred Route, Company Route, and Helicopter Operations Company Route Records; length 1 character (read together with Qualifiers 1-3 for terminal procedures); alpha/numeric. Examples illustrate combined Route Type plus Qualifier coding, e.g., LDC = Localizer-only procedure, DME required, Circle-to-Land minimums; SNS = VOR procedure via VORDME/VORTAC, DME not required, straight-in; I_H = ILS procedure, no DME requirement, helicopter operations to a runway (Airport Approach file).

| Qualifier Description             | Qualifier 1 Field Content   | Qualifier 2 Field Content   | Qualifier 3 Field Content   |
|-----------------------------------|-----------------------------|-----------------------------|-----------------------------|
| DME Required                      | D                           |                             |                             |
| GNSS Required                     | G                           |                             |                             |
| Radar Required                    | R                           |                             |                             |
| Helicopter SID from Runway        | H                           |                             |                             |
| Point-in-Space (PinS) SID         | P                           |                             |                             |
| RNAV PBN Nav Spec                 |                             | D (Note 2)                  |                             |
| RNP PBN Nav Spec                  |                             | E (Note 1)                  |                             |
| FMS Required                      |                             | F (Note 3)                  |                             |
| Conventional Departures           |                             | G                           |                             |
| PinS Departure - Proceed Visually |                             | W(Note 5)                   |                             |
| PinS Departure - Proceed VFR      |                             | X (Note 5)                  |                             |
| RNAV 5 PBN Nav Spec               |                             |                             | Z                           |
| RNAV 2 PBN Nav Spec               |                             |                             | Y                           |
| RNAV 1 PBN Nav Spec               |                             |                             | X                           |
| B RNAV                            |                             |                             | B                           |
| P RNAV                            |                             |                             | P                           |
| RNP 2 PBN Nav Spec                |                             |                             | D                           |
| RNP 1 PBN Nav Spec                |                             |                             | E                           |
| RNP AR PBN Nav Spec               |                             |                             | F (Note 4)                  |
| A-RNP (Advanced RNP) PBN Nav Spec |                             |                             | A                           |
| RNP 0.3 PBN Nav Spec              |                             |                             | G                           |
| RNP 1 or RNAV 1 PBN Nav Spec      |                             |                             | M                           |
| PBN Nav Spec unspecified          |                             |                             | U                           |
| VOR/DME RNAV                      |                             |                             | V                           |

| STAR Route Type Description   |   Field Content |
|-------------------------------|-----------------|
| STAR Enroute Transition       |               1 |
| STAR or STAR Common Route     |               2 |
| STAR Runway Transition        |               3 |

| Qualifier Description             | Qualifier 1 Field Content   | Qualifier 2 Field Content   | Qualifier 3 Field Content   |
|-----------------------------------|-----------------------------|-----------------------------|-----------------------------|
| DME Required                      | D                           |                             |                             |
| Radar Required                    | R                           |                             |                             |
| GNSS Required                     | G                           |                             |                             |
| Helicopter STAR to Runway         | H                           |                             |                             |
| Continuous Descent STAR           | P                           |                             |                             |
| RNAV PBN Nav Spec                 |                             | D (Note 2)                  |                             |
| RNP PBN Nav Spec                  |                             | E (Note 3)                  |                             |
| FMS Required                      |                             | F (Note 1)                  |                             |
| Conventional Arrivals             |                             | G                           |                             |
| RNAV 5 PBN Nav Spec               |                             |                             | Z                           |
| RNAV 2 PBN Nav Spec               |                             |                             | Y                           |
| RNAV 1 PBN Nav Spec               |                             |                             | X                           |
| B RNAV                            |                             |                             | B                           |
| P RNAV                            |                             |                             | P                           |
| RNP 2 PBN Nav Spec                |                             |                             | D                           |
| RNP 1 PBN Nav Spec                |                             |                             | E                           |
| RNP AR PBN Nav Spec               |                             |                             | F                           |
| A-RNP (Advanced RNP) PBN Nav Spec |                             |                             | A                           |
| RNP 0.3 PBN Nav Spec              |                             |                             | G                           |
| RNP 1 or RNAV 1 PBN Nav Spec      |                             |                             | M                           |
| PBN Nav Spec unspecified          |                             |                             | U                           |
| VOR/DME RNAV                      |                             |                             | V                           |

| Approach Route Type Description                                                              | Route Type Field Content   |
|----------------------------------------------------------------------------------------------|----------------------------|
| Approach Transition                                                                          | A                          |
| Localizer/Backcourse Approach                                                                | B                          |
| VORDME Approach                                                                              | D                          |
| Flight Management System (FMS) Approach                                                      | F                          |
| Instrument Guidance System (IGS) Approach                                                    | G                          |
| Area Navigation (RNAV) Approach with Required Navigation Performance (RNP) Approach (Note 1) | H                          |
| Instrument Landing System (ILS) Approach                                                     | I                          |
| GNSS Landing System (GLS)Approach                                                            | J                          |
| Localizer Only (LOC) Approach                                                                | L                          |
| Microwave Landing System (MLS) Approach                                                      | M                          |
| Non-Directional Beacon (NDB) Approach                                                        | N                          |
| Global Positioning System (GPS) Approach                                                     | P                          |
| Non-Directional Beacon + DME (NDB+DME) Approach                                              | Q                          |
| Area Navigation (RNAV) Approach (Note 1)                                                     | R                          |
| VOR Approach using VORDME/VORTAC                                                             | S                          |
| TACAN Approach                                                                               | T                          |
| Simplified Directional Facility (SDF) Approach                                               | U                          |
| VOR Approach                                                                                 | V                          |
| Localizer Directional Aid (LDA) Approach                                                     | X                          |
| Missed Approach                                                                              | Z                          |

| Qualifier Description                                   | Qualifier 1 Field Content (Note 1)   | Qualifier 2 Field Content Note 1   | Qualifier 3 Field Content (Note1)   |
|---------------------------------------------------------|--------------------------------------|------------------------------------|-------------------------------------|
| RNAV 1 PBN Nav Spec                                     |                                      |                                    | X (Note 8)                          |
| RNP 1 PBN Nav Spec                                      |                                      |                                    | E (Note 8)                          |
| RNP APCH PBN Nav Spec                                   |                                      |                                    | H (Note 8)                          |
| RNP 0.3 PBN Nav Spec                                    |                                      |                                    | G (Note 8)                          |
| A-RNP (Advance RNP) PBN Nav Spec                        |                                      |                                    | A (Note 8)                          |
| RNP AR PBN Nav Spec                                     |                                      |                                    | F (Note 8)                          |
| RNAV Visual Procedure                                   |                                      |                                    | B (Note 2)                          |
| DME Required for Procedure                              | D (Note 5)                           |                                    |                                     |
| GPS (GNSS) required, DME/DME to RNP xx.x not authorized | J (Note 2)                           |                                    |                                     |
| DME Not Required for Procedure                          | N (Note 5)                           |                                    |                                     |
| GNSS Required                                           | P (Note 2)                           |                                    |                                     |
| GPS (GNSS) or DME/DME to RNP xx.x required              | R (Note 2)                           |                                    |                                     |
| DME/DME Required for Procedure                          | T (Note 2)                           |                                    |                                     |
| RNAV or RNP, Sensor Not Specified                       | U (Note 2)                           |                                    |                                     |
| VOR/DME RNAV                                            | V (Note 2)                           |                                    |                                     |
| Procedure that Requires SBAS FAS Data Block             | W(Note 4)                            |                                    |                                     |
| Primary Missed Approach                                 |                                      | A (Note 6)                         |                                     |
| Secondary Missed Approach                               |                                      | B (Note 6)                         |                                     |
| Engine Out Missed Approach                              |                                      | E (Note 6)                         |                                     |
| Procedure with Circle-to-land Minimums                  |                                      | C (Note 3)                         |                                     |
| Helicopter with Straight-in Minimums                    |                                      | H (Note 6, 7)                      |                                     |
| Helicopter with Circle-to-land Minimums                 |                                      | I (Note 7)                         |                                     |
| Helicopter with Helicopter Landing Minimums             |                                      | L (Note 6, 9)                      |                                     |
| Procedure with Straight-in Minimums                     |                                      | S                                  |                                     |
| Procedure with VMC minimums                             |                                      | V (Note 10)                        |                                     |
| PinS Procedure - Proceed Visually                       |                                      | W(Note 11)                         |                                     |
| PinS Procedure - Proceed VFR                            |                                      | X (Note 11)                        |                                     |

## 5.8 Route Identifier (ROUTE IDENT)

The Route Identifier field (ROUTE IDENT) identifies a route of flight or traffic orientation using coding from aeronautical navigation charts and related publications. For Enroute Airways, codes derive from official government publications. For Preferred Routes, published Route Identifiers are used where available. For North American Routes for North Atlantic Traffic (Common Portion) and similar systems, codes are those published in government sources. For the European Traffic Orientation System, North American Routes (Non-common Portion), Preferred Routes, and Preferential Routes published without official/flight-plan identifiers but defined between specific airports or fixes, route identifiers combine the initial and terminus fix idents per Chapter 7 naming rules; Chapter 7 also provides rules for routings lacking a unique initial or terminus fix, developed using the Geographical Reference Tables (TG) - see Chapter 3 Section 3.2.7.2 and Chapter 4 Section 4.1.26. Used on Enroute Airway, Preferred Route Records, and the Geographical Reference Table; length 5 characters max (Enroute Airway) or 10 characters max (Preferred Route); alpha/numeric. Examples: Enroute Airway V216, C1150, J380, UA16, UB414; Preferred Routes N111B, TOS13, TOS14WK, CYYLCYYC, ARTCOLAR, KZTLKSAV, SCNDICANRY.

## 5.9 SID/STAR Route Identifier (SID/STAR IDENT)

The SID/STAR Route Identifier field (SID/STAR IDENT) contains the name of the SID or STAR, combining the basic indicator, validity indicator, and route indicator abbreviated to six characters per Chapter 7 naming rules; codes derive from official government publications describing the terminal procedures structure. Used on Airport SID/STAR, Heliport SID/STAR, and Flight Planning Arrival/Departure Data Records; length 6 characters max; alpha/numeric. Examples: DEPU2, SCK4, TRP7, 41M3, MONTH6.

## 5.10 Approach Route Identifier (APPROACH IDENT)

The Approach Route Identifier field (APPROACH IDENT) contains the identifier of the approach route to be flown and, to support multiple approach procedures of the same type to a runway, also carries a multiple indicator. Table 5-10 (Runway Dependent Procedure Ident) defines a 6-column layout: Column 1 = Approach Type alpha character (as in Route Type, Section 5.7); Columns 2-3 = Runway Identification in tens of degrees (01-36); Column 4 = Runway Designation (dash placeholder, L, R, C, or blank, with Columns 5-6 blank when C or blank); Column 5 = Multiple Indicator (alphanumeric or blank); Column 6 blank. Table 5-11 (Circle-to-Land Procedures Identifier): Columns 1-3 = Circling Procedure Ident; Column 4 = government-provided procedure suffix or multiple indicator (A-Z, 1-9); Columns 5-6 blank. Table 5-12 (Circle-to-Land Route Type Identifier) maps each Route Type code (from Section 5.7) to its first three Circling Procedure Identifier characters, e.g., B=LBC, D=VDM, F=FMS, G=IGS, H=RNP, J=GLS, L=LOC, M=MLS, N=NDB, P=GPS, Q=NDM, R=RNV, S/V=VOR, T=TAC, U=SDF, W/Y=MLS, X=LDA (A = Approach Transitions, I and Z have no circling equivalent). Table 5-13 (Helicopter Approach Procedures to Runways or Final Approach Course): Column 1 = Approach Type alpha character; Columns 2-4 = three-digit runway designation or final approach course in full degrees; Column 5 = Multiple Indicator; Column 6 blank.

| Column   | Contents                                                                                                  |
|----------|-----------------------------------------------------------------------------------------------------------|
| 1        | Type of Approach-Alpha Character, the same as field 5.7 Route Type                                        |
| 2-3      | Runway Identification- Numeric in tens of degrees, valid range 01-36                                      |
| 4        | Runway Designation                                                                                        |
| 4        | - (dash) Place holder if other runway designation codes are not present and multiple indicators required. |
| 4        | L Left                                                                                                    |
| 4        | R Right                                                                                                   |
| 4        | C                                                                                                         |
| 4        | Center Blank Position 5 and 6 must also be Blank                                                          |
| 5        | Multiple Indicator Alphanumeric or Blank                                                                  |
| 6        | Blank                                                                                                     |

| Column   | Contents                                                                                   |
|----------|--------------------------------------------------------------------------------------------|
| 1-3      | Circling Procedure Ident (See below).                                                      |
| 4        | A thru Z or 1 thru 9 A government source provided procedure suffix or a multiple indicator |
| 5-6      | Blank                                                                                      |

| Route Type Field Content (5.7)   | 1 ST Three Characters of Circling Procedure Identifier   |
|----------------------------------|----------------------------------------------------------|
| A                                | (Approach Transitions)                                   |
| B                                | LBC                                                      |
| D                                | VDM                                                      |
| F                                | FMS                                                      |
| G                                | IGS                                                      |
| H                                | RNP                                                      |
| I                                | (No Circling ILS)                                        |
| J                                | GLS                                                      |
| L                                | LOC                                                      |
| M                                | MLS                                                      |
| N                                | NDB                                                      |
| P                                | GPS                                                      |
| Q                                | NDM                                                      |
| R                                | RNV                                                      |
| S                                | VOR                                                      |
| T                                | TAC                                                      |
| U                                | SDF                                                      |
| V                                | VOR                                                      |
| W                                | MLS                                                      |
| X                                | LDA                                                      |
| Y                                | MLS                                                      |
| Z                                | (Missed Approach)                                        |

| Column   | Contents                                                                                                                        |
|----------|---------------------------------------------------------------------------------------------------------------------------------|
| 1        | Type of Approach-Alpha Character, the same as the field 5.7 Route Type.                                                         |
| 2-4      | Three-digit numeric character representing the runway designation or procedure final approach course, expressed in full degrees |
| 5        | Multiple Indicator Alphanumeric or Blank                                                                                        |
| 6        | Blank                                                                                                                           |

## 5.10-x77 Table 5-14 - Helicopter Approach Procedures to Heliports and Coded to a Specific Pad Identifier

Table 5-14 (Helicopter Approach Procedures to Heliports Coded to a Specific Pad Identifier): Column 1 = Approach Type alpha character (per Section 5.7 Route Type); Columns 2-6 = Pad Identification. Used on Airport and Heliport Approach Route Records, Flight Planning Arrival/Departure Data, Airport and Helicopter Operations, SBAS Path Point, GBAS Path Point, Airport/Heliport Localizer, Airport/Heliport TAA, and Simulation Continuation Records; length 6 characters max; alpha/numeric. Examples: Runway Dependent - I26L, B08R, R29, V01L, N35, L16RA, L16RB, V08-A, V08-B, I18L1, I18L2, R35-Y, R35-Z; Circle-to-Land/Point-in-Space - VOR, VDM, LOC, VORA, VORB, NDB1, NDB2 (multiple indicators), NDBB, VDMA, LOCD, BI, P168, NDAT (source-provided suffixes); Helicopter to Runway - I13L, L040, V175, N175B; Helicopter to Helipad - IA127 (ILS to pad A127), VBRAVO (VOR to pad BRAVO), N23 (NDB to pad 23), RWESTA (RNAV to pad West Alpha).

| Column   | Contents                                                                |
|----------|-------------------------------------------------------------------------|
| 1        | Type of Approach-Alpha Character, the same as the field 5.7 Route Type. |
| 2-6      | Pad Identification                                                      |

## 5.11 Transition Identifier (TRANS IDENT)

The Transition Identifier field (TRANS IDENT) describes the transition made between the enroute environment and the terminal area (and vice versa), and between the terminal area/runway/helipad and the approach. Content is determined by the Route Type field (Section 5.7) per Table 5-15: Engine Out SID (Route Type 0) and SID/RNAV SID Route Type 1 = Runway (RWY) or Pad Identifier; Route Type 2 = Blank/RWY/PAD/ALL (Notes 1, 3); Route Type 3 = SID Enroute Transition Identifier (Note 5); Vector SID Route Type T = Runway/Pad Identifier, Route Type V = Vector SID Enroute Transition Identifier; STAR/RNAV STAR Route Type 1 = STAR Enroute Transition Identifier (Note 5), Route Type 2 = Blank/RWY/PAD/ALL (Note 3), Route Type 3 = Runway/Pad Identifier (Note 2); Approach Transitions (Route Type A) = Approach Transition Identifier; Missed Approach (Route Type Z) = Missed Approach Transition Identifier (Note 4); all other Route Types = Blank. Note 1: SID Route Type 2 carries an entry only if there is no Route Type 1 for the SID; otherwise blank. Note 2: STAR Route Type 2 carries an entry only if there is no Route Type 3 for the STAR; otherwise blank. Note 3: ALL means the procedure is valid for all runways/helipads; otherwise individual runway transitions are coded, with B (e.g., RW08B) denoting a single transition coding all parallel runways (e.g., RW08L/RW08R or RW08L/RW08C/RW08R); if parallel runways cannot share one coded transition, each must be coded individually. Note 4: the Missed Approach Transition Identifier is the Missed Approach Holding Fix identifier, or the last fix in the missed approach coding if no holding fix exists; modified per Attachment 5 and Section 8.6 for multiple procedure instances. Note 5: Enroute Transition Identifiers are normally the navaid or waypoint identifier. Transition Identifiers derive from official government sources where provided. Used on Airport and Heliport SID/STAR/Approach, Flight Planning Arrival/Departure Data, and Company Route Records; length 5 characters max; alpha/numeric. Examples: 9TU, ETX, KEENE, DEN, RW08R, Blank.

| Record          | Route Type   | Field Content                               |
|-----------------|--------------|---------------------------------------------|
| Engine Out SID  | 0            | Runway (RWY) or Pad Identifier              |
| SID/RNAV SID    | 1            | Runway (RWY) or Pad Identifier              |
|                 | 2            | Blank/RWY/PAD/ALL (Note 1 and 3)            |
|                 | 3            | SID Enroute Transition Identifier (Note 5)  |
| Vector SID      | T            | Runway (RWY) or Pad Identifier              |
|                 | V            | Vector SID Enroute Transition Identifier    |
| STAR/ RNAV STAR | 1            | STAR Enroute Transition Identifier (Note 5) |
|                 | 2            | Blank RWY/PAD/ALL/ (Note 3)                 |

| Record               | Route Type                                       | Field Content                         |          |
|----------------------|--------------------------------------------------|---------------------------------------|----------|
|                      | 3                                                | Runway (RWY) or Pad Identifier        | (Note 2) |
| Approach Transitions | A                                                | Approach Transition Identifier        |          |
| Missed Approach      | Z                                                | Missed Approach Transition Identifier | (Note 4) |
| Approach Procedure   | All Other Codes Except A and Z (see Section 5.7) | Blank                                 |          |

## 5.12 Sequence Number (SEQ NR)

The Sequence Number field (SEQ NR) defines a record's position within an ordered series: for Route Type Records, the position in the route of flight sequence identified by the Route Identifier; for Boundary Type Records, the position within a boundary; for Record Types needing multiple primary records, the position within that defining sequence. For Airport and Heliport TAA Records, Sequence Number 1 is always the Center-Fix-based Straight-In Area record, 2 the Left Base Area record, and 3 the Right Base Area record; an absent area's number is simply not used (e.g., only 1 and 3 if no Left Base Area). Sequence numbers are assigned during route/boundary/sequence definition and must not duplicate within a uniquely identified route, boundary, or sequence. For three- or four-digit Sequence Numbers, an initial increment of ten between consecutive records is used; for one- or two-digit numbers, the initial increment is one. When a record must later be inserted into a route or boundary sequence, its sequence number keeps the same significant characters as the preceding record, with the units character set midway between the preceding and following values (e.g., 5 when both are 0). For one- or two-digit sequence numbering, inserting a record requires renumbering all subsequent records. When an enroute airway crosses a geographical area boundary (Section 5.3), the boundary-adjacent fix is coded twice (once per area) with the same sequence number in each case; uniqueness is maintained via the Boundary Code (Section 5.18), and sequence numbers must allow airway records to sort into continuous flight-sequence order by Route Identifier and Sequence Number alone, regardless of Geographical Area Code. On Enroute, Airport, and Heliport Communications Primary and Continuation records, the Sequence Number instead serves as a record counter within a given Identifier and Communications Class to ensure output file record uniqueness. Used on Enroute Airways, Airport/Heliport MSA, Airport/Heliport TAA, Airport/Heliport SID/STAR/Approach, Company Route, Cruise Tables, FIR/UIR, Restrictive Airspace, Controlled Airspace, Preferred Routes, Flight Planning Arrival/Departure Data, VHF Navaid Limitation Continuation, Helicopter Operations Company Routes, and TACAN-Only NAVAID Limitation Continuation Records. Length: 4 characters (Enroute Airways, Preferred Routes, FIR/UIR, Restrictive Airspace); 3 characters (SID/STAR/Approach, Company Routes); 2 characters (VHF Navaid Limitation Continuation, TACAN-Only NAVAID Limitation Continuation); 1 character (MSA Table, TAA Table, Cruise Table). Character Type: Numeric. Examples: 0010, 0135, 2076, 120, 030, 01, 84, 3.

## 5.13 Fix Identifier (FIX IDENT)

The Fix Identifier field (FIX IDENT) contains the five-character name-code or other character series identifying a fix, including Waypoint Identifiers, VHF NAVAID Identifiers, NDB NAVAID Identifiers, Airport Identifiers, and Runway Identifiers. Content comes from officially published identifiers or identifiers derived per Chapter 7 Naming Conventions. Used on Holding Patterns, Enroute Airways, Airport/Heliport SID/STAR/Approach, Enroute Airway Restrictions, Enroute Waypoints, Airport/Heliport Terminal Waypoints (Waypoint Ident), and Flight Planning Arrival/Departure Data Records; length 5 characters max; alpha/numeric (no embedded blanks). Examples: SHARP, DEN43, BHM, RW27L, KGRR.

## 5.14 ICAO Code (ICAO CODE)

The ICAO Code field (ICAO CODE) permits geographic categorization of records within the limits of the Area Code field's categorization. Codes come from ICAO Document No. 7910, Location Indicators. To allow sub-division of the United States into more manageable regions, the ICAO code for the USA (K) is followed by a numeric character obtained from Figure 5-2. Used on all records except Cruising Tables and Grid MORA; length 2 characters max; alpha/numeric. Examples: K1, K7, PA, MM, EG, UT.

## 5.16 Continuation Record Number (CONT NR)

When a record's information exceeds the 132 columns of the Primary Record, one or more Continuation Records are used; the Continuation Record Number identifies a continuation record's position in that sequence. Primary records contain 0 when no Continuation Records exist; a 1 indicates one or more follow. Continuation Records are numbered sequentially starting at 2; if requirements exceed a Continuation Record numbered 9, numbering continues with alpha characters A through Z as needed. Used on all records except Company Route, Airport Localizer Marker/Locator, Enroute Markers, Cruising Tables, FIR/UIR, and Grid MORA; length 1 character; alpha/numeric. Examples: 0, 1, 2 through 9, A, B, C through Z.

## 5.17 Waypoint Description Code (DESC CODE)

The Waypoint Description Code field (DESC CODE) designates the type, function, and attributes of a waypoint in Enroute Airway or Terminal Procedure segment coding, via a four-column code (columns 40-43) defined in Table 5-16. Column 40 (Type/Function/Attribute) values include Airport as Fix (A, SID/STAR/APCH), Essential Waypoint (E), Off Airway Floating Waypoint (F, Enroute), Runway/Helipad as Fix (G), Heliport as Waypoint (H), NDB Navaid as Waypoint (N), Phantom Waypoint (P), Non-Essential Waypoint (R, Enroute), Transition Essential Waypoint (T, Enroute), and VHF Navaid as Fix (V). Column 41 covers Flyover Waypoint Ending Leg (B), End of Continuous Segment (E), Uncharted Airway Intersection (U, Enroute), and Fly-Over Waypoint (Y). Column 42 covers Unnamed Stepdown Fix on Final (A) or Intermediate (B) Approach Segment, ATC Compulsory Reporting Point (C), Oceanic Gateway Waypoint (G, Enroute), First Leg of Missed Approach Procedure (M), Fix used for turning final approach (R), and Named Stepdown Fix (S). Column 43 covers Initial Approach Fix (A), Intermediate Approach Fix (B), Holding at Initial Approach Fix (C), Initial Approach Fix at FACF (D), Final End Point (E), Final Approach Fix (F), source-provided Enroute Waypoint without/with Holding (G/H), Final Approach Course Fix (I), Missed Approach Point (M), Engine Out SID Missed Approach Disarm Point (N), and Initial Departure Fix (P, SID). Generic note: there is a Waypoint Description field for each coding segment; Column 40 is never blank for Enroute Airways but may be blank for Terminal Procedures when the path terminator does not reference a fix (see Attachment 5). Note 1: waypoint type/function/attribute definitions are in Section Two, Special Navigation Terms. Note 2: Column 41 Y indicates a government-designated Overfly Waypoint that must be overflown before the next leg's maneuver; End of Continuous Segment (E) is an implementation-derived (not source) indicator provided at the end of a Terminal Procedure Transition, the end of an airway, where a route continues beyond a gap, or where the ARINC Area Code changes in the next leg; when both conditions apply in Terminal Procedure coding, Column 41 is set to B. Note 3: Column 42 M (First Leg of Missed) is coded on the approach leg following the Missed Approach Point (Column 43). Note 4: Column 42 R marks a step-down fix on final approach where the segment course changes by 1 degree or more from the next leg (all non-procedure RF fixes on final approach qualify), and takes precedence over a co-located step-down fix code. Note 5: Column 43 N on an engine-out SID or missed approach record marks the engine-out SID/missed-approach disarm point, controlling automatic engine-out procedure loading based on when engine failure is detected relative to that fix. Note 6: Column 40 A or H applies only to SIDs that are Vector SIDs consisting solely of Enroute Transitions (Attachment 5, Rule 4.11), or to STARs ending in vectors to final approach (Attachment 5, Rule 5.1). Note 7: Column 43 P (Initial Departure Fix) is coded for the first published fix/waypoint of an RNAV departure. Used on Airport and Heliport SID/STAR/Approach and Enroute Airway Records; length 4 characters; alpha.

| Waypoint Description                               | Used On                  | Column   | Column   | Column   | Column   | Remarks   |
|----------------------------------------------------|--------------------------|----------|----------|----------|----------|-----------|
| Type/ Function/ Attribute                          | Enroute, SID, STAR, APCH | 40       | 41       | 42       | 43       |           |
| Airport as Fix                                     | SID, STAR, APCH          | A        |          |          |          | Note 6    |
| Essential Waypoint                                 | Enroute, SID, STAR, APCH | E        |          |          |          | Note 1    |
| Off Airway Floating Waypoint                       | Enroute                  | F        |          |          |          | Note 1    |
| Runway as Fix, Helipad as Fix                      | SID, STAR, APCH          | G        |          |          |          |           |
| Heliport as Waypoint                               | SID, STAR, APCH          | H        |          |          |          | Note 6    |
| NDB Navaid as Waypoint                             | Enroute, SID, STAR, APCH | N        |          |          |          |           |
| Phantom Waypoint                                   | SID, STAR, APCH          | P        |          |          |          | Note 1    |
| Non-Essential Waypoint                             | Enroute                  | R        |          |          |          | Note 1    |
| Transition Essential Waypoint                      | Enroute                  | T        |          |          |          | Note 1    |
| VHF Navaid As Fix                                  | Enroute, SID, STAR, APCH | V        |          |          |          |           |
| Flyover Waypoint, En d ing Leg                     | SID, STAR, APCH          |          | B        |          |          | Note 2    |
| End of Continuous Segment                          | Enroute, SID, STAR, APCH |          | E        |          |          | Note 2    |
| Uncharted Airway Intersection                      | Enroute                  |          | U        |          |          | Note 1    |
| Fly-Over Waypoint                                  | APCH, SID, STAR,         |          | Y        |          |          | Note 2    |
| Unnamed Stepdown Fix Final Approach Segment        | APCH                     |          |          | A        |          |           |
| Unnamed Stepdown Fix Intermediate Approach Segment | APCH                     |          |          | B        |          |           |
| ATC Compulsory Reporting Point                     | SID, STAR, APCH Enroute  |          |          | C        |          | Note 1    |
| Oceanic Gateway Waypoint                           | Enroute                  |          |          | G        |          | Note 1    |
| First Leg of Missed Approach Procedure             | APCH                     |          |          | M        |          | Note 3    |
| Fix used for turning final approach                | APCH                     |          |          | R        |          | Note 4    |
| Named Stepdown Fix                                 | APCH                     |          |          | S        |          |           |
| Initial Approach Fix                               | APCH                     |          |          |          | A        | Note 1    |
| Intermediate Approach Fix                          | APCH                     |          |          |          | B        | Note 1    |
| Holding at Initial Approach Fix                    | APCH                     |          |          |          | C        |           |
| Initial Approach Fix at FACF                       | APCH                     |          |          |          | D        |           |
| Final End Point                                    | APCH                     |          |          |          | E        | Note 1    |
| Final Approach Fix                                 | APCH                     |          |          |          | F        | Note 1    |
| Source provided Enroute Waypoint without Holding   | Enroute                  |          |          |          | G        |           |
| Source provided Enroute Waypoint with Holding      | Enroute SID, STAR, APCH  |          |          |          | H        |           |
| Final Approach Course Fix                          | APCH                     |          |          |          | I        | Note 1    |
| Missed Approach Point                              | APCH                     |          |          |          | M        | Note 1    |
| Engine Out SID Missed Approach Disarm Point        | SID (Engine Out), APCH   |          |          |          | N        | Note 5    |
| Initial Departure Fix                              | SID                      |          |          |          | P        | Note 7    |

## 5.18 Boundary Code (BDY CODE)

Routes of flight frequently cross geographical boundaries; the Boundary Code field (BDY CODE) identifies the area into or from which a continuous route passes at such a crossing, per the codes in Table 5-17 (e.g., USA=U, Canada and Alaska=C, Pacific=P, Latin America=L, South America=S, South Pacific=1, Europe=E, Eastern Europe=2, Middle East South Asia=M, Africa=A). Used on Enroute Airways records; length 1 character; alpha/numeric. This section was newly added.

| Area                   | Area Code*   | Boundary Code   |
|------------------------|--------------|-----------------|
| USA                    | USA          | U               |
| Canada and Alaska      | CAN          | C               |
| Pacific                | PAC          | P               |
| Latin America          | LAM          | L               |
| South America          | SAM          | S               |
| South Pacific          | SPA          | 1               |
| Europe                 | EUR          | E               |
| Eastern Europe         | EEU          | 2               |
| Middle East South Asia | MES          | M               |
| Africa                 | AFR          | A               |

## 5.19 Level (LEVEL)

The Level field (LEVEL) defines the airway structure an Enroute Airway, Preferred Route, Restrictive Airspace, or Controlled Airspace record belongs to: B for All Altitudes, H for High Level Airways, L for Low Level Airways. Length 1 character; alpha.

## 5.20 Turn Direction (TURN DIR)

The Turn Direction field (TURN DIR) specifies the direction Terminal Procedure turns are made, and also indicates direction on course reversals (Attachment 5, Path and Termination). Content is L for Left turns, R for Right turns, and E for turns in either direction. Used on Airport and Heliport SID/STAR/Approach records; length 1 character; alpha.

## 5.21 Path and Termination (PATH TERM)

The Path and Termination field (PATH TERM) defines the path geometry for a single record of an ATC terminal procedure; Attachment 5 (Path and Terminator) contains the available Path Term codes for coding an ATC terminal procedure. Used on Airport and Heliport SID/STAR/Approach records; length 2 characters; alpha.

## 5.22 Turn Direction Valid (TDV)

The Turn Direction Valid field (TDV) is used with Turn Direction (Section 5.20) to indicate that a turn is required before capturing the path defined in a terminal procedure leg; content is Y when a turn is required prior to beginning the leg defined by the Path Term, with the turn direction specified in Section 5.20. Used on Airport and Heliport SID/STAR/Approach Records; length 1 character; alpha.

## 5.23 Recommended NAVAID (RECD NAV)

The Recommended Navaid field (RECD NAV) specifies the reference facility for the waypoint in a record's Fix Ident field, or for an Airport or Heliport; VHF, NDB (Enroute and Terminal), Localizer, TACAN, GLS, and MLS Navaids may be referenced, using a 1-4 character identifier. Navaids recommended in official government publications are used when available. Procedures requiring leg types referenced to specific navaids follow Attachment 5 coding rules. A VHF Navaid may be any VOR, DME, VORDME, VORTAC, TACAN, Un-Biased ILSDME, or MLSDME in the database per Table 5-18's specific rules. An NDB Navaid may be any NDB or Locator in the Enroute or Terminal NDB files. Localizers and MLS Azimuth serve as Recommended Navaids for procedures referencing those navaids, including RNAV Transitions to them. The final-approach Recommended Navaid is the procedure reference facility; RNAV and GPS final approaches, which reference no navaid, omit this field (see Attachment 5). On Airport and Heliport Records, the Recommended Navaid is any VOR, VORDME, or VORTAC in the database. On Enroute Airway Records, when provided, it is any VORDME or VORTAC. On Terminal Procedure Records other than final approach, it is the procedure reference facility per the coding rules for Path Terminators in Attachment 5. Rules for Converging ILS Approach Procedures match those for ILS Approach Procedures. For GLS Approach Procedures, the Recommended Navaid is the GLS Reference Path identifier appropriate to the runway and approach. Non-collocated VORDME, VORTAC, and Localizer/ILSDME or ILSTACAN facilities may be used as the recommended navaid in terminal procedure coding only in defined circumstances (see Section 5.35 for non-collocated definition, Table 5-18 for the circumstances). Used on Enroute Airway, Airport/Heliport SID/STAR/Approach, and Airport/Heliport Records; length 4 characters max; alpha/numeric. Examples: P, PP, DEN, LAX, ILAX, MJFK.

## 5.23-x78 Table 5-18 - Procedure Use

Table 5-18 (Procedure Use) cross-references Facility Type (Collocated VORDME/VORTAC, Non-collocated VORDME/VORTAC, Localizer, VOR, DME, TACAN, NDB, ILSDME or ILSTACAN, GLS, MLS) against Procedure User categories (SID/STAR, Approach Transition, Missed Approach Procedure, Path Terminator types AF/CR/VR/CD/VD/FD, VORDME/VORTAC Final Approach, VOR Only Final Approach, NDB Only Final Approach, NDB+DME Final Approach, TACAN Final Approach, GLS Final Approach, MLS Final Approach, and Airports) to show which facility types are valid recommended navaids for each procedure use, marked X or with footnote numbers. Footnote 1: applies on FACF and FAF Records. Footnote 2: applies on Runway/MAP Records only. Footnote 3: ILSDMEs and ILSTACANs must be unbiased for use as a recommended navaid and need not be collocated with the frequency-paired localizer in the instances allowed.

|                                | Procedure User   | Procedure User      | Procedure User            | Procedure User       | Procedure User           | Procedure User                                                                                                  | Procedure User               | Procedure User                 | Procedure User                 | Procedure User                  | Procedure User              | Procedure User            | Procedure User                                                                | Procedure User   |
|--------------------------------|------------------|---------------------|---------------------------|----------------------|--------------------------|-----------------------------------------------------------------------------------------------------------------|------------------------------|--------------------------------|--------------------------------|---------------------------------|-----------------------------|---------------------------|-------------------------------------------------------------------------------|------------------|
| Facility Type                  | SID/STAR         | Approach Transition | Missed Approach Procedure | Path Terminator - AF | Path Terminator - CR, VR | Path Terminator - CD, VD, FD Localizer Final Approach & Transitions of Course or Heading to Intercept Localizer | VORDME/VORTAC Final Approach | VOR Only Final Approach Coding | NDB Only Final Approach Coding | NDB + DME Final Approach Coding | TACAN Final Approach Coding | GLS Final Approach Coding | MLS Final Approach Coding & Transitions of Course or Heading to Intercept MLS | Airports         |
| Collocated VORDME/ VORTAC      | X                | X                   | X                         | X                    | X                        | X                                                                                                               | X                            |                                |                                | 2                               |                             |                           |                                                                               | X                |
| Non- collocated VORDME/ VORTAC |                  | X                   | X                         |                      |                          |                                                                                                                 | X                            |                                |                                | 2                               |                             |                           |                                                                               | X                |
| Localizer                      |                  | X                   | X                         |                      | X                        | X                                                                                                               |                              |                                |                                |                                 |                             |                           |                                                                               |                  |
| VOR                            |                  | X                   | X                         |                      | X                        |                                                                                                                 |                              | X                              |                                |                                 |                             |                           |                                                                               | X                |
| DME                            |                  |                     | X                         |                      |                          | X                                                                                                               |                              |                                |                                | 2                               |                             |                           |                                                                               |                  |
| TACAN                          | X                | X                   | X                         | X                    | X                        | X                                                                                                               |                              |                                |                                | 2                               | X                           |                           |                                                                               | X                |
| NDB                            |                  | X                   | X                         |                      |                          |                                                                                                                 |                              |                                | X                              | 1                               |                             |                           |                                                                               |                  |
| ILSDME or ILSTACAN             |                  |                     | 3                         |                      |                          | 3                                                                                                               |                              |                                |                                | 2 & 3                           |                             |                           |                                                                               |                  |
| GLS                            |                  | X                   |                           |                      |                          |                                                                                                                 |                              |                                |                                |                                 |                             | X                         |                                                                               |                  |
| MLS                            |                  | X                   |                           |                      |                          |                                                                                                                 |                              |                                |                                |                                 |                             |                           | X                                                                             |                  |

## 5.24 Theta (THETA)

Theta is the magnetic bearing to the waypoint in the record's Fix Ident field, measured from the navaid in the Recommended Navaid field. Values derive from official government sources when available, provided in degrees and tenths of a degree with the decimal point suppressed; content is controlled by the Path Terminator requirements and coding rules in Attachment 5. Used on Airport and Heliport SID/STAR/Approach and Enroute Airway Records; length 4 characters; alpha/numeric. Examples: 0000, 0756, 1217, 1800.

## 5.25 Rho (RHO)

Rho is the geodesic distance in nautical miles to the waypoint in the record's Fix Ident field, measured from the navaid in the Recommended Navaid field. Values derived from official government sources are used when available, entered in nautical miles and tenths of a nautical mile with the decimal point suppressed; content is controlled by Path Terminator requirements and coding rules in Attachment 5. Used on Airport and Heliport SID/STAR/Approach and Enroute Airway Records; length 4 characters; alpha/numeric. Examples: 0000, 0216, 0142, 1074.

## 5.26 Outbound Magnetic Course (OB MAG CRS)

Outbound Magnetic Course is the published outbound magnetic course from the waypoint in the record's Fix Ident field; it is also used for Course/Heading/Radials on SID/STAR/Approach Records per Path Terminator requirements and coding rules in Attachment 5. Values from official government sources are used when available, expressed in degrees and tenths of a degree with the decimal point suppressed; for route/procedure segments published in degrees true, the last (tenths) character contains T (see Section 5.165). Used on Airport and Heliport SID/STAR/Approach, Enroute Airway, and Flight Planning Arrival/Departure Data Records; length 4 characters; alpha/numeric. Examples: 2760, 0231, 194T.

## 5.27 Route Distance From, Holding Distance/Time (RTE DIST FROM, HOLD DIST/TIME)

Route Distance From, Holding Distance/Time (RTE DIST FROM, HOLD DIST/TIME) expresses the length of the path defined in the record, in nautical miles or in minutes.

In Enroute Airways, it contains the distance from the waypoint in the Fix Ident field to the next waypoint in the route.

In SID, STAR, and Approach Procedure Records, it holds segment distance, along track distance, excursion distance, DME distance, holding pattern leg distance, or time, depending on Path and Termination (see Table Three, Leg Data Fields, Attachment 5).

Source/Content: Distances come from official government source where available, expressed in nautical miles and tenths with the decimal point suppressed. For time, the first character is 'T' followed by minutes and tenths of minutes, decimal point suppressed. Holding Pattern Record data is per Section 5.64 or 5.65.

Used On: Airport and Heliport SID/STAR/Approach, Enroute Airway Records. Length: 4 characters. Character Type: Distance - Numeric; Time - Alpha/numeric.

## 5.28 Inbound Magnetic Course (IB MAG CRS)

Inbound Magnetic Course (IB MAG CRS) is the published inbound magnetic course to the waypoint in the Fix Ident field.

The HX group of Path Terminator codes provides racetrack-type course reversal flight paths; government publications for these include an inbound magnetic bearing. SID/STAR/Approach Procedure records have no dedicated inbound course field — this data is carried instead in the Outbound Magnetic Course field of those records.

Source/Content: Official government values are used when available. The field contains magnetic bearing in degrees and tenths of a degree, decimal point suppressed. For routes published with true courses, the last character is 'T' in place of tenths of a degree.

Used On: Enroute Airways records. Length: 4 characters. Character Type: Alpha/numeric.

## 5.29 Altitude Description (ALT DESC)

Altitude Description (ALT DESC) designates whether a waypoint should be crossed at, at or above, at or below, or at or above to at or below specified altitudes, and also flags recommended altitudes or cases with two distinct altitudes at one fix.

Source/Content: A code is selected from a table (below) based on official government source or Attachment 5 coding rules. Codes include: + (at or above first Altitude field), - (at or below first Altitude field), @ blank (at first Altitude field), B (at or above to at or below first and second Altitude fields; not used on FAF/MAP with electronic Glideslope), C (at or above second Altitude field, whichever is earlier), D (at or above second Altitude field, whichever is later, equivalent to not before), G (Glideslope Altitude at Fix on FAF, Glideslope Intercept Altitude as second altitude in Precision Approach Coding), O (at or above second Altitude field until established inbound on racetrack; optional at or above first Altitude field at the Fix).

B may appear on any record with altitude/description data; the higher value appears first, or as the first three digits of the Altitude Limitation field; not used on missed approach point or final end point in approach coding. C/D indicate a conditional altitude termination valid only for ascending SID and Missed Approach segments (Attachment 5). O is coded only on HF Path Terminator, for a racetrack outbound altitude differing from the HF fix altitude.

Used On: Airport and Heliport SID/STAR/Approach Primary and Continuation Records, Airport/Heliport/Enroute Communications, VHF NAVAID Limitation Continuation, Preferred Routes and Flight Planning Arrival/Departure Data Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 1 character. Character Type: Alpha. Deleted Field Content: V, X, Y and associated Note.

| Field Content   | Waypoint Crossing Description                                                                                                                                                            |
|-----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| + (plus)        | At or above altitude specified in first Altitude field.                                                                                                                                  |
| - (minus)       | At or below altitude specified in first Altitude field.                                                                                                                                  |
| @(blank)        | At altitude specified in first Altitude field.                                                                                                                                           |
| B               | At or above to at or below altitudes specified in the first and second Altitude fields. Not used on FAF or MAP Waypoint Records in Precision Approach Coding with Electronic Glideslope. |
| C               | At or above altitude specified in second Altitude field. Condition is whichever is earlier.                                                                                              |
| D               | At or above altitude specified in second Altitude field. Condition is whichever is later, which is operationally equivalent to the condition of not before.                              |

| Field Content   | Waypoint Crossing Description                                                                                                                                                                                                    |
|-----------------|----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| G               | Glideslope Altitude (MSL) At Fix, specified in the first Altitude field on the FAF Waypoint and Glideslope Intercept Altitude (MSL) in second altitude of FAF Waypoint in Precision Approach Coding with electronic Glideslope . |
| O               | At or above altitude specified in second Altitude field applicable until established inbound on the racetrack pattern. Optional at or above altitude specified in first Altitude field applicable at the Fix.                    |

## 5.30 Altitude/Minimum Altitude

Altitude/Minimum Altitude indicates the reference altitude for: Enroute Airways (MEA, MFA or other minimum altitudes), the holding pattern path in a Holding Pattern record, altitudes at fixes/path terminations in SID/STAR/Approach records (per Path Terminator), and the lowest altitude of blocked altitudes for a Preferred Route.

Source/Content: Reference altitudes come from official government source where available, per this specification's rules otherwise. Fields may contain all-numeric altitudes in feet (one-foot resolution) or alpha/numeric flight levels ('FL' plus three digits of hundreds of feet) or codes.

On Airport/Heliport SID/STAR/Approach records, the first Altitude field is populated when Altitude Description is +, -, B, or G; the second when Altitude Description is B, C, D, or G. Fix altitudes below sea level (e.g., runway threshold below sea level) use a minus sign as the first of five characters.

On Enroute Airway records, the first Minimum Altitude holds MEA/MFA if the same both directions (second left blank); for directional MEAs/MFAs the first holds the coded direction's value and the second the opposite direction. Where government sources provide sensor-specific MEA/MFA (e.g., Conventional vs. RNAV), the value matching the coded Route Type (Section 5.7) is used. The first Minimum Altitude may contain UNKNN (unknown) or NESTB (not established).

On Preferred Routes, Minimum/Maximum Altitude apply to the whole route as a block; Altitude 1 and Altitude 2 are fix-related, per the Altitude Description field.

Used On: Airport and Heliport SID/STAR/Approach Primary and Continuation Records, Holding Pattern, Enroute Airway, Preferred Routes. Length: 5 characters. Character Type: Alpha/numeric. Field Content V removed as a reference.

## 5.31 File Record Number (FRN)

File Record Number (FRN) is a housekeeping reference number assigned to each record, numbered consecutively starting at 00001, subject to change at each file update.

Source/Content: Assigned during file assembly; if the count reaches 99999, the next number restarts at 00000.

Used On: All records. Length: 5 characters. Character Type: Numeric.

## 5.32 Cycle Date (CYCLE)

Cycle Date (CYCLE) identifies the calendar period in which a record was added or last revised. Any ARINC 424 field change — except Dynamic Magnetic Variation, Frequency Protection, Continuation Record Number, and File Record Number — requires a cycle date change; it stays the same if the data is unchanged.

Source/Content: The first two digits are the last two digits of the year of the change; the last two digits are the numeric identity of the 28-day data update cycle (13 per year normally, rarely 14).

Used On: All records. Length: 4 characters. Character Type: Numeric.

## 5.33 VOR/NDB Identifier (VOR IDENT/NDB IDENT)

VOR/NDB Identifier (VOR IDENT/NDB IDENT) identifies the VHF/MF/LF facility defined in the record.

Source/Content: On VHF NAVAIDs, NDB NAVAIDs, and Airport Localizer Marker Records, it holds the official government 1-4 character navigation facility identifier. On Airport and Heliport Localizer and MLS Records, it holds the official identifier of any DME or TACAN Navaid in the data file (including ILSDME, MLSDME/N, MLSDME/P) collocated at the same airport.

Used On: VHF NAVAIDs, NDB NAVAIDs, Airport Localizer Marker records, Airport and Heliport Localizer, and Airport and Heliport MLS records. Length: 4 characters max. Character Type: Alpha/numeric.

## 5.34 VOR/NDB Frequency (VOR/NDB FREQ)

VOR/NDB Frequency (VOR/NDB FREQ) specifies the frequency of the NAVAID named in the VOR/NDB Identifier field.

Source/Content: Derived from official government sources. VHF NAVAID frequencies use characters for hundreds, tens, units, tenths, and hundredths of megahertz; NDB frequencies use thousands, hundreds, tens, units, and tenths of kilohertz. The decimal point after the unit digit is suppressed in both cases.

Used On: VHF NAVAID, NDB NAVAID, Airport Localizer Marker records. Length: 5 characters. Character Type: Numeric.

## 5.35 NAVAID Class (CLASS)

NAVAID Class (CLASS) codes the type of navaid, its coverage, information carried on its signal, and collocation with other navaids, using five columns of codes.

Source/Content: Information for the five columns is transformed from official government source; mapping of codes to output columns for each navaid type is given in the section's tables.

Used On: Navaid Records (VHF, NDB, Airport/Heliport Localizer/Markers/Locators). Length: 5 characters (including blanks). Character Type: Alpha.

The VHF Navaid Record table (Output Record Section/Subsection D, columns 28-32) defines codes for Facility (VOR=V; DME=D; TACAN ch17-59/70-126=T; MIL TACAN ch1-16/60-69=M; ILS/DME and ILS/TACAN=I; MLS/DME/N=N; MLS/DME/P=P), Coverage (Terminal=T, ~25NM/<12000ft; Low Altitude=L, ~40NM/<18000ft; High Altitude=H, ~130NM/<60000ft; Undefined=U; ILS/TACAN=C, Terminal), Additional Information (Biased ILSDME/ILSTACAN=D; Automatic Transcribed Weather Broadcast=A; Scheduled Weather Broadcast=B; No Voice=W; Voice=blank), and Collocation (Collocated=blank; Non-Collocated=Note 1).

|                                         | Col 28        | Col 29        | Col 30       | Col 31   | Col 32      |                                                                                                                                                                         |
|-----------------------------------------|---------------|---------------|--------------|----------|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| Facility                                | Navaid Type 1 | Navaid Type 2 | Range/ Power | Add Info | Collocation | Explanation                                                                                                                                                             |
| VOR                                     | V             |               |              |          |             |                                                                                                                                                                         |
| DME                                     |               | D             |              |          |             |                                                                                                                                                                         |
| TACAN (channels 17-59 & 70-126)         |               | T             |              |          |             |                                                                                                                                                                         |
| MIL TACAN (channels 1-16 & 60-69)       |               | M             |              |          |             |                                                                                                                                                                         |
| ILS/DME                                 |               | I             |              |          |             |                                                                                                                                                                         |
| ILS/TACAN                               |               | I             |              |          |             |                                                                                                                                                                         |
| MLS/DME/N                               |               | N             |              |          |             |                                                                                                                                                                         |
| MLS/DME/P                               |               | P             |              |          |             |                                                                                                                                                                         |
| Coverage                                |               |               |              |          |             |                                                                                                                                                                         |
| Terminal                                |               |               | T            |          |             | Generally usable within 25NM of the facility and below 12000 feet                                                                                                       |
| Low Altitude                            |               |               | L            |          |             | Generally usable within 40NM of the facility and up to 18000 feet                                                                                                       |
| High Altitude                           |               |               | H            |          |             | Generally usable within 130NM of the facility and up to 60000 feet                                                                                                      |
| Undefined                               |               |               | U            |          |             | Coverage not defined by government source                                                                                                                               |
| ILS/TACAN                               |               |               | C            |          |             | Full TACAN facility frequency-paired and operating with the same identifier as an ILS Localizer. Coverage is Terminal                                                   |
| Additional Information                  |               |               |              |          |             |                                                                                                                                                                         |
| Biased ILSDME or ILSTACAN               |               |               |              | D        |             | The zero-range reading of the DME facility is not at the transmitting antenna site.                                                                                     |
| Automatic Transcribed Weather Broadcast |               |               |              | A        |             | The frequency of this Navaid is used for the continuous broadcast of some sort of automated weather system such as AWOS, ASOS, TWEB, AWIB, AWIS.                        |
| Scheduled Weather Broadcast             |               |               |              | B        |             | The frequency of this Navaid is used for the scheduled, non-continuous broadcast of some sort of automated weather system such as VOLMET.                               |
| No Voice on Frequency                   |               |               |              | W        |             | The frequency of this Navaid is not used to support two-way communication between a ground station and aircraft.                                                        |
| Voice on Frequency                      |               |               |              | Blank    |             | The frequency of this Navaid is used to support two-way communication between a ground station and aircraft.                                                            |
| Collocation                             |               |               |              |          |             |                                                                                                                                                                         |
| Collocated Navaids                      |               |               |              |          | Blank       | The latitude/longitude position of the VOR or Localizer portion and the DME or TACAN portion of a VORDME, VORTAC, ILSDME or ILSTACAN are identical. See also Note 1     |
| Non-Collocated Navaids                  |               |               |              |          | Note 1      | The latitude/longitude position of the VOR or Localizer portion and the DME or TACAN portion of a VORDME, VORTAC, ILSDME or ILSTACAN are not identical. See also Note 1 |

## 5.35-x79 NDB Navaid Record -NDBs and Terminal NDBs, Output Record Section/Subsection DB and PN

This section is a table defining the NAVAID Class (CLASS) codes for NDB Navaid Records (NDBs and Terminal NDBs, Output Record Section/Subsection DB and PN, columns 28-32) and for Airport/Heliport Localizer Marker/Locator Records (NDB Locator and Marker Navaids, Subsection PM, columns 75-79).

Facility codes: NDB=H, SABH=S, Marine Beacon=M, Inner Marker=I, Middle Marker=M, Outer Marker=O, Back Marker=C. Coverage codes: High-powered NDB=H (~75NM all altitudes), NDB=blank (~50NM), Low-powered NDB=M (~25NM), Locator=L (~15NM). Additional Information: Automatic Transcribed Weather Broadcast=A, Scheduled Weather Broadcast=B, No Voice=W, Voice=blank. Collocation: BFO Operation=B; for Localizer Marker/Locator records also Locator/Marker Collocated=A, Locator/Middle Marker Not Collocated=N.

Note 1 (Collocation): for VHF Navaid records, N in column 32 is entered when VOR and collocated DME/TACAN lat/long of a frequency-paired VORDME/VORTAC differ by ≥1/10 arc minute (blank if less); the same N/blank convention applies to frequency-paired ILSDME/ILSTACAN, carried on the ILSDME/ILSTACAN record. For Localizer Marker/Locator records, column 79 carries N if Marker and its associated Locator lat/long differ by ≥1/10 arc minute, A if they differ by less, blank if identical.

Note 2: if both a collocation and BFO operations requirement exist for the same Navaid Record, collocation characters take preference.

|                                         | Col 28        | Col 29        | Col 30       | Col 31    | Col 32      |                                                                                                                                                  |
|-----------------------------------------|---------------|---------------|--------------|-----------|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| Facility                                | Navaid Type 1 | Navaid Type 2 | Range/ Power | Add/ Info | Collocation | Explanation                                                                                                                                      |
| NDB                                     | H             |               |              |           |             |                                                                                                                                                  |
| SABH                                    | S             |               |              |           |             |                                                                                                                                                  |
| Marine Beacon                           | M             |               |              |           |             |                                                                                                                                                  |
| Inner Marker                            |               | I             |              |           |             | There is an Inner Marker beacon at this location.                                                                                                |
| Middle Marker                           |               | M             |              |           |             | There is a Middle Marker beacon at this location.                                                                                                |
| Outer Marker                            |               | O             |              |           |             | There is an Outer Marker beacon at this location.                                                                                                |
| Back Marker                             |               | C             |              |           |             | There is a Backcourse Marker at this location.                                                                                                   |
| Coverage                                |               |               |              |           |             |                                                                                                                                                  |
| High-powered NDB                        |               |               | H            |           |             | Generally usable within 75NM of the facility at all altitudes                                                                                    |
| NDB                                     |               |               | Blank        |           |             | Generally usable within 50NM of the facility at all altitude                                                                                     |
| Low-powered NDB                         |               |               | M            |           |             | Generally usable within 25NM of the facility at all altitude                                                                                     |
| Locator                                 |               |               | L            |           |             | Generally usable within 15NM of the facility at all altitudes                                                                                    |
| Additional Information                  |               |               |              |           |             |                                                                                                                                                  |
| Automatic Transcribed Weather Broadcast |               |               |              | A         |             | The frequency of this Navaid is used for the continuous broadcast of some sort of automated weather system such as AWOS, ASOS, TWEB, AWIB, AWIS. |
| Scheduled Weather Broadcast             |               |               |              | B         |             | The frequency of this Navaid is used for the scheduled, non-continuous broadcast of some sort of automated weather system such as VOLMET.        |
| No Voice on Frequency                   |               |               |              | W         |             | The frequency of this Navaid is not used to support two-way communication between a ground station and aircraft.                                 |
| Voice on Frequency                      |               |               |              | Blank     |             | The frequency of this Navaid is used to support two-way communication between a ground station and aircraft.                                     |
| Collocation                             |               |               |              |           |             |                                                                                                                                                  |
| BFO Operation                           |               |               |              |           | B           | Use of Beat Frequency Oscillator type of equipment is required to receive an aural identification signal.                                        |

|                                         | Col. 75       | Col. 76       | Col. 77      | Col. 78   | Col. 79     |                                                                                                                                                  |
|-----------------------------------------|---------------|---------------|--------------|-----------|-------------|--------------------------------------------------------------------------------------------------------------------------------------------------|
| Facility                                | Navaid Type 1 | Navaid Type 2 | Range/ Power | Add Info  | Collocation |                                                                                                                                                  |
| NDB                                     | H             |               |              |           |             |                                                                                                                                                  |
| SABH                                    | S             |               |              |           |             |                                                                                                                                                  |
| Marine Beacon                           | M             |               |              |           |             |                                                                                                                                                  |
| Inner Marker                            |               | I             |              |           |             |                                                                                                                                                  |
| Middle Marker                           |               | M             |              |           |             |                                                                                                                                                  |
| Outer Marker                            |               | O             |              |           |             |                                                                                                                                                  |
| Back Marker                             |               | C             |              |           |             |                                                                                                                                                  |
| Coverage                                |               |               |              |           |             |                                                                                                                                                  |
| High-powered NDB                        |               |               | H            |           |             | Generally usable within 75NM of the facility at all altitudes                                                                                    |
| NDB                                     |               |               | Blank        |           |             | Generally usable within 50NM of the facility at all altitude                                                                                     |
| Low-powered NDB                         |               |               | M            |           |             | Generally usable within 25NM of the facility at all altitude                                                                                     |
| Locator                                 |               |               | L            |           |             | Generally usable within 15NM of the facility at all altitudes                                                                                    |
| Additional Information                  |               |               |              |           |             |                                                                                                                                                  |
| Automatic Transcribed Weather Broadcast |               |               |              | A         |             | The frequency of this Navaid is used for the continuous broadcast of some sort of automated weather system such as AWOS, ASOS, TWEB, AWIB, AWIS. |
| Scheduled Weather Broadcast             |               |               |              | B         |             | The frequency of this Navaid is used for the scheduled, non-continuous broadcast of some sort of automated weather system such as VOLMET.        |
| No Voice on Frequency                   |               |               |              | W         |             | The frequency of this Navaid is not used to support two-way communication between a ground station and aircraft.                                 |
| Voice on Frequency                      |               |               |              | Blank     |             | The frequency of this Navaid is used to support two-way communication between a ground station and aircraft.                                     |
| Collocation                             |               |               |              |           |             |                                                                                                                                                  |
| BFO Operation                           |               |               |              |           | B           | Use of Beat Frequency Oscillator type of equipment is required to receive an aural identification signal. See also Note 2                        |
| Locator/Marker Collocated               |               |               |              |           | A           | The latitude/longitude position of the Locator and Marker are identical. See also Note 1                                                         |
| Locator/Middle Marker Not Collocated    |               |               |              |           | N           | The latitude/longitude position of Locator and Marker are not identical. See also Note 1                                                         |

## 5.36 Latitude (LATITUDE)

Latitude contains the latitude of the navigational feature in the record.

Source/Content: Latitudes needed in the database are defined during route design, often from official government publications. The first character is N or S (N is used for the equator); the following eight numeric characters give degrees, minutes, seconds, tenths and hundredths of seconds, with symbols and decimal point suppressed.

Some RNAV system users may round latitude to less than one hundredth of a second before entry into the airborne computer. Reference points defined by lat/long are listed in Table 5-19.

Used On: NAVAID, Waypoint, Airport, Heliport, Airport and Heliport ILS, Airport Gate, Runway, Airport and Heliport Localizer Marker, Airport and Heliport MLS and GLS (and MLS Continuation), Airway Marker, Airport/Heliport/Enroute Communications, Heliport, Airport and Heliport Helipads, Restrictive Airspace, FIR/UIR, Controlled Airspace, Path Point and GLS Records. Length: 9 characters. Character Type: Alpha/numeric.

## 5.37 Longitude (LONGITUDE)

Longitude contains the longitude of the geographic position of the navigational feature in the record.

Source/Content: Longitudes needed in the database come from route design, often official government publications. The first character is E or W (E is used for the 0/180-degree meridians); the following nine numeric characters give degrees, minutes, seconds, tenths and hundredths of seconds, symbols and decimal point suppressed.

Some RNAV system users may round longitude to less than one hundredth of a second before airborne computer entry. Reference points are listed in Table 5-19.

Used On: NAVAID, Waypoint, Airport, Heliport, Airport and Heliport ILS, Airport Gate, Runway, Helipad, Airport and Heliport Localizer Marker, Airport and Heliport MLS/GLS/MLS Continuation, Airway Marker, Airport/Heliport/Enroute Communications, Heliport, Airport and Heliport Helipads, Restrictive Airspace, FIR/UIR, Controlled Airspace, Path Point and GLS Records. Length: 10 characters. Character Type: Alpha/numeric.

Table 5-19 lists, per record file, which lat/long field defines which location (e.g., Airport→Aerodrome Reference Point, Runway→Runway Landing Threshold, VHF Navaid VOR/DME/TACAN→respective antenna, MLS→Azimuth/Elevation/Back Azimuth/Datum antennas, GLS→GLS Reference Point), with Notes 1-9 clarifying: VOR/DME-TACAN fields are populated per NAVAID Class codes (Notes 1-2); MLS Back Azimuth left blank if no facility (Note 3); MLS Datum is the runway centerline point closest to the elevation antenna phase center (Note 4); Runway threshold may be a displaced threshold if published (Note 5); Localizer Glideslope may be blank if unavailable (Note 6); Communications records use the transmitting antenna location, falling back to the Aerodrome Reference Point or sector center as appropriate, with Remote Facility (5.200) indicating the reference (Notes 7-8); Helipad uses its own reference point or falls back to the airport/heliport reference point (Note 9).

| Record File     | Lat/Long Field        | Location Defined            |
|-----------------|-----------------------|-----------------------------|
| Airport         | Airport               | Aerodrome Reference Point   |
| Airport Comm    | Comm (Note 7)         | Antenna Reference           |
| Enroute Comm    | Comm (Note 8)         | Antenna or Sector Reference |
| Enroute Marker  | Marker                | Marker Antenna              |
| FIR/UIR         | FIR/UIR               | Boundary Position           |
| FIR/UIR         | Arc Origin            | Center of Arc               |
| Gate            | Gate                  | Gate                        |
| Heliport        | Heliport              | Heliport Reference Point    |
| Heliport Comm   | Comm (Note 7)         | Antenna Reference           |
| Localizer       | Localizer             | Localizer Antenna           |
| Localizer       | Glideslope (Note 6)   | Glideslope Antenna          |
| Marker/Locator  | Marker Beacon         | Marker Antenna              |
| Marker/Locator  | Locator               | Locator Antenna             |
| NDB Navaid      | NDB                   | NDB Antenna                 |
| Restr. Airspace | Restr. Airspace       | Boundary Position           |
| Restr. Airspace | Arc Origin            | Center of Arc               |
| VHF Navaid      | VOR (Note 1)          | VOR Antenna                 |
| VHF Navaid      | DME or TACAN (Note 2) | DME or TACAN Antenna        |
| Runway          | Runway (Note 5)       | Runway Landing Threshold    |
| Helipad         | Helipad (Note 9)      | Helipad Reference Point     |
| Waypoint        | Waypoint              | Waypoint                    |
| MLS             | Azimuth               | Azimuth Antenna             |
| MLS             | Elevation             | Elevation Antenna           |
| MLS             | Back Azimuth (Note 3) | Back Azimuth Antenna        |
| MLS             | Datum (Note 4)        | MLS Reference Datum Point   |
| GLS             | GLS                   | GLS Reference Point         |

## 5.38 DME Identifier (DME IDENT)

DME Identifier (DME IDENT) identifies a DME facility, TACAN facility, or the DME/TACAN component of a VORDME or VORTAC facility.

Source/Content: Contains the officially published 2-4 character DME facility identifier. For VOR/DME and VORTAC facilities, the field is blank if the VOR and DME identification codes match; if they differ, VOR Identification follows Section 5.33 and this field carries the DME component's identifier. Blank if the VHF Navaid has no DME component. Always populated for TACANs, DME-only NAVAIDs, and Localizer or MLS DME facilities.

Used On: VHF NAVAID records. Length: 4 characters max. Character Type: Alpha/numeric.

## 5.39 Magnetic Variation (MAG VAR, D MAG VAR)

Magnetic Variation (MAG VAR, D MAG VAR) is the angular difference between True North and Magnetic North at the record's location; Dynamic Magnetic Variation is a computer-model value based on location and date. Station Declination is covered separately in Section 5.66.

Source/Content: Derived from official government and geographical magnetic variation sources. Common terms include Epoch Year Variation (government-determined every ~5 years) — data suppliers use this rather than annual drift figures — and Magnetic Variation of Record, an Epoch Year value applied consistently to everything at a given location (e.g., an airport and its terminal procedures). Dynamic Magnetic Variation, carried in the VHF Navaid Simulation Continuation Record, TACAN-Only Navaid Simulation Continuation Record, and Enroute/Terminal Waypoint Primary Records, is a computed earth-model figure updated on the supplier's schedule and can differ from the static database value.

On Enroute/Airport/Heliport Communication Records, the field holds the magnetic variation at the record's lat/long — matching the referenced navaid/airport record if that position is used (Table 5-19, Notes 7-8), otherwise a government-sourced or Dynamic value for a stand-alone transmitter, or blank if the lat/long fields are blank.

Field position 1 holds a code: E (variation East of True North), W (West of True North), or T (element is provided as TRUE, in which case positions 2-5 are all zeros), followed by the value in degrees and tenths, decimal point suppressed.

Used On: Airport, NDB Navaid, Airport Localizer Marker, MLS, GLS, Airway Marker, Enroute/Airport/Heliport Communication, Heliport, Enroute Waypoint, Airport and Heliport Terminal Waypoint and GLS Primary Records, and VHF Navaid Continuation Records. Length: 5 characters. Character Type: Alpha/numeric.

| Field Content   | Description                                                 |
|-----------------|-------------------------------------------------------------|
| E               | Magnetic variation is East of TRUE North                    |
| W               | Magnetic variation is West of TRUE North                    |
| T               | The element defined in the current record is provided TRUE. |

## 5.40 DME Elevation (DME ELEV)

DME Elevation (DME ELEV) defines the elevation of the DME component of the NAVAID described in the record.

Source/Content: Entered in feet MSL from official government publications; a leading minus (-) sign is used when the elevation is below MSL.

Used On: VHF NAVAID records. Length: 5 characters. Character Type: Alpha/numeric.

## 5.41 Region Code (REGN CODE)

Region Code (REGN CODE) categorizes waypoints and holding patterns as enroute or terminal area; for terminal area, the field identifies the terminal airport.

Source/Content: Contains ENRT for enroute waypoints, or the Airport Ident for terminal waypoints. In the holding pattern file, the content matches the holding fix's classification (ENRT if the holding fix is an enroute waypoint/navaid; the airport identification if it is a terminal waypoint/terminal NDB).

Used On: Waypoint and Holding Pattern records. Length: 4 characters. Character Type: Alpha/numeric.

## 5.42 Waypoint Type (TYPE)

Waypoint Type (TYPE) identifies several data conditions for a waypoint: (1) whether it is published in official government source or created during database coding; (2) whether it is an intersection/DME fix formed relative to ground navaids or an RNAV waypoint formed by lat/long; (3) its function(s) in terminal procedure coding; (4) its location relative to airspace boundaries and/or grid lines; (5) how ATC may use it in operational clearances; (6) whether it is published for VFR use only; and (7) whether it is published for use in a specific terminal procedure type, multiple types, or not published at all.

## 5.42-x81 COMMENTARY

This section notes that it is intended for applications not using airway and terminal procedure records, and that its content partially duplicates Section 5.17.

Source/Content: The table (Page 164) lists valid Waypoint Type codes across three columns — Column 27 (e.g., A=ARC Center Fix, C=Combined Named Intersection/DME Fix and RNAV Waypoint, I=Unnamed Charted Intersection/DME Fix, M=Middle/Inner Marker, N=NDB or Terminal NDB as Waypoint, O=Outer/Back Marker, R=Named Intersection/DME Fix, U=Uncharted Airway Intersection, V=VFR Waypoint, W=RNAV Waypoint); Column 28 (e.g., A=Final Approach Fix, B=Initial+Final Approach Fix, C=Final Approach Course Fix, D=Intermediate Approach Fix, F=Off-Route Waypoint/Intersection/DME Fix, G=Initial Departure Fix, H=Helicopter Only Airway Fix, I=Initial Approach Fix, J=Required Off-Route Waypoint, K/L=Final Approach Course Fix combinations, M=Missed Approach Fix, N=Initial Approach+Missed Approach Fix, O=Oceanic Gateway Fix, P=Unnamed Stepdown Fix, R=RF Leg Fix Not at Procedure Fix, S=Named Stepdown Fix, U=FIR/UIR or Controlled Airspace Intersection, V/W=Lat/Long Fix full/half degree); and Column 29 (D=SID, E=STAR, F=Approach Procedures, Z=Multiple Terminal Procedure Types, G=Source Provided Enroute Waypoint). Unless prohibited, all combinations across columns are valid; each row also indicates applicability to Enroute Airways (EA), Holding (HC), and/or Procedure Coding (PC).

Used On: Enroute Waypoints, Airport and Heliport Terminal Waypoints. Length: 3 characters. Character Type: Alpha.

Notes: Column 28 is always blank when column 27=N (Note 1); column 29 codes are shared between enroute and terminal waypoints and always blank when column 27=N (Note 2); columns 28-29 are blank when column 27=A (ARC Center Fix) (Note 3); code V (VFR Waypoint) in column 27 is not combined with column 28/29 codes (Note 4); column 28=R is used only with column 27=C, R, or W (Note 5); Off-Route Waypoints (F) can be source-provided or supplier-created for referential integrity and are excluded from the Enroute Airway File (Note 6); option G supports ADS-C reporting for ANSP-established waypoints, allowing supplier-created on-route fixes for referential integrity such as Company Routes (Note 7); option J (Required Off-Route Waypoint) supports programs such as FRA in Europe (Note 8).

| ENROUTE AND TERMINAL WAYPOINTS                                     | ENROUTE AND TERMINAL WAYPOINTS   | ENROUTE AND TERMINAL WAYPOINTS   | ENROUTE AND TERMINAL WAYPOINTS   | ENROUTE AND TERMINAL WAYPOINTS   |
|--------------------------------------------------------------------|----------------------------------|----------------------------------|----------------------------------|----------------------------------|
| Waypoint Type                                                      | Column 27                        | Column 28                        | Column 29                        | Use                              |
| ARC Center Fix                                                     | A                                | Note 3                           | Note 3                           | PC                               |
| Combined Named Intersection and/or named DME Fix and RNAV Waypoint | C                                |                                  |                                  | EA, PC                           |
| Unnamed, Charted Intersection and/or Unnamed DME Fix               | I                                |                                  |                                  | EA, PC                           |
| Middle or Inner Marker as Waypoint                                 | M                                |                                  |                                  | PC                               |
| NDB or Terminal NDB Navaid as Waypoint                             | N                                | Note 1                           | Note 2                           | EA, PC                           |
| Outer or Back Marker as Waypoint                                   | O                                |                                  |                                  | PC                               |
| Named Intersection and/or Named DME Fix                            | R                                |                                  |                                  | EA, PC                           |
| Uncharted Airway Intersection                                      | U                                |                                  |                                  | EA                               |
| VFR Waypoint                                                       | V                                | Note 4                           |                                  | EA, PC                           |
| RNAV Waypoint                                                      | W                                |                                  |                                  | EA, PC                           |
| Final Approach Fix                                                 |                                  | A                                |                                  | EA, PC                           |
| Initial Approach Fix and Final Approach Fix                        |                                  | B                                |                                  | EA, PC                           |
| Final Approach Course Fix                                          |                                  | C                                |                                  | EA, PC                           |
| Intermediate Approach Fix                                          |                                  | D                                |                                  | EA, PC                           |
| Off-Route Waypoint, Intersection or DME Fix                        |                                  | F (Note 6)                       |                                  | EA                               |
| Initial Departure Fix                                              |                                  | G                                |                                  | EA, HC, PC                       |
| Helicopter Only Airway Fix                                         |                                  | H                                |                                  | EA                               |
| Initial Approach Fix                                               |                                  | I                                |                                  | EA, PC                           |
| Required Off-Route Waypoint                                        |                                  | J (Note 8)                       |                                  | EA                               |
| Final Approach Course Fix and Initial Approach Fix                 |                                  | K                                |                                  | EA, PC                           |
| Final Approach Course Fix and Intermediate Approach Fix            |                                  | L                                |                                  | EA, PC                           |
| Missed Approach Fix                                                |                                  | M                                |                                  | EA, PC                           |
| Initial Approach Fix and Missed Approach Fix                       |                                  | N                                |                                  | EA, PC                           |
| Oceanic Gateway Fix                                                |                                  | O                                |                                  | EA                               |
| Unnamed Stepdown Fix                                               |                                  | P                                |                                  | PC                               |
| RF Leg Fix Not at Procedure Fix                                    |                                  | R                                | Note 5                           | PC                               |
| Named Stepdown Fix                                                 |                                  | S                                |                                  | PC                               |
| FIR/UIR or Controlled Airspace Intersection                        |                                  | U                                |                                  | EA                               |
| Latitude/Longitude Fix, Full Degree of Latitude                    |                                  | V                                |                                  | EA                               |
| Latitude/Longitude Fix, Half Degree of Latitude                    |                                  | W                                |                                  | EA                               |
| Published for Use in SID                                           |                                  |                                  | D                                | EA, PC                           |
| Published for Use in STAR                                          |                                  |                                  | E                                | EA, PC                           |
| Published for Use in Approach Procedures                           |                                  |                                  | F                                | EA, PC                           |
| Published for Use in Multiple Terminal Procedure Types             |                                  |                                  | Z                                | EA, PC                           |
| Source Provided Enroute Waypoint                                   |                                  |                                  | G (Note 7)                       | EA                               |

## 5.43 Waypoint Name/Description (NAME/DESC)

Waypoint Name/Description (NAME/DESC) provides the unabbreviated name of a named waypoint or a definition of an unnamed waypoint.

Source/Content: Named waypoints are spelled out in full; unnamed waypoint definitions follow Chapter 7 of this specification.

Used On: Enroute Waypoints, Airport and Heliport Terminal Waypoints. Length: 25 characters max. Character Type: Alpha/numeric.

## 5.44 Localizer/MLS/GLS Identifier (LOC, MLS, GLS IDENT)

Localizer/MLS/GLS Identifier (LOC, MLS, GLS IDENT) identifies the localizer, MLS facility, or GLS Reference Path defined in the record.

Source/Content: Contains the identification code of the Localizer, MLS facility, or GLS Reference Path from official government sources.

Used On: Localizer, Localizer Marker, MLS, MLS Continuation, and GLS Records. Length: 4 characters max. Character Type: Alpha/numeric.

## 5.45 Localizer Frequency (FREQ)

Localizer Frequency (FREQ) specifies the VHF frequency of the facility named in the Localizer Identifier field.

Source/Content: Official government-source localizer frequency, entered with 50 kHz resolution, decimal point after the MHz unit digit suppressed.

Used On: Airport and Heliport ILS Localizer records. Length: 5 characters. Character Type: Numeric.

## 5.46 Runway Identifier (RUNWAY ID)

Runway Identifier (RUNWAY ID) identifies runways in runway records and runways served by ILS/MLS in ILS/MLS records.

Source/Content: Derived from official government sources; format is 'RW' followed by two numeric digits (01-36) and an optional fifth character: C (Center, of three parallel runways), L (Left, of two or three parallel), or R (Right, of two or three parallel). Other suffixes (North, South, East, West, True, STOL) are not included.

Used On: Airport and Heliport ILS and MLS, GLS Runway, Airport and Heliport Localizer Marker, Path Point, and GLS Records. Length: 5 characters max. Character Type: Alpha/numeric.

| C   | Center (Runway of three parallel runways)       |
|-----|-------------------------------------------------|
| L   | Left (Runway of two or three parallel runways)  |
| R   | Right (Runway of two or three parallel runways) |

## 5.47 Localizer Bearing (LOC BRG)

Localizer Bearing (LOC BRG) defines the magnetic bearing of the localizer course of the ILS facility/GLS approach in the record.

Source/Content: Derived from official government sources, entered in degrees and tenths of a degree, decimal point suppressed. For courses published as true courses, the last character is 'T' in place of tenths of a degree.

Used On: ILS, GLS records. Length: 4 characters. Character Type: Alpha/numeric.

## 5.48 Localizer Position (LOC FR RW END) Azimuth/Back Azimuth Position (AZ/BAZ FR RW END)

Localizer Position (LOC FR RW END) / Azimuth/Back Azimuth Position (AZ/BAZ FR RW END) defines the location of the facility antenna relative to one end of the runway.

Source/Content: Official government-source distance in feet from the antenna to the runway end, one-foot resolution.

Used On: ILS, MLS and MLS Continuation records. Length: 4 characters. Character Type: Numeric.

## 5.49 Localizer/Azimuth Position Reference (@, +, -)

Localizer/Azimuth Position Reference (@, +, -) indicates whether the Localizer/Azimuth antenna is beyond the stop end, ahead of, or off to the side relative to the runway; the Back-Azimuth Position Reference indicates the same relative to the approach end and stop end.

Source/Content: For Localizer/Azimuth: blank (@) = beyond the stop end; + = ahead of the approach end; - = off to one side. For Back Azimuth: blank (@) = ahead of the approach end; + = beyond the stop end; - = off to one side.

Used On: ILS, MLS and MLS Continuation records. Length: 1 character. Character Type: Alpha.

## 5.50 Glideslope Position (GS FR RW THRES) Elevation Position (EL FR RW THRES)

Glideslope Position (GS FR RW THRES) / Elevation Position (EL FR RW THRES) defines the antenna location relative to the approach end of the runway.

Source/Content: Four numeric characters giving the distance in feet (one-foot resolution) from a line perpendicular to the runway at the antenna position, to the runway threshold.

Used On: ILS and MLS records. Length: 4 characters max. Character Type: Numeric.

## 5.51 Localizer Width (LOC WIDTH)

Localizer Width (LOC WIDTH) specifies the localizer course width of the ILS facility in the record.

Source/Content: Official government-source course widths entered in degrees, tenths, and hundredths of a degree, decimal point suppressed.

Used On: ILS records. Length: 4 characters. Character Type: Numeric.

## 5.52 Glideslope Angle (GS ANGLE) Minimum Elevation Angle (MIN ELEV ANGLE)

Glideslope Angle (GS ANGLE) defines the glideslope angle of an ILS facility/GLS approach; Minimum Elevation Angle (MIN ELEV ANGLE) defines the lowest elevation angle authorized for an MLS procedure.

Source/Content: Official government-source angles entered in degrees, tenths, and hundredths of a degree, decimal point suppressed.

Used On: ILS, GLS and MLS records. Length: 3 characters. Character Type: Numeric.

## 5.53 Transition Altitude/Level (TRANS ALTITUDE/LEVEL)

Transition Altitude/Level (TRANS ALTITUDE/LEVEL) defines, for the vicinity of an airport/heliport, the altitude at or below which aircraft vertical position is controlled by reference to MSL altitudes (Transition Altitude), and the lowest flight level available above it (Transition Level). Descending aircraft use local station pressure through the layer; departing aircraft climbing through it use standard altimeter setting (QNE, 29.92 in Hg / 1013.2 mb / hPa).

Source/Content: Derived from official government sources. For STAR and Approach records, the field is the level (feet) where altimeter setting changes from standard to local for that procedure; for SID records, it is the Transition Altitude (feet) for that SID. The first leg of each SID must carry the transition altitude/level (1-foot resolution); the first leg of each STAR/Approach must carry the transition level (1-foot resolution). If unknown or ATC-assigned, the procedure record field is blank.

For Airport and Heliport records, Transition Altitude and Transition Level are entered in feet (1-foot resolution) in their respective fields; if unknown or ATC-assigned, the airport/heliport field is blank.

Used On: Airport and Heliport SID/STAR/Approach, Airport and Heliport Records. Length: 5 characters. Character Type: Numeric. (Revised to clarify that the Airport/Heliport value, not the procedure value, should be blank when unknown.)

## 5.54 Longest Runway (LONGEST RWY)

Longest Runway (LONGEST RWY) permits airport classification based on the longest operational hard-surface runway.

Source/Content: Derived from official government sources, entered in hundreds of feet; represents the longest hard-surfaced operational runway available without restriction, reflecting pavement length declared suitable for ground operations. Where no hard-surfaced runway exists or qualifies, the value is the longest operational runway at the airport.

Used On: Airport Records. Length: 3 characters. Character Type: Numeric.

## 5.55 Airport/Heliport Elevation (ELEV)

Defines the elevation of the Airport/Heliport in the Airport Elevation and Heliport Elevation field. Derived from official government sources, entered in feet to a resolution of one foot. Above MSL: numeric characters only; below MSL: first character is a minus (-) sign. Airport elevation is the highest elevation of any landing surface on the airport. Used on Airport and Heliport records. Length: 5 characters, Character Type: Alpha/numeric. Examples: 02171, -0142, 05230.

## 5.56 Gate Identifier (GATE IDENT)

Identifies the airport gate defined in the record, in the Gate Identifier field. Coded gate identity derived from official government sources and navigation system users. Used on Gate records. Length: 5 characters max, Character Type: Alpha/numeric. Examples: C134B, 23, 30A, B12A.

## 5.57 Runway Length (RUNWAY LENGTH)

Defines total length of the runway surface identified in the Runway Identifier field. Derived from official government sources, entered in feet with a resolution of one foot; represents the overall runway length regardless of displaced thresholds, starter extensions, stopways, overruns, or clearways. Available landing lengths and take-off runs differ and are provided in the Runway Continuation Records. Because the record's latitude/longitude reflects the Landing Threshold Point (which may be displaced), there is no direct correlation between Runway Length and a value calculated from those coordinates. Used on Runway Records. Length: 5 characters, Character Type: Numeric. Examples: 05000, 07000, 11480. See Figure 5-3 - Runway Profile View.

## 5.58 Runway Magnetic Bearing (RWY BRG)

Specifies the magnetic bearing of the runway (Runway Identifier or Pad Ident field) in the Runway Magnetic Bearing field, entered in degrees and tenths of a degree with the decimal point suppressed. For bearings published as true bearings, the last character is T in place of tenths. On helipad records, may contain the bearing of a former fixed-wing runway converted to helicopter use, or a specific approach bearing from a government source. Used on Runway and Helipad Records. Length: 4 characters, Character Type: Alpha/numeric. Examples: 1800, 2302, 0605, 347T.

## 5.59 Runway Description (RUNWAY DESCRIPTION)

Provides additional information about a runway, when required, in the Runway Description field. Contents are determined when the record is assembled. Used on Runway records. Length: 22 characters max, Character Type: Alpha/numeric. Examples: GROOVED, SINGLE ENG. ONLY.

## 5.60 Name (NAME)

Defines the name commonly applied to the navigation entity in the record, in the Name field, derived from official government or customer sources. Used on Gate and Holding Pattern records. Length: 25 characters max, Character Type: Alpha/numeric. Example: HOLDING JIMEE MIAMI.

## 5.61 Notes (Continuation Records) (NOTES)

Accommodates information that cannot be entered in the primary record, in the Notes field of continuation records. Contents are determined when the primary record is assembled. Used on all records except Company route records. Length: 70 characters max, Character Type: Alpha/numeric. Examples: EASTBOUND PREFERRED; 090/0Z/230/0Z.

## 5.62 Inbound Holding Course (IB HOLD CRS)

Defines the inbound course to the holding waypoint, in the Inbound Holding Course field, entered in degrees and tenths of a degree with the decimal point suppressed. For holding courses published with true bearings, the last character is T in place of tenths. Used on Holding Pattern records. Length: 4 characters, Character Type: Alpha/numeric. Examples: 0456, 1800, 3034, 347T.

## 5.63 Turn (TURN)

Specifies the direction of holding pattern turns in the Turn field, which always contains either L or R. Used on Holding Pattern records. Length: 1 character, Character Type: Alpha.

## 5.64 Leg Length (LEG LENGTH)

Specifies the distance of the inbound or outbound leg of the holding pattern in the Leg Length field; whether inbound or outbound is identified by the content of Section 5.298 of the applicable record. Inbound is the distance between the point at which the aircraft rolls out on the inbound leg and the holding fix; outbound is the distance from a point abeam the holding fix to the beginning of the inbound turn (Figure 5-4). Derived from official government sources, entered in nautical miles and tenths of a nautical mile with the decimal point suppressed. Used on Holding Pattern records. Length: 3 characters, Character Type: Numeric. Examples: 108, 055.

## 5.65 Leg Time (LEG TIME)

Specifies the length of the inbound or outbound leg of a holding pattern in units of time, in the Leg Time field; whether inbound or outbound is identified by the content of Section 5.298 of the applicable record. Inbound is the timing between roll-out on the inbound leg and the holding fix; outbound is the timing from a point abeam the holding fix to the beginning of the inbound turn (Figure 5-4). Derived from official government sources, entered in minutes and tenths of a minute with the decimal point suppressed. Used on Holding Pattern records. Length: 2 characters, Character Type: Numeric. Examples: 10, 15, 20.

## 5.66 Station Declination (STN DEC)

For VHF NAVAIDS, defines the angular difference between true north and the zero-degree radial of the NAVAID at the time it was last site checked, in the Station Declination field. For ILS localizers, defines the angular difference between true north and magnetic north at the localizer antenna site when the localizer course's magnetic bearing was established. Derived from official government sources; the field contains an alpha character (see table) followed by the declination value in degrees and tenths of a degree, decimal point suppressed. When column 1 is coded T or G, the remainder of the field is coded all zeros. Table: E = Declination East of True North; W = Declination West of True North; T = Station oriented to True North where local variation is not zero; G = Station oriented to Grid North. Used on VHF NAVAID and ILS records. Length: 5 characters, Character Type: Alpha/numeric. Examples: E0072, E0000, T0000, G0000. Commentary (5.66-x83): a G in column 1 alerts users that although a NAVAID declination may not be zero, an unknown grid reference prevents defining a value.

| Column 1 Character   | Declination Description                                                                |
|----------------------|----------------------------------------------------------------------------------------|
| E                    | Declination is East of True North                                                      |
| W                    | Declination is West of True North                                                      |
| T                    | Station is oriented to True North in an area in which the local variation is not zero. |
| G                    | Station is oriented to Grid North                                                      |

## 5.67 Threshold Crossing Height (TCH)

Specifies the height above the landing threshold on a normal glide path, in the Threshold Crossing Height field. Derived from official government sources when available: on Runway Records it equals the Glideslope Height at the landing threshold for ILS/MLS approaches; if no ILS/MLS but an RNAV approach exists, it is the published TCH for that procedure; otherwise it is 40 or 50 feet per the table (40 feet when all approaches are for Category A/B aircraft only, or runway length is less than 6000 feet with no published approach; 50 feet when at least one approach is published for Category C or D, or runway length is 6000 feet or greater with no published approach). On Approach Continuation Records it is the published TCH; on ILS or MLS Records it is the glideslope height at the threshold; on GLS records it is the glide path height at the threshold. Commentary (5.67-x84): the single TCH on the Runway Record may differ, sometimes significantly, from the TCH on the Approach Continuation Record for a procedure to the same runway; comparisons of procedure altitude data to threshold elevation/TCH should only be made against the Approach Continuation Record and GLS Record. Used on Airport and Heliport ILS and MLS Runway, Airport, and Heliport Approach Continuation Records. Length: 3 characters, Character Type: Numeric. Examples: 037, 050, 109, 101.

| Content   | Description                                                                                                  |
|-----------|--------------------------------------------------------------------------------------------------------------|
| 40 (feet) | On Runway records for which all approach procedures are published for Category A and B aircraft only.        |
| 40 (feet) | On Runway records with a length of less than 6000 feet and no published approach procedure.                  |
| 50 (feet) | On Runway records for which there is at least one approach procedure published for Category C or D aircraft. |
| 50 (feet) | On Runway records with a length of 6000 feet or greater and no published approach procedure.                 |

## 5.68 Landing Threshold Elevation (LANDING THRES ELEV)

Defines the elevation of the landing threshold of the runway/helipad in the Landing Threshold Elevation field. Derived from official government sources, entered in feet to a resolution of 1 foot. Above MSL: numeric characters only; below MSL: first character is a minus (-) sign. Used on Runway Airport and Heliport Helipad records. Length: 5 characters, Character Type: Alpha/numeric. Examples: 01250, -0150.

## 5.69 Threshold Displacement Distance (DSPLCD THR)

Defines the distance from the extremity of a runway to a threshold not located at that extremity, in the Threshold Displacement Distance field. Derived from official government sources, entered in feet. Used on Runway records. Length: 4 characters, Character Type: Numeric. Examples: 0485, 1260.

## 5.70 Vertical Angle (VERT ANGLE)

Defines the angular portion of the vertical navigation path in STAR Route and Approach Procedure Route records, in the Vertical Angle field. Should cause the aircraft to fly at the last coded altitude and then descend on the VNAV path, projected back from the fix and altitude in the route sequence containing the Vertical Angle. Uses official government source values when available; for Precision Approach Procedures it is the angle assigned to the glideslope; for non-precision procedures it is the government-published VNAV Path angular definition or a value computed per the rules in Attachment 5. Values greater than zero are preceded by a minus sign (-) to indicate descending flight; when no government value is available and none can be computed, the field is populated with all zeros and no minus sign. Expressed in degrees, tenths, and hundredths of degrees with the decimal point suppressed; maximum value 9.99 degrees. Used on Airport and Heliport STAR and Approach Route Records. Length: 4 characters (first character (-) or blank), Character Type: Alpha/numeric. Examples: -300, -275, -542, 000.

## 5.71 Name Field

Further defines the record by name, in the Name field. Facility name derived from official government sources; a parenthetical name following the official name may identify the facility's location. Used on Navaid, Airport, Heliport and Enroute Marker records. Length: 30 characters, Character Type: Alpha/numeric.

## 5.72 Speed Limit (SPEED LIMIT)

Defines a minimum, maximum, or mandatory indicated air speed (KIAS) for a fix, leg, or multiple legs in a terminal procedure; a maximum allowed airspeed for an airport or heliport terminal environment; or a maximum airspeed within an airspace, in the Speed Limit field. Derived from official government source documentation, shown in Knots. On an Airport or Heliport Record it indicates the maximum allowed speed for all flight segments departing or arriving that terminal area, at and below the Speed Limit Altitude (5.73). On Airport and Heliport SID/STAR/Approach Records it indicates a speed for a fix, leg, or multiple legs, used with Speed Limit Description (5.261). On a Controlled Airspace record it describes the speed restriction within the airspace. Used on Airport and Heliport SID/STAR/Approach, Airport and Heliport, Flight Planning Arr/Dep Data, and Controlled Airspace Records. Length: 3 characters, Character Type: Alpha/Numeric. Example: 250. Section was updated to reference the speed limit in Controlled Airspace Record.

## 5.73 Speed Limit Altitude

Defines the altitude below which speed limits may be imposed, in the Speed Limit Altitude field. Derived from official government sources in feet MSL or FLs. Used on Airport and Heliport, and Controlled Airspace records. Length: 5 characters, Character Type: Alpha/numeric. Examples: 10000, FL125. Section was updated to reference the speed limit in Controlled Airspace Record.

## 5.74 Component Elevation (GS ELEV, EL ELEV, AZ ELEV, BAZ ELEV)

Defines the elevation of a given component in the Localizer, GLS and MLS records, in the Component Elevation field. GS ELEV defines the Glideslope component elevation in Localizer Records; EL ELEV the Elevation component of the MLS Record; AZ ELEV the Azimuth component of the MLS Record; BAZ ELEV the Back-Azimuth component of the MLS Record; GLS ELEV the GLS ground station elevation in the GLS record. Derived from official government publications with respect to MSL; below-MSL elevations have a minus (-) sign as the first column. Used on Localizer, MLS and GLS Records and MLS Continuation Records. Length: 5 characters, Character Type: Alpha/numeric. Examples: 00235, 01265, -0011.

## 5.75 From/To - Airport/Heliport/Fix

On Company Routes and Helicopter Operations Company Routes, the From Airport/Heliport/Fix is the fix from which the route originates and the To Airport/Heliport/Fix is the fix at which it terminates. On Alternate Records it is the Departure, Destination or Enroute Airport/Fix for which alternate information is provided. The customer defines origination/termination points and which departure, destination, or enroute points have alternate information; on Company Routes and Helicopter Operations Company Routes may reference airport, heliport, navaid, or waypoint records, further defined by ICAO, Section, and Subsection data. Used on Company Route, Helicopter Operations Company Route and Alternate Records. Length: 5 characters max, Character Type: Alpha/numeric.

## 5.76 Company Route Ident

Identifies each unique route between origination and destination, in the Company Route Ident field. Determined by the customer. Used on Company Route Records and Helicopter Operations Company Routes. Length: 10 characters, Character Type: Alpha/numeric.

## 5.77 VIA Code

Defines the type of route used in the SID/STAR/Approach/Airways field (Section 5.78) on Company Route records, and the type of route used in the AWY Identifier on Preferred Route records; on Preferred Route records, some codes also define the use of, or restriction on, a fix or routing. The code must be selected from the Company Route Record (R) table: ALT (Alternate Airport), APP (Approach Route), APT (Approach Transition), AWY (Designated Airway), DIR (Direct to Fix), INT (Initial Fix), PRE (Preferred Route), SID (Standard Instrument Departure), SDE (Standard Instrument Departure - Enroute Transition), SDY (Standard Instrument Departure - Runway Transition), STR (Standard Terminal Arrival and Profile Descent), STE (Standard Terminal Arrival and Profile Descent - Enroute Transition), STY (Standard Terminal Arrival and Profile Descent - Runway Transition).

| VIA Field   | Description                                                        |
|-------------|--------------------------------------------------------------------|
| ALT         | Alternate Airport                                                  |
| APP         | Approach Route                                                     |
| APT         | Approach Transition                                                |
| AWY         | Designated Airway                                                  |
| DIR         | Direct to Fix                                                      |
| INT         | Initial Fix                                                        |
| PRE         | Preferred Route                                                    |
| SID         | Standard Instrument Departure                                      |
| SDE         | Standard Instrument Departure - Enroute Transition                 |
| SDY         | Standard Instrument Departure - Runway Transition                  |
| STR         | Standard Terminal Arrival and Profile Descent                      |
| STE         | Standard Terminal Arrival and Profile Descent - Enroute Transition |
| STY         | Standard Terminal Arrival and Profile Descent - Runway Transition  |

## 5.77-x85 Preferred Route Record (ET)

Defines the VIA Field codes for Preferred Route Records: AWY (Designated Airway), DIR (Direct to Fix), INT (Initial Fix), RVF (Route via Fix), RNF (Route via Fix not permitted), SID (Standard Instrument Departure), STR (Standard Terminal Arrival and Profile Descent). A Current Via x Next Via sequencing table indicates which VIA sequences are disallowed (N) versus allowed (blank); for example INT and DIR may not be followed by most listed Via values, while ALT may not be followed by any Via (all N). Note 1: N means sequence not allowed, blank means sequence is allowed. Note 2: the To Fix must match the beginning fix of the following Via. Used on Company Route and Preferred Route records and Helicopter Operations Company Routes. Length: 3 characters, Character Type: Alpha/numeric. Table 5-20 (Company Route Record (R) Field Content) specifies, per VIA code, how the S/S/A AIRWAY, AREA, TO FIX, RWY TRANS, ENRT TRANS, CRUISE ALT, TERM/ALT ARPT, and ALT DIST fields must be completed, e.g. ALT requires Area, Arpt or Heliport Ident, and Dist in NM; SID requires SID Ident, Fix Ident, Rwy Ident/All or Blank, and Trans Ident or Blank.

| VIA Field   | Description                                   |
|-------------|-----------------------------------------------|
| AWY         | Designated Airway                             |
| DIR         | Direct to Fix                                 |
| INT         | Initial Fix                                   |
| RVF         | Route via Fix                                 |
| RNF         | Route via Fix not permitted                   |
| SID         | Standard Instrument Departure                 |
| STR         | Standard Terminal Arrival and Profile Descent |

| Current   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   | Next Via   |
|-----------|------------|------------|------------|------------|------------|------------|------------|------------|------------|------------|------------|------------|
| Via       | INT        | DIR        | SDY        | SID        | SDE        | AWY        | STE        | STR        | STY        | APT        | APP        | ALT        |
| INT       | N          |            |            |            |            |            |            |            |            |            |            |            |
| DIR       | N          |            |            |            |            |            |            |            |            |            |            |            |
| SDY       | N          |            | N          |            |            |            |            |            |            |            |            |            |
| SID       | N          |            | N          | N          |            |            |            |            |            |            |            |            |
| SDE       | N          |            | N          | N          | N          |            |            |            |            |            |            |            |
| AWY       | N          |            | N          | N          | N          |            |            |            |            |            |            |            |
| STE       | N          |            | N          | N          | N          | N          | N          |            |            |            |            |            |
| STR       | N          |            | N          | N          | N          | N          | N          | N          |            |            |            |            |
| STY       | N          |            | N          | N          | N          | N          | N          | N          | N          |            |            |            |
| APT       | N          |            | N          | N          | N          | N          | N          | N          | N          | N          |            |            |
| APP       | N          |            | N          | N          | N          | N          | N          | N          | N          | N          | N          |            |
| ALT       | N          | N          | N          | N          | N          | N          | N          | N          | N          | N          | N          | N          |

| VIA      | S/S/A AIRWAY   | AREA   | TO FIX             | RWY TRANS              | ENRT TRANS             | CRUISE ALT   | TERM/ALT ARPT                                         | ALT DIST   |
|----------|----------------|--------|--------------------|------------------------|------------------------|--------------|-------------------------------------------------------|------------|
| ALT      | Blank          | Area   | Blank              | Blank                  | Blank                  | ALT or Blank | Arpt or Heliport Ident                                | Dist in NM |
| APP      | Apch Ident     | Area   | Optional           | Blank                  | Tml Rte Ident or Blank | Blank        | Arpt or Heliport Ident if TO FIX Ident is Terminal    | Blank      |
| APT      | Apch Ident     | Area   | Fix Ident          | Blank                  | Trans Ident            | Blank        | Airport or Heliport ident if TO FIX Ident is Terminal | Blank      |
| AWY      | Awy Ident      | Area   | Fix Ident          | Blank                  | Blank                  | ALT or Blank | Blank                                                 | Blank      |
| DIR, INT | Blank          | Area   | Fix Ident          | Blank                  | Blank                  | ALT or Blank | Airport or Heliport Ident if TO FIX Ident is Terminal | Blank      |
| SID      | SID Ident      | Area   | Fix Ident          | Rwy Ident/All or Blank | Trans Ident or Blank   | ALT or Blank | Airport or Heliport if TO FIX Ident is Terminal       | Blank      |
| SDE      | SID Ident      | Area   | Fix Ident          | Blank                  | Trans Ident            | ALT or Blank | Airport or Heliport Ident if TO FIX Ident is Terminal | Blank      |
| SDY      | SID Ident      | Area   | Fix Ident          | Rwy Ident              | Blank                  | ALT or Blank | Airport or Heliport Ident if TO FIX Ident is Terminal | Blank      |
| STR      | STAR Ident     | Area   | Fix Ident of Blank | Rwy Ident/All          | Trans Ident or Blank   | ALT or Blank | Airport or Heliport Ident if TO FIX Ident is Terminal | Blank      |
| STE      | STAR Ident     | Area   | Fix Ident          | Blank                  | Trans Ident            | ALT or Blank | Airport or Heliport Ident if TO FIX Ident is Terminal | Blank      |
| STY      | STAR Ident     | Area   | Fix Ident          | Rwy Ident              | Blank                  | ALT or Blank | Airport or Heliport Ident if TO FIX Ident is Terminal | Blank      |
| PRE      | Pref Rte Ident | Area   | Fix Ident          | Blank                  | Blank                  | ALT or Blank | Airport or Heliport Ident if TO FIX Ident is Terminal | Blank      |

## 5.78 SID/STAR/APP/AWY (S/S/A/AWY) SID/STAR/AWY (S/S/AWY)

Provides the identifier of the enroute airway or terminal route to be flown, referenced by the VIA field (Section 5.77); further defined by the Route Type and Route Type Qualifier data in columns 95/96/97 of the Company Route or 106/107/108 of the Preferred Route. For Company Route records this field can contain the SID/STAR, Approach, Enroute Airway, or Preferred Route Identifier (Sections 5.8, 5.9, and 5.10). For Preferred Route records this field can contain the SID/STAR or Enroute Airway Route Identifier (Section 5.8). Blank for certain records depending on the VIA field content (Section 5.77). Used on Company Route and Preferred Route Records, and Helicopter Operations Company Routes. Length: 6 characters, Character Type: Alpha/numeric. Examples: SID -> CUIT8, STR -> LOCKE9, APP -> I19L, R35-Z, AWY -> J501.

## 5.79 Stopway

Defines Stopway as the length of an area beyond the take-off runway, no less wide than the runway and centered upon the extended centerline of the runway, designated for use in decelerating the airplane during an aborted takeoff. Derived from official government sources and shown in feet (see Table 5-15). Used on Runway records. Length: 4 characters, Character Type: Numeric. Examples: 0900, 1000.

## 5.80 ILS/MLS/GLS Category (CAT)

For ILS/MLS/GLS stations, defines the Facility Performance Category (Category I, II, and III) up to which the station is operating as a minimum; does not imply permission to use the facility for landing guidance to that level, nor limit minimal use to the designated classification. Also used to define the classification for other than ILS/MLS/GLS installations such as LOC, IGS, LDA, or SDF. Derived from official government sources and indicated by a table value: 0 = Localizer only, no Glideslope; 1 = ILS/MLS/GLS Category I; 2 = ILS/MLS/GLS Category II; 3 = ILS/MLS/GLS Category III; I = IGS Facility; L = LDA Facility with Glideslope; A = LDA Facility, no Glideslope; S = SDF Facility with Glideslope; F = SDF Facility, no Glideslope. Used on Localizer, MLS and MLS Continuation Records, GLS Record. Length: 1 character, Character Type: Alpha/numeric.

| Definition                    | Category/ Classification   |
|-------------------------------|----------------------------|
| Localizer only, no Glideslope | 0                          |
| ILS /MLS/GLS Category I       | 1                          |
| ILS /MLS/GLS Category II      | 2                          |
| ILS /MLS/GLS Category III     | 3                          |
| IGS Facility                  | I                          |
| LDA Facility with Glideslope  | L                          |
| LDA Facility, no Glideslope   | A                          |
| SDF Facility with Glideslope  | S                          |
| SDF Facility, no Glideslope   | F                          |

## 5.81 ATC Indicator (ATC)

Indicates that altitudes shown in the altitude fields can be modified by ATC or will be assigned by ATC, in the ATC Indicator field. Contains the alpha character A when the official government source states the altitude can be modified or assigned by ATC. Contains the alpha character S when the official government source states the altitude will be assigned by ATC or if no altitude is supplied. Used on Airport and Heliport SID/STAR/Approach Records. Length: 1 character, Character Type: Alpha.

## 5.82 Waypoint Usage

The Waypoint Usage field indicates the structure in which the waypoint is utilized (record column 31): B = HI and LO Altitude, H = HI Altitude, L = LO Altitude, blank = Terminal Use Only (not used enroute). Used on Waypoint (EA/PC) and Heliport Terminal Waypoint (HC) records. Length: 1 character, Character Type: Alpha. This section also defines the Company Route, Helicopter Operation Company Route, and Preferred Route To Fix field, used to terminate the route referenced in the SID/STAR/APCH/AWY field (Section 5.78), or to terminate a Direct segment or start an Initial segment when no SID/STAR/APCH/AWY is referenced. For Company Route records the field contains Enroute Waypoint, Airport Terminal Waypoint, VHF NAVAID, NDB NAVAID, Terminal NDB NAVAID, Airport or Runway Identifier. For Helicopter Operations Company Route records it contains Enroute Waypoint, Helicopter Terminal Waypoint, VHF NAVAID, NDB NAVAID, Terminal NDB NAVAID, Airport, Heliport, Runway Identifier or Helipad Identifier; Terminal Fixes, Runway Identifiers or Helipad Identifiers must be for the From Airport/Heliport or To Airport/Heliport and consistent with the VIA Code. For Preferred Route records the field contains Enroute Waypoint, Terminal Waypoint, VHF NAVAID, NDB NAVAID or Terminal NDB NAVID, Airport Identifier. Used on Company Route, Helicopter Operations Company Route, and Preferred Route Records. Length: Company Route/Helicopter Operations Company Route - 6 characters max; Preferred Route - 5 characters max. Character Type: Alpha/numeric. Examples: SHARP, BHM, DEN43, KDEN, RW35R.

| Usage                                | Record Column Content   |
|--------------------------------------|-------------------------|
| Usage                                | 31                      |
| HI and LO Altitude                   | B                       |
| HI Altitude                          | H                       |
| LO Altitude                          | L                       |
| Terminal Use Only (not used enroute) | Blank                   |

## 5.84 RUNWAY TRANS

Identifies the desired runway transition of the applicable SID or STAR, in the RUNWAY TRANS field. Together with the Section/Subsection identified for the SID/STAR/App/AWY field, it links directly to the SID/STAR procedure records depending on the Company Route/Helicopter Operations Company Route.

## 5.83 To FIX

Defines the desired runway transition for a SID/STAR in Company Route or Helicopter Operations Company Route records, applied together with the VIA field (Section 5.77). If VIA field contains SID or STR: when the SID/STAR has explicit runway transitions per the Procedure Route Type, this field uniquely identifies the desired runway transition; if no runway transition is desired, the field is blank. If the SID/STAR does not have explicit runway transitions per the Procedure Route Type, this field is always non-blank and exactly matches the TRANS IDENT field of the SID/STAR procedure records (i.e., when a SID starts with Route Type 2 or a STAR ends with Route Type 2). If VIA field contains SDY or STY, the field contents follow the same rules as SID/STR but the field is always non-blank; the field is blank for all other VIA field contents. Length: 5 characters. Character Type: Alpha/numeric.

## 5.85 ENRT TRANS

Together with the Section/Subsection identified for the SID/STAR/App/AWY field, this field identifies the desired enroute transition of the applicable SID or STAR, and can also identify the desired approach transition of an approach. If VIA field contains SID or STR, this field uniquely identifies the desired SID/STAR enroute transition; blank if none desired. If VIA field contains SDE or STE, the same rules apply except the field is always non-blank. If VIA field contains APP, this field uniquely identifies the desired approach transition; blank if none desired. The field is blank for all other VIA field contents. Used on Company Route, Helicopter Operations Company Route Records. Length: 5 characters. Character Type: Alpha/numeric.

## 5.86 Cruise Altitude

Establishes an Enroute Cruise Altitude, entered on Company Route records as specified by the customer, who supplies the Cruise Altitude in feet or flight level. Used on Company Route, Helicopter Operations Company Route Records. Length: 5 characters. Character Type: Alpha/numeric.

## 5.87 TERMINAL/ALTERNATE Airport (TERM/ALT ARPT)

Has two uses depending on the VIA field and File Code for To Fix. When VIA field content is ALT, this field contains the Alternate Airport Ident or Heliport Ident for the Company Route. If the To Fix file code contains P, this field contains the Airport Ident for REGN CODE (Section 5.41) of Terminal Waypoints (PC records) and Runway (PG records). If the To Fix file code contains H, this field contains the Heliport Ident for REGN CODE (Section 5.41) of Helicopter Terminal Waypoints (HC records). See Section 5.6, Airport/Heliport Identifier. Used on Company Route, Helicopter Operations Company Route Records. Length: 4 characters. Character Type: Alpha/numeric.

## 5.88 Alternate Distance (ALT DIST)

Supplies the distance in nautical miles from the To Airport/Heliport/Fix to the Alternate Airport/Heliport. Values are supplied by the customer and must be equal to or greater than the great circle distance from the destination airport/fix to the alternate airport/heliport. Used on Company Route, Helicopter Operations Company Route Records. Length: 4 characters. Character Type: Numeric.

## 5.89 Cost Index

Defines the relative value of fuel-related costs and time-related costs for a particular route. Source is supplied by the customer airline. Used on Company Route, Helicopter Operations Company Route Records. Length: 3 characters. Character Type: Numeric.

## 5.90 ILS/DME Bias

Specifies the DME offset. The field contains a 2-digit bias term in nautical miles and tenths of a nautical mile with the decimal point suppressed; it is blank for unbiased DMEs. Used on VHF NAVAID Records containing ILS/DME or MLS/DME Facilities. Length: 2 characters. Character Type: Numeric.

## 5.91 Continuation Record Application Type (APPL)

Indicates the specific application of a continuation record via a one-character type code (see table). Used on Continuation Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                                                                                     |
|-----------------|-----------------------------------------------------------------------------------------------------------------|
| A               | A standard ARINC 424 Continuation containing Notes or other formatted data not covered by a define Continuation |
| B               | Combined Controlling Agency/Call Sign and formatted Time of Operation                                           |
| C               | Call Sign/Controlling Agency Continuation                                                                       |
| E               | Primary Record Extension                                                                                        |
| L               | VHF Navaid/TACAN Only Navaid Limitation Continuation                                                            |
| N               | A Sector Narrative Continuation                                                                                 |
| T               | A Time of Operations Continuation, formatted time data                                                          |
| U               | A Time of Operations Continuation Narrative time data                                                           |
| V               | A Time of Operations Continuation, Start/End Date                                                               |
| P               | A Flight Planning Application Continuation                                                                      |
| S               | Simulation Application Continuation                                                                             |
| W               | An Airport or Heliport Procedure Data Continuation                                                              |

## 5.92 Facility Elevation (FAC ELEV)

Provides the elevation of navaids and communications transmitters. Facility Elevation data is derived from official government source, provided in feet with a resolution of one foot, referenced to MSL. When the elevation is below MSL, the first character of the field is a minus sign (-). Used on ILS Marker, Airway Marker Primary Records, Enroute/Airport/Heliport Primary Extension Continuation Records, VHF Navaids and NDB Navaids Simulation Continuation Records. Length: 5 characters. Character Type: Alpha/numeric.

## 5.93 Facility Characteristics (FAC CHAR)

Identifies the characteristics of the NAVAID facility, encoded in columns 28-32 depending on facility type (see table): synchronous/asynchronous/unknown status for VHF NAVAID, ILS & MLS; voice ident presence for VHF NAVAID/NDB NAVAID/Locator; type of emission and repetition rate for NDB NAVAID; ILS DME location relative to Localizer/Glideslope; ILS Back Course usability; MLS/DME or DME/P location relative to Azimuth/Elevation; and MLS Approach Azimuth Scan Rate. Used on ILS Marker Primary records, VHF Navaid, NDB Navaid and ILS/MLS continuation records. Length: 5 characters. Character Type: Alpha/numeric. Note 1: 0=A0, 1=A1, 2=A2. Note 2: enter number of occurrences per minute if known, else blank. Note 3: Collocated means the latitudes and longitudes of the two facilities differ by no more than 1 arc second. Note 4: enter H if high-rate approach azimuth guidance is available, otherwise blank. Commentary (5.93-x86): The NDB emission designators in Note 1 are being replaced with new designators (A0→NON, A1→A1A/A1B, A2→A2A) per the 1979 ITU World Administrative Radio Conference.

| Facility                                    | 28   | 29   | 30    | 31     | 32     |
|---------------------------------------------|------|------|-------|--------|--------|
| VHF NAVAID, ILS & MLS                       |      |      |       |        |        |
| Synchronous                                 | S    |      |       |        |        |
| Asynchronous                                | A    |      |       |        |        |
| Unknown                                     | U    |      |       |        |        |
| VHF NAVAID, NDB NAVAID and Locator          |      |      |       |        |        |
| Voice Ident                                 |      | Y    |       |        |        |
| No Voice Ident                              |      | N    |       |        |        |
| Undefined                                   |      | U    |       |        |        |
| NDB NAVAID                                  |      |      |       |        |        |
| Type of emission                            |      |      | Note1 |        |        |
| 400H                                        |      |      |       | 4      |        |
| 1020H                                       |      |      |       | 1      |        |
| Repetition Rate                             |      |      |       |        | Note 2 |
| ILS DME Location                            |      |      |       |        |        |
| Collocated with Localizer Note 3            |      |      |       |        | L      |
| Collocated with Glideslope                  |      |      |       |        | G      |
| Not collocated with Localizer or Glideslope |      |      |       |        | Blank  |
| ILS Back Course                             |      |      |       |        |        |
| Usable                                      |      |      |       | Y      |        |
| Unusable                                    |      |      |       | N      |        |
| Restricted                                  |      |      |       | R      |        |
| Undefined                                   |      |      |       | U      |        |
| MLS, DME or DME/P Location                  |      |      |       |        |        |
| Collocated with Azimuth                     |      |      |       |        | A      |
| Collocated with Elevation                   |      |      |       |        | E      |
| Not Collocated with Azimuth or Elevation    |      |      |       |        | N      |
| MLS Approach Azimuth Scan Rate              |      |      |       | Note 4 |        |

| Present Designator   | New Designator   | Description                                   |
|----------------------|------------------|-----------------------------------------------|
| A0                   | NON              | Unmodulated Carrier                           |
| A1                   | A1A              | Carrier keyed, bandwidth less than 0.1 kHz    |
| A1                   | A1B              | Carrier keyed, bandwidth greater than 0.1 kHz |
| A2                   | A2A              | Tone keyed modulation                         |

## 5.94 True Bearing (TRUE BRG)

Allows the true bearing to be provided independently of the magnetic bearing given in the primary record for ILS localizer, MLS Azimuth, MLS Back Azimuth and Runway records. True Bearings are entered in degrees, tenths and hundredths of a degree with the decimal point suppressed. When source magnetic bearing data is provided as true with intent to be used as true, the Magnetic Bearing and True Bearing values are identical. See Section 5.95 for source description. Used on ILS Continuation, MLS Continuation and Runway Continuation records. Length: 5 characters. Character Type: Numeric.

## 5.95 Government Source (SOURCE)

Indicates whether the True Bearing is derived from official government sources or other sources. The field contains Y when derived from official government sources, N when derived from other sources, and T when the source Magnetic and True bearings are provided only in True. Used on ILS, MLS, MLS continuation and runway continuation records. Length: 1 character. Character Type: Alpha.

## 5.96 Glideslope Beam Width (GS BEAM WIDTH)

Specifies the glide path beam width of the Glideslope defined in the record. Glideslope beam widths from official government sources are entered in degrees, tenths and hundredths of a degree with the decimal point suppressed. Used on ILS continuation records. Length: 3 characters. Character Type: Numeric.

## 5.97 Touchdown Zone Elevation (TDZE)

The Touchdown Zone Elevation is the highest elevation in the first 3,000 feet of the landing surface beginning at the threshold. Touchdown zone elevations from official government sources are used when available; otherwise the runway threshold elevation is entered, or if unavailable, the Airport reference point elevation (see TDZE Location, Section 5.98). Entered in feet, resolution of 1 foot, with respect to MSL; below-MSL elevations begin with a minus (-) sign. Used on Runway continuation records. Length: 5 characters. Character Type: Alpha/numeric.

## 5.98 TDZE Location (LOCATION)

Indicates whether the TDZ elevation was obtained from official government sources or other sources. The field contains T for official source, L if the landing threshold elevation is used, or A if the airport elevation is used. Used on Runway continuation records. Length: 1 character. Character Type: Alpha.

## 5.99 Marker Type (MKR TYPE)

Defines the type of marker via a 3-character code in record columns 18-20 (see table): Inner Marker (IM), Middle Marker (MM), Outer Marker (OM), Back Marker (BM), and Locator at Marker (L). Used on Airport Localizer Marker records. Length: 3 characters. Character Type: Alpha.

| Type of Facility   | Record Column Content   | Record Column Content   | Record Column Content   |
|--------------------|-------------------------|-------------------------|-------------------------|
| Type of Facility   | 18                      | 19                      | 20                      |
| Inner Marker       |                         | I                       | M                       |
| Middle Marker      |                         | M                       | M                       |
| Outer Marker       |                         | O                       | M                       |
| Back Marker        |                         | B                       | M                       |
| Locator at Marker  | L                       |                         |                         |

## 5.100 Minor Axis Bearing (MINOR AXIS TRUE BRG)

Indicates the true bearing of the minor axis of marker beacons. This field contains the true bearing in degrees and tenths of a degree, with the decimal point suppressed. Used on Airport Localizer Marker records. Length: 4 characters. Character Type: Numeric.

## 5.101 Communications Type (COMM TYPE)

A three-character code indicating the type of communications service available on the frequency contained in the record (see Communications Type Translation Table for decoding), derived from official source or created by the data supplier. The table lists codes such as ACC (Area Control Center), ACP (Airlift Command Post), AIR (Air to Air), APP (Approach Control), ARR (Arrival Control), ASO (ASOS), ATI (ATIS), AWI (AWIB), AWO (AWOS), AWS (AWIS), CBA/CCA (Class B/C Airspace), CLD (Clearance Delivery), CPT (Clearance Pre-Taxi), CTA (Control Area Terminal), CTF (CTAF), CTL (Control), DEP (Departure Control), DIR (Director), EFS (EFAS), EMR (Emergency), FSS (Flight Service Station), GCO (Ground Comm Outlet), GND (Ground Control), GTE (Gate Control), HEL (Helicopter Frequency), INF (Information), MBZ (Mandatory Broadcast Zone), MIL (Military), MUL (Multicom), OPS (Operations), PAL (Pilot Activated Lighting), RDO (Radio), RDR (Radar), RFS (RFSS), RMP (Ramp/Taxi Control), RSA (ARSA), TCA/TMA (Terminal Control Area), TML (Terminal), TRS (TRSA), TWE (TWEB), TWR (Tower), UAC (Upper Area Control), UNI (Unicom), and VOL (Volmet), each flagged as applying to Airport/Heliport comm only, Enroute comm only, or both. Note 1: PAL is used only when frequencies are exclusively for airport lighting activation; if the frequency also carries voice communications, the Pilot Controlled Lighting parameter of the Service Indicator is used instead. Note 2: CTF and MBZ are used only in Australia, New Zealand and East Timor. Used on Enroute, Airport and Heliport Communications. Length: 3 characters. Character Type: Alpha.

| Field Content   | Description                                   | Airport Heliport Comm Only   | Enroute Comm Only   | Both Comm Type   |
|-----------------|-----------------------------------------------|------------------------------|---------------------|------------------|
| ACC             | Area Control Center                           |                              |                     | X                |
| ACP             | Airlift Command Post                          | X                            |                     |                  |
| AIR             | Air to Air                                    | X                            |                     |                  |
| APP             | Approach Control                              | X                            |                     |                  |
| ARR             | Arrival Control                               | X                            |                     |                  |
| ASO             | Automatic Surface Observing System (ASOS)     | X                            |                     |                  |
| ATI             | Automatic Terminal Info Service (ATIS)        | X                            |                     |                  |
| AWI             | Airport Weather Information Broadcast (AWIB)  | X                            |                     |                  |
| AWO             | Automatic Weather Observing Service (AWOS)    |                              |                     | X                |
| AWS             | Aerodrome Weather Information Services (AWIS) | X                            |                     |                  |
| CBA             | Class B Airspace                              | X                            |                     |                  |
| CCA             | Class C Airspace                              | X                            |                     |                  |
| CLD             | Clearance Delivery                            | X                            |                     |                  |
| CPT             | Clearance, Pre-Taxi                           | X                            |                     |                  |
| CTA             | Control Area (Terminal)                       | X                            |                     |                  |
| CTF             | Common Traffic Advisory Frequencies Note      | X                            |                     |                  |
| CTL             | Control                                       |                              |                     | X                |
| DEP             | Departure Control                             | X                            |                     |                  |
| DIR             | Director (Approach Control Radar)             | X                            |                     |                  |
| EFS             | Enroute Flight Advisory Service (EFAS)        |                              | X                   |                  |
| EMR             | Emergency                                     |                              |                     | X                |
| FSS             | Flight Service Station                        |                              |                     | X                |
| GCO             | Ground Comm Outlet                            | X                            |                     |                  |
| GND             | Ground Control                                | X                            |                     |                  |
| GTE             | Gate Control                                  | X                            |                     |                  |
| HEL             | Helicopter Frequency                          | X                            |                     |                  |
| INF             | Information                                   |                              |                     | X                |
| MBZ             | Mandatory Broadcast Zone Note                 | X                            |                     |                  |
| MIL             | Military Frequency                            |                              |                     | X                |
| MUL             | Multicom                                      |                              |                     | X                |
| OPS             | Operations                                    | X                            |                     |                  |
| PAL             | Pilot Activated Lighting Note                 | X                            |                     |                  |
| RDO             | Radio                                         |                              |                     | X                |
| RDR             | Radar                                         |                              |                     | X                |
| RFS             | Remote Flight Service Station (RFSS)          |                              |                     | X                |
| RMP             | Ramp/Taxi Control                             | X                            |                     |                  |
| RSA             | Airport Radar Service Area (ARSA)             | X                            |                     |                  |
| TCA             | Terminal Control Area (TCA)                   | X                            |                     |                  |

| Field Content   | Description                          | Airport Heliport Comm Only   | Enroute Comm Only   | Both Comm Type   |
|-----------------|--------------------------------------|------------------------------|---------------------|------------------|
| TMA             | Terminal Control Area (TMA)          | X                            |                     |                  |
| TML             | Terminal                             | X                            |                     |                  |
| TRS             | Terminal Radar Service Area (TRSA)   | X                            |                     |                  |
| TWE             | Transcriber Weather Broadcast (TWEB) |                              | X                   |                  |
| TWR             | Tower, Air Traffic Control           | X                            |                     |                  |
| UAC             | Upper Area Control                   |                              | X                   |                  |
| UNI             | Unicom                               | X                            |                     |                  |
| VOL             | Volmet                               |                              | X                   |                  |

## 5.102 Radar (RADAR)

Indicates whether the communications unit identified in the record has access to and uses information derived from primary or secondary radars while performing the service indicated by the Communications Type; it is not an indication of an operational radar frequency. Derived from official government sources. The field is R if primary or secondary radar information is available, N if source documentation specifically states no access, or U if source documentation provides no details. Used on Enroute, Airport and Heliport Communications records. Length: 1 character. Character Type: Alpha.

## 5.103 Communications Frequency (COMM FREQ)

Specifies either the transmit or receive frequency of the communications service, depending on column location. Each record contains both transmit and receive frequencies unless the service is Transmit Only or Receive Only; content is identical if transmit and receive frequency match; fields are blank for digital services. Content is derived from official government sources: HF frequencies are five significant digits plus one decimal in kHz (decimal suppressed, e.g., 17955 kHz = 1795500, 8965 kHz = 0896500); VHF frequencies with 100/50/25 kHz spacing are three significant digits plus three decimals in MHz (e.g., 118.50 MHz = 0118500, 131.275 MHz = 0131275); UHF frequencies are three significant digits plus two decimals in MHz (e.g., 267 MHz = 0026700, 287.5 MHz = 0028750); VHF frequencies with 8.33 kHz spacing use four significant digits plus three decimals as the assigned channel number (e.g., 132.0583 MHz becomes channel 132.060 = 0132060). The decimal point is always suppressed; the Frequency Units field (Section 5.104) assists in determining the actual frequency. Used on Enroute, Airport and Heliport Communications Records. Length: 7 characters. Character Type: Numeric.

## 5.104 Frequency Units (FREQ UNIT)

Designates the frequency spectrum area of the Communications Frequency (Section 5.103) field, or that the field contains a channel, and for VHF units also designates the required frequency spacing. Codes (see table): L=Low Frequency, M=Medium Frequency, H=High Frequency (2800-30,000 kHz), K=VHF 100 kHz spacing, F=VHF 50 kHz spacing, T=VHF 25 kHz spacing, V=VHF (30,000 kHz-200 MHz) non-standard spacing, U=UHF (200-3000 MHz), C=VHF Communication Channel for 8.33 kHz spacing, D=Digital Service. Note 1: L and M are used only when the transmitting frequency is an LF/MF Navaid (NDB); a receiving frequency in the same record would be VHF. Note 2: D is used for data link type services, in which case transmit/receive frequency columns are blank. Used on Enroute, Airport, and Heliport Communications records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                                      |
|-----------------|------------------------------------------------------------------|
| L               | Low Frequency Note 1                                             |
| M               | Medium Frequency Note 1                                          |
| H               | High Frequency (2800 kHz to 30,000 kHz)                          |
| K               | Very High Frequency 100 kHz spacing                              |
| F               | Very High Frequency 50 kHz spacing                               |
| T               | Very High Frequency 25 kHz spacing                               |
| V               | Very High Frequency (30,000 kHz to 200 MHz) Non-standard spacing |
| U               | Ultra-High Frequency (200 MHz to 3000 MHz)                       |
| C               | Very High Frequency Communication Channel for 8.33kHz spacing    |
| D               | Digital Service Note 2                                           |

## 5.105 Call Sign (CALL SIGN)

Contains the name of a communications service provider used when contacting that service or used by the service to identify itself when contacting aircraft on the frequencies in the record; also provides the broadcast identification name of automated services. Call Signs and broadcast service identification names are derived from official government sources. The type of service may be omitted from the Call Sign field when it matches the service identified in Communications Type (5.101), e.g., APP→LION (APPROACH omitted), TWR→LION (TOWER omitted), DEP→LONDON APPROACH, ACC→DENVER CENTER. Used on Airport, Enroute, and Heliport Communications Records. Length: 25 characters. Character Type: Alpha/numeric.

## 5.106 Service Indicator (SERV IND)

Further defines the use of the frequency for the specified Communication Type (5.101), via codes in columns 112-114. Table 5-21 (Airport Heliport Communications Records): column 112 - A=Airport Advisory Service (AAS), C=Community Aerodrome Radio Station (CARS), D=Departure Service, F=Flight Information Service (FIS), I=Initial Contact, L=Arrival Service, S=Aerodrome Flight Information Service (AFIS), T=Terminal Area Control; column 113 - A=Aerodrome Traffic Frequency (ATF), C=Common Traffic Advisory Frequency (CTAF), M=Mandatory Frequency (MF), S=Secondary Frequency; column 114 - D=VHF Direction Finding Service (VDF), L=Language other than English, M=Military Use Frequency, P=Pilot Controlled Light (PCL). Table 5-22 (Enroute Communications Records): column 112 - A=Aeronautical Enroute Information Service (AEIS), F=Flight Information Service (FIS); column 113 - A=Air/Ground, D=Discrete Frequency, M=Mandatory Frequency, S=Secondary Frequency; column 114 - D=VDF, L=Language other than English, M=Military Use Frequency. Used on Enroute, Airport, and Helicopter Communications records. Length: 3 characters. Character Type: Alpha.

| Description                                                        | Column Contents   | Column Contents   | Column Contents   |
|--------------------------------------------------------------------|-------------------|-------------------|-------------------|
|                                                                    | 112               | 113               | 114               |
| Airport Advisory Service (AAS)                                     | A                 |                   |                   |
| Community Aerodrome Radio Station (CARS)                           | C                 |                   |                   |
| Departure Service (Other than Departure Control Unit)              | D                 |                   |                   |
| Flight Information Service (FIS)                                   | F                 |                   |                   |
| Initial Contact (IC)                                               | I                 |                   |                   |
| Arrival Service (Other than Arrival Control Unit)                  | L                 |                   |                   |
| Aerodrome Flight Information Service (AFIS)                        | S                 |                   |                   |
| Terminal Area Control (Other than dedicated Terminal Control Unit) | T                 |                   |                   |
| Aerodrome Traffic Frequency (ATF)                                  |                   | A                 |                   |
| Common Traffic Advisory Frequency (CTAF)                           |                   | C                 |                   |
| Mandatory Frequency (MF)                                           |                   | M                 |                   |
| Secondary Frequency                                                |                   | S                 |                   |
| VHF Direction Finding Service (VDF)                                |                   |                   | D                 |
| Language other than English                                        |                   |                   | L                 |
| Military Use Frequency                                             |                   |                   | M                 |
| Pilot Controlled Light (PCL)                                       |                   |                   | P                 |

| Description                                     | Column Contents   | Column Contents   | Column Contents   |
|-------------------------------------------------|-------------------|-------------------|-------------------|
|                                                 | 112               | 113               | 114               |
| Aeronautical Enroute Information Service (AEIS) | A                 |                   |                   |
| Flight Information Service (FIS)                | F                 |                   |                   |
| Air/Ground                                      |                   | A                 |                   |
| Discrete Frequency                              |                   | D                 |                   |
| Mandatory Frequency                             |                   | M                 |                   |
| Secondary Frequency                             |                   | S                 |                   |
| VHF Direction Finding Service (VDF)             |                   |                   | D                 |
| Language other than English                     |                   |                   | L                 |
| Military Use Frequency                          |                   |                   | M                 |

## 5.107 ATA/IATA Designator (ATA/IATA)

Contains the Airport/Heliport ATA/IATA designator code to which the record's data relates. Content should be derived from IATA Reservations Manual Part II, IATA Resolution 763/Location Identifiers. Used on Airport and Heliport records. Length: 3 characters. Character Type: Alpha.

## 5.108 IFR Capability (IFR)

Indicates if the Airport/Heliport has any published Instrument Approach Procedures. The field contains Y if there is an Official Government Instrument Approach Procedure published, otherwise N. (Presence of Y does not necessarily imply the published instrument approach is coded in the database.) Used on Airport and Heliport records. Length: 1 character. Character Type: Alpha.

## 5.109 Runway Width (WIDTH)

Specifies the width of the runway identified in the Runway Identifier field. Runway widths from Official Government Sources are entered in feet, resolution of one foot; for runways of variable width, the minimum width over the runway length is entered. Used on Runway records. Length: 3 characters. Character Type: Numeric.

## 5.110 Marker Ident (MARKER IDENT)

Contains a unique computer ident assigned to each enroute marker. A unique identifier is created for each enroute marker since such idents are not designated by official sources; established using the 2-character ICAO code followed by two numeric digits to keep markers unique within a given ICAO region. Used on Enroute marker records. Length: 4 characters. Character Type: Alpha/numeric.

## 5.111 Marker Code (MARKER CODE)

Contains the coded ident that provides an aural and visual indication of station passage in the cockpit, keyed to transmit dots or dashes, or both, on a radio frequency of 75 MHz with a modulating tone frequency of 3000 Hz. The field contains the Morse code ident derived from official government sources. Used on Enroute marker records. Length: 4 characters. Character Type: Alpha.

## 5.112 Marker Shape (SHAPE)

Defines the radiation pattern of an airways marker as either bone or elliptical. The field contains the shape derived from official government sources when available: B designates bone shape, E designates elliptical shape; E is entered when the source does not supply shape information. Used on Enroute airways marker records. Length: 1 character. Character Type: Alpha.

## 5.113 High/Low (HIGH/LOW)

Indicates the power of the enroute marker. The field contains the power derived from official government sources: L indicates low power for use at low altitudes, H indicates high power for general use. Used on Enroute marker records. Length: 1 character. Character Type: Alpha.

## 5.114 Duplicate Indicator (DUP IND)

The Duplicate Identifier field further defines holding patterns when official government sources designate more than one Holding Pattern on a Navaid or Waypoint. Holding Patterns derive from official government source documents, which normally specify the airspace structure in which the holding is used and may designate more than one Holding Pattern for a single Navaid or Waypoint. More than one holding is designated on a single fix when Inbound Holding Course, Turn Direction, Altitude, Leg Length or Leg Time, or Holding Speed differ within the same airspace structure. If only one Holding Pattern is designated for a fix with undefined airspace structure, the field contains 00. If only one Holding Pattern is designated with defined airspace structure, or the same holding applies to more than one airspace structure, position one contains a digit 1 through 6 and position two contains 0. If more than one holding is designated for a single fix within one airspace structure type, position one contains a digit 1 through 6 and position two contains a digit 0 through 9 depending on the number of holdings. If multiple holdings for a single fix include some without a defined airspace structure, those carry digit 7 in position one and 0 through 9 in position two. Used On: Holding Pattern Records. Length: 2 characters. Character Type: Numeric. Examples: 00, 10, 61, 32.

|                                | Duplicate Indicator   | Duplicate Indicator   |
|--------------------------------|-----------------------|-----------------------|
| Holding Pattern                | Position One Airspace | Position Two Multiple |
| Undefined (None Defined)       | 0                     | See Note 1            |
| High Altitude                  | 1                     | See Note 1            |
| Low Altitude                   | 2                     | See Note 1            |
| SID                            | 3                     | See Note 1            |
| STAR                           | 4                     | See Note 1            |
| Approach                       | 5                     | See Note 1            |
| Missed Approach                | 6                     | See Note 1            |
| Undefined (with other defined) | 7                     | See Note 1            |
| All Altitude                   | 8                     | See Note 1            |

## 5.115 Directional Restriction

The Direction Restriction field, when used on Enroute Airway records, indicates the direction an Enroute Airway is to be flown. When used on Preferred Route records, it indicates whether the routing is available only from the initial fix to the terminus fix or in both directions. Direction Restrictions are derived from official government sources and coded and supplied as follows.

## 5.115-x87 Enroute Airway Records

For Enroute Airway Records: F indicates one way in the direction the route is coded (Forward); B indicates one way in the opposite direction (Backward); Blank indicates no restriction on direction. For Preferred Route Records (5.115-x87-x88): F indicates a Uni-directional Preferred Route usable only from Initial Fix to Terminus Fix; B indicates a Bi-directional Preferred Route usable from Initial Fix to Terminus Fix or vice versa. Used On: Enroute Airway and Preferred Route Records. Length: 1 character. Character Type: Alpha.

| F     | One way in direction route is coded (Forward).           |
|-------|----------------------------------------------------------|
| B     | One way in opposite direction route is coded (backward). |
| Blank | No restrictions on direction.                            |

| F   | Uni-directional Preferred Route, usable only from Initial Fix to Terminus Fix.                               |
|-----|--------------------------------------------------------------------------------------------------------------|
| B   | Bi-directional Preferred Route, usable from Initial Fix to Terminus Fix or from Terminus Fix to Initial Fix. |

## 5.116 FIR/UIR Identifier (FIR/UIR IDENT)

The FIR/UIR Identifier field identifies the Flight Information Region and Upper Information Region of airspace with defined dimensions within which Flight Information Service and Alerting Service are provided, identifying the controlling Area Control Center or Flight Information Center. Derived from official government sources, it contains the four-character identifier assigned to the airspace; areas charted as NO FIR use XX plus a two-digit numeric. On Flight Planning Continuation records, entries relate to the altitude structure: for records classed as high altitude, the FIR field is blank; where a single FIR identifier is valid for both low and high altitude, the UIR field is blank; for records classed as both low and high altitude, both FIR and UIR identifiers are entered. Used On: FIR/UIR, VHF NAVAID, NDB NAVAID, Enroute, Terminal Waypoint, Airport Flight Planning Continuation and Heliport records. Length: 4 characters. Character Type: Alpha. Examples: DAAG, SGAS, XX02.

## 5.117 FIR/UIR Indicator (IND)

When used on Enroute Communications Records, the content definition for the FIR/UIR Record applies whenever the FIR/RDO field (5.190) of the Enroute Communications Record contains an Information Region Identifier; in all other cases the Indicator field is blank. Field Content: F for FIR, U for UIR, B for Combined FIR/UIR. Used On: FIR/UIR and Enroute Communications records. Length: 1 character. Character Type: Alpha.

| Type             | Field Content   |
|------------------|-----------------|
| FIR              | F               |
| UIR              | U               |
| Combined FIR/UIR | B               |

## 5.118 Boundary Via (BDRY VIA)

The Boundary VIA defines the path of the boundary from the position identified in the record to the next defined position, determined from official government sources or the application rules below, selected from the table: C Circle, G Great Circle, H Rhumb Line, L Counter Clockwise ARC, R Clockwise ARC; position two E indicates end of description, return to origin point. Application Rules: Special Use Airspace following rivers, country, state or other political boundaries is averaged using a series of straight lines so no path is greater than two miles from the actual boundary, coded G. A named waypoint on an airway crossing an irregular FIR/UIR boundary uses the waypoint coordinates to define a point in that boundary path, with Boundary VIA appropriate to the path. Paths following lines of latitude are coded H; paths following lines of longitude may be coded G or H, with consistent use within a single airspace desired. Otherwise, H is used only when specifically stated in official source as Rhumb Line or not along latitude/longitude; other straight lines are coded G. Refer to Figure 5-5 for sample coding of Boundary VIA Codes. Used On: Controlled Airspace, FIR/UIR, and Restrictive Airspace records. Length: 2 characters. Character Type: Alpha.

| Field Position 1   | Content Position 2   | Description                                |
|--------------------|----------------------|--------------------------------------------|
| C                  |                      | Circle                                     |
| G                  |                      | Great Circle                               |
| H                  |                      | Rhumb Line                                 |
| L                  |                      | Counter Clockwise ARC                      |
| R                  |                      | Clockwise ARC                              |
|                    | E                    | End of description, return to origin point |

|   Seq No. | Boundary Via   | Latitude   | Longitude   | Arc Origin Latitude   | Arc Origin Longitude   |   Arc Dist |   Arc Brg |
|-----------|----------------|------------|-------------|-----------------------|------------------------|------------|-----------|
|       010 | H              | N45-00-00  | W060-00-00  |                       |                        |            |           |
|       020 | G              | N45-00-00  | W047-00-00  |                       |                        |            |           |
|       030 | G              | N43-12-45  | W048-05-00  |                       |                        |            |           |
|       040 | G              | N41-18-24  | W046-16-12  |                       |                        |            |           |
|       050 | G              | N38-58-54  | W048-30-36  |                       |                        |            |           |
|       060 | H              | N37-20-15  | W047-00-00  |                       |                        |            |           |
|       070 | R              | N37-20-15  | W049-31-00  | N37-20-18             | W052-30-30             |        115 |       090 |
|       080 | H              | N37-20-15  | W055-30-00  |                       |                        |            |           |
|       090 | G              | N42-00-00  | W055-30-00  |                       |                        |            |           |

## 5.119 Arc Distance (ARC DIST)

The Arc Distance field defines the distance in nautical miles from the Arc Origin position to the arc defining the lateral boundary of a FIR/UIR or Restrictive Airspace. Derived from official government sources when available, in nautical miles and tenths of a nautical mile with the decimal point suppressed; entered only when Boundary Via is A, C, L, or R. Used On: FIR/UIR, Restrictive Airspace, and Controlled Airspace records. Length: 4 characters. Character Type: Numeric. Examples: 0080, 0150, 1000.

## 5.120 Arc Bearing (ARC BRG)

The Arc Bearing field contains the true bearing from the Arc Origin position to the beginning of the arc. Derived from official government sources when available, in degrees and tenths of a degree with the decimal point suppressed; entered only when Boundary Via is A, C, L, or R. Used On: FIR/UIR, Restrictive Airspace, and Controlled Airspace records. Length: 4 characters. Character Type: Numeric. Examples: 0900, 1800, 3450.

## 5.121 Lower/Upper Limit

Special Use Airspace is described by both lateral and vertical boundaries; the Lower/Upper Limit fields contain the lower and upper limits of the FIR/UIR or Restrictive Airspace being described, derived from official government sources. The field may contain altitude (all numeric), flight levels (alpha/numeric, alpha characters FL followed by altitude in hundreds of feet), or an all-alpha entry, entered on the first record only of each FIR/UIR or Restrictive Airspace being described. Used On: FIR/UIR, Restrictive Airspace, and Controlled Airspace records. Length: 5 characters. Character Type: Alpha/numeric. Examples: all numeric 05000, 25000; alpha/numeric FL245, FL450; all alpha NOTSP (Not Specified), UNLTD (unlimited), GND (Ground), MSL (Mean Sea Level), NOTAM (Restrictive Airspace only).

## 5.122 FIR/UIR ATC Reporting Units Speed (RUS)

The FIR/UIR ATC Reporting Units Speed field indicates the units of measurement concerning True Air Speed used in the specific FIR/UIR to fulfill the requirements of ICAO flight plan, derived from official government publications and entered on the first record only for each FIR/UIR identifier. Field Entry: 0 Not specified, 1 TAS in Knots, 2 TAS in Mach, 3 TAS in Kilometers/hr. Used On: FIR/UIR records. Length: 1 character. Character Type: Numeric.

| Reporting Units      |   Field Entry |
|----------------------|---------------|
| Not specified        |             0 |
| TAS in Knots         |             1 |
| TAS in Mach          |             2 |
| TAS in Kilometers/hr |             3 |

## 5.123 FIR/UIR ATC Reporting Units Altitude (RUA)

The FIR/UIR ATC Reporting Units Altitude field indicates the units of measurement concerning the altitude used in the specific FIR/UIR to fulfill the requirements of ICAO flight plan, derived from official government publications and entered on the first record only for each FIR/UIR identifier. Field Entry: 0 Not specified, 1 ALT in Flight Level, 2 ALT in Meters, 3 ALT in Feet. Used On: FIR/UIR records. Length: 1 character. Character Type: Numeric.

| Reporting Units     |   Field Entry |
|---------------------|---------------|
| Not specified       |             0 |
| ALT in Flight Level |             1 |
| ALT in Meters       |             2 |
| ALT in Feet         |             3 |

## 5.124 FIR/UIR Entry Report (ENTRY)

The FIR/UIR Entry Report field indicates whether an entry report on ICAO flight plan is required for that specific FIR/UIR, derived from official government publications. Y indicates Entry Report is required, N indicates no Entry Report is required, entered on the first record only for each FIR/UIR identifier. Used On: FIR/UIR records. Length: 1 character. Character Type: Alpha.

## 5.125 FIR/UIR Name

The FIR/UIR Name field contains the official name of the controlling agency of the FIR/UIR of which this record is an element, derived from official publications. Areas without a specific FIR/UIR designation are labeled NO FIR. Used On: FIR/UIR records. Length: 25 characters. Character Type: Alpha/numeric. Examples: ACCRA, FIR, ASUNCION FIR/UIR, NO FIR.

## 5.126 Restrictive Airspace Name

The Restrictive Airspace Name field contains the name of the restrictive airspace when assigned, derived from official government sources. The name, if assigned, is entered in the first record only; if source does not assign a name, the field may be blank. Used On: Restrictive Airspace records. Length: 30 characters. Character Type: Alpha/numeric. Examples: RANDOLPH ONE MOA, SAMBURU GAME RESERVE.

## 5.127 Maximum Altitude (MAX ALT)

The Maximum Altitude field indicates the Maximum Altitude Allowed (MAA). On Enroute Airway Records, it is derived from official government publications describing a maximum allowable flight altitude, or the upper limit of the airway when no MAA is provided, expressed in feet or flight level. On Holding Pattern Records, it is a value provided in source documentation that restricts use of the Holding, expressed in feet or flight level; in all other cases the field is left blank. On Preferred Route Records, it is the maximum flight altitude at which the preferred route is established, or the upper limit of the airspace in which the route is published. Used On: Enroute Airway, Holding Pattern, and Preferred Route records. Length: 5 characters. Character Type: Alpha/numeric. Examples: all numeric 17999, 08000; alpha/numeric FL100, FL450; all alpha UNLTD (unlimited).

## 5.128 Restrictive Airspace Type (REST TYPE)

The Restrictive Airspace Type field indicates the type of Airspace in which the flight of aircraft is prohibited or restricted, continuously or for specified times, derived from official government publications. Field codes: A Alert, C Caution, D Danger, M Military Operations Area, N National Security Area, P Prohibited, R Restricted, T Training, W Warning, U Unspecified or Unknown. Used On: Restrictive Airspace and Enroute Airway Flight Planning Continuation records. Length: 1 character. Character Type: Alpha.

| Type                     | Field   |
|--------------------------|---------|
| Alert                    | A       |
| Caution                  | C       |
| Danger                   | D       |
| Military Operations Area | M       |
| National Security Area   | N       |
| Prohibited               | P       |
| Restricted               | R       |
| Training                 | T       |
| Warning                  | W       |
| Unspecified or Unknown   | U       |

## 5.129 Restrictive Airspace Designation

The Restrictive Airspace Designation field contains the number or name that uniquely identifies the restrictive airspace, derived from official government sources. The field contains a numeric number, or when designation is by name, the name up to 10 characters; when the name is longer than 10 characters, the 10th position contains an asterisk indicating the name field should be used for the full designator. Used On: Restrictive Airspace and Enroute Airway Flight Planning Continuation records. Length: 10 characters. Character Type: Alpha/numeric.

| Field Content      | Field Content   | Field Content   | Field Content   |
|--------------------|-----------------|-----------------|-----------------|
| Charted Designator | ICAO            | Type            | Rest. Desig.    |
| RJ(R)-116          | RJ              | R               | 116             |
| R-2524             | K2              | R               | 2524            |
| Crystal MOA        | K4              | M               | Crystal         |
| Randolph MOA One B | K4              | M               | Randolph*       |

## 5.130 Multiple Code (MULTI CD)

The Multiple Code field is used to indicate Restrictive Airspace Areas or MSA Centers having the same designator but subdivided or differently divided by lateral and/or vertical detail. It is used when official government publications for Restrictive Airspace divide an area with the same designator into different areas of activation, altitude or other defining characteristics; for MSA Centers, it provides different sectorization and altitudes for MSAs published with the same center. The field contains an alpha/numeric character uniquely identifying each area or MSA: the first affected record could contain A and multiple primary records could contain B, C, D, 0, 1, etc., as required. Used On: Controlled Airspace, Restrictive Airspace, Airport and Heliport MSA Center, Airport and Heliport SID/STAR/Approach, and Enroute Airway Flight Planning Continuation Records. Length: 1 character. Character Type: Alpha/numeric.

## 5.131 Time Code (TIME CD)

On the Primary or Primary Extension Continuation Record of most record types (excluding Airway Restriction Records), the Time Code field indicates whether the record's data is available continuously or not continuously. On a Time of Operations Continuation Record (other than Airway Restriction Records), it indicates how to interpret the Time of Operations Continuation Records. On Airway Restriction Primary and Continuation Records, the Time Code indicates continuous or non-continuous operation, with details contained in the same record. Active times are derived from official government source and contain an alpha character with an associated description per the Primary Records, Continuation Records, and Primary and Continuation Records tables (e.g., C Active Continuously including holidays, H Active Continuously excluding holidays, N Active Non-Continuously refer to Continuation Record, P Active times announced by NOTAM, U Active times not specified in source documentation; continuation values H, N, T for Time of Operation format or Note Form). Used On: Primary Records (Restrictive Airspace, Preferred Route, Controlled Airspace), Primary Extension Continuation Records (Airport, Heliport, Enroute Communications), Time of Operations Continuation Records (Restrictive Airspace, Preferred Route, Controlled Airspace, Airport, Heliport, Enroute Communications), and Enroute Airway Restriction Primary and Continuation Records. Length: 1 character. Character Type: Alpha.

| PRIMARY RECORDS   | PRIMARY RECORDS                                        |
|-------------------|--------------------------------------------------------|
| Field Content     | Description                                            |
| C                 | Active Continuously, including holidays                |
| H                 | Active Continuously, excluding holidays                |
| N                 | Active Non-Continuously, Refer to Continuation Record  |
| P                 | Active times announced by NOTAM                        |
| U                 | Active times are not specified in source documentation |

|    | CONTINUATION RECORDS                                                                        |
|----|---------------------------------------------------------------------------------------------|
| H  | Active times are provided in Time of Operation format and exclude holidays                  |
| N  | Activation Times are too complex for Time of Operation format and are provided in Note Form |
| T  | Active times are provided in Time of Operation format and include holidays                  |

| PRIMARY AND CONTINUATION RECORDS   | PRIMARY AND CONTINUATION RECORDS                                           |
|------------------------------------|----------------------------------------------------------------------------|
| Field Content                      | Description                                                                |
| C                                  | Active Continuously, including holidays                                    |
| H                                  | Active Continuously, excluding holidays                                    |
| S                                  | Active times are provided in Time of Operation format and exclude holidays |
| T                                  | Active times are provided in Time of Operation format and include holidays |

## 5.132 NOTAM

Restrictive Airspace areas may not have established active times and are activated by NOTAM, or may be active by NOTAM in addition to established times. Active times by NOTAM are derived from official government source. On primary records, the area is active only by NOTAM and there is no continuation record. On continuation records, the area is active by NOTAM in addition to the established times. The field contains the alpha character N to indicate either condition; otherwise the field is blank. Used On: Controlled Airspace, Restrictive Airspace, and Restrictive Airspace Continuation records. Length: 1 character. Character Type: Alpha.

## 5.133 Unit Indicator (UNIT IND)

Restrictive Airspace lower and upper limits are specified as above Mean Sea Level (MSL) or Above Ground Level (AGL); this field permits the unit of measurement to be indicated. The units of lower and upper limits are derived from official government source. The alpha character M indicates MSL and the alpha character A indicates AGL. Used On: Controlled Airspace, Restrictive Airspace records. Length: 1 character. Character Type: Alpha.

## 5.134 Cruise Table Identifier (CRSE TBL IDENT)

A standard cruising level table is established by ICAO and observed except when a modified table is prescribed by regional air navigation agreements; this field permits the enroute airway record to identify the Cruise Table record used for cruise levels. Cruise Levels are derived from official government sources. For the standard ICAO cruise table, the field contains AA; for countries with a modified table, it contains BB, CC, etc. If a country uses the standard ICAO table or a modified table but an airway or portion is flown opposite the cruise table, the field contains alpha/numeric characters identifying the table to be used (e.g., AO exception to ICAO cruise table, BB-ZZ modified cruise table, BO-ZO exception to modified cruise table). Used On: Enroute Airway, FIR/UIR, Cruise Table, and Flight Planning Arrival/Departure Data Records. Length: 2 characters. Character Type: Alpha/numeric.

| Field Content   | Description                        |
|-----------------|------------------------------------|
| AA              | ICAO standard cruise table         |
| AO              | Exception to ICAO cruise table     |
| BB - ZZ         | Modified cruise table              |
| BO - ZO         | Exception to modified cruise table |

## 5.135 Course FROM/TO

The Course From field indicates the lowest course, and the Course To field the highest course, for which a block of cruising levels is prescribed. The Courses are derived from official government sources in degrees and tenths of a degree with the decimal point suppressed. The Magnetic/True indicator field indicates True (T) or Magnetic (M) courses. Used On: Cruising Table records. Length: 4 characters. Character Type: Numeric. Examples: 0000, 1790, 3590.

## 5.136 Cruise Level From/To

The Cruise Level From field indicates the lowest cruising level, and the Cruise Level To field the highest cruising level, prescribed for use within the Course From/To fields. Cruise Levels are derived from official government sources. Levels entered in feet are all numeric; levels entered in meters have alpha character M in the first column followed by all numeric; if the Level To is unlimited, the field contains the alpha characters UNLTD. Used On: Cruising Table records. Length: 5 characters. Character Type: Alpha/numeric. Examples: 0200, M0600, M1585.

## 5.137 Vertical Separation

The Vertical Separation field indicates the minimum separation prescribed to be maintained between the cruising levels. Vertical Separation Values are derived from official government sources and entered in feet or tens of meters with M in the first column. Used On: Cruising Table records. Length: 5 characters. Character Type: Alpha/numeric. Examples: 01000, 02000, M0030, M0060.

## 5.138 Time Indicator (TIME IND)

The Time Indicator field indicates whether the times shown in the Time of Operations field(s) are Local Time, Daylight Savings Time or Universal Coordinated Time. Time in the affected record(s) is derived from official government sources and qualified as follows: T Times codes are Local Time, S Times codes are to be adjusted for Daylight Savings Time, Blank Times shown are Universal Coordinated Time (UTC). Used On: Controlled Airspace, Restrictive Airspace Continuation, Referred Route Continuation, Enroute Airway Restriction, Airport and Heliport Communication Continuation, and Enroute Communications Continuation Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                              |
|-----------------|----------------------------------------------------------|
| T               | Times codes are Local Time                               |
| S               | Times codes are to be adjusted for Daylight Savings Time |
| Blank           | Times shown are Universal Coordinated Time (UTC)         |

## 5.140 Controlling Agency

Some Restrictive Airspace areas are designated joint use, and IFR operations in the area may be authorized by the controlling agency when it is not being utilized by the using agency. The name of the Controlling Agency is derived from official government sources and shown on the first record only; if no Controlling Agency is specified, the field may be blank. Used On: Controlled Airspace, Restrictive Airspace Continuation record. Length: 25 characters. Character Type: Alpha/numeric. Examples: LAX, ARTCC, Lumpur ACC, Butterworth APP.

## 5.141 Starting Latitude

The Grid MORA Table contains records describing the MORA for each Latitude and Longitude block; each record contains thirty blocks, and the Starting Latitude field defines the lower left corner for the first block of each record. The Starting Latitude is determined when the record is assembled. Used On: Grid Mora record. Length: 3 characters. Character Type: Alpha/numeric. Examples: N00, N42, S20, S90.

## 5.142 Starting Longitude

The Grid MORA table contains records describing the MORA for each Latitude and Longitude block; each record contains thirty blocks, and the Starting Longitude field defines the lower left corner for the first block of each record. The Starting Longitude is determined when the record is assembled. Used On: Grid Mora records. Length: 4 characters. Character Type: Alpha/numeric. Examples: E000, W150, E090, W180.

## 5.143 Grid MORA

Grid MORA (Minimum Off-route Altitude) provides terrain and obstruction clearance within the section outlined by latitude and longitude blocks provided in the Starting Latitude and Starting Longitude fields. Grid MORA values clear all terrain and obstructions by 1000 feet in areas where the highest elevations are 5000 feet MSL or lower, and by 2000 feet where the highest elevations are 5001 feet MSL or higher. The field contains values expressed in hundreds of feet (e.g., 6000 feet is expressed as 060, 7100 feet as 071); for geographical sections that are not surveyed, the field contains the alpha characters UNK for Unknown. Per Commentary (5.143-x89), MORA values are generally not provided in government source and are calculated by the data supplier using the Source/Content formula, though some governments do provide off-route altitude data that a supplier may elect to use. Used On: Grid MORA Records. Length: 3 characters. Character Type: Alpha/numeric. Examples: 010, 071, 100, 123, UNK.

## 5.144 Center Fix (CENTER FIX)

When used on Airport and Heliport MSA Records, Center Fix represents the MSA Center — the point on which the MSA is predicated. On Terminal Procedure Records it has three uses: when the procedure has an MSA defined, it contains the identifier of the fix on which the MSA is predicated, pointing to the specific MSA Record (for Approach Procedures, populated on the first leg of the final approach coding, or on the first leg of each transition if the government source MSA is 'by transition'; for SIDs and STARs, populated on the first leg of each transition to which it applies); when the procedure has a TAA defined, it contains the identifier of the fix on which the TAA Sector is predicated, pointing to the specific TAA Record, populated on the first record for each approach transition; when used in a record defined by an RF Path Terminator, it contains the fix defining the center of the constant radius arc. As MSA Center, the field contains the identification of the navigation facility, Enroute Waypoint, Terminal Waypoint, Runway, Airport Reference Point or Heliport Reference Point on which the MSA coverage radius is predicated, derived from official government sources. As TAA IAF Waypoint, it contains the official identifier of the waypoint for which the TAA Sector is defined. As Radius Center, it contains the identification of the navigation facility, Enroute Waypoint, or Terminal Waypoint used to define the center point of the RF turn. Used On: Airport and Heliport MSA Records, Airport and Heliport TAA Records, Airport and Heliport SID/STAR Approach Procedure Records. Length: 5 characters max. Character Type: Alpha/numeric. Table 5-24 shows a sample GRID MORA table (N00/E000 to N14/E029, blocked at sixty-minute intervals); the Start Lat/Long values are the lower-left corner of a one-degree Lat/Long box. The text was revised to allow RF center fixes.

| SEC CODE   | SUB CODE   | START LAT   | START LONG   | MORA   |   MORA |   MORA |   MORA |   MORA |   MORA | MORA   | MORA   |
|------------|------------|-------------|--------------|--------|--------|--------|--------|--------|--------|--------|--------|
| A          | S          | N00         | E000         | 010    |    010 |    010 |    010 |    010 |    010 | 090    | 191    |
| A          | S          | N01         | E000         | 010    |    010 |    010 |    010 |    010 |    010 | 010    | 082    |
| A          | S          | N02         | E000         | 010    |    010 |    010 |    010 |    010 |    010 | 010    | 073    |
| A          | S          | N03         | E000         | 010    |    010 |    010 |    010 |    010 |    010 | 010    | 073    |
| A          | S          | N04         | E000         | 010    |    010 |    010 |    010 |    010 |    015 | UNK    | 049    |
| A          | S          | N05         | E000         | 026    |    014 |    010 |    010 |    014 |    020 | UNK    | 042    |
| A          | S          | N06         | E000         | 049    |    024 |    020 |    019 |    026 |    029 | 029    | 042    |
| A          | S          | N07         | E000         | UNK    |    040 |    033 |    031 |    038 |    043 | 035    | 040    |
| A          | S          | N08         | E000         | 041    |    037 |    033 |    035 |    035 |    034 | 035    | UNK    |
| A          | S          | N09         | E000         | 029    |    045 |    030 |    035 |    027 |    032 | 033    | UNK    |
| A          | S          | N10         | E000         | 030    |    034 |    029 |    028 |    028 |    032 | 043    | UNK    |
| A          | S          | N11         | E000         | 030    |    034 |    031 |    032 |    025 |    041 | 046    | UNK    |
| A          | S          | N12         | E000         | 026    |    029 |    029 |    022 |    024 |    028 | 043    | UNK    |
| A          | S          | N13         | E000         | 026    |    030 |    030 |    030 |    026 |    026 | 030    | UNK    |
| A          | S          | N14         | E000         | 031    |    031 |    024 |    030 |    023 |    040 | 034    | UNK    |

## 5.145 Radius Limit

The altitude in the Sector Altitude field provides 1000-foot obstacle clearance within a specified radius from the navigational facility/fix; the Radius Limit field lets that radius be specified. Radius limits are derived from official government sources and shown in whole nautical miles. Used On: Airport and Heliport MSA Records. Length: 2 characters. Character Type: Numeric. Examples: 25, 30.

## 5.146 Sector Bearing (SEC BRG)

On MSA Records, Sector Bearing (SEC BRG) contains beginning and ending bearing values, referenced to the MSA Center, for each MSA sector. On TAA records, it contains the beginning and ending bearings defining a TAA Area, referenced to the Sector Bearing Reference Waypoint. Derived from official government source; each field is made up of the start-of-sector and end-of-sector bearing, in whole degrees — the first three digits are the start, the last three the end. For MSA, values are sector-dividing values and the end value of one sector is the start value of the next. For TAA, values are inclusive. Multiple Sector Bearings in the same MSA or TAA record are provided starting with the lowest numbered values, in clockwise order. For MSA with multiple radii and sector altitudes for the same sector, the Sector Bearings repeat with the additional radius/altitude data before the next sector. For an un-sectorized circle MSA, both start and end sector bearing values are set to 180. Values may be magnetic or true, as indicated by the Mag/True Indicator in the MSA or TAA. See Figure 5-7. Used On: Airport and Heliport MSA and TAA Primary Records. Length: 6 characters. Character Type: Numeric. Examples: 060140 (sector from 060° clockwise to 140°); 140060 (sector from 140° clockwise to 060°); 180180 (full circle MSA, no sectorization).

## 5.147 Sector Altitude (SEC ALT)

On MSA records, Sector Altitude (SEC ALT) provides 1000-foot obstacle clearance within the specified sector. On TAA records, the Sector Minimum Altitude is the minimum altitude for that sector, providing obstacle clearance compatible with the associated instrument procedures, generally 1000 feet or more in mountainous areas; flight crews are expected to fly direct to the initial approach fix at the appropriate sector altitude unless otherwise instructed by ATC. Values are derived from official government source, given in hundreds of feet; where no Sector Altitude is provided for a sector, the value is 999. See Figure 5-7. Used On: Airport and Heliport MSA Records and TAA Primary Records. Length: 3 characters. Character Type: Numeric. Examples: 010 = 1000ft, 025 = 2500ft, 100 = 10,000ft, 999 = no sector altitude. Figure 5-7 gives sample output strings for un-sectorized MSA (e.g. 18018003125: Sector Bearings 180180, Sector Altitude 031, Sector Radius 25), sectorized MSA with single radius, sectorized MSA with multiple radius, and no-data sectors. Note 1: one example needs 11 Bearing/Altitude/Radius data sets, but the MSA Primary Record allows only 7; additional sets go in a continuation record formatted the same as the Primary.

## 5.148 Enroute Alternate Airport/Heliport (EAA)

The Enroute Alternate Airport/Heliport (EAA) field identifies the most suitable emergency airport or heliport along a Company Route or Helicopter Operations Company Route. It is determined by the user airline and contains the Airport or Heliport Ident. Used On: Company Route, Helicopter Operations Company Route records. Length: 4 characters. Character Type: Alpha/numeric. Examples: KDEN, EGKK, EDFF.

## 5.149 Figure of Merit (MERIT)

The Figure of Merit (MERIT) field denotes cases where a VHF Navaid is usable beyond the range specified in the Class field, cases where a VHF Navaid in the database is not available for operational use (out of service), and cases where a VHF Navaid is not included in a civilian international NOTAM system. Field entry values are not in official government source but are derived values based on usage, class, availability, etc., possibly adjusted by actual user input; when the field matches the VHF Navaid Class field (Section 5.35), no usable range beyond the Class specification has been reported. Used On: VHF Navaid Records. Length: 1 character. Character Type: Numeric. Content codes: 0 = Terminal Use (~25NM), 1 = Low Altitude Use (~40NM), 2 = High Altitude Use (~130NM), 3 = Extended High-Altitude Use (beyond 130NM), 7 = Navaid not in civil international NOTAM system, 9 = Navaid Out of Service.

|   Field Content | Description                                               |
|-----------------|-----------------------------------------------------------|
|               0 | Terminal Use (generally within 25NM)                      |
|               1 | Low Altitude Use (generally within 40NM)                  |
|               2 | High Altitude Use (generally within 130NM)                |
|               3 | Extended High-Altitude Use (generally beyond 130NM)       |
|               7 | Navaid not included in a civil international NOTAM system |
|               9 | Navaid Out of Service                                     |

## 5.150 Frequency Protection Distance (FREQ PRD)

The Frequency Protection Distance (FREQ PRD) field indicates the distance to the next nearest NAVAID on the same frequency. The distance is computer generated, entered only for NAVAID with DME or TACAN equipped facilities, indicating the distance in nautical miles to the next nearest DME or TACAN equipped facility; maximum relevant value is 600 nautical miles. Used On: VHF Navaid records. Length: 3 characters. Character Type: Alpha/numeric. Examples: 030, 150, 600.

## 5.151 FIR/UIR Address (ADDRESS)

The FIR/UIR Address (ADDRESS) field contains the four-character communications address of the FIR/UIR, supplementing the FIR/UIR Ident. Per ICAO Document 8585 (three-letter designators for Aircraft Operating Agencies, Aeronautical Authorities and Services) and ICAO Document 7910 (Location Indicators, Address of Centers in charge of FIR/UIR), messages to the ATS Center in charge of a FIR/UIR add a suffix designator: ZQZX for IFR-related messages, ZFZX for VFR-related messages. Unless otherwise stipulated by the user, this field uses ZOZX for an Oceanic FIR/UIR and ZRZX for all other FIR/UIRs. On Enroute Communications Records, this content definition applies whenever the FIR/RDO field (Section 5.190) contains an Information Region Identifier; otherwise the Address field is blank. Used On: FIR/UIR and Enroute Communications records. Length: 4 characters. Character Type: Alpha. Examples: ZOZX, ZRZX.

## 5.152 Start/End Indicator (S/E IND)

This section (Start/End Indicator, S/E IND) was deleted by Supplement 21.

## 5.153 Start/End Date

This section (Start/End Date) was deleted by Supplement 21.

## 5.154 Restriction Identifier (REST IDENT)

The Restriction Identifier (REST IDENT) assigns a unique identifier to a restriction record and to multiple restriction records for a particular route or route segment. Identifiers are assigned during data file assembly, initially in sequence (001, 002, 003, ...). If a restriction record is removed, only that record is deleted and other identifiers for that airway are unaffected — e.g. if 002 is deleted, 001 and 003 retain their identifiers. A new restriction added within a few cycles of a deletion uses the next higher number even if gaps exist in the sequence. Used On: Airway Restriction and Airway Restriction Continuation records. Length: 3 characters. Character Type: Numeric. Examples: 001, 002, 003. (Sections 5.155 and 5.156 are Intentionally Left Blank.)

## 5.157 Airway Restriction Start/End Date (START/END DATE)

The Airway Restriction Start Date indicates the earliest GMT date the restriction takes effect; the End Date indicates the latest GMT date it remains in effect. This may be supplemented by Time of Operation information in an Airway Restriction Record, Type AE or TC; when no AE or TC record exists for the Restriction Identifier, start time is 0000 GMT and end time is 2359 GMT of the indicated dates. Start and end dates are entered in format DDMMMYY; a blank YY means the restriction is valid every year; a blank start date means immediate effect; a blank end date means valid until further notice. Used On: Enroute Airway Restriction records. Length: 7 characters. Character Type: Alpha/numeric. Examples: 15JAN92, 15JAN(blank). (Sections 5.158 and 5.159 are Intentionally Left Blank.)

## 5.160 Units of Altitude (UNIT IND)

The Units of Altitude (UNIT IND) field indicates the unit of measurement for the Restriction Altitude fields. Values are derived from official government sources. Used On: Airway Restriction records and Airway Restriction Continuation Records. Length: 1 character. Character Type: Alpha. Codes: F = Restriction Altitudes in hundreds of feet, K = metric Flight Levels, L = feet Flight Levels, M = tens of meters.

| Field Content   | Description                                                 |
|-----------------|-------------------------------------------------------------|
| F               | Restriction Altitudes are expressed in hundreds of feet     |
| K               | Restriction Altitudes are expressed in metric Flight Levels |
| L               | Restriction Altitudes are expressed in feet Flight Levels   |
| M               | Restriction Altitudes are expressed in tens of meters       |

## 5.161 Restriction Altitude (RSTR ALT)

The Restriction Altitude (RSTR ALT) fields specify the altitude profile for a specific restriction. Altitudes are derived from official government sources, entered in hundreds of feet, tens of meters, or standard/metric Flight Levels as determined by the Units of Altitude field, and expressed in ascending order; all altitude fields after a blank altitude are also blank. Used On: Airway Restriction, Airway Restriction Continuation records. Length: 3 characters. Character Type: Numeric. Examples: 310 (standard FL310 or metric FL3199m or 31000 feet or 3100 meters), 090 (standard FL90 or metric FL900m or 9000 feet or 900 meters).

## 5.162 Step Climb Indicator (STEP)

The Step Climb Indicator (STEP) field indicates whether step climb up or down is permitted. Used On: Airway Restriction and Airway Restriction Continuation records. Length: 1 character. Character Type: Alpha. Codes: B = step climb up or down permitted, D = only step climb down permitted, N = no step climb permitted, U = only step climb up permitted.

| Field Content   | Description                        |
|-----------------|------------------------------------|
| B               | Step climb up or down is permitted |
| D               | Only step climb down is permitted  |
| N               | No step climb is permitted         |
| U               | Only step climb up is permitted    |

## 5.163 Restriction Notes

The Restriction Notes field may contain any restriction not otherwise covered by the altitude or time restriction. Notes are derived from official government sources. Used On: Airway Restriction continuation records. Length: 104 characters. Character Type: Alpha/numeric. Example: 'AVAILABLE FOR WESTBOUND DEPARTURES FROM GATWICK. EASTBOUND AND OVER-FLIGHTS BY ATC ONLY. REROUTING MUST BE EXPECTED MON-FRI 1800-2400 DUE TO MILITARY TRAFFIC.'

## 5.164 EU Indicator (EU IND)

The EU Indicator (EU IND) field identifies Enroute Airway records that have an Airway Restriction record, without identifying the restriction itself. The field contains alpha character Y when a restriction for the segment exists in the restriction file, or is blank when no restriction record exists. Used On: Enroute Airways records. Length: 1 character. Character Type: Alpha.

## 5.165 Magnetic/True Indicator (M/T IND)

This field has multiple definitions. For Airport and Heliport Primary Records, it indicates whether all bearing and course detail for that airport/heliport reference Magnetic North or True North; it is blank when the database mixes magnetic and true bearing/course information for the airport. It is also used to indicate whether the Course From and Course To fields of the Cruise Table record, and the Sector Bearing fields of the MSA and TAA record, are magnetic or true. In Airport/Heliport Records, the field contains M if all bearing and course detail is magnetic, or T if all is true; setting an airport/heliport to T does not mean courses and bearings need not be coded as true — true coding must still comply with the true-coding rules elsewhere; the field is blank for mixed magnetic/true data. Cruise Table Courses and MSA/TAA Sector Bearings are derived from official government source and use M for magnetic or T for true. Used On: Airport, Heliport, Cruise Table and Airport and Heliport MSA Records, and Airport and Heliport TAA Record. Length: 1 character. Character Type: Alpha.

## 5.166 Channel

The Channel field specifies the channel of the Azimuth, Elevation and Data transmissions for the MLS identified in the record's MLS Identifier field. Channels are derived from official government sources and range from 500 to 699. Used On: MLS records. Length: 3 characters. Character Type: Numeric.

## 5.167 MLS Azimuth Bearing (MLS AZ BRG) MLS Back Azimuth Bearing (MLS BAZ BRG)

The MLS Azimuth Bearing (MLS AZ BRG) and MLS Back Azimuth Bearing (MLS BAZ BRG) fields define the inbound magnetic final approach course assigned to the center of the Azimuth or Back Azimuth Coverage (see Section 5.172). Values derive from official government source documents, generally the inbound course for the approach procedure considered the primary use of the MLS facility, given in degrees and tenths of degrees with the decimal point suppressed. If the source value is intended for true-only use, the last character holds T in place of the tenths-of-a-degree value. Used On: MLS and MLS Continuation records. Length: 4 characters. Character Type: Numeric. Examples: 0550, 0155, 015T.

## 5.168 Azimuth Proportional Angle Right/Left (AZ PRO RIGHT/LEFT) Back Azimuth Proportional Angle Right/Left (BAZ PRO RIGHT/LEFT)

The MLS Azimuth and Back Azimuth Proportional Angle fields (AZ PRO RIGHT/LEFT, BAZ PRO RIGHT/LEFT) define the limits of proportional guidance of the azimuth transmitter signal on the right and left side of the MLS Azimuth bearing (Section 5.167). The BAZ is identical to the AZ and provides guidance for Missed Approach Procedures and departures; see the figure under Section 5.172. Values are derived from official government publications, entered in whole degrees. Used On: MLS and MLS Continuation records. Length: 3 characters. Character Type: Numeric. Examples: 040, 025, 015.

## 5.169 Elevation Angle Span (EL ANGLE SPAN)

The Elevation Angle Span (EL ANGLE SPAN) field defines the scan of the elevation transmitter signal between the lower and upper limits. Limits are derived from official government publications, entered in degrees and tenths of degrees with the decimal point suppressed. Used On: MLS records. Length: 3 characters. Character Type: Numeric. Examples: 300, 150.

## 5.170 Decision Height (DH)

This section (Decision Height, DH) was deleted by Supplement 20.

## 5.171 Minimum Descent Height (MDH)

This section (Minimum Descent Height, MDH) was deleted by Supplement 20.

## 5.172 Azimuth Coverage Sector Right/Left (AZ COV RIGHT/LEFT) Back Azimuth Coverage Sector Right/Left (BAZ COV RIGHT/LEFT)

The Azimuth Coverage Sector fields (AZ COV RIGHT/LEFT, BAZ COV RIGHT/LEFT) define the limit of the azimuth transmitter signal on the right and left side of the MLS Bearing (Section 5.167). The Back-Azimuth Coverage Sector is identical to the Azimuth Coverage Sector and provides guidance for Missed Approach Procedures and departures. Values are derived from official government publications, entered in whole degrees. Used On: MLS and MLS Continuation records. Length: 3 characters. Character Type: Numeric. Examples: 040, 062, 110. Commentary (5.172-x90): the Azimuth Coverage Sector includes the Proportional Guidance Sector and the Clearance Guidance Sector, as illustrated in the referenced figure.

## 5.173 Nominal Elevation Angle (NOM ELEV ANGLE)

The Nominal Elevation Angle (NOM ELEV ANGLE) field defines the normal glide path angle for the MLS installation. Glide path angles from official government sources are entered in tens of degrees, tenths of a degree, and hundredths of a degree, with the decimal point suppressed. Used On: MLS records. Length: 4 characters. Character Type: Numeric. Examples: 1000, 0275.

## 5.174 Restrictive Airspace Link Continuation (LC)

The Restrictive Airspace Link Continuation (LC) field indicates cases where not all Enroute Airway to Restrictive Airspace Links can be stored in the Flight Planning Continuation Record defined in 4.6.3 (more than four area links required). When an additional Continuation Record (per Section 4.1.6.4) is needed to provide further links, this field contains alpha character Y to indicate that status. Used On: Enroute Airway Flight Planning Continuation records. Length: 1 character. Character Type: Alpha.

## 5.175 Holding Speed (HOLD SPEED)

The Holding Speed (HOLD SPEED) field is the maximum speed in a holding pattern. The speed limit is derived from official government sources; if different from the ICAO rules limit, it is shown in knots, else the field is blank. Used On: Holding Pattern record. Length: 3 characters. Character Type: Numeric. Examples: 250, 015.

## 5.176 Pad Dimensions

The Pad Dimensions field defines the landing surface dimensions of a helicopter landing pad, described as a runway, a rectangle, or a circle. Dimensions are derived from official government sources, entered in feet with one-foot resolution. For a rectangular pad, the first five digits define one side and the last three digits the other side (e.g. 00060120 = 60 feet by 120 feet). For a circular pad, the first five digits define the diameter and the last three digits are zeros (e.g. 00080000 = 80-foot diameter). For a runway-shaped pad, the first five digits define the length and the last three digits the width (e.g. 12500120 = 12500 feet long, 120 feet wide). Used On: Airport Helipad Records, Heliport Helipad Records. Length: 8 characters. Character Type: Numeric. Examples: 00060060, 10220150, 00040040, 00080000.

## 5.177 Public/Military Indicator (PUB/MIL)

Airports are classified into four categories by use: open to the general public, military, joint civil and military use, and closed to the public. This field categorizes airports by that use. Data is obtained from official government sources and use is defined in civil and/or military publications. Used On: Airport and Heliport records. Length: 1 character. Character Type: Alpha. Codes: C = open to the public (civil), M = military airport, P = not open to the public (private), J = joint Civil and Military.

| Field Content   | Description                                          |
|-----------------|------------------------------------------------------|
| C               | Airport/Heliport is open to the public (civil)       |
| M               | Airport/Heliport is military airport                 |
| P               | Airport/Heliport is not open to the public (private) |
| J               | Airport is joint Civil and Military                  |

## 5.178 Time Zone

The standard time zone system divides the world into 24 zones of 15 degrees longitude each. The zero-time zone is centered on the Greenwich meridian, between 7 degrees 30 minutes West and 7 degrees 30 minutes East, with no difference from Greenwich Mean Time. Time zones are designated by a letter of the alphabet and a number indicating the difference from Greenwich time. Time zones are derived from official Time Zone Charts of the World, or published per country. The first character of the field indicates the time zone observed by the airport, per the table below. The second and third characters indicate, in minutes, the adjustment from the hour that the airport/heliport observed time requires. When the 1st character is 1 or 2, the 2nd and 3rd characters are always blank. Used On: Airport and Heliport records. Length: 3 characters. Character Type: Alpha/numeric. Example: India falls in zones E (-5) and F (-6), but observes E30 (-5 hours 30 minutes) throughout. For a country in the M or Y time zone observing a time equal to the next greater time zone, the 1-hour adjustment is indicated by 60 in the second and third positions.

| Field Cont   |   Diff to Zulu time | Lat/long Boundaries   | Field Cont   |   Diff to Zulu time | Lat/Long Boundaries   |
|--------------|---------------------|-----------------------|--------------|---------------------|-----------------------|
| Z            |                   0 | W007 30/E007 30       |              |                     |                       |
| A            |                  -1 | E007 30/E022 30       | N            |                  +1 | W007 30/W022 30       |
| B            |                  -2 | E022 30/E037 30       | O            |                  +2 | W022 30/W037 30       |
| C            |                  -3 | E037 30/E052 30       | P            |                  +3 | W037 30/W052 30       |
| D            |                  -4 | E052 30/E067 30       | Q            |                  +4 | W052 30/W067 30       |
| E            |                  -5 | E067 30/E082 30       | R            |                  +5 | W067 30/W082 30       |
| F            |                  -6 | E082 30/E097 30       | S            |                  +6 | W082 30/W097 30       |
| G            |                  -7 | E097 30/E112 30       | T            |                  +7 | W097 30/W112 30       |
| H            |                  -8 | E112 30/E127 30       | U            |                  +8 | W112 30/W127 30       |
| I            |                  -9 | E127 30/E142 30       | V            |                  +9 | W127 30/W142 30       |
| K            |                 -10 | E142 30/E157 30       | W            |                 +10 | W142 30/W157 30       |
| L            |                 -11 | E157 30/E172 30       | X            |                 +11 | W157 30/W172 30       |
| M            |                 -12 | E172 30/180 00        | Y            |                 +12 | W172 30/180 00        |
| 1            |                 -13 | Phoenix Island Tonga  |              |                     |                       |
| 2            |                 -14 | Kiribati Line Island  |              |                     |                       |

## 5.179 Daylight Time Indicator (DAY TIME)

The Daylight Time Indicator (DAY TIME) field indicates whether the airport observes Daylight or Summer time when such changes apply for its country or state. This is obtained from official publications: the field contains Y if the airport observes Daylight/Summer time, and N if it does not or if unknown. Used On: Airport and Heliport records. Length: 1 character. Character Type: Alpha.

## 5.180 Pad Identifier (PAD IDENT)

The Pad Identifier (PAD IDENT) field identifies the helipad described in heliport helipad records, or the pad served by ILS/MLS described in Airport and Heliport ILS/MLS records. Identifiers are derived from official government publications when available; otherwise, the data supplier assigns unique identifiers. Used On: Airport and Heliport Localizer and Glideslope Records, Localizer Marker Primary Records, GLS Primary Records, GBAS Path Point Primary Records, Helipad Records, Helicopter Operations Company Routes, and MLS Records. Length: 5 characters max. Character Type: Alpha/numeric. Examples: Source Supplied - PADA1, NWPAD, ALPHA, A1; Data Supplier - HELO1, HELO2, HELO3.

## 5.181 H24 Indicator (H24)

The H24 Indicator field indicates whether a communications service frequency is available continually (24 hours a day, seven days a week). Hours of operation are derived from official government publications: the field contains Y if continually available, N if not continually available (with other Times of Operation provided), or U if unknown. If set to Y, the Time Code (5.131) in the Primary Extension Continuation Record for the frequency is set to C or H. If set to N, the Time Code is set to N or P. If set to U, the Time Code is also set to U. Used On: Enroute/Airport and Heliport Communications records. Length: 1 character. Character Type: Alpha.

## 5.182 Guard/Transmit (G/T)

This section is withdrawn. The status of transmit-only, receive-only, or both for a given frequency is now provided by the transmit and receive frequency columns of the communications records.

## 5.183 Sectorization (SECTOR)

The Sectorization (SECTOR) field defines the airspace sector a communication frequency applies to when an airport defines sectors by bearing from a common point. Derived from official government publications, each Sectorization contains two whole-degree bearings: the first three characters are the beginning bearing and the last three are the ending bearing, moving clockwise from start to end. A complete circle is coded 180180; its radius is given by Communications Distance (Section 5.188). Sectors defined by cardinal directions may be translated to bearings using the accompanying four- and eight-compass-point tables. If sectors are not defined by bearings or cardinal directions, sectorization is shown in narrative form in an Airport Communications Continuation Record. Sector bearing data relates to the lat/long of the Sector Facility (5.185); if none is provided, it relates to the lat/long in the same communications record. Used On: Airport Communication records. Length: 6 characters. Character Type: Alpha/numeric. Examples: 010189, 190009.

| Source Cardinal Direction       | ARINC 424 Sectorization         |
|---------------------------------|---------------------------------|
| Source Used Four Compass Points | Source Used Four Compass Points |
| North                           | 316045                          |
| East                            | 046135                          |
| South                           | 136225                          |
| West                            | 226315                          |

| Source Used Eight Compass Points   |   Source Used Eight Compass Points |
|------------------------------------|------------------------------------|
| North                              |                             341025 |
| North East                         |                             026070 |
| East                               |                             071115 |
| South East                         |                             116160 |
| South                              |                             161205 |
| South West                         |                             206250 |
| West                               |                             251295 |
| North West                         |                             296340 |

## 5.184 Communication Altitude (COMM ALTITUDE)

The Communications Altitude 1 and Altitude 2 fields provide information on use of communications frequencies with reference to specific altitudes; if the record also includes Sectorization data (5.183), the altitude data is valid only for that sector. Derived from official government documentation and processed with the Communications Altitude Description field, the field contains altitude expressed in hundreds of feet. Altitude 1 contains a value when the Description contains + or -. Altitude 1 may contain a value when the Description is blank, indicating use at a specific altitude only. Both Altitude 1 and Altitude 2 contain values when the Description contains B. Used On: Enroute, Airport, and Heliport Primary Communications Records. Length: 3 characters. Character Type: Alpha/numeric. Examples: 050 (5000 feet), 245 (24500 feet).

## 5.185 Sector Facility (SEC FAC)

The Sector Facility (SEC FAC) field defines the Navaid or Airport upon which the Sectorization (5.183) field information is based. Derived from official government sources, the field contains the official Navaid or Airport identifier. Used On: Airport and Heliport Communications Records. Length: 4 characters. Character Type: Alpha/numeric. Examples: IOC, COS, DEN, KJFK.

## 5.186 Sectorization Narrative

The Sectorization Narrative field defines communications sectors of operation in narrative form when they cannot be formatted in the Sectorization (5.183) field, and may also qualify the Sectorization information (e.g., an 'and' condition alongside a coded sector, such as 309127 plus "When Departing Runway 31L/R"). Derived from official government sources. Used On: Airport and Heliport Sector Narrative Continuation Records. Length: 60 characters. Character Type: Alpha/numeric. Examples: North Complex, Departures to North, When Rwy 09/27 is Active.

## 5.187 Distance Description (DIST DESC)

The Distance Description (DIST DESC) field designates whether a communications frequency in the Airport Communications Record is used from the facility out to a specified distance, or from a specified distance and beyond. In the VHF Navaid Limitation and TACAN-Only Navaid Limitation Continuation Records, it defines whether the limitation applies from the navaid out to a specified distance or beyond it. The field contains - when used/applies out to a specified distance, + when used/applies beyond a specified distance, and is blank when no restriction applies. Used On: Airport Communications Records, VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 1 character. Character Type: Alpha.

## 5.188 Communications Distance (COMM DIST)

The Communications Distance (COMM DIST) field defines the distance restriction within which or beyond which a communication frequency is used, applied together with the Distance Description field. Derived from official government publications, it contains a value in nautical miles from the communications facility. If Distance Description is -, the frequency is used from the facility to the specified distance; if +, it is used from the specified distance and beyond. The field is blank if no restrictions apply. Used On: Airport Communications records. Length: 2 characters. Character Type: Numeric. Examples: 05, 10, 15.

## 5.189 Position Narrative

The Position Narrative field is a textual description of the location of a communications transmitter, which may be the name of a Remote Communications Outlet, a Remote Communications Air/Ground Station, or the place name of the transmitter site's geographical location. Derived from official government source; the field may be blank if source information is unavailable. Used On: Enroute Communications records. Length: 25 characters. Character Type: Alpha/numeric. Examples: CHEYENNE, ABBEVILLE.

## 5.190 FIR/RDO Identifier (FIR/RDO)

The FIR/RDO Identifier field on Enroute Communications records is the source-provided identifier for a communications service as used in message addressing. For Flight Information/Upper Information Regions (FIR/UIR), it is the four-character identifier assigned per ICAO Document 7910, Location Indicators. For Flight Service Stations, it is the three- or four-character identifier assigned by the relevant authority. For other enroute communications services not addressable under the FIR/UIR or Flight Service Station concept, it is the identifier assigned by the relevant authority for message addressing. Derived from official government source documentation; only three- or four-character identifiers are used. Used On: Enroute Communications records. Length: 4 characters. Character Type: Alpha/numeric. Examples: KZDN, DEN.

## 5.191 Triad Stations (TRIAD STA)

Deleted by Supplement 14.

## 5.192 Group Repetition Interval (GRI)

Deleted by Supplement 14.

## 5.193 Additional Secondary Phase Factor (ASF)

Deleted by Supplement 14.

## 5.194 Initial/Terminus Airport/Fix

The Initial Fix and Terminus Fix fields define the departure airport or initial fix and the destination airport or terminus fix of a preferred route. For preferred and preferential routes, these fields normally contain an airport identifier. For North America Routes for North Atlantic Traffic Common portion routes, they may contain NAVAID or waypoint identifiers. For Non-common portion routes, they may contain airport, NAVAID, or waypoint identifiers. These fields are entered only on the first sequence of a route, except when the route serves more than one airport, in which case additional airports appear on succeeding sequences. Used On: Preferred Route record. Length: 5 characters. Character Type: Alpha/numeric. Examples: KDEN, CYUL, DEN, YUL, COLOR; sample sequences given for routes between Metro Area New York and Atlanta (KJFK/KLGA/KEWR via K6/K7 to/from KATL).

## 5.195 Time of Operation

The Time of Operation field indicates the operating times of a Facility or Restriction, derived from official government source. Each group defines a daily operating period within a calendar week. The first two positions identify days of the week (Monday=1 through Sunday=7); a single day like Monday is 01, and a consecutive range like Monday-Friday is 15, with non-consecutive days requiring multiple entries. The remaining 8 characters give a starting time and ending time in HHMM 24-hour format, e.g., 00012350 (one minute after midnight to ten minutes before midnight) or 07152000 (07:15 to 20:00). Times can also use Sunrise (SR) and Sunset (SS): starting/ending exactly at Sunrise is 000R, at Sunset is 000S; offsets before/after Sunrise or Sunset use formats like 030R (30 min before sunrise), R030 (30 min after sunrise), 100R (1 hr before sunrise), R100 (1 hr after sunrise), 030S/S030 and 100S/S100 for sunset equivalents, with the three digits expressing hours then minutes (e.g., 130 = 1h30m). Multiple definitions needed to fully define a calendar week are coded as additional Time of Operation fields. Examples: a restriction valid Mon/Wed/Fri 0700-1700 requires three entries (0107001700, 0307001700, 0507001700); a continuous restriction Monday 0700 through Friday 1700 requires three entries (0107002359, 2400002359 for Tue-Thu, 0500001700 for Friday); times crossing midnight are coded on the actual ending day, e.g., Mon-Fri 1700-0300 (ending Saturday) is shown as 1617000300, not 1517000300. Used On: Enroute Airway Restriction Primary and Continuation Records; Airport/Heliport/Enroute Communications, Restrictive Airspace, Preferred Route, Enroute Airway Restrictions, and Controlled Airspace records. Length: 10 characters. Character Type: Alpha/numeric.

## 5.196 Name Format Indicator (NAME IND)

The Name Format Indicator field describes the format of the Waypoint Name/Description field (5.43), per the Waypoint Naming Conventions in Chapter 7. Values have no official government source and are assigned per the accompanying table (codes not combined between columns): A=Abeam Fix, B=Bearing and Distance Fix, D=Airport Name as Fix, F=FIR Fix, H=Phonetic Letter Name Fix (Note 1), I=Airport Ident as Fix, L=Latitude/Longitude Fix, M=Multiple Word Name Fix, N=Navaid Ident as Fix, P=Published Five-Letter-Name Fix, Q=Published Name Fix less than five letters, R=Published Name Fix more than five letters, T=Airport/Rwy Related Fix (Note 2), U=UIR Fix; Column 97: O=Localizer Marker with officially published five-letter identifier, M=Localizer Marker without one. Note 1: Column 98 is reserved for future expansion. Note 2: T is used with all fixes established per Chapter 7, Section 7.2.6, Terminal Waypoints. Used On: Enroute Waypoints, Airport, and Heliport Terminal Waypoints. Length: 3 characters. Character Type: Alpha.

| Record 96   | Column 97   | Content 98   | Description                                                            |
|-------------|-------------|--------------|------------------------------------------------------------------------|
| A           |             |              | Abeam Fix                                                              |
| B           |             |              | Bearing and Distance Fix                                               |
| D           |             |              | Airport Name as Fix                                                    |
| F           |             |              | FIR Fix                                                                |
| H           |             | Note 1       | Phonetic Letter Name Fix                                               |
| I           |             |              | Airport Ident as Fix                                                   |
| L           |             |              | Latitude/Longitude Fix                                                 |
| M           |             |              | Multiple Word Name Fix                                                 |
| N           |             |              | Navaid Ident as Fix                                                    |
| P           |             |              | Published Five - Letter - Name - Fix                                   |
| Q           |             |              | Published Name Fix, less than five letters                             |
| R           |             |              | Published Name Fix, more than five letters                             |
| T           |             |              | Airport/Rwy Related Fix (Note 2)                                       |
| U           |             |              | UIR Fix                                                                |
|             | O           |              | Localizer Marker with officially published five - letter identifier    |
|             | M           |              | Localizer Marker without officially published five - letter identifier |

## 5.197 Datum Code (DATUM)

The Datum Code (DATUM) field defines the Local Horizontal Reference Datum to which a geographical position (latitude/longitude) is associated. Derived from official government documentation, it contains a three-letter code corresponding to that publication; a listing of valid three-letter codes is in Attachment 2 to this specification. Used On: VHF Navaid, NDB Navaid, Terminal NDB, Enroute Waypoint, Airport, Fan Marker, Heliport, and GLS Transmitter Records. Length: 3 characters. Character Type: Alpha. Examples: AGD, NAS, WGA.

## 5.198 Modulation (MODULN)

The Modulation (MODULN) field designates the type of modulation for the frequency in the Communication Frequency (5.103) field. The field is set to A unless source documentation specifies otherwise; content is A (Amplitude Modulated Frequency) or F (Frequency Modulated Frequency). Used On: Enroute, Airport, and Heliport Communication Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                   |
|-----------------|-------------------------------|
| A               | Amplitude Modulated Frequency |
| F               | Frequency Modulated Frequency |

## 5.199 Signal Emission (SIG EM)

High Frequency (HF) signals used in aeronautical communications may be the complete signal or a portion, called a sideband. The Signal Emission (SIG EM) field designates for each HF Frequency what emission is used. The field is set to 3 unless source documentation specifies otherwise, using codes: 3=Double Sideband (A3), A=Single sideband, reduced carrier (A3A), B=Two Independent sidebands (A3B), H=Single sideband, full carrier (A3H), J=Single sideband, suppressed carrier (A3J), L=Lower (single) sideband, carrier unknown, U=Upper (single) sideband, carrier unknown. The field is blank on records with frequencies that are not HF (see Section 5.104). Used On: Enroute, Airport, and Heliport Communications Records. Length: 1 character. Character Type: Alpha/numeric.

| Field Content   | Description                               |
|-----------------|-------------------------------------------|
| 3               | Double Sideband (A3)                      |
| A               | Single sideband, reduced carrier (A3A)    |
| B               | Two Independent sidebands (A3B)           |
| H               | Single sideband, full carrier (A3H)       |
| J               | Single sideband, suppressed carrier (A3J) |
| L               | Lower (single) sideband, carrier unknown  |
| U               | Upper (single) sideband, carrier unknown  |

## 5.200 Remote Facility (REM FAC)

The Remote Facility (REM FAC) field identifies a Navaid or Airport used to provide the latitude/longitude of a communications transmitter, per Table 5-19 and Notes 7 and 8 in Section 5.37. Derived from official government sources, the field contains the official identifier of the navaid or airport used. Used On: Enroute, Airport and Heliport Communications Records. Length: 4 characters. Character Type: Alpha/numeric.

## 5.201 Restriction Record Type (REST TYPE)

The Restriction Record Type (REST TYPE) field defines what type of restriction is contained in an Enroute Airway Restriction Record, selected from: AE = Altitude Exclusion (altitudes normally available that are excluded for the airway segment, possibly further restricted by Time of Operation); TC = Cruising Table Replacement (references a Cruising Table Identifier that replaces the one in the airway segment records defined by Start Fix/End Fix); SC = Seasonal Restriction (closes an airway or portion on a seasonal basis); NR = Note Restrictions (restrictions not fitting other formatted Restriction Record Types). Used On: Enroute Airway Restriction Records. Length: 2 characters. Character Type: Alpha.

## 5.202 Exclusion Indicator (EXC IND)

The Exclusion Indicator (EXC IND) field indicates how altitudes in the Cruising Table record referenced by the airway segment(s) are restricted, an all-altitude restriction further defined by direction of flight; these codes are not used when certain altitudes remain available in a direction. Codes: A = all altitudes in both directions restricted (closes the airway in both directions); B = all altitudes in the direction opposite to how the Enroute Airway is coded are restricted (closes the airway in that opposite direction); F = all altitudes in the direction in which the Enroute Airway is coded are restricted (closes the airway in that coded direction); (blank) = the restriction is not an all-altitude restriction. Used On: Enroute Airway Restriction Records. Length: 1 character. Character Type: Alpha.

## 5.203 Block Indicator (BLOCK IND)

The Block Indicator (BLOCK IND) field specifies whether the altitudes that follow in a restriction record form a block of restricted altitudes or are individual restricted altitudes. The field is set to B for an altitude block or I for individual altitudes; one, the other, or both codes appear in restriction records that are not Exclusion restrictions (see Section 5.201). Used On: Enroute Airway Restriction, Enroute Airway Restriction Continuation Records. Length: 1 character. Character Type: Alpha. Examples: 030B090 = all altitudes from 3000 to 9000 feet inclusive are not available; 030I090 = individual altitudes of 3000 and 9000 feet are not available; 030I070B130 = individual altitude 3000 feet plus all altitudes from 7000 to 13000 feet inclusive are not available.

## 5.204 ARC Radius (ARC RAD)

The ARC Radius (ARC RAD) field defines the radius of a precision turn: in Terminal Procedures, the Constant Radius To A Fix Path and Termination for an RF Leg; in Holding Patterns, the turning radius inbound to outbound leg for RNP Holding, including RNP holding patterns in SID, STAR, and Approach Records as HA, HF, and HM legs. Derived from official source publications, it is expressed in nautical miles with tenths, hundredths, and thousandths of a nautical mile, decimal point suppressed; the resolution converts to an accuracy of 6 feet. Used On: SID, STAR and Approach Records, Holding Pattern Records. Length: 6 characters. Character Type: Numeric. Examples: 246868, 460820, 691231.

## 5.205 Navaid Limitation Code (NLC)

The Navaid Limitation Codes (NLC) field defines the type of limitation expected with a VHF Navaid, derived from official government publications and coded per the table: C = Coverage (limitations expressed as maximum reception reliability); F = Fluctuations (radials affected by course fluctuations); G = Roughness (signal roughness in defined sectors); N = Unreliable in defined sector(s)/altitude(s)/distance(s); R = Restricted in defined sector(s)/altitude(s)/distance(s); T = Unusable in defined sector(s)/altitude(s)/distance(s); U = Out of Tolerance in defined sector(s)/altitude(s)/distance(s). Used On: VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 1 character. Character Type: Alpha.

| Content   | Limitation Description                                                             |
|-----------|------------------------------------------------------------------------------------|
| C         | Coverage, the limitations are expressed as maximum reception reliability.          |
| F         | Fluctuations, radial(s) are affected by course fluctuations.                       |
| G         | Roughness, signal roughness experienced in the sector(s) defined.                  |
| N         | Unreliable in the sector(s), at the altitude(s), at the distance(s) defined.       |
| R         | Restricted in the sector(s), at the altitude(s), at the distance(s) defined.       |
| T         | Unusable in the sector(s), at the altitude(s), at the distance(s) defined.         |
| U         | Out of Tolerance in the sector(s), at the altitude(s), at the distance(s) defined. |

## 5.206 Component Affected Indicator (COMP AFFTD IND)

The VHF Navaid File contains navaids with one or two components (azimuth and/or distance); published limitations may apply to one or both. The Component Affected Indicator (COMP AFFTD IND) field defines which component(s) are affected, entered per the table from official government publications: A = TACAN or VORTAC, TACAN azimuth only affected; B = VORDME or VORTAC, both azimuth and distance affected; D = VORDME or DME, distance only affected; M = VORTAC or TACAN, TACAN azimuth and distance affected; T = TACAN or VORTAC, distance affected; V = VOR, VORDME, VOR azimuth affected; Z = VORDME, VORTAC or TACAN, VOR and TACAN azimuth and distance affected. When different limitations apply to different components or component pairs, multiple Component Affected Indicators cover the full limitation, with the Sequence Number (5.12) restarting at 01 for each new indicator. Used On: VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 1 character. Character Type: Alpha.

| Content   | Component Description                                                           |
|-----------|---------------------------------------------------------------------------------|
| A         | TACAN or VORTAC, TACAN azimuth component only affected.                         |
| B         | VORDME, or VORTAC, both azimuth and distance component affected.                |
| D         | VORDME or DME, distance component only affected.                                |
| M         | VORTAC or TACAN, TACAN azimuth and distance component affected.                 |
| T         | TACAN or VORTAC, distance component affected.                                   |
| V         | VOR, VORDME or VORDME, VOR azimuth component affected.                          |
| Z         | VORDME, VORTAC or TACAN, VOR and TACAN azimuth and distance component affected. |

## 5.207 Sector From/Sector To (SECTR)

The Sector From/Sector To (SECTR) field defines sectorization applicable to range-limited sectors of VOR/DME, VORTAC, or TACAN facilities, using sector letters from the accompanying table (A through X, each spanning 15 degrees true from 000 to 360). Each sector is described by two characters, interpreted from the first character clockwise to the second character. Field content is derived through interpretation of official government publication information, which may be in a variety of formats. Used On: VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 2 characters. Character Type: Alpha. Examples: AB, TA, LW.

| Sector Character   |   From (degrees true) |   To (degrees true) |
|--------------------|-----------------------|---------------------|
| A                  |                   000 |                 015 |
| B                  |                   015 |                 030 |
| C                  |                   030 |                 045 |
| D                  |                   045 |                 060 |
| E                  |                   060 |                 075 |
| F                  |                   075 |                 090 |
| G                  |                   090 |                 105 |
| H                  |                   105 |                 120 |
| I                  |                   120 |                 135 |
| J                  |                   135 |                 150 |
| K                  |                   150 |                 165 |
| L                  |                   165 |                 180 |
| M                  |                   180 |                 195 |
| N                  |                   195 |                 210 |
| O                  |                   210 |                 225 |
| P                  |                   225 |                 240 |
| Q                  |                   240 |                 255 |
| R                  |                   255 |                 270 |
| S                  |                   270 |                 285 |
| T                  |                   285 |                 300 |
| U                  |                   300 |                 315 |
| V                  |                   315 |                 330 |
| W                  |                   330 |                 345 |
| X                  |                   345 |                 000 |

## 5.208 Distance Limitation (DIST LIMIT)

The Distance Limitation field defines the distance(s) from the navaid at which a limitation applies, derived from official government publications. It contains one or two distances in nautical miles from the facility; used with the Distance Description field to express ranges (see examples). The field is blank if no distances apply. Used On: VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 6 characters. Character Type: Alpha/numeric.

| Distance Description   |   Distance Limit - First Three Digits |   Distance Limit - Second Three Digits | Description of Content                          |
|------------------------|---------------------------------------|----------------------------------------|-------------------------------------------------|
| _                      |                                   040 |                                    000 | Limitation valid out to 40NM from the facility. |
| +                      |                                   040 |                                    000 | Limitation valid beyond 40NM from the facility. |
| B                      |                                   100 |                                    040 | Limitation valid between 40NM and 100NM.        |
| Blank                  |                                   040 |                                    000 | Limitation valid at 40NM from the facility.     |

## 5.209 Altitude Limitation (ALT LIMIT)

The Altitude Limitation field defines the altitude(s) at which a limitation applies, derived from official government publications. It contains one to two altitudes in hundreds of feet MSL; used with the Altitude Description field to express ranges (see examples). The field is blank if no altitudes apply. Used On: VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 6 characters. Character Type: Alpha/numeric.

| Altitude Description   |   Altitude Limit - First Three Digits |   Altitude Limit - Second Three Digits | Description of Content                           |
|------------------------|---------------------------------------|----------------------------------------|--------------------------------------------------|
| -                      |                                   040 |                                    000 | Limitation valid at or below 4000/FL040.         |
| +                      |                                   040 |                                    000 | Limitation valid at or above 4000/FL040.         |
| B                      |                                   100 |                                    040 | Limitation valid from 4000/FL040 to 10000/FL100. |
| blank                  |                                   040 |                                    000 | Limitation valid at 4000/FL040.                  |

## 5.210 Sequence End Indicator (SEQ END)

The Sequence End Indicator field marks the end of a set of sequences defining a limitation for a given VHF Navaid Component or Component pair, derived from official government publications. It contains the character E in the final sequence of a limitation. Used On: VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record. Length: 1 character. Character Type: Alpha.

## 5.211 Required Navigation Performance (RNP)

Required Navigation Performance (RNP) states the navigation performance required for operation within a defined airspace per ICAO Annex 15 and/or State rules. RNP values from official government sources are entered as two digits in nautical miles plus a one-digit zero or negative exponent. On Enroute Airway segments, RNP applies inbound to the fix in increasing sequence order and only to the leg on which it is coded; absence of a value means no database-specified RNP for that segment. On SID, STAR, and Approach Procedure records, RNP applies to the segment on which it is coded, per source; absence indicates no source-supplied RNP for that segment. On Holding Patterns, RNP applies to the holding pattern as defined in the record. Note 1: the RNP concept also applies to defined airspaces; ARINC 424-13 added an airspace record reserving space for RNP pending content definition. Note 2: ARINC 424 currently has no provision for Vertical RNP. Used On: Airport and Heliport SID/STAR/Approach, Enroute Airways, Airport and Heliport SID/STAR/Approach Continuation, Controlled Airspace and Holding Pattern Records. Length: 3 characters (see content paragraph). Character Type: Numeric. Examples: 990 (99.0 NM), 120 (12.0 NM), 013 (0.001 NM), 302 (0.3 NM).

## 5.212 Runway Gradient (RWY GRAD)

The Runway Gradient field gives the overall gradient, in percent, measured from the start of take-off roll to the runway's designated end, expressed as positive (upward) or negative (downward). Values are derived from official government source; the first position is + or - and positions 2-5 give the gradient with the decimal point suppressed, up to a maximum of +9.000 or -9.000. Used On: Runway Records. Length: 5 characters. Character Type: Alpha/numeric. Examples: +0450, -0300.

## 5.213 Controlled Airspace Type (ARSP TYPE)

The Controlled Airspace Type field indicates the type of controlled airspace, derived from official government publications, using the codes in the table below (A, C, M, R, T, Z). For the USA, legacy designations such as TCA are given for reference though no longer officially published. Used On: Controlled Airspace Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                                           |
|-----------------|-----------------------------------------------------------------------|
| A               | Class C Airspace (was ARSA within the USA)                            |
| C               | Control Area, ICAO Designation (CTA)                                  |
| M               | Terminal Control Area, ICAO Designation (TMA or TCA)                  |
| R               | Radar Zone or Radar Area (was TRSA within the USA)                    |
| T               | Class B Airspace (Was TCA with the USA)                               |
| Z               | Class D Airspace within the USA, Control Zone, ICAO Designation (CTR) |

## 5.214 Controlled Airspace Center (ARSP CNTR)

The Controlled Airspace Center field defines the navigation element on which the controlled airspace is predicated, though not necessarily centered; where the airspace is undefined, the Region Identifier is used, and the field then contains the ICAO Identification code for that airspace. The center is determined during record construction — e.g., New York Class B Airspace uses the Kennedy Airport identifier KJFK — and may contain a Navaid, Enroute Waypoint, Heliport, or Airport Identifier. A Region Identifier is derived from official government source or ICAO Document 7910, Location Indicators, when no controlling authority is published and the airspace serves more than one airport. Commentary (5.214-x91): if no suitable published Navaid, Waypoint, Airport, or Region Identifier exists, data suppliers may create a center waypoint for this field. Used On: Controlled Airspace records. Length: 5 characters. Character Type: Alpha/numeric. Examples: OTR, FISHS, KJFK, EGTT.

## 5.215 Controlled Airspace Classification (ARSP CLASS)

The Controlled Airspace Classification field contains an alpha character for the published classification of the controlled airspace, when assigned, derived from official government sources; blank if source provides no classification. Used On: Controlled Airspace records. Length: 1 character. Character Type: Alpha. Examples: B, C, G, Blank.

## 5.216 Controlled Airspace Name (ARSP NAME)

The Controlled Airspace Name field contains the name of the controlled airspace when assigned, derived from official government sources; the name is entered only in the first record and may be blank if source assigns none. Used On: Controlled Airspace records. Length: 30 characters. Character Type: Alpha/numeric. Examples: DENVER CLASS B, OAKLAND OCTA.

## 5.217 Controlled Airspace Indicator (CTLD ARSP IND)

The Controlled Airspace Indicator field indicates whether an airport is associated with terminal-type controlled airspace, such as TMA/TCA, Radar Area, or Class B/C Airspace (USA), determined from official government publications describing lateral limits. The Controlled Airspace Airport/ICAO fields identify the airport for which terminal-controlled airspace is included in the Controlled Airspace Section; this field holds one of the codes in the table below (A, C, M, R, T), or is blank if the airport has no such association. The Controlled Airspace Airport/ICAO may differ from the record airport. Control Zones (CTR), though provided as Controlled Airspace, are not referenced this way in the Airport Flight Planning Continuation Record. Used On: Airport Flight Planning Continuation Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                                            |
|-----------------|------------------------------------------------------------------------|
| A               | The Airport is within or below the lateral limits of Class C Airspace. |
| C               | The Airport is within or below the lateral limits of a CTA.            |
| M               | The Airport is within or below the lateral limits of a TMA or TCA.     |
| R               | The Airport is within or below the lateral limits Radar Zone.          |
| T               | The Airport is within or below the lateral limits of Class B Airspace. |

## 5.218 Geographical Reference Table Identifier (GEO REF TBL ID)

The Geographical Reference Table Identifier gives a unique identification for each Geographical Entity, acting as a pseudo key since the Geographical Entity field is large with no established content. Position One is the first (or other significant) letter of the Geographical Entity; Position Two is a numeric 0-9 for each multiple of that letter. Used On: Geographical Reference Table records. Length: 2 characters. Character Type: Alpha/numeric. Examples: Scandinavia S1, Southern United Kingdom S2, Baleric Islands B0.

## 5.219 Geographical Entity (GEO ENT)

The Geographical Reference Table identifies Geographical Entities not definable by other established encoding systems (see Section 7 for established systems). Content is derived from official government source documentation for preferred route systems of any kind. Used On: Geographical Reference Table Records. Length: 29 characters. Character Type: Alpha/numeric.

## 5.220 Preferred Route Use Indicator (ET IND)

The Preferred Route Use Indicator shows whether a route is point-to-point (usable for navigation) or area-to-area (advisory only, requiring further processing), and whether RNAV equipment is required. Set by the data supplier when the route is established: position one is P (point-to-point) or A (area-to-area); position two is R (RNAV required) or N (RNAV not required). Used On: Preferred Route and Geographical Reference Table Records. Length: 2 characters. Character Type: Alpha.

## 5.221 Aircraft Use Group (ACFT USE GP)

The Aircraft Use Group field indicates what aircraft or aircraft groups are permitted to use a given route, encoded per government source using the codes in the table below (A, C, D, E, F, H, J, M, N, P, Q, R, S, T). The first column holds the code valid for the routing. Note 1: when two routings are defined between end fixes/areas solely to separate aircraft groups, the first column holds the code for the group permitted to use the routing and the second column holds the code for the group that must use the alternative routing; the second column is blank if there is no alternative routing. Used On: Preferred Route Records. Length: 2 characters. Character Type: Alpha. Examples: a Single Engine/Twin Engine separation pair uses ST for the Single Engine route and TS for the Twin Engine route.

| Aircraft or Aircraft Group                                    | Field Content   | Field Content   |
|---------------------------------------------------------------|-----------------|-----------------|
| All Aircraft                                                  | A               | See Note 1      |
| All Aircraft, Cruise speed 250 kts or less                    | C               | See Note 1      |
| Non-Jet and Turbo Prop                                        | D               | See Note 1      |
| Multi-Engine Props Only                                       | E               | See Note 1      |
| Jets and Turbo Props/Special, Cruise Speed 190 kts or greater | F               | See Note 1      |
| Helicopter Only                                               | H               | See Note 1      |
| Jet Power                                                     | J               | See Note 1      |
| Turbo-Prop/Special, Cruise Speed 190 kts or greater           | M               | See Note 1      |
| Non-Jet, Non-Turbo Prop                                       | N               | See Note 1      |
| Non-Jet, Cruise speed 190 kts or greater                      | P               | See Note 1      |
| Non-Jet, Cruise speed 189 kts or less                         | Q               | See Note 1      |
| Aircraft as defined in a Notes Continuation Record            | R               | See Note 1      |
| Single Engine                                                 | S               | See Note 1      |
| Twin Engine                                                   | T               | See Note 1      |

## 5.222 GNSS/FMS Indicator (GNSS/FMS IND)

The GNSS/FMS Indicator field shows whether the responsible government agency has authorized overlay of a conventional ground-based approach with a GNSS-capable sensor, or authorized FMS as primary navigation equipment, and also indicates when a PBN RNP procedure is authorized for GNSS-based vertical navigation. The indicator is selected from the table below (values 0-4, P, U, and letters A-D, G, L). Note 1: A indicates the PBN RNP procedure is authorized for SBAS-based vertical navigation. Note 2: B indicates the PBN RNP or RNAV Visual procedure is NOT authorized for SBAS-based vertical navigation, though advisory vertical may be provided. Note 3: C indicates SBAS-based vertical navigation use has not been published for the PBN RNP procedure. Note 4: D indicates the PBN RNP is SBAS-authorized only for lateral navigation, with advisory vertical possibly provided. Note 5: G indicates the GPS approach is a PBN RNAV approach with route type P. Note 6: L indicates the LOC approach is the Localizer-only portion of an ILS approach containing glideslope-out information. Used On: Airport and Heliport Approach Procedure Records. Length: 1 character. Character Type: Alpha/numeric.

| Indicator Definition                                                                                                               | Field Content   |
|------------------------------------------------------------------------------------------------------------------------------------|-----------------|
| Procedure Not Authorized for GNSS or FMS Overlay.                                                                                  | 0               |
| Procedure Authorized for GNSS Overlay, primary Navaids operating and monitored.                                                    | 1               |
| Procedure Authorized for GNSS Overlay, primary Navaids installed, not monitored. Example: Procedure Title includes (GPS) or (GNSS) | 2               |
| Procedure Authorized for GNSS Overlay, Procedure Title includes GPS or GNSS                                                        | 3               |
| Procedure Authorized for FMS Overlay                                                                                               | 4               |
| PBN RNP Procedure SBAS use authorized; SBAS-based vertical navigation authorized                                                   | A (Note 1)      |
| PBN RNP or RNAV Visual Procedure, SBAS-based vertical navigation NOT Authorized                                                    | B (Note 2)      |
| PBN RNP Procedure, SBAS-based vertical navigation use not published                                                                | C (Note 3)      |
| PBN RNP Procedure within the SBAS operational footprint, but SBAS-based vertical navigation NOT Authorized                         | D (Note 4)      |
| Stand Alone GPS (GNSS) Procedure                                                                                                   | P               |
| PBN RNP Approach provide as GPS                                                                                                    | G (Note 5)      |
| Localizer only coding portion of ILS                                                                                               | L (Note 6)      |
| Procedure Overlay Authorization not published                                                                                      | U               |

## 5.223 Operation Type (OPS TYPE)

The Operation Type field indicates whether the operation is an approach procedure, an advanced operation, or another operation type to be defined later.

## 5.223-x92 COMMENTARY

Advanced operations can include straight-in approaches followed by a missed approach, precision curved approaches, departure procedures, and roll-out/taxiing procedures. The field holds a value from 0 to 15; separate code ranges are defined for SBAS and GBAS operations (see table). Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 2 characters. Character Type: Numeric.

| SBAS   | SBAS                                                  |
|--------|-------------------------------------------------------|
| 0      | Straight-in or point-in-space approach procedure      |
| 1-2    | Reserved for future definition                        |
| 3-15   | Spare                                                 |
| GBAS   | GBAS                                                  |
| 0      | Straight-in approach path                             |
| 1      | Terminal Area Path definition (not for FAS Datablock) |
| 2      | Missed Approach (not for FAS Datablock)               |
| 3-15   | Spare                                                 |

## 5.224 Route Indicator (RTE IND)

The Route Indicator field is a single alpha character differentiating multiple final approach segments to the same runway or helipad within Final Approach Coding, using a code A through Z (omitting I and O). This character is consistent with the Multiple Approach Indicator, the fifth character of an Approach Procedure Identifier per Section 5.10. Used On: Airport and Helicopter Operations SBAS Path Point, GBAS Path Point Record. Length: 1 character. Character Type: Alpha.

## 5.225 Ellipsoidal Height

The Ellipsoidal Height field is the height of a surveyed point relative to the WGS-84 ellipsoid, an official publication value expressed in meters to a tenth of a meter with the decimal point suppressed. A leading minus (-) sign indicates the height is below the ellipsoid; otherwise a plus (+) sign is used. On Path Point Records, it applies to the LTP or FTP Position; on Helicopter Operations SBAS Path Point Records, it is the height above ellipsoid for the Fictitious Helipoint (or helipoint); on Runway Records, it applies to the Landing Threshold. Used On: Airport and Helicopter Operations SBAS Path Point Record, GBAS Path Point Records, and Runway Records. Length: 6 characters. Character Type: Alpha/numeric. Examples: +00356, +00051, +00015, -00022, -01566.

## 5.226 Glide Path Angle (GPA)

The Glide Path Angle field is an angle, in degrees, tenths, and hundredths of degrees, measured at the Flight Path Control Point (FPCP) for approach procedures requiring an Airport or Helicopter Operations SBAS Path Point record or GBAS Path Point Record; it sets the intended descent gradient for the final approach flight path (see Figure 5-8). Values are derived from official government source. Used On: Airport and Helicopter Operations SBAS Path Point Record, GBAS Path Point Records. Length: 4 characters. Character Type: Numeric. Examples: 0275 (2.75°), 1015 (10.15°), 0300 (3.00°).

## 5.227 Orthometric Height (ORTH HGT)

The Orthometric Height field is the height of a surveyed point relative to Mean Sea Level (MSL), derived from official government source and entered to a tenth of a meter with the decimal point suppressed. A leading minus (-) sign indicates height below MSL; otherwise a plus (+) sign is used. Used On: Airport and Helicopter Operations Path Point Continuation Records, GBAS Path Point Continuation Records, SBAS Path Point Continuation Records. Length: 6 characters. Character Type: Alpha/numeric. Examples: +00356, +00051, +01566, -00022, -01566.

## 5.228 Course Width At Threshold (CRS WDTH)

The Course Width At Threshold field defines the lateral course width at the Landing Threshold Point (LTP) or Fictitious Helipoint; combined with the Flight Path Alignment Point (FPAP) location, it defines lateral deviation sensitivity throughout the approach. Derived from official government sources, it is entered in meters (hundreds, tens, units, tenths, hundredths, decimal point suppressed) with a resolution of 0.25 meters, ending in 00, 25, 50, or 75. For a helicopter alighting point (helipad), the value is 38 meters (03800); for a helicopter Point in Space (PinS) procedure, it is the course width at a fictitious helipoint (see Figure 5-9). Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 5 characters. Character Type: Numeric. Examples: 08025, 14375, 03800.

## 5.229 Final Approach Segment Data CRC Remainder (FAS CRC)

The Final Approach Segment Data CRC Remainder field is an eight-character hexadecimal representation of the 32-bit CRC value, provided by the source for the aeronautical data fields monitored for integrity, calculated by a specific mathematical algorithm that is both machine and man processible. For CRC calculation, refer to RTCA DO-229 (Minimum Operational Performance Standards for GPS/WAAS Airborne Equipment, FAS Data Block CRC standards) or RTCA DO-246 (GNSS Based Precision Approach LAAS Signal-in-Space ICD), as appropriate. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 8 characters. Character Type: Alpha/numeric. Examples: 243BC649, A6934B72.

## 5.230 Procedure Type (PROC TYPE)

The Procedure Type field on the Flight Planning Arrival/Departure Data Record is a single character indicating the procedure type, such as Arrival, STAR, SID, Vector SID, or Approach, each with codes for whether it is Available or Not Available in the Database (see table). Used On: Flight Planning Arrival/Departure Data Records. Length: 1 character. Character Type: Alpha.

| Procedure Type Description                                        | Procedure Type Code   |
|-------------------------------------------------------------------|-----------------------|
| Arrival Procedure, Available in Database                          | A                     |
| Arrival Procedure, Not Available in Database                      | B                     |
| Departure Procedure, Available in Database                        | C                     |
| Departure Procedure, Not Available in Database                    | D                     |
| Standard Terminal Arrival Route (STAR), Available in Database     | E                     |
| Standard Terminal Arrival Route (STAR), Not Available in Database | F                     |
| Standard Instrument Departure (SID), Available in Database        | G                     |
| Standard Instrument Departure (SID), Not Available in Database    | H                     |
| Vector SID, Available in Database                                 | I                     |
| Vector SID, Not Available in Database                             | J                     |
| Approach Procedure, Available in Database                         | K                     |
| Approach Procedure, Not Available in Database                     | L                     |

## 5.231 Along Track Distance (ATD)

The Along Track Distance field on Flight Planning Arrival/Departure Data Records is the total distance for a given transition, from the initial fix to the ending fix. A single Primary Record occurrence can hold up to three ATD fields (one per transition type in the terminal route) plus up to four intermediate fix points per Continuation Record; collectively these equal the along-track distance from the first fix of the first transition to the last fix of the last transition. Data suppliers calculate the distances from coded or uncoded terminal procedures derived from official government source, expressed in nautical miles with 1NM resolution. Used On: Flight Planning Arrival/Departure Data Records. Length: 3 characters. Character Type: Numeric.

## 5.232 Number of Engines Restriction (NOE)

The Number of Engines Restriction field on Flight Planning Arrival/Departure Data Records, derived from government source, is included when a procedure (normally a departure) is restricted to or designed for aircraft with a specific number of engines. The field holds character Y for each authorized engine configuration position (1, 2, 3, 4) and N for non-authorized positions. Used On: Flight Planning Arrival/Departure Data Records. Length: 4 characters. Character Type: Alpha. Examples: YYYY (1, 2, 3, or 4 engine aircraft may use procedure); NNYY (3 and 4 engine aircraft may use procedure).

## 5.233 Turboprop/Jet Indicator (TURBO)

The Turboprop/Jet Indicator field on Flight Planning Arrival/Departure Data Records, derived from government source, is included when a procedure (normally a departure) is restricted to or designed for aircraft with a specific kind of engine. The use restriction (Turboprop, Jet, or Both, etc.) is indicated by a single character from the table below (A, B, C, D, E, J, N, P). Used On: Flight Planning Arrival/Departure Data Records. Length: 1 character. Character Type: Alpha.

| Aircraft or Aircraft Group                 | Field Content   |
|--------------------------------------------|-----------------|
| All Aircraft                               | A               |
| Jets and Turbo Props                       | B               |
| All Aircraft, Cruise speed 250 kts or less | C               |
| Non-jet and Turbo Prop                     | D               |
| Multi-Engine Props Only                    | E               |
| Jets                                       | J               |
| Non-Jet, Non-Turbo Prop                    | N               |
| Turbo Props                                | P               |

## 5.234 RNAV Flag (RNAV)

The RNAV Flag field on Flight Planning Arrival/Departure Data Records, derived from government source, is included when a procedure is restricted to or designed for RNAV-capable aircraft. The field contains Y if the procedure is RNAV, or N if it is not. Used On: Flight Planning Arrival/Departure Data Records. Length: 1 character. Character Type: Alpha.

## 5.235 ATC Weight Category (ATC WC)

The ATC Weight Category field on Flight Planning Arrival/Departure Data Records, derived from government source, is included when a procedure is restricted to or designed for a specific aircraft weight grouping: H for Heavy (aircraft types of 136,000kg / 300,000LB or more), M for Medium (less than 136,000kg / 300,000LB and more than 7,000kg / 155,000LB), L for Light (aircraft types of 7,000kg / 155,000LB or less). Used On: Flight Planning Arrival/Departure Data Records. Length: 1 character. Character Type: Alpha.

## 5.236 ATC Identifier (ATC ID)

The ATC Identifier field on Flight Planning Arrival/Departure Data Records is the officially published procedure designation required for Flight Planning, derived from official government source. This seven-character field is required in addition to the six-character identifier; the ATC Identifier is used in Flight Planning while the six-character identifier is used to access the database. Used On: Flight Planning Arrival/Departure Data Records. Length: 7 characters. Character Type: Alpha/numeric.

## 5.237 Procedure Description (PROC DESC)

The Procedure Description (PROC DESC) field on Flight Planning Arrival/Departure Data Records provides the textual representation of the procedure name, derived from official government source, to help match flight plan content to charted procedures. Used On: Flight Planning Arrival/Departure Data Records. Length: 15 characters, Alpha/numeric.

## 5.238 Leg Type Code (LTC)

The Leg Type Code (LTC) field, used on Flight Planning Arrival/Departure Data Records, simplifies the Path Terminator concept by indicating the path between intermediate waypoints as straight or curved and the turn direction at an intermediate waypoint. In this two-character field, the first position uses S for straight line point-to-point or C for curved line flight track; the second position uses L for Left or R for Right turn indication. Used On: Flight Planning Arrival/Departure Data Records. Length: 2 characters, Alpha.

## 5.239 Reporting Code (RPT)

The Reporting Code (RPT) field, used on Flight Planning Arrival/Departure Data Records, simplifies the Waypoint Description concept by indicating whether an intermediate waypoint requires a position report. The single-character field uses C for Position Report Required (Compulsory Report) and X for Position Report Not Required (On-Request Report). Used On: Flight Planning Arrival/Departure Data Records. Length: 1 character, Alpha.

## 5.240 Altitude (ALT)

The Altitude (ALT) field, used on Flight Planning Arrival/Departure Data Records, is a simplified version of the altitude concept used in full procedure records, expressed in hundreds of feet with no AGL, MSL, or FL indication. It is derived from official government source and reduced to this flight planning resolution. Used On: Flight Planning Arrival/Departure Data Records. Length: 3 characters, Numeric. Examples: FL100 = 100, 10000 feet = 100, 03500 feet = 035.

## 5.241 Fix Related Transition Code (FRT Code)

The Fix Related Transition Code (FRT Code) field, used on Flight Planning Arrival/Departure Data Continuation Records containing Intermediate Fix information, indicates in which transition of the procedure the intermediate fix is located, using the standard coding practice that separates the procedure into transitions. Used On: Flight Planning Arrival/Departure Data Records. Length: 1 character, Numeric.

| Intermediate Fix is Located in Transition Type   |   Field Content |
|--------------------------------------------------|-----------------|
| Fix Located in SID Runway Transition             |               1 |
| Fix Located in SID Common Portion                |               2 |
| Fix Located in SID Enroute Transition            |               3 |
| Fix Located in STAR Enroute Transition           |               4 |
| Fix Located in STAR Common Portion               |               5 |
| Fix Located in STAR Runway Transition            |               6 |

## 5.242 Procedure Category (PROC CAT)

The Procedure Category (PROC CAT) field supports the All Sensor RNAV Approach procedure, which has multiple sets of weather minimums (DH and NDA) associated with it, by identifying the Procedure Categories to which each set of minimums applies. Used On: Airport and Heliport SID/STAR/Approach Procedure Continuation Records. Length: 4 characters, Alpha.

| Content   | Procedure Category                          |
|-----------|---------------------------------------------|
| LAAS      | Local Area Differential Augmentation System |
| WAAS      | Wide Area Differential Augmentation System  |
| FMS       | Flight Management System                    |
| GPS       | Global Positioning System, no Augmentation  |
| VDME      | VORDME, VORTAC                              |
| CIRC      | Circle-To-Land                              |

## 5.243 GLS Station Identifier

The GLS Station Identifier field defines the identification code used to retrieve a GLS transmitter from a database; it is not a transmitted identifier. Its content is the Airport or Heliport ICAO Location Identifier Code at which the transmitter is installed. Used On: GLS Records. Length: 4 characters max, Alpha/numeric.

## 5.244 SBAS/GBAS Channel

The GNSS Channel Number (SBAS/GBAS Channel) field identifies the channel used for a given approach. It is derived from official government sources and entered as five numeric digits, ranging from 0000 to 9999 and 20001 to 99999. Numbers below 20000 are generally reserved for ILS and MLS; in some countries 0000-9999 are reserved for SCAT-1 (entered as 00000-09999); 20001-39999 are reserved for GBAS (and SBAS where applicable); and 40000-99999 are reserved for SBAS. Used On: GLS and Path Point Continuation Records. Length: 5 characters, Numeric. Examples: 01423, 20010, 56234.

## 5.245 Service Volume Radius

The Service Volume Radius field identifies the radius, in nautical miles, of the service volume around the GLS transmitter. The value is derived from official government sources; if no source is provided, the field is left blank. Used On: GLS Record. Length: 2 characters, Numeric. Examples: 05, 19.

## 5.246 TDMA Slots

The TDMA Slots field identifies the Time Division Multiple Access time slot(s) in which the ground station transmits the related approach. GPS's high-precision time source enables TDMA, allowing multiple ground stations to share a common frequency by dividing it into eight time slots; a station may broadcast in one or more of the eight slots. The value is derived from official government sources, ranging from 01 to FF, with blank as the default if no source is provided. Used On: GLS Record. Length: 2 characters, Alpha/numeric. Examples: A2, 01, FF.

## 5.247 Station Type

The Station Type field identifies the type of differential ground station: the first character is L for a LAAS/GLS ground station or C for a SCAT-1 station; the second and third characters are currently blank but are reserved to indicate the interoperability standard the station conforms to. The value is derived from official government sources, defaulting to blank if LAAS/GLS or SCAT-1 is not specified. Used On: GLS Record. Length: 3 characters, Alpha/numeric. Examples: L, C.

## 5.248 Station Elevation WGS84

The Station Elevation WGS84 field identifies the WGS84 ellipsoid elevation, in feet, of the GLS ground station described in the record, derived from official government sources. When the elevation is below the WGS84 ellipsoid, the first column of the field contains a minus (-) sign. Used On: GLS Record. Length: 5 characters, Alpha/numeric. Examples: 00530, -0140.

## 5.249 Longest Runway Surface Code (LRSC)

The Longest Runway Surface Code (LRSC) field defines whether a hard-surface runway exists. On Airport Records it applies to the runway length indicated in the Longest Runway field; on Runway Continuation Records (as Runway Surface Code) it applies to the runway described in that record; on Helipad records (as Helipad Surface Code) it applies to the helipad described in the record. Used On: Airport Records Runway Continuation Record, Airport and Heliport Helipad Records. Length: 1 character, Alpha.

| Field Content   | Description                                        |
|-----------------|----------------------------------------------------|
| H               | Hard Surface, for example, asphalt or concrete     |
| S               | Soft Surface, for example, gravel, grass or soil   |
| W               | Water Runway                                       |
| U               | Undefined, surface material not provided in source |

## 5.250 Alternate Record Type (ART)

The Alternate Record Type (ART) field identifies whether an Alternate Record applies to the departure airport (take-off alternate), destination airport (arrival alternate), or a fix along the route (enroute alternate). Field content AA indicates the Airport identifier in Columns 7-11 of the Primary Record is the Arrival Airport; DA indicates it is the Departure Airport; EA indicates the end fix of a Company Route identified in Columns 7-15 of the Primary Record. Used On: Alternate Records. Length: 2 characters, Alpha.

| Content   | Description                                                                                                      |
|-----------|------------------------------------------------------------------------------------------------------------------|
| AA        | The Airport identifier in Columns 7 through 11 of the Primary Record is the identifier of the Arrival Airport.   |
| DA        | The Airport identifier in Columns 7 through 11 of the Primary Record is the identifier of the Departure Airport. |
| EA        | The end fix of a Company Route is identified in Columns 7 through 15 of the Primary Record.                      |

## 5.251 Distance To Alternate (DTA)

The Distance To Alternate (DTA) field defines either the direct (geodesic) distance from the Destination Airport or Fix to the Alternate Airport, or the along-track distance of an alternate Company Route. When the Alternate Type field is A, DTA carries the straight-line geodesic distance in nautical miles between the Destination Airport/Fix and the Alternate Airport listed in the Alternate Identifier fields; when Alternate Type is C, DTA carries the cumulative along-track distance for the Alternate Company Route. Used On: Alternate Records. Length: 3 characters max, Numeric.

## 5.252 Alternate Type (ALT TYPE)

The Alternate Type (ALT TYPE) field is an information-processing indicator specifying whether the Alternate Identifier fields define an alternate airport or a company route to an airport. The field contains A when an Airport is provided or C when a Company Route is provided. Used On: Alternate Records. Length: 1 character, Alpha.

## 5.253 Primary and Additional Alternate Identifier (ALT IDENT)

The Primary and Additional Alternate Identifier (ALT IDENT) fields (primary plus up to four additional alternates) uniquely identify either an Alternate Airport or an Alternate Company Route, with the Alternate Type field determining which. Content is determined by the customer. Used On: Alternate Records. Length: 10 characters max, Alpha/numeric.

## 5.254 Fixed Radius Transition Indicator (FIXED RAD IND)

The Fixed Radius Transition Indicator (FIXED RAD IND) field indicates that a specific turn radius from the inbound to outbound course is required by the airspace controlling agency. When required, a 3-digit numeric value gives the turn radius in nautical miles to one decimal place (decimal point suppressed); a blank entry indicates no fixed radius transition is required. Used On: Enroute Airway Records. Length: 3 characters, Numeric. Examples: 225 = 22.5 nm, 150 = 15.0 nm.

## 5.255 SBAS Service Provider Identifier (SBAS ID)

The SBAS Service Provider Identifier (SBAS ID) field associates the SBAS approach procedure with a particular satellite-based augmentation system service provider; in the GBAS Path Point Record it is carried only for CRC calculation purposes. It is a number from 00 to 15. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 2 characters, Numeric.

| 0    | WAAS                                                          |
|------|---------------------------------------------------------------|
| 1    | EGNOS                                                         |
| 2    | MSAS                                                          |
| 3    | GAGAN                                                         |
| 4    | SDCM                                                          |
| 5-13 | (Spare)                                                       |
| 14   | Not intended for SBAS, used as the CRC default value for GBAS |
| 15   | Any Service provider may be used                              |

## 5.256 Reference Path Data Selector (REF PDS)

The Reference Path Data Selector (REF PDS) field enables automatic tuning of a procedure by Ground Based Augmentation System (GBAS) avionics; it is not used for SBAS operations. It is a number from 00 to 48, selected via receiver channeling, and is set to zero for SBAS Path Point Records. Used On: Airport, Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 2 characters, Numeric.

## 5.257 Reference Path Identifier (REF ID)

The Reference Path Identifier (REF ID) field is a three- or four-character alphanumeric code uniquely designating the reference path; it is synonymous with the approach ID shown beneath the Channel Number on Instrument Approach Plates and is unique only for a given airport. It uses upper-case alpha characters or numeric digits, derived from official government sources and analogous to the Morse code identifier on existing ILS approaches. Industry practice often uses a leading service-provider character (e.g., W for WAAS, E for EGNOS), though this is not mandatory, followed by the runway number and a trailing alpha character. For Point in Space procedures, the final approach segment course rounded to the nearest 10 degrees replaces the runway number. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 4 characters, Alpha/numeric. Examples: W12A, E27A, W34A.

## 5.258 Approach Performance Designator (APD)

The Approach Performance Designator (APD) field indicates the type or category of approach; it is not used for SBAS operations and is set to zero for SBAS Path Point Records. It is a number from 0 to 7 corresponding to GBAS Approach Service Types (GAST): per RTCA DO-253, a GAST is the matched set of airborne and ground performance and functional requirements used together to provide approach guidance with quantifiable performance. Used On: Airport, Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 1 character, Numeric. Example: 1 (Category I Approach).

| 0   | GAST A or GAST B   |
|-----|--------------------|
| 1   | GAST C             |
| 2   | GAST C or GAST D   |
| 3-7 | Spare              |

## 5.259 Length Offset (OFFSET)

The Length Offset (OFFSET) field is the distance from the Stop End of the Runway (SER) to the FPAP, defining the location where lateral sensitivity changes to missed approach sensitivity; it is zero if the FPAP is located at the designated center of the opposite runway end, and blank if not provided by source. The value, expressed in meters (actual resolution 8 meters), is derived from official government sources. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 4 characters, Alpha/Numeric. Examples: 0000, 0432.

## 5.260 Terminal Procedure Flight Planning Leg Distance (LEG DIST)

The Terminal Procedure Flight Planning Leg Distance (LEG DIST) field is the along-track distance required to complete a given leg, used to determine cumulative track distance for a terminal procedure for flight planning purposes, from the beginning of the take-off or arrival point to the procedure's termination point. Values are determined during route definition and controlled by Path and Termination requirements and data supplier coding rules, expressed in nautical miles and tenths with the decimal point suppressed. Used On: Airport and Heliport SID, STAR, and Approach Procedure Flight Planning Continuation Records. Length: 4 characters, Numeric. Examples: 0176, 0822, 0208, 0016, 0100.

## 5.261 Speed Limit Description (SLD)

The Speed Limit Description (SLD) field designates whether a speed limit coded at a fix in a terminal procedure is mandatory, minimum, or maximum. For maximum speeds, the SID and Missed Approach Procedure limit applies backward from the coded leg to the beginning of the procedure or the previous speed limit, while the STAR and Approach Procedure limit applies forward to the end of the arrival (excluding the missed approach) or until superseded. For minimum speeds, the SID and Missed Approach Procedure limit applies forward to the end of the SID or Missed Approach or until superseded, while the STAR and Approach Procedure limit applies backward from the coded leg to the beginning of the procedure or the previous speed limit. For mandatory speeds, the requirement applies only at the coded fix and is not carried to previous or subsequent legs. Field content is @ (blank) for Mandatory speed (cross fix AT the specified speed), + (plus) for Minimum speed (AT or ABOVE), and - (minus) for Maximum speed (AT or BELOW).

| Field Content Value   | Description                                                         |
|-----------------------|---------------------------------------------------------------------|
| @(blank)              | Mandatory Speed, Cross Fix AT speed specified in Speed Limit        |
| + (plus)              | Minimum Speed, Cross Fix AT or ABOVE speed specified in Speed Limit |
| - (minus)             | Maximum Speed, Cross Fix AT or BELOW speed specified in Speed Limit |

## 5.263 HAL

This section header (HAL) contains only field usage metadata in the extracted source text, with no accompanying definition or source/content notes. Used On: Airport/Heliport SID/STAR/Approach Records. Length: 1 character. Character Type: Alpha.

## 5.262 Approach Type Identifier (ATI)

The Approach Type Identifier (ATI) field identifies the approach types published on a given approach procedure that require Airport or Helicopter Operations SBAS Path Point records. It holds up to 10 characters representing the literal name of an approach with vertical guidance requiring path points, Horizontal Alert Limit (HAL), and Vertical Alert Limit (VAL), derived from government source material. Used On: Airport and Helicopter Operations SBAS Path Point Continuation Records. Length: 10 characters, Alpha/numeric. Examples: LPV, LP, APV-II.

The Horizontal Alert Limit (HAL) is the radius of a circle in the horizontal plane (the local plane tangent to the WGS-84 ellipsoid), centered at the true position, describing the region required to contain the indicated horizontal position with the required probability for a given navigation mode, assuming the probability of a GPS satellite integrity failure being included in the position solution is less than or equal to 10-4 per hour. The value is expressed in meters to a resolution of tenths of meters (decimal point suppressed), derived from official government sources. Used On: Airport and Helicopter Operations SBAS Path Point Records. Length: 3 characters, Numeric. Examples: 400, 200.

## 5.264 Vertical Alert limit (VAL)

The Vertical Alert Limit (VAL) is half the length of a segment on the vertical axis (perpendicular to the horizontal plane of the WGS-84 ellipsoid), centered at the true position, describing the region required to contain the indicated vertical position with a probability of 1-10-7 per approach, assuming the probability of a GPS satellite integrity failure being included in the position solution is less than or equal to 10-4 per hour. For approaches with lateral-only guidance, VAL equals 0, indicating vertical deviations cannot be used. The value is expressed in meters to a resolution of tenths of meters (decimal point suppressed), derived from official government sources. Used On: Airport and Helicopter Operations SBAS Path Point Records. Length: 3 characters, Numeric. Examples: 120, 500.

## 5.265 Path Point TCH

The Path Point TCH field is, on procedures to runways or helipads, the height above the runway threshold (LTP) or helicopter alighting point; on Point in Space procedures, it is the height of the fictitious helipoint above the heliport. It is the same concept as the TCH defined in Section 5.67 but with greater resolution due to required precision. The value, derived from official government sources, is expressed either in feet to a resolution of tenths of a foot or in meters to a resolution of hundredths of a meter (decimal point suppressed in both cases); the TCH Units Indicator determines which unit applies. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 6 characters, Numeric. Examples: 000526, 001023 (Feet); 001603, 003118 (meters).

## 5.266 TCH Units Indicator

The TCH Units Indicator field, used in Path Point Records, defines the unit of measure for the Path Point TCH: F if the value is provided in feet, or M if provided in meters. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 1 character, Alpha.

## 5.267 High Precision Latitude (HPLAT)

Definition/Description: HPLAT contains the latitude of the navigation feature identified in the record. On Airport Path Point Records, one feature is the LTP/FTP, the other the FPAP. On Helicopter Operations Path Point Records, one feature is the Fictitious Helipoint (or Helipoint), the other the FPAP. Source/Content: the field expands the latitude defined in Section 5.36 to include degrees, minutes, seconds, tenths, hundredths, thousandths and tenths of thousandths of seconds, for a high precision resolution of 0.0005 arc seconds. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 11 characters. Character Type: Alpha/numeric. Example: N3028422400.

## 5.268 High Precision Longitude (HPLONG)

Definition/Description: HPLONG contains the latitude of the navigation feature identified in the record. On Airport Path Point Records, one feature is the LTP/FTP, the other the FPAP. On Helicopter Operations Path Point Records, one feature is the Fictitious Helipoint (or Helipoint), the other the FPAP. Source/Content: the field expands the latitude defined in Section 5.36 to include degrees, minutes, seconds, tenths, hundredths, thousandths and tenths of thousandths of seconds, for a high precision resolution of 0.0005 arc seconds. Used On: Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records. Length: 12 characters. Character Type: Alpha/numeric. Example: W08142030100.

## 5.269 Helicopter Procedure Course (HPC)

Definition/Description: HPC, used on Path Point Continuation Records, defines the final approach course of procedures designed for helicopter operations to runways, helipads, and points in space. Source/Content: the field contains the full degree final approach course of the procedure, derived from official government source, and is used with the Approach Procedure Identifier and Runway/Helipad Identifier in the Path Point Primary record to uniquely identify an approach procedure. Used On: Airport and Helicopter Operations SBAS Path Point Continuation Records. Length: 3 Characters. Character Type: Numeric. Examples: 003, 013, 103, 310, 333.

## 5.270 TCH Value Indicator (TCHVI)

Definition/Description: TCHVI defines which TCH value is provided in the runway record. Source/Content: values are I (TCH is that of the Electronic Glideslope), R (TCH is that of an RNAV procedure to the runway), and D (TCH is the default value of 40 or 50 feet, see Section 5.67). Used On: Runway Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                                                                  |
|-----------------|----------------------------------------------------------------------------------------------|
| I               | TCH provided in Runway Record is that of the Electronic Glideslope.                          |
| R               | TCH provided in Runway Record is that of an RNAV procedure to the runway.                    |
| D               | TCH provided in the Runway Record is the default value of 40 or 50 fee t (See Section 5.67). |

## 5.271 Procedure Turn (PROC TURN)

Definition/Description: the TAA Procedure Turn field indicates whether a course reversal is necessary when flying within a particular TAA Area. Source/Content: official government source carries an indication (generally NOPT) when the course reversal is not necessary; otherwise a course reversal is expected. When not necessary, the field carries N; when necessary, it carries Y. The indication is provided for each sector on a particular TAA Initial Approach Fix. Used on: Airport or Heliport TAA Primary Record. Length: 1 character. Character Type: Alpha.

## 5.272 TAA Sector Identifier

Definition/Description: the TAA Sector Identifier (Fix Position Indicator) field indicates which TAA Initial Approach Fix (IAF) or Intermediate Fix (IF) the record's data applies to. Source/Content: TAAs are published for each IAF or IF for some RNAV and GPS Approach Procedures; content is derived from official government source per the table: C = Straight-In or Center Fix, L = Left Base Area, T = Right Base Area. Left/right/center refer to the TAA fix's position relative to the final approach course, or the direction of turn onto final from the base leg. On Airport and Heliport Approach Procedure Records it points to the specific TAA Record (PK) holding the fix data. Used On: Airport and Heliport TAA Primary Records. Length: 1 character. Character Type: Alpha.

| Field Content   | TAA Fix Position Indicator   |
|-----------------|------------------------------|
| C               | Straight-In or Center Fix    |
| L               | Left Base Area               |
| T               | Right Base Area              |

## 5.273 TAA Waypoint

Definition/Description: the TAA Waypoint field contains the identifier of the Initial Approach Fix (IAF) or Intermediate Fix (IF) associated with a given Terminal Area Altitude sector; up to three IAF waypoints may be defined for a single approach procedure, and the TAA IAF Waypoint in each TAA Sector record is the fix from which radius distances are defined. Source/Content: the field contains the official identifier of the waypoint for which the TAA Sector is defined, derived from official government sources. Used On: Airport and Heliport TAA Records. Length: 5-character max. Character Type: Alpha/numeric.

## 5.274 TAA Sector Radius

Definition/Description: the Sector Radius field in TAA records defines the inclusive start and end distances of a TAA area, referenced to the TAA IAF Waypoint defined in that record. Source/Content: derived from official government source; each TAA sector comprises a start-of-sector radius and end-of-sector radius in nautical miles. The first two digits give the radius for the start of the sector, the second two digits the end of the sector, when flying towards the IAF/IF Waypoint. Used On: Airport and Heliport TAA Primary Records. Length: 4 characters. Character Type: Numeric. Examples: 3011, a Sector that starts at 30 nautical miles to the IAF Waypoint and ends at 11 nautical miles to the IAF Waypoint. 0500, a Sector that starts at 5 nautical miles to the IAF Waypoint and ends at that IAF Waypoint.

## 5.275 Level of Service Name (LSN)

Definition/Description: the Level of Service Name (LSN) field identifies the official procedure level of service based on published procedure operating minimums for PBN RNP APCH or A_RNP Approach Procedures. Source/Content: derived from official government source; examples include LPV, LPV200, LP, LNAV, and LNAV/VNAV. Used On: Procedure Data Continuation Records. Length: 10 characters (Note 3). Character Type: Alpha. Note 1: the names LPV, LPV200, LP, LNAV/VNAV, and LNAV are derived from industry documentation in use when Supplement 20 was published; other terminology may be in use. Note 2: only LPV originally had a FAS Block Provided category; since only one FAS Block Level of Service name exists per approach procedure, LPV, LPV200, and LP are given in the FAS Block Provided Level of Service Name field (Sections 4.1.9.5 or 4.2.3.5) while other names are in dedicated fields; LNAV/VNAV and/or LNAV can be authorized with or without a FAS Datablock, so they are always carried in the dedicated field. Note 3: the 10-character field is left justified with remaining columns blank; when the paired Level of Service Authorized field (Sections 4.1.9.5 or 4.2.3.5, and 5.276) is N (Not Authorized), the entire 10-character field should be blank.

| Level of Service Name (Note 1)   | Level of Service Name (Note 1)   |
|----------------------------------|----------------------------------|
| LPV                              | (Note 2)                         |
| LPV200                           | (Note 2)                         |
| LP                               | (Note 2)                         |
| LNAV                             | LNAV                             |
| LNAV/VNAV                        | LNAV/VNAV                        |

## 5.276 Level of Service Authorized

Definition/Description: the Level of Service Authorized field defines whether the Level of Service designated in the associated field (Section 5.275) is authorized or not authorized for a procedure. Source/Content: derived from official government sources; a code selected from the table: A = Designated Level of Service is authorized for the procedure, N = Designated Level of Service is not authorized for the procedure. Used On: Procedure Data Continuation Records. Length: 1 characters. Character Type: Alpha.

| Description                                                      | Field Content   |
|------------------------------------------------------------------|-----------------|
| Designated Level of Service is authorized for the procedure.     | A               |
| Designated Level of Service is not authorized for the procedure. | N               |

## 5.277 DME Operational Service Volume (D-OSV)

Definition/Description: the DME Operational Service Volume (D-OSV) field specifies the service volume information of DME Navaids to support DME-DME and DME-DME-IRU FMS capabilities in RNAV procedures and routes. Source/Content: derived from official government source documentation and encoded per the table: A = 40NM or less, B = 70NM or less, C = 130NM or less, D = Greater than 130NM, U = Unspecified. Used On: VHF Navaid Primary Records. Length: 1 character. Character Type: Alpha.

| Field Content   | D-OSV Description   |
|-----------------|---------------------|
| A               | 40NM or less        |
| B               | 70NM or less        |
| C               | 130NM or less       |
| D               | Greater than 130NM  |
| U               | Unspecified         |

## 5.278 Activity Type

Definition/Description: the Activity Type field defines the type of Special Activity that is occurring. Source/Content: derived from official government publications; codes are P = Parachute Jumping Area, G = Glider Operations, H = Hang Glider Activities, U = Ultralight Activities. Used On: Special Activity Area records. Length: 1 character. Character Type: Alpha.

| Type                   | Field Content   |
|------------------------|-----------------|
| Parachute Jumping Area | P               |
| Glider Operations      | G               |
| Hang Glider Activities | H               |
| Ultralight Activities  | U               |

## 5.279 Activity Identifier

Definition/Description: the Activity Identifier field contains the number or name that uniquely identifies the Special Activity Area. Source/Content: derived from official government publications; an alphanumeric designation up to 6 characters combining Activity Type, State/Nation, and Activity Designator. Used On: Special Activity Area records. Length: 6 characters. Character Type: Alpha/numeric. Examples: PTX117, GVA5, UOR99.

| Field Content          | Field Content   | Field Content   | Field Content       |
|------------------------|-----------------|-----------------|---------------------|
| Activity               | Type            | State/Nation    | Activity Designator |
| Parachute Jumping Area | P               | TX              | 117                 |
| Glider Operations      | G               | VA              | 5                   |
| Hang Glider Activities | H               | CA              | 45                  |
| Ultralight Activities  | U               | OR              | 99                  |

## 5.280 Special Activity Area Size

Definition/Description: the Special Activity Area Size field contains the radius around the center point where the Special Activity is expected to occur. Source/Content: defined from official government publications when available; the radius is entered in nautical miles to a tenth of a nautical mile with the decimal point suppressed. Used On: Special Activity Area records. Length: 3 characters. Character Type: Numeric. Examples: 020, 105, 050.

## 5.281 Special Activity Area Volume

Definition/Description: the Special Activity Area Volume field contains the expected annual level of intensity of the Special Activity. Source/Content: derived from official government publications when available. Used On: Special Activity Area records. Length: 1 character. Character Type: Alpha/numeric.

## 5.282 Special Activity Area Operating Times

Definition/Description: the Special Activity Area Operating Times field contains the annual expected operation schedule of the Special Activity. Source/Content: derived from official government publications when available, per a table combining Days (C = Weekdays and Weekends, D = Weekdays, E = Weekends, O = Other, U = Unknown), Holiday Qualifier (H = Including Holidays, X = Excluding Holidays, U = Unknown), and Time of Use (D = SR-SS, N = Night Use, C = Continuous, A = Active by NOTAM). Used On: Special Activity Area records. Length: 3 characters. Character Type: Alpha. Examples: DXD (Weekdays, Excluding Holidays from Sunrise to Sunset).

| Field Content         | Field Content   | Field Content     | Field Content   |
|-----------------------|-----------------|-------------------|-----------------|
| Description           | Days            | Holiday Qualifier | Time of Use     |
| Weekdays and Weekends | C               |                   |                 |
| Weekdays              | D               |                   |                 |
| Weekends              | E               |                   |                 |
| Other                 | O               |                   |                 |
| Unknown               | U               |                   |                 |
| Including Holidays    |                 | H                 |                 |
| Excluding Holidays    |                 | X                 |                 |
| Unknown               |                 | U                 |                 |
| SR-SS                 |                 |                   | D               |
| Night Use             |                 |                   | N               |
| Continuous            |                 |                   | C               |
| Active by NOTAM       |                 |                   | A               |

## 5.283 Communications Class (Comm Class)

Definition/Description: the Communications Class (Comm Class) field designates the major grouping of the Communications Types contained in the record. Source/Content: value selected from the table: LIRC (linked to an FIR/UIR for control services), LIRI (linked to an FIR/UIR for information services), USVC (used within an FIR/UIR for purposes other than control or information services, not linked to that Region), ASVC (automated or broadcast services within an FIR/UIR), ATCF (ATC services to aircraft within an airport terminal area), GNDF (ATC services to aircraft on the ground at an airport), AOTF (services other than ATC on the ground or within an airport terminal area), AFAC (automated or broadcast services to aircraft on the ground or within an airport terminal area). Used On: Enroute, Airport, and Heliport Primary and Continuation Communications Records and the Communications Type Translation Table Record. Length: 4 characters. Character Type: Alpha.

| Field Content   | Description                                                                                                                                                                  |
|-----------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| LIRC            | The Communications Type is that of one linked to an Information Region (FIR/UIR) for the purposes of providing control services to aircraft.                                 |
| LIRI            | The Communications Type is that of one linked to an Information Region (FIR/UIR) for the purposes of providing information services to aircraft.                             |
| USVC            | The Communications Type is that of one used within an Information Region (FIR/UIR) for purposes other than control or information services and is not linked to that Region. |
| ASVC            | The Communications Type is that of one providing automated or broadcast services within an Information Region (FIR/UIR).                                                     |
| ATCF            | The Communications Type is that of one providing ATC services to aircraft within the terminal area of an airport.                                                            |
| GNDF            | The Communications Type is that of one providing ATC services to aircraft on the ground at an airport.                                                                       |
| AOTF            | The Communications Type is that of one providing services other than ATC functions on the ground or within the terminal area of an airport.                                  |
| AFAC            | The Communications Type is that of one provided automated or broadcast services to aircraft on the ground or with the terminal area of an airport.                           |

## 5.284 Assigned Sector Name (ASN)

Definition/Description: the Assigned Sector Name (ASN) field indicates the published name of an Enroute Communications Sector. Source/Content: content derived from official government source. Used On: Enroute Communications Records. Length: 25 characters max. Character Type: Alpha/numeric. Examples: West Sector, Mediterranean Sector, UR Sector, SE High Sector.

## 5.285 Time Narrative

Definition/Description: the Time Narrative field provides Time of Operations and/or Conditions of Operations in narrative form when source information cannot be formatted per Section 5.195. Source/Content: content derived from official government sources. Used On: Enroute Airway Restriction, Enroute/Airport/Heliport Communications, Restrictive Airspace, Controlled Airspace and Preferred Route Continuation Records. Length: 100 characters max (per record). Character Type: Alpha/numeric.

## 5.286 Multi-Sector Indicator (MSEC IND)

Definition/Description: the Multi-Sector Indicator (MSEC IND) field indicates that the communications service and frequency are used in more than one defined sector, with the actual sector data in the primary and continuation records of the affected airport or heliport communications record set. Source/Content: set to Y when multi-sector data is published in official government source for the service and frequency, or N when official government source provides only a single defined sector for the service and frequency; left blank if no defined sector data is published for the service and frequency. Used On: Airport and Heliport Communications Primary Records. Length: 1 character. Character Type: Alpha/numeric.

## 5.287 Type Recognized By (TRB)

Definition/Description: the Type Recognized By (TRB) field provides an indication of the provider of a given Communications Type (5.101).

## 5.289 Used On

Definition/Description: the Used On field provides an indication of what kind of communications records a particular Communications Type is used on. Source/Content: the content is derived from the official government source used to establish the Communications Type and selected from the table: I (found in government source per ICAO standards), F (found in government source per US FAA standards), B (found in government source per both ICAO and US FAA standards), C (found in government source provided by the country in which the communications is used), O (found in government source provided by the country in which the communications is used), S (established by the data supplier). Used On: Communications Type Translation Table Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                                                                                        |
|-----------------|--------------------------------------------------------------------------------------------------------------------|
| I               | The Communications Type is found in government source provided in accordance with ICAO standards.                  |
| F               | The Communications Type is found in government source provided in accordance with US FAA standards.                |
| B               | The Communications Type is found in government source provided in accordance with both ICAO and US FAA standards.  |
| C               | The Communications type is found in government source provided by the country in which the communications is used. |
| O               | The Communications type is found in government source provided by the country in which the communications is used. |
| S               | The Communications Type has been established by the data supplier.                                                 |

## 5.288 Translation

Definition/Description: the Translation field provides a decoding of a three-character Communications Type (5.101). Source/Content: content derived from official government source documentation, with a listing for every Communications Type in the output file. Used On: Communications Type Translation Table Records. Length: 80 characters max. Character Type: Alpha/numeric. Examples: TWR: ATC Control Tower, GCO: Ground Communication Outlet, ATI: Automated Terminal Services. A related table defines the record types a Communications Type applies to: A = Airport Communications Records only, E = Enroute Communications Records only, H = Heliport Communications Records only, B = Airport, Heliport and Enroute Communications Records, C = Airport and Heliport Communications Records; that indicator field is 1 character, Alpha, used on Communications Type Translation Table Records.

| Field Content   | Description                                                                              |
|-----------------|------------------------------------------------------------------------------------------|
| A               | The Communications Type is used on Airport Communications Records only.                  |
| E               | The Communications Type is used on Enroute Communications Records only.                  |
| H               | The Communications Type is used on Heliport Communications Records only.                 |
| B               | The Communications Type is used on Airport, Heliport and Enroute Communications Records. |
| C               | The Communications Type is used on Airport and Heliport Communications Records.          |

## 5.290 Procedure Design Mag Var (PDMV)

Definition/Description: the Procedure Design Mag Var (PDMV) field specifies the angular difference between True North and Magnetic North at the location defined in the record, which may be the airport for which the procedure was designed (the Airport Magnetic Variation of Record) or the procedure leg defined in the record, as determined by the data coded to Section 5.291 (Procedure Design Mag Var Indicator). Source/Content: obtained from official government procedure data sources and understood to be the Epoch Year value used when the procedure was last revised; this may differ from magnetic variation data in the airport primary record or from individual navaid/waypoint data, and is updated only when procedure source data changes. Position 1 contains an alpha character from the table: E = Magnetic Variation East of True North, W = Magnetic Variation West of True North, T = Procedure Designed based on True North. Positions 2 thru 5 carry the angular difference in degrees and tenths of a degree with the decimal point suppressed; when Position 1 is T, Positions 2 thru 5 are all zeros. Length: 5 characters. Character Type: Alpha/numeric. Examples: E0140, E0007, T0000.

| Field Content   | Description                                                                                    |
|-----------------|------------------------------------------------------------------------------------------------|
| E               | Procedure Designed based on Magnetic Variation (angular difference) that is East of True North |
| W               | Procedure Designed based on Magnetic Variation (angular difference) that is West of True North |
| T               | Procedure Designed based on True North                                                         |

## 5.291 Procedure Design Mag Var Indicator (PDMVI)

Definition/Description: the Procedure Design Mag Var Indicator (PDMVI) field indicates how procedure design magnetic variation was provided in official source data for the procedure defined in the record/record set. Source/Content: Procedure Design Mag Var (5.290) is obtained from official government source procedure data, either as a single value valid for the entire procedure or a series of values for individual legs. The field contains P when the value applies to the entire procedure or L when it applies to the associated leg. Except for VOR radials and tracks in VORDME RNAV Approach procedures, Approach Procedures are designed using the airport magnetic variation of record with a single value for the complete procedure; VOR radials use the established station declination of the VOR, and tracks in VORDME RNAV procedures use the station declination of the procedure reference navaid. Used On: Airport and Heliport SID/STAR/Approach Primary Extension Continuation Records. Length: One character. Character Type: Alpha.

## 5.292 Category Distance

Definition/Description: the Category Distance (Category Radii) fields, expressed in tenths of nautical miles, specify the obstacle clearance area for aircraft maneuvering to land on a runway not aligned with the FAC of the approach procedure; the circling area limits are an arc from the center of the end of each usable runway, with adjacent arcs joined by tangent lines, enclosing the circling approach area. Source/Content: obtained from official government publications; the field contains a figure in nautical miles with a resolution of 1/10, or 00 if the radii are not known or defined. Used On: Airport and Heliport Approach Continuation Records. Length: 2 characters. Character Type: Alpha/numeric. Examples: 00, 13, 15, 17, 23.

## 5.293 Vertical Scale Factor (VSF)

Definition/Description: Vertical Scale Factor (VSF) is used to set the vertical deviation scale. Source/Content: VSF values derived from official source when available are entered in feet (three digits). On Enroute Airway segments, VSF applies inbound to the fix in decreasing sequence number order and only to the airway leg on which it is specified; if no VSF is coded, there is no database-specified VSF for that segment. On a SID, STAR, Approach Transition or Missed Approach record, VSF applies to the balance of the procedure route unless superseded by another VSF value on a subsequent record, with the procedure route determined by the Route Type field (Section 5.7). On final approach records, VSF applies to the waypoint referenced by the final approach record. Used On: Enroute Airways, SID, STAR and Approach Route and Controlled Airspace Records, Holding Pattern Records. Length: 3 characters. Character Type: Numeric. Examples: 250, 100, 050.

## 5.294 RVSM Minimum Level

Definition/Description: RVSM Minimum Level is the lowest defined cruising level for an airway or holding pattern. Source/Content: derived from official source when available and entered as a three-digit numeric flight level. Used On: Enroute Airway Records, Holding Pattern Records. Length: 3 characters. Character Type: Numeric. Examples: 080, 180, 270.

## 5.295 RVSM Maximum Level

Definition/Description: RVSM Maximum Level is the highest defined cruising level for an airway or holding pattern. Source/Content: derived from official source when available and entered as a three-digit numeric flight level. Used On: Enroute Airway Records, Holding Pattern Records. Length: 3 characters. Character Type: Numeric. Examples: 270, 250, 510.

## 5.296 RNP Level of Service (LSN)

Definition/Description: the RNP Level of Service (LSN) field identifies the official procedure level of service based on published procedure operating minimums for Approach Procedures authorized for RNP. Source/Content: derived from official government source and provided beginning with the least restrictive value; examples include 031, 152, 112. Note 1: the RNP level of service name fields are formatted per Chapter 5 Section 5.211; if the field is not applicable because the associated Level of Service Authorized (Section 4.1.9.5 or 4.2.3.5, and 5.276) is N for Not Authorized, the RNP Level of Service will be populated regardless of the Level of Service Authorized (5.276) designation. Used On: Procedure Data Continuation Records. Length: 3 characters. Character Type: Numeric.

|   Level of Service Name - RNP (Note 1) |
|----------------------------------------|
|                                    031 |
|                                    152 |
|                                    112 |

## 5.297 Route Inappropriate Navaid Indicator

A Route Inappropriate Navaid Indicator applies when a DME navaid has source-provided information identifying it as inappropriate for use in navigation solutions for RNAV 1 and RNAV 2 routes. The field is set to N when the DME navaid has not been published as inappropriate for RNAV 1 or RNAV 2 navigation solutions, or Y when it has been published as inappropriate for one or more such routes. Used On: VHF Navaid Primary Records. Length: 1 character. Character Type: Alpha.

## 5.298 Holding Pattern/Race Track Course Reversal Leg Inbound/Outbound Indicator

The Leg Inbound/Outbound Indicator identifies whether the Leg Length or Leg Time field values (5.64 or 5.65) apply to the inbound or outbound leg of a holding pattern or race track course reversal. The field contains I for Inbound or O for Outbound, derived from official government source documentation. On SID/STAR/Approach Records, it is populated only when the Path and Terminator is HA, HF, or HM; otherwise it is blank. Used On: Holding Pattern, Airport, and Heliport SID/STAR/Approach Records. Length: 1 character. Character Type: Alpha.

## 5.299 Procedure Referenced Fix Identifier

The Procedure Referenced Fix Identifier field contains the five-character-name-code, or other series of characters, identifying the Fix. The officially published Waypoint Identifier, VHF Navaid Identifier, or NDB Navaid Identifier is required for use in the terminal procedure but is not included in the SID, STAR, or Approach primary record procedure coding. Source/Content: Officially published identifiers. Used On: Airport/Heliport SID/STAR/Approach Primary Extension Continuation Records. Length: 5 characters max. Character Type: Alpha/numeric (no embedded blanks). Examples: SHARP, BBNSI.

## 5.300 Final Approach Course as Runway

The Final Approach Course as Runway field provides data for Point in Space approach procedures that are not to a runway. The Final Approach Course is derived from government publications and populated with the final approach course rounded to the nearest 10 degrees, expressed as a two-digit number; other positions are zero filled. Used On: Helicopter Operations SBAS Path Point Records, Airport SBAS Path Point Primary Records, and GBAS Path Point Primary Records. Length: 5 characters. Character Type: Numeric. Examples: 01000, 15000, 36000.

## 5.301 Procedure Design Aircraft Category or Type

This field identifies the aircraft category(s) or type(s) for which a procedure or portion of a procedure (transition) was designed, or the aircraft category(s)/type(s) applicable to a speed limit in a Controlled Airspace. Source/Content: derived from official government sources; contains a single alpha character defined in the accompanying table. For Approach Procedures, the content is specific to a Transition and can vary between Transitions within a single procedure. Used On: Airport and Heliport SID, STAR, and Approach, and Controlled Airspace Records. Length: 1 character. Character Type: Alpha (may be blank). Section was updated to reference the speed limit in Controlled Airspace Record; Aircraft Type Turbojet and Turboprop only was added to the Aircraft Category or Type table.

| AIRCRAFT CATEGORY or TYPE                 | FIELD CONTENT   |
|-------------------------------------------|-----------------|
| Aircraft Category A only                  | A               |
| Aircraft Category B only                  | B               |
| Aircraft Category C only                  | C               |
| Aircraft Category D only                  | D               |
| Aircraft Category E only                  | E               |
| Aircraft Categories A and B only          | F               |
| Aircraft Categories C and D only          | G               |
| Aircraft Categories A, B, and C only      | I               |
| Aircraft Categories A, B, C, and D only   | J               |
| Aircraft Categories A, B, C, D, E only    | K               |
| Aircraft Categories D and E only          | L               |
| Aircraft Category H - (Helicopter) only   | H               |
| Aircraft Categories B and C only          | M               |
| Aircraft Categories C, D, and E only      | N               |
| Aircraft Categories B, C, D, and E only   | O               |
| Aircraft Type Jets only                   | W               |
| Aircraft Type Non-Jets only               | X               |
| Aircraft Type Pistons only                | Y               |
| Aircraft Type Not Limited                 | P               |
| Aircraft Type Turbojet and Turboprop only | Q               |
| Aircraft Type Turbojet only               | R               |
| Aircraft Type Turboprop only              | S               |
| Aircraft Type Prop only                   | T               |
| Aircraft Type Turboprop and Prop          | U               |
| Aircraft Type Non-Turbojets only          | V               |
| Aircraft Category/Type not provided       | Blank           |

## 5.302 Surface Type

The Surface Type field defines the predominant surface type of the runway/helipad described in the record. Source/Content: valid contents and their associated Runway Surface Code (5.249) are defined in the accompanying table (e.g., ASPH Asphalt, CONC Concrete, GRAS Grass, WATE Water, UNKN Unknown). Used On: Runway Continuation, Airport Helipad, Heliport Helipad Records. Length: 4 characters. Character Type: Alpha.

| Surface Type   | Description                                                                                                        | Surface Code (5.249)   |
|----------------|--------------------------------------------------------------------------------------------------------------------|------------------------|
| ASPH           | Asphalt                                                                                                            | H                      |
| ASGR           | Asphalt and grass                                                                                                  | H                      |
| BITU           | Bituminous tar or asphalt and/or oil or bitumen bound, mix-in-place surfaces (often referred to as 'earth cement') | H                      |
| BRCK           | Brick, laid, or mortared                                                                                           | S                      |
| CLAY           | Clay                                                                                                               | S                      |
| CONC           | Concrete                                                                                                           | H                      |
| COAS           | Concrete and asphalt                                                                                               | H                      |
| COGS           | Concrete and grass                                                                                                 | H                      |
| CORL           | Coral                                                                                                              | S                      |
| DIRT           | Dirt                                                                                                               | S                      |
| GRAS           | Grass                                                                                                              | S                      |
| GRVL           | Gravel                                                                                                             | S                      |
| ICE            | Ice                                                                                                                | S                      |
| LATE           | Laterite - a high iron clay formed in tropical areas                                                               | S                      |
| MACA           | A macadam or tarmac surface consisting of water- bound crushed rock                                                | H                      |
| MATS           | Landing mat portable system usually made of aluminum                                                               | S                      |
| MEMB           | A protective laminate usually made of rubber                                                                       | S                      |
| META           | Metal - steel, aluminum                                                                                            | H                      |
| MIX            | Non-Bituminous mix                                                                                                 | S                      |
| OTHR           | Other                                                                                                              | U                      |
| PAVD           | Paved (generic hard surface type)                                                                                  | H                      |
| PSP            | Pierced steel planking                                                                                             | S                      |
| SAND           | Sand                                                                                                               | S                      |
| SELD           | Sealed                                                                                                             | S                      |
| SILT           | Silt                                                                                                               | S                      |
| SNOW           | Snow                                                                                                               | S                      |
| SOIL           | Soil (Earth (in general))                                                                                          | S                      |
| STON           | Stone                                                                                                              | H                      |
| TARM           | Tarmac                                                                                                             | H                      |
| TRTD           | Treated                                                                                                            | S                      |
| TURF           | Turf                                                                                                               | S                      |
| UNKN           | Unknown                                                                                                            | U                      |

| Surface Type   | Description                         | Surface Code (5.249)   |
|----------------|-------------------------------------|------------------------|
| UNPV           | Unpaved (generic soft surface type) | S                      |
| WATE           | Water                               | W                      |

## 5.303 Helipad Shape

The Helipad Shape field defines the geometric shape of a helipad as circle, runway, or rectangular. Source/Content: derived from official government sources when available, selected from a table: C for Circle, S for Square/Rectangle, R for Runway, U for Undefined/not provided in source. Used On: Airport Helipad Records, Heliport Helipad Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                     |
|-----------------|-------------------------------------------------|
| C               | Circle                                          |
| S               | Square/Rectangle                                |
| R               | Runway                                          |
| U               | Undefined, helipad shape not provided in source |
| C               | Circle                                          |

## 5.304 Sector Bearing Reference Waypoint

The Sector Bearing Reference Waypoint field contains the identifier of the waypoint that Sector Bearings are referenced to within a given Terminal Area Altitude (TAA) sector. Source/Content: contains the official waypoint identifier, derived from official government sources. Used On: Airport and Heliport TAA Records. Length: 5 characters max. Character Type: Alpha/numeric.

## 5.305 Heliport Type

This field provides information on the type of heliport facility. Source/Content: the indicator is selected from a table: H for Hospital, O for Oil Rig, Blank for all other types, U for type not provided. Used On: Heliport Records. Length: 1 character. Character Type: Alpha (may be blank).

| Heliport Type     | Field Content   |
|-------------------|-----------------|
| Hospital          | H               |
| Oil Rig           | O               |
| All other types   | Blank           |
| Type not provided | U               |

## 5.306 Preferred Multiple Approach Indicator

The Preferred Multiple Approach Indicator identifies the multiple approach generally considered most likely to be utilized/needed when multiple approaches are available for a given approach type at a runway; it is defined on the Approach FAF record in the Final Approach. For a given approach type at a runway, there shall be one and only one Preferred Multiple Approach Indicator. Source/Content: per official government source; when not provided, defined by data suppliers as appropriate. A P on the approach final FAF record indicates the preferred multiple approach, which can be given priority during data packing if desired; a blank indicates the approach is not preferred. Used On: Airport and Heliport SID/STAR/Approach Records. Length: 1 character. Character Type: Alpha (may be blank).

## 5.307 Special Indicator

This field indicates whether a terminal procedure requires specific operational approval per official government sources. Special procedures may be based on aircraft performance, equipment, or crew training, and may require landing aids, communications, or weather services not available for public use (e.g., SIAP, RCAP). Source/Content: a Y indicates a special procedure derived from official government sources; a blank indicates the procedure is not special. Used On: Airport and Heliport SID/STAR/Approach Records. Length: 1 character. Character Type: Alpha (may be blank).

## 5.308 Remote Altimeter Flag

This field indicates whether a Remote Altimeter Setting applies to the procedure, meaning LNAV/VNAV (Baro-VNAV) is Not Authorized when the Remote Altimeter Setting is used. Source/Content: based on government sources; the field contains R when there is a Remote Altimeter Restriction on LNAV/VNAV (Baro-VNAV) Lines of Minimum, otherwise blank. Used On: Procedure Data Continuation Records. Length: 1 character. Character Type: Alpha.

## 5.309 Maximum Allowable Helicopter Weight

The Maximum Allowable Helicopter Weight represents the maximum weight, in hundreds of pounds, that a helipad or FATO can support. Source/Content: derived from official government sources; if no source is provided, the value is blanked. Used On: Airport Helipad Records, Heliport Helipad Records. Length: 3 characters. Character Type: Numeric. Examples: 101, 050, 100.

## 5.310 Helicopter Performance Requirement

The Helicopter Performance Requirement identifies any restriction imposed on helicopter performance to use a given helipad. Source/Content: derived from official government sources when available, selected from a table: M for Multi-engine required, S for Single engine only, U for Unknown.

| Field Content   | Description           |
|-----------------|-----------------------|
| M               | Multi-engine required |
| S               | Single engine only    |
| U               | Unknown               |

## 5.311 FIR/FRA Transition Waypoint

The FIR/FRA Transition Waypoint field designates specific waypoint types used to enter, exit, and/or transition through Free Route Airspace (FRA) within a Flight Information Region (FIR); these designations are normally provided by host nation authorities via their AIP. Source/Content: derived from official government sources, selected from a table (columns 44-49): E Entry Point, X Exit Point, A Arrival Transition Point, D Departure Transition Point, I Intermediate Point, H Terminal Holding Point. A waypoint may have multiple values assigned by the State airspace authority.

|   Column | Field Content   | Description                |
|----------|-----------------|----------------------------|
|       44 | E               | Entry Point                |
|       45 | X               | Exit Point                 |
|       46 | A               | Arrival Transition Point   |
|       47 | D               | Departure Transition Point |
|       48 | I               | Intermediate Point         |
|       49 | H               | Terminal Holding Point     |

## 5.313 TORA

Take Off Run Available (TORA) is the declared distance value available for take-off ground roll, used with Section 5.317 Runway Usage Indicator. Source/Content: derived from official government sources and shown in feet. Starter extension distances are not included in TORA and may be added if a starter extension is available. A value of 00000 indicates the runway is not usable for take-off; a blank field means no value is declared in source. Used On: Runway Continuation Records. Length: 5 characters. Character Type: Numeric. Examples: 02900, 10000.

## 5.314 TODA

Take Off Distance Available (TODA) is the declared distance value available for take-off over a 50 ft obstacle, used with Section 5.317 Runway Usage Indicator; typically TODA equals TORA plus clearway. Source/Content: derived from official government sources and shown in feet. Starter extension distances are not included in TODA. A value of 00000 indicates the runway is not usable for take-off; a blank field means no value is declared in source. Used On: Runway Continuation Records. Length: 5 characters. Character Type: Numeric. Examples: 02900, 10000. Definition/Description: Accelerate Stop Distance Available is the declared distance value which is available in case of an aborted take-off. The field is [continues in following section].

## 5.315 ASDA

Used On: Waypoint Flight Planning Continuation Records. Length: 1 character. Character Type: Alpha/Numeric.

## 5.312 Starter Extension

Starter Extension means an area made available for take-off, prior to the normal runway end at the beginning of the takeoff run. Starter extensions are established where additional takeoff distance, takeoff run, or accelerate-stop distance is required, but physical limitations do not allow provision of the mandatory runway strip or width. Source/Content: derived from official government sources and shown in feet (see Table 5-15). Used On: Runway Records. Length: 4 characters. Character Type: Numeric. Examples: 0900, 1000.

## 5.316 LDA

[Continuation of ASDA] Used in conjunction with Section 5.317 Runway Usage Indicator; typically ASDA equals TORA plus stopway. Source/Content: the ASDA value is derived from official government sources and shown in feet. Starter extension distances are not included in the ASDA distance and may be added if a starter extension is available. A value of 00000 indicates the runway is not usable for take-off; a blank field means no value is declared in source. Used On (5.316-x94): Runway Continuation Records. Length: 5 characters. Character Type: Numeric. Examples: 02900, 10000. Landing Distance Available (LDA) is the declared distance value available for landing, used with Section 5.317 Runway Usage Indicator; typically LDA equals runway length minus the threshold displacement distance. Source/Content: derived from official government sources and shown in feet. A value of 00000 indicates the runway is not usable for landing; a blank field means no value is declared in source. Used On: Runway Continuation Records. Length: 5 characters. Character Type: Numeric. Examples: 02900, 10000.

## 5.317 Runway Usage Indicator

The Runway Usage Indicator field specifies whether a runway is usable for take-off, landing, or both operations. Source/Content: derived from official government sources, with content selected from a table. A field content of L requires TORA, TODA, and ASDA to be 0 and LDA either blank or non-0; a field content of T requires TORA, TODA, and ASDA to be blank or non-0 and LDA to be 0. Used On: Runway Continuation Records. Length: 1 character. Character Type: Alpha.

## 5.318 Runway Accuracy Compliance Flag

This flag indicates whether runway parameters meet Runway Accuracy Requirements: coded Runway Length (5.57) within 5 meters of an independently measured length; coded Runway Threshold Position (5.36, 5.37) within 5 meters of an independently measured location; coded Runway Threshold Displacement Distance (5.69) within 5 meters of an independently measured value; and runway true bearing computed from coded Runway Magnetic Bearing (5.58) and Airport Magnetic Variation (5.39) within 0.5 degrees of an independently measured true bearing. Source/Content: populated by the data provider using a table: Y (meets Accuracy Requirements), N (does not meet), or Blank (not evaluated). Used On: Runway Records. Length: 1 character. Character Type: Alpha.

| Field Content   | Description                                                      |
|-----------------|------------------------------------------------------------------|
| Y               | Runway data meets Accuracy Requirements                          |
| N               | Runway data does not meet Accuracy Requirements                  |
| Blank           | Runway data has not been evaluated against Accuracy Requirements |

## 5.319 Landing Threshold Elevation Accuracy Compliance Flag

This flag indicates whether the Runway Landing Threshold Elevation (5.68) meets Accuracy Requirements, defined as being within 5 meters of an independently measured landing threshold elevation. Source/Content: populated by the data provider using a table: Y (meets Accuracy Requirements), N (does not meet), or Blank (not evaluated). New section was added.

| Field Content   | Description                                                                           |
|-----------------|---------------------------------------------------------------------------------------|
| Y               | Landing Threshold Elevation data meets Accuracy Requirements                          |
| N               | Landing Threshold Elevation data does not meet Accuracy Requirements                  |
| Blank           | Landing Threshold Elevation data has not been evaluated against Accuracy Requirements |

## 5.319-x95 Used On: Runway Record Length: 1 Character Character Type: Alpha

Used On: Runway Record. Length: 1 character. Character Type: Alpha. [5.320 SBAS Final Approach Course] Definition/Description: The SBAS Final Approach Course field contains the published final approach course of the PBN procedure with SBAS level of service. Source/Content: derived from the PBN procedure Final Approach Course. Used On: Path Point Continuation Records. Length: 4 characters. Character Type: Alpha/Numeric. Examples: 2570, 0147, 2910, 347T.

## 5.320 SBAS Final Approach Course

New section was added.
