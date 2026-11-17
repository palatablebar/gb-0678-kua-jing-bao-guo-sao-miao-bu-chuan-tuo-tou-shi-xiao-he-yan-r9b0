# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV。

时效计算（M5）每行附带 `segments` 分段数组：`key`/`name` 标识环节，`start_utc`/`end_utc` 为事件发生时刻，`working_hours` 为该段目的地工作日工时，`status` 为 `attributed` 或 `pending`。待定段带 `reason`（MISSING_DEPART/MISSING_CUSTOMS/MISSING_DELIVERED/SIMULTANEOUS_CONFLICT/PATH_REGRESSION）与 `action` 催办语；`segment_hours` 恒等于 `working_hours`，`main_delay_segment` 给出首个耗尽承诺工时的环节（在待定段耗尽则保持待定）。M4 行新增 `node_times` 与 `events`，供按扫描路径重建分段。
