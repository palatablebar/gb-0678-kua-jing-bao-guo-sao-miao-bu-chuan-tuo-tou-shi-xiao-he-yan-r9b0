REASONS={"BAD_COLUMNS":"列数不匹配","EMPTY_VALUE":"必填值为空","INVALID_NUMBER":"数字格式错误","INVALID_TIME":"时间缺少偏移或格式错误","DUPLICATE_CONFLICT":"同键取值冲突","UNKNOWN_REFERENCE":"引用不存在","STALE_VERSION":"版本已更新","EMPTY_FILE":"文件为空","HEADER_ONLY":"仅有表头","BLANK_ONLY":"全部为空行","MISSING_DEPART":"缺少起运扫描，时段保留待定归属","MISSING_CUSTOMS":"缺少清关扫描，时段保留待定归属","MISSING_DELIVERED":"缺少妥投扫描，尾段保留待定归属","SIMULTANEOUS_CONFLICT":"同刻扫描节点冲突","PATH_REGRESSION":"扫描路径倒退","SEGMENT_NOT_BALANCED":"分段工时与总工时不平"}
def reject(row, code, detail):
    return {**row,"reason":code,"detail":detail}
def sources(row):
    return row.get("_sources", [row.get("_line",0)])
