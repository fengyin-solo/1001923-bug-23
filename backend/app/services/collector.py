"""集电线路业务规则：状态流转、字段校验、筛选口径、调度台账回写都收在这里。"""
from __future__ import annotations

import threading
from datetime import date
from typing import Any

from app.store import store

MODULE = "collector"
LEDGER_MODULE = "dispatch_ledger"
REQUIRED_FIELDS = ["线路编号", "电压等级", "起止杆塔"]
# 登记时允许写入的业务字段；线路状态由状态流转决定，不接受直接填写。
OPTIONAL_FIELDS = ["线路长度", "所属场站", "上次巡视日"]
STATUS_ORDER = ["待巡视", "运行正常", "存在缺陷", "已停运"]
ACTION_RULES = {"提交巡视": "运行正常", "登记缺陷": "存在缺陷", "停运线路": "已停运"}
# 动作回写到调度台账时的处置结果口径。
LEDGER_RESULTS = {"提交巡视": "巡视已提交", "登记缺陷": "已挂缺陷", "停运线路": "已停运"}

# 筛选条件按线路编号 → 电压等级 → 起止杆塔的顺序逐步收紧，
# 命不中时好说明到底是哪一步对不上。
FILTER_STEPS: list[tuple[str, str]] = [
    ("line_no", "线路编号"),
    ("voltage", "电压等级"),
    ("towers", "起止杆塔"),
]


class CollectorService:
    def __init__(self) -> None:
        # FastAPI 的同步接口跑在线程池里，并发提交同一张线路编号时要串行化，
        # 保证同一编号只登记成功一条。
        self._write_lock = threading.Lock()

    # ---- 列表 / 明细 ---------------------------------------------------

    def _base_rows(self) -> list[dict[str, Any]]:
        """默认排序取数：按 id 升序，每次进入次序一致。

        同一张线路编号只保留 id 最小的一条，重复编号不重复显示。
        """
        rows = sorted(store.rows(MODULE), key=lambda row: int(row.get("id", 0)))
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for row in rows:
            line_no = str(row.get("线路编号", "")).strip()
            if line_no in seen:
                continue
            seen.add(line_no)
            unique.append(row)
        return unique

    def _present(self, row: dict[str, Any]) -> dict[str, Any]:
        """对外投影：列表与明细走同一份字段口径。

        线路长度取台账里登记的同一个值；线路状态统一由内部状态字段派生，
        避免列表和详情各显示一套。
        """
        item = dict(row)
        item["线路状态"] = row.get("status")
        return item

    def list_entries(
        self,
        *,
        line_no: str | None = None,
        voltage: str | None = None,
        towers: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int, str | None]:
        """按线路编号、电压等级、起止杆塔逐步过滤；返回 (当页数据, 总数, 未命中说明)。"""
        conditions = {
            "line_no": (line_no or "").strip(),
            "voltage": (voltage or "").strip(),
            "towers": (towers or "").strip(),
        }
        rows = self._base_rows()
        notice: str | None = None
        prior_step_matched = False
        for param, label in FILTER_STEPS:
            value = conditions[param]
            if not value:
                continue
            next_rows = [
                row for row in rows
                if value in str(row.get(label, "") or "")
            ]
            if not next_rows:
                # 说清是哪一步对不上：编号/电压/杆塔，以及是在什么范围里没对上。
                scope = "已按前序条件命中的线路" if prior_step_matched else "全部线路"
                notice = f"没有命中：按{label}「{value}」在{scope}中未找到匹配线路，已保留当前筛选条件"
                rows = next_rows
                break
            rows = next_rows
            prior_step_matched = True

        total = len(rows)
        start = max(page - 1, 0) * size
        items = [self._present(row) for row in rows[start:start + size]]
        return items, total, notice

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        """明细与列表共用同一份投影，线路长度、线路状态取值一致。"""
        row = store.find(MODULE, entry_id)
        if row is None:
            return None
        return self._present(row)

    # ---- 登记 ----------------------------------------------------------

    def _find_by_line_no(self, line_no: str) -> dict[str, Any] | None:
        for row in self._base_rows():
            if str(row.get("线路编号", "")).strip() == line_no:
                return row
        return None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str], str]:
        """登记集电线路。

        线路编号沿用调度台账既有字段：编号必须先在台账里建档；
        同一编号并发提交只留一条（重复提交幂等返回既有那条）。
        返回 (记录, 缺失字段, 未命中/重复等说明)。
        """
        cleaned = {
            field: str(values.get(field) or "").strip()
            for field in REQUIRED_FIELDS + OPTIONAL_FIELDS
        }
        missing = [field for field in REQUIRED_FIELDS if not cleaned[field]]
        if missing:
            return None, missing, ""

        line_no = cleaned["线路编号"]
        with self._write_lock:
            ledger_row = self._find_ledger(line_no)
            if ledger_row is None:
                return None, [], (
                    f"线路编号「{line_no}」在调度台账中查不到，"
                    "请沿用既有台账已建档的线路编号，或先在调度台账建档"
                )
            existing = self._find_by_line_no(line_no)
            if existing is not None:
                return self._present(existing), [], f"线路编号「{line_no}」已登记，本次为重复提交，只保留既有那一条"

            rows = store.rows(MODULE)
            entry: dict[str, Any] = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
            for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
                if cleaned[field]:
                    entry[field] = cleaned[field]
            entry.setdefault("缺陷数量", 0)
            entry["status"] = STATUS_ORDER[0]
            entry["pending"] = True
            entry["abnormal"] = False
            rows.append(entry)
            # 登记即纳入台账处置闭环。
            self._write_ledger(line_no, "已登记")
            return self._present(entry), [], ""

    # ---- 动作流转 ------------------------------------------------------

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"集电线路 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于集电线路可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = target == "存在缺陷"
        line_no = str(entry.get("线路编号", "")).strip()
        # 处置结果回写调度台账（线路编号沿用台账字段）。
        self._write_ledger(line_no, LEDGER_RESULTS[action])
        return self._present(entry), f"集电线路已{action}，处置结果已回写调度台账"

    # ---- 调度台账 ------------------------------------------------------

    def list_ledger(self) -> list[dict[str, Any]]:
        return sorted(
            (dict(row) for row in store.rows(LEDGER_MODULE)),
            key=lambda row: str(row.get("线路编号", "")),
        )

    def _find_ledger(self, line_no: str) -> dict[str, Any] | None:
        for row in store.rows(LEDGER_MODULE):
            if str(row.get("线路编号", "")).strip() == line_no:
                return row
        return None

    def _write_ledger(self, line_no: str, result: str) -> None:
        """把处置结果 upsert 到调度台账：既有编号就地更新，没有就补建。"""
        row = self._find_ledger(line_no)
        if row is None:
            store.rows(LEDGER_MODULE).append(
                {"线路编号": line_no, "处置结果": result, "处置时间": date.today().isoformat(), "备注": "由集电线路登记自动建档"}
            )
            return
        row["处置结果"] = result
        row["处置时间"] = date.today().isoformat()
