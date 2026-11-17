from datetime import datetime,timedelta,time
from zoneinfo import ZoneInfo
from decimal import Decimal
from app.values import instant,number,money
from app.errors import DomainError
HOLIDAYS={"JP":{"2026-11-03","2026-11-23"},"US":{"2026-11-26"},"DE":{"2026-10-03"}}
STAGES=[("ACCEPT","收件"),("DEPART","起运"),("CUSTOMS","清关"),("DELIVERED","妥投")]
STAGE_NAME=dict(STAGES);NODE_ORDER=[node for node,_ in STAGES]
# 相邻节点之间的标准环节；缺节点或冲突被隔离时，跨越的时间没有归属证据，只能待定
LEGS={("ACCEPT","DEPART"):("leg_depart","收件→起运（起运段）"),
      ("DEPART","CUSTOMS"):("leg_carriage","起运→清关（干线段）"),
      ("CUSTOMS","DELIVERED"):("leg_last_mile","清关→妥投（末端段）")}
PENDING_ACTION={"MISSING_DEPART":"催补起运扫描，补传后重新分段",
                "MISSING_CUSTOMS":"催补清关扫描，补传后重新分段",
                "MISSING_DELIVERED":"催补妥投扫描，先按在途尾段处理",
                "SIMULTANEOUS_CONFLICT":"核对同刻冲突扫描，确认有效节点后重新分段",
                "PATH_REGRESSION":"核对路径倒退扫描，确认有效节点后重新分段"}
def working_seconds(start,end,zone,holidays):
    "按当地自然日切片，仅累加工作日且非节假日的整数微秒，避免浮点误差"
    if end<start:raise DomainError("NEGATIVE_INTERVAL","妥投早于收件")
    tz=ZoneInfo(zone);cursor=start;micros=0
    while cursor<end:
        local=cursor.astimezone(tz);next_day=datetime.combine(local.date()+timedelta(days=1),time.min,tzinfo=tz).astimezone(cursor.tzinfo)
        stop=min(end,next_day)
        if local.weekday()<5 and local.date().isoformat() not in holidays:micros+=(stop-cursor)//timedelta(microseconds=1)
        cursor=stop
    return micros
def _format_hours(micros):
    "保留与历史口径一致的字符串：整数小时显示 x.0"
    text=str(Decimal(micros)/Decimal(3_600_000_000))
    return text if "." in text else text+".0"
def working_hours(start,end,zone,holidays):
    return Decimal(working_seconds(start,end,zone,holidays))/Decimal(3_600_000_000)
def _label(node):return STAGE_NAME.get(node,"截至时刻")
def _leg(micros,key,name,from_node,to_node,start,end,status="attributed",reason=None):
    leg={"key":key,"name":name,"from_node":from_node,"to_node":to_node,
         "start_utc":start.isoformat() if start else None,"end_utc":end.isoformat() if end else None,
         "working_hours":_format_hours(micros),"working_micros":micros,"status":status}
    if reason:
        leg["reason"]=reason;leg["action"]=PENDING_ACTION[reason]
    return leg
def _gap_reason(prev_node,node,conflict_nodes):
    "优先沿用M4对缺失节点的隔离原因（同刻冲突/倒退）；否则按首个缺失节点挂单"
    missing={"ACCEPT":"MISSING_DEPART","DEPART":"MISSING_CUSTOMS","CUSTOMS":"MISSING_DELIVERED"}
    for mid in NODE_ORDER[NODE_ORDER.index(prev_node)+1:NODE_ORDER.index(node)]:
        if mid in conflict_nodes:return conflict_nodes[mid]
    return missing.get(prev_node,"MISSING_DELIVERED")
def build_legs(row,clock_end,zone,holidays,conflict_nodes=None):
    "以事件发生时刻重建分段；无证据归属的跨段保留待定，不并入相邻环节，也不删除时长"
    conflict_nodes=conflict_nodes or {}
    times=dict(row.get("node_times") or {})
    times.setdefault("ACCEPT",row["accepted_at"])
    if row.get("delivered_at"):times.setdefault("DELIVERED",row["delivered_at"])
    boundaries=[(node,instant(times[node])) for node,_ in STAGES if node in times]
    legs=[]
    for index,(node,ts) in enumerate(boundaries[1:],1):
        prev_node,prev_ts=boundaries[index-1]
        micros=working_seconds(prev_ts,ts,zone,holidays)
        if (prev_node,node) in LEGS:
            key,name=LEGS[(prev_node,node)]
            legs.append(_leg(micros,key,name,prev_node,node,prev_ts,ts))
        else:
            reason=_gap_reason(prev_node,node,conflict_nodes)
            name=f"{_label(prev_node)}→{_label(node)}（待定归属）"
            legs.append(_leg(micros,"leg_pending",name,prev_node,node,prev_ts,ts,"pending",reason))
    if not row.get("delivered_at"):
        last_node,last_ts=boundaries[-1]
        micros=working_seconds(last_ts,clock_end,zone,holidays)
        reason=conflict_nodes.get("DELIVERED","MISSING_DELIVERED")
        legs.append(_leg(micros,"leg_pending",f"{_label(last_node)}→截至（待定尾段）",last_node,"AS_OF",last_ts,clock_end,"pending",reason))
    return legs
def main_delay(legs,promised):
    "承诺工时沿路径逐段扣减，首个耗尽SLA的环节负主责；耗尽发生在待定段则责任同样待定"
    remaining=promised
    for leg in legs:
        hours=Decimal(leg["working_hours"])
        if hours>remaining:
            return leg["name"],leg["status"]=="pending"
        remaining-=hours
    return None,False
def evaluate(rows,context):
    p=context.get("parameters",{});as_of=instant(p.get("as_of","2026-11-18T00:00:00Z"));rate=number(p.get("hourly_compensation","1.00"))
    if rate<0:raise DomainError("BAD_RATE","赔付费率不能为负")
    conflicts={}
    for q in context.get("quarantine",[]):
        if q.get("reason") in ("SIMULTANEOUS_CONFLICT","PATH_REGRESSION"):
            conflicts.setdefault(q.get("parcel"),{})[q.get("node")]=q["reason"]
    good=[];pending_segments=0;pending_parcels=0
    for row in rows:
        start=instant(row["accepted_at"]);end=instant(row["delivered_at"]) if row.get("delivered_at") else max(start,as_of)
        holidays=set(p.get("holidays",{}).get(row["destination"],HOLIDAYS.get(row["destination"],set())))
        total_micros=working_seconds(start,end,row["zone"],holidays)
        legs=build_legs(row,end,row["zone"],holidays,conflicts.get(row.get("parcel")))        # 对账不变式：各段工时相加之值必须等于原总时差，任何无证据时段都不得被静默丢弃
        segment_micros=sum(leg["working_micros"] for leg in legs)
        if segment_micros!=total_micros:
            raise DomainError("SEGMENT_NOT_BALANCED",f"包裹{row.get('parcel')}分段工时与总工时不平")
        hours=Decimal(_format_hours(total_micros));promised=number(row["promised_hours"])
        late=max(Decimal(0),hours-promised);comp=min(number(row["declared_value"])*Decimal("0.10"),late*rate)
        delay_name,delay_pending=main_delay(legs,promised)
        pending_count=sum(leg["status"]=="pending" for leg in legs)
        pending_segments+=pending_count;pending_parcels+=1 if pending_count else 0
        good.append({**row,"working_hours":str(hours),"late_hours":str(late),"expected":money(comp),
                     "sla":"超时" if late>0 else "达标","clock_end":end.isoformat(),
                     "segments":legs,"segment_hours":_format_hours(segment_micros),
                     "main_delay_segment":delay_name or "无（达标）","main_delay_pending":delay_pending,
                     "pending_segment_count":pending_count})
    return {"rows":good,"quarantine":[],"metrics":{"parcels":len(good),"late_parcels":sum(r["sla"]=="超时" for r in good),
            "compensation":money(sum((number(r["expected"]) for r in good),Decimal(0))),
            "pending_segments":pending_segments,"pending_parcels":pending_parcels,
            "segment_balanced":all(Decimal(r["segment_hours"])==Decimal(r["working_hours"]) for r in good)}}
