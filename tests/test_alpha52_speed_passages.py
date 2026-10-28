import copy

import pytest

from pengucoach.coach.session_features import route_briefing, speed_passages


def route(speeds=None):
    speeds = speeds or ([8]*20 + [16]*10 + [8]*20)
    distance = 0.0
    rows = []
    for i, speed in enumerate(speeds + [speeds[-1]]):
        rows.append({'elapsed_s': i*10, 'distance_km': distance, 'speed_kmh': speed,
                     'position_lat': 48+i*.0001, 'position_long': 11+i*.0001,
                     'power': 0, 'heart_rate': 140, 'track_segment': 0})
        distance += speed*10/3600
    return rows


def test_sustained_passage_without_elevation_and_optional_sensors():
    rows = route()
    result = route_briefing(rows)
    passage, = result['speed_passages']
    assert not result['hills'] and not result['has_elevation']
    assert (passage['start_index'], passage['end_index']) == (20, 30)
    assert (passage['start_s'], passage['end_s'], passage['duration_s']) == (200, 300, 100)
    assert passage['length_m'] == 444 and passage['avg_speed_kmh'] == 16
    assert passage['metrics']['avg_power'] == 0 and passage['metrics']['avg_hr'] == 140
    result = speed_passages([{**r, 'power': None, 'heart_rate': None} for r in rows])
    assert 'avg_power' not in result['speed_passages'][0]['metrics']
    assert 'avg_hr' not in result['speed_passages'][0]['metrics']


def test_pauses_do_not_turn_steady_speed_into_fast_passages():
    assert not speed_passages(route([0]*20+[12]*20+[0]*20))['speed_passages']
    assert not speed_passages(route([12]*40))['speed_passages']
    assert not speed_passages(route([8]*20+[50]+[8]*20))['speed_passages']
    assert not speed_passages(route([8]*20+[16]*2+[8]*20))['speed_passages']
    # Fast but too short in distance even after 30 seconds.
    assert not speed_passages(route([2]*20+[4]*4+[2]*20))['speed_passages']


@pytest.mark.parametrize('key,value', [('speed_kmh', None), ('speed_kmh', -1), ('speed_kmh', 500),
                                      ('elapsed_s', None), ('position_lat', None), ('position_long', 181),
                                      ('distance_km', None), ('track_segment', 1)])
def test_invalid_reading_breaks_short_passages(key, value):
    rows = route([8]*20+[20]*5+[8]*20)
    rows[22][key] = value
    assert not speed_passages(rows)['speed_passages']


def test_time_gaps_resets_and_distance_jumps_break_detection():
    for key, value in [('elapsed_s', 100), ('elapsed_s', 1000), ('distance_km', 0), ('distance_km', 99)]:
        rows = route([8]*20+[20]*5+[8]*20)
        rows[22][key] = value
        assert not speed_passages(rows)['speed_passages']
    for key in ['elapsed_s', 'distance_km', 'speed_kmh', 'position_lat']:
        result = speed_passages([{**r, key: None} for r in route()])
        assert not result['has_speed'] and not result['speed_passages']
    assert not speed_passages(route([8]*3+[16]*2))['speed_passages']


def test_speed_threshold_and_average_weight_actual_seconds():
    rows = route()
    # Sparse faster samples have more duration; no unweighted sensor averaging.
    for i, row in enumerate(rows):
        row['elapsed_s'] = i*5 if i <= 20 else 100+(i-20)*20 if i <= 30 else 300+(i-30)*5
    rows[20]['speed_kmh'] = 20
    passage, = speed_passages(rows)['speed_passages']
    assert passage['avg_speed_kmh'] == 16.4 and passage['duration_s'] == 200
    assert passage['metrics']['avg_speed_kmh'] == 16.4


def test_longest_eight_passages_return_in_route_order_without_mutation():
    rows = route(sum(([8]*20+[16]*(5+i) for i in range(10)), [])+[8]*20)
    before = copy.deepcopy(rows)
    result = speed_passages(rows)
    assert len(result['speed_passages']) == 8
    indices = [p['start_index'] for p in result['speed_passages']]
    assert indices == sorted(indices) and indices[0] > 20
    assert rows == before
