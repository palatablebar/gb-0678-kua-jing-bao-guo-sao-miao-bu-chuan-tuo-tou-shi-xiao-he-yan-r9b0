from app.modules.m5_timeliness.rules import working_hours,evaluate,build_legs
from app.modules.m4_paths.rules import evaluate as evaluate_paths
from app.values import instant
from decimal import Decimal
import pytest
from app.errors import DomainError
def test_real_holiday_excluded(result): assert result["stages"][4]["rows"][0]["working_hours"]=="24.0"
def test_real_sla_uses_event_not_upload(result): assert result["stages"][4]["metrics"]["compensation"]=="0.00"
def test_holiday_full_day_stops():
    "TRAP-23"
    assert working_hours(instant("2026-11-02T15:00:00Z"),instant("2026-11-03T15:00:00Z"),"Asia/Tokyo",{"2026-11-03"})==0
def test_weekend_stops(): assert working_hours(instant("2026-11-06T15:00:00Z"),instant("2026-11-08T15:00:00Z"),"Asia/Tokyo",set())==0
def test_reversed_interval_rejected():
    with pytest.raises(DomainError):working_hours(instant("2026-11-04T00:00:00Z"),instant("2026-11-02T00:00:00Z"),"Asia/Tokyo",set())
def test_compensation_capped():
    row={"accepted_at":"2026-11-02T00:00:00Z","delivered_at":"2026-11-06T00:00:00Z","zone":"Asia/Tokyo","destination":"JP","promised_hours":"0","declared_value":"100"}
    assert evaluate([row],{})["rows"][0]["expected"]=="10.00"
def test_dst_actual_elapsed_hours():
    "TRAP-12"
    assert working_hours(instant("2026-11-01T04:00:00Z"),instant("2026-11-02T05:00:00Z"),"America/New_York",set())==0
def _scan(i,node,at,received="2026-11-09T00:00:00Z",parcel="P1"):
    return {"scan_id":str(i),"parcel":parcel,"node":node,"event_utc":at,"received_utc":received,
            "zone":"Asia/Tokyo","destination":"JP","promised_hours":"24","declared_value":"200","reported":"0","_sources":[i]}
def _m5(events,quarantine=None):
    paths=evaluate_paths(events,{})
    ctx={"parameters":{},"quarantine":quarantine if quarantine is not None else list(paths["quarantine"])}
    return evaluate(paths["rows"],ctx),paths
def test_real_segments_sum_to_total(result):
    "TRAP-24 各段工时相加必须等于原总时差"
    for row in result["stages"][4]["rows"]:
        assert Decimal(row["segment_hours"])==Decimal(row["working_hours"])
        assert sum(leg["working_micros"] for leg in row["segments"])>=0
        assert row["segments"]  # 任何包裹至少有一段，时间不允许被静默删除
def test_real_three_attributed_legs(result):
    legs=result["stages"][4]["rows"][0]["segments"]
    assert [leg["key"] for leg in legs]==["leg_depart","leg_carriage","leg_last_mile"]
    assert all(leg["status"]=="attributed" for leg in legs)
    assert [leg["working_hours"] for leg in legs]==["12.0","3.0","9.0"]
def test_missing_depart_kept_pending_not_merged():
    "TRAP-25 缺起运扫描：跨段保留待定归属，不并入相邻环节，时长不删"
    r,_=_m5([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),_scan(2,"CUSTOMS","2026-11-03T00:00:00Z"),
             _scan(3,"DELIVERED","2026-11-04T00:00:00Z")])
    row=r["rows"][0];gap=row["segments"][0]
    assert gap["status"]=="pending" and gap["reason"]=="MISSING_DEPART"
    assert "催补起运扫描" in gap["action"]
    assert Decimal(row["segment_hours"])==Decimal(row["working_hours"])
def test_missing_customs_pending_bears_delay():
    "责任段结论：SLA在待定段耗尽时，主延误段保持待定，不栽给相邻环节"
    r,_=_m5([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),_scan(2,"DEPART","2026-11-02T12:00:00Z"),
             _scan(3,"DELIVERED","2026-11-05T00:00:00Z")])
    row=r["rows"][0]
    assert row["sla"]=="超时" and row["main_delay_pending"] is True
    assert "待定归属" in row["main_delay_segment"]
def test_missing_delivery_tail_pending():
    "未妥投：到as_of的尾段保留待定，仍计入总工时"
    r,_=_m5([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),_scan(2,"DEPART","2026-11-02T12:00:00Z"),
             _scan(3,"CUSTOMS","2026-11-03T00:00:00Z")])
    row=r["rows"][0];tail=row["segments"][-1]
    assert tail["reason"]=="MISSING_DELIVERED" and tail["status"]=="pending"
    assert Decimal(row["segment_hours"])==Decimal(row["working_hours"])
def test_simultaneous_conflict_marks_pending():
    "TRAP-25 同刻冲突被M4隔离后，对应时段沿用冲突原因挂待定"
    r,paths=_m5([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),_scan(2,"DEPART","2026-11-02T00:00:00Z"),
                 _scan(3,"CUSTOMS","2026-11-03T00:00:00Z"),_scan(4,"DELIVERED","2026-11-04T00:00:00Z")])
    assert paths["quarantine"][0]["reason"]=="SIMULTANEOUS_CONFLICT"
    gap=r["rows"][0]["segments"][0]
    assert gap["status"]=="pending" and gap["reason"]=="SIMULTANEOUS_CONFLICT"
def test_conflict_reason_is_node_specific():
    "其他节点的路径倒退隔离，不得误挂到无关的缺节点待定段"
    r,paths=_m5([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),_scan(2,"DEPART","2026-11-02T12:00:00Z"),
                 _scan(3,"DELIVERED","2026-11-04T00:00:00Z"),
                 _scan(4,"ACCEPT","2026-11-05T00:00:00Z")])
    assert any(q["reason"]=="PATH_REGRESSION" for q in paths["quarantine"])
    gap=[leg for leg in r["rows"][0]["segments"] if leg["status"]=="pending"][0]
    assert gap["reason"]=="MISSING_CUSTOMS"
def test_late_upload_event_time_segments():
    "TRAP-13 延伸：妥投迟到补传不改变分段结论"
    r,_=_m5([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),_scan(2,"DEPART","2026-11-02T12:00:00Z"),
             _scan(3,"CUSTOMS","2026-11-03T00:00:00Z"),
             _scan(4,"DELIVERED","2026-11-04T00:00:00Z",received="2026-11-20T00:00:00Z")])
    row=r["rows"][0]
    assert [leg["key"] for leg in row["segments"]]==["leg_depart","leg_carriage","leg_last_mile"]
    assert Decimal(row["segment_hours"])==Decimal(row["working_hours"])==Decimal("24.0")
def test_late_arriving_scan_resolves_pending_segment():
    "晚到事件会改变责任段：补传前待定，补传后转为有归属，总工时不变"
    before_paths=evaluate_paths([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),_scan(3,"CUSTOMS","2026-11-03T00:00:00Z"),
                                 _scan(4,"DELIVERED","2026-11-04T00:00:00Z")],{})
    before=evaluate(before_paths["rows"],{"parameters":{},"quarantine":[]})["rows"][0]
    after_paths=evaluate_paths([_scan(1,"ACCEPT","2026-11-02T00:00:00Z"),
                                _scan(2,"DEPART","2026-11-02T12:00:00Z",received="2026-11-08T00:00:00Z"),
                                _scan(3,"CUSTOMS","2026-11-03T00:00:00Z"),_scan(4,"DELIVERED","2026-11-04T00:00:00Z")],{})
    after=evaluate(after_paths["rows"],{"parameters":{},"quarantine":[]})["rows"][0]
    assert any(leg["status"]=="pending" for leg in before["segments"])
    assert all(leg["status"]=="attributed" for leg in after["segments"])
    assert before["working_hours"]==after["working_hours"]
def test_main_delay_segment_first_to_exhaust_sla():
    row={"parcel":"P","accepted_at":"2026-11-02T00:00:00+00:00","delivered_at":"2026-11-10T00:00:00+00:00",
         "zone":"Asia/Tokyo","destination":"JP","promised_hours":"24","declared_value":"200",
         "node_times":{"ACCEPT":"2026-11-02T00:00:00+00:00","DEPART":"2026-11-02T12:00:00+00:00",
                       "CUSTOMS":"2026-11-03T00:00:00+00:00","DELIVERED":"2026-11-10T00:00:00+00:00"}}
    row=evaluate([row],{"parameters":{},"quarantine":[]})["rows"][0]
    assert row["main_delay_segment"]=="清关→妥投（末端段）" and row["main_delay_pending"] is False
def test_pending_metrics_counted(result):
    m=result["stages"][4]["metrics"]
    assert m["pending_segments"]==0 and m["pending_parcels"]==0
    assert m["segment_balanced"] is True
def test_fallback_without_node_times_still_balances():
    row={"parcel":"P","accepted_at":"2026-11-02T00:00:00+00:00","delivered_at":"2026-11-04T00:00:00+00:00",
         "zone":"Asia/Tokyo","destination":"JP","promised_hours":"24","declared_value":"200"}
    out=evaluate([row],{"parameters":{},"quarantine":[]})["rows"][0]
    assert Decimal(out["segment_hours"])==Decimal(out["working_hours"])
    assert out["segments"][0]["status"]=="pending"
