from pengucoach.imports.manual_activity import parse_gpx_bytes, parse_tcx_bytes


def test_parse_gpx_activity():
    raw = b'''<?xml version="1.0"?><gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"><trk><name>Morning Run</name><type>running</type><trkseg><trkpt lat="48.0" lon="11.0"><ele>400</ele><time>2026-09-20T08:00:00Z</time><extensions><hr>120</hr></extensions></trkpt><trkpt lat="48.0009" lon="11.0"><ele>405</ele><time>2026-09-20T08:01:00Z</time><extensions><hr>140</hr></extensions></trkpt></trkseg></trk></gpx>'''
    df, session, name, sport = parse_gpx_bytes(raw)
    assert name == "Morning Run"
    assert sport == "running"
    assert len(df) == 2
    assert df.iloc[1]["distance"] > 90
    assert df.iloc[0]["heart_rate"] == 120
    assert session["source_format"] == "gpx"


def test_parse_tcx_activity():
    raw = b'''<?xml version="1.0"?><TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"><Activities><Activity Sport="Biking"><Id>2026-09-20T09:00:00Z</Id><Lap StartTime="2026-09-20T09:00:00Z"><TotalTimeSeconds>60</TotalTimeSeconds><DistanceMeters>500</DistanceMeters><Calories>20</Calories><Track><Trackpoint><Time>2026-09-20T09:00:00Z</Time><Position><LatitudeDegrees>48</LatitudeDegrees><LongitudeDegrees>11</LongitudeDegrees></Position><AltitudeMeters>400</AltitudeMeters><DistanceMeters>0</DistanceMeters><HeartRateBpm><Value>110</Value></HeartRateBpm></Trackpoint><Trackpoint><Time>2026-09-20T09:01:00Z</Time><Position><LatitudeDegrees>48.001</LatitudeDegrees><LongitudeDegrees>11</LongitudeDegrees></Position><AltitudeMeters>410</AltitudeMeters><DistanceMeters>500</DistanceMeters><HeartRateBpm><Value>145</Value></HeartRateBpm><Extensions><TPX><Speed>8.33</Speed><Watts>180</Watts></TPX></Extensions></Trackpoint></Track></Lap></Activity></Activities></TrainingCenterDatabase>'''
    df, session, name, sport = parse_tcx_bytes(raw)
    assert name is None
    assert sport == "cycling"
    assert len(df) == 2
    assert session["total_distance"] == 500
    assert session["total_timer_time"] == 60
    assert df.iloc[1]["power"] == 180
    assert df.iloc[1]["heart_rate"] == 145
