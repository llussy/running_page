#!/usr/bin/env python3
"""为缺少地理位置的活动反查 location_country，并从 db 重新生成 activities.json。

背景：generator/db.py 在活动入库时本来就会反查 Nominatim，但那段代码没有任何限速，
首次全量同步（几百上千条）会被 Nominatim 限流，且失败是静默的（except: pass），
结果就是 location_country 全为 NULL，前端足迹地图显示 0 个省份。

本脚本按 1 次/秒限速补齐，可断点续跑（已有位置的会跳过）。

用法：
    python run_page/fix_run_location.py                 # 补齐所有缺位置的活动
    python run_page/fix_run_location.py --dry-run       # 只看要处理哪些，不写库
    python run_page/fix_run_location.py --type Run      # 只处理跑步
    python run_page/fix_run_location.py --limit 10      # 只处理前 10 条

与自带的 fix_location.py 的区别：
    - 支持 --type 过滤，不必对全量数据反查
    - 可断点续跑
    - 结尾用 Generator.load() 出 json，不走 make_activities_file
      （后者会 sync_from_data_dir 重扫 GPX_OUT，有覆盖刚写入位置的风险）
"""

import argparse
import json
import os
import time

import polyline
from config import JSON_FILE, SQL_FILE
from generator import Generator
from generator.db import Activity, init_db
from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

geocoder = Nominatim(user_agent="running_page_location_fix")


def reverse_geocode(lat, lon, max_retries=3):
    """反查坐标对应的地址，失败返回 None。"""
    for attempt in range(max_retries):
        try:
            loc = geocoder.reverse(f"{lat}, {lon}", language="zh-CN", timeout=10)
            return str(loc) if loc else None
        except (GeocoderTimedOut, GeocoderServiceError) as e:
            if attempt < max_retries - 1:
                time.sleep(2**attempt)
            else:
                print(f"    geocode 失败（重试 {max_retries} 次）: {e}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"    geocode 异常: {e}", flush=True)
            return None
    return None


def pending_activities(session, activity_type=None, limit=None):
    """查出缺位置、但有 polyline 可用的活动。"""
    query = (
        session.query(Activity)
        .filter(Activity.summary_polyline.isnot(None))
        .filter(Activity.summary_polyline != "")
        .filter(
            (Activity.location_country.is_(None))
            | (Activity.location_country == "")
            | (Activity.location_country == "China")
        )
    )
    if activity_type:
        query = query.filter(Activity.type == activity_type)
    query = query.order_by(Activity.start_date_local)
    if limit:
        query = query.limit(limit)
    return query.all()


def regenerate_json():
    """从 db 重新生成 activities.json。"""
    generator = Generator(SQL_FILE)
    activities_list = generator.load()
    with open(JSON_FILE, "w") as f:
        json.dump(activities_list, f)
    print(
        f"已写入 {JSON_FILE}（{len(activities_list)} 条，"
        f"{os.path.getsize(JSON_FILE)} bytes）",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description="补齐活动的地理位置信息")
    parser.add_argument("--type", dest="activity_type", help="只处理指定类型，如 Run")
    parser.add_argument("--limit", type=int, help="最多处理多少条")
    parser.add_argument("--sleep", type=float, default=1.0, help="每次请求间隔秒数")
    parser.add_argument(
        "--dry-run", action="store_true", help="只列出待处理的活动，不写库"
    )
    args = parser.parse_args()

    session = init_db(SQL_FILE)
    todo = pending_activities(session, args.activity_type, args.limit)
    total = len(todo)
    print(f"待处理活动: {total}", flush=True)

    if not total:
        print("没有需要补位置的活动。", flush=True)
        return

    if args.dry_run:
        for act in todo[:20]:
            print(f"  {act.run_id}  {act.start_date_local}  {act.type}")
        if total > 20:
            print(f"  ...（共 {total} 条）")
        print("\n去掉 --dry-run 才会实际写入。")
        return

    fixed = 0
    for i, act in enumerate(todo, 1):
        try:
            points = polyline.decode(act.summary_polyline)
        except Exception as e:  # noqa: BLE001
            print(f"[{i}/{total}] {act.run_id} polyline 解码失败: {e}", flush=True)
            continue
        if not points:
            print(f"[{i}/{total}] {act.run_id} polyline 为空", flush=True)
            continue

        lat, lon = points[0]
        location = reverse_geocode(lat, lon)
        if location:
            act.location_country = location
            session.add(act)
            session.commit()
            fixed += 1
            if i == 1 or i % 25 == 0:
                print(f"[{i}/{total}] {act.run_id} -> {location[:60]}", flush=True)
        else:
            print(f"[{i}/{total}] {act.run_id} 反查无结果", flush=True)

        if i < total:
            time.sleep(args.sleep)

    print(f"\n完成: 写入位置 {fixed}/{total}", flush=True)
    print("重新生成 activities.json ...", flush=True)
    regenerate_json()


if __name__ == "__main__":
    main()
