## 5 NAVIGATION DATA - FIELD DEFINITIONS

5.1 If a STAR ends in vectors to a final approach (VM leg), the Airport Record or Heliport Record for which the procedure is established will be coded in the Waypoint Ident field of the STAR Record.

5.2 Deleted by Supplement 19.

5.3 If a STAR does not begin at a fix in the source documentation, the closest named fix along the STAR track must be assigned as the initial fix (IF leg) for the STAR.

5.4 If no crossing altitudes are specified on intermediate fixes of a STAR or Profile Descent, a vertical angle will be coded in the last leg of the procedure. This angle will be computed, based on the altitudes specified at the end fixes, to provide a constant descent path through all intermediate fixes. The angle provided will ensure compliance with minimum enroute altitudes for those segments without assigned altitudes.

5.5 A STAR which consists of a single path from an origination fix to a termination fix will be coded as a Route Type 2.

5.6 When a STAR Route or portion of a STAR Route is repeated with different Runway Identifiers or different Helipad Identifiers in the Transition Identifier it must be coded as a Runway Transition Route Type 3. When a STAR Route/Profile Descent Route or portion of a STAR Route is repeated with different Fix Identifiers in the Transition Identifier, it must be coded as an Enroute Transition Route Type 1.

5.7 When an Arrival Route serves the same runway or helipad as an Approach Route and the Arrival Route overlaps an Approach Transition, both the Arrival Route and the Approach Transition will be coded in their entirety in accordance with source documentation.

5.8 A STAR which consists of Enroute Transitions only can be coded with the required Route Type 3 coding, followed by a single IF leg as a Route Type 2. The fix on which the IF leg is coded must be the last fix in all of the Enroute Transitions. The Transition Identifier must be coded in accordance with Chapter Five, Section 5.11. In the cases where all the Enroute Transitions do not end at the same fix, but where most end at the same fix then a partial STAR may be coded.

Identify Project Papers expected to be completed per the table in the following section.

## 5.1 General

Section sets forth definitions/descriptions and content for each type of field employed in the records discussed in Chapter 4. The following information is presented for each field:

Field Name (section heading)

Abbreviation used in proportional record layouts (Chapter 4) when different than Field Name (follows section heading)

Field Definition/Description

Source/Content of each field

Length of field, expressed in number of characters

Type of character allowed in each field, alpha or numeric or alpha/numeric

Examples of field content when appropriate and/or necessary

The following general rules apply to the format of all the fields:

All numeric fields and the numeric parts of latitude, longitude, magnetic variation, negative elevation, and station declination fields will be right justified and filled with leading zeros.

All alpha and alpha/numeric fields will be left justified.

Allowable field content of blank is defined as alpha/numeric content.

The following table identifies the number of meetings and proposed meeting days needed to produce the documents described above.

| Activity   | Mtgs      | Mtg-Days (Total)   | Expected Start Date   | Expected Completion Date   |
|------------|-----------|--------------------|-----------------------|----------------------------|
| Document a | # of mtgs | # of mtg days      | mm/yyyy               | mm/yyyy                    |
| Document b | # of mtgs | # of mtg days      | mm/yyyy               | mm/yyyy                    |

Please note the number of meetings, the number of meeting days, and the frequency of web conferences to be supported by the IA Staff.

## 5.2 Record Type (S/T)

Definition/Description: The Record Type field content indicates whether the record data are standard, i.e., suitable for universal application, or tailored, i.e., included on the master file for a single user's specific purpose (Section 1.2 of this specification refers).

Source/Content: The field contains the letter S when the field data are standard and the letter T when they are tailored.

Used On:

All records

Length:

1 character

Character Type:

Alpha

## 5.3 Customer/Area Code (CUST/AREA)

Definition/Description: The Customer Area Code field permits the categorization of standard records by geographical area and of tailored records by the airlines , airline subsets, or other customer code for whom they are provided in the master file. Several record types do not adhere to the established geographical boundaries. There is no AREA in such records.

Source/Content: AREA Codes should be derived from Figure 5-1. Airline codes should be derived from ICAO Doc 8585 for the three-letter code or the IATA Airline Coding Directory for the two-character code. If no code is defined in these documents for an entity, a unique code may be established. On Company Route and Preferred Route Records, an additional AREA field is used as a pointer to the AREA in which the Route Segment is located. For records, which do not follow geographical boundaries, the field is blank. For Preferred Routes, the field content is PDR.

Used On:

All records with content as defined above.

Length:

3 characters max

Character Type:

Alpha /numeric

Examples:

Areas - USA, CAN, EUR

Customer - UAL, DAL, DLH, AA8, DL3, LH8

Preferred Routes - PDR

The text was updated to numeric and airline subsets or other customer codes.

5.5 Subsection Code (SUB CODE)

Updated Table 5-1 and removed subsection code N, RNAV Table.

## 5.4 Section Code (SEC CODE)

Definition/Description: The Section Code field defines the major section of the navigation system database in which the record resides.

Source/Content: Table 5-1 shows the database section encoding scheme.

Used On:

All records

Length:

1 character

Character Type:

Alpha

## 5.5 Subsection Code (SUB CODE)

Definition/Description: The Subsection Code field defines the specific part of the database major section in which the record resides.

Additionally, records that reference other records within the database use Section/Subsection Codes to make the reference, together with the record identifier. This is true for fix information in Holdings, Enroute Airways, Airport and Heliport SID/STAR/APPROACH, all kinds of Communications, Airport and Heliport MSA, Airport and Heliport TAA, Company Routes, Enroute Airway Restrictions, Preferred Routes and Alternate Records. The Section Code will define the major database section, the Subsection Code permits the exact section (file) to be identified and the fix (record) can then be located within this file.

Source/Content: Table 5-1 shows the database Subsection Encoding Scheme.

Used On:

All records

Length:

1 character

Character Type:

Alpha

Table 5-1 - Section and Subsection Encoding Scheme

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

Table 5-1 - Section and Subsection Encoding Scheme

## 5.6 Airport/Heliport Identifier (ARPT/HELI IDENT)

Definition/Description: The Airport Identifier and the Heliport Identifier fields contain the identification of the airport or heliport to which the data contained in the record relates.

Source/Content: The content of this field is derived from official government sources. It will be the four-character ICAO Location Identifier of the airport or heliport when such is published. It will be the three or four-character Domestic

Identifier when published and no ICAO Location Identifier is available for the airport or heliport. It will be the supplied procedure location identifier for Point in Space procedures that are not designated to an Airport or Heliport. When used on Airport or Heliport Flight Planning Continuation Records, it will be the Airport or Heliport Identifier owning the terminal controlled airspace referenced in that record.

Note:

Within the continental United States, in addition to using the

published four character ICAO Location Identifiers, data suppliers append the character K for the USA to certain Domestic Identifiers to present an ICAO look-alike four character identifier.

## 5.6-x74 COMMENTARY

Where no officially published identifier is available, a data supplier may create a unique, temporary and unofficial identifier. Airports or Heliports within such identifiers may supply Tailored Data only and with full knowledge and concurrence of the data user. Whenever possible, such temporary identifiers should be coordinated among the various data suppliers prior to its release. In cases where a Point in Space procedure is to be provided to a location that is not an Airport or a Heliport, procedure design provided identifiers will be used.

The content of this Airport/Heliport Identifier should not be confused with the perhaps more familiar ATA/IATA two or three-character identifiers often user by airlines for other than navigation purposes. These ATA/IATA identifiers are included in the ARINC 424 database in accordance with Section 5.107 of this specification.

Used On:

Airport Identifier - VHF Navaid, NDB Navaid, Airport Terminal Waypoint, Airport, Airport Gate, Airport SID/STAR/Approach, Runway, Airport and Heliport Localizer, Airport and Heliport Localizer Marker, Holding Pattern, Airport Communications, Airport and Heliport MLS, GLS Airport MSA, Airport TAA, Path Point Flight Planning Arrival Departure Data, GLS Record, Airport Helipad Records, and Enroute Airway Restriction and Company Route to the Airport Identifier.

Heliport Identifier - VHF Navaid, NDB Navaid, Heliport Terminal Waypoint, Heliport, Heliport SID/STAR/Approach, Airport and Heliport Localizer, Airport and Heliport Localizer Marker, Holding Pattern, Heliport Communications, Airport and MLS, GLS Heliport MSA, Heliport TAA, Path Point Flight Planning Arrival/Departure Data, GLS Records, Airport Helipad Records, and Enroute Airway Restriction and Company Route to the Airport Identifier.

Point in Space Procedure Location Identifier - Heliport Records when used to provide Point in Space Procedure Location, Heliport Terminal Waypoint Records when used to provide Point in Space Procedures, Heliport SID/STAR/Approach Records when used to provide Point in Space Procedures, Heliport MSA Records when used for Point

in Space Procedures, Heliport Path Point Records for Point in Space Procedures, Heliport Helipad Records for Point in Space Procedures. Length: 4 characters maximum Character Type: Alpha/numeric Examples: KJFK, DMIA, 9Y9, CYUL, EDDF, 53Y, CA14

Figure 5-1 - Geographical Area Codes

## 5.7 Route Type (RT TYPE)

Definition/Description: The Route Type field defines the type of Enroute Airway, Preferred Route, Airport and Heliport SID/STAR/Approach Routes of which the record is an element. For Airport and Heliport SID/STAR/Approach Routes, Route Type includes a primary route type, and up to two route type qualifiers.

Source/Content: The content of this field (for approach procedures) will be as indicated in the following tables:

Table 5-2 - Enroute Airway Records (ER)

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

Table 5-2 - Enroute Airway Records (ER)

Table 5-3 - Route Qualifier Content

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

Table 5-3 - Route Qualifier Content

Note 1: The N will be coded if an airway is coded with Route Type R but includes non PBN segments. In these cases, Qualifier 1 and 2 will be blank.

Table 5-4 - Preferred Route Records (ET)

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

Table 5-4 - Preferred Route Records (ET)

Table 5-5 - Airport SID (PD) and Heliport SID (HD) Records

| SID Route Type Description    | Field Content   |
|-------------------------------|-----------------|
| Engine Out SID                | 0               |
| SID Runway Transition         | 1               |
| SID or SID Common Route       | 2               |
| SID Enroute Transition        | 3               |
| Vector SID Runway Transition  | T               |
| Vector SID Enroute Transition | V               |

Table 5-5 - Airport SID (PD) and Heliport SID (HD) Records

Table 5-2: added RNP and ICAO PBN Nav Spec.

Table 5-3: was added to support Route Qualifier Content, other tables were renumbered.

Table 5-6: Airport and Heliport SID Record, deleted Note 6.

Table 5-6: RNP 1 or RNAV 1 PBN Nav Spec to Qualifier Description.

### 5.7-x348 SUPPLEMENT 22 TO ARINC SPECIFICATION 424 - Page d

Table 5-7, Airport STAR (PE) and Heliport STAR (HE) Records, the following updates were made:

Added Note 2 to RNAV PBN Nave Spec under Qualifier 2.

Added an RNP PBN Nav Qualifier Description and reference Note 3.

Deleted Note 4 in the RNP AR PBN Nave Spec Qualifier.

Added RNP 1 or RNAV 1 PBN Nav Spec to Qualifier Description.

Table 5-8, Airport Approach (PF) and Heliport (HF) Records, the following updates were made:

The Qualifier Description GBAS Procedure was deleted. This update was completed to coincide with the ICAO definition.

Note 2 was updated to remove reference to GLS procedures.

## 5.7-x75 Table 5-6 - Airport and Heliport SID Record

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

Departure Procedures designed and published based upon an ICAO PBN RNP Navigation Specification. Qualifier 3

Note 1: must be coded with D, E, F, A, G, or U.

Note 2: RNAV Departures designed and published based upon an ICAO PBN RNAV Navigation Specification will be coded with a qualifier 3 Z, Y, X, B, P, M, or U. RNAV Departures not based upon PBN will be coded with a qualifier 3 U or V.

Note 3:   Used when the government authority has designated a Departure as FMS.

Note 4: The Qualifier F indicates that the departure is an RNP AR procedure. Implied GNSS required. Qualifier F used with SID route type 0 will designate an RNP AR Engine Out SID. Qualifier F can be used in conjunction with SID route type 1, 2 or 3, provided the corresponding SID transition is AR.

Note 5: Implied that Database Supported RNAV is required. Qualifier W and X can be used in conjunction with Qualifier 1 set to P and SID route type 1, 2, or 3. Qualifier 2 to be set to D when procedure chart is not annotated with Proceed Visually or Proceed VFR.

Table 5-7 - Airport STAR (PE) and Heliport STAR (HE) Records

| STAR Route Type Description   |   Field Content |
|-------------------------------|-----------------|
| STAR Enroute Transition       |               1 |
| STAR or STAR Common Route     |               2 |
| STAR Runway Transition        |               3 |

Table 5-7 - Airport STAR (PE) and Heliport STAR (HE) Records

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

Note 1:  Used when the government authority has designated an Arrival as FMS.

Note 2:  RNAV Arrivals designed and published based upon an ICAO PBN RNAV Navigation Specification will be coded with a qualifier 3 Z, Y, X, B, P , M , or U. RNAV Arrivals not based upon PBN will be coded with a qualifier 3 U or V.

Note 3:  Arrival Procedure designed and published based upon an ICAO PBN RNP Navigation Specification. Qualifier 3 must be coded with D, E, F, A, G, or U.

Table 5-8 - Airport Approach (PF) and Heliport Approach (HF) Records

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

Table 5-8 - Airport Approach (PF) and Heliport Approach (HF) Records

The listing above for Approach Route Type is alphabetical and does not represent any kind of priority.

Note 1: Route Type R indicates a procedure titled RNAV, e.g., RNAV (GPS) or RNAV (RNP). Route Type H indicates a procedure titled RNP.

**COMMENTARY:**

The Route Types H and R are coded to differentiate between the approach procedure titles published in state source. The words in brackets will not be considered for the coding of the Route Type. While according to the PBN manual there is no RNAV approach specification, many approaches are still published using an RNAV title. Additionally, there are still non PBN RNAV approaches published, e.g., VOR/DME RNAV.

The following old titles will be coded with a Route Type R: RNAV (GPS) RWY 09 RNAV (GNSS) RWY 09 RNAV (RNP) RWY 09

The following new titles will be coded with Route Type H:

RNP RWY 09 RNP RWY 09 (AR)

The following new titles will be coded with Route Type R:

RNAV RWY 09 RNAV RWY 09 (AR)

### 5.7-x75-x76 Table 5-9 - Airport Approach (PF) and Heliport (HF) Records

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

Not all Qualifiers will apply to all Route Types, see notes below. Qualifier fields may be blank where their use is not required by source documentation.

Note 1:

Qualifier 1 and 2 are carried on each sequence of every transition for Approach Procedure Coding (Approach Transition, Final Approach and Missed Approach) and will be identical for each sequence in a specific transition. Qualifier 2 will be different between Approach Transitions/Final approach coding where S or C will be used and Missed Approach where A, B, or E will be used (See Note 6). Qualifier 3 will be coded where applicable and will be identical for each sequence in a specific transition but may be different between transitions.

Note 2: Route Type R is used for all procedures titled RNAV. Route Type H is used for all types of RNP procedure coding titled RNP. The type of RNAV or RNP procedure is further defined through the content of Qualifier 1.

Conventional Area Navigation Approach Procedures using RHO-RHO or RHO-THETA equipment are coded as Route Type H or R and Qualifier 1 of T or V.

GNSS based RNP Approach Procedures are coded as Route Type H or R with Qualifier 1 set to J, R, P, or U as required by source publications and mapped to this table.

Note 3: In Approach Transition and Final Approach Coding, Qualifier 2 is set to indicate the type of minimums applicable to the coding as indicated in the table. A Qualifier 2 of S or H means the procedure has been coded as straight-in. There may also be circle-to-land minimums for the same procedure. Qualifier 2 is required for all Route Types and is independent of the content of Qualifier 1.

Note 4: A Qualifier 1 value of W is used to indicate that the Procedure is authorized for SBAS navigation (vertical and lateral, or lateral-only) and requires the ARINC 424 Path Point with the Final approach Segment (FAS) Data Block. No other navigation sensors are authorized for these procedures.

**Examples:**

Note 4, An Approach Procedure is authorized for SBAS navigation only (vertical and lateral, or lateral-only) and requires the FAS Data Block. The Route Type would be coded as H or R and Qualifier 1 would be coded as W. The associated GNSS/FMS Indicator (Section 5.222) would be set to indicate that SBAS-based vertical navigation is authorized. A Path Point Record carrying the FAS Data Block would be provided for the procedure. A Procedure Data Continuation Record would be provided and would be used to define the Levels of Service authorized and the official government source documentation Names for these Services.

Note 2, An Approach Procedure is authorized for SBAS navigation (lateral and/or vertical) and for single or multiple sensors other than SBAS. The Route Type would be coded as H or R and Qualifier 1 would be coded as J, P, or R, as appropriate. The setting of the GNSS/FMS Indicator would be appropriate to the level of authorization. A Path Point Record would or would not be provided, according to government source publications. A Procedure Data Continuation Record would be provided and would be used to define the Levels of Services authorized for SBAS and the official government source documentation Names for these Services.

Note 2, An Approach Procedure is authorized for a single or multiple sensors other than SBAS; SBAS-based vertical navigation is not authorized. The Route Type would be coded as H or R and Qualifier 1 would be coded as J, R L, U, or P as appropriate. The setting of the GNSS/FMS Indicator would be appropriate to the level of authorization. No Path Point Record

would be provided. No Procedure Data Continuation Record would be provided.

Note 5: The Qualifier 1 codes of D and N are not used on RNAV and RNP Procedures (Route Type H and R) of any kind. Additionally, these codes are not used in conjunction with Route Types that provide a DME Option of a procedure; specifically, they are not used in conjunction with the Route Types D and Q.

Note 6: The Qualifier 2 codes of A, B and E can only be used in conjunction with a Route Type of Z = Missed Approach Coding. Qualifier 2 codes of C, S, H, I, and L can be used in conjunction with any Route Type except Z.

Note 7: The Qualifier 2 code of H or I is only used with Airport Approach (PF) Records.

Note 8: The Qualifier F indicates that the approach is an RNP AR (Authorization Required) procedure. Qualifier A indicates an A-RNP procedure without an AR requirement. Qualifier H indicates that the approach procedure is a basic RNP procedure not requiring any further capabilities. Qualifiers E and X maybe coded on transitions for any non RNAV/RNP approaches.

Note 9: The Qualifier 2 code of L is used with Airport Procedure (PF) Records and Heliport Procedure (HF) Records and only for those government sources that provide Helicopter Minimums without specifying Straight-In or Circle-To-Land.

Note 10: The Qualifier 2 code of V is used only in conjunction with a Qualifier 1 of B.

Note 11: The Qualifier 2 code W and X are used only in conjunction with a Qualifier 1 set to J, P, R, U, V, or W. Qualifier 2 to be set to H, I, or L when procedure chart is not annotated with Proceed Visually or Proceed VFR.

Used On:

Enroute Airways, Airport and Heliport SID/STAR/Approach, Preferred Route and Company Route Records and Helicopter Operations Company Route Records.

Length:

1 character for Enroute Airways and Preferred Routes. 1 character for Airport and Heliport SID/STAR/Approach Records; however, only complete when read in conjunction with Qualifier 1, 2, and 3 of the same record, which are in a different location in the Records.

Character Type:

Alpha/numeric

Approach

Examples:

LDC = A Localizer-based procedure, for localizer only, no glideslope, with DME required, Circle-To-Land Minimums.

LNC= A Localizer-based procedure, for localizer only, no glideslope, DME not required, Circle-To-Land Minimums

SNS = A VOR procedure, using VORDME or VORTAC Navaid, the DME is not required for the procedure, the minimums are straight-in.

SDC = A VOR procedure, using VORDME or VORTAC Navaid, the with a DME required note for the procedure, the minimums are Circle-To-Land

D S = A VOR/DME procedure, using a VORDME or VORTAC Navaid, the DME is required for the procedure, the minimums are straight-in.

VNS = A VOR procedure using VOR Navaid with only NAVAID, no DME installed, minimums are straight-in.

VDC = A VOR procedure, using a VOR Navaid with a DME required note, the minimums are Circle-To-Land

N S = An NDB procedure, minimums are straight-in.

Q S = An NDB + DME procedure, the DME is required, the minimums are straight-in.

I_H = ILS procedure, no DME requirements, procedure is designed for Helicopter operations to a runway at an airport, records are contents in Airport Approach (PF) file section.

I_ _= ILS Procedure, no DME requirements, procedure is designed for Helicopter operations to a helipad at a heliport, records are contents in Heliport Approach (HF) file section.

## 5.8 Route Identifier (ROUTE IDENT)

Definition/Description: The Route Identifier field identifies a route of flight or traffic orientation, using the coding employed on aeronautical navigation charts and related publications.

Source/Content: For Enroute Airways, Route Identifier codes should be derived from official government publications. For Preferred Routes, Route Identifiers may or may not be provided in government publications. Where they are available, they will be used.

For North American Routes for North Atlantic Traffic, Common Portion and other similar route system, route identifier code shall be those published in government sources. For the European Traffic Orientation System or other similar route systems such as North American Routes for North Atlantic Traffic, Non-common Portion, Preferred Routes, and Preferential Routes published without official and/or flight plan identifiers, but published as between specific airports or other navigation fixes, route identifiers define the initial fix and the terminus fix idents according to the naming rules in Chapter 7. For routings which do not include a unique initial or terminus fix, rules on creating unique Route Identifiers are also contained in Chapter 7. Those rules have been developed with use of the Geographical Reference Tables (TG). Refer to Chapter 3, Section 3.2.7.2 and Chapter 4, Section 4.1.26 for more detail.

Used On:

Enroute Airway, Preferred Route Records and Geographical Reference Table

Length:

Enroute Airway - 5 characters maximum

Preferred Route - 10 characters maximum

Character Type:

Alpha/numeric

Examples:

Enroute Airway - V216, C1150, J380, UA16, UB414 Preferred Routes - N111B, TOS13, TOS14WK, CYYLCYYC, ARTCOLAR, KZTLKSAV, SCNDICANRY

Refer to Chapter 7 for specific examples and their meaning.

## 5.9 SID/STAR Route Identifier (SID/STAR IDENT)

Definition/Description: The SID/STAR Route Identifier field contains the name of the SID or STAR, using the basic indicator, validity indicator and route indicator abbreviated to six characters with the naming rules in Chapter 7 of this document.

Source/Content: SID/STAR route identifier codes should be derived from official government publications describing the terminal procedures structure.

Used On:

Airport SID/STAR, Heliport SID/STAR and Flight Planning

Arrival/Departure Data Records

Length:

6 characters max

Character Type:

Alpha/numeric

Examples:

DEPU2, SCK4, TRP7, 41M3, MONTH6

## 5.10 Approach Route Identifier (APPROACH IDENT)

Definition/Description: The Approach Route Identifier field contains the identifier of the approach route to be flown. To facilitate the provision of multiple approach procedures of the same type to a given runway, the field also is used to provide a multiple indicator.

Source/Content:

Table 5-10 - Runway Dependent Procedure Ident

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

Table 5-10 - Runway Dependent Procedure Ident

Table 5-11 - Circle-to-Land Procedures Identifier

| Column   | Contents                                                                                   |
|----------|--------------------------------------------------------------------------------------------|
| 1-3      | Circling Procedure Ident (See below).                                                      |
| 4        | A thru Z or 1 thru 9 A government source provided procedure suffix or a multiple indicator |
| 5-6      | Blank                                                                                      |

Table 5-11 - Circle-to-Land Procedures Identifier

Table 5-12 - Circle-to-Land Route Type Identifier

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

Table 5-12 - Circle-to-Land Route Type Identifier

Table 5-13 - Helicopter Approach Procedures to Runways or Final Approach Course Procedure Identifier

| Column   | Contents                                                                                                                        |
|----------|---------------------------------------------------------------------------------------------------------------------------------|
| 1        | Type of Approach-Alpha Character, the same as the field 5.7 Route Type.                                                         |
| 2-4      | Three-digit numeric character representing the runway designation or procedure final approach course, expressed in full degrees |
| 5        | Multiple Indicator Alphanumeric or Blank                                                                                        |
| 6        | Blank                                                                                                                           |

Table 5-13 - Helicopter Approach Procedures to Runways or Final Approach Course Procedure Identifier

## 5.10-x77 Table 5-14 - Helicopter Approach Procedures to Heliports and Coded to a Specific Pad Identifier

| Column   | Contents                                                                |
|----------|-------------------------------------------------------------------------|
| 1        | Type of Approach-Alpha Character, the same as the field 5.7 Route Type. |
| 2-6      | Pad Identification                                                      |

Used On:

Airport and Heliport Approach Route Records, Flight Planning Arrival/Departure Data, Airport and Helicopter Operations, SBAS Path Point, GBAS Path Point, and Airport, Heliport Localizer, Airport and Heliport TAA, and Simulation Continuation Records.

Length:

6 characters max.

Character Type:

Alpha/numeric

Examples:

Runway

Dependent

I26L, B08R, R29, V01L, N35 L16RA, L16RB, V08-A, V08-B I18L1, I18L2, R35-Y, R35-Z

Circle-To-Land or

Point in Space

VOR, VDM, LOC

VORA, VORB, NDB1, NDB2 (These are multiple indicators)

NDBB, VDMA, LOCD, BI, P168, NDAT (These are source

provided procedure suffixes)

Helicopter to

Runway

I13L, L040, V175, N175B

Helicopter to

Helipad

IA127 = ILS Procedure to a pad designated A127

VBRAVO =VOR Procedure to a Pad designated BRAVO N23 =NDB Procedure to a Pad designated 23 RWESTA RNAV Procedure to a Pad designated West Alpha

## 5.11 Transition Identifier (TRANS IDENT)

Definition/Description: The Transition Identifier field describes the type of transition to be made from the enroute environment into the terminal area and vice versa, and from the terminal area to the approach or from the runway or helipad to the terminal area.

Source Content: The content of the transition identifier field should be determined from the content of the Route Type field (See Section 5.7) in accordance with the rules set forth in Table 5-1 5 .

Table 5-15 - Transition Identifier Field Content

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

Table 5-15 - Transition Identifier Field Content

| Record               | Route Type                                       | Field Content                         |          |
|----------------------|--------------------------------------------------|---------------------------------------|----------|
|                      | 3                                                | Runway (RWY) or Pad Identifier        | (Note 2) |
| Approach Transitions | A                                                | Approach Transition Identifier        |          |
| Missed Approach      | Z                                                | Missed Approach Transition Identifier | (Note 4) |
| Approach Procedure   | All Other Codes Except A and Z (see Section 5.7) | Blank                                 |          |

Note 1: If there is no Route Type 1 for the SID, then the SID Records with the Route Type of 2 will have an entry in the Transition Identifier field. If there is a Route Type of 1 for the procedure, then the records with the Route Type of 2 will carry a blank transition identifier.

Note 2: If there is no Route Type 3 for the STAR, then the STAR record with the Route Type of 2 will have an entry in the Transition Identifier field. If there is a Route Type 3 for the procedure, then the Transition Identifier in the Route Type 2 will carry a blank transition identifier.

Note 3: The use of ALL in the Transition Identifier field indicates that the procedure is valid for all runways at an airport or all helipads at a heliport. If the procedure is not valid for all the runways at an airport or all the helipads at a heliport, individual runway transitions should be coded. In the coding of individual runway transitions, the use of the character B along with the runway designation, such as RW08B, indicates that a single runway transition has been coded for all available parallel runways. This can be RW08L and RW08R or RW08L, RW08C, and RW08R. If there are parallel runways and the single transition cannot be coded for all instances, individual runway transitions must be coded for each individual runway.

Note 4: It will be the identifier of the Missed Approach Holding Fix or the last fix in the missed approach procedure coding if there is no missed approach holding fix. In cases where there are multiple instances for a given approach procedure, the Missed Approach Transition Identifier will be modified according to the rules in Attachment 5 and Section 8 .6 of this specification.

Note 5: Enroute Transition Identifiers are normally the identifier of the navaid or waypoint.

Transition Identifiers should be derived from official government sources, where provided.

Used On:

Airport and Heliport SID/STAR/ Approach, Flight Planning Arrival/Departure Data and Company Route Records

Length:

5 characters max.

Character Type:

Alpha/numeric

Examples:

9TU, ETX, KEENE, DEN, RW08R, Blank

## 5.12 Sequence Number (SEQ NR)

Definition/Description: For Route Type Records - A route of flight is defined by a series of records taken in order. The Sequence Number field defines the location of the record in the sequence defining the route of flight identified in the route identifier field. For Boundary Type Records - A boundary is defined by a series of records taken in order. The Sequence Number field defines the location of the record in the sequence defining a boundary. For Record Types requiring more than one primary record to define the complete content - In a series of records used to define a complete condition, the Sequence Number is used to define each primary record in the sequence. For Airport and Heliport TAA Records - Sequence Number 1 will always be assigned to the record based on the Center Fix upon which the StraightIn Area is predicated, Sequence Number 2 will always be assigned to the record based on the Center Fix upon which the Left Base Area is predicated, and Sequence Number 3 will always be assigned to the record based on the Center Fix upon which the Right Base Area is predicated. Therefore, if a TAA Record has a Straight-In Area and a Right Base Area, but no Left Base Area, only Sequence Numbers 1 and 3 will be used. If a TAA Record has a Straight-In Area and a Left Base Area but no Right Base Area, only Sequence Numbers 1 and 2 will be used.

Source/Content: Sequence numbers are assigned during the route, boundary or sequence definition phase of the data file assembly. Sequence numbers are assigned so as not to be duplicated within the route, boundary or sequence assigned a unique identification/designation. For three or four-digit Sequence Numbers, initially, an increment of ten should be maintained between the sequence numbers assigned to consecutive records. For one or two-digit Sequence Numbers, the initial increment is one. In route or boundary records, should subsequent maintenance of the file necessitate the addition of a record or records, the new record(s) should be located in the correct position in the sequence and assigned a sequence number whose most significant characters are identical to those in the sequence number of the preceding record in sequence. The unit character should be assigned a value midway between the units character values of the preceding and following record sequence numbers. For example, if it is desired to add one record to the sequence and the units characters of both the preceding and following records at the desired location are zeros (indicating no previous modification at this point), the units character or the inserted record's sequence number should be five (5). For records taken in sequence with one or two-digit sequence numbers, additional data must be entered in the proper sequence and all subsequent records will be up numbered accordingly.

When an enroute airway crosses the boundary separating two geographical areas (Section 5.3), the airway fix lying on or closest to the boundary shall be coded twice, once for each geographical area, and should be assigned the same sequence number in each case. Record uniqueness in such cases is maintained through the Boundary Code (Section 5.18). Enroute airway record sequence numbers should be assigned in a manner which permits them to be arranged into continuous airway routes in flight sequence order when sorted according to the Route Identifier and Sequence Number only, without regard to their applicable Geographical Area Code.

When used on Enroute, Airport and Heliport Communications Primary and Continuation records, the Sequence Number is used as a record counter within a given Identifier and Communications Class for providing output file record uniqueness.

Used On:

Enroute Airways, Airport and Heliport MSA Records, Airport and Heliport TAA Records , Airport and Heliport SID/STAR/Approach, Company Route, Cruise Tables, FIR/UIR, Restrictive Airspace, Controlled Airspace, Preferred Routes, Flight Planning Arrival/Departure Data and VHF Navaid Limitation Continuation Records, Helicopter Operations Company Routes, TACAN-Only NAVAID Limitation

Continuation Record

Length:

4 characters - Enroute Airways, Preferred Routes, FIR/UIR, and Restrictive Airspace

3 characters - SID/STAR/Approach and Company Routes

2 characters - VHF Navaid Limitation Continuation Records and

TACAN-Only NAVAID Limitation Continuation Record

1 character - MSA Table, TAA Table , Cruise Table Numeric

Character Type: Examples:

0010, 0135, 2076, 120, 030, 01, 84, 3

## 5.13 Fix Identifier (FIX IDENT)

Definition/Description: The Fix Identifier field contains the five-character-name-code, or other series of characters, with which the fix is identified. This includes Waypoint Identifiers, VHF NAVAID Identifiers, NDB NAVAID identifier, Airport Identifiers, and Runway Identifiers.

Source/Content: Officially published identifiers or identifiers derived in accordance with Chapter 7, Naming Conventions, of this document.

Used On:

Holding Patterns, Enroute Airways, Airport and Heliport SID/STAR/Approach, Enroute Airway Restrictions, and Enroute Waypoints, Airport and Heliport Terminal Waypoints (Waypoint Ident) and Flight Planning Arrival/Departure Data Records.

Length:

5 characters max

Character Type:

Alpha/numeric (no embedded blanks)

Examples:

SHARP, DEN43, BHM, RW27L, KGRR

## 5.14 ICAO Code (ICAO CODE)

Definition/Description: The ICAO Code field permits records to be categorized geographically within the limits of the categorization performed by the Area Code field.

Source/Content: The code is to be employed in the ICAO code field may be found in ICAO Document No. 7910, Location Indicators.

In order to permit sub-division of the United States into more easily manageable regions, the ICAO code for the USA (K) is followed by a numeric character obtained from Figure 5-2.

Used On:

All records except Cruising Tables and Grid MORA

Length:

2 characters max

Character Type:

Alpha/numeric

Examples:

K1, K7, PA, MM, EG, UT

## 5.16 Continuation Record Number (CONT NR)

Definition/Description: When it is not possible to store all the information needed on a record within the 132 columns of the record itself, the so-called Primary Record; one or more continuation records may be used. The Continuation Record Number identifies the position of a continuation record in a sequence of such records.

Source/Content: Primary records contain the numeric 0 when no Continuation Records are included in the file for that Primary. The numeric 1 in this field of the Primary Record indicates that one or more Continuation Records follow the Primary Record. Continuation Records are numbered sequentially starting with the numeric 2 in the first continuation. If the information requirement goes beyond a Continuation Record with the numeric 9, the sequence is continued with alpha characters, starting with A and continuing through to Z as required.

Used On:

All records except Company Route,

Airport Localizer Marker/Locator,

Enroute Markers, Cruising Tables,

FIR/UIR and Grid MORA

Length:

1 character

Character Type:

Alpha/numeric

Examples:

0, 1, 2 (through 9) A, B, C (through Z)

## 5.17 Waypoint Description Code (DESC CODE)

Definition/Description: The Waypoint Description field facilitates the designation of the type, function, and attributes of a specific waypoint in Enroute Airway or Terminal Procedure segment coding.

Source/Content: Valid contents for the Waypoint Description Code are contained in the following table:

Table 5-16 - Waypoint Description

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

Table 5-16 - Waypoint Description

Generic Note:

There is a Waypoint Description field for each coding segment of an Enroute Airway or Terminal Procedure. For Enroute Airways, Column 40 will never be blank. For Terminal Procedures, Column 40 may be blank when the path terminator for that segment does not reference a fix. For details on path terminators and more information on sequence coding, refer to Attachments 5.

Note 1:   For a definition of the waypoint type, function or attributes, refer to Section Two, Special Navigation Terms, of this specification.

Note 2: The basic method of indicating that the government source has designated a specific fix as an Overfly Waypoint, meaning the fix must be overflown before commencing the maneuver defined in the subsequent leg, is to code a Y in Column 41. End of Continuous Segment indications are not source provided data, but rather an implementation of the translation of that source data based on this specification.

Column 41 End of Continuous indications of E will be provided in the last segment of an individual Terminal Procedure Transition and at the end of a specific airway. The indication is also provided in airway coding when the basic route designation continues beyond the fix, but there is a gap in the route definition. And the indication is provided in airway coding when there is a change in ARINC Area Code (Section 5.3) in the subsequent leg. In Terminal Procedure coding, when both conditions exist, i.e., the fix has been designated as an Overfly Waypoint and the End of Continuous Segment indication is required by the rules in this specification, Column 41 is set to B.

Note 3:   The First Leg of Missed indication, M in column 42 is coded on the first leg of approach procedure coding that follows the designation of the Missed Approach Point (MAP) in Column 43.

Note 4: Step-down fix on the final approach coding indicating a segment course change that is greater than or equal to one degree different than the next leg. All RF non-procedure fixes on the final approach coding meet this requirement. This code will take precedence over a step-down fix code at the same fix.

Notes 5: An N in column 43 of an engine out SID or missed approach record designates the waypoint as the engine out SID (or missed approach) disarm point. For example if an engine failure is detected before this point, the engine out procedure is automatically loaded. If the engine failure is detected after this point, the engine out SID is not automatically loaded.

Note 6: The column 40 value of A or H will only be used on SIDs when it is a Vector SID which consists of Enroute Transitions only (Attachment 5, Rule 4.11). The Column 40 value of A or H will only be used on STARs when the STAR ends in vectors to a final approach (Attachment 5, Rule 5.1).

Note 7: The Initial Departure Fix indication, P in column 43, is coded for the first published fix/waypoint of an RNAV departure.

Used On

Airport and Heliport SID/STAR/Approach, Enroute Airway Records 4 Characters

Length:

Character Type:

Alpha

Figure 5-2 - 7 Subdivisions for United States

## 5.18 Boundary Code (BDY CODE)

Definition/Description: Routes of flight frequently cross geographical boundaries. The Boundary Code field identifies the area into, or from which a continuous route passes when such a crossing occurs.

Source/Content: See Table 5-1

7 .

Used On:

Enroute Airways records

Length:

1 character

Character Type:

Alpha/numeric

Table 5-17 - Boundary Codes

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

Table 5-17 - Boundary Codes

New section was added.

## 5.19 Level (LEVEL)

Definition/Description: The Level field defines the airway structure of which the record is an element.

Source/Content:

B All Altitudes

H High level Airways

L Low Level Airways

Used On:

Enroute Airway, Preferred Routes, Restrictive Airspace, and Controlled Airspace records

Length:

1 character

Character Type:

Alpha

## 5.20 Turn Direction (TURN DIR)

Definition/Description: The Turn Direction field specifies the direction in which Terminal Procedure turns are to be made. It is also used to indicate direction on course reversals, see Attachment 5 Path and Termination.

Source/Content: The field contains the alpha character L for Left turns, R for Right turns, and E for turns in either direction.

Used On:

Airport and Heliport SID/STAR/Approach records

Length:

1 character

Character Type:

Alpha

## 5.21 Path and Termination (PATH TERM)

Definition/Description: The Path and Termination defines the path geometry for a single record of an ATC terminal procedure.

Source/Content: Attachment 5 to this document, Path and Terminator, contains the various Path Term codes available for coding an ATC terminal procedure.

Used On:

Airport and Heliport SID/STAR/Approach records

Length:

2 characters

Character Type:

Alpha

## 5.22 Turn Direction Valid (TDV)

Definition/Description: This field is used in conjunction with Turn direction to indicate that a turn is required prior to capturing the path defined in a terminal procedure.

Source/Content: The field contains the alpha character Y when a turn is required prior to beginning the leg defined by the Path Term. The direction of the turn is specified in Section 5.20.

Used On:

Airport and Heliport SID/STAR/Approach Records

Length:

1 character

Character Type:

Alpha

## 5.23 Recommended NAVAID (RECD NAV)

Definition/Description: The Recommended Navaid field allows the reference facility for the waypoint in a given record Fix Ident field or for an Airport or Heliport to be

specified. VHF, NDB (Enroute and Terminal), Localizer, TACAN, GLS, and MLS Navaids may be referenced.

Source/Content: The 1, 2, 3, or 4-character identification of the Navaid appears in this field. Navaids recommended for waypoint reference in official government publications will be used when available. The following general rules on field content apply:

Procedures that use coding which require leg types referenced to specific navaids are covered by the procedure coding rules in Attachment 5 to this specification.

A VHF Navaid may be any VOR, DME, VORDME, VORTAC, TACAN, Un-Biased ILSDME or MLSDME available in the database following the specific rules in Table 5 -18 .

An NDB Navaid may be any NDB or Locator available in the Enroute or Terminal NDB files in the database.

Localizers and MLS Azimuth are used as Recommended Navaids for procedures that reference those navaids, including RNAV Transitions to these types of procedures.

The Recommended Navaid in final approach coding will be the procedure reference facility. As not all Final Approach Procedure reference a Navaid, i.e., RNAV and GPS, the Recommended Navaid is not provided in these types of procedure, see Attachment 5 for specific rules.

The Recommended Navaid in Airport and Heliport Records will be any VOR, VORDME, or VORTAC available in the database.

The Recommended Navaid in any Enroute Airway Record, when provided, will be any VORDME or VORTAC available in the database.

The Recommended Navaid in any Terminal Procedure Record other than the final approach coding will be the procedure reference facility of a type from the Definition/Description paragraph above and will be in accordance with the rules governing Recommended Navaids for Path Terminators and coding rule as defined in Attachment 5 of this specification.

The rules for Recommended Navaids for Converging ILS Approach Procedures are the same as for ILS Approach Procedures.

The Recommended Navaid used in a GLS Approach Procedure will be the GLS Reference Path identifier appropriate to the runway and approach.

The use of non-collocated facilities of the types VORDME, VORTAC, and Localizer/ILSDME or ILSTACAN as the recommended navaid in terminal procedure coding is limited to defined circumstances only. For a definition of non-collocated, refer to Section 5.35 of this specification. For the defined circumstances, refer to Table 5-1 8 of this specification.

Used On:

Enroute Airway Record, Airport and Heliport SID/STAR/Approach Records, Airport and Heliport Record

Length:

4 characters max.

Character Type:

Alpha/numeric

Examples:

P, PP, DEN, LAX, ILAX, MJFK

## 5.23-x78 Table 5-18 - Procedure Use

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

1 On FACF and FAF Records

2 On Runway/MAP Records Only

3 ILSDMEs and ILSTACANs must be unbiased for use as a recommended navaid. They do not have to be collocated with the frequency paired localizer for use as a recommended navaid in the instances allowed.

## 5.24 Theta (THETA)

Definition/Description: Theta is defined as the magnetic bearing to the waypoint identified in the record's FIX Ident field from the Navaid in the Recommended Navaid field.

Source/Content: Theta values are derived from official government sources when available. They are provided in degrees and tenths of a degree, with the decimal point suppressed. The content is controlled through requirements of the Path Terminator and coding rules contained in Attachment 5 of this specification.

Used On:

Airport and Heliport SID/STAR/Approach, Enroute Airway Records 4 characters

Length:

Character Type:

Alpha/numeric

Examples:

0000, 0756, 1217, 1800

## 5.25 Rho (RHO)

Definition/Description: RHO is defined as the geodesic distance in nautical miles to the waypoint identified in the record's Fix Ident field from the NAVAID in the Recommended NAVAID field.

Source/Content: Rho values derived from official government sources will be used when available. They are entered into the field in nautical miles and tenths of a nautical mile, with the decimal point suppressed. The content is controlled through requirements of the Path Terminator and coding rules contained in Attachment 5 of this specification.

Used On:

Airport and Heliport SID/STAR/Approach, Enroute Airway Records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

0000, 0216, 0142, 1074

## 5.26 Outbound Magnetic Course (OB MAG CRS)

Definition/Description: Outbound Magnetic Course is the published outbound magnetic course from the waypoint identified in the record's Fix Ident field. In addition, this field is used for Course/Heading/Radials on SID/STAR Approach Records through requirements of the Path Terminator and coding rules contained in Attachment 5 of this specification.

Source/Content: Values from official government sources will be used when available. The field contains magnetic information expressed in degrees and tenths of a degree, with the decimal point suppressed. For route and procedure segments published in degrees true, the last character (tenths position) of the field will contain the character T. See Section 5.165 of this document for more information on degrees true information.

Used On:

Airport and Heliport SID/STAR/Approach, Enroute Airway and

Flight Planning Arrival/ Departure Data Records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

2760, 0231, 194T

## 5.27 Route Distance From, Holding Distance/Time (RTE DIST FROM, HOLD DIST/TIME)

Definition/Description: An expression of the length of the path defined in the record in either distance in nautical miles or time in minutes.

In Enroute Airways, Route Distance From will contain the distance from the waypoint identified in the records' Fix Ident field to the next waypoint in the route.

In SID, STAR, and Approach Procedure Records, the field will contain one of the following: segment distance, along track distance, excursion distance, DME distance, holding pattern leg distance, or time. The actual content is dependent on the Path and Termination. For more information on the content, refer to Table Three, Leg Data Fields, in Attachment 5 of this document.

Source/Content: The field contains distances or time, from official government source where available. Distances are expressed in nautical miles and tenths of with

the decimal point suppressed. When the expression is time, the first character in the field will be 'T,' followed by the minutes and tenths of minutes with the decimal point suppressed. For data in Holding Pattern Records, refer to Section 5.64 or 5.65 of this specification.

Used On:

Airport and Heliport SID/STAR/Approach, Enroute Airway Records

Length:

4 characters

Character Type:

Distance - Numeric;

Time - Alpha/numeric

Examples:

1076, 2822, T010, 0208, 0016

## 5.28 Inbound Magnetic Course (IB MAG CRS)

Definition/Description: Inbound Magnetic Course is the published inbound magnetic course to the waypoint in the Fix Ident field of the records in which it is employed.

The HX group of Path Terminator codes is used to provide racetrack type course reversal flight paths. Government publications for these course reversals include an inbound magnetic bearing. The SID/STAR/Approach Procedures records do not include a dedicated field for this inbound course. Instead, the information is included in the Outbound Magnetic Course field of such records.

Source/Content: Values from official government sources will be used when available. The field contains magnetic bearing in degrees and tenths of a degree, with the decimal point suppressed. For routes published with true courses, the last character of this field will contain a T in place of tenths of a degree.

Used On:

Enroute Airways records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

2760, 0231, 194T

## 5.29 Altitude Description (ALT DESC)

Definition/Description: The Altitude Description field will designate whether a waypoint should be crossed at, at or above, at or below or at or above to at or below specified altitudes. The field is also used to designate recommended altitudes and cases where two distinct altitudes are provided at a single fix.

Source/Content: A code from the following table, selected based on official government source or coding rules in Attachment 5 to this document.

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

Note:

The B entry may appear on any record type that includes altitude and altitude description data. The higher value will always appear first in the records with two altitudes or as the first three digits of the Altitude Limitation field. When used on approach, the B entry may not be used on the missed approach point or final end point.

Note:

The C or D entry is used to indicate that the leg has a conditional altitude termination, meaning the leg ends as specified in the Path and Terminator or at the altitude specified, under the condition indicated. These codes are limited to SID and Missed Approach Coding as the potential for an altitude termination exists and such a termination is only valid for ascending terminal procedure segments. See Attachment 5 of this specification.

Note:

The O entry may only be coded on HF Path Terminator. It is used in these cases where an altitude is specified at the outbound position of a racetrack procedure that is different than the altitude specified at the HF fix.

Used On:

Airport and Heliport SID/STAR/Approach, Primary and Continuation Records, Airport, Heliport and Enroute Communications, VHF NAVAID Limitation Continuation, Preferred Routes and Flight Planning Arrival/Departure Data Records, TACAN-Only NAVAID Limitation Continuation Record.

Length:

1 character

Character Type:

Alpha

Deleted Field Content V, X, Y, and the associated Note.

## 5.30 Altitude/Minimum Altitude

Definition/Description: The Altitude/Minimum Altitude field indicates the reference altitude associated with (1) Enroute Airways (MEA, MFA or other minimum altitudes as defined by source), (2) holding pattern path of Holding Pattern record, (3) altitudes at fixes in terminal procedures and terminal procedure path termination defined by the Path Terminator in the Airport or Heliport SID/STAR/Approach Record and (4) lowest altitude of the blocked altitudes for a Preferred Route.

Source/Content: Reference altitudes are determined during route definition. The values are derived from official government source when available. This specification includes specific rules for altitude provision and when those altitudes are not provided by source documents, they will be included by data suppliers according to those rules. The field may contain altitudes (all numeric) or flight level (alpha/numeric). The all-numeric fields will contain altitudes in feet with a resolution of one foot. The alpha/numeric fields will contain the alpha characters FL followed

by the altitude expressed in hundreds of feet (three digits) or a code as indicated below.

On Airport and Heliport SID, STAR, and Approach Route records, the first Altitude field will contain an altitude when Altitude Description field contains a plus (+), a minus (-), or one of the following characters: B or G. The second Altitude field will contain an altitude when the Altitude Description field contains one of the following characters: B, C, D, or G. In approach procedure coding, some fix Altitudes may be below sea level, in the case of altitudes at runway fixes when the runway threshold elevation is below sea level. In these cases, the Altitude will be expressed in feet with a minus (-) sign in the first character of the five-character field, see examples.

On Enroute Airway records, the first Minimum Altitude field will contain the MEA or MFA if the altitude is the same for both directions of flight and the second minimum Altitude will be blank. If the airway segment has directional MEAs/MFAs, the first Minimum Altitude field will contain the value for the direction of flight in which the airway is coded and the second Minimum Altitude field will contain the value for the opposite route coding. When the official government authority provides different MEA/MFA values for a given airway segment that are based on the navigation sensor, e.g., Convention and RNAV, the MEA/MFA provided will be that value appropriate to the Route Type (Section 5.7) coded in that segment. The first Minimum Altitude field may contain the alpha characters UNKNN when the MEA/MFA is unknown or the alpha characters NESTB when the MEA/MFA has not been established by the appropriate authority.

On Preferred Routes, the Minimum Altitude and the Maximum Altitude apply to the entire route and is a minimum and maximum block. Altitude 1 and Altitude 2 are fix related apply only to the fix in the sequence in which they occur and are defined by the Altitude Description field.

Used On:

Airport and Heliport

SID/STAR/Approach, Primary and Continuation Records , Holding Pattern, Enroute Airway, Preferred Routes.

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

05000, FL050, 18000, FL180, 00600, -0012, 29000, FL290, UNKNN or NESTB (the last two on Enroute Airways only)

Removed the reference Field Content V.

## 5.31 File Record Number (FRN)

Definition/Description: The File Record Number is a reference number assigned to the record for housekeeping purposes. Records are numbered consecutively, the first record on the file being assigned the number 00001, the second the number 00002, and so on through the final record on the file. File record numbers are subject to change at each file update.

Source/Content: File record numbers are assigned to records during the assembly of the data file. If the file reaches 99999, the next record number will start over with 00000.

Used On:

All records

Length:

5 characters

Character Type:

Numeric

Examples:

10640, 00420, 31462

## 5.32 Cycle Date (CYCLE)

Definition/Description: The Cycle Date field identifies the calendar period in which the record was added to the file or last revised. A change in any ARINC 424 field, except Dynamic Magnetic Variation, Frequency Protection, Continuation Record Number, and File Record Number, requires a cycle date change. The cycle date will not change if there is no change in the data.

Source/Content: The first two digits of the field contain the last two digits of the year in which the addition or revision was made. The last two digits contain the numeric identity of the 28-day data update cycle during which the change occurred. Each calendar year contains 13 such cycles; however, on rare occasions 14 cycles will be encountered.

Used On:

All records

Length:

4 characters

Character Type:

Numeric

## 5.33 VOR/NDB Identifier (VOR IDENT/NDB IDENT)

Definition/Description: The VOR/NDB Identifier field identifies the VHF/MF/LF facility defined in the record.

Source/Content: When used on VHF NAVAIDs, NDB NAVAIDs, Airport Localizer Marker Records, the field contains the official government 1, 2, 3, and 4-character navigation facility identification codes. When used on Airport and Heliport Localizer, and Airport and Heliport MLS Records, the field contains the official 1, 2, 3, or 4character navigation facility identifier of any DME or TACAN Navaid contained in the data file, including ILSDMEs, MLSDME/N, and MLSDME/P facilities as long as they are at the same airport.

Used On:

VHF NAVAIDs, NDB NAVAIDs, Airport Localizer Marker records, Airport and Heliport Localizer, and Airport and Heliport MLS records .

Length:

4 characters max

Character Type:

Alpha/numeric

Examples:

DEN, 6YA, PPI, TIKX

## 5.34 VOR/NDB Frequency (VOR/NDB FREQ)

Definition/Description: The VOR/NDB Frequency field specifies the frequency of the NAVAID identified in the VOR/NDB Identifier field of the record.

Source/Content: Frequencies are derived from official government sources. VHF NAVAID frequencies contain characters for hundreds, tens, units, tenths and hundredths of megahertz. NDB frequencies contain characters for thousands, hundreds, tens, units and tenths of kilohertz. The decimal point following the unit entry is suppressed in both cases.

Used On:

VHF NAVAID, NDB NAVAID, Airport Localizer Marker records

Length:

5 characters

Character Type:

Numeric

Examples:

VHF 11630, 11795 NDB 03620, 17040

## 5.35 NAVAID Class (CLASS)

Definition/Description: The Navaid Class field provides information in coded format on the type of navaid, the coverage of the navaid, information carried on the navaid signal and collocation of navaids in both an electronic and aeronautical sense. The field is made up of five columns of codes that define this information.

Source/Content: The information for the five columns is transformed from official government source. The mapping of the information codes to the output record columns for the various types of navaids is contained in the tables in this section.

Used On:

Navaid Records (VHF, NDB and Airport/Heliport

Localizer/Markers/Locators)

Length:

5 characters (including blanks)

Character Type:

Alpha

VHF Navaid Record - Includes VOR, VORDME, VORTAC, TACAN, ILSDME, and MLSDME type navaids, Output Record Section/Subsection D

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

### 5.35-x79-x80 Airport/Heliport Localizer Marker/Locator Record -NDB Locator and Marker Navaids, Output Record Section/Subsection PM

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

**Note 1:**

Collocations:

For VHF Navaid records, the character N in column 32 is entered if either the latitude and/or the longitude of the VOR and the Collocated DME or TACAN of a frequency paired VORDME or VORTAC differ by 1/10 arc minutes or more. Column 32 is blank on VHF Navaids where the difference in latitude or longitude is less than the 1/10-arc minutes. Column 32 of the VHF Navaid will also carry the N or blank meaning listed above for frequency paired ILSDMEs and ILSTACANs. Note that in this later case, the character is carried on the ILSDME or ILSTACAN record as the Localizer record is not part of the VHF Navaid Section.

For Airport/Heliport Localizer Marker/Locator records, the character N in column 79 is entered if either the latitude or longitude of a Marker and it aeronautically associated Locator differ by 1/10-arc minutes or more. The character A in column 79 is entered if the latitude or longitude of a Marker and its aeronautically associated Locator differ by less than 1/10-arc minutes. Column 79 is left blank when the latitude and longitude of the Marker and Locator are exactly the same.

Note 2:

Airport/Heliport Localizer Marker/Locator Navaids, Operations/Collocation. Should both a collocation and a BFO operations requirement exist for one and the same Navaid Record, preference is given to the collocation characters.

## 5.36 Latitude (LATITUDE)

Definition/Description: The Latitude field contains the latitude of the navigational feature identified in the record.

Source/Content: Geographic positions whose latitudes must be included in the database are defined during route design, many of them in official government publications. The field is constructed as follows. The first character position contains the alpha character N or S indicating whether the latitude is north or south of the equator. N is entered for latitudes falling on the equator. The following eight numeric characters define the latitude in degrees, minutes, seconds, tenths of seconds and hundredths of seconds. Degree, minute and second symbols and the decimal point are suppressed.

Note:

Some RNAV system users may elect to round off latitude values to resolutions of less than one hundredth of a second prior to the entry of these data into the airborne computer.

The navigation reference points to be defined by latitude and longitude coordinates are listed in Table 5-1 9 .

Used On:

NAVAID, Waypoint, Airport Heliport, Airport and Heliport ILS, Airport, Gate, Runway, Airport and Heliport Localizer Marker, Airport and Heliport MLS and GLS, Airport and Heliport MLS Continuation, Airway Marker, Airport and Heliport Communications, Enroute Communications, Heliport, Airport and Heliport Helipads, Restrictive Airspace, FIR/UIR, Controlled Airspace, Path Point and GLS Records.

Length:

9 characters

Character Type:

Alpha/numeric

Examples:

N39513881

## 5.37 Longitude (LONGITUDE)

Definition/Description: The Longitude field contains the longitude of the geographic position of the navigational feature identified in the record.

Source/Content: Geographic positions whose longitudes must be included in the database are defined during route design, many of them in official government publications. The field is constructed as follows: The first character position will contain the alpha character E or W, indicating whether the longitude is east or west of the prime (zero degree) meridian. For longitudes falling on the 0 or 180-degree meridians, E is entered. The following nine numeric characters define the longitude in degrees, minutes, seconds, tenths of seconds and hundredths of seconds. Degree, minute and second symbols, and the decimal point are suppressed.

Note:

Some RNAV system users may elect to round off longitude values to resolutions of less than one hundredth of a second prior to the entry of these data into the airborne computer.

The navigation reference points to be defined by latitude and longitude coordinates are listed in Table 5-1 9 .

Used On:

NAVAID, Waypoint, Airport, Heliport, Airport and Heliport ILS, Airport Gate, Runway, Helipad, Airport and Heliport Localizer Marker, Airport and Heliport MLS, GLS Airports and Heliport MLS Continuation, Airway Marker, Airport and Heliport Communications, Enroute Communications, Heliport, Airport and Heliport Helipads, Restrictive Airspace, FIR/UIR, Controlled Airspace, Path Point and GLS Records.

Length:

10 characters

Character Type:

Alpha/numeric

Examples:

W104450794

Table 5-19

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

Table 5-19

Note 1: The VOR latitude and longitude fields are filled when the NAVAID Class field contains the letter V in column 28 of the record. If column 28 is blank, these fields are blank also.

Note 2: The DME or TACAN latitude and longitude fields are filled when the NAVAID Class field contains the letters D, I, M, N, P or T in column 29 of the record. If column 29 is blank, these fields are blank also.

Note 3: The MLS Back Azimuth latitude and longitude fields are to be left blank where no such facility exists.

Note 4: MLS Datum is the point on the runway center line closest to the phase center of the approach elevation antenna.

Note 5: The Runway latitude and longitude fields define the Runway Landing Threshold. This threshold can be the beginning of the landing runway pavement. It will be the displaced threshold (inward from the beginning of the landing runway pavement) when such is published by official government documentation.

Note 6: Localizer Glideslope latitude and longitude may be blank when detail is not available through source documentation.

Note 7: On Airport and Heliport Communications Records, the Latitude/Longitude defines the physical location of the transmitting antenna when this is provided in official government source. This may be a navaid or independent transmitter location. In cases where the physical location of the transmitting antenna is not provided in source, the Latitude/Longitude of the Aerodrome Reference Point will be provided. When the Latitude/Longitude provided are those of a navaid or the ARP, the content of the Remote Facility (5.200) will provide an indication of the reference made. In cases where the communications record is defining a digital service capability, the latitude/longitude will be blank.

Note 8: On Enroute Communications Records, the Latitude/Longitude defines the physical location of the transmitting antenna when this is provided in official government source. This may be a navaid or independent transmitter location. In cases where the physical location of the transmitting antenna is not provided in source but it is known to be at a specific airport, the Latitude/Longitude of the Aerodrome Reference Point will be provided. When the Latitude/Longitude provided are those of a navaid or the ARP, the content of the Remote Facility (5.200) will provide an indication of the reference made. In cases where the physical location of the transmitter is provided in source but the service/frequency contained in the record is assigned to a specific Enroute Communications Sector, the Latitude/Longitude defines the geographical center of that sector and not the physical transmitter location. In cases where none of the information defined above can be derived from official government sources, the Latitude/Longitude fields will be left blank to indicate the unknown position information. In these cases, the Position Narrative field will contain any such information available in the government sources. In cases where the communications record is defining a digital service capability, the latitude/longitude will be blank.

Note 9: The Helipad latitude and longitude fields are filled when the reference point or defining geographic coordinates of a particular helipad are provided by official government source. When no coordinates are provided, the field will be populated with the latitude and longitude of the airport or heliport reference point.

## 5.38 DME Identifier (DME IDENT)

Definition/Description: The identification of a DME facility, a TACAN facility or the DME (or TACAN) component of a VORDME or VORTAC facility.

Source/Content: The DME Identifier field will contain the officially published 2-, 3-, or 4-character DME facility identifier. For VOR/DME and VORTAC facilities, if the identification codes of the VOR and DME components of the NAVAID defined in the record are the same, the field will be blank. If they are not the same, the VOR Identification will be as defined in Section 5.33 and the DME Identifier field will carry the identification of the DME component. The field is blank when the VHF Navaid facility in the reference record has no DME component. The field will always contain the DME Identifier for TACANs, DME Only NAVAIDS and Localizer or MLS DME facilities.

Used On:

VHF NAVAID records

Length:

4 characters max

Character Type:

Alpha/numeric

Examples:

MCR, DEN, IDVR, DN, (Blank)

## 5.39 Magnetic Variation (MAG VAR, D MAG VAR)

Definition/Description: The Magnetic Variation field specifies the angular difference between True North and Magnetic North at the location defined in the record. Dynamic Magnetic Variation is a computer model derived value and takes location and date into consideration. For the Station Declination used in some record types, refer to Section 5.66.

Source/Content: Magnetic variations are obtained from official government data sources and other geographical magnetic variation source. A number of different terms are used in government documentation that have specific connotations for the information provided by that government. The most common is Epoch Year Variation. In theory, this is a value determined by a government agency once every five years and published for general use. Along with Epoch Year Variation, some governments also publish an annual drift value. Data suppliers do not include annual drift derived figures in their databases but rather stay with the Epoch Year value. Another term encountered in source documentation is Magnetic Variation of Record. This is generally an Epoch Year value. The difference here is that the government authority has established the value as valid for everything associated with a given location. For example, if a Magnetic Variation of Record is established for an airport location, everything referenced to that airport will use the same value. This is of interest as it means that Terminal Procedure design is also based on that value. Obvious differences can occur between a database supplied, semi-static value, and a value derived dynamically, either by the airborne systems or supplier ground systems. Dynamic Magnetic Variation, contained in the VHF Navaid Simulation Continuation Record, TACAN-Only Navaid Simulation Continuation Record, and Enroute/Terminal

Waypoint Primary Records, is a computed, earth model derived figure, and is updated dynamically on a schedule established by the database supplier.

When used on Enroute, Airport, and Heliport Communication Records, the field contains the magnetic variation of the latitude/longitude position defined in the record. If that latitude/longitude represents the position of a navaid or airport (Table 5-1 9 and Notes 7 and 8 of Section 5.37) the value provided will be identical to magnetic variation provided in the referenced record. If the latitude/longitude represents a stand-alone communications transmitter, the field will contain a government source provided value or the derived Dynamic Magnetic Variation when no source information is provided. If the latitude/longitude fields of the record are blank, the magnetic variation field will also be blank.

Position one of the field contains an alpha character taken from the table below followed by the value of magnetic variation expressed in degrees and tenths of a degree, with the decimal point suppressed. When the first position is coded with the character T, the value provided in position 2 through 5 will be all zeros.

| Field Content   | Description                                                 |
|-----------------|-------------------------------------------------------------|
| E               | Magnetic variation is East of TRUE North                    |
| W               | Magnetic variation is West of TRUE North                    |
| T               | The element defined in the current record is provided TRUE. |

Used On:

Airport, NDB Navaid, Airport Localizer Marker, MLS, GLS, Airway Marker, Enroute/ Airport/ Heliport Communication, Heliport, Enroute Waypoint, Airport and Heliport Terminal Waypoint and GLS Primary Records and VHF Navaid Continuation Records.

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

E0140, E0000, T0000

## 5.40 DME Elevation (DME ELEV)

Definition/Description: The DME Elevation field defines the elevation of the DME component of the NAVAID described in the record.

Source/Content: DME elevations specified in official government publications are entered into this field in feet with respect to MSL. When the elevation is below MSL, the first column of the field contains a minus (-) sign.

Used On:

VHF NAVAID records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

00530, -0140

## 5.41 Region Code (REGN CODE)

Definition/Description: The Region Code permits the categorization of waypoints and holding patterns as either enroute or terminal area waypoints. In the latter case, the terminal area airport is identified in the field.

Source/Content: The field contains the alpha characters ENRT for enroute waypoints and airport identification code (Airport Ident) for terminal waypoints. In the holding pattern file, the content will match that of the holding fix, e.g., if the holding fix is an enroute waypoint or enroute Navaid, the content with be ENRT; if the holding fix is a terminal waypoint or terminal NDB, the content will be the airport identification.

Used On:

Waypoint and Holding Pattern records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

ENRT, KLAX, 9V9

## 5.42 Waypoint Type (TYPE)

Definition/Description: The Waypoint Type field identifies a number of data conditions.

The first is whether or not the waypoint has been published in an official government source or created during database coding of routes or procedures.

The second is whether or not the waypoint is an intersection and/or DME fix formed with reference to ground based navaids or is an RNAV Waypoint formed by the latitude and longitude.

The third is an indication of one or more functions assigned to that waypoint in terminal procedure coding.

The fourth is an indication of location of the waypoint with reference to airspace boundaries and/or grid lines.

The fifth is an indication of how ATC might be using the waypoint in operational clearances.

The sixth is an indication that the waypoint has been published for VFR use only.

Lastly, there is an indication of whether the waypoint is published for use in terminal procedure coding of a specific type, multiple types or not published at all.

## 5.42-x81 COMMENTARY

Users of this specification should be aware that this section is intended for use in applications that do not use airway and terminal procedure records and that there is partial duplication of the information between this section and Section 5.17.

Source/Content: Valid contents for Waypoint type are contained in the table below. Unless specifically prohibited, all combinations of data from the three columns are valid.

### 5.42-x81-x82 ARINC SPECIFICATION 424 - Page 164

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

Used On:

Enroute Waypoints, Airport and Heliport Terminal Waypoints.

Length:

3 characters

Character Type:

Alpha

Note 1:

Column 28 of the Enroute and Terminal Waypoint Types will always be blank when column 27 carries the N for NDB or Terminal NDB produced as Waypoints.

Note 2: Possible codes for column 29 are identical for both Enroute and Terminal Waypoints and are those carried in the third

portion of the table. Column 29 will always be blank when column 27 carries the N for NDB or Terminal NDB produced as Waypoints.

Note 3: When column 27 equals A for ARC Center Fix Waypoint, columns 28 and 29 will always be blank.

Note 4: The code V in column 27 for VFR Waypoints is not used in conjunction with any codes from column 28 and 29.

Note 5 Column 28 content of R used only in conjunction with column 27 set to C, R, or W.

Note 6: Off-Route Waypoints, Intersections, or DME fixes can be source provided or created by the data supplier to ensure referential integrity within a data file. The only specific meaning of the option is that the fix in not used on any route coded as part of the Enroute Airway File (ER Section).

Note 7: The coding option G for Source Provided Enroute Waypoint is in support of ADS-C and is intended to facilitate the application providing ADS-C Reports when and only when the waypoint has been established by the relevant ANSP. This permits the data supplier to create on-route fixes that are not published by the ANSP for referential integrity purposes such as the coding of Company Routes.

Note 8: The coding of option J for Required Off-Route Waypoint is in support of programs such as FRA in Europe .

## 5.43 Waypoint Name/Description (NAME/DESC)

Definition/Description: The Waypoint Name/Description field sets the unabbreviated name of a named waypoint or a definition of an unnamed waypoint.

Source/Content: The name of a named waypoint is spelled out in full. Definitions for unnamed waypoints are described in Chapter 7 of this specification.

Used On:

Enroute Waypoints, Airport and Heliport Terminal Waypoints.

Length:

25 characters max

Character Type:

Alpha/numeric

Examples:

FORT SMITH, LAX04026, LOS235/110, 6100N01234W (OCTA), OM RW26L ALTUR

## 5.44 Localizer/MLS/GLS Identifier (LOC, MLS, GLS IDENT)

Definition/Description: The Localizer/MLS/GLS Identifier field identifies the localizer, MLS facility or GLS Ref Path defined in the record.

Source/Content: The field contains the identification code of the Localizer or MLS facility or GLS Reference Path derived from official government sources.

Used On:

Localizer, Localizer Marker, MLS, MLS Continuation, and GLS

Record.

Length:

4 characters max

Character Type:

Alpha/numeric

Examples:

Localizer - IDEN, ISTX, IDU, PP MLS - MDEN, MSTX, MLAX GLS - LFBL, EGLC, KSAN

## 5.45 Localizer Frequency (FREQ)

Definition/Description: The Localizer Frequency field specifies the VHF frequency of the facility identified in the Localizer Identifier field.

Source/Content: The official government-source localizer frequency is entered into the field with a resolution of 50 kHz. The decimal point following the unit MHz entry is suppressed.

Used On:

Airport and Heliport ILS Localizer records

Length:

5 characters

Character Type:

Numeric

Examples:

11030, 11195

## 5.46 Runway Identifier (RUNWAY ID)

Definition/Description: The Runway Identifier field identifies the runways described in runway records and runways served by the ILS/MLS described in ILS/MLS records.

Source/Content: Runway identifiers are derived from official government sources and are shown in the following format:

The two letters RW are followed by two numeric, 01 thru 36, and may contain a fifth character designation of one of the following:

| C   | Center (Runway of three parallel runways)       |
|-----|-------------------------------------------------|
| L   | Left (Runway of two or three parallel runways)  |
| R   | Right (Runway of two or three parallel runways) |

Any other designations (suffixes), such as North, South, East, West, True, or STOL will not be included in the ARINC 424 database file.

Used On:

Airport and Heliport ILS and MLS, GLS Runway, Airport and Heliport Localizer Marker, Path Point, and GLS Records.

Length:

5 characters max

Character Type:

Alpha/numeric

Examples:

RW26L, RW08R, RW26C, RW05,

## 5.47 Localizer Bearing (LOC BRG)

Definition/Description: The Localizer Bearing field defines the magnetic bearing of the localizer course of the ILS facility/GLS approach described in the record.

Source/Content: Localizer courses, derived from official government sources, are entered into the field in degrees and tenths of a degree, with the decimal point suppressed. For localizer courses published with the intent to be used as true courses, the last character of this field will contain a T in place of tenths of a degree.

Used On:

ILS, GLS records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

2570, 0147, 2910, 347T

## 5.48 Localizer Position (LOC FR RW END) Azimuth/Back Azimuth Position (AZ/BAZ FR RW END)

Definition/Description: The Localizer/Azimuth Position field defines the location of the facility antenna relative to one end of the runway.

Source/Content: The field contains the official government source distance, in feet, from the antenna to the runway end. The resolution is one foot.

Used On:

ILS, MLS and MLS Continuation records

Length:

4 characters

Character Type:

Numeric

Examples:

0950, 1000

## 5.49 Localizer/Azimuth Position Reference (@, +, -)

Definition/Description: The Localizer/Azimuth Position Reference field indicates whether the antenna is situated beyond the stop end of the runway, ahead of or beyond the approach end of the runway. The Back-Azimuth Position Reference field indicates whether the antenna is situated ahead of the approach end of the runway, ahead of or beyond the stop end of the runway.

Source/Content: For Localizer and Azimuth positions the field is blank (@) when the antenna is situated beyond the stop end of the runway, it contains a plus (+) sign when the antenna is situated ahead of the approach end of the runway or a minus (-) sign when it is located off to one side of the runway. For Back Azimuth positions the field is blank (@) when the antenna is situated ahead of the approach end of the runway, it contains a plus (+) sign when the antenna is situated beyond the stop end of the runway or a minus (-) sign when it is located off to one side of the runway.

Used On:

ILS, MLS and MLS Continuation records

Length:

1 character

Character Type:

Alpha

## 5.50 Glideslope Position (GS FR RW THRES) Elevation Position (EL FR RW THRES)

Definition/Description: The Glideslope/Elevation Position field defines the location of the antenna with respect to the approach end of the runway.

Source/Content: The field contains four numeric characters indicating the distance in feet (to a resolution of one foot) from a line drawn at right angles to the runway at the antenna position to the threshold of the runway.

Used On:

ILS and MLS records

Length:

4 characters max

Character Type:

Numeric

Examples:

0980, 1417

## 5.51 Localizer Width (LOC WIDTH)

Definition/Description: The Localizer Width field specifies the localizer course width of the ILS facility defined in the record.

Source/Content: Localizer course widths from official government sources are entered into the field in degrees, tenths of a degree and hundredths of a degree with the decimal point suppressed.

Used On:

ILS records

Length:

4 characters

Character Type:

Numeric

Examples:

0500, 0400, 0350

## 5.52 Glideslope Angle (GS ANGLE) Minimum Elevation Angle (MIN ELEV ANGLE)

Definition/Description: The Glideslope Angle field defines the glideslope angle of an ILS facility/GLS approach. The Minimum Elevation Angle field defines the lowest elevation angle authorized for the MLS procedure.

Source/Content: Glideslope and Elevation angles from official government sources are entered into the fields in degrees, tenths of a degree and hundredths of a degree with the decimal point suppressed.

Used On:

ILS, GLS and MLS records

Length:

3 characters

Character Type:

Numeric

Example:

275, 300

## 5.53 Transition Altitude/Level (TRANS ALTITUDE/LEVEL)

Definition/Description: The Transition Altitude field defines the altitude in the vicinity of an airport or heliport at or below which the vertical position of an aircraft is controlled by reference to altitudes (MSL). The Transition Level field defines the lowest flight level available for use above the transition altitude. Aircraft descending through the transition layer will use altimeters set to local station pressure, while departing aircraft climbing through the layer will be using standard altimeter setting (QNE) of 29.92 inches of mercury, 1013.2 millibars, or 1013.2 hectopascals.

Source/Content: Transition Altitudes/Levels are derived from official government sources.

For STAR and Approach records, the field defines the level, expressed in feet, at which the altimeter barometric setting is changed from standard to local values for that particular procedure . For SID records, the field should contain the Transition Altitude expressed in feet , for that particular SID . The first leg of each Airport and Heliport SID procedure shall contain the appropriate transition altitude /level with a resolution of one foot. The first leg of each Airport and Heliport STAR/Approach procedure shall contain the appropriate transition level with a resolution of one foot. If the transition altitude /level is unknown , or assinged by ATC, the field will be blank in procedure records.

For Airport and Heliport records, the Transition Altitude and Transition Level should be entered into the appropriate fields, in feet with a resolution of one foot. If the Transition Altitude or Level is unknown, or assigned by ATC, the field on the airport/heliport record should be blank.

Used On:

Airport and Heliport SID/STAR/Approach, Airport and Heliport

Records

Length:

5 characters

Character Type:

Numeric

Examples:

05000, 23000, 18000

This section was revised to clarify that the Airport/Heliport value should be blank, not the procedures value.

## 5.54 Longest Runway (LONGEST RWY)

Definition/Description: The Longest Runway field permits airport to be classified on the basis of the longest operational hard-surface runway.

Source/Content: The longest runway will be derived from official government sources and entered in the field in hundreds of feet. This value will represent the longest hard-surfaced operational runway available without restriction at the airport. The value reflects overall pavement length declared suitable and available for the ground operations of aircraft. Where no hard-surfaced runway is available or those available do not meet criteria, the value will represent the longest operational runway at the airport.

Used On:

Airport Records

Length:

3 characters

Character Type:

Numeric

Examples:

040, 055, 098, 111

## 5.55 Airport/Heliport Elevation (ELEV)

Definition/Description: The elevation of the Airport/Heliport specified in the record is defined in the Airport Elevation and Heliport Elevation field.

Source/Content: Airport/Heliport elevations are to be derived from official government sources and entered into the field in feet to a resolution of one foot. For elevations above MSL, the field contains the numeric characters of the elevation only. For the below MSL elevations, the first character of the field is a minus (-) sign. Airport elevation is defined as the highest elevation of any landing surface on the airport.

Used On:

Airport and Heliport records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

02171, -0142, 05230

## 5.56 Gate Identifier (GATE IDENT)

Definition/Description: The airport gate defined in the record is identified in the Gate Identifier field.

Source/Content: Coded gate identity information is derived from official government sources and navigation system users.

Used On:

Gate records

Length:

5 characters max

Character Type

Alpha/numeric

Examples:

C134B, 23, 30A, B12A

## 5.57 Runway Length (RUNWAY LENGTH)

Definition/Description: The Runway Length field defines the total length of the runway surface for the runway identified in the records' Runway Identifier field.

Source/Content: Runway lengths are derived from official government sources and are entered in feet with a resolution of one foot. The value represents the overall length of the runway, with no regard for displaced thresholds , starter extension s , stopways, overruns, or clearways. Available landing lengths and take-off runs are not necessarily identical to this runway length. These distances are provided in the Runway Continuation Records. As the latitude/longitude information in the runway record reflects the Landing Threshold Point of the runway identified in the record, which may or may not be displaced, there is no direct correlation between the Runway Length provided in the record and a value calculated based on these latitude/longitude values.

Used On:

Runway Records

Length:

5 characters

Character Type:

Numeric

Examples:

05000, 07000, 11480

Figure 5-3 - Runway Profile View

Source/Content text was updated to support added fields for runway usage.

## 5.58 Runway Magnetic Bearing (RWY BRG)

Definition/Description: The magnetic bearing of the runway identified in the runway identifier or pad ident field of the record is specified in the Runway Magnetic Bearing field.

Source/Content: Runway magnetic bearings derived from official government sources are entered into the field in degrees and tenths of a degree, with the decimal point suppressed. For runway bearings published with the intent to be used as true bearings, the last character of this field will contain a T in place of tenths of a degree. When used on helipad records, it usually will contain the bearing of a former fixedwing runway that has been converted to helicopter use only or when a specific bearing to approach a particular helipad has been provided by government source.

Used On:

Runway and Helipad Records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

1800, 2302, 0605, 347T

## 5.59 Runway Description (RUNWAY DESCRIPTION)

Definition/Description: If required, additional information concerning a runway can be included in a record in the Runway Description field.

Source/Content: Appropriate contents for the field will be determined when the record is assembled.

Used On:

Runway records

Length:

22 characters max

Character Type:

Alpha/numeric

Examples:

GROOVED, SINGLE ENG. ONLY

## 5.60 Name (NAME)

Definition/Description: The Name field defines the name commonly applied to the navigation entity defined in the record.

Source/Content: Appropriate contents for the field will be determined from official government or customer sources.

Used On:

Gate and Holding Pattern records

Length:

25 characters max

Character Type:

Alpha/numeric

Examples:

HOLDING JIMEE MIAMI

## 5.61 Notes (Continuation Records) (NOTES)

Definition/Description: The Notes field (continuation record) is provided to accommodate any information that cannot be entered in the primary record.

Source/Content: Appropriate contents for the field will be determined at the time the primary record is assembled.

Used On:

All except Company route records

Length:

70 characters max

Character Type:

Alpha/numeric

Examples:

EASTBOUND PREFERRED

090/0Z/230/0Z

## 5.62 Inbound Holding Course (IB HOLD CRS)

Definition/Description: The Inbound Holding Course field defines the inbound course to the holding waypoint.

Source/Content: Inbound holding courses derived from official government sources are entered into the field in degrees and tenths of a degree, with the decimal point suppressed. For holding courses published with true bearings, the last character of this field contains a T in place of tenths of a degree.

Used On:

Holding Pattern records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

0456, 1800, 3034, 347T

## 5.63 Turn (TURN)

Definition/Description: The Turn field specifies the direction in which holding pattern turns are to be made.

Source/Content: The Turn field will always contain either L or R.

Used On:

Holding Pattern records

Length:

1 character

Character Type:

Alpha

## 5.64 Leg Length (LEG LENGTH)

Definition/Description: The Leg Length field specifies the distance of either the inbound leg or the outbound leg of the holding pattern. The determination of inbound or outbound is identified by the content of Section 5.298 of the applicable record. Inbound is defined as the distance between the point at which the aircraft rolls out on the inbound leg of the holding pattern and the fix at which the holding pattern is defined. Outbound is defined as the distance from a point abeam the holding fix to the beginning of the inbound turn (Figure 5-4).

Source/Content: Leg length derived from official government sources is entered into the field in nautical miles and tenths of a nautical mile, with the decimal point suppressed.

Used On:

Holding Pattern records

Length:

3 characters

Character Type:

Numeric

Examples:

108, 055

## 5.65 Leg Time (LEG TIME)

Definition/Description: The Leg Time field specifies the length of the inbound leg or outbound of a holding pattern in units of time. The determination of inbound or outbound is identified by the content of Section 5.298 of the applicable record. Inbound is defined as the timing between the point at which the aircraft rolls out on the inbound leg of the holding pattern and the fix at which the holding pattern is defined. Outbound is defined as the timing from a point abeam the holding fix to the beginning of the inbound turn (Figure 5-4).

Source/Content: Leg time, derived from official government sources, is entered into this field in minutes and tenths of a minute, with the decimal point suppressed.

Used On:

Holding Pattern records

Length:

2 characters

Character Type:

Numeric

Examples:

10, 15, 20

LEG LENGTH (TIME)

LEG LENGTH (DISTANCE)

Figure 5-4 - Holding Pattern Leg Length

## 5.66 Station Declination (STN DEC)

Definition/Description: For VHF NAVAIDS, the Station Declination field contains the angular difference between true north and the zero-degree radial of the NAVAID at the time the NAVAID was last site checked. For ILS localizers, the field contains the

angular difference between true north and magnetic north at the localizer antenna site at the time the magnetic bearing of the localizer course was established.

Source/Content: Station declinations are derived from official government sources. The field contains one of the alpha characters shown in the following table followed by the value of the declination in degrees and tenths of a degree, with the decimal point suppressed. When the first column of the Station Declination field is coded T or G, the remainder of the field should be coded all zeros.

| Column 1 Character   | Declination Description                                                                |
|----------------------|----------------------------------------------------------------------------------------|
| E                    | Declination is East of True North                                                      |
| W                    | Declination is West of True North                                                      |
| T                    | Station is oriented to True North in an area in which the local variation is not zero. |
| G                    | Station is oriented to Grid North                                                      |

Used On:

VHF NAVAID and ILS records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

E0072, E0000, T0000, G0000

### 5.66-x83 COMMENTARY

The appearance of the character G in column 1 of this field will alert users that although a NAVAID declination may not be zero, the fact that the grid reference is unknown prevents a value from being defined.

## 5.67 Threshold Crossing Height (TCH)

Definition/Description: The Threshold Crossing Height specifies the height above the landing threshold on a normal glide path.

Source/Content: The Threshold Crossing Height will be derived from official government sources when available. As provided on Runway Records, the TCH value will be the Glideslope Height at the landing threshold for runways with ILS or MLS approaches. If an ILS or MLS is not available and an RNAV approach is available, it will be the published TCH for that procedure. If none of these values are available, it will be 40 or 50 feet based on the table below. When used on Approach Continuation Records, the field will contain the published TCH for that procedure. When used on ILS or MLS Records, it will be the height of the glideslope at the landing threshold. When used on a GLS record, it will be the height of the glide path at the landing threshold.

| Content   | Description                                                                                                  |
|-----------|--------------------------------------------------------------------------------------------------------------|
| 40 (feet) | On Runway records for which all approach procedures are published for Category A and B aircraft only.        |
| 40 (feet) | On Runway records with a length of less than 6000 feet and no published approach procedure.                  |
| 50 (feet) | On Runway records for which there is at least one approach procedure published for Category C or D aircraft. |
| 50 (feet) | On Runway records with a length of 6000 feet or greater and no published approach procedure.                 |

### 5.67-x84 COMMENTARY

Based on the information contained in the Source/Content paragraph, it should be noted that the single TCH value provided on the Runway Record may be different than the TCH value provided on the Approach Continuation Record for a procedure to that same runway. These differences may be significant. A comparison of procedure altitude data to threshold elevation and threshold crossing heights should only be made to the Approach Continuation Record and GLS Record.

Used On:

Airport and Heliport ILS and MLS Runway, Airport, and Heliport Approach Continuation Records.

Length:

3

Character Type:

Numeric

Example

037, 050, 109, 101

## 5.68 Landing Threshold Elevation (LANDING THRES ELEV)

Definition/Description: The elevation of the landing threshold of the runway/helipad described in a runway/helipad record is defined in the Landing Threshold Elevation field.

Source/Content: Landing threshold elevations derived from official government sources are entered into this field in feet, to a resolution of 1 foot. For elevations above MSL, the field contains the numeric characters of the elevation only. For below MSL elevations, the first character of the field is a minus (-) sign.

Used On:

Runway Airport and Heliport Helipad records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

01250, -0150

## 5.69 Threshold Displacement Distance (DSPLCD THR)

Definition/Description: The distance from the extremity of a runway to a threshold not located at that extremity of that runway.

Source/Content: Threshold displacement distances derived from official government sources are entered into this field in feet.

Used On:

Runway records

Length:

4 characters

Character Type:

Numeric

Examples:

0485, 1260

## 5.70 Vertical Angle (VERT ANGLE)

Definition/Description: The Vertical Angle field defines the angular portion of vertical navigation path in STAR Route and Approach Procedure Route records. The Vertical Angle should cause the aircraft to fly at the last coded altitude and then descend on the VNAV path, projected back from the fix and altitude contained in the route sequence that contains the Vertical Angle.

Source/Content: Values from official government source documents will be used when available. In the coding of Precision Approach Procedures , the Vertical Angle is the angle assigned to the glideslope. In the coding of non-precision procedures, it will be the VNAV Path angular definition provided by the government source or a value computed based on the rules for such a computation documented in Attachment 5 of this specification. Values greater than zero will be preceded by the minus sign (-) to indicate descending flight. When no government source value is available and none can be computed based on the rules in Attachment 5 of this specification, the field is populated with all zeros, no minus sign. Vertical Angles are expressed in degrees, tenths and hundredths of degrees with the decimal point suppressed. The maximum value is 9.99 degrees.

Used On:

Airport and Heliport STAR and Approach Route Records 4 characters (first character either (-) or blank)

Length:

Character Type:

Alpha/numeric

Examples:

-300, -275, -542, 000

## 5.71 Name Field

Definition/Description: This field will be used to further define the record by name.

Source/Content: Facility name will be derived from official government sources. A parenthetical name following the official name may be used to identify the location of the facility.

Used On:

Navaid, Airport, Heliport and Enroute Marker records 30 characters

Length:

Character Type:

Alpha/numeric

## 5.72 Speed Limit (SPEED LIMIT)

Definition/Description: The Speed Limit field defines a minimum, maximum, or mandatory indicated air speed, (KIAS) for a fix, a leg or multiple legs in a terminal procedure , maximum allowed airspeed for an airport or heliport terminal environment , or a maximum airspeed with an airspace .

Source/Content: The speed limit will be derived from official government source documentation and shown in Knots. When used on an Airport or Heliport Record, the field is an indication of the maximum allowed speed and applies to all flight segments departing or arriving that airport's or heliport's terminal area, at and below the specified Speed Limit Altitude (5.73). When used on Airport and Heliport SID/STAR/Approach Records, the field is an indication of a speed for a fix, a leg, or multiple legs in the procedure description, used in conjunction with Speed Limit

Description (5.261). When used on a Controlled Airspace record, the field is used to describe the speed restriction within the Airspace.

Used On:

Airport and Heliport SID/STAR/Approach, Airport and Heliport, Flight Planning Arr/Dep Data , and Controlled Airspace Records

Length:

3 characters

Character Type:

Alpha/ Numeric

Examples:

250

Section was updated to reference the speed limit in Controlled Airspace Record.

## 5.73 Speed Limit Altitude

Definition/Description: Speed Limit Altitude is the altitude below which speed limits may be imposed.

Source/Content: The Speed Limit Altitude will be derived from official government sources in feet MSL or FLs.

Used On:

Airport and Heliport , and Controlled Airspace records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

10000, F L1 25

Section was updated to reference the speed limit in Controlled Airspace Record.

## 5.74 Component Elevation (GS ELEV, EL ELEV, AZ ELEV, BAZ ELEV)

Definition/Description: The Component Elevation field defines the elevation of a given component in the Localizer, GLS and MLS records. The Glideslope Elevation (GS ELEV) defines the elevation of the Glideslope component in the Localizer Records. The EL Elevation (EL ELEV) defines the elevation of the Elevation component of the MLS Record, the Azimuth Elevation (AZ ELEV) defines the elevation of the Azimuth component of the MLS Record and the Back-Azimuth Elevation (BAZ ELEV) defines the elevation of the Back-Azimuth component of the MLS Record. The GLS station elevation (GLS ELEV) defines the elevation of the GLS ground station in the GLS record.

Source/Content: Elevations specified in official government publications are entered in this field with respect to MSL. When the elevation is below MSL, the first column of the field contains a minus (-) sign.

Used On:

Localizer, MLS and GLS Records and MLS Continuation Records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

00235, 01265, -0011

## 5.75 From/To - Airport/Heliport/Fix

Definition/Description: When used on Company Routes and Helicopter Operations Company Routes, the From Airport/Heliport/Fix is the fix from which the company route originates. The To Airport/Heliport/Fix is the fix at which the company route terminates. When used on Alternate Records, it is the Departure, Destination or Enroute Airport/Fix for which the alternate information is being provided.

Source/Content: The customer is responsible for defining points at which company routes originate and terminate and for defining which departure, destination or enroute points are to have alternate information. On Company Routes and Helicopter Operations Company Routes, may reference airport, heliport, navaid or

waypoint records which will be further defined by ICAO, Section, and Subsection data.

Used On:

Company Route, Helicopter Operations Company Route and Alternate Records

Length:

5 characters max.

Character Type:

Alpha/numeric

## 5.76 Company Route Ident

Definition/Description: The Company Route Ident field identifies each unique route between origination and destination.

Source/Content: This field is determined by the customer.

Used On:

Company Route Records Helicopter Operations Company

Routes

Length:

10 characters

Character Type:

Alpha/numeric

## 5.77 VIA Code

Definition/Description: The VIA Code field is used to define the type of route used in the SID/STAR/Approach/Airways field (Section 5.78) on Company Route records and defines the type of route used in the AWY Identifier on Preferred Route records. On the Preferred Route records, some codes define the use, or restriction to use, of a fix or routing.

Source/Content: The code to be entered must be selected from the tables below:

Company Route Record (R)

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

Note 1:

N means sequence not allowed, blank means sequence is allowed.

Note 2: The To Fix must match the beginning fix of the following Via.

Used On:

Company Route and Preferred Route records and Helicopter Operations Company Routes

Length:

3 characters

Character Type:

Alpha/numeric

Note:

Table 5- 20 illustrates how various fields are to be completed in the Company Route Record based on the various VIA Codes defined in this section.

Table 5-20 - Company Route Record (R) Field Content

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

Table 5-20 - Company Route Record (R) Field Content

## 5.78 SID/STAR/APP/AWY (S/S/A/AWY) SID/STAR/AWY (S/S/AWY)

Definition/Description: This field is used to provide the identifier of the particular enroute airway or terminal route to be flown as referenced by the VIA field (Section 5.77). The identifier is further defined by the content of columns 95/96/97 of the Company Route or 106/107/108 of the Preferred Route which contain the Route Type and Route Type Qualifier data of the specific route or procedure.

Source/Content: For Company Route records this field can contain the SID/STAR, Approach, Enroute Airway, or Preferred Route Identifier (Sections 5.8, 5.9, and 5.10). For Preferred Route records this field can contain the SID/STAR or Enroute Airway Route Identifier (Section 5.8). This field will be blank for certain records depending on the VIA field content (Section 5.77).

Used On:

Company Route and Preferred Route Records, and Helicopter Operations Company Routes

Length:

6 characters

Character Type:  Alpha/numeric

Examples:

VIA Code

S/S/A/AWY Content

SID

CUIT8

STR

LOCKE9

APP

I19L, R35-Z

AWY

J501

## 5.79 Stopway

Definition/Description: Stopway means the length of an area beyond the take-off runway, no less wide than the runway and centered upon the extended centerline of the runway, and designated for use in decelerating the airplane during an aborted takeoff.

Source/Content: The Stopway will be derived from official government sources and shown in feet (See Table 5-1 5 ).

Used On:

Runway records

Length:

4 characters

Character Type:

Numeric

Examples:

0900, 1000

## 5.80 ILS/MLS/GLS Category (CAT)

Definition/Description: For ILS/MLS/GLS stations, this field defines the Facility Performance Category, defined as Category I, II, and III, up to which the station is operating as a minimum. The level of Facility Performance Category does neither imply that permission exists to use the facility for landing guidance to that level nor limit the minimal use to the designated classification.

This field is also used to define the classification for other than ILS/MLS/GLS installations such as LOC, IGS, LDA, or SDF.

Source/Content: The ILS/MLS/GLS Category/Classification will be derived from official government sources and will be indicated by a value from the table below.

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

Used On:

Localizer, MLS and MLS Continuation Records, GLS Record.

Length:

1 character

Character Type:

Alpha/numeric

## 5.81 ATC Indicator (ATC)

Definition/Description: The ATC Indicator field will be used to indicate that the altitudes shown in the altitude fields can be modified by ATC or the altitude will be assigned by ATC.

Source/Content: This field will contain the alpha character A when the official government source states that the altitude can be modified or assigned by ATC. This field will contain the alpha character S when the official government source states that the altitude will be assigned by ATC or if no altitude is supplied.

Used On:

Airport and Heliport SID/STAR/ Approach Records

Length:

1 character

Character Type:

Alpha

## 5.82 Waypoint Usage

Definition/Description: The waypoint usage field is employed to indicate the structure in which the waypoint is utilized.

Source/Content:

| Usage                                | Record Column Content   |
|--------------------------------------|-------------------------|
| Usage                                | 31                      |
| HI and LO Altitude                   | B                       |
| HI Altitude                          | H                       |
| LO Altitude                          | L                       |
| Terminal Use Only (not used enroute) | Blank                   |

Used On:

Waypoint (EA/PC) and Heliport Terminal Waypoint (HC)

records

Length:

1 character

Character Type:

Alpha

Definition/Description: The Company Route, Helicopter Operation Company Route, and Preferred Route To Fix field is used to terminate the route referenced in the SID/STAR/APCH/AWY field (Section 5.78), or terminate a Direct segment or start an Initial segment when no SID/STAR/APCH/AWY is referenced.

Source/Content: For Company Route records the field will contain Enroute Waypoint, Airport Terminal Waypoint, VHF NAVAID, NDB NAVAID, Terminal NDB NAVAID, Airport or Runway Identifier. For Helicopter Operations Company Route records the field will contain Enroute Waypoint, Helicopter Terminal Waypoint, VHF NAVAID, NDB NAVAID, Terminal NDB NAVAID, Airport, Heliport, Runway Identifier or Helipad Identifier. The customer will define where a particular route segment is to terminate. Terminal Fixes, Runway Identifiers or Helipad Identifiers must be for the From Airport/Heliport or To Airport/Heliport which must be consistent with the VIA Code. For Preferred Route records, the field will contain Enroute Waypoint, Terminal Waypoint, VHF NAVAID, NDB NAVAID or Terminal NDB NAVID, Airport Identifier.

Used On:

Company Route, Helicopter Operations Company Route, and

Preferred Route Records

Length:

Company Route/Helicopter Operations Company Route - 6 characters max.

Preferred Route - 5 characters max.

Character Type:

Alpha/numeric

Examples:

SHARP, BHM, DEN43, KDEN, RW35R

## 5.84 RUNWAY TRANS

Definition/Description: This field is used to identify the desired runway transition of the applicable SID or STAR. Together with the Section/Subsection identified for the SID/STAR/App/AWY field, it is used to link directly to the SID/STAR procedure records depending on the Company Route/Helicopter Operations Company Route

## 5.83 To FIX

record VIA field (Section 5.77) and whether or not the SID/STAR has explicit runway transitions.

Source/Content:

VIA field contains SID or STR:

If the applicable SID/STAR has explicit runway transitions as indicated by the Procedure Route Type, then this field uniquely identifies the desired runway transition. If the applicable SID/STAR has explicit runway transitions as indicated by the Procedure Route Type but no runway transition is desired in the Company Route, the field is blank. If the applicable SID/STAR does not have explicit runway transitions as indicated by the Procedure Route Type, this field is always non-blank and exactly matches the TRANS IDENT field of the SID/STAR procedure records. This is the case when a SID starts with Route Type 2 or a STAR ends with Route Type 2.

VIA field contains SDY or STY:

In this situation, the field contents are defined exactly as stated above (VIA field = SID or STR) except that the field is always non-blank. This field is blank for all other contents of the VIA field.

Used On:

Company Route, Helicopter Operations Company Route Records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

RW08L, ALL,

Blank PADA1, NWPAD

## 5.85 ENRT TRANS

Definition/Description: Together with the Section/Subsection identified for the SID/STAR/App/AWY field, this field is used to identify the desired enroute transition of the applicable SID or STAR. It can also be used to identify the desired approach transition of an approach.

Source/Content:

VIA field contains SID or STR:

This field uniquely identifies the desired SID/STAR enroute transition. If no enroute transition is desired, the field is blank.

VIA field contains SDE or STE:

In this situation, the field contents are defined exactly as stated above (VIA field - SID or STR) except that the field is always non-blank.

VIA field contain APP:

This field uniquely identifies the desired approach transition. If no approach transition is desired, the field is blank.

The field is blank for all other contents of the VIA field.

Used On:

Company Route, Helicopter Operations Company Route Records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

ETS, KEENE, DEN

## 5.86 Cruise Altitude

Definition/Description: This field will be used to establish an Enroute Cruise Altitude. It will be entered on Company Route records as specified by the customer.

Source/Content: The customer will supply the Cruise Attitude in feet or flight level.

Used On:

Company Route, Helicopter Operations Company Route Records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

10000, 15000, FL090, FL240

## 5.87 TERMINAL/ALTERNATE Airport (TERM/ALT ARPT)

Definition/Description: This field has two uses depending on the VIA field and File Code for To Fix. For VIA field content of ALT this field will contain the Alternate Airport Ident or Heliport Ident for this Company Route. If the file code for To Fix contains P, this field will contain the Airport Ident for REGN CODE (Section 5.41) of Terminal Waypoints (PC records) and Runway (PG records). If the file code for To Fix contains H, this field will contain the Heliport Ident for REGN CODE (Section 5.41) of Helicopter Terminal Waypoints (HC records).

Source/Content: See Section 5.6, Airport/Heliport Identifier.

Used On:

Company Route, Helicopter Operations Company Route Records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

KDEN, EDDF

## 5.88 Alternate Distance (ALT DIST)

Definition/Description: This field is used to supply the distance in nautical miles from the To Airport/Heliport/Fix to the Alternate Airport/Heliport.

Source/Content: Values for this field will be supplied by the customer and must be equal to or greater than the great circle distance from the destination airport/fix to the alternate airport/heliport.

Used On:

Company Route, Helicopter Operations Company Route

Records

Length:

4 characters

Character Type:

Numeric

Examples:

052, 0011, 0123

## 5.89 Cost Index

Definition/Description: The Cost Index field is used to define the relative value of fuel-related costs and time-related costs for a particular route.

Source/Content: Source will be by customer airline.

Used On:

Company Route, Helicopter Operations Company Route

Records

Length:

3 characters

Character Type:

Numeric

Examples:

001, 011, 999

## 5.90 ILS/DME Bias

Definition/Description: This field is used to specify the DME offset.

Source/Content: The field contains a 2-digit bias term in nautical miles and tenths of a nautical mile with the decimal point suppressed. Field is blank for unbiased DMEs.

Used On:

VHF NAVAID Records containing ILS/DME or MLS/DME

Facilities

Length:

2 characters

Character Type:

Numeric

Examples:

13, 91

## 5.91 Continuation Record Application Type (APPL)

Definition/Description: This field indicates specific application of this continuation record.

Source/Content: The field will contain one of the following type codes:

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

Used On:

Continuation Records

Length:

1 character

Character Type:

Alpha

## 5.92 Facility Elevation (FAC ELEV)

Definition/Description: The Facility Elevation field provides the elevation of navaids and communications transmitters.

Source/Content: Facility Elevation data is derived from official government source. It is provided in feet with a resolution of one foot. It is referenced to MSL. When the elevation is below MSL, the first character of the field will be a minus sign (-) indicating below sea level.

Used On:

ILS Marker, Airway Marker Primary Records Enroute, Airport, and Heliport Primary Extension Continuation Records, VHF Navaids and NDB Navaids Simulation Continuation Records 5 characters

Length:

Character Type:

Alpha/numeric

Examples:

00530, -0014

## 5.93 Facility Characteristics (FAC CHAR)

Definition/Description: The Facility Characteristics field identifies the characteristics of the NAVAID facility.

**Source/Content:**

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

Used On:

ILS Marker Primary records, VHF Navaid, NDB Navaid and ILS/MLS continuation records

Length:

5 characters

Character Type:

Alpha/numeric

Note 1:

0=A0, 1=A1, 2=A2

Note 2: Enter number of occurrences per minute if known. Leave blank if not known.

Note 3: Collocated means that the latitudes and longitudes of the two facilities differ by no more than 1 arc second.

Note 4: Where a high-rate approach azimuth guidance is available, enter H, otherwise leave blank.

### 5.93-x86 COMMENTARY

The NDB emission designators set forth in Note 1 above are being replaced with the new designators shown in the equivalency table below as the result of action taken at the 1979 ITU World Administrative Radio Conference.

| Present Designator   | New Designator   | Description                                   |
|----------------------|------------------|-----------------------------------------------|
| A0                   | NON              | Unmodulated Carrier                           |
| A1                   | A1A              | Carrier keyed, bandwidth less than 0.1 kHz    |
| A1                   | A1B              | Carrier keyed, bandwidth greater than 0.1 kHz |
| A2                   | A2A              | Tone keyed modulation                         |

## 5.94 True Bearing (TRUE BRG)

Definition/Description: The Magnetic Bearing for ILS localizer, MLS Azimuth, MLS Back Azimuth and Runway records is given in the primary record. This field allows the true bearing to be provided independently of the magnetic bearing data.

Source/Content: True Bearings are entered into the field in degrees, tenths of a degree and hundredths of a degree, with the decimal point suppressed. When the source magnetic bearing data is provided as true with the intent for it to be used as true, the Magnetic Bearing and the True Bearing values will be identical. See Section 5.95 for source description.

Used On:

ILS Continuation, MLS Continuation and Runway Continuation records

Length:

5 characters

Character Type:

Numeric

Examples:

19000, 23021, 06050

## 5.95 Government Source (SOURCE)

Definition/Description: The content of the source field indicates whether the True Bearing is derived from official government sources or from other sources.

Source/Content: The field contains Y when the True Bearing is derived from official government sources and N when it is derived from other sources. The field contains T when the source Magnetic and True bearing are provided only in True.

Used On:

ILS, MLS, MLS continuation and runway continuation records

Length:

1 character

Character Type:

Alpha

## 5.96 Glideslope Beam Width (GS BEAM WIDTH)

Definition/Description: The Glideslope Beam Width field specifies the glide path beam width of the Glideslope defined in the record.

Source/Content: Glideslope beam widths from official government sources are entered into this field in degrees, tenths of a degree and hundredths of a degree with the decimal point suppressed.

Used On:

ILS continuation records

Length:

3 characters

Character Type:

Numeric

Examples:

140, 180, 200

## 5.97 Touchdown Zone Elevation (TDZE)

Definition/Description: The Touchdown Zone Elevation is the highest elevation in the first 3,000 feet of the landing surface beginning at the threshold.

Source/Content: Touchdown zone elevations from official government sources will be used when available. If official source is not available, the runway threshold elevation will be entered. If the runway threshold elevation is not available, the Airport reference point elevation will be entered. (See TDZE Location, Section 5.98) The elevation will be entered in feet, to a resolution of 1 foot, with respect to MSL. For below MSL elevations, the first character of the field is a minus (-) sign.

Used On:

Runway continuation records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

02171, 05230, -0142

## 5.98 TDZE Location (LOCATION)

Definition/Description: The content of the TDZE Location field indicates whether the TDZ elevation was obtained from official government sources or from other sources.

Source/Content: The field will contain a T for official source or an L if the landing threshold elevation is used, or an A if the airport elevation is used.

Used On:

Runway continuation records

Length:

1 character

Character Type:

Alpha

## 5.99 Marker Type (MKR TYPE)

Definition/Description: The Marker Type field defines the type of marker.

Source/Content: The field contains the following information.

| Type of Facility   | Record Column Content   | Record Column Content   | Record Column Content   |
|--------------------|-------------------------|-------------------------|-------------------------|
| Type of Facility   | 18                      | 19                      | 20                      |
| Inner Marker       |                         | I                       | M                       |
| Middle Marker      |                         | M                       | M                       |
| Outer Marker       |                         | O                       | M                       |
| Back Marker        |                         | B                       | M                       |
| Locator at Marker  | L                       |                         |                         |

Used On:

Airport Localizer Marker records

Length:

3 characters

Character Type:

Alpha

## 5.100 Minor Axis Bearing (MINOR AXIS TRUE BRG)

Definition/Description: The Minor Axis Bearing field indicates the true bearing of the minor axis of marker beacons.

Source/Content: This field will contain the true bearing in degrees and tenths of a degree, with the decimal point suppressed.

Used On:

Airport Localizer Marker records

Length:

4 characters

Character Type:

Numeric

Examples:

0900, 2715

## 5.101 Communications Type (COMM TYPE)

Definition/Description: The Communications Type is a three-character code indicating the type of communications service available on the frequency contained in the record. Decoding is available in the Communications Type Translation Table.

Source/Content: The field will be derived from official source or created by the data supplier. An indication of the origination of the code is contained in the Communications Type Translation Table.

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

Note 1:   The Comm Type PAL is used only when the frequency(s) published are used exclusively for the activation of airport lighting. If the pilot activation of airport lighting is accomplished on a frequency that is also used for voice communications, the Pilot Controlled Lighting parameter of the Service Indicator is used.

Note 2:   The Comm Types CTF and MBZ are used in Australia, New

Zealand and East Timor only.

Used On:

Enroute, Airport and Heliport Communications

Length:

3 characters

Character Type:

Alpha

## 5.102 Radar (RADAR)

Definition/Description: The Radar field indicates whether or not the communications unit identified in the record has access to and uses information derived from primary or secondary radars while performing the communications service indicated by the Communications Type. It is not an indication of an operational radar frequency.

Source/Content: The availability of radar information to a communications service provider is derived from official government sources. The field will be set to the character R if primary or secondary radar information is available to the service, the character N if the source documentation specifically states that the service does not have access to primary or secondary radar information or the character U if the source documentation does not provide details on radar information access for the service.

Used On:

Enroute, Airport and Heliport Communications records

Length:

1 character

Character Type:

Alpha

## 5.103 Communications Frequency (COMM FREQ)

Definition/Description: The Communications Frequency field specifies either transmit or receive frequency of the communications service, dependent on in which column the frequency is located. Each communications record will contain both transmit and receive frequencies unless the service is published as a Transmit Only or Receive Only service. The content will be identical if the service transmits and receives on the same frequency. The fields will be left blank when the service provided is a digital service.

Source/Content: Content is derived from official government sources. The following details apply:

HF frequencies are provided as five significant digits and one decimal in kilohertz for 10 thousand, thousands, hundreds, tens and units, and tenths. The remaining position of the seven-character field is zero filled.

Example: The HF frequency of 17955 kHz would be expressed as 1795500. The HF frequency of 8965 kHz would be expressed as 0896500.

VHF frequencies with 100, 50 or 25 kilohertz spacing are provided as three significant digits and three decimals in megahertz for hundreds, tens, units, tenths, hundredths and thousandths. The remainder of the seven-character field is zero filled.

Example: The VHF frequency of 118.50 MHz would be expressed as 0118500. The VHF frequency of 131.275 MHz would be expressed as 0131275.

UHF frequencies are provided as three significant digits and two decimals in megahertz for hundreds, tens, units, tenths and hundredths. The remainder of the seven-character field is zero filled.

Example: The UHF frequency of 267 MHz would be expressed as 0026700. The UHF frequency of 287.5 MHz would be expressed as 0028750.

VHF frequencies with 8.33 kHz spacing are provided as four significant digits and three decimals for the assigned channel number. The actual frequency (which would be three significant digits and four decimal places) is not provided.

Example: The VHF frequency of 132.0583 MHz will be provided as the channel number 132.060, expressed in seven digits as 0132060.

The decimal point is always suppressed. As all of these numeric expressions look alike, the Frequency Units field (Section 5.104) is provided to assist in actual frequency determination.

Used On:

Enroute, Airport and Heliport Communications Records

Length:

7 characters

Character Type:

Numeric

## 5.104 Frequency Units (FREQ UNIT)

Definition/Description: The Frequency Units field will designate the frequency spectrum area for the frequency in the Communications Frequency (Section 5.103) field as indicated in the table or will designate the content of the Communications Frequency field as a channel. For VHF based units, the field will also designate the established frequency spacing required of the frequency for unambiguous use.

Source/Content: This field contains the following information.

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

Note 1: The Codes L and M will only be used when the transmitting frequency is that of a LF/MF Navaid (NDB). If a receiving frequency is provided in the same communications record, it will be a VHF frequency.

Note 2: The Code D for Digital Service will be provided when the communications record contains a data link type service. In these cases, transmit and receive frequency columns will be blank.

Used On:

Enroute, Airport, and Heliport Communications records

Length:

1 character

Character Type:

Alpha

## 5.105 Call Sign (CALL SIGN)

Definition/Description: The Call Sign field contains the name of a communications service provider that is to be used when contacting that service/used by the service to identify itself when contacting aircraft on the frequencies contained in the record. The field is also used to provide the broadcast identification name of automated services.

Source/Content: Call Signs and broadcast service identification names are derived from official government sources. The type of service may be omitted from the Call Sign field when it is the same as the service identified in the Communications Type (5.101).

Used On:

Airport, Enroute, and Heliport Communications Records

Length:

25 characters

Character Type:

Alpha/numeric COMM TYPE CALL NAME APP LION (APPROACH is omitted) TWR LION (TOWER is omitted) DEP LONDON APPROACH ACC DENVER CENTER

Examples:

## 5.106 Service Indicator (SERV IND)

Definition/Description: The Service Indicator field is used to further define the use of the frequency for the specified Communication Type (5.101).

Source/Content: The field may contain the following information:

Table 5-21 - Airport Heliport Communications Records

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

Table 5-21 - Airport Heliport Communications Records

Table 5-22 - Enroute Communications Records

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

Table 5-22 - Enroute Communications Records

Used On:

Enroute, Airport, and Helicopter Communications records

Length:

3 characters

Character Type:

Alpha

## 5.107 ATA/IATA Designator (ATA/IATA)

Definition/Description: The ATA/IATA field contains the Airport/Heliport ATA/IATA designator code to which the data contained in the record relates.

Source/Content: The content of this field should be derived from IATA Reservations Manual Part II, IATA Resolution 763/Location Identifiers.

Used On:

Airport and Heliport records

Length:

3 characters

Character Type:

Alpha

Examples:

DEN, LHR, JFK

## 5.108 IFR Capability (IFR)

Definition/Description: The IFR Capability field indicates if the Airport/Heliport has any published Instrument Approach Procedures.

Source/Content: The field contains Y if there is an Official Government Instrument Approach Procedure published, otherwise the field will contain N. (Note: The presence of Y in this field does not necessarily imply that the published instrument approach is coded in the database.)

Used On:

Airport and Heliport records

Length:

1 character

Character Type:

Alpha

## 5.109 Runway Width (WIDTH)

Definition/Description: The width of the runway identified in the Runway Identifier field is specified in the Runway Width field.

Source/Content: Runway widths derived from Official Government Sources are entered into the field in feet, with a resolution of one foot. For runways of variable width, the minimum width encountered over the runway length will be entered.

Used On:

Runway records

Length:

3 characters

Character Type:

Numeric

Examples:

150, 300, 075

## 5.110 Marker Ident (MARKER IDENT)

Definition/Description: The Marker Ident field contains a unique computer ident assigned to each enroute marker.

Source/Content: A unique identifier will be created for each enroute marker since such idents are not designated by official sources. Marker idents will be established using the 2-character ICAO code followed by two numeric digits assigned to keep markers unique within a given ICAO region.

Used On:

Enroute marker records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

EG01, EG02, K101, K102

## 5.111 Marker Code (MARKER CODE)

Definition/Description: The Marker Code field contains the coded ident that provides an aural and visual indication of station passage in the cockpit. The code shall be keyed so as to transmit dots or dashes, or both, in an appropriate sequence on a radio frequency of 75 MHz. The frequency of the modulating tone is 3000 Hz.

Source/Content: The field contains the Morse code ident (dots and dashes) derived from official government sources.

Used On:

Enroute marker records

Length:

4 characters

Character Type:

Alpha

Examples:

-.-., . . . ., - - - -

## 5.112 Marker Shape (SHAPE)

Definition/Description: The Shape field defines the radiation pattern of an airways marker as being either bone or elliptical.

Source/Content: The field contains the shape of the marker derived from official government sources when available. The character B will designate the bone shape and the character E will designate the elliptical shape. E will be entered when the source does not supply shape information.

Used On:

Enroute airways marker records

Length:

1 character

Character Type:

Alpha

## 5.113 High/Low (HIGH/LOW)

Definition/Description: The High/Low field indicates the power of the enroute marker.

Source/Content: The field contains the power derived from official government sources. The character L indicates low power for use at low altitudes. The character H indicates high power for general use.

Used On:

Enroute marker records

Length:

1 character

Character Type:

Alpha

## 5.114 Duplicate Indicator (DUP IND)

Definition/Description: The Duplicate Identifier field is used to further define holding patterns when official government source has designated more than one Holding Pattern on a Navaid or Waypoint.

Source/Content: Holding Patterns are derived from official government sources documents. That documentation will normally specify the airspace structure in which the holding is to be used. That documentation may also designate more than one Holding Pattern for a single Navaid or Waypoint. This field will contain details on airspace structure and multiple designations. More than one holding is designated on a single fix when one or more of the following elements are different for holdings

within the same airspace structure. Inbound Holding Course, Turn Direction, Altitude, Leg Length or Leg Time, and Holding Speed.

If only one Holding Pattern is designated for a fix and the airspace structure in which that holding is to be used is not defined, the field will contain 00. If only one Holding Pattern is designated for a fix and the airspace structure in which that holding is to be used is defined or if the same holding is designated for more than one airspace structure, the first position of the Duplicate Indicator will contain a digit of 1 through 6 and the second position will contain a zero. If more than one holding is designated for a single fix in one type of airspace structure, the first position will contain a digit of 1 through 6 and the second position will contain a digit of 0 through 9, depending on the number of holdings on that fix within that airspace structure.

If multiple holdings are designated in official source documents for a single fix and some of those holding are not associated with a defined airspace structure, then those with undefined airspace structure will carry the digit 7 in position one and a digit of 0 through 9 in position two.

Table 5-23 - Multiple Holding Patterns

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

Table 5-23 - Multiple Holding Patterns

Note 1:

If there is only one holding pattern on a given fix within an airspace structure, position 2 will contain a 0. For additional holdings on that same fix within the same airspace structure, position 2 will be incremented by 1.

Used On:

Holding Pattern Records

Length:

2 characters

Character Type:

Numeric

Examples:

00, 10, 61, 32

## 5.115 Directional Restriction

Definition/Description: The Direction Restriction field, when used on Enroute Airway records, will indicate the direction an Enroute Airway is to be flown. The Direction Restriction field, when used on Preferred Route records, will indicate whether the routing is available only in the direction of from initial fix to terminus fix or in both directions.

Source/Content: Direction Restrictions should be derived from official government sources. They will be coded and supplied as follows:

## 5.115-x87 Enroute Airway Records

| F     | One way in direction route is coded (Forward).           |
|-------|----------------------------------------------------------|
| B     | One way in opposite direction route is coded (backward). |
| Blank | No restrictions on direction.                            |

### 5.115-x87-x88 Preferred Route Records

| F   | Uni-directional Preferred Route, usable only from Initial Fix to Terminus Fix.                               |
|-----|--------------------------------------------------------------------------------------------------------------|
| B   | Bi-directional Preferred Route, usable from Initial Fix to Terminus Fix or from Terminus Fix to Initial Fix. |

Used On:

Enroute Airway and Preferred Route Records

Length:

1 character

Character Type:

Alpha

## 5.116 FIR/UIR Identifier (FIR/UIR IDENT)

Definition/Description: The FIR/UIR Identifier field identifies the Flight Information Region and Upper Information Region of airspace with defined dimensions within which Flight Information Service and Alerting Service are provided. The Identifier is for the controlling Area Control Center or Flight Information Center.

Source/Content: FIR/UIR Identifiers will be derived from official government sources. This field contains the four-character identifier assigned to the airspace. For those areas charted as NO FIR, the identifier field will contain XX plus a twodigit numeric.

When used on Flight Planning Continuation records, the entry will be related to the altitude structure. For records that are classed or designated as high altitude, the FIR field will be blank. For areas assigned a FIR identifier only that is valid for both the low altitude and the high-altitude structure, the UIR field will be blank. For detail records classed or designated as low altitude and high altitude, both the FIR and the UIR identifier will be entered.

Used On:

FIR/UIR, VHF NAVAID, NDB NAVAID, Enroute, Terminal Waypoint, Airport Flight Planning Continuation and Heliport records

Length:

4 characters

Character Type:

Alpha

Examples:

DAAG, SGAS, XX02

## 5.117 FIR/UIR Indicator (IND)

Definition/Description: When used on Enroute Communications Records, the content definition above for the FIR/UIR Record is to be applied whenever the FIR/RDO (5.190) field of the Enroute Communications Record contains an Information Region Identifier. In all other cases, the Indicator field of the Enroute Communications Record will be blank.

Source/Content:

| Type             | Field Content   |
|------------------|-----------------|
| FIR              | F               |
| UIR              | U               |
| Combined FIR/UIR | B               |

Used On:

FIR/UIR and Enroute Communications records

Length:

1 character

Character Type:

Alpha

## 5.118 Boundary Via (BDRY VIA)

Definition/Description: The Boundary VIA defines the path of the boundary from the position identified in the record to the next defined position.

Source/Content: The path of the boundary will be determined from official government sources or the rule listed below and the Boundary VIA will be selected from the table below.

| Field Position 1   | Content Position 2   | Description                                |
|--------------------|----------------------|--------------------------------------------|
| C                  |                      | Circle                                     |
| G                  |                      | Great Circle                               |
| H                  |                      | Rhumb Line                                 |
| L                  |                      | Counter Clockwise ARC                      |
| R                  |                      | Clockwise ARC                              |
|                    | E                    | End of description, return to origin point |

**Application Rules:**

Special Use Airspace designated as following rivers, country, state or other political boundaries will be averaged in coding by using a series of straight lines so that no path will be greater than two miles from the actual boundary. The Boundary VIA will be G.

If there is a named waypoint on an airway which crossed an irregular FIR/UIR boundary, the waypoint coordinates will be used to define a point in the path defining that FIR/UIR boundary. The Boundary VIA will appropriate to the path definition.

Paths that follow lines of latitude will be coded with a Boundary Via of H. Paths that follow lines of longitude may be coded with a Boundary Via of G or H. Consistent use of one or the other with a single airspace is desired.

Other than for lines of latitude and longitude, the Boundary VIA of H shall only be used when specifically stated in the official government source. If not stated as Rhumb Line or not along latitude/longitude, all straight lines will be coded as G.

Note:

Refer to Figure 5-5 for sample coding of Boundary VIA Codes.

Used On:

Controlled Airspace, FIR/UIR, and Restrictive Airspace records

Length:

2 characters

Character Type:

Alpha

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

Figure 5-5 - Controlled and Restrictive Airspace and FIR/UIR Boundaries

## 5.119 Arc Distance (ARC DIST)

Definition/Description: The Arc Distance field is used to define the distance in nautical miles from the Arc Origin position to the arc defining the lateral boundary of a FIR/UIR or Restrictive Airspace.

Source/Content: ARC distances should be derived from official government sources when available, in nautical miles and tenths of nautical mile, with the decimal point suppressed. The field will be entered only when Boundary Via is A, C, L, or R.

Used On:

FIR/UIR, Restrictive Airspace, and Controlled Airspace records

Length:

4 characters

Character Type:

Numeric

Examples:

0080, 0150, 1000

## 5.120 Arc Bearing (ARC BRG)

Definition/Description: The Arc Bearing field contains the true bearing from the Arc Origin position to the beginning of the arc.

Source/Content: Arc bearings should be derived from official government sources when available. The field contains true bearing in degrees and tenths of degree, with the decimal point suppressed. The field will only be entered when Boundary Via is A, C, L, or R.

Used On:

FIR/UIR, Restrictive Airspace, and Controlled Airspace records

Length:

4 characters

Character Type:

Numeric

Examples:

0900, 1800, 3450

## 5.121 Lower/Upper Limit

Definition/Description: Special Use Airspace is described by both lateral and vertical boundaries. The Lower/Upper Limit fields contain the lower and upper limits of the FIR/UIR or Restrictive Airspace being described.

Source/Content: Limits for the special use airspace should be derived from official government sources. The field may contain altitude (all numerics), flight levels (alpha/numerics) or an all alpha entry (see examples). The flight level entry will contain the alpha characters FL followed by the altitude in hundreds of feet. These fields will be entered on the first record only of each FIR/UIR or Restrictive Airspace being described.

Used On:

FIR/UIR, Restrictive Airspace, and Controlled Airspace records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

All numeric:

05000, 25000

Alpha/numeric:

FL245, FL450

All alpha:

NOTSP (for Not Specified)

UNLTD (for unlimited)

GND (for Ground)

MSL (for Mean Sea Level)

NOTAM (for Restrictive Airspace only)

## 5.122 FIR/UIR ATC Reporting Units Speed (RUS)

Definition/Description: The FIR/UIR ATC Reporting Units Speed is used to indicate the units of measurement concerning True Air Speed used in the specific FIR/UIR to fulfill the requirements of ICAO flight plan.

Source/Content: FIR/UIR Reporting Units should be derived from official government publications. The field will be entered on the first record only for each FIR/UIR identifier.

| Reporting Units      |   Field Entry |
|----------------------|---------------|
| Not specified        |             0 |
| TAS in Knots         |             1 |
| TAS in Mach          |             2 |
| TAS in Kilometers/hr |             3 |

Used On:

FIR/UIR records

Length:

1 character

Character Type:

Numeric

## 5.123 FIR/UIR ATC Reporting Units Altitude (RUA)

Definition/Description: The FIR/UIR ATC Reporting Units Altitude field is used to indicate the units of measurement concerning the altitude used in the specific FIR/UIR to fulfill the requirements of ICAO flight plan.

Source/Content: FIR/UIR Reporting Units should be derived from official government publications. The field will be entered on the first record only for each FIR/UIR identifier.

| Reporting Units     |   Field Entry |
|---------------------|---------------|
| Not specified       |             0 |
| ALT in Flight Level |             1 |
| ALT in Meters       |             2 |
| ALT in Feet         |             3 |

Used On:

FIR/UIR records

Length:

1 character

Character Type:

Numeric

## 5.124 FIR/UIR Entry Report (ENTRY)

Definition/Description: The FIR/UIR Entry Report field is used to indicate whether an entry report on ICAO flight plan is required for that specific FIR/UIR.

Source/Content: FIR/UIR Entry Report should be derived from official government publications. Y in this field indicates Entry Report is required, N in this field indicates no Entry Report is required. The field will be entered on the first record only for each FIR/UIR identifier.

Used On:

FIR/UIR records

Length:

1 character

Character Type:

Alpha

## 5.125 FIR/UIR Name

Definition/Description: The FIR/UIR Name field contains the official name of the controlling agency of the FIR/UIR of which this record is an element.

Source/Content: The FIR/UIR name will be derived from official publications. The areas without a specific FIR/UIR designation will be labeled NO FIR.

Used On:

FIR/UIR records

Length:

25 characters

Character Type:

Alpha/numeric

Examples:

ACCRA, FIR, ASUNCION FIR/UIR, NO FIR

## 5.126 Restrictive Airspace Name

Definition/Description: The Restrictive Airspace Name field will contain the name of the restrictive airspace when assigned.

Source/Content: Names will be derived from official government sources. The name, if assigned, will be entered in the first record only. If source does not assign a name, this field may be blank.

Used On:

Restrictive Airspace records

Length:

30 characters

Character Type:

Alpha/numeric

Examples:

RANDOLPH ONE MOA, SAMBURU GAME RESERVE

## 5.127 Maximum Altitude (MAX ALT)

Definition/Description: The Maximum Altitude field is used to indicate the Maximum Altitude Allowed (MAA).

Source/Content: When used on Enroute Airway Records, the Maximum Altitude will be derived from official government publications describing a maximum allowable flight altitude, or the upper limit of the airway when no MAA is provided, expressed in feet or flight level.

When used on Holding Pattern Records, the Maximum Altitude will be a value provided in source documentation that restricts the use of the Holding, expressed in feet or flight level. In all other cases, the field will be left blank.

When used on Preferred Route Records, the Maximum Altitude will be the maximum flight altitude at which the preferred route is established or the upper limit of the airspace in which the route is published.

Used On:

Enroute Airway, Holding Pattern, and Preferred Route records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

All numeric:

17999, 08000

Alpha/numeric:

FL100, FL450

All alpha:

UNLTD (for unlimited)

## 5.128 Restrictive Airspace Type (REST TYPE)

Definition/Description: The Restrictive Airspace Type field is used to indicate the type of Airspace in which the flight of aircraft is prohibited or restricted. The restriction may be continuous or specified for certain times.

Source/Content: The Restrictive Airspace Type should be derived from official government publications.

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

Used On:

Restrictive Airspace and Enroute Airway Flight Planning Continuation records

Length:

1 character

Character Type:

Alpha

## 5.129 Restrictive Airspace Designation

Definition/Description: The Restrictive Airspace Designation field contains the number or name that uniquely identifies the restrictive airspace.

Source/Content: The identifiers will be derived from official government sources. The field will contain a numeric number, or when designation is by name this field will contain the name up to 10 characters. When name is longer than 10 characters, the 10 th position will contain an asterisk indicating the name field should be used for the full designator.

Used On:

Restrictive Airspace and Enroute Airway Flight Planning Continuation records

Length:

10 characters

Character Type:

Alpha/numeric

| Field Content      | Field Content   | Field Content   | Field Content   |
|--------------------|-----------------|-----------------|-----------------|
| Charted Designator | ICAO            | Type            | Rest. Desig.    |
| RJ(R)-116          | RJ              | R               | 116             |
| R-2524             | K2              | R               | 2524            |
| Crystal MOA        | K4              | M               | Crystal         |
| Randolph MOA One B | K4              | M               | Randolph*       |

## 5.130 Multiple Code (MULTI CD)

Definition/Description: The Multiple Code field will be used to indicate Restrictive Airspace Areas or MSA Centers having the same designator but subdivided or differently divided by lateral and/or vertical detail.

Source/Content: This field will be used when official government publications for Restrictive Airspace divides an area with the same designator into different areas of Activation, altitude or other defining characteristics. For MSA Centers, this provides different sectorization and altitudes for the MSA published with the same center. The field will contain an alpha/numeric character uniquely identifying each area or MSA. The first record affected could contain the character A and multiple primary records could contain the character B, C, D, 0, 1, etc., as required.

Used On:

Controlled Airspace, Restrictive Airspace, Airport and Heliport MSA Center, Airport and Heliport SID/STAR/Approach, and Enroute Airway Flight Planning Continuation Records.

Length:

1 character

Character Type:

Alpha/numeric

## 5.131 Time Code (TIME CD)

Definition/Description: When used on the Primary or Primary Extension Continuation Record of the possible record types, with the exception of the Airway Restriction Records, the Time Code field is used to indicate that the data contained in the record is either available continuously or not continuously. When Time Code is used in a Time of Operations Continuation Record, other that Airway Restriction Records, the field is used to indicate how to interpret Time of Operations Continuation Records. On Airway Restriction Primary and Continuation Records, the Time Code indicated either a continuous or non-continuous operation, the details of which are contained in the same record.

Source/Content: Active times are derived from official government source. The field will contain an alpha character for which an associated description has been defined as indicated in the tables below.

Used On:

Primary Records: Restrictive Airspace, Preferred Route, Controlled Airspace - Use Primary Record Table portion.

Primary Extension Continuation Records:

Airport, Heliport and Enroute Communications Records - Use Primary Record Table portion.

Time of Operations Continuation Records:

Restrictive Airspace, Preferred Route, Controlled Airspace, Airport, Heliport, Enroute Communications Records - Use Continuation Records Table portion.

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

Used On:

Enroute Airway Restriction Primary and Continuation Records

Length:

1 character

Character Type:

Alpha

## 5.132 NOTAM

Definition/Description: Restrictive Airspace areas may not have established active times and are activated by NOTAM or may be active by NOTAM in addition to established times.

Source/Content: Active times by NOTAM will be derived from official government source. When used on primary records, the area is active only by NOTAM and there will be no continuation record. When used on continuation records, the area is active by NOTAM in addition to the established times. The field will contain the alpha character N to indicate either condition, otherwise the field will be blank.

Used On:

Controlled Airspace, Restrictive Airspace, and Restrictive Airspace Continuation records

Length:

1 character

Character Type:

Alpha

## 5.133 Unit Indicator (UNIT IND)

Definition/Description: Restrictive Airspace lower and upper limits are specified as above Mean Sea Level (MSL) or Above Ground Level (AGL). This field permits the unit of measurement to be indicated.

Source/Content: The units of lower and upper limits are derived from official government source. The alpha character M will indicate MSL and the alpha character A will indicate AGL.

Used On:

Controlled Airspace, Restrictive Airspace records

Length:

1 character

Character Type:

Alpha

## 5.134 Cruise Table Identifier (CRSE TBL IDENT)

Definition/Description: A standard cruising level table is established by ICAO and is to be observed except when, on the basis of regional air navigation agreements, a modified table of cruising levels is prescribed for use. This field permits the enroute airway record to identify the Cruise Table record that is to be used for cruise levels.

Source/Content: Cruise Levels will be derived from official government sources. For the standard ICAO cruise table, this field will contain the alpha characters AA. For

those countries not using the standard ICAO table and having a modified table this field will contain the alpha characters BB, CC, etc. If a country uses the standard ICAO table or a Modified table but indicates that an airway or portion of an airway is to be flown opposite of the cruise table, the field will contain alpha/numeric characters that identify the table to be used.

Used On:

Enroute Airway, FIR/UIR, Cruise Table, and Flight Planning

Arrival/Departure Data Records

Length:

2 characters

Character Type:

Alpha/numeric

Example:

| Field Content   | Description                        |
|-----------------|------------------------------------|
| AA              | ICAO standard cruise table         |
| AO              | Exception to ICAO cruise table     |
| BB - ZZ         | Modified cruise table              |
| BO - ZO         | Exception to modified cruise table |

## 5.135 Course FROM/TO

Definition/Description: The Course From field is used to indicate the lowest course for which a block of cruising levels is prescribed. The Course To field is used to indicate the highest course for which a block of cruising levels is prescribed.

Source/Content: The Courses will be derived from official government sources in degrees and tenths of degree with the decimal point suppressed. The Magnetic/True indicator field will be used to indicate True (T) or Magnetic (M) courses.

Used On:

Cruising Table records

Length:

4 characters

Character Type:

Numeric

Examples:

0000, 1790, 3590

## 5.136 Cruise Level From/To

Definition/Description: The Cruise Level From field is used to indicate the lowest cruising level prescribed for use within the Course From/To fields. The Cruise Level To field is used to indicate the highest cruising level prescribed for use within the Course From/To fields.

Source/Content: Cruise Levels will be derived from official government sources. When the level is entered in feet the field will be all numeric. When the level is entered in meters, the first column will contain the alpha character M followed by all numeric. If the Level To is unlimited, the field will contain the alpha characters UNLTD.

Used On:

Cruising Table records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

0200, M0600, M1585

## 5.137 Vertical Separation

Definition/Description: The Vertical Separation field is used to indicate the minimum separation prescribed to be maintained between the cruising levels.

Source/Content: Vertical Separation Values will be derived from official government sources and entered in feet or tens of meters with M in the first column.

Used On:

Cruising Table records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

01000, 02000, M0030, M0060

## 5.138 Time Indicator (TIME IND)

Definition/Description: The Time Indicator field is used to indicate whether the times shown in the Time of Operations field(s) are Local Time, Daylight Savings Time or Universal Coordinated Time.

Source/Content: Time contained in the affected record(s) is derived from official government sources. The Time Indicator will qualify those source derived times as indicated in the following table:

| Field Content   | Description                                              |
|-----------------|----------------------------------------------------------|
| T               | Times codes are Local Time                               |
| S               | Times codes are to be adjusted for Daylight Savings Time |
| Blank           | Times shown are Universal Coordinated Time (UTC)         |

Used On:

Controlled Airspace, Restrictive Airspace Continuation, Referred Route Continuation, Enroute Airway Restriction, Airport and Heliport Communication Continuation, and Enroute Communications Continuation Records

Length:

1 character

Character Type:

Alpha

## 5.140 Controlling Agency

Definition/Description: Some Restrictive Airspace areas are designated joint use and IFR operations in the area may be authorized by the controlling agency when it is not being utilized by the using agency.

Source/Content: The name of the Controlling Agency should be derived from official government sources and will be shown on the first record only. If no Controlling Agency is specified, the field may be blank.

Used On:

Controlled Airspace, Restrictive Airspace Continuation record

Length:

25 characters

Character Type:

Alpha/numeric

Examples:

LAX, ARTCC, Lumpur ACC, Butterworth APP

## 5.141 Starting Latitude

Definition/Description: The Grid MORA Table will contain records describing the MORA for each Latitude and Longitude block. Each record will contain thirty blocks and the Starting Latitude field defines the lower left corner for the first block of each record.

Source/Content: The Starting Latitude will be determined when the record is assembled.

Used On:

Grid Mora record

Length:

3 characters

Character Type:

Alpha/numeric

Examples:

N00, N42, S20, S90

## 5.142 Starting Longitude

Definition/Description: The Grid MORA table will contain records describing the MORA for each Latitude and Longitude block. Each record will contain thirty blocks and the Starting Longitude field defines the lower left corner for the first block of each record.

Source/Content: The Starting Longitude will be determined when the record is assembled.

Used On:

Grid Mora records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

E000, W150, E090, W180

## 5.143 Grid MORA

Definition/Description: Grid MORA Minimum Off-route Altitude (MORA) provides terrain and obstruction clearance within the section outlined by latitude and longitude blocks provided in the Starting Latitude and Starting Longitude fields.

Source/Content: Grid MORA values clear all terrain and obstructions by 1000 feet in areas where the highest elevations are 5000 feet MSL or lower. MORA values clear all terrain by 2000 feet in areas where the highest elevations are 5001 feet MSL or higher. The field will contain values expressed in hundreds of feet, for example, the value of 6000 feet is expressed as 060 and the value of 7100 feet is expressed as 071. For geographical sections that are not surveyed, the field will contain the alpha characters UNK for Unknown.

### 5.143-x89 COMMENTARY

MORA values are generally not provided in government source and are calculated by the data supplier using the formula indicated in the Source/Content paragraph. There are, however, some governments that do provide off route altitude data and a data supplier may elect to use the government source values in their data services.

Used On:

Grid MORA Records

Length:

3 characters

Character Type:

Alpha/numeric

Examples:

010, 071, 100, 123, UNK

## 5.144 Center Fix (CENTER FIX)

Definition/Description: When used on Airport and Heliport MSA Records, the Center Fix field represents the MSA Center; that point on which the MSA is predicated. When used on Terminal Procedure Records, it can be used in three ways:

When the terminal procedure has an MSA defined, the field will contain the identifier of the fix on which the MSA is predicated. This will serve as a pointer to the specific MSA Record. For Approach Procedures, this pointer will be populated on the first leg of the final approach coding unless the government source MSA is 'by transition' in which case the pointer is populated on the first leg of each transition. For SIDs and STARs, this pointer will be populated on the first leg of each transition which it applies.

When the terminal procedure has a TAA defined, the field will contain the identifier of the fix on which the TAA Sector is predicated. This will serve as a pointer to the specific TAA Record. This will be populated on the first record for each approach transition.

When used in a terminal procedure record defined by an RF Path Terminator, the field will contain the fix that defines the center of the constant radius arc.

Source/Content: When used as MSA Center, the field will contain the identification of the navigation facility, Enroute Waypoint, Terminal Waypoint, Runway, Airport Reference Point or Heliport Reference Point, upon which the MSA coverage radius is predicated. Such content will be derived from official government sources. When used as a TAA IAF Waypoint, the field contains the official identifier of the waypoint for which the TAA Sector is defined. They will be derived from official government sources. When used as Radius Center, the field will contain the identification of the navigation facility, Enroute Waypoint, or Terminal Waypoint used to define the center point of the RF turn.

Used On:

Airport and Heliport MSA Records, Airport and Heliport TAA Records, Airport and Heliport SID/STAR Approach Procedure Records

Length:

5 characters max

Character Type:

Alpha/numeric

Table 5-24 - GRID MORA Sample

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

Table 5-24 - GRID MORA Sample

Table 5-2 4 shows a sample of the Grid Mora Table as it would appear in the file. The table starts at N00/E000 and ends at N14/E029, and is blocked at intervals of sixty minutes. The values shown in the Start Lat and Start Long fields are the lower left corner of a one-degree Lat/Long box. The values shown at the bottom of the table are for illustration purpose only and show the Longitude of the lower corner for the MORA values in the table. The values from longitude E007 thru E028 have been omitted from this illustration.

The text was revised to allow RF center fixes.

## 5.145 Radius Limit

Definition/Description: The altitude shown in the Sector Altitude field provides a 1000-foot obstacle clearance with a specified radius from the navigational facility/fix. The Radius Limit, field allows the radius to be specified.

Source/Content: Radius limits will be derived from official government sources. Values will be shown in whole nautical miles.

Used On:

Airport and Heliport MSA Records

Length:

2 characters

Character Type:

Numeric

Examples:

25, 30

## 5.146 Sector Bearing (SEC BRG)

Definition/Description: When used on MSA Records, the Sector Bearing contains beginning and ending bearing values, referenced to the MSA Center, for each sector of the MSA. When used on TAA records, the Sector Bearing contains the beginning and ending bearings that define a TAA Area and are referenced to the Sector Bearing Reference Waypoint.

Source/Content: Sector Bearing information will be derived from official government source. Each Sector Bearing field is made up of the start of sector bearing and the end of sector bearing. The values are provided in whole degrees. The first three

digits define the start of the sector, the last three digits the end of the sector. For MSA, the values are sector dividing values and the end value of one sector is used as the start value of the next sector. For TAA, the values are inclusive. When multiple Sector Bearings are included in the same MSA or TAA record, they are provide starting with the lowest numbered values and in clockwise order. For MSA that include multiple radii and sector altitudes for the same sector, the Sector Bearings are repeated with the additional radius and altitude data before defining the next sector. For an MSA that is a provided in official government source as an un sectorized circle, both the start and the end sector bearing values are set to 180. Sector Bearing values may be magnetic or true bearings. The Mag/True Indicator in the MSA or TAA will provide this information. See Figure 5-7.

Used On:

Airport and Heliport MSA and TAA Primary Records 6 characters

Length:

Character Type:

Numeric

Examples:

060140, a Sector that starts at 060 degrees and continues clockwise to end at 140 degrees.

140060, a Sector that starts at 140 degrees and continues clockwise to end at 060 degrees

180180, a sector that starts at 180 degrees and continues clockwise to end at 180, a full circle MSA, no sectorization

## 5.147 Sector Altitude (SEC ALT)

Definition/Description: When used on MSA records, the Sector Altitude provides a 1000-foot obstacle clearance within the specified sector. When used on TAA records, the Sector Minimum Altitude is the minimum altitude for that sector, providing obstacle clearance compatible with the instrument procedures with which the TAA is associated, generally 1000 feet or more as necessary in mountainous areas. Flight crews are expected to fly direct to the initial approach fix in the record at the appropriate sector altitude unless otherwise instructed by ATC.

Source/Content: Sector Altitude values are derived from official government source and are provided in hundreds of feet. When the official government source does not provide a Sector Altitude for one or more sectors of an MSA, the value is provided as 999. See Figure 5-7.

Used On:

Airport and Heliport MSA Records and TAA Primary Records

Length:

3 characters

Character Type:

Numeric

Examples:

010 = 1000ft, 025 = 2500, 100= 10,000 999 = no sector altitude

Output Data:

0190690303006909403020069094033300941560302015626003030260321030202 603210343032135903010321359037303590190302535901905330

**Un-Sectorized MSA:**

Output Data: 18018003125, where 180180 represents the Sector Bearings, 031 the Sector Altitude, and 25 the Sector Radius

**Sectorized MSA, Single Radius:**

Output Data: 0902700222527009002825

**Sectorized MSA, Multiple Radius:**

**No Data Sectors:**

Output Data:

0972740302527409799925

020200030252002600502526002099925

Figure 5-7 - MSA Data Examples

Note 1: The MSA example requires a total of 11 data sets of Bearing/Altitude/Radius to provide all of the information. The current MSA Primary Record only allows for 7 sets. The additional data sets would be provided in a continuation record that is formatted exactly the same as the Primary.

## 5.148 Enroute Alternate Airport/Heliport (EAA)

Definition/Description: The Enroute Alternate Airport/Heliport field identifies the most suitable emergency airport or heliport along a Company Route or Helicopter Operations Company Route.

Source/Content: This field is determined by the user airline and will contain the Airport or Heliport Ident.

Used On:

Company Route, Helicopter Operations Company Route records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

KDEN, EGKK, EDFF

## 5.149 Figure of Merit (MERIT)

Definition/Description: The Figure of Merit field is used to denote those situations where information has been made available that indicate a VHF Navaid facility is usable beyond the range value that is specified through the Class field. It is also used to denote when a VHF Navaid contained in the database is not available for operational use, i.e., is out of service and to flag a VHF Navaid that is not included in a civilian international NOTAM system.

Source/Content: Actual Field Entry Values are not contained in official government source but rather are derived values based on usage, class, availability, etc. These may be further adjusted by input from actual users. When the field content is equal to the information in the VHF Navaid Class field (Section 5.35), this is an indication that no information has been received indicating usable ranges beyond the Class specification

The content will be as defined in the table below.

|   Field Content | Description                                               |
|-----------------|-----------------------------------------------------------|
|               0 | Terminal Use (generally within 25NM)                      |
|               1 | Low Altitude Use (generally within 40NM)                  |
|               2 | High Altitude Use (generally within 130NM)                |
|               3 | Extended High-Altitude Use (generally beyond 130NM)       |
|               7 | Navaid not included in a civil international NOTAM system |
|               9 | Navaid Out of Service                                     |

Used On:

VHF Navaid Records

Length:

1 character

Character Type:

Numeric

## 5.150 Frequency Protection Distance (FREQ PRD)

Definition/Description: The Frequency Protection Distance field provides an indication of the distance to the next nearest NAVAID on the same frequency.

Source/Content: The distance to the next NAVAID will be computer generated values. Values will be entered on NAVAID with DME or TACAN equipped facilities only and will indicate the distance, in nautical miles, to the next nearest DME or TACAN equipped facility. Maximum relevant value will be 600 nautical miles.

Used On:

VHF Navaid records

Length:

3 characters

Character Type:

Alpha/numeric

Examples:

030, 150, 600

## 5.151 FIR/UIR Address (ADDRESS)

Definition/Description: The FIR/UIR Address field contains the four-character communications address of the FIR/UIR to supplement the FIR/UIR Ident.

Source/Content: When addressing ATS messages to the ATS Center in charge of a FIR or UIR, a three-letter designator followed by a filler of X or by a letter representing a department or division within the organization addressed should be used. The three-letter designators are to be those defined in ICAO Document 8585, Designators for Aircraft Operating Agencies, Aeronautical Authorities 2 and Services. ICAO Document 7910, Location Indicators, Address of Centers in charge of FIR/UIR, states that when addressing ATS messages to the ATS Center in change of a FIR or a UIR, one of the following designators should be added to the location indicator to complete the addressee indicator:

If the message is related to an IFR Flight-ZQZX

If the message is related to a VFR Flight-ZFZX

To satisfy this requirement, unless otherwise stipulated by the user, the following address codes will be used:

ZOZX if related to an Oceanic FIR/UIR.

ZRZX if related to all other FIR/UIRs.

When used on Enroute Communications Records, the content definition above for the FIR/UIR Record is to be applied whenever the FIR/RDO (Section 5.190) field of the Enroute Communications Record contains an Information Region Identifier. In all other cases, the Address field of the Enroute Communications Record will be blank.

Used On:

FIR/UIR and Enroute Communications records

Length:

4 characters

Character Type:

Alpha

Examples:

ZOZX, ZRZX

## 5.152 Start/End Indicator (S/E IND)

This section deleted by Supplement 21.

## 5.153 Start/End Date

This section deleted by Supplement 21.

## 5.154 Restriction Identifier (REST IDENT)

Definition/Description: The Restriction Identifier is used to assign a unique identifier to a restriction record and to multiple restrictions records for a particular route or route segment.

Source/Content: Restriction Identifiers are assigned during the data file assembly. Initially the identifier will be assigned in sequence with the first restriction assigned the numeric value 001, the second 002, the third 003, etc. If a restriction record is removed, only that record is deleted and there will be no effect on the other identifiers for that airway; i.e., if record 002 is deleted, records 001 and 003 will retain their identifiers. If a new restriction is added, within a few cycles of the deletion of 002, it will use the next higher number even if there are gaps in the sequence of identifiers.

Used On:

Airway Restriction and Airway Restriction Continuation records

Length:

3 characters

Character Type:

Numeric

Examples:

001, 002, 003

5.155    Intentionally Left Blank

5.156    Intentionally Left Blank

## 5.157 Airway Restriction Start/End Date (START/END DATE)

Definition/Description: The Airway Restriction Start Date field is used to indicate the earliest GMT date at which the restriction takes effect. The Airway Restriction End Date is used to indicate the latest GMT date at which the restriction is still in effect. This date information may be supplemented by Time of Operation information contained in an Airway Restriction Record, Type AE or TC. When no AE or TC record exists for the Restriction Identifier, the Start time is 0000 GMT and the end time is 2359 GMT of the dates indicated.

Source/Content: When entered, start dates and end dates will be in the format DDMMMYY. If the YY portion is equal to blanks, the restriction is valid every year. When the start date is equal to blanks, the restriction is valid with immediate effect. When the end date is equal to blanks, the restriction is valid until further notice.

Used On:

Enroute Airway Restriction records

Length:

7 characters

Character Type:

Alpha/numeric

Examples:

15JAN92, 15 JAN (blank)

5.158    Intentionally Left Blank

5.159    Intentionally Left Blank

## 5.160 Units of Altitude (UNIT IND)

Definition/Description: The Units of Altitude field is used to indicate the units of measurement for the values in the Restriction Altitude fields.

Source/Content: The actual values are derived from official government sources and expressed as one of the following codes.

| Field Content   | Description                                                 |
|-----------------|-------------------------------------------------------------|
| F               | Restriction Altitudes are expressed in hundreds of feet     |
| K               | Restriction Altitudes are expressed in metric Flight Levels |
| L               | Restriction Altitudes are expressed in feet Flight Levels   |
| M               | Restriction Altitudes are expressed in tens of meters       |

Used On:

Airway Restriction records and Airway Restriction Continuation

Records

Length:

1 character

Character Type:

Alpha

## 5.161 Restriction Altitude (RSTR ALT)

Definition/Description: The Restriction Altitude fields are used to specify the altitude profile for a specific restriction.

Source/Content: Altitudes will be derived from official government sources and entered in hundreds of feet, tens of meters, standard or metric Flight Levels. The units used are determined through the Units of Altitude field. Altitudes are expressed in ascending order. All altitude fields after a blank altitude will also be blank.

Used On:

Airway Restriction, Airway Restriction Continuation records

Length:

3 characters

Character Type:

Numeric

Examples:

310 (standard FL310 or metric FL3199m or 31000 feet or 3100 meters)

090 (standard FL90 or metric FL900m or 9000 feet or 900 meters)

## 5.162 Step Climb Indicator (STEP)

Definition/Description: The Step Climb Indicator field is used to indicate if step climb up or down is permitted.

Source/Content:

| Field Content   | Description                        |
|-----------------|------------------------------------|
| B               | Step climb up or down is permitted |
| D               | Only step climb down is permitted  |
| N               | No step climb is permitted         |
| U               | Only step climb up is permitted    |

Used On:

Airway Restriction and Airway Restriction Continuation records

Length:

1 character

Character Type:

Alpha

## 5.163 Restriction Notes

Definition/Description: The Restriction Notes field may contain any restriction not otherwise covered by the altitude or time restriction.

Source/Content: Restriction notes will be derived from official government sources.

Used On:

Airway Restriction continuation records

Length:

104 characters

Character Type:

Alpha/numeric

Examples:

AVAILABLE FOR WESTBOUND DEPARTURES FROM GATWICK. EASTBOUND AND OVER-FLIGHTS BY ATC ONLY. REROUTING MUST BE EXPECTED MON-FRI 1800-2400 DUE TO MILITARY TRAFFIC.

## 5.164 EU Indicator (EU IND)

Definition/Description: The EU Indicator field is used to identify those Enroute Airway records that have an Airway Restriction record without identifying the restriction.

Source/Content: The field will contain the alpha character Y when a restriction for the segment is contained in the restriction file or a blank when no restriction record exists.

Used On:

Enroute Airways records

Length:

1 character

Character Type:

Alpha

## 5.165 Magnetic/True Indicator (M/T IND)

Definition/Description: The field has multiple definitions. For Airport and Heliport Primary Records, it is used to indicate that all bearing and course detail for that airport/heliport are included in the database with a reference to either Magnetic North or to True North. The field is blank in Airport/Heliport Record when the database contains a mix of magnetic and true bearing or course information for the airport. The Magnetic/True Indicator field is also used to indicate if the Course From and Course To fields of the Cruise Table record and the Sector Bearing fields of the MSA and TAA record are in magnetic or true degrees.

Source/Content: In Airport/Heliport Records, the field will contain the alpha character M if all bearing and course detail for the airport/heliport are provided in magnetic or the alpha character T if all bearing and course detail for the airport/heliport are provided in true. Setting the airport/heliport to T does not indicate that courses and bearings at that airport/heliport do not need to be coded as true. True coding of courses and bearings must still comply with the true coding described in those sections. The field will be blank if bearing and course data are provided in a mix of magnetic and true for the airport. Cruise Table Courses, MSA, and TAA Sector Bearings will be derived from official government source. The field will contain the alpha character M if the Course From/To or Sector Bearings are magnetic. It will contain the alpha character T if the courses/bearings are true.

Used On:

Airport, Heliport, Cruise Table and Airport and Heliport MSA Records, and Airport and Heliport TAA Record

Length:

1 character

Character Type:

Alpha

## 5.166 Channel

Definition/Description: The Channel field specifies the channel of the Azimuth, Elevation and Data transmissions for the MLS identified in the MLS Identifier field of the record.

Source/Content: Channels are derived from official government sources and range from 500 to 699.

Used On:

MLS records

Length:

3 characters

Character Type:

Numeric

## 5.167 MLS Azimuth Bearing (MLS AZ BRG) MLS Back Azimuth Bearing (MLS BAZ BRG)

Definition/Description: The MLS Azimuth Bearing and the MLS Back Azimuth Bearing fields define the inbound magnetic final approach course assigned to the center of the Azimuth or Back Azimuth Coverage (see Section 5.172).

Source/Content: The fields are populated with the inbound magnetic course information derived from official government source documents, generally the inbound course for a given approach procedure to a given runway considered the primary use of the MLS facility. The values are provided in degrees and tenths of degrees with the decimal point suppressed. Should the source value be provided with the intent to be used only in degrees true, the last character of the field will contain a T in place of the tenths of a degree value.

Used On:

MLS and MLS Continuation records

Length:

4 characters

Character Type:

Numeric

Examples:

0550, 0155, 015T

## 5.168 Azimuth Proportional Angle Right/Left (AZ PRO RIGHT/LEFT) Back Azimuth Proportional Angle Right/Left (BAZ PRO RIGHT/LEFT)

Definition/Description: The MLS Azimuth and Back Azimuth Proportional Angle fields define the limits of proportional guidance of the azimuth transmitter signal on the right and left side of the MLS Azimuth bearing (Section 5.167). The BAZ is

identical to the AZ and provides guidance for Missed Approach Procedures and departures. See figure under Section 5.172.

Source/Content: Azimuth Proportional angles will be derived from official government publications and entered in whole degrees.

Used On:

MLS and MLS Continuation records

Length:

3 characters

Character Type:

Numeric

Examples:

040, 025, 015

## 5.169 Elevation Angle Span (EL ANGLE SPAN)

Definition/Description: The Elevation Angle Span field defines the scan of the elevation transmitter signal between the lower and upper limits.

Source/Content: Elevation angle span limits will be derived from official government publications and entered in degrees and tenths of degrees with the decimal point suppressed.

Used On:

MLS records

Length:

3 characters

Character Type:

Numeric

Examples:

300, 150

## 5.170 Decision Height (DH)

This section deleted by Supplement 20.

## 5.171 Minimum Descent Height (MDH)

This section deleted by Supplement 20.

## 5.172 Azimuth Coverage Sector Right/Left (AZ COV RIGHT/LEFT) Back Azimuth Coverage Sector Right/Left (BAZ COV RIGHT/LEFT)

Definition/Description: The Azimuth Coverage Sector fields define the limit of the azimuth transmitter signal on the right and left side of the MLS Bearing (Section 5.167). The Back-Azimuth Coverage Sector is identical to the Azimuth Coverage Sector and provides guidance for Missed Approach Procedures and departures.

Source/Content: Azimuth Coverage Sectors will be derived from official government publications and entered in whole degrees.

Used On:

MLS and MLS Continuation records

Length:

3 characters

Character Type:

Numeric

Examples:

040, 062, 110

### 5.172-x90 COMMENTARY

The Azimuth Coverage Sector includes the Proportional Guidance Sector and the Clearance Guidance Sector as illustrated in below.

## 5.173 Nominal Elevation Angle (NOM ELEV ANGLE)

Definition/Description: The Nominal Elevation Angle field defines the normal glide path angle for the MLS installation.

Source/Content: Glide Path angles from official government sources are entered into the field in tens of degrees, tenths of a degree, and hundredths of a degree with the decimal point suppressed.

Used On:

MLS records

Length:

4 characters

Character Type:

Numeric

Examples:

1000, 0275

## 5.174 Restrictive Airspace Link Continuation (LC)

Definition/Description: The Restrictive Airspace Link Continuation field is used to indicate cases where it is not possible to store all Enroute Airway to Restrictive Airspace Links in the Flight Planning Continuation Record defined in 4.6.3 (more than four area links required).

Source/Content: When an additional Continuation Record (as defined in Section 4.1.6.4) is required to provide further Enroute Airway to Restrictive Airspace Links, this field will contain the alpha character Y to indicate that status.

Used On:

Enroute Airway Flight Planning Continuation records

Length:

1 character

Character Type:

Alpha

## 5.175 Holding Speed (HOLD SPEED)

Definition/Description: The Holding Speed will be the maximum speed in a holding pattern.

Source/Content: The speed limit will be derived from official government sources. If the value is different from the limit given with ICAO rules, it will be shown in knots, else the field will be blank.

Used On:

Holding Pattern record

Length:

3 characters

Character Type:

Numeric

Examples:

250, 015

## 5.176 Pad Dimensions

Definition/Description: The Pad Dimensions field defines the landing surface dimensions of the helicopter landing pad. The pad may be described as a runway, a rectangle or a circle.

Source/Content: Pad dimensions will be derived from official government sources and entered into the field in feet with a resolution of one foot.

When the pad is rectangular, the first five digits define one side of the landing pad and the last three digits the other side of the pad, e.g., 00060120 indicates the pad is 60 feet by 120 feet.

When the pad is circular, the first five digits define the diameter of the pad and the last three digits will be zeros, e.g., 00080000 indicates a pad that is 80 feet in diameter.

When the pad is a runway, the first five digits define the length of the pad and the last three digits the width of the pad, e.g., 12500120 indicates a pad that is 12500 feet long and 120 feet wide.

Used On:

Airport Helipad Records, Heliport Helipad Records

Length:

8 characters

Character Type:

Numeric

Examples:

00060060, 10220150, 00040040, 00080000

## 5.177 Public/Military Indicator (PUB/MIL)

Definition/Description: Airports can be classified into four categories, airports open to the general public, military airports, joint use civil and military, and airports closed to the public. This field permits these airports to be categorized by their use.

Source/Content: Airport data is obtained from official government sources and their use is defined in these civil and or military publications.

| Field Content   | Description                                          |
|-----------------|------------------------------------------------------|
| C               | Airport/Heliport is open to the public (civil)       |
| M               | Airport/Heliport is military airport                 |
| P               | Airport/Heliport is not open to the public (private) |
| J               | Airport is joint Civil and Military                  |

Used On:

Airport and Heliport records

Length:

1 character

Character Type:

Alpha

## 5.178 Time Zone

Definition/Description: The standard time zone system is based on the division of world into 24 zones, each of 15 degrees longitude. The zero-time zone is entered at Greenwich meridian with longitudes 7 degrees, 30 minutes West and 7 degrees, 30 minutes east, and there is no difference in the standard time of this time zone and Greenwich Mean Time. Time zones are designated by letters of the alphabet and numbers by which the standard time of each zone differs from that at Greenwich.

Source/Content: Time zones will be derived from official Time Zone Charts of the World, or individual time zones can be published based on country. The first character of the field indicates the time zone observed by the airport. Time zones are indicated by a letter of the alphabet and numbers according to the following table:

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

The second and third characters indicate, in minutes, that the time observed by the airport/heliport must be adjusted from the hour by the number of minutes indicated.

When the 1 st character is a 1 or 2, then the 2 nd and 3 rd characters will always be blank.

Used On:

Airport and Heliport records

Length:

3 characters

Character Type:

Alpha/numeric

Examples:

India falls in the E (-5) and F (-6) time zones; however, the time zone observed in all of India is E30 (-5 hours and 30 minutes). For any country falling into the M or Y time zone and observing a time equal to the next greater time zone, the adjustment of 1 hour will be indicated by 60 in the second and third positions.

## 5.179 Daylight Time Indicator (DAY TIME)

Definition/Description: The Daylight Time Indicator field is used to indicate if the airport observes Daylight or Summer time when such time changes are in effect for the country or state the airport resides in.

Source/Content: Countries and states that observe Daylight time will be obtained from official publications and the field will contain the alpha character Y if airport observes Daylight or Summer time. The field will contain the alpha character N if the airport does not observe Daylight time or if it is unknown.

Used On:

Airport and Heliport records

Length:

1 character

Character Type:

Alpha

## 5.180 Pad Identifier (PAD IDENT)

Definition/Description: The PAD Identifier field identifies the helipad described in the heliport records, helipad field, or that pad served by ILS/MLS described in the Airport and Heliport ILS/MLS records.

Source/Content: PAD Identifiers will be derived from official government publications when available. If not available from source, unique identifiers will be assigned by the data supplier.

Used On:

Airport and Heliport Localizer and Glideslope Records, Airport and Heliport Localizer Marker Primary Records, GLS Primary Records, GBAS Path Point Primary Records, Airport and Heliport Helipad Records, Helicopter Operations Company Routes, and MLS Records

Length:

5 characters max

Character Type:

Alpha/numeric

Examples:

Source Supplied - PADA1, NWPAD, ALPHA, A1 Data Supplier - HELO1, HELO2, HELO3

## 5.181 H24 Indicator (H24)

Definition/Description: The 24H Indicator field is used to indicate whether a communications service frequency is available for use on a continual, i.e., 24 hours a day, seven days a week, basis or not.

Source/Content: Hours of operation for a communications service frequency are derived from official government publications. The field will contain the character Y if the frequency is continually available, the character N if the frequency is not continually available and other Times of Operation are provided or the character U are unknown.

If the field is set to Y, the Time Code (5.131) in the Primary Extension Continuation Record for the frequency will be set to C or H. If the field is set to N, the Time Code in the Primary Extension Continuation Record for the frequency will be set to N or P. If the field is set to U, the Time Code will also be set to U.

Used On:

Enroute/Airport and Heliport Communications records

Length:

1 character

Character Type:

Alpha

## 5.182 Guard/Transmit (G/T)

This section is withdrawn. The status of transmits only, receives only or both for a given frequency is provided by transmit and receive frequency columns of the communications records.

## 5.183 Sectorization (SECTOR)

Definition/Description: The Sectorization field is used to define the airspace sector a communication frequency is applicable for when an airport defines sectors by bearing from the same point.

Source/Content: Source/Content: Sectors are derived from official government publication. Each Sectorization will contain two bearings, expressed in whole degrees, of the sector being defined. The first three numeric characters define the beginning bearing from the station and the last three characters define the ending bearing from the station, moving in a clockwise direction from start to end. If the sector is a complete circle, this field will be set to 180180. The radius of the circle will be provided as the Communications Distance, Section 5.188.

Sectors which are defined by cardinal directions may be translated to bearings using the table below.

If the sectors are not defined by bearings, then the sectorization will be shown in narrative form in an Airport Communications Continuation Record.

Sector bearing data relates to the lat/long location of the Sector Facility (5.185). If no Section Facility is provided in the communications record, the sector bearing data relates to the lat/long included in the same communications record.

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

If the sectors are not defined by bearings or cardinal directions, the sectorization will be shown in narrative form in a Continuation Record.

Used On:

Airport Communication records

Length:

6 characters

Character Type:

Alpha/numeric

Examples:

010189, 190009

## 5.184 Communication Altitude (COMM ALTITUDE)

Definition/Description: The Communications Altitude 1 and Altitude 2 fields are used to provide information on use of communications services frequencies with reference to specific altitudes. If the communications record in which Communications Altitude data is provided includes Sectorization data (5.183), the altitude data is valid only for the specific Sector.

Source/Content: Communications Altitude information will be derived from official government source documentation. The fields are to be processed in conjunction with the Communications Altitude Description field. The field will contain altitude expressed in hundreds of feet. The Communications Altitude 1 field will contain a value when the Communications Altitude Description contains the character + (plus) or - (minus). The Communications Altitude 1 field may contain a value when the Communications Altitude Description is blank, indicating that communications service/frequency is used at a specific altitude only. The Communications Altitude 1 and Altitude 2 fields will contain values when the Communications Altitude Description contains the character B.

Used On:

Enroute, Airport, and Heliport Primary Communications

Records

Length:

3 characters

Character Type:

Alpha/numeric

Examples:

050 (5000 feet), 245 (24500 feet)

## 5.185 Sector Facility (SEC FAC)

Definition/Description: The Sector Facility field is used to define the Navaid or Airport upon which the information in the Sector (5.183) field is based.

Source/Content: Sector related facility information will be derived from official government sources. The field will contain the official Navaid or Airport identifier.

Used On:

Airport and Heliport Communications Records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

IOC, COS, DEN, KJFK

## 5.186 Sectorization Narrative

Definition/Description: The Sectorization Narrative field is used to define sectors of operations for communications services on specific frequencies in a narrative format when that data cannot be formatted in the Sectorization (5.183) field. The field may also be used to qualify the Sectorization information. This is usually the and situation, meaning the communications service/frequency is to be used in the defined sector and in some other defined situation that cannot be formatted such as Sectorization. An example is 309127 in the Sectorization field and When Departing Runway 31L/R in the Narrative field.

Source/Content: Sector Narrative data will be derived from official government source.

Used On:

Airport and Heliport Sector Narrative Continuation Records

Length:

60 characters

Character Type:

Alpha/numeric

Examples:

North Complex, Departures to North, When Rwy 09/27 is Active

## 5.187 Distance Description (DIST DESC)

Definition/Description: The Distance Description field will designate whether a Communications frequency is to be used from the facility out to a specified distance or from a specified distance and beyond in the Airport Communications Record. In the VHF Navaid Limitation Continuation Record and the TACAN Only Navaid Limitation Continuation Record, the field is used to define whether the limitation applies from the navaid out to a specified distance or from a specified distance and beyond.

Source/Content: The field will contain the character - when the communications frequency or navaid limitation is out to a specified distance. When the field content is +, then the communications frequency is used or the navaid limitation applies beyond a specified distance. When the field is blank, no restrictions/limitations apply.

Used On:

Airport Communications Records, VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation

Continuation Record

Length:

1 character

Character Type:

Alpha

## 5.188 Communications Distance (COMM DIST)

Definition/Description: The Communications Distance field is used to define the distance restriction a communication frequency is to be used within or beyond when such restrictions apply. This field is used in conjunction with the Distance Description field.

Source/Content: Distances restrictions are derived from official government publications and will contain a value in nautical miles from the communications facility. If the Distance Description field contains the character -, then the frequency is to be used from the facility to the distance specified. If the Distance Description field contains the character + then the frequency is to be used from the distance specified and beyond. The field will be blank if no restrictions apply.

Used On:

Airport Communications records

Length:

2 characters

Character Type:

Numeric

Examples:

05, 10, 15

## 5.189 Position Narrative

Definition/Description: The Position Narrative field is a textual description of the location of a communications transmitter. This may be the name of a Remote Communications Outlet, a Remote Communications Air/Ground Station or the place name of the geographical location of the transmitter site.

Source/Content: Position Narrative information will be derived from official government source. The field may be blank in cases where the source information is not available.

Used On:

Enroute Communications records

Length:

25 characters

Character Type:

Alpha/numeric

Examples:

CHEYENNE, ABBEVILLE

## 5.190 FIR/RDO Identifier (FIR/RDO)

Definition/Description: The FIR/RDO Identifier field used on Enroute Communications records is the source provided identifier for a communication service as used in message addressing. For Information Regions (FIR/UIR) it is the four-character identifier assigned to the Information Region as published in ICAO Document 7910, Location Indicators. For Flight Service Stations, it is the three or four-character identifier assigned to the station by the relevant authority. For other communications services established for enroute use and not addressable under the Information Region, Flight Service Station concept, it is the identifier assigned by the relevant authority to that station for the purpose of addressing message traffic.

Source/Content: The field content will be derived from official government source documentation as indicated above. Only three or four-character identifiers are to be used.

Used:

Enroute Communications records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

KZDN, DEN

## 5.191 Triad Stations (TRIAD STA)

Deleted by Supplement 14.

## 5.192 Group Repetition Interval (GRI)

Deleted by Supplement 14.

## 5.193 Additional Secondary Phase Factor (ASF)

Deleted by Supplement 14.

## 5.194 Initial/Terminus Airport/Fix

Definition/Description: The Initial Fix and the Terminus Fix fields are used to define the departure airport or initial fix and the destination airport or terminus fix of a preferred route.

Source/Content: For preferred and preferential routes, these fields will normally contain an airport identifier. For North America Routes for North Atlantic Traffic Common portion routes, these fields may contain NAVAID or waypoint identifiers. For North America routes for North Atlantic Traffic - Non-common portion routes, these fields may contain airport, NAVAID or waypoint identifiers. These fields will be entered on the first sequence of a route only, except when the route serves more than one airport, in which case the additional airports are shown on succeeding sequences.

Used On:

Preferred Route record

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

KDEN, CYUL, DEN, YUL, COLOR

Entries for Metro Area New York to Atlanta

Seq 010 KJFK K6 KATL K7

Seq 020 KLGA K6

Seq 030KEWR K6

Entries for Atlanta to Metro Area New York

Seq 010KATL K7 KJFK K6

Seq 020LGA K6

Seq 030KEWR K6

## 5.195 Time of Operation

Definition/Description: The Time of Operation field is used to indicate the times of operation of a Facility or Restriction.

Source/Content: The times of operation are derived from official government source. Each Time of Operation group contains the definition of a daily period of operations within a calendar week.

The first two positions identify days of the week, with Monday equal to 1 and Sunday equal to 7. A single day, for example, Monday, is depicted as 01. A consecutive series of days, for example Monday through Friday, is depicted as 15. Non-consecutive days require multiple Time of Operation entries. The remaining 8

characters define a starting time of four characters and an ending time of four characters. These times are in the format HHMM (H= hours, M= minutes) using a 24-hour time system. For example, 00012350 starts at one minute after midnight and ends at 10 minutes before midnight. 07152000 starts at 07:15 hours and ends at 20:00 hours.

Times of Operation can also be expressed in terms of Sunrise (SR) and Sunset (SS). When a Time of Operation is defined as starting at or ending at Sunrise, that time is specified as 000R. When a Time of Operation is defined as starting at or ending at Sunset, that time is specified as 000S. When a Time of Operation is defined as starting at or ending at a certain number of hours/minutes before or after Sunrise or Sunset, those times are specified as in the following examples:

030R for 30 minutes before Sunrise or R030 for 30 minutes after Sunrise.

100R for 1 hour before Sunrise or R100 for 1 hour after Sunrise.

030S for 30 minutes before Sunset or S030 for 30 minutes after Sunset.

100S for 1 hour before Sunset or S100 for 1 hour after Sunset

Of the three digits associated with R or S, the first is an expression of hours, the second and third an expression of minutes. 1 hour, 30 minutes would be 130, 2 hours, 15 minutes would be 215, etc.

When multiple definitions are required to fully define the Time of Operation for a given calendar week, these are coded as second and subsequent Time of Operation fields.

**Examples:**

A restriction valid on Mondays, Wednesdays and Fridays only, 0700 to 1700, would require three Time of Operation entries, one for 01 (Monday), one for 03 (Wednesday), one for 05 (Friday), and would be expressed as 0107001700, 0307001700, and 0507001700.

A continuous restriction, starting on Monday at 0700 and ending on Friday at 1700 would require three Time of Operation entries, one for Monday of 0107002359, one for Tuesday through Thursday of 2400002359, and one for Friday of 0500001700.

When the times to be defined go over midnight, the second four characters of time information are valid on the actual ending day. For example, a Time of Operation of Monday through Friday, 1700 to 0300 actually ends on Saturday and would be shown as 1617000300, not 1517000300.

Used On:

Enroute Airway Restriction Primary and the following Continuation Records - Airport/Heliport/Enroute Communications, Restrictive Airspace, Preferred Route, Enroute Airway Restrictions, and Controlled Airspace 10 characters

Length:

Character Type:

Alpha/numeric

## 5.196 Name Format Indicator (NAME IND)

Definition/Description: The Name Format Indicator field is used to describe the format of the Waypoint Name/Description field (5.43). This field will be formatted

according to the rules described in Chapter 7 of this specification, Waypoint Naming Conventions.

Source/Content: Values for this field have no official government source and are adjusted by input from the following table. Code may not be used in combination between columns.

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

Note 1: Column 98 is reserved for future expansion of the NameFormat-Indicator concept.

Note 2: The T indicator will be used with all fixes established in accordance with Chapter 7, Section 7.2.6, Terminal Waypoints, in this document.

Used On:

Enroute Waypoints, Airport, and Heliport Terminal Waypoints

Length:

3 characters

Character Type:

Alpha

## 5.197 Datum Code (DATUM)

Definition/Description: The Datum Code field defines the Local Horizontal Reference Datum to which a geographical position, expressed in latitude and longitude, is associated.

Source/Content: Local Horizontal Reference Datums will be derived from official government documentation. The Datum Code field will contain a three-letter code corresponding to that government publication. A listing of valid three letter codes is contained in Attachment 2 to this specification.

Used On:

VHF Navaid, NDB Navaid, Terminal NDB, Enroute Waypoint, Airport, Fan Marker, Heliport, and GLS Transmitter Records 3 characters

Length:

Character Type:

Alpha

Examples:

AGD, NAS, WGA

## 5.198 Modulation (MODULN)

Definition/Description: The Modulation field will design the type of modulation for the frequency in the Communication Frequency (5.103) field.

Source/Content: The field contains the following information:

The field will be set to A unless the source documentation specifies otherwise.

| Field Content   | Description                   |
|-----------------|-------------------------------|
| A               | Amplitude Modulated Frequency |
| F               | Frequency Modulated Frequency |

Used On:

Enroute, Airport, and Heliport Communication Records

Length:

1 character

Character Type:

Alpha

## 5.199 Signal Emission (SIG EM)

Definition/Description: High Frequency (HF) signals used in aeronautical communications can be the complete signal or a portion of the signal, called a sideband. The Signal Emission field will designate for each HF Frequency what emission is used.

Source/Content: The field will be set to 3 unless the source documentation specifies otherwise. The field content contains the following information:

Note: The field is blank on records with frequencies that are not HF, see Section 5.104.

| Field Content   | Description                               |
|-----------------|-------------------------------------------|
| 3               | Double Sideband (A3)                      |
| A               | Single sideband, reduced carrier (A3A)    |
| B               | Two Independent sidebands (A3B)           |
| H               | Single sideband, full carrier (A3H)       |
| J               | Single sideband, suppressed carrier (A3J) |
| L               | Lower (single) sideband, carrier unknown  |
| U               | Upper (single) sideband, carrier unknown  |

Note: The field is blank on records with frequencies that are not HF, see Section 5.104.

Used On:

Enroute, Airport, and Heliport Communications Records 1 character

Length:

Character Type:

Alpha/numeric

## 5.200 Remote Facility (REM FAC)

Definition/Description: The Remote Facility field is used to identify a Navaid or Airport that has been used to provide the latitude/longitude of a communications transmitter, Table 5-1 9 and Notes 7 and 8 in Section 5.37 of this specification.

Source/Content: The field will contain the official identifier of the navaid or airport used, as derived from official government sources.

Used On:

Enroute, Airport and Heliport Communications Records.

Length:

4 characters

Character Type:

Alpha/numeric

## 5.201 Restriction Record Type (REST TYPE)

Definition/Description: The Restriction Record Type field is used to define what type of a restriction is contained in the Enroute Airway Restriction Record in question.

Source/Content: The content of this field should be selected from the following listing of possible codes:

AE = Altitude Exclusion. The record contains altitudes, normally available, that are excluded from use for the Enroute Airway Segment. May be further restricted by Time of Operation information.

TC = Cruising Table Replacement. The record contains only a reference to a Cruising Table Identifier. That Cruise Table will be in force, replacing the Cruise Table Identifier in the Enroute Airway segment records defined in the Start Fix/End Fix fields.

SC = Seasonal Restriction. Record is used to close an Airway or portion of an Airway on a seasonal basis.

NR = Note Restrictions. The record contains restrictions that do not fit the pattern of formatted information allowed by other Restriction Record Types.

Used On:

Enroute Airway Restriction Records

Length:

2 characters

Character Type:

Alpha

## 5.202 Exclusion Indicator (EXC IND)

Definition/Description: The Exclusion Indicator field is an indication of how the altitudes contained in the Cruising Table record referenced by the Airway segment(s) are restricted. This is an all altitude restriction, further defined by direction of flight. These codes will not be used when certain altitudes remain available in a direction of flight.

Source/Content: The content of the field will be one of the codes from the following listing:

A = All altitudes in both directions of flight are restricted. This effectively closes the airway in both direction of flight. All altitudes in the opposite direction in which the Enroute Airway

B = is coded are restricted. This effectively closes the airway in one direction of flight, i.e., the opposite direction from that in which the airway is coded.

F = All altitudes in the direction in which the Enroute Airway is coded are restricted. This effectively closes the airway in one direction of flight, i.e., the direction in which the airway is coded.

(blank) = The restriction is not an all altitude restriction.

Used On:

Enroute Airway Restriction Records

Length:

1 character

Character Type:

Alpha

## 5.203 Block Indicator (BLOCK IND)

Definition/Description: The Block Indicator field is used to specify that the altitudes that follow in the restriction record are either block of altitudes that are restricted (not available for flight) or are individual altitudes that are restricted.

Source/Content: The field will either be set to B indicating an altitude block or I indicating individual altitudes. One or the other or both codes will appear in restriction records that are not Exclusive restrictions (see Section 5.201).

Used On:

Enroute Airway Restriction, Enroute Airway Restriction

Continuation Records

Length:

1 character

Character Type:

Alpha

Examples:

(using multiple columns of the record)

030B090 =

all altitudes from 3000 feet to 9000 feet

(inclusive) are not available

030I090 =

the individual altitudes of 3000 feet and 9000 feet are not available

030I070B130

=

the individual altitude of 3000 feet and all altitudes from 7000 feet to 13000 feet (inclusive) are not available

## 5.204 ARC Radius (ARC RAD)

Definition/Description: The ARC Radius field is used to define the radius of a precision turn. In Terminal Procedures, this is the Constant Radius To A Fix Path and Termination, for RF Leg. In Holding Patterns, this is the turning radius, inbound to outbound leg, for RNP Holding. The ARC Radius field is also used to specify the turn radius of RNP holding patterns included in SID, STAR, and Approach Records as HA, HF, and HM legs.

Source/Content: The content of the field will be derived from official source publications. It will be expressed in nautical miles, tenths, hundredths and thousandths of a nautical mile, with the decimal point suppressed. A conversion to feet of the resolution in nautical miles is equal to an accuracy of 6 feet.

Used On:

SID, STAR and Approach Records, Holding Pattern Records

Length:

6 characters

Character Type:

Numeric

Examples:

246868, 460820, 691231

## 5.205 Navaid Limitation Code (NLC)

Definition/Description: The Navaid Limitation Codes field is used to define the type of limitation to be expected with a VHF Navaid.

Source/Content: The type of limitation will be derived from official government publications and entered using one of the codes defined in the table.

| Content   | Limitation Description                                                             |
|-----------|------------------------------------------------------------------------------------|
| C         | Coverage, the limitations are expressed as maximum reception reliability.          |
| F         | Fluctuations, radial(s) are affected by course fluctuations.                       |
| G         | Roughness, signal roughness experienced in the sector(s) defined.                  |
| N         | Unreliable in the sector(s), at the altitude(s), at the distance(s) defined.       |
| R         | Restricted in the sector(s), at the altitude(s), at the distance(s) defined.       |
| T         | Unusable in the sector(s), at the altitude(s), at the distance(s) defined.         |
| U         | Out of Tolerance in the sector(s), at the altitude(s), at the distance(s) defined. |

Used On:

VHF Navaid Limitation Continuation Records, TACAN-Only

NAVAID Limitation Continuation Record

Length:

1 character

Character Type:

Alpha

## 5.206 Component Affected Indicator (COMP AFFTD IND)

Definition/Description: The VHF Navaid File contains navaids that have one or two components - azimuth and/or distance. Published limitations may apply to one or both of the components. The Component Affected Indicator defines which component(s) are affected by the limitation.

Source/Content: The field content will be entered as indicated in the table based on official government publications. When different limitations apply to different components or components pairs, this will result in multiple Component Affected Indicators for a single navaid to cover the complete limitation. In these cases, the Sequence Number (Section 5.12) will start again with one (01) with each new Component Affected Indicator.

| Content   | Component Description                                                           |
|-----------|---------------------------------------------------------------------------------|
| A         | TACAN or VORTAC, TACAN azimuth component only affected.                         |
| B         | VORDME, or VORTAC, both azimuth and distance component affected.                |
| D         | VORDME or DME, distance component only affected.                                |
| M         | VORTAC or TACAN, TACAN azimuth and distance component affected.                 |
| T         | TACAN or VORTAC, distance component affected.                                   |
| V         | VOR, VORDME or VORDME, VOR azimuth component affected.                          |
| Z         | VORDME, VORTAC or TACAN, VOR and TACAN azimuth and distance component affected. |

Used On:

VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record

Length:

1 character

Character Type:

Alpha

## 5.207 Sector From/Sector To (SECTR)

Definition/Description: The Sector From/Sector To field defines sectorization applicable to the range limited sectors of VOR/DME, VORTAC, or TACAN facilities, using the sector letters from the table. Each sector is described by two characters and is to be interpreted as from the first character, clockwise to the second character.

Source/Content: Field content is derived through interpretation of official government publication information which may be in a variety of formats.

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

Used On:

VHF Navaid Limitation Continuation Records TACAN-Only NAVAID Limitation Continuation Record

Length:

2 characters

Character Type:

Alpha

Examples:

AB, TA, LW

## 5.208 Distance Limitation (DIST LIMIT)

Definition/Description: The Distance Limitation field is used to define the distance(s) from the navaid at which the limitation applies.

Source/Content: Distance Limitations are derived from official government publications. The field will contain one or two distances expressed in nautical miles from the facility. Used together with the Distance Description field, the distances can be provided as indicated in the table of examples. The field will be blank if there are no distances associated with the limitation.

Used On:

VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record

Length:

6 characters

Character Type:

Alpha/numeric

Examples:

| Distance Description   |   Distance Limit - First Three Digits |   Distance Limit - Second Three Digits | Description of Content                          |
|------------------------|---------------------------------------|----------------------------------------|-------------------------------------------------|
| _                      |                                   040 |                                    000 | Limitation valid out to 40NM from the facility. |
| +                      |                                   040 |                                    000 | Limitation valid beyond 40NM from the facility. |
| B                      |                                   100 |                                    040 | Limitation valid between 40NM and 100NM.        |
| Blank                  |                                   040 |                                    000 | Limitation valid at 40NM from the facility.     |

## 5.209 Altitude Limitation (ALT LIMIT)

Definition/Description: The Altitude Limitation field is used to define the altitude(s) at which the limitation applies.

Source/Content: Altitude Limitations are derived from official government publications. The field will contain one to two altitudes, expressed in hundreds of feet MSL. Used together with the Altitude Description field, the altitudes can be provided as indicated in the table of examples. The field will be blank if there are no altitudes associated with the limitation.

Used On:

VHF Navaid Limitation Continuation Records, TACAN-Only NAVAID Limitation Continuation Record

Length:

6 characters

Character Type:

Alpha/numeric

Examples:

| Altitude Description   |   Altitude Limit - First Three Digits |   Altitude Limit - Second Three Digits | Description of Content                           |
|------------------------|---------------------------------------|----------------------------------------|--------------------------------------------------|
| -                      |                                   040 |                                    000 | Limitation valid at or below 4000/FL040.         |
| +                      |                                   040 |                                    000 | Limitation valid at or above 4000/FL040.         |
| B                      |                                   100 |                                    040 | Limitation valid from 4000/FL040 to 10000/FL100. |
| blank                  |                                   040 |                                    000 | Limitation valid at 4000/FL040.                  |

## 5.210 Sequence End Indicator (SEQ END)

Definition/Description: The Sequence End Indicator field is used to define the end of a set of sequences defining a given limitation to a given VHF Navaid Component or Component pair.

Source/Content: Limitations are derived from official government publications. The field will contain the character E in that sequence which is the end of a given limitation.

Used On:

VHF Navaid Limitation Continuation Records, TACAN-Only

NAVAID Limitation Continuation Record

Length:

1 character

Character Type:

Alpha

## 5.211 Required Navigation Performance (RNP)

Definition/Description: Required Navigation Performance (RNP) is a statement of the Navigation Performance necessary for operation within a defined airspace in accordance with ICAO Annex 15 and/or State published rules.

Source/Content: RNP values derived from official government source will be used when available. They are entered into the field in nautical miles (two digits) with a zero or negative exponent (one digit). The contents can be:

When used on Enroute Airway segments, RNP shall apply inbound to the fix when viewed in increasing sequence number order. The RNP applies only to the airway leg on which it is specified. If no RNP values is coded on a segment, there is not a database specified RNP for that segment.

When used on a SID, STAR and Approach Procedure records, the RNP shall apply to the segment on which it is coded. RNP will be coded on every segment where it is specified by source. Lack of an RNP value on a segment indicates no source supplied RNP value was available for that segment.

When used on Holding Patterns, the RNP applies to the holding pattern as defined in the record.

Note 1: The RNP concept will also be applied to defined airspaces, in addition to the specific flight paths as defined above. ARINC 424-13 added an airspace record that includes a reservation for RNP until actual content can be defined.

Note 2: There are no provisions for Vertical RNP in ARINC 424 at this time.

Used On:

Airport and Heliport SID/STAR/Approach, Enroute Airways, Airport and Heliport SID/STAR/Approach Continuation, Controlled Airspace and Holding Pattern Records

Length:

3 characters (see content paragraph)

Character Type:

Numeric

Examples:

990 (equal to 99.0 NM), 120 (equal to 12.0 NM), 013 (equal to 0.001 NM), 302 (equal to 0.3 NM)

## 5.212 Runway Gradient (RWY GRAD)

Definition/Description: The Runway Gradient field indicates an overall gradient in percent, measured from the start of take-off roll end of the runway designated in the record. The gradient is expressed as a positive or negative gradient; positive being an upward and negative being a downward gradient.

Source/Content: The values will be derived from official government source. The first position will be either a + or a - sign indicating upward or downward gradient. Positions 2 through 5 indicate the gradient with the decimal point suppressed. The Maximum Gradient that can be expressed in this field is (+9.000 or -9.000).

Used On:

Runway Records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

+0450, -0300

## 5.213 Controlled Airspace Type (ARSP TYPE)

Definition/Description: The Controlled Airspace Type field is used to indicate the type of controlled airspace, using codes from the table below.

Source/Content: The airspace type should be derived from official government publications. The table below shows the indicators used for the various types. For the USA, the previous applied designations such as TCA are supplied for ease of reference, they are longer officially published.

| Field Content   | Description                                                           |
|-----------------|-----------------------------------------------------------------------|
| A               | Class C Airspace (was ARSA within the USA)                            |
| C               | Control Area, ICAO Designation (CTA)                                  |
| M               | Terminal Control Area, ICAO Designation (TMA or TCA)                  |
| R               | Radar Zone or Radar Area (was TRSA within the USA)                    |
| T               | Class B Airspace (Was TCA with the USA)                               |
| Z               | Class D Airspace within the USA, Control Zone, ICAO Designation (CTR) |

Used On:

Controlled Airspace Records

Length:

1 character

Character Type:

Alpha

## 5.214 Controlled Airspace Center (ARSP CNTR)

Definition/Description: The Controlled Airspace Center field is used to define the navigation element upon which the controlled airspace being defined is predicated, but not necessarily centered. Where the Airspace is not defined then the Region Identifier should be used. In this case, the Controlled Airspace Center will contain the ICAO Identification code for the Controlled Airspace to which the data contained in the record relates.

Source/Content: The Controlled Airspace Center will be determined during the construction of the records. As an example, the New York Class B Airspace (formerly TCA) is centered on the JFK VOR, the LGA VOR and the Newark airport. The Controlled Airspace Center field could contain the Kennedy Airport identifier KJFK as the key for all records describing the New York Class B Airspace. The field may contain a Navaid, Enroute Waypoint, Heliport or Airport Identifier. A Region Identifier content should be derived from official government source where the controlling authority is published or from ICAO Document 7910, Location Indicators. In cases where no official identifier is published that can be used as the Airspace Center where the controlled airspace is used for more than one airport, the Region Identifier can be used.

### 5.214-x91 COMMENTARY

It should be noted that during construction of a Controlled Airspace Center, no published Navaid, Enroute Waypoint, Airport Identifier or Region Identifier may be found to be suitable. Data suppliers may create a center waypoint for use in the Airspace Center field in such cases.

Used On:

Controlled Airspace records

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

OTR, FISHS, KJFK, EGTT

## 5.215 Controlled Airspace Classification (ARSP CLASS)

Definition/Description: The Controlled Airspace Classification field will contain an alpha character indicating the published classification of the controlled airspace, when assigned.

Source/Content: Classification codes will be derived from official government sources. If source does not provide a classification, the field will be blank.

Used On:

Controlled Airspace records

Length:

1 character

Character Type:

Alpha

Examples:

B, C, G, Blank

## 5.216 Controlled Airspace Name (ARSP NAME)

Definition/Description: The Controlled Airspace Name field will contain the name of the controlled airspace when assigned.

Source/Content: Names will be derived from official government sources. The name, if assigned, will be entered in the first record only. If source does not assign a name, the field may be blank.

Used On:

Controlled Airspace records

Length:

30 characters

Character Type:

Alpha/numeric

Examples:

DENVER CLASS B, OAKLAND OCTA

## 5.217 Controlled Airspace Indicator (CTLD ARSP IND)

Definition/Description: The Controlled Airspace Indicator field is used to indicate if an airport is associated with controlled airspace of a terminal type such as a Terminal Control Area (TMA or TCA) Radar Area or Class B or C Airspace within the USA.

Source/Content: Airports lying within or below terminal controlled airspace will be determined through the use of official government publications describing the lateral limits of such airspace. The Controlled Airspace Airport/ICAO fields identify the airport for which terminal-controlled airspace has been included in the Controlled Airspace Section of the file. The Controlled Airspace Indicator field will contain one of the codes from the table below. If an airport is not associated with any terminal controlled airspace of the types in this table, the Controlled Airspace Indicator field will be blank. The Controlled Airspace Airport/ICAO may be identical to or different than the record airport. Although Control Zones (CTR) are provided as Controlled Airspace, no reference to them is made in this manner in the Airport Flight Planning Continuation Record.

| Field Content   | Description                                                            |
|-----------------|------------------------------------------------------------------------|
| A               | The Airport is within or below the lateral limits of Class C Airspace. |
| C               | The Airport is within or below the lateral limits of a CTA.            |
| M               | The Airport is within or below the lateral limits of a TMA or TCA.     |
| R               | The Airport is within or below the lateral limits Radar Zone.          |
| T               | The Airport is within or below the lateral limits of Class B Airspace. |

Used On:

Airport Flight Planning Continuation Records

Length:

1 character

Character Type:

Alpha

## 5.218 Geographical Reference Table Identifier (GEO REF TBL ID)

Definition/Description: The Geographical Reference Table Identifier will be used to provide a unique identification for each Geographical Entity. As the Geographical Entity field is a large field with no established content, this two-character code will act as a pseudo key for the record.

Source/Content: The content of this field will be determined by the data supplier using the rules below.

Position One - The first letter or other significant letter of the Geographical Entity.

Position Two - A numeric of 0 thru 9 for each multiple of the character in position one.

Used On:

Geographical Reference Table records

Length:

2 characters

Character Type:

Alpha/numeric

Examples:

Scandinavia S1

Southern United Kingdom S2

Baleric Islands B0

## 5.219 Geographical Entity (GEO ENT)

Definition/Description: The Geographical Reference Table will be used to identify Geographical Entities not definable by other established encoding systems. For established systems refer to Section 7 of this document.

Source/Content: The content of the field will be derived from official government source documentation for preferred route systems of any kind.

Used On:

Geographical Reference Table Records

Length:

29 characters

Character Type:

Alpha/numeric

## 5.220 Preferred Route Use Indicator (ET IND)

Definition/Description: The Preferred Route Use Indicator provides information on whether the route in question is point-to-point and therefore usable for navigation, or area-to-area and usable only as advisory information which requires further

processing. The field will also provide information on whether or not RNAV equipment is required to use the route.

Source/Content: The content of this field will be determined by the data supplier at the time the route is established. The two-character field will be used to denote both the definition of the route initial/terminus nature and the RNAV equipment requirement. In position one, the field will contain the alpha character P if the route is point-to-point or A if the route is area-to-area. In position two, the field will contain the alpha character R if RNAV equipment is required and the alpha character N if RNAV equipment is not required.

Used On:

Preferred Route and Geographical Reference Table Records

Length:

2 characters

Character Type:

Alpha

## 5.221 Aircraft Use Group (ACFT USE GP)

Definition/Description: The Aircraft Use Group field provides information on what aircraft or groups of aircraft are permitted to use a certain route.

Source/Content: The raw information for this field will be derived from government sources and encoded according to the table below. The first column will contain the code valid for the routing. See Note One for the second column content.

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

Note 1:

When two routings have been defined between end fixes/areas for the sole purpose of separating aircraft groups of use, the first column will contain the code for the group that may use the routing and the second column will contain the code for the group that must use the alternative routing. If there is no alternative routing for aircraft group separation, the second column will be blank.

Used On:

Preferred Route Records

Length:

2 characters

Character Type:

Alpha

Examples:

For a pair of routings established for aircraft group separation between Single Engine and Twin Engine, the Single Engine would carry the code of ST and the Twin Engine Route would be TS.

## 5.222 GNSS/FMS Indicator (GNSS/FMS IND)

Definition/Description: The GNSS/FMS Indicator field provides an indication of whether or not the responsible government agency has authorized the overlay of a conventional, ground based approach procedure with the use of a sensor capable of processing GNSS data or if the procedure may be flown with FMS as the primary navigation equipment. The field is also used to indicate when a PBN RNP procedure has been authorized for GNSS-based vertical navigation.

Source/Content: The Indicator will be selected from the table below.

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

Note 1: The GNSS/FMS IND of A indicates that the PBN RNP procedure is authorized for SBAS-based vertical navigation.

Note 2: The GNSS/FMS IND of B indicates that the PBN RNP or RNAV Visual procedure is not authorized for SBAS-based vertical navigation. Advisory vertical may be provided.

Note 3: The GNSS/FMS IND of C indicates that thePBN RNP use of SBAS-based vertical navigation has not been published.

Note 4: The GNSS/FMS IND of D indicates that PBN RNP is SBAS authorized only for lateral navigation. Advisory vertical may be provided.

Note 5: The GNSS/FMS IND of G indicates that the GPS approach is an PBN RNAV approach provided with route type P.

Note 6: The GNSS/FMS IND of L indicates that the LOC approach is the Localizer only portion of an ILS approach which

contains glideslope out information.

Used On:

Airport and Heliport Approach Procedure Records

Length:

1 character

Character Type:

Alpha/numeric

## 5.223 Operation Type (OPS TYPE)

Definition/Description: The Operation Type field indicates whether the operation is an approach procedure, an advanced operation or other operational to be defined later.

## 5.223-x92 COMMENTARY

Advanced operation can be straight-in approaches followed by a missed approach, a precision curved approach or departure procedures and roll-out and taxiing procedures .

Source/Content: This field should contain a value in the range of 0 to 15, defined as follows:

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

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

2 characters

Character Type:

Numeric

## 5.224 Route Indicator (RTE IND)

Definition/Description: The Route Indicator field is a single alpha character used to differentiate between multiple final approach segments to the same runway or helipad contained in the Final Approach Coding.

Source/Content: A code of A through Z, (omitting I and O).

Note:

This single character is consistent with the Multiple Approach Indicator included as the fifth character of an Approach Procedure Identifier as defined in Section 5.10 of this specification.

Used On:

Airport and Helicopter Operations SBAS Path Point, GBAS Path Point Record

Length:

1 character

Character Type:

Alpha

## 5.225 Ellipsoidal Height

Definition/Description: The Ellipsoidal Height field is the height of a surveyed point in reference to the WGS-84 ellipsoid.

Source/Content: The Ellipsoidal Height will be an official publication value. It will be provided in meters with a resolution of one tenth. The decimal point is suppressed. When the published Height is below the Ellipsoid, the first position will carry a minus (-) sign to indicate this condition. Otherwise, this first position will be a plus (+) sign. When used on Path Point Records, the Ellipsoidal Height will be for the LTP or FTP Position defined in the Path Point Record. When used on Helicopter Operations SBAS Path Point Records, the value is the height above ellipsoid for the Fictitious Helipoint (or helipoint). When used on Runway Records, the Ellipsoidal Height will be for the Landing Threshold defined in the Runway Record.

Used On:

Airport and Helicopter Operations SBAS Path Point Record, GBAS Path Point Records, and Runway Records

Length:

6 characters

Character Type:

Alpha/numeric

Examples:

+00356, +00051, +00015, -00022, -01566

## 5.226 Glide Path Angle (GPA)

Definition/Description: The Glide Path Angle field is an angle, expressed in degrees, tenths and hundredths of degrees, measured at the Flight Path Control Point (FPCP) of those approach procedures that require the coding of an Airport or Helicopter Operations SBAS Path Point record or GBAS Path Point Record. It establishes the intended descent gradient for the final approach flight path. For an illustration of the GPA and related points, see Figure 5-8.

Source/Content: The values will be derived from official government source.

Used On:

Airport and Helicopter Operations SBAS Path Point Record, GBAS Path Point Records

Length:

4 characters

Character Type:

Numeric

Examples:

0275 (is equal to 2.75°), 1015 (is equal to 10.15°), 0300 (is equal to 3.00 ° )

Figure 5-8 - Precision Approach Path Points

## 5.227 Orthometric Height (ORTH HGT)

Definition/Description: The Orthometric Height field is the height of a surveyed point in reference to Mean Sea Level (MSL).

Source/Content: The Orthometric Height will be derived from official government source and entered with a resolution of a tenth a meter, with the decimal point suppressed. When the height is below MSL, the first position will carry a minus (-) sign; otherwise, this position will be a plus (+) sign.

Used On:

Airport and Helicopter Operations Path Point Continuation Records, GBAS Path Point Continuation Records, SBAS Path Point Continuation Records

Length:

6 characters

Character Type:

Alpha/numeric

Examples:

+00356, +00051, +01566, -00022, -01566

## 5.228 Course Width At Threshold (CRS WDTH)

Definition/Description:The Course Width At Threshold field defines the width of the lateral course at the Landing Threshold Point (LTP) or Fictitious Helipoint (or helipoint). This width, in conjunction with the location of the Flight Path Alignment Point (FPAP) defines the sensitivity of the lateral deviations throughout the approach.

Source/Content: The width will be derived from official government sources and entered in meters in the hundreds, tens, units, tenths and hundredths format with the decimal point suppressed. The value requires a data resolution of 0.25 meters and acceptable values will end in 00, 25, 50, and 75. When the procedure is to a helicopter alighting point (helipad), the value is 38 meters (expressed as 03800). When the procedure is a helicopter operations Point in Space (PinS) procedure, the value is the course width at a fictitious helipoint (or helipoint), see Figure 5-9 .

Figure 5-9 - Lateral Display Scaling for PinS Approach Operations

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

5 characters

Character Type:

Numeric

Examples:

08025, 14375, 03800

## 5.229 Final Approach Segment Data CRC Remainder (FAS CRC)

Definition/Description: The Final Approach Segment Data CRC Remainder field is an eight (8) character hexadecimal representation of the 32-bit CRC value provided by the source for the information contained in the aeronautical data fields being monitored for integrity. The value is calculated by a specific mathematical algorithm, which is both machine and man processible.

Source/Content: For CRC calculation information refer to RTCA DO-229 Minimum Operational Performance Standards for Global Positioning System/Wide Area Augmentation System Airborne Equipment for Final Approach Segment (FAS) Data Block CRC standards or RTCA DO-246 GNSS Based Precision Approach Local Area Augmentation System (LAAS) - Signal-in-Space Interface Control Document (ICD) as appropriate.

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

8 characters

Character Type:

Alpha/numeric

Examples:

243BC649, A6934B72

## 5.230 Procedure Type (PROC TYPE)

Definition/Description: The Procedure Type field used on Flight Planning Arrival/Departure Data Record is a single character code indicating the type of procedure in the record, such as Arrival, Standard Instrument Arrival Route, Approach.

Source/Content: The Procedure Type code must be one of the following codes:

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

Used On:

Flight Planning Arrival/Departure Data Records

Length:

1 character

Character

Type:

Alpha

## 5.231 Along Track Distance (ATD)

Definition/Description: The Along Track Distance field used on Flight Planning Arrival/Departure Data Records is the total distance for a given transition, from the initial fix to the ending fix in the transition. A single occurrence of a Flight Planning Arrival/Departure Data record can contain up to three Along Track Distance fields, one for each of the transition types that can make up a single terminal route in the Primary Record and up to four possible intermediate fix points in each Continuation Record. Collectively, the values equal the along track distance from the first fix in the first transition to the last fix in the last transition.

Source/Content: The along track distances will be calculated by data suppliers using coded terminal procedures or uncoded terminal procedures derived from official government source and expressed in nautical miles with a 1NM resolution.

Used On:

Flight Planning Arrival /Departure Data Records

Length:

3 characters

Character Type:

Numeric

## 5.232 Number of Engines Restriction (NOE)

Definition/Description: The Number of Engines Restriction field used on Flight Planning Arrival/Departure Data Records is derived from government source and is included whenever a given procedure, normally departure, is restricted to, or designed for, aircraft with a specific number of engines.

Source/Content: The number of engines will be taken from official government source. The field will contain the character Y for each engine configuration position, 1, 2, 3, and 4, for which the procedure is authorized. Non-authorized configuration positions will contain the character N.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

4 characters

Character Type:

Alpha

Examples:

YYYY (1, 2, 3, or 4 Engine aircraft may use procedure)

NNYY (3 and 4 Engine aircraft may use procedure)

## 5.233 Turboprop/Jet Indicator (TURBO)

Definition/Description: The Turboprop/Jet Indicator field used on Flight Planning Arrival/Departure Data Records is derived from government source and is included whenever a given procedure, normally departure, is restricted to, or designed for, aircraft with a specific kind of engines.

Source/Content: The indication of Turboprop, Jet, or Both on the use restriction of given procedure will be taken from official government source. The field will indicate the use restriction with a character from the table below.

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

Used On:

Flight Planning Arrival /Departure Data Records

Length:

1 character

Character Type:

Alpha

## 5.234 RNAV Flag (RNAV)

Definition/Description: The RNAV Flag field used on Flight Planning Arrival/Departure Data Records is derived from government source and is included whenever a given procedure included in the record is restricted to, or designed for, aircraft capable of flying RNAV Procedures.

Source/Content: The indication of RNAV, Yes or No, on a given procedure will be taken from official government source. The field will indicate Y for Yes, the procedure is an RNAV procedure or N for No, the procedure is not RNAV.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

1 character

Character Type:

Alpha

## 5.235 ATC Weight Category (ATC WC)

Definition/Description: The ATC Weight Category field used on Flight Planning Arrival/Departure Data Records is derived from government source and is included whenever a given procedure included in the record is restricted to, or designed for, a specific aircraft weight grouping.

Source/Content: The indication of Heavy, Medium, or Light aircraft on a given procedure will be taken from official government source. The field will be derived from that source to indicate:

H for Heavy, all aircraft types of 136,000kg (300000LB) or more.

M for Medium, aircraft types less than 136,000kg (300,000LB) and more than 7,000kg (155,000LB).

L for Light, aircraft types of 7,000kg (155,000LB) or less.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

1 character

Character Type:

Alpha

## 5.236 ATC Identifier (ATC ID)

Definition/Description: The ATC Identifier field used on Flight Planning Arrival/Departure Data Records is the indication of the officially published procedure designation which is required for Flight Planning.

Source/Content: The ATC Identifier will be derived from official government source. This seven-character field is required in addition to the six-character identifier, the former is used in Flight Planning, the latter in accessing the database.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

7 characters

Character

Type:

Alpha/numeric

## 5.237 Procedure Description (PROC DESC)

Definition/Description: The Procedure Description field used on Flight Planning Arrival/Departure Data Records is the textual representation of the procedure name.

Source/Content: The Procedure Description will be derived from official government source. It will assist in matching flight plan content to charted procedures.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

15 characters

Character Type:

Alpha/numeric

## 5.238 Leg Type Code (LTC)

Definition/Description: The Leg Type Code field used on Flight Planning Arrival/Departure Data Records is a simplification of the Path Terminator concept. It will provide the information on the path between intermediate waypoints as straight or curved and provide an indication of the change in direction of flight, expressed as left or right, at an intermediate waypoint.

Source/Content: The Leg Type Code will be derived from official government source. In this two-character field, the first position will indicate with the character S, straight line point to point and with the character C, curved line flight track. The second position will be used as a turn indication, L for Left and R for Right when there is a turn requirement at an intermediate waypoint.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

2 characters

Character Type:

Alpha

## 5.239 Reporting Code (RPT)

Definition/Description: The Reporting Code field used on Flight Planning Arrival/Departure Data Records is a simplification of the Waypoint Description concept. It will provide the information on intermediate waypoints as either Position Report Required (Compulsory Report) or Position Report Not Required (OnRequest Report).

Source/Content: The Reporting Code will be derived from official government source. In this single character field, the code C will indicate Position Report Required and the code X Position Report Not Required.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

1 character

Character Type:

Alpha

## 5.240 Altitude (ALT)

Definition/Description: The Altitude field used on Flight Planning Arrival/Departure Data Records is a simplification of the altitude concept used in the full procedure records. It will provide an altitude indication in hundreds of feet, no AGL, MSL, FL, etc., indication provided.

Source/Content: The Altitude will be derived from official government source and reduced to this flight planning resolution requirement.

Used On:

Flight Planning Arrival/Departure Data Records

Length:

3 characters

Character Type:

Numeric

Examples:

FL100 = 100

10000 feet = 100

03500 feet = 035

## 5.241 Fix Related Transition Code (FRT Code)

Definition/Description: The Fix Related Transition Code is used on Flight Planning Arrival/Departure Data Continuation Records containing Intermediate Fix information and provides an indication, through use of the standard coding practices of separating the procedure into transitions, as to where in the procedure the intermediate fix is located.

Source/Content: The field will contain a code and meaning as indicated in the table below.

| Intermediate Fix is Located in Transition Type   |   Field Content |
|--------------------------------------------------|-----------------|
| Fix Located in SID Runway Transition             |               1 |
| Fix Located in SID Common Portion                |               2 |
| Fix Located in SID Enroute Transition            |               3 |
| Fix Located in STAR Enroute Transition           |               4 |
| Fix Located in STAR Common Portion               |               5 |
| Fix Located in STAR Runway Transition            |               6 |

Used On:

Flight Planning Arrival/Departure Data Records

Length:

1 character

Character Type:

Numeric

## 5.242 Procedure Category (PROC CAT)

Definition/Description: The Airport and Heliport SID/STAR/Approach Procedure Route Type supports the All Sensor RNAV Approach procedure. This kind of approach will have multiple sets of weather minimums (DH and NDA) associated with it. This field identifies the Procedure Categories for which these minimums apply.

Source Content: The field will contain a coded category from the following table:

| Content   | Procedure Category                          |
|-----------|---------------------------------------------|
| LAAS      | Local Area Differential Augmentation System |
| WAAS      | Wide Area Differential Augmentation System  |
| FMS       | Flight Management System                    |
| GPS       | Global Positioning System, no Augmentation  |
| VDME      | VORDME, VORTAC                              |
| CIRC      | Circle-To-Land                              |

Used On:

Airport and Heliport SID/STAR/Approach Procedure Continuation Records

Length:

4 characters

Character Type:

Alpha

## 5.243 GLS Station Identifier

Definition/Description: The GLS Identifier field defines the identification code for retrieval of such a transmitter from a database. This is not a transmitted identifier.

Source/Content: The content of this field will be the Airport or Heliport ICAO Location Identifier Code at which the transmitter is installed.

Used On:

GLS Records

Length:

4 characters max

Character Type:

Alpha/numeric

## 5.244 SBAS/GBAS Channel

Definition/Description: The GNSS Channel Number field identifies the channel to be used for a given approach.

Source/Content: The Channel Number is derived from official government sources and is entered as five numeric characters. It consists of numeric characters in the ranges 0000 to 9999 and 20001 to 99999. In general, numbers less than 20000 are reserved for ILS and MLS. In some countries, Channel Numbers from 0000 to 9999 are reserved for SCAT-1 and will be entered as 00000 through 09999. Channel Numbers from 20001 to 39999 are reserved for GBAS (and SBAS if applicable). Channel Numbers from 40000 to 99999 are reserved for SBAS.

Used On:

GLS and Path Point Continuation Records

Length:

5 characters

Character Type:

Numeric

Examples:

01423, 20010, 56234

## 5.245 Service Volume Radius

Definition/Description: The service volume radius identifies the radius of the service volume around the transmitter in Nautical miles.

Source/Content: The value for this field will be derived from official government sources. If no source is provided, the default value will be blanked.

Used On:

GLS Record

Length:

2 characters

Character Type:

Numeric

Examples:

05, 19

## 5.246 TDMA Slots

Definition/Description: The Time Division Multiple Access (TDMA) identifies the time slot(s) in which the ground station transmits the related approach. The high precision time source available through GPS permits utilization of Time division multiplexing or TDMA (Time Division Multiple Access), allowing multiple ground stations to share a common frequency by dividing it into eight time slots. An individual station may broadcast in one or more of eight slots.

Source/Content: The value for this field will be derived from official government sources. The range is 01 to FF. If no source is provided, the default value will be blank.

Used On:

GLS Record

Length:

2 characters

Character Type:

Alpha/numeric

Examples:

A2, 01, FF

## 5.247 Station Type

Definition/Description: The station type identifies the type of the differential ground station. The first character will be L for LAAS/GLS ground station, C for SCAT-1 station. The second and third character will be blank for the moment. They will indicate the interoperability standard to which the station conforms.

Source/Content: The value for this field will be derived from official government sources. If LAAS/GLS or SCAT-1 is not specified in source, the default value will be blank.

Used on:

GLS Record

Length:

3 characters

Character Type:

Alpha/numeric

Examples:

L, C

## 5.248 Station Elevation WGS84

Description/Definition: This field identifies the WGS84 elevation of the GLS ground station described in the record.

Source/Content: The value for this field will be derived from official government sources or entered into this field in feet with respect to the WGS84 ellipsoid. When elevation is below the WGS 84 ellipsoid, the first column of the field contains a minus (-) sign.

Used On:

GLS Record

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

00530, -0140

## 5.249 Longest Runway Surface Code (LRSC)

Definition/Description: On Airport Records, the Longest Runway Surface Code field is used to define whether or not there is a hard surface runway at the airport, the length of which is indicated in the Longest Runway field.

On Runways Continuation records, the Runway Surface Code field is used to define whether or not the runway described in the record is a hard surface runway.

On Helipad records, the Helipad Surface Code field is used to define whether or not the helipad described in the record is a hard surface helipad.

Source/Content: The content will be selected from the table below.

| Field Content   | Description                                        |
|-----------------|----------------------------------------------------|
| H               | Hard Surface, for example, asphalt or concrete     |
| S               | Soft Surface, for example, gravel, grass or soil   |
| W               | Water Runway                                       |
| U               | Undefined, surface material not provided in source |

Used On:

Airport Records Runway Continuation Record, Airport, and Heliport Helipad Records

Length:

1 character

Character Type:

Alpha

## 5.250 Alternate Record Type (ART)

Definition/Description: The Alternate Record Type field identifiers the record as being applicable to the departure airport (take-off alternate), destination airport (arrival alternate) or a fix along the route (enroute alternate).

Source/Content: The Alternate Record Type will be selected from the following table:

| Content   | Description                                                                                                      |
|-----------|------------------------------------------------------------------------------------------------------------------|
| AA        | The Airport identifier in Columns 7 through 11 of the Primary Record is the identifier of the Arrival Airport.   |
| DA        | The Airport identifier in Columns 7 through 11 of the Primary Record is the identifier of the Departure Airport. |
| EA        | The end fix of a Company Route is identified in Columns 7 through 15 of the Primary Record.                      |

Used On:

Alternate Records

Length:

2 characters

Character Type:

Alpha

## 5.251 Distance To Alternate (DTA)

Definition/Description: The Distance To Alternate field defines either the direct (geodesic) distance from the Destination Airport or Fix to the Alternate Airport or the along track distance of an alternate Company Route.

Source/Content: When the Alternate Type field carries the character A, the Distance to Alternate field carries the straight line (geodesic) distance in nautical miles between the Destination Airport or Fix and the Alternate Airport as listed in Alternate

Identifier fields. When the Alternate Type field carries the character C, the Distance to Alternate field carries the cumulative along track distance for the Alternate Company Route as listed in the Alternate Identifier fields.

Used On:

Alternate Records

Length:

3 characters max.

Character Type:

Numeric

## 5.252 Alternate Type (ALT TYPE)

Definition/Description: The Alternate Type field is an information processing indicator. The Alternate Destination can be defined as an airport or an airport and route to an airport. This field defines that an alternate airport or, a company route is defined in the Alternate Identifier fields.

Source/Content: The field will contain either the character A when an Airport is provided or the character C when a Company Route is provided.

Used On:

Alternate Records

Length:

1 character

Character Type:

Alpha

## 5.253 Primary and Additional Alternate Identifier (ALT IDENT)

Definition/Description: The Primary Alternate Identifier and the Additional Alternate Identifiers (two through five) uniquely identify either an Alternate Airport or an Alternate Company Route. The determination of whether the content is an Airport Identifier or a Company Route Identifier is accomplished through the Alternate Type field.

Source/Content: The content of this field is determined by the customer.

Used On:

Alternate Records

Length:

10 characters max

Character Type:

Alpha/numeric

## 5.254 Fixed Radius Transition Indicator (FIXED RAD IND)

Definition/Description: Indicates that a specific turn radius from the inbound course to the outbound course is required by the airspace controlling agency.

Source/Content: When a fix radius turn is required a 3-digit numeric value will be entered in this field representing the radius of the turn to 1 decimal place (tenths, decimal point suppressed) in nautical miles. A blank entry in this field indicates that no fixed radius transition is required.

Used On:

Enroute Airway Records

Length:

3 characters

Character Type:

Numeric

Examples:

225=22.5nm, 150=15.0 nm

## 5.255 SBAS Service Provider Identifier (SBAS ID)

Definition/Description: The SBAS Service Provider Identifier field is used to associate the SBAS approach procedure to a particular satellite-based approach system service provider. The SBAS Service Provider is carried in the GBAS Path Point Record only for the purpose of CRC calculations.

Source/Content: A number from 00 to 15. The current definitions are:

| 0    | WAAS                                                          |
|------|---------------------------------------------------------------|
| 1    | EGNOS                                                         |
| 2    | MSAS                                                          |
| 3    | GAGAN                                                         |
| 4    | SDCM                                                          |
| 5-13 | (Spare)                                                       |
| 14   | Not intended for SBAS, used as the CRC default value for GBAS |
| 15   | Any Service provider may be used                              |

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

2 characters

Character Type:

Numeric

## 5.256 Reference Path Data Selector (REF PDS)

Definition/Description: The Reference Path Data Selector field enables the automatic tuning of a procedure by Ground Based Augmentation Systems (GBAS) avionics. This data is not used for SBAS operations.

Source/Content: A number from 00 to 48. Values 0-48 are selected via receiver channeling. The field is set to zero for SBAS Path Point Records.

Used On:

Airport, Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

2 characters

Character Type:

Numeric

## 5.257 Reference Path Identifier (REF ID)

Definition/Description: The Reference Path Identifier field represents the three or four alphanumeric characters used to uniquely designate the reference path. The Reference Path Identifier is synonymous with the approach ID located beneath the Channel Number on Instrument Approach Plates and is unique only for a given airport.

Source/Content: Upper-case Alpha characters or numeric digits are used. The content will be derived from official government sources and analogous to the Morse code identifier on existing ILS approach Procedures. While existing industry practices call for a leading character based on the service provider such as W for WAAS or E for EGNOS, the specific use of such characters is not mandatory and other characters may be used. This is followed by the runway number, and a trailing alpha character. For Point in Space procedures, the final approach segment course rounded to the nearest 10 degrees is use in place of the runway number.

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

4 characters

Character Type:

Alpha/numeric

Examples:

W12A, E27A, W34A

## 5.258 Approach Performance Designator (APD)

Definition/Description: The Approach Performance Designator field is used to indicate the type or category of approach. The data is not used for SBAS operations.

Source/Content: A number between 0 and 7 as indicated in the table below. The field is set to zero for SBAS Path Point Records.

| 0   | GAST A or GAST B   |
|-----|--------------------|
| 1   | GAST C             |
| 2   | GAST C or GAST D   |
| 3-7 | Spare              |

### 5.258-x93 COMMENTARY

From RTCA DO-253:

GBAS Approach Service Types (GAST)

A GBAS Approach Service Type is defined as the matched set of airborne and ground performance and functional requirements that are intended to be used in concert in order to provide approach guidance with quantifiable performance.

Used On:

Airport, Helicopter Operations SBAS Path Point Records,

GBAS Path Point Records

Length:

1 character

Character Type:

Numeric

Example:

1 (Category I Approach)

## 5.259 Length Offset (OFFSET)

Definition/Description: The Length Offset field is the distance from the Stop End of the Runway (SER) to the FPAP. This distance defines the location where lateral sensitivity changes to the missed approach sensitivity. If the FPAP is located at the designated center of the opposite runway end, the distance is zero. If the Length Offset is not provided by source , the value is set to blank .

Source/Content: A value, expressed in meters, derived from official government sources (Explanation and details will appear in appropriate FAA and ICAO documents). The actual resolution is 8 meters.

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

4 characters

Character Type:

Alpha/ Numeric

Examples:

0000, 0432

## 5.260 Terminal Procedure Flight Planning Leg Distance (LEG DIST)

Definition/Description: The Terminal Procedure Flight Planning Leg distance is the along track distance required to complete any given leg. It is used to determine a cumulative track distance for a given terminal procedure for flight planning purposes, from the beginning of the take-off or arrival point to the termination point of the procedure.

Source/Content: The values will be determined during route definition of the procedure records. The content is controlled through requirements of the Path and Termination and coding rules in force with the data supplier. The values are expressed in nautical miles and tenths of nautical miles, with the decimal point suppressed.

Used On:

Airport and Heliport SID, STAR, and Approach Procedure Flight Planning Continuation Records

Length:

4 characters

Character Type:

Numeric

Examples:

0176, 0822, 0208 0016, 0100

## 5.261 Speed Limit Description (SLD)

Definition/Description: The Speed Limit Description field will designate whether the speed limit coded at a fix in a terminal procedure description is a mandatory, minimum, or maximum speed.

For Maximum speeds: The SID Procedure Records and Missed Approach Procedures speed limit will apply to all legs up to and including the termination of the leg on which the speed is coded from the beginning of the procedure or a previous speed limit. If a different speed is coded on a subsequent leg, the limit will be applied for that leg and from that leg backwards to the previous terminator which contained a speed limit.

The STAR and Approach Procedure Record speed limit will be applied forward to the end of the arrival (excluding the missed approach procedure) or until superseded by another speed limit.

For Minimum speeds: The SID Procedure Records and Missed Approach Procedures speed limit will be applied forward to the end of the SID or Missed Approach Procedure or until superseded by another speed limit.

The STAR and Approach Procedure Record speed limit will apply to all legs up to and including the termination of the leg on which the speed is coded from the beginning of the procedure or a previous speed limit. If a different speed is coded on a subsequent leg, the limit will be applied for that leg and from that leg backwards to the previous terminator which contained a speed limit.

For Mandatory speeds: The speed requirement shall be met at the fix. The speed will not be applied to previous legs or applied forward to the next legs of the procedure record.

Source/Content: The content will be as defined in the table below.

| Field Content Value   | Description                                                         |
|-----------------------|---------------------------------------------------------------------|
| @(blank)              | Mandatory Speed, Cross Fix AT speed specified in Speed Limit        |
| + (plus)              | Minimum Speed, Cross Fix AT or ABOVE speed specified in Speed Limit |
| - (minus)             | Maximum Speed, Cross Fix AT or BELOW speed specified in Speed Limit |

## 5.263 HAL

Used On:

Airport/Heliport SID/STAR/Approach Records

Length:

1 character

Character Type:

Alpha

## 5.262 Approach Type Identifier (ATI)

Definition/Description: Identifies the approach types published on a given approach procedure which require Airport or Helicopter Operations SBAS Path Points records.

Source/Content: Up to 10 characters representing the literal name of an approach with vertical guidance requiring path points, Horizontal Alert Limit (HAL) and Vertical Alert Limit (VAL). The name is derived from government source material.

Used On:

Airport and Helicopter Operations SBAS Path Point Continuation Records

Length:

10 Characters

Character Type:

Alpha/numeric

Examples:

LPV, LP, APV-II

Definition/Description: The Horizontal Alert Limit (HAL) is the radius of a circle in the horizontal plane (the local plane tangent to the WGS-84 ellipsoid), with its center being at the true position, which describes the region which is required to contain the indicated horizontal position with the required probability for a particular navigation mode assuming the probability of a GPS satellite integrity failure being included in the position solution is less than or equal to 10 -4 per hour.

Source/Content: A value, expressed in meters to a resolution of tenths of meters with the decimal point suppressed, derived from official government sources.

Used On:

Airport and Helicopter Operations SBAS Path Point Records

Length:

3 Characters

Character Type:

Numeric

Examples:

400, 200

## 5.264 Vertical Alert limit (VAL)

Definition/Description: The Vertical Alert Limit (VAL) is half the length of a segment on the vertical axis (perpendicular to the horizontal plane of WGS-84 ellipsoid), with its center being at the true position, which describes the region which is required to contain the indicated vertical position with a probability of 1-10 -7  per approach, assuming the probability of a GPS satellite integrity failure being included in the position solution is less than or equal to 10 -4 per hour. For approaches with lateral only guidance, the VAL will equal 0. This indicates the vertical deviations cannot be used.

Source/Content: A value, expressed in meters to a resolution of tenths of meters with the decimal point suppressed, derived from official government sources.

Used On:

Airport and Helicopter Operations SBAS Path Point Records

Length:

3 Characters

Character Type:

Numeric

Examples:

120, 500

## 5.265 Path Point TCH

Definition/Description: On procedures to runways or helipads, the Path Point TCH is the height above the runway threshold (LTP) or the helicopter alighting point. On procedures which are Point in Space, the height of the fictitious helipoint (or helipoint) above the height of the heliport. It is the same as the TCH defined in Section 5.67, but has greater resolution due to the required precision.

Source/Content: The value is derived from official government sources. The value may be expressed in feet to a resolution of tenths of feet, decimal point suppressed or expressed in meters to a resolution of hundredths of meters, decimal point suppressed. Whether the value is in feet or meters can be determined from the TCH Units Indicator.

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

6 characters

Character Type:

Numeric

Examples:

000526, 001023 (Feet)

001603, 003118 (meters)

## 5.266 TCH Units Indicator

Definition/Description: The TCH Units Indicator field is used in Path Point Records to define the units, Feet or Meters for the Path Point TCH.

Source/Content: The field will contain the character F if the Path Point TCH is provided in source documentation in feet or the character M if that value is provided in meters.

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

1 character

Character Type:

Alpha

## 5.267 High Precision Latitude (HPLAT)

Definition/Description: The High Precision Latitude field contains the latitude of the navigation feature identified in the record.

When used on Airport Path Point Records, one navigation feature is the LTP/FTP, the other is the FPAP. When used on Helicopter Operations Path Point Records, one navigation feature is the Fictitious Helipoint (or Helipoint), the other is the FPAP.

Source/Content: The content of field is an expansion of the latitude defined in Section 5.36 to include degrees, minutes, seconds, tenths, hundredths, thousandths and tenths of thousandths of seconds to accommodate the high precision resolution of 0.0005 arc seconds.

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

11 characters

Character Type:

Alpha/numeric

Example:

N3028422400

## 5.268 High Precision Longitude (HPLONG)

Definition/Description: The High Precision Longitude field contains the latitude of the navigation feature identified in the record.

When used on Airport Path Point Records, one navigation feature is the LTP/FTP, the other is the FPAP. When used on Helicopter Operations Path Point Records, one navigation feature is the Fictitious Helipoint (or Helipoint), the other is the FPAP.

Source/Content: The content of field is an expansion of the latitude defined in Section 5.36 to include degrees, minutes, seconds, tenths, hundredths, thousandths and tenths of thousandths of seconds to accommodate the high precision resolution of 0.0005 arc seconds.

Used On:

Airport and Helicopter Operations SBAS Path Point Records, GBAS Path Point Records

Length:

12 characters

Character Type:

Alpha/numeric

Example:

W08142030100

## 5.269 Helicopter Procedure Course (HPC)

Definition/Description: The Helicopter Procedure Course field is used on Path Point Continuation Records to define the final approach course of procedures designed for helicopter operations to runways, to helipads, and to points in space.

Source/Content: The field will contain the full degree final approach course of a procedure designed to a runway, helipad or Point in Space and be derived from official government source. It will be used in conjunction with the Approach Procedure Identifier and Runway/Helipad Identifier data in the Path Point Primary record to uniquely identify an approach procedure.

Used On:

Airport and Helicopter Operations SBAS Path Point

Continuation Records

Length:

3 Characters

Character Type:

Numeric

Examples:

003, 013, 103, 310, 333

## 5.270 TCH Value Indicator (TCHVI)

Definition/Description: The TCH Value Indicator field will define which TCH value is provided in the runway record.

Source/Content: The field will contain a value from the following table:

| Field Content   | Description                                                                                  |
|-----------------|----------------------------------------------------------------------------------------------|
| I               | TCH provided in Runway Record is that of the Electronic Glideslope.                          |
| R               | TCH provided in Runway Record is that of an RNAV procedure to the runway.                    |
| D               | TCH provided in the Runway Record is the default value of 40 or 50 fee t (See Section 5.67). |

Used On:

Runway Records

Length:

1 character

Character Type:

Alpha

## 5.271 Procedure Turn (PROC TURN)

Definition/Description: The TAA Procedure Turn field is used to indicate whether or a course reversal is necessary when flying within a particular TAA Area.

Source/Content: Official government source will carry an indication when the course reversal is not necessary. Generally, that indication is NOPT. Otherwise, the execution of a course reversal is expected. When the course reversal is not necessary, this field will carry an N . When the course reversal is necessary, the field will carry a Y. The indication is provided for each sector on a particular TAA Initial Approach Fix.

Used on:

Airport or Heliport TAA Primary Record

Length:

1 character

Character Type:

Alpha

## 5.272 TAA Sector Identifier

Definition/Description: The Fix Position Indicator field contains an indication as to which TAA Initial Approach Fix (IAF) or intermediate Fix (IF) the data in the record applies.

Source/Content: Airport and Heliport Terminal Area Altitude (TAA) are published for each Initial Approach Fix (IAF) or intermediate Fix (IF) for some RNAV and GPS Approach Procedures. The field identifies the fix to which the data contained in the record applies. The content is derived from official government source and entered as indicated in the table below. The terminology left, right and center refers to the position of the TAA fix to the final approach course. Center indicates on the final approach course. Left indicates left of the final approach course. Right indicates right of the final approach course. It could also be viewed as the direction of turn onto final approach an aircraft would make from the base leg defined by the fix. When used on Airport and Heliport Approach Procedure Records, it serves as a pointer to the specific Airport or Heliport TAA Record (PK) where the data pertaining to the fix resides.

| Field Content   | TAA Fix Position Indicator   |
|-----------------|------------------------------|
| C               | Straight-In or Center Fix    |
| L               | Left Base Area               |
| T               | Right Base Area              |

Used On:

Airport and Heliport TAA Primary Records

Length:

1 character

Character Type:

Alpha

## 5.273 TAA Waypoint

Definition/Description: The TAA Waypoint field contains the identifier of the Initial Approach Fix (IAF) or Intermediate Fix (IF) associated with a given Terminal Area Altitude sector. There may be one, two or three such IAF waypoints defined for a single approach procedure. The TAA IAF Waypoint in the individual TAA Sector records is the fix from which radius distances are defined.

Source/Content: The field contains the official identifier of the waypoint for which the TAA Sector is defined. They will be derived from official government sources.

Used On:

Airport and Heliport TAA Records

Length:

5-character max

Character Type:

Alpha/numeric

## 5.274 TAA Sector Radius

Definition/Description: The Sector Radius field in TAA records defines the start and end distances that define a TAA area. They are referenced to the TAA IAF Waypoint defined in that record. As TAA information is used towards that waypoint, the radius information is provided towards that waypoint. They enclose the sector defined in the record. The values are inclusive.

Source/Content: The Sector Radius information will be derived from official government source. Each TAA sector is made up of the start of sector radius and the end of sector radius. The values are provided in nautical miles. The first two digits define the radius for start of the sector, the second two digits the end of the sector, when flying towards the IAF/IF Waypoint.

Used On:

Airport and Heliport TAA Primary Records

Length:

4 characters

Character Type:

Numeric

Examples:

3011, a Sector that starts at 30 nautical miles to the IAF Waypoint and ends at 11 nautical miles to the IAF Waypoint. 0500, a Sector that starts at 5 nautical miles to the IAF Waypoints and ends at that IAF Waypoint

## 5.275 Level of Service Name (LSN)

Definition/Description: The Level of Service Name field identifies the official procedure level of service based on published procedure operating minimums information for PBN RNP APCH or A_RNP Approach Procedures.

Source/Content: The field will be derived from official government. The table below shows examples of Level of Service Names.

| Level of Service Name (Note 1)   | Level of Service Name (Note 1)   |
|----------------------------------|----------------------------------|
| LPV                              | (Note 2)                         |
| LPV200                           | (Note 2)                         |
| LP                               | (Note 2)                         |
| LNAV                             | LNAV                             |
| LNAV/VNAV                        | LNAV/VNAV                        |

Used On:

Procedure Data Continuation Records 10 characters (Note 3)

Length:

Character Type:

Alpha

Note 1:

The Level of Service Names of LPV, LPV200, LP, LNAV/VNAV, and LNAV are derived from available industry documentation in use at the time Supplement 20 was published. Other terminology to describe these procedures may be in use.

Note 2:   At the time Level of Service was originally introduced, the only Level of Service published for which there was a FAS Block Provided category was LPV. Subsequently, other criteria and terminology has been developed and this is reflected in the examples above. As there can be only one FAS Block Level of Service name per approach procedure, the Level of Service Names LPV, LPV200, and LP are provided as appropriate in the field named FAS Block Provided Level of Service Name in Sections 4.1.9.5 or 4.2.3.5 while the other Level of Service Names are provided in dedicated fields in those paragraphs. It should be noted that it is possible for LNAV/VNAV and/or LNAV to be authorized either with or without a FAS Datablock provided and therefore these Level of Service Names are always carried in the dedicated field.

Note 3: The 10 character fields are left justified. Any remaining columns are filled with blanks. When the paired Level of Service Authorized field (Sections 4.1.9.5 or 4.2.3.5, and 5.276) is set to N (Not Authorized), the entire10-character Level of Service Name field should be blank.

Updated the text and Note 2 to remove SBAS authorization statement and added the official level of service based on published procedures operating minimums information for PBN RNP APCH or A-ARNP approach procedures.

## 5.276 Level of Service Authorized

Definition/Description: The Level of Service Authorized field defines whether the Level of Service designated in an associated field (Section 5.275) is authorized or not authorized for a procedure.

Source/Content: The Level of Service Authorized can be derived from official government sources. It is a code selected from the table below.

| Description                                                      | Field Content   |
|------------------------------------------------------------------|-----------------|
| Designated Level of Service is authorized for the procedure.     | A               |
| Designated Level of Service is not authorized for the procedure. | N               |

Used On:

Procedure Data Continuation Records

Length:

1 characters

Character Type:

Alpha

## 5.277 DME Operational Service Volume (D-OSV)

Definition/Description: The DME Operational Service Volume field is used to specify the service volume information of DME Navaids to support using DME-DME and DME-DME-IRU FMS capabilities in RNAV procedures and routes.

Source/Content: The information will be derived from official government source documentation and encoded based on the table below:

| Field Content   | D-OSV Description   |
|-----------------|---------------------|
| A               | 40NM or less        |
| B               | 70NM or less        |
| C               | 130NM or less       |
| D               | Greater than 130NM  |
| U               | Unspecified         |

Used On:

VHF Navaid Primary Records

Length:

1 character

Character Type:

Alpha

## 5.278 Activity Type

Definition/Description: The Activity Type is used to define the type of Special Activity that is occurring.

Source/Content: The Activity Type should be derived from official government publications.

| Type                   | Field Content   |
|------------------------|-----------------|
| Parachute Jumping Area | P               |
| Glider Operations      | G               |
| Hang Glider Activities | H               |
| Ultralight Activities  | U               |

Used On:

Special Activity Area records

Length:

1 character

Character Type:

Alpha

## 5.279 Activity Identifier

Definition/Description: The Activity Identifier field contains the number or name that uniquely identifies the Special Activity Area.

Source/Content: The Activity Identifier is to be derived from official government publications. The field will contain an alphanumeric designation up to 6 characters.

| Field Content          | Field Content   | Field Content   | Field Content       |
|------------------------|-----------------|-----------------|---------------------|
| Activity               | Type            | State/Nation    | Activity Designator |
| Parachute Jumping Area | P               | TX              | 117                 |
| Glider Operations      | G               | VA              | 5                   |
| Hang Glider Activities | H               | CA              | 45                  |
| Ultralight Activities  | U               | OR              | 99                  |

Used On:

Special Activity Area records

Length:

6 characters

Character Type:

Alpha/numeric

Examples:

PTX117, GVA5, UOR99

## 5.280 Special Activity Area Size

Definition/Description: The Special Activity Area Size field contains the radius around the center point where the Special Activity is expected to occur.

Source/Content: The Special Activity Area Size is to be defined from official government publications when available. The radius is entered in nautical miles to a tenth of a nautical mile with the decimal point suppressed.

Used On:

Special Activity Area records.

Length:

3 characters

Character Type:

Numeric

Examples:

020, 105, 050

## 5.281 Special Activity Area Volume

Definition/Description: The Special Activity Area Volume field contains the expected annual level of intensity of the Special Activity.

Source/Content: The Special Activity Area Volume is to be derived from official government publications when available.

Used On:

Special Activity Area records

Length:

1 character

Character Type:

Alpha/numeric

## 5.282 Special Activity Area Operating Times

Definition/Description: The Special Activity Area Operating Times field contains the annual expected operation schedule of the Special Activity.

Source/Content: The Special Activity Area Operating Times is to be derived from official government publications when available.

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

Used On:

Special Activity Area records

Length:

3 characters

Character Type:

Alpha

Examples:

DXD (Weekdays, Excluding Holidays from Sunrise to Sunset)

## 5.283 Communications Class (Comm Class)

Definition/Description: The Communications Class field will designate the major grouping of the Communications Types contained in the record.

Source/Content: The value will be selected from the options in the table below:

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

Used On:

Enroute, Airport, and Heliport Primary and Continuation Communications Records and the Communications Type Translation Table Record

Length:

4 characters

Character Type:

Alpha

## 5.284 Assigned Sector Name (ASN)

Definition/Description: The Associated Sector Name field is used to indicate the published name of an Enroute Communications Sector.

Source/Content: The content of the field will be derived from official government source.

Used On:

Enroute Communications Records

Length:

25 characters max

Character Type:

Alpha/numeric

Examples:

West Sector, Mediterranean Sector, UR Sector, SE High Sector

## 5.285 Time Narrative

Definition/Description: The Time Narrative field is used to provide Time of Operations and/or Conditions of Operations in a narrative form when source information cannot be formatted in accordance with Section 5.195 of this specification.

Source/Content: The field content will be derived from official government sources.

Used On:

Enroute Airway Restriction, Enroute/Airport/Heliport Communications, Restrictive Airspace, Controlled Airspace and Preferred Route Continuation Records

Length:

100 characters max (per record)

Character Type:

Alpha/numeric

## 5.286 Multi-Sector Indicator (MSEC IND)

Definition/Description: The Multi-Sector Indicator field is used to indicate that the communications service and frequency are used in more than one defined sector. The actual sector data will be contained in the primary and continuation records of the affected airport or heliport communications record set.

Source/Content: The field will be set to Y, indicating multi-sector data is published in official government source for the service and frequency or N, indicating that the official government source has provided only a single defined sector for the service and frequency. The field will be left blank if there is no defined sector data published for the service and frequency.

Used On:

Airport and Heliport Communications Primary Records

Length:

1 character

Character Type:

Alpha/numeric

## 5.287 Type Recognized By (TRB)

Definition/Description: The Type Recognized By field is used to provide an indication of the provider of a given Communications Type (5.101).

## 5.289 Used On

Definition/Description: The Used On field provides an indication of what kind of communications records a particular Communications Type is used on.

Source/Content: The content will be derived from official government source and will be selected from the table below.

Source/Content: The field content will be derived from the official government source used to establish the Communications Type and will be selected from the table below:

| Field Content   | Description                                                                                                        |
|-----------------|--------------------------------------------------------------------------------------------------------------------|
| I               | The Communications Type is found in government source provided in accordance with ICAO standards.                  |
| F               | The Communications Type is found in government source provided in accordance with US FAA standards.                |
| B               | The Communications Type is found in government source provided in accordance with both ICAO and US FAA standards.  |
| C               | The Communications type is found in government source provided by the country in which the communications is used. |
| O               | The Communications type is found in government source provided by the country in which the communications is used. |
| S               | The Communications Type has been established by the data supplier.                                                 |

Used On:

Communications Type Translation Table Records

Length:

1 character

Character Type:

Alpha

## 5.288 Translation

Definition/Description: The Translation field is used to provide a decoding of a threecharacter Communications Type (5.101).

Source/Content: The content of the field will be derived from official government source documentation. There will be a listing for every Communications Type contained in the output file.

Used On:

Communications Type Translation Table Records

Length:

80 characters max

Character Type:  Alpha/numeric

Examples:

TWR:

ATC Control Tower

GCO:

Ground Communication Outlet

ATI:

Automated Terminal Services

| Field Content   | Description                                                                              |
|-----------------|------------------------------------------------------------------------------------------|
| A               | The Communications Type is used on Airport Communications Records only.                  |
| E               | The Communications Type is used on Enroute Communications Records only.                  |
| H               | The Communications Type is used on Heliport Communications Records only.                 |
| B               | The Communications Type is used on Airport, Heliport and Enroute Communications Records. |
| C               | The Communications Type is used on Airport and Heliport Communications Records.          |

Used On:

Communications Type Translation Table Records

Length:

1 character

Character Type:

Alpha

## 5.290 Procedure Design Mag Var (PDMV)

Definition/Description: The Procedure Design Mag Var field specifies the angular difference between True North and Magnetic North at the location defined in the record. That location may be the airport for which the procedure was designed, the so-called Airport Magnetic Variation of Record, or may be the procedure leg defined in the record. Which location is intended can be determined from the content of the data coded to Section 5.291 (Procedure Design Mag Var Indicator).

Source/Content: Procedure Design Mag Var is obtained from official government procedure data sources and is understood to be the Epoch Year value used when the procedure last revised. This value may differ from magnetic variation data in the primary record of the airport for which the procedure was designed and from data for individual navaids or waypoints used in the procedure. Updating of this value is based only on procedure source data change. Position one of the field contains an alpha character taken from the table below. Positions 2 thru 5 carry the angular difference value expressed in degrees and tenths of a degree with the decimal point suppressed. When Position one is set to T, Positions 2 thru 5 will be all zeros.

| Field Content   | Description                                                                                    |
|-----------------|------------------------------------------------------------------------------------------------|
| E               | Procedure Designed based on Magnetic Variation (angular difference) that is East of True North |
| W               | Procedure Designed based on Magnetic Variation (angular difference) that is West of True North |
| T               | Procedure Designed based on True North                                                         |

Length:

5 characters

Character Type:

Alpha/numeric

Examples:

E0140, E0007, T0000

## 5.291 Procedure Design Mag Var Indicator (PDMVI)

Definition/Description: The Procedure Design Mag Var Indicator field is an indication of how procedure design magnetic variation was provided in official source data for the procedure defined in the record/record set.

Source/Content: Procedure Design Mag Var (5.290) will be obtained from official government source procedure data. That data can be a value valid for the entire procedure or a series of values valid for individual legs of the procedure. The field will contain the alpha character P when the value applies to the entire procedure or the alpha character L with the value applies to the leg with which it is associated. With the exception of VOR radials and tracks in VORDME RNAV Approach procedures, Approach Procedures are designed using the airport magnetic variation of record and a single value will apply for the complete procedure. VOR radials use the establish station declination of the VOR. Tracks in VORDME RNAV procedures use the station declination of the procedure reference navaid.

Used On:

Airport and Heliport SID/STAR/Approach Primary Extension Continuation Records

Length:

One character

Character Type:

Alpha

## 5.292 Category Distance

Definition/Description: The Category Radii fields, expressed in tenths of nautical miles, specifies the obstacle clearance area for aircraft maneuvering to land on a runway which is not aligned with the FAC of the approach procedure. The limits of the circling area are defined to be an arc from the center of the end of each usable runway. The extremities of the adjacent arcs are joined by lines drawn tangent to the arcs. The area thus enclosed is the circling approach area.

Source/Content: Category radii are obtained from official government publications. The field will contain a figure expressed in nautical miles, with a resolution of 1/10. If the radii are not known or defined, the field is filled with 00.

Used On:

Airport and Heliport Approach Continuation Records

Length:

2 characters

Character Type:

Alpha/numeric

Examples:

00, 13, 15, 17, 23

## 5.293 Vertical Scale Factor (VSF)

Definition/Description: Vertical Scale Factor (VSF) is used to set the vertical deviation scale.

Source/Content: VSF values derived from official source will be used when available. They are entered into the field in feet (three digits). The content can be:

When used on Enroute Airway segments, VSF shall apply inbound to the fix when viewed in decreasing sequence number order. The VSF applies only to the airway leg on which it is specified. If no VSF value is coded on a segment, there is not a database specified VSF for that segment.

When used on a SID, STAR, Approach Transition or Missed Approach record, the VSF shall apply to the balance of the procedure route unless superseded by another value of VSF on a subsequent record. Procedure route must be determined by the Route Type field (see Section 5.7).

When used on final approach records, VSF must apply to the waypoint referenced by the final approach record.

Used On:

Enroute Airways, SID, STAR and Approach Route and Controlled Airspace Records, Holding Pattern Records

Length:

3 characters

Character Type:

Numeric

Examples:

250, 100, 050

## 5.294 RVSM Minimum Level

Definition/Description: RVSM Minimum Level is the lowest defined cruising level for an airway or holding pattern.

Source/Content: RVSM Minimum Levels are derived from official source when available. They are entered into the field as a three-digit numeric flight level.

Used On:

Enroute Airway Records, Holding Pattern Records

Length:

3 characters

Character Type:

Numeric

Examples:

080,180,270

## 5.295 RVSM Maximum Level

Definition/Description: RVSM Maximum Level is the highest defined cruising level for an airway or holding pattern.

Source/Content: RVSM Maximum Levels are derived from official source when available. They are entered into the field as a three-digit numeric flight level.

Used On:

Enroute Airway Records, Holding Pattern Records

Length:

3 characters

Character Type:

Numeric

Examples:

270,250,510

## 5.296 RNP Level of Service (LSN)

Definition/Description: The Level of Service field identifies the official procedure level of service based on published procedure operating minimums information for Approach Procedures authorized for RNP.

Source/Content: The field will be derived from official government source and provided beginning with the least restrictive value. The table below shows examples of Level of Service for RNP.

|   Level of Service Name - RNP (Note 1) |
|----------------------------------------|
|                                    031 |
|                                    152 |
|                                    112 |

Note 1:  The RNP level of service name fields are formatted per chapter 5 Section 5.211. In the case that the field is not applicable because the associated Level of Service Authorized (Section 4.1.9.5 or 4.2.3.5, and 5.276) is N for Not Authorized, the RNP Level of Service will be populated regardless of the Level of Service Authorized (5.276) designation.

Used On:

Procedure Data Continuation Records

Length:

3 characters

Character Type:

Numeric

## 5.297 Route Inappropriate Navaid Indicator

Definition/Description: A Route Inappropriate Navaid Indicator is used when a DME navaid has source provided information identifying the navaid as inappropriate for use in navigation solutions for RNAV 1 and RNAV 2 routes.

Source/Content: The content of the field is derived from official government sources. The field will be set to the character N when the DME navaid has not been published as being inappropriate for navigation solutions for RNAV 1 or RNAV 2 routes or the character Y when the DME navaid has been published as being inappropriate for navigation solutions for one or more RNAV 1 or RNAV 2 routes.

Used On:

VHF Navaid Primary Records

Length:

1 character

Character Type:

Alpha

## 5.298 Holding Pattern/Race Track Course Reversal Leg Inbound/Outbound Indicator

Definition/Description: The Leg Inbound/Outbound Indicator is used to identify the Leg Length or Leg Time field values (5.64 or 5.65) as being applicable to either the inbound or the outbound leg of a holding pattern or race track course reversal.

Source/Content: The field will contain either the character I for Inbound or O for Outbound. This content is derived from official government source documentation. On SID/STAR/Approach Records, the field is populated when the Path and Terminator in the record is HA, HF, or HM only, otherwise it is left blank.

Used On:

Holding Pattern, Airport, and Heliport SID/STAR/Approach

Records

Length:

1 character

Character Type:

Alpha

## 5.299 Procedure Referenced Fix Identifier

Definition/Description: The Procedure Referenced Fix Identifier field contains the five-character-name-code, or other series of characters, with which the Fix is identified. The officially published Waypoint Identifier, VHF Navaid Identifier or NDB Navaid identifier will be required for use in the terminal procedure, but is not included in the SID, STAR, or Approach primary record procedure coding.

Source/Content: Officially published identifiers.

Used On:

Airport/Heliport SID/STAR/Approach Primary Extension Continuation Records

Length:

5 characters max

Character Type:

Alpha/numeric (no embedded blanks)

Examples:

SHARP, BBNSI

## 5.300 Final Approach Course as Runway

Definition/Description: The Final Approach Course as Runway field is a method of providing data for Point in Space approach procedure that are not to a runway.

Source/Content: The Final Approach Course is derived from government publications and is populated with the final approach course rounded to the nearest 10 degrees and expressed as a two-digit number. Other positions are zero filled.

Used On:

Helicopter Operations SBAS Path Point Records, Airport SBAS Path Point Primary Records, and GBAS Path Point Primary Records

Length:

5 characters

Character Type:

Numeric

Examples:

01000, 15000, 36000

## 5.301 Procedure Design Aircraft Category or Type

Definition/Description: This field provides the aircraft category(s) or types for which the procedure or portion of a procedure (transition) was designed. This can be aircraft category information or aircraft type information. This field also provides the aircraft category(s) or types applicable to a speed limit in a Controlled Airspace.

Source/Content: The content of this field is derived from official government source and will contain a single alpha character from the table below. For Approach Procedures, the content is specific to a Transition and can vary between Transitions for a single procedure.

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

Used On:

Airport and Heliport SID, STAR and Approach , and Controlled Airspace Records

Length:

1 Character

Character Type:

Alpha (may be blank)

Section was updated to reference the speed limit in Controlled Airspace Record.

Aircraft Type Turbojet and Turboprop only was added to Aircraft Category or Type table.

## 5.302 Surface Type

Definition/Description: The Surface Type field defines the predominant surface type of the runway/helipad described in the record.

Source/Content: Valid contents are defined in column 1 of the table below. Column 3 defines the Runway Surface Code that must be associated for each Runway Surface Type.

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

Used On:

Runway Continuation, Airport Helipad, Heliport Helipad

Records

Length:

4 Character

Character Type:

Alpha

## 5.303 Helipad Shape

Definition/Description: The Helipad Shape field defines the geometric shape of a helipad as being either circle, runway, or rectangular.

Source/Content: The field contains the shape of the helipad derived from official government sources when available. The content will be selected from the table below:

| Field Content   | Description                                     |
|-----------------|-------------------------------------------------|
| C               | Circle                                          |
| S               | Square/Rectangle                                |
| R               | Runway                                          |
| U               | Undefined, helipad shape not provided in source |
| C               | Circle                                          |

Used On:

Airport Helipad Records, Heliport Helipad Records

Length:

1 Character

Character Type:

Alpha

## 5.304 Sector Bearing Reference Waypoint

Definition/Description: The Sector Bearing Reference Waypoint field contains the identifier of the waypoint that the Sector Bearings are referenced to within a given Terminal Area Altitude sector.

Source/Content: The field contains the official identifier of the waypoint that the Sector Bearings within a TAA sector are referenced to. The field will be derived from official government sources.

Used On:

Airport and Heliport TAA Records

Length:

5 Character Max

Character Type:

Alpha/numeric

## 5.305 Heliport Type

Definition/Description: This field provides information on the type of heliport facility.

Source/Content: The indicator will be selected from the table below.

| Heliport Type     | Field Content   |
|-------------------|-----------------|
| Hospital          | H               |
| Oil Rig           | O               |
| All other types   | Blank           |
| Type not provided | U               |

Used On:

Heliport Records

Length:

1 Character

Character Type:

Alpha (may be blank)

## 5.306 Preferred Multiple Approach Indicator

Definition/Description: Preferred Multiple Approach Indicator is used to identify the multiple approach that is generally considered to be the most likely one to be utilized/needed when there are only multiple approaches available for a given approach type at a runway. This will be defined on the Approach FAF record in the Final Approach. For a given approach type at a runway, there shall be one and only one Primary Multiple Approach Indicator provided.

Source/Content: The Preferred Multiple Approach Indicator is per official government source. When not provided by official source, it is defined by the data suppliers as they deem appropriate to support their customers. A P in this field on the approach final FAF record indicates the approach is the preferred multiple approach and can be given priority during data packing, if desired. A blank on the approach final FAF record will be interpreted that the approach is not the preferred multiple approach.

Used On:

Airport and Heliport SID/STAR/Approach Records

Length:

1 Character

Character Type:

Alpha (may be blank)

## 5.307 Special Indicator

Definition/Description: This field provides an indicator whether the terminal procedure requires specific operational approval defined by official government sources. Special procedures may be developed based on aircraft performance, aircraft equipment, or crew training, and may also require the use of landing aids, communications, or weather services not available for public use. Examples of special procedures include: SIAP, RCAP, etc.

Source/Content: Special indicator derived from official government sources will be entered using a Y in this field. A blank will be interpreted that the procedure is not defined as a special procedure.

Used On:

Airport and Heliport SID/STAR/Approach Records

Length:

1 Character

Character Type:

Alpha (may be blank)

## 5.308 Remote Altimeter Flag

Definition/Description: The field indicates whether or not the existence and use of a Remote Altimeter Setting is applicable to the procedure with the meaning that LNAV/VNAV (Baro-VNAV) is Not Authorized with the Remote Altimeter Setting is being used.

Source/Content: The field content is based on government sources. The field contains the character R when there is a Remote Altimeter Restriction on the use of LNAV/VNAV (Baro-VNAV) Lines of Minimum. For all other cases, the field is blank.

Used On:

Procedure Data Continuation Records

Length:

1 Character

Character Type:

Alpha

## 5.309 Maximum Allowable Helicopter Weight

Definition/Description: The Maximum Allowable Helicopter Weight represents the maximum weight, expressed in hundreds of pounds, that a helipad or FATO can support.

Source/Content: The value for this field will be derived from official government sources. If no source is provided, the default value will be blanked

Used On:

Airport Helipad Records, Heliport Helipad Records

Length:

3 Character

Character Type:

Numeric

Examples

101, 050, 100

## 5.310 Helicopter Performance Requirement

Definition/Description: The Helipad Performance Requirement is used to identify any restriction imposed on helicopter performance in order to use a given helipad.

Source/Content: The field contains the performance requirement of the helipad derived from official government sources when available. The content will be selected from the table below:

| Field Content   | Description           |
|-----------------|-----------------------|
| M               | Multi-engine required |
| S               | Single engine only    |
| U               | Unknown               |

## 5.311 FIR/FRA Transition Waypoint

Definition/Description: The Flight Information Region (FIR) Free Route Airspace (FRA) Waypoint column allows designation of specific waypoint types used to enter, exit, and/or transition through FRA areas. These waypoint designations will normally be provided by host nation authorities via their AIP.

Source/Content: The field content will be derived from official government sources. The content will be selected from the table below. A waypoint may have multiple values assigned by the State airspace authority.

|   Column | Field Content   | Description                |
|----------|-----------------|----------------------------|
|       44 | E               | Entry Point                |
|       45 | X               | Exit Point                 |
|       46 | A               | Arrival Transition Point   |
|       47 | D               | Departure Transition Point |
|       48 | I               | Intermediate Point         |
|       49 | H               | Terminal Holding Point     |

## 5.313 TORA

Definition/Description: Take Off Run Available is the declared distance value which is available for take-off ground roll. The field is used in conjunction with Section 5.317, Runway Usage Indicator.

Source/Content: The TORA value will be derived from official government sources and shown in feet. Starter extension distances are not included in the TORA distance and may be added if a starter extension is available. A value of 00000 indicates that the runway is not usable for take-off. A blank field means that no value is declared in source.

Used On:

Runway Continuation Records

Length:

5 Character

Character Type:

Numeric

Examples:

02900, 10000

New section was added for runway declared distances.

New section was added for runway declared distances.

New section was added for runway declared distances.

New section was added for runway declared distances.

New section was added for runway declared distances.

## 5.314 TODA

Definition/Description: Take Off Distance Available is the declared distance value which is available for take-off over a 50 ft obstacle. The field is used in conjunction with Section 5.317, Runway Usage Indicator. Typically, the TODA equals the TORA plus clearway.

Source/Content: The TODA value will be derived from official government sources and shown in feet. Starter extension distances are not included in the TODA. A value of 00000 indicates that the runway is not usable for take-off. A blank field means that no value is declared in source.

Used On:

Runway Continuation Records

Length:

5 Character

Character Type:

Numeric

Examples:

02900, 10000

Definition/Description: Accelerate Stop Distance Available is the declared distance value which is available in case of an aborted take-off. The field is

## 5.315 ASDA

Used On:

Waypoint Flight Planning Continuation Records

Length:

1 Character

Character Type:

Alpha/Numeric

## 5.312 Starter Extension

Definition/Description: Starter Extension means an area made available for take-off, prior to the normal runway end at the beginning of the takeoff run. Starter extensions are established where additional takeoff distance, takeoff run or accelerate-stop distance is required, but physical limitations do not allow provision of the mandatory runway strip or width.

Source/Content: The Starter Extension will be derived from official government sources and shown in feet (See Table 5-1 5 ).

Used On:

Runway Records

Length:

4 Character

Character Type:

Numeric

Examples:

0900, 1000

## 5.316 LDA

used in conjunction with Section 5.317, Runway Usage Indicator. Typically, the ASDA equals the TORA plus stopway.

Source/Content: The ASDA value will be derived from official government sources and shown in feet. Starter extension distances are not included in the TODA distance and may be added if a starter extension is available. A value of 00000 indicates that the runway is not usable for take-off. A blank field means that no value is declared in source.

### 5.316-x94 Used On: Runway Continuation Records Length: 5 Character Character Type: Numeric

Examples:

02900, 10000

Definition/Description: Landing Distance Available is the declared distance value which is available for landing. The field is used in conjunction with Section 5.317, Runway Usage Indicator. Typically, the LDA equals the runway length minus the threshold displacement distance.

Source/Content: The LDA value will be derived from official government sources and shown in feet. A value of 00000 indicates that the runway is not usable for landing. A blank field means that no value is declared in source.

Used On:

Runway Continuation Records

Length:

5 Character

Character Type:

Numeric

Examples:

02900, 10000

## 5.317 Runway Usage Indicator

Definition/Description: The Runway Usage Indicator field specifies if a Runway is usable for take-off, landing, or both operations. Source/Content: The field will be derived from official government sources.

The content will be selected from the table below.

A field content of L will require the TORA, TODA, and ASDA to be 0 and the LDA either blank or non-0. A field content T will require the TORA, TODA, and ASDA to be blank or non-0 and the LDA to be 0.

Used On:

Runway Continuation Records

Length:

1 Character

Character Type:

Alpha

## 5.318 Runway Accuracy Compliance Flag

Definition/Description: Flag that indicates if runway parameters meet Runway Accuracy Requirements defined as follows:

Difference between coded Runway Length (PG 5.57) and runway length measured with an independent means (e.g., satellite imagery) is 5 meters or less.

Difference between coded Runway Threshold Position (PG 5.36 and 5.37) and runway landing threshold location measured with an independent means (e.g., satellite imagery) is 5 meters or less.

Difference between coded Runway Threshold Displacement Distance (PG 5.69) and runway threshold displacement distance measured with an independent means (e.g., satellite imagery) is 5 meters or less.

Difference between runway true bearing computed using coded Runway Magnetic Bearing (PG 5.58) and coded Airport Magnetic Variation (PA 5.39) and runway true bearing measured with an independent means (e.g., satellite imagery) is less than 0.5°.

Source/Content: The field will be populated by the data provider, using one of the three possibilities presented in the below table:

| Field Content   | Description                                                      |
|-----------------|------------------------------------------------------------------|
| Y               | Runway data meets Accuracy Requirements                          |
| N               | Runway data does not meet Accuracy Requirements                  |
| Blank           | Runway data has not been evaluated against Accuracy Requirements |

Used On:

Runway Records

Length:

1 Character

Character Type:

Alpha

## 5.319 Landing Threshold Elevation Accuracy Compliance Flag

Definition/Description: Flag that indicates if the Runway Landing Threshold Elevation meets Accuracy Requirements defined as follows:

Difference between Runway Landing Threshold Elevation (A424 PG 5.68) and runway landing threshold elevation measured with an independent means is 5 meters or less.

Source/Content: The field will be populated by the data provider, using one of the three possibilities presented in the below table:

| Field Content   | Description                                                                           |
|-----------------|---------------------------------------------------------------------------------------|
| Y               | Landing Threshold Elevation data meets Accuracy Requirements                          |
| N               | Landing Threshold Elevation data does not meet Accuracy Requirements                  |
| Blank           | Landing Threshold Elevation data has not been evaluated against Accuracy Requirements |

New section was added.

## 5.319-x95 Used On: Runway Record Length: 1 Character Character Type: Alpha

5.320    SBAS Final Approach Course

### 5.319-x95-x96 Definition/Description: The SBAS Final Approach Course field contains the published final approach course of the PBN procedure with SBAS level of service. Source/Content: The content of this field is derived from PBN procedure Final Approach Course. Used On: Path Point Continuation Records Length: 4 Character Character Type: Alpha/Numeric Examples: 2570, 0147, 2910, 347T



## 5.320 SBAS Final Approach Course

New section was added
