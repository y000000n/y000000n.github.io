from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
import ipaddress
import json
import random
import re
import socket
import ssl
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

import pandas as pd
import certifi
import streamlit as st
import streamlit.components.v1 as components

import db

st.set_page_config(page_title="통역 졸업시험 플래너", page_icon="🎧", layout="wide")
db.init_db()
_component_dir = Path(__file__).with_name("script_highlighter_v11")
script_highlighter_component = (
    components.declare_component("script_highlighter_native_v18", path=str(_component_dir))
    if _component_dir.is_dir() else None
)
_material_editor_dir = Path(__file__).with_name("study_material_editor")
study_material_editor_component = (
    components.declare_component("study_material_editor_v1", path=str(_material_editor_dir))
    if _material_editor_dir.is_dir() else None
)

st.markdown("""
<style>
  .stApp { background: #f7f8fa; }
  [data-testid="stMetric"] { background:white; border:1px solid #e8eaee; padding:18px; border-radius:14px; }
  .hero { padding:22px 26px; border-radius:18px; color:white; background:linear-gradient(120deg,#263b73,#4069b1); margin-bottom:20px; }
  .hero h1 { margin:0 0 6px; font-size:1.75rem; }
  .hero p { margin:0; opacity:.85; }
  .card { background:white; border:1px solid #e8eaee; border-radius:14px; padding:20px; }
  .muted { color:#667085; font-size:.92rem; }
  [data-testid="stSidebar"] div[role="radiogroup"] { gap:7px; }
  [data-testid="stSidebar"] div[role="radiogroup"] label { padding:10px 12px; border-radius:10px; transition:.15s; }
  [data-testid="stSidebar"] div[role="radiogroup"] label:hover { background:#e9eef8; }
  [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) { background:#315a9c; color:white; }
  [data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p { color:white; font-weight:700; }
  [data-testid="stSidebar"] div[role="radiogroup"] label > div:first-child { display:none; }
  [data-testid="stSidebar"] div[role="radiogroup"] label { margin-left:0; }
</style>
""", unsafe_allow_html=True)

TYPE_LABELS = {"collocation": "콜로케이션", "term": "용어", "pattern": "패턴", "other": "기타"}
ACTIVITY_LABELS = {"simultaneous": "동시통역", "consecutive": "순차통역", "sight_translation": "시역", "shadowing": "섀도잉"}
ERROR_LABELS = {
    "omission": "내용 누락", "number_omission": "숫자 누락", "logic_error": "논리관계 오류",
    "expression_block": "표현 막힘", "unnatural_expression": "부자연스러운 표현",
}


def hero(title: str, subtitle: str) -> None:
    st.markdown(f'<div class="hero"><h1>{title}</h1><p>{subtitle}</p></div>', unsafe_allow_html=True)


def edit_button(table, row, fields, summary, key):
    left, right = st.columns([8,1])
    left.caption(summary)
    with right.popover("수정", use_container_width=True):
        values = {}
        for field, label in fields:
            current = row.get(field, "")
            if field in ("activity_type", "pair_type", "interpretation_type", "direction"):
                if field == "activity_type": options, shown = list(ACTIVITY_LABELS), ACTIVITY_LABELS.get(current,current)
                elif field == "pair_type": options, shown = list(TYPE_LABELS), TYPE_LABELS.get(current,current)
                elif field == "interpretation_type": options, shown = ["동시통역","순차통역"], current
                else: options, shown = ["KO→JA","JA→KO"], current
                display = ACTIVITY_LABELS if field=="activity_type" else TYPE_LABELS if field=="pair_type" else {}
                values[field] = st.selectbox(label, options, index=options.index(current), format_func=lambda x,d=display:d.get(x,x), key=f"{key}_{field}")
            elif field in ("minutes","difficulty","omission","number_omission","logic_error","expression_block","unnatural_expression","mastery"):
                values[field] = st.number_input(label, min_value=0 if field not in ("minutes","difficulty","mastery") else 1, value=int(current), key=f"{key}_{field}")
            elif field == "video_speed":
                values[field] = st.select_slider(label, options=[round(.7+i*.05,2) for i in range(7)], value=float(current or 1.0), key=f"{key}_{field}")
            elif "script" in field or field in ("content","feedback","other_notes","notes"):
                values[field] = st.text_area(label, value=str(current or ""), height=140, key=f"{key}_{field}")
            else:
                values[field] = st.text_input(label, value=str(current or ""), key=f"{key}_{field}")
        if st.button("변경사항 저장", type="primary", key=f"{key}_save"):
            db.update_record(table, row["id"], values)
            st.success("수정했습니다."); st.rerun()


def selected_record_editor(table, rows, fields, summary_func, key):
    if not rows:
        return
    selected_id = st.selectbox("수정할 기록 선택", [None] + [r["id"] for r in rows],
        format_func=lambda i: "기록을 선택하세요" if i is None else summary_func(next(r for r in rows if r["id"] == i)), key=f"{key}_picker")
    state_key = f"{key}_editing"
    if selected_id is not None and st.button("선택한 기록 수정", key=f"{key}_open"):
        st.session_state[state_key] = selected_id
    editing_id = st.session_state.get(state_key)
    if editing_id is None or not any(r["id"] == editing_id for r in rows): return
    row = next(r for r in rows if r["id"] == editing_id)
    with st.container(border=True):
        st.caption(summary_func(row))
        with st.form(f"{key}_form"):
            values = {}
            for field, label in fields:
                current = row.get(field, "")
                if field in ("activity_type", "pair_type", "interpretation_type", "direction"):
                    if field == "activity_type": options, display = list(ACTIVITY_LABELS), ACTIVITY_LABELS
                    elif field == "pair_type": options, display = list(TYPE_LABELS), TYPE_LABELS
                    elif field == "interpretation_type": options, display = ["동시통역", "순차통역"], {}
                    else: options, display = ["KO→JA", "JA→KO", "없음"], {}
                    if current not in options: current = options[0]
                    values[field] = st.selectbox(label, options, index=options.index(current), format_func=lambda x,d=display:d.get(x,x), key=f"{key}_{editing_id}_{field}")
                elif field in ("minutes","difficulty","omission","number_omission","logic_error","expression_block","unnatural_expression","mastery"):
                    values[field] = st.number_input(label, min_value=0 if field not in ("minutes","difficulty","mastery") else 1, value=int(current), key=f"{key}_{editing_id}_{field}")
                elif field == "video_speed": values[field] = st.select_slider(label, options=[round(.7+i*.05,2) for i in range(7)], value=float(current or 1.0), key=f"{key}_{editing_id}_{field}")
                elif "script" in field or field in ("content","feedback","other_notes","notes"): values[field] = st.text_area(label, value=str(current or ""), height=140, key=f"{key}_{editing_id}_{field}")
                else: values[field] = st.text_input(label, value=str(current or ""), key=f"{key}_{editing_id}_{field}")
            save, cancel = st.columns(2)
            if save.form_submit_button("변경사항 저장", type="primary", use_container_width=True):
                if table == "practices" and values.get("activity_type") == "shadowing": values["direction"] = "없음"
                db.update_record(table, row["id"], values); st.session_state[state_key] = None; st.rerun()
            if cancel.form_submit_button("취소", use_container_width=True): st.session_state[state_key] = None; st.rerun()


def dashboard():
    settings = db.get_settings()
    exam = datetime.strptime(settings["exam_date"], "%Y-%m-%d").date()
    dday = (exam - date.today()).days
    hero("오늘도 한 문장씩, 더 정확하게", f"졸업시험까지 D-{dday}" if dday >= 0 else f"시험일로부터 {abs(dday)}일")
    today = date.today().isoformat()
    week = db.week_start()
    week_practices = db.practices_between(week)
    mins = {direction: sum(r["minutes"] for r in week_practices if r["activity_type"] != "shadowing" and r["direction"] == direction) for direction in ("KO→JA", "JA→KO")}
    pair_count = sum(1 for r in db.all_pairs() if str(r["created_at"])[:10] >= week)
    total_goal = int(settings["weekly_ko_ja_goal"]) + int(settings["weekly_ja_ko_goal"])
    total_mins = sum(mins.values())
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("시험 D-day", f"D-{dday}" if dday >= 0 else "종료")
    c2.metric("이번 주 연습", f"{total_mins}분", f"목표 {total_goal}분")
    c3.metric("연습 목표 진행률", f"{min(100, total_mins / total_goal * 100) if total_goal else 0:.0f}%")
    c4.metric("이번 주 신규 언어쌍", f"{pair_count}개", f"목표 {settings['weekly_pairs_goal']}개")
    st.subheader("오늘의 기본 루틴")
    routines = [
        ("simultaneous", "KO→JA", "KO→JA 동시통역"),
        ("simultaneous", "JA→KO", "JA→KO 동시통역"),
        ("consecutive", "KO→JA", "KO→JA 순차통역"),
        ("consecutive", "JA→KO", "JA→KO 순차통역"),
        ("shadowing", None, "섀도잉"),
    ]
    today_raw = db.practices_between(today, today)
    def routine_minutes(rows, activity, direction):
        return sum(r["minutes"] for r in rows if r["activity_type"] == activity and (direction is None or r["direction"] == direction))
    cols = st.columns(5)
    for col, (activity, direction, label) in zip(cols, routines):
        current = routine_minutes(today_raw, activity, direction)
        col.markdown(f"### {'✅' if current >= 10 else '⬜'} {label}")
        col.caption(f"오늘 {current}분 / 기본 10분")
        col.progress(min(current / 10, 1.0))
    today_sight_events = db.sight_translation_events(today, today)
    sight_cols = st.columns(2)
    for col, direction in zip(sight_cols, ("KO→JA", "JA→KO")):
        sight_count = sum(1 for e in today_sight_events if e["direction"] == direction)
        col.markdown(f"### {'✅' if sight_count >= 7 else '⬜'} {direction} 시역")
        col.caption(f"오늘 {sight_count}회 / 기본 7회")
        col.progress(min(sight_count / 7, 1.0))
    st.subheader("이번 주 루틴 실천표")
    week_days = [date.fromisoformat(week) + timedelta(days=i) for i in range(7)]
    weekly_raw = db.practices_between(week_days[0].isoformat(), week_days[-1].isoformat())
    table = []
    for activity, direction, label in routines:
        row = {"기본 루틴": label}
        for day in week_days:
            day_rows = [r for r in weekly_raw if str(r["practice_date"])[:10] == day.isoformat()]
            amount = routine_minutes(day_rows, activity, direction)
            row[f"{day.strftime('%m/%d')}\n{'월화수목금토일'[day.weekday()]}"] = "✅" if amount >= 10 else (f"{amount}분" if amount else "—")
        table.append(row)
    sight_events = db.sight_translation_events(week_days[0].isoformat(), week_days[-1].isoformat())
    for direction in ("KO→JA", "JA→KO"):
        row = {"기본 루틴": f"{direction} 시역(회)"}
        for day in week_days:
            count = sum(1 for e in sight_events if str(e["practice_date"])[:10] == day.isoformat() and e["direction"] == direction)
            row[f"{day.strftime('%m/%d')}\n{'월화수목금토일'[day.weekday()]}"] = count
        table.append(row)
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.subheader("최근 공부 메모")
    recent_notes = db.all_notes()[:3]
    if recent_notes:
        for note in recent_notes:
            with st.container(border=True):
                st.markdown(f"**{note['title']}** · {note['note_date']}")
                st.write(note["content"])
                if note["tags"]: st.caption(f"#{note['tags'].replace(',', ' #')}")
    else:
        st.caption("아직 작성한 메모가 없습니다. Study Notes에서 첫 메모를 남겨보세요.")
    st.subheader("이번 주 방향별 진행")
    for direction, key in [("KO→JA", "weekly_ko_ja_goal"), ("JA→KO", "weekly_ja_ko_goal")]:
        goal = int(settings[key]); current = mins.get(direction, 0)
        st.write(f"{direction}  ·  {current} / {goal}분")
        st.progress(min(current / goal, 1.0) if goal else 0)
    with st.expander("시험일 및 주간 목표 설정"):
        with st.form("settings"):
            exam_date = st.date_input("졸업시험일", exam)
            x, y, z = st.columns(3)
            ko = x.number_input("KO→JA 주간 목표(분)", 10, 1000, int(settings["weekly_ko_ja_goal"]), 10)
            ja = y.number_input("JA→KO 주간 목표(분)", 10, 1000, int(settings["weekly_ja_ko_goal"]), 10)
            pairs = z.number_input("신규 언어쌍 주간 목표(개)", 1, 500, int(settings["weekly_pairs_goal"]), 5)
            if st.form_submit_button("설정 저장", type="primary"):
                db.save_settings({"exam_date": exam_date.isoformat(), "weekly_ko_ja_goal": str(ko), "weekly_ja_ko_goal": str(ja), "weekly_pairs_goal": str(pairs)})
                st.success("설정을 저장했습니다."); st.rerun()


def practice():
    hero("통역 연습", "동시통역·순차통역·섀도잉 연습과 셀프피드백을 기록하세요.")
    st.subheader("오늘의 시역")
    st.caption("기사를 한 편 시역할 때마다 버튼을 누르세요. KO→JA와 JA→KO 각각 하루 7회가 기본 루틴입니다.")
    today_sight = db.sight_translation_events(date.today().isoformat(), date.today().isoformat())
    sight_cols = st.columns(2)
    for col, direction in zip(sight_cols, ("KO→JA", "JA→KO")):
        count = sum(1 for e in today_sight if e["direction"] == direction)
        with col.container(border=True):
            st.markdown(f"### {'✅' if count >= 7 else '⬜'} {direction} 시역")
            st.metric("오늘 횟수", f"{count} / 7회", "목표 달성" if count >= 7 else f"{7-count}회 남음")
            st.progress(min(count / 7, 1.0))
            if st.button(f"{direction} 시역 +1", type="primary", use_container_width=True, key=f"sight_top_{direction}"):
                db.add_sight_translation(direction)
                st.rerun()
    st.divider()
    st.subheader("통역 연습 기록")
    with st.form("practice", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("날짜", date.today())
        practice_types = {k:v for k,v in ACTIVITY_LABELS.items() if k != "sight_translation"}
        activity_label = c2.selectbox("연습 유형", list(practice_types.values()))
        activity_type = next(k for k, v in ACTIVITY_LABELS.items() if v == activity_label)
        if activity_type == "shadowing":
            c3.text_input("방향", value="해당 없음", disabled=True)
            direction = "없음"
        else:
            direction = c3.segmented_control("방향", ["KO→JA", "JA→KO"], default="KO→JA")
        title = st.text_input("자료 제목 *", placeholder="예: 기후변화 정상회의 연설 또는 시역 기사 제목")
        topic = st.text_input("주제", placeholder="예: 환경·에너지")
        source_url = st.text_input("자료 URL", placeholder="https://…", help="동시통역·순차통역·시역 자료의 원문, 기사 또는 영상 주소를 저장하세요.")
        c1, c2 = st.columns(2)
        minutes = c1.number_input("실제 연습시간(분)", 1, 300, 10)
        difficulty = c2.slider("체감 난이도", 1, 5, 3)
        video_speed = st.select_slider("동영상 속도", options=[round(0.70 + i * 0.05, 2) for i in range(7)], value=1.0, format_func=lambda x: f"×{x:.2f}", help="동시통역 기록에만 저장됩니다.")
        st.markdown("#### 셀프피드백 오류 횟수")
        cols = st.columns(5)
        errors = {key: cols[i].number_input(label, 0, 999, 0, key=key) for i, (key, label) in enumerate(ERROR_LABELS.items())}
        notes = st.text_area("기타 메모", placeholder="오류 원인이나 다음 연습에서 신경 쓸 점")
        if st.form_submit_button("연습 기록 저장", type="primary", use_container_width=True):
            if not title.strip(): st.error("자료 제목을 입력해주세요.")
            else:
                if source_url.strip() and not source_url.strip().startswith(("http://", "https://")):
                    st.error("자료 URL은 http:// 또는 https://로 시작해야 합니다.")
                else:
                    db.add_practice({"practice_date": day.isoformat(), "activity_type": activity_type, "direction": direction, "title": title.strip(), "topic": topic.strip(), "source_url": source_url.strip() if activity_type in ("simultaneous", "consecutive", "sight_translation") else "", "video_speed": video_speed if activity_type == "simultaneous" else 1.0, "minutes": minutes, "difficulty": difficulty, **errors, "other_notes": notes.strip()})
                    st.success("연습 기록을 저장했습니다.")
    st.subheader("최근 기록")
    rows = [{"날짜":r["practice_date"], "연습유형":ACTIVITY_LABELS.get(r["activity_type"], r["activity_type"]), "방향":"—" if r["activity_type"]=="shadowing" else r["direction"], "자료":r["title"], "주제":r["topic"], "URL":r.get("source_url", ""), "속도":f"×{r.get('video_speed',1.0):.2f}" if r["activity_type"]=="simultaneous" else "—", "분":r["minutes"], "난이도":r["difficulty"]} for r in db.recent_practices(20)]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("아직 연습 기록이 없습니다.")
    if rows:
        st.markdown("#### 기록 수정")
        raw_rows = db.recent_practices(20)
        fields = [(x,y) for x,y in [("practice_date","날짜"),("activity_type","연습 유형"),("direction","방향"),("title","자료 제목"),("topic","주제"),("source_url","URL"),("video_speed","속도"),("minutes","분"),("difficulty","난이도"),("omission","내용 누락"),("number_omission","숫자 누락"),("logic_error","논리 오류"),("expression_block","표현 막힘"),("unnatural_expression","부자연스러운 표현"),("other_notes","메모")]]
        selected_record_editor("practices", raw_rows, fields, lambda r: f"{r['practice_date']} · {ACTIVITY_LABELS.get(r['activity_type'])}{'' if r['activity_type']=='shadowing' else ' '+r['direction']} · {r['title']}", "practice")


def language_pairs():
    hero("언어쌍", "통역 중 바로 꺼내 쓸 표현 덩어리를 모으세요.")
    with st.expander("새 언어쌍 추가", expanded=True):
        with st.form("pair", clear_on_submit=True):
            a, b = st.columns(2)
            korean = a.text_area("한국어 *", placeholder="정책을 적극적으로 추진하다")
            japanese = b.text_area("일본어 *", placeholder="政策を積極的に推進する")
            c1, c2, c3 = st.columns(3)
            pair_type_label = c1.selectbox("유형", list(TYPE_LABELS.values()))
            source = c2.text_input("출처")
            mastery = c3.slider("숙지도", 1, 5, 1)
            notes = st.text_area("메모")
            if st.form_submit_button("언어쌍 저장", type="primary"):
                if not korean.strip() or not japanese.strip(): st.error("한국어와 일본어를 모두 입력해주세요.")
                else:
                    pair_type = next(k for k, v in TYPE_LABELS.items() if v == pair_type_label)
                    db.add_pair({"korean": korean.strip(), "japanese": japanese.strip(), "pair_type": pair_type, "source": source.strip(), "notes": notes.strip(), "mastery": mastery})
                    st.success("언어쌍을 저장했습니다.")
    st.subheader("언어쌍 검색")
    c1, c2, c3 = st.columns([2,1,1])
    term = c1.text_input("검색", placeholder="한국어·일본어·출처 검색", label_visibility="collapsed")
    kind = c2.selectbox("유형 필터", ["전체"] + list(TYPE_LABELS.values()), label_visibility="collapsed")
    mastery_filter = c3.selectbox("숙지도 필터", ["전체"] + [str(i) for i in range(1,6)], label_visibility="collapsed")
    pair_type_filter = next((k for k,v in TYPE_LABELS.items() if v==kind), None)
    rows = db.find_pairs(term, pair_type_filter, None if mastery_filter == "전체" else int(mastery_filter))
    if rows:
        shown = [{"한국어":r["korean"], "일본어":r["japanese"], "유형":TYPE_LABELS[r["pair_type"]], "출처":r["source"], "숙지도":"★"*r["mastery"], "복습":r["review_count"]} for r in rows]
        st.dataframe(shown, use_container_width=True, hide_index=True)
        st.markdown("#### 기록 수정")
        fields = [("korean","한국어"),("japanese","일본어"),("pair_type","유형"),("source","출처"),("notes","메모"),("mastery","숙지도")]
        selected_record_editor("language_pairs", rows, fields, lambda r: f"{r['korean']} → {r['japanese']}", "pair")
    else: st.info("조건에 맞는 언어쌍이 없습니다.")


def review():
    hero("리뷰", "잘 떠오르지 않는 표현이 먼저 나오는 플래시카드입니다.")
    queue = db.review_queue()
    if not queue: st.info("먼저 Language Pairs에서 언어쌍을 추가해주세요."); return
    if "review_pos" not in st.session_state: st.session_state.review_pos = 0
    if "revealed" not in st.session_state: st.session_state.revealed = False
    idx = st.session_state.review_pos % len(queue); card = queue[idx]
    st.caption(f"카드 {idx+1} / {len(queue)} · 복습 {card['review_count']}회")
    st.markdown(f'<div class="card" style="text-align:center;padding:44px"><div class="muted">한국어</div><h2>{card["korean"]}</h2></div>', unsafe_allow_html=True)
    if not st.session_state.revealed:
        if st.button("일본어 정답 보기", type="primary", use_container_width=True): st.session_state.revealed=True; st.rerun()
    else:
        st.markdown(f'<div class="card" style="text-align:center;margin-top:12px"><div class="muted">일본어</div><h2>{card["japanese"]}</h2><p>{card["notes"]}</p></div>', unsafe_allow_html=True)
        cols = st.columns(3)
        for col, label, rating in zip(cols, ["못 떠올림", "조금 고민", "바로 나옴"], [0,1,2]):
            if col.button(label, use_container_width=True, type="primary" if rating==2 else "secondary"):
                db.record_review(card["id"], rating); st.session_state.review_pos += 1; st.session_state.revealed=False; st.rerun()


def study_notes():
    hero("공부 메모", "수업, 연습, 피드백에서 얻은 공부 메모를 모아보세요.")
    with st.form("study_note", clear_on_submit=True):
        a, b = st.columns([1, 2])
        note_date = a.date_input("날짜", date.today())
        title = b.text_input("제목 *", placeholder="예: 숫자 통역 시 주의점")
        content = st.text_area("메모 내용 *", height=180, placeholder="배운 점, 개선할 점, 다음 연습에서 적용할 내용을 기록하세요.")
        tags = st.text_input("태그", placeholder="숫자, 피드백, 시험전략 (쉼표로 구분)")
        if st.form_submit_button("메모 저장", type="primary"):
            if not title.strip() or not content.strip():
                st.error("제목과 메모 내용을 모두 입력해주세요.")
            else:
                db.add_note({"note_date": note_date.isoformat(), "title": title.strip(), "content": content.strip(), "tags": tags.strip()})
                st.success("공부 메모를 저장했습니다.")
    st.subheader("메모 모아보기")
    keyword = st.text_input("메모 검색", placeholder="제목·내용·태그 검색")
    notes = db.find_notes(keyword)
    if notes:
        for note in notes:
            with st.expander(f"{note['note_date']} · {note['title']}"):
                st.write(note["content"])
                if note["tags"]: st.caption(f"태그: {note['tags']}")
        st.markdown("#### 기록 수정")
        selected_record_editor("study_notes", notes, [("note_date","날짜"),("title","제목"),("content","내용"),("tags","태그")], lambda r: f"{r['note_date']} · {r['title']}", "note")
    else:
        st.info("조건에 맞는 메모가 없습니다.")


def analyze_scripts(source: str, interpreted: str) -> str:
    source_numbers = re.findall(r"\d+(?:[.,]\d+)*%?", source)
    interpreted_numbers = re.findall(r"\d+(?:[.,]\d+)*%?", interpreted)
    missing = [n for n in source_numbers if n not in interpreted_numbers]
    source_len = len(re.sub(r"\s", "", source)); interpreted_len = len(re.sub(r"\s", "", interpreted))
    ratio = interpreted_len / source_len if source_len else 0
    source_sentences = len([x for x in re.split(r"[.!?。！？]+", source) if x.strip()])
    output_sentences = len([x for x in re.split(r"[.!?。！？]+", interpreted) if x.strip()])
    hesitations = len(re.findall(r"(?:^|\s)(음+|어+|えー+|あの)(?:\s|$)", interpreted))
    notes = []
    notes.append(f"숫자 보존: {len(source_numbers)-len(missing)}/{len(source_numbers)}개" if source_numbers else "숫자 보존: 원문에 숫자가 없습니다.")
    if missing: notes.append("확인이 필요한 숫자: " + ", ".join(missing))
    notes.append(f"통역문 분량: 원문의 약 {ratio*100:.0f}% (문자 수 기준)")
    if ratio < .45: notes.append("분량이 짧아 핵심 내용 누락 여부를 문장별로 확인해보세요.")
    elif ratio > 1.6: notes.append("통역문이 길어졌습니다. 반복 표현과 불필요한 설명을 줄일 수 있는지 확인해보세요.")
    else: notes.append("전체 분량은 원문과 비교해 무리가 없는 범위입니다.")
    notes.append(f"문장 단위: 원문 {source_sentences}개 / 통역문 {output_sentences}개")
    notes.append(f"머뭇거림 표현 감지: {hesitations}회")
    notes.append("※ 자동 평가는 숫자·분량·문장 구조 중심의 보조 분석입니다. 의미 정확성과 표현 자연스러움은 두 스크립트를 직접 대조해 최종 판단하세요.")
    return "\n".join(f"• {x}" for x in notes)


def openai_api_key():
    try:
        return str(st.secrets.get("OPENAI_API_KEY", "")).strip()
    except Exception:
        return ""


def call_openai_structured(instructions, user_text, schema, name, effort="low"):
    api_key = openai_api_key()
    if not api_key: raise ValueError("Streamlit Secrets에 OPENAI_API_KEY가 없습니다.")
    payload = {"model":"gpt-5.4-mini","input":[{"role":"system","content":[{"type":"input_text","text":instructions}]},{"role":"user","content":[{"type":"input_text","text":user_text}]}],"reasoning":{"effort":effort},"text":{"format":{"type":"json_schema","name":name,"strict":True,"schema":schema}}}
    request = Request("https://api.openai.com/v1/responses", data=json.dumps(payload).encode("utf-8"), headers={"Authorization":f"Bearer {api_key}","Content-Type":"application/json"}, method="POST")
    try:
        with urlopen(request, timeout=180, context=ssl.create_default_context(cafile=certifi.where())) as response: data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace"); raise RuntimeError(f"OpenAI API 오류({exc.code}): {detail[:400]}") from exc
    except URLError as exc: raise RuntimeError(f"OpenAI API 연결 실패: {exc.reason}") from exc
    output_text = "".join(content.get("text", "") for item in data.get("output", []) if item.get("type") == "message" for content in item.get("content", []) if content.get("type") == "output_text")
    if not output_text: raise RuntimeError("AI 분석 결과가 비어 있습니다.")
    return json.loads(output_text)


def analyze_scripts_ai(source, interpreted, direction, interpretation_type):
    schema = {
        "type":"object", "additionalProperties":False,
        "properties":{
            "overall_score":{"type":"integer","minimum":0,"maximum":100},
            "summary":{"type":"string"},
            "strengths":{"type":"array","items":{"type":"string"}},
            "priorities":{"type":"array","items":{"type":"string"}},
            "sentences":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{
                "number":{"type":"integer"}, "source":{"type":"string"}, "interpreted":{"type":"string"},
                "status":{"type":"string","enum":["정확","부분 누락","중요 누락","오역","추가/왜곡","대응 없음"]},
                "accuracy_score":{"type":"integer","minimum":0,"maximum":100},
                "omissions":{"type":"array","items":{"type":"string"}},
                "meaning_errors":{"type":"array","items":{"type":"string"}},
                "expression_feedback":{"type":"array","items":{"type":"string"}},
                "fluency_feedback":{"type":"array","items":{"type":"string"}},
                "better_interpretation":{"type":"string"}
            },"required":["number","source","interpreted","status","accuracy_score","omissions","meaning_errors","expression_feedback","fluency_feedback","better_interpretation"]}}
        }, "required":["overall_score","summary","strengths","priorities","sentences"]
    }
    instructions = """당신은 한국어-일본어 통역대학원 교수다. 원문과 학습자의 실제 통역문을 의미 단위별로 정렬하여 한 문장씩 엄격하게 평가한다. 문장 수가 다르면 1:N 또는 N:1 대응도 허용하되 같은 내용을 중복 평가하지 않는다. 핵심 주장, 주체, 대상, 부정, 시제, 인과·대조·조건, 수치, 고유명사의 누락·추가·왜곡을 구체적으로 적는다. 단순 직역 차이는 오역으로 보지 않는다. 통역문의 음, 어, えー, あの, 반복, 자기수정, 문장 미완결, 장시간 멈춤을 암시하는 표기를 fluency_feedback에 반드시 기록한다. 표현이 어색하거나 문맥에 맞지 않으면 자연스럽고 즉시 말할 수 있는 개선안을 제시한다. 근거 없는 오류를 만들지 말고, 문제가 없으면 해당 배열을 비운다. 모든 피드백은 한국어로 쓴다."""
    user_text = f"통역 유형: {interpretation_type}\n방향: {direction}\n\n[원문]\n{source}\n\n[실제 통역문]\n{interpreted}"
    return call_openai_structured(instructions, user_text, schema, "interpretation_feedback", "medium")


def show_script_analysis(result):
    if isinstance(result, str):
        try: result = json.loads(result)
        except Exception: st.text(result); return
    st.metric("종합 정확도", f"{result.get('overall_score', 0)}점")
    st.write(result.get("summary", ""))
    a, b = st.columns(2)
    with a:
        st.markdown("**잘한 점**")
        for x in result.get("strengths", []): st.write(f"• {x}")
    with b:
        st.markdown("**우선 개선할 점**")
        for x in result.get("priorities", []): st.write(f"• {x}")
    st.markdown("#### 문장별 비교")
    for row in result.get("sentences", []):
        with st.container(border=True):
            h1, h2 = st.columns([1,4])
            h1.markdown(f"**#{row['number']} · {row['status']}**")
            h2.progress(row["accuracy_score"] / 100, text=f"정확도 {row['accuracy_score']}점")
            left, right = st.columns(2)
            left.markdown("**원문**"); left.write(row["source"] or "—")
            right.markdown("**실제 통역**"); right.write(row["interpreted"] or "—")
            details = []
            for label, field in [("누락","omissions"),("의미 오류","meaning_errors"),("표현","expression_feedback"),("유창성","fluency_feedback")]:
                if row.get(field): details.append(f"**{label}:** " + " / ".join(row[field]))
            if details: st.markdown("  \n".join(details))
            if row.get("better_interpretation"): st.success(f"개선 예시: {row['better_interpretation']}")


def is_ai_feedback(value):
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return isinstance(parsed, dict) and isinstance(parsed.get("sentences"), list)
    except Exception:
        return False


class _ArticleHTMLParser(HTMLParser):
    """Extract likely article paragraphs and JSON-LD articleBody without extra packages."""

    _SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form"}
    _ARTICLE_HINT = re.compile(r"(?:article|story|news|content|본문|article-body|article_body|post-content)", re.I)

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.paragraph = None
        self.paragraph_score = 0
        self.paragraphs = []
        self.json_ld = []
        self.json_buffer = None
        self.title_buffer = None
        self.h1_buffer = None
        self.title = ""
        self.meta_title = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs = dict(attrs)
        marker = " ".join((attrs.get("id", ""), attrs.get("class", ""), attrs.get("itemprop", "")))
        parent_skip = self.stack[-1][1] if self.stack else False
        parent_score = self.stack[-1][2] if self.stack else 0
        skip = parent_skip or tag in self._SKIP_TAGS
        score = parent_score + (2 if tag == "article" else 1 if self._ARTICLE_HINT.search(marker) else 0)
        self.stack.append((tag, skip, score))
        if tag == "meta" and (attrs.get("property") == "og:title" or attrs.get("name") in {"title", "twitter:title"}):
            self.meta_title = attrs.get("content", "").strip() or self.meta_title
        if tag == "script" and "ld+json" in attrs.get("type", "").lower():
            self.json_buffer = []
        elif tag == "p" and not skip:
            self.paragraph, self.paragraph_score = [], score
        elif tag == "title" and not skip:
            self.title_buffer = []
        elif tag == "h1" and not skip:
            self.h1_buffer = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if self.json_buffer is not None:
            self.json_buffer.append(data)
            return
        if self.stack and self.stack[-1][1]:
            return
        if self.paragraph is not None:
            self.paragraph.append(data)
        if self.title_buffer is not None:
            self.title_buffer.append(data)
        if self.h1_buffer is not None:
            self.h1_buffer.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "script" and self.json_buffer is not None:
            raw = "".join(self.json_buffer).strip()
            if raw:
                self.json_ld.append(raw)
            self.json_buffer = None
        if tag == "p" and self.paragraph is not None:
            text = re.sub(r"\s+", " ", unescape("".join(self.paragraph))).strip()
            if len(text) >= 20:
                self.paragraphs.append((self.paragraph_score, text))
            self.paragraph = None
        if tag == "title" and self.title_buffer is not None:
            self.title = re.sub(r"\s+", " ", "".join(self.title_buffer)).strip()
            self.title_buffer = None
        if tag == "h1" and self.h1_buffer is not None:
            heading = re.sub(r"\s+", " ", "".join(self.h1_buffer)).strip()
            if heading:
                self.meta_title = self.meta_title or heading
            self.h1_buffer = None
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                break

    def json_article(self):
        def walk(value):
            if isinstance(value, dict):
                body = value.get("articleBody")
                if isinstance(body, str) and len(body.strip()) >= 100:
                    return body, str(value.get("headline", "")).strip()
                for child in value.values():
                    found = walk(child)
                    if found:
                        return found
            elif isinstance(value, list):
                for child in value:
                    found = walk(child)
                    if found:
                        return found
            return None
        for raw in self.json_ld:
            try:
                found = walk(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue
            if found:
                return found
        return None


def _validate_public_article_url(value):
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("기사 URL은 http:// 또는 https://로 시작해야 합니다.")
    if parsed.username or parsed.password:
        raise ValueError("로그인 정보가 포함된 URL은 사용할 수 없습니다.")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".local"):
        raise ValueError("공개된 신문기사 URL만 사용할 수 있습니다.")
    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("기사 사이트의 주소를 확인할 수 없습니다.") from exc
    for address in {item[4][0].split("%", 1)[0] for item in addresses}:
        try:
            if not ipaddress.ip_address(address).is_global:
                raise ValueError("공개된 신문기사 URL만 사용할 수 있습니다.")
        except ValueError as exc:
            if "공개된" in str(exc):
                raise
            raise ValueError("기사 사이트의 주소를 확인할 수 없습니다.") from exc
    return url


class _SafeArticleRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_public_article_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_article_text(article_url):
    url = _validate_public_article_url(article_url)
    request = Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "ko,en-US;q=0.8,ja;q=0.7",
        "Accept-Encoding": "identity",
    })
    try:
        with build_opener(_SafeArticleRedirectHandler()).open(request, timeout=25) as response:
            _validate_public_article_url(response.geturl())
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise ValueError("HTML 형식의 신문기사만 불러올 수 있습니다.")
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("기사 페이지가 너무 커서 불러올 수 없습니다.")
            declared = response.headers.get_content_charset()
    except HTTPError as exc:
        if exc.code in {401, 403, 451}:
            raise RuntimeError("기사 사이트가 자동 본문 수집을 허용하지 않습니다. 기사 본문을 직접 붙여넣어 주세요.") from exc
        raise RuntimeError(f"기사 페이지를 불러오지 못했습니다. (HTTP {exc.code})") from exc
    except URLError as exc:
        raise RuntimeError(f"기사 페이지 연결에 실패했습니다: {exc.reason}") from exc
    candidates = [declared, "utf-8", "cp949", "euc-kr", "shift_jis"]
    decoded = []
    for encoding in dict.fromkeys(x for x in candidates if x):
        try:
            text = raw.decode(encoding, errors="replace")
            decoded.append((text.count("\ufffd"), text))
        except (LookupError, UnicodeError):
            continue
    html_text = min(decoded, key=lambda item: item[0])[1] if decoded else raw.decode("utf-8", "replace")
    parser = _ArticleHTMLParser()
    parser.feed(html_text)
    json_article = parser.json_article()
    if json_article:
        body, json_title = json_article
        article_text = re.sub(r"[ \t]+", " ", unescape(body)).strip()
        title = json_title or parser.meta_title or parser.title
    else:
        preferred = [text for score, text in parser.paragraphs if score > 0]
        paragraphs = preferred if len("\n".join(preferred)) >= 300 else [text for _, text in parser.paragraphs]
        article_text = "\n\n".join(dict.fromkeys(paragraphs)).strip()
        title = parser.meta_title or parser.title
    if len(article_text) < 200:
        raise RuntimeError("기사 본문을 충분히 찾지 못했습니다. 로그인·유료벽·자바스크립트 전용 기사라면 본문을 직접 붙여넣어 주세요.")
    if len(article_text) > 60_000:
        article_text = article_text[:60_000]
    return {"title": title.strip(), "text": article_text, "url": url}


def _normalize_extracted_term(value):
    return re.sub(r"[\s·・.ㆍ\-_/（）()「」『』\[\]]+", "", str(value or "")).casefold()


def refine_extracted_terms(terms):
    """Remove deterministic exclusions, generic words, and duplicated person components."""
    excluded = {
        "청와대", "青瓦台", "행정안전부", "행안부", "行政安全部", "기획재정부", "기재부", "企画財政部",
        "산업통상부", "산업통상자원부", "산자부", "産業通商資源部", "후생성", "厚生省",
        "518민주화운동", "518民主化運動", "국가폭력피해자", "国家暴力被害者",
        "gdp", "gnp", "닛케이지수", "日経指数", "日経平均", "日経平均株価",
        "행정안전부장관", "행안부장관", "行政安全部長官", "기획재정부장관", "기재부장관", "企画財政部長官",
        "산업통상부장관", "산업통상자원부장관", "산자부장관", "産業通商資源部長官", "후생성장관", "厚生大臣",
    }
    generic_terms = {
        "정부", "국가", "사회", "국민", "시민", "피해자", "유가족", "관계자", "당국", "부처", "기업", "조직", "위원회",
        "명예회복", "진상규명", "특별법", "관련법", "법률", "법안", "제도", "정책", "사업", "대책", "계획",
        "경제", "문제", "사건", "피해", "지원", "보상", "배상", "조사", "발표", "회의", "협의", "개정", "시행", "추진",
        "政府", "国家", "社会", "国民", "市民", "被害者", "遺族", "関係者", "当局", "省庁", "企業", "組織", "委員会",
        "名誉回復", "真相究明", "特別法", "関連法", "法律", "法案", "制度", "政策", "事業", "対策", "計画",
        "経済", "問題", "事件", "被害", "支援", "補償", "賠償", "調査", "発表", "会議", "協議", "改正", "施行", "推進",
    }
    excluded.update(generic_terms)
    excluded = {_normalize_extracted_term(value) for value in excluded}
    explicit_leader_exclusions = (
        ("이재명", ("대통령", "大統領")), ("李在明", ("대통령", "大統領")),
        ("다카이치사나에", ("총리", "수상", "首相", "内閣総理大臣")),
        ("高市早苗", ("총리", "수상", "首相", "内閣総理大臣")),
    )
    kept = []
    for item in terms or []:
        normalized = _normalize_extracted_term(item.get("term", ""))
        if not normalized or normalized in excluded:
            continue
        if any(_normalize_extracted_term(name) in normalized and any(_normalize_extracted_term(title) in normalized for title in titles) for name, titles in explicit_leader_exclusions):
            continue
        kept.append(item)
    combined = [
        (_normalize_extracted_term(item.get("term", "")), item)
        for item in kept if item.get("subtype") == "인명·소속·직책"
    ]
    refined = []
    for item in kept:
        normalized = _normalize_extracted_term(item.get("term", ""))
        if item.get("subtype") != "인명·소속·직책" and any(normalized != whole and normalized in whole for whole, _ in combined):
            continue
        refined.append(item)
    return refined


def extract_terms_ai(text):
    subtypes = ["인명·소속·직책","인명","직책","부서명","팀명","위원회·조직명","기관·기업명","법률·협정명","정책·사업명","기술·전문개념","기타 고유명사"]
    schema = {"type":"object","additionalProperties":False,"properties":{"source_language":{"type":"string","enum":["한국어","일본어","혼합"]},"terms":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"term":{"type":"string"},"translation":{"type":"string"},"translation_language":{"type":"string","enum":["한국어","일본어"]},"category":{"type":"string","enum":["고유명사","전문용어"]},"subtype":{"type":"string","enum":subtypes},"context":{"type":"string"},"position":{"type":"integer"}},"required":["term","translation","translation_language","category","subtype","context","position"]}}},"required":["source_language","terms"]}
    instructions = """입력 텍스트에서 한일·일한 통역 준비에 실제로 필요한 항목만 추출한다. 아래 판단 순서를 반드시 따른다.

1. 우선 제외:
- 청와대, 행정안전부, 기획재정부, 산업통상자원부, 후생성 등 한국·일본 및 기타 국가의 정부부처·대통령실과 그 약칭은 추출하지 않는다.
- 정부부처명에 '장관' 또는 '대신'이라는 직책만 붙고 사람 이름이 없으면 추출하지 않는다.
- 한국과 일본의 대통령·총리는 사람 이름이 함께 있어도 추출하지 않는다. 현직·전직을 모두 포함한다. 예: '이재명 대통령', '다카이치 사나에 총리'는 제외한다.
- '5·18 민주화운동', '국가폭력 피해자' 같은 기초 역사 용어·일반명사와 국가명, 수도명, GDP, GNP, 닛케이 지수, 기초 시사용어는 제외한다.
- 기사에서 중요하게 다뤄지거나 반복되더라도 일반명사·보통명사·일반적인 표현은 추출하지 않는다. 예: '정부', '명예회복', '특별법', '피해자', '유가족', '진상규명', '지원', '보상', '법률', '정책', '사업'은 단독으로 추출하지 않는다.
- 법률·정책·위원회 등의 전체 정식 명칭은 추출할 수 있지만, 그 명칭에서 '특별법', '위원회', '정책' 같은 일반 부분만 떼어 별도 용어로 만들지 않는다.

2. 이름 결합:
- 위 제외 대상이 아닌 인명에 소속이나 직책이 함께 나오면 반드시 하나의 term으로 합친다. 인명, 소속, 직책을 별도 항목으로 중복 출력하지 않는다.
- 원문에 나온 정보만 합치며 원문에 없는 소속이나 직책을 추정하지 않는다.
- 예: '삼성전자 홍길동 팀장'은 그 전체를 하나의 '인명·소속·직책'으로 출력한다.
- 예: '야마다 케이스케 한일협회 회장'은 그 전체를 하나의 '인명·소속·직책'으로 출력한다.
- 정부부처 장관도 사람 이름이 나오면 부처명과 직책을 포함한 전체 표현을 하나로 추출한다. 예: '김민수 행정안전부 장관'은 포함한다. 단, 한국·일본 대통령·총리 제외 규칙이 항상 우선한다.
- 이름만 나오면 '인명', 직책만 준비 가치가 있을 때는 '직책'으로 출력한다.

3. 반드시 포함:
- 정부부처가 아닌 위원회, 기업, 노동조합, 협회, 단체와 기타 조직의 고유명은 반드시 추출한다. 예: '전교조'는 '위원회·조직명'으로 포함한다.
- 회사·기관의 부서명과 팀명, 법률명, 협정명, 정책명, 사업명, 기술명, 그리고 '생산가능인구'처럼 정확한 개념 준비가 필요한 전문용어를 추출한다.
- 각 후보는 다음 중 하나를 만족해야 한다: (a) 그 표현 전체가 특정 사람·조직·법률·정책·사업을 고유하게 식별한다. (b) 일반어의 조합만으로 뜻을 바로 알기 어렵고 별도의 전문 정의나 정형 번역을 준비해야 한다.
- 위 조건을 만족하지 않으면 중요한 문맥에 등장해도 제외한다. 추출할 항목이 없으면 terms를 빈 배열로 반환한다.

4. 출력:
- term에는 원문 표기를 유지하고 같은 대상을 중복 출력하지 않는다.
- 한국어 원문 용어에는 자연스럽고 표준적인 일본어 번역을, 일본어 원문 용어에는 자연스러운 한국어 번역을 병기한다. 혼합 텍스트는 각 용어의 원문 언어와 반대 언어로 번역한다.
- 영문 표기의 용어는 그 용어가 들어 있는 문장이 한국어이면 일본어로, 일본어이면 한국어로 번역한다.
- 인명·기관명 등 정식 번역을 확정할 수 없으면 널리 쓰이는 표기 또는 음역을 쓰며, 번역을 임의로 만들어내지 않는다.
- context에는 그 기사에서의 짧은 의미나 역할을 한국어로 적는다.
- position에는 원문에서 처음 등장한 문자 위치에 가까운 정수를 넣는다.
- 근거가 없는 용어는 추가하지 않는다."""
    result = call_openai_structured(instructions, text, schema, "terminology_extraction", "low")
    result["terms"] = refine_extracted_terms(result.get("terms", []))
    return result


def terminology_extraction():
    hero("고유명사·전문용어 추출", "신문기사 URL이나 직접 입력한 텍스트에서 용어를 추출하고 한일 번역을 병기합니다.")
    if not openai_api_key(): st.warning("Streamlit Secrets에 OPENAI_API_KEY를 등록해야 합니다.")
    mode = st.segmented_control("통역 방식", ["동시통역", "순차통역"], default="동시통역")
    st.caption("동시통역은 원문 등장 순서, 순차통역은 순서를 섞어 표시합니다.")
    article_url = st.text_input("신문기사 URL", placeholder="https://…", help="URL이 입력되어 있으면 해당 기사 본문을 먼저 불러옵니다. 일부 로그인·유료 기사는 직접 붙여넣기가 필요할 수 있습니다.")
    text = st.text_area("직접 입력할 텍스트", height=280, placeholder="URL을 사용하지 않는 경우 기사, 연설문 또는 수업 자료를 붙여넣으세요.")
    if st.button("용어 추출", type="primary", use_container_width=True):
        st.session_state["extracted_terms_ready"] = False
        st.session_state["extracted_terms"] = []
        st.session_state["extracted_article"] = None
        if not article_url.strip() and not text.strip(): st.error("신문기사 URL 또는 분석할 텍스트를 입력해주세요.")
        else:
            try:
                with st.spinner("고유명사와 전문용어를 추출하고 있습니다…"):
                    article = fetch_article_text(article_url.strip()) if article_url.strip() else None
                    analysis_text = article["text"] if article else text.strip()
                    result = extract_terms_ai(analysis_text)
                    terms = result.get("terms", [])
                terms.sort(key=lambda x: x.get("position", 0))
                if mode == "순차통역": random.SystemRandom().shuffle(terms)
                st.session_state["extracted_terms"] = terms
                st.session_state["extracted_terms_mode"] = mode
                st.session_state["extracted_terms_source_language"] = result.get("source_language", "혼합")
                st.session_state["extracted_article"] = article
                st.session_state["extracted_terms_ready"] = True
            except Exception as exc: st.error(str(exc))
    terms = st.session_state.get("extracted_terms", [])
    if terms:
        article = st.session_state.get("extracted_article")
        st.subheader(f"추출 결과 · {len(terms)}개")
        st.caption(f"원문 언어 · {st.session_state.get('extracted_terms_source_language', '혼합')}")
        if article:
            st.caption(f"기사: {article.get('title') or '제목을 찾지 못함'} · 본문 {len(article.get('text','')):,}자")
            with st.expander("수집한 기사 본문 확인"):
                st.text(article.get("text", ""))
        shown = [{"번호":i, "원문 용어":item["term"], "번역":item["translation"], "번역 언어":item["translation_language"], "구분":item["category"], "세부 분류":item["subtype"], "문맥·의미":item["context"]} for i,item in enumerate(terms, 1)]
        st.dataframe(shown, use_container_width=True, hide_index=True)
    elif st.session_state.get("extracted_terms_ready"):
        st.info("설정한 기준에 해당하는 고유명사나 전문용어를 찾지 못했습니다.")


def tts_target_duration(text, language):
    character_count = len(re.sub(r"\s+", "", str(text or "")))
    characters_per_minute = 200 if language == "한국어" else 1000 / 6
    return character_count, character_count / characters_per_minute * 60 if character_count else 0


def generate_tts_audio(text):
    api_key = openai_api_key()
    if not api_key:
        raise ValueError("Streamlit Secrets에 OPENAI_API_KEY가 없습니다.")
    payload = {
        "model": "tts-1",
        "input": text,
        "voice": "alloy",
        "response_format": "mp3",
        "speed": 0.75,
    }
    request = Request(
        "https://api.openai.com/v1/audio/speech",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=180, context=ssl.create_default_context(cafile=certifi.where())) as response:
            audio = response.read(25_000_001)
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"OpenAI 음성 API 오류({exc.code}): {detail[:400]}") from exc
    except URLError as exc:
        raise RuntimeError(f"OpenAI 음성 API 연결 실패: {exc.reason}") from exc
    if not audio:
        raise RuntimeError("생성된 음성이 비어 있습니다.")
    if len(audio) > 25_000_000:
        raise RuntimeError("생성된 음성 파일이 너무 큽니다. 텍스트를 나누어 다시 시도해주세요.")
    return audio


def _format_duration(seconds):
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60}분 {seconds % 60:02d}초"


def render_paced_tts_player(audio_bytes, target_seconds, language, character_count):
    encoded = base64.b64encode(audio_bytes).decode("ascii")
    components.html(f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><style>
    *{{box-sizing:border-box}}body{{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2937}}
    .player{{border:1px solid #e1e6ef;border-radius:14px;padding:18px;background:#fff}}
    .meta{{color:#667085;font-size:13px;margin-bottom:12px}}.controls{{display:flex;align-items:center;gap:10px}}
    button{{border:0;border-radius:9px;padding:9px 15px;background:#315a9c;color:white;font-weight:700;cursor:pointer}}
    button.secondary{{background:#eef2f8;color:#315a9c}}input[type=range]{{flex:1;accent-color:#315a9c}}
    .time{{font-variant-numeric:tabular-nums;font-size:13px;min-width:92px;text-align:right}}.status{{margin-top:11px;font-size:13px;color:#475467}}
    </style></head><body><div class="player">
    <div class="meta">{language} · 공백 제외 {character_count:,}자 · 목표 {_format_duration(target_seconds)}</div>
    <audio id="audio" preload="metadata" src="data:audio/mpeg;base64,{encoded}"></audio>
    <div class="controls"><button id="toggle">▶ 재생</button><button id="reset" class="secondary">처음으로</button><input id="seek" type="range" min="0" max="1000" value="0"><span id="time" class="time">0:00 / --:--</span></div>
    <div id="status" class="status">음성 길이를 확인하고 목표 속도로 맞추는 중입니다…</div>
    </div><script>
    const audio=document.getElementById('audio'), toggle=document.getElementById('toggle'), reset=document.getElementById('reset');
    const seek=document.getElementById('seek'), time=document.getElementById('time'), status=document.getElementById('status');
    const target={float(target_seconds):.4f}; let rate=1;
    const clock=(s)=>{{s=Math.max(0,Math.round(s||0));return `${{Math.floor(s/60)}}:${{String(s%60).padStart(2,'0')}}`;}};
    const update=()=>{{const total=audio.duration&&isFinite(audio.duration)?audio.duration/rate:target;const current=(audio.currentTime||0)/rate;time.textContent=`${{clock(current)}} / ${{clock(total)}}`;seek.value=audio.duration?Math.round(audio.currentTime/audio.duration*1000):0;}};
    audio.addEventListener('loadedmetadata',()=>{{const proposed=audio.duration/target;rate=Math.min(4,Math.max(.25,proposed));audio.defaultPlaybackRate=rate;audio.playbackRate=rate;audio.preservesPitch=true;audio.webkitPreservesPitch=true;const exact=Math.abs(rate-proposed)<.001;status.textContent=`목표 재생시간 ${{clock(target)}} · 자동 보정 ${{rate.toFixed(2)}}배속${{exact?'':' · 브라우저 지원 범위 내에서 조정'}}`;update();}});
    audio.addEventListener('timeupdate',update);audio.addEventListener('play',()=>toggle.textContent='❚❚ 일시정지');
    audio.addEventListener('pause',()=>toggle.textContent='▶ 재생');audio.addEventListener('ended',()=>{{toggle.textContent='▶ 다시 재생';update();}});
    toggle.addEventListener('click',()=>{{audio.playbackRate=rate;if(audio.ended)audio.currentTime=0;audio.paused?audio.play():audio.pause();}});
    reset.addEventListener('click',()=>{{audio.pause();audio.currentTime=0;update();}});
    seek.addEventListener('input',()=>{{if(audio.duration)audio.currentTime=Number(seek.value)/1000*audio.duration;update();}});
    </script></body></html>""", height=180)


def tts_page():
    hero("TTS", "한국어와 일본어 스크립트를 통역 연습용 목표 속도로 들어보세요.")
    if not openai_api_key():
        st.warning("음성을 생성하려면 Streamlit Secrets에 OPENAI_API_KEY를 등록해야 합니다.")
    language = st.segmented_control("언어", ["한국어", "일본어"], default="한국어", key="tts_language")
    target_label = "1,200자당 6분 · 분당 200자" if language == "한국어" else "1,000자당 6분 · 분당 약 167자"
    st.caption(f"목표 속도 · {target_label} · 글자 수는 공백을 제외하고 계산합니다.")
    text = st.text_area("읽을 텍스트", height=320, placeholder="한국어 또는 일본어 스크립트를 입력하세요.", key="tts_text")
    character_count, target_seconds = tts_target_duration(text, language)
    a, b = st.columns(2)
    a.metric("공백 제외 글자 수", f"{character_count:,}자")
    b.metric("목표 재생시간", _format_duration(target_seconds))
    st.caption("한 번에 최대 4,000자까지 생성할 수 있습니다. 이 음성은 AI가 생성합니다.")
    if st.button("음성 생성", type="primary", use_container_width=True, key="tts_generate"):
        clean_text = text.strip()
        if not clean_text or character_count == 0:
            st.error("읽을 텍스트를 입력해주세요.")
        elif len(clean_text) > 4_000:
            st.error("텍스트가 4,000자를 초과합니다. 여러 부분으로 나누어 생성해주세요.")
        else:
            try:
                with st.spinner("음성을 생성하고 목표 속도를 계산하고 있습니다…"):
                    audio = generate_tts_audio(clean_text)
                st.session_state["tts_audio"] = audio
                st.session_state["tts_signature"] = (language, clean_text)
                st.session_state["tts_target_seconds"] = target_seconds
                st.session_state["tts_character_count"] = character_count
                st.success("음성을 생성했습니다.")
            except Exception as exc:
                st.error(str(exc))
    audio = st.session_state.get("tts_audio")
    if audio and st.session_state.get("tts_signature") == (language, text.strip()):
        st.subheader("재생")
        render_paced_tts_player(audio, st.session_state["tts_target_seconds"], language, st.session_state["tts_character_count"])
    elif audio:
        st.info("언어나 텍스트가 변경되었습니다. 새 내용으로 음성을 다시 생성해주세요.")


def script_feedback():
    hero("스크립트 피드백", "AI가 원문과 실제 통역문을 문장별로 정렬해 누락·오역·표현·유창성을 분석합니다.")
    if not openai_api_key():
        st.warning("AI 분석을 사용하려면 Streamlit Secrets에 OPENAI_API_KEY를 등록해야 합니다.")
    with st.form("script_feedback"):
        a,b,c = st.columns(3)
        feedback_date = a.date_input("날짜", date.today())
        interpretation_type = b.selectbox("통역 유형", ["동시통역", "순차통역"])
        direction = c.segmented_control("방향", ["KO→JA", "JA→KO"], default="KO→JA")
        title = st.text_input("자료 제목 *")
        left,right = st.columns(2)
        source_script = left.text_area("통역 대상 스크립트 *", height=320)
        interpreted_script = right.text_area("실제 통역 스크립트 *", height=320)
        if st.form_submit_button("분석하고 저장", type="primary", use_container_width=True):
            if not title.strip() or not source_script.strip() or not interpreted_script.strip():
                st.error("제목과 두 스크립트를 모두 입력해주세요.")
            else:
                try:
                    with st.spinner("문장별 의미와 표현을 분석하고 있습니다…"):
                        result = analyze_scripts_ai(source_script.strip(), interpreted_script.strip(), direction, interpretation_type)
                    saved = json.dumps(result, ensure_ascii=False)
                    db.add_script_feedback({"feedback_date":feedback_date.isoformat(), "interpretation_type":interpretation_type, "direction":direction, "title":title.strip(), "source_script":source_script.strip(), "interpreted_script":interpreted_script.strip(), "feedback":saved})
                    st.session_state["latest_script_feedback"] = result
                    st.success("문장별 AI 분석 결과를 저장했습니다.")
                except Exception as exc:
                    st.error(str(exc))
    if st.session_state.get("latest_script_feedback"):
        st.subheader("이번 분석 결과"); show_script_analysis(st.session_state["latest_script_feedback"])
    st.subheader("저장된 피드백")
    feedback_items = sorted(db.all_script_feedbacks(), key=lambda item: int(item.get("id", 0)), reverse=True)[:20]
    for item in feedback_items:
        kind = "AI 상세 분석" if is_ai_feedback(item.get("feedback", "")) else "기존 기본 분석"
        with st.expander(f"{item['feedback_date']} · {item['interpretation_type']} {item['direction']} · {item['title']} · {kind}"):
            show_script_analysis(item["feedback"])
    if feedback_items:
        st.markdown("#### 기록 수정")
        selected_record_editor("script_feedbacks", feedback_items, [("feedback_date","날짜"),("interpretation_type","통역 유형"),("direction","방향"),("title","제목"),("source_script","대상 스크립트"),("interpreted_script","실제 통역 스크립트"),("feedback","피드백")], lambda r: f"{r['feedback_date']} · {r['interpretation_type']} {r['direction']} · {r['title']}", "feedback")


def script_review():
    hero("스크립트 복습", "본문을 드래그해 하이라이트하고 선택한 부분 아래에 메모를 남기세요.")
    if script_highlighter_component is None:
        st.error("하이라이터 파일이 없습니다. GitHub에서 app.py와 같은 위치에 script_highlighter_v11/index.html을 업로드해주세요.")
        return
    with st.expander("새 복습 스크립트 추가", expanded=not bool(db.all_script_reviews())):
        with st.form("new_review_script", clear_on_submit=True):
            title = st.text_input("스크립트 제목 *")
            text = st.text_area("스크립트 *", height=260)
            if st.form_submit_button("스크립트 저장", type="primary"):
                if not title.strip() or not text.strip(): st.error("제목과 스크립트를 입력해주세요.")
                else: db.add_script_review(title.strip(), text.strip()); st.success("저장했습니다."); st.rerun()
    scripts = db.all_script_reviews()
    if not scripts: st.info("복습할 스크립트를 먼저 추가해주세요."); return
    selected_id = st.selectbox("복습할 스크립트", [r["id"] for r in scripts], format_func=lambda i: next(r["title"] for r in scripts if r["id"]==i))
    item = next(r for r in scripts if r["id"] == selected_id)
    highlights = script_highlighter_component(text=item["script_text"], highlights=item.get("highlights") or "[]", key=f"highlighter_{selected_id}", default=item.get("highlights") or "[]")
    if st.button("하이라이트와 메모 저장", type="primary", use_container_width=True):
        db.update_record("script_reviews", selected_id, {"highlights": highlights or "[]"})
        st.success("복습 내용을 저장했습니다."); st.rerun()
    edit_button("script_reviews", item, [("title","제목"),("script_text","스크립트")], "스크립트 원문을 수정합니다. 원문 위치가 바뀌면 기존 하이라이트 위치도 달라질 수 있습니다.", f"script_{selected_id}")


def render_study_material(content_html):
    components.html(f"""<!doctype html><html lang='ko'><head><meta charset='utf-8'><style>
    body{{margin:0;padding:22px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#1f2937;font-size:16px;line-height:1.75;overflow-wrap:anywhere}}
    iframe{{display:block;width:min(100%,760px);aspect-ratio:16/9;height:auto;border:0;border-radius:12px;margin:16px 0;background:#111}} img{{max-width:100%}} a{{color:#315a9c}} h1,h2,h3{{line-height:1.35}}
    </style></head><body>{content_html}</body></html>""", height=720, scrolling=True)


def study_materials():
    hero("공부 자료", "YouTube 영상과 텍스트 자료를 게시판처럼 작성하고 모아보세요.")
    if study_material_editor_component is None:
        st.error("공부 자료 편집기 파일이 없습니다. study_material_editor/index.html을 함께 업로드해주세요.")
        return
    materials = db.all_study_materials()
    page = st.session_state.get("material_page", "list")
    selected_id = st.session_state.get("material_selected_id")

    if page == "list":
        st.subheader("자료 게시판")
        st.session_state.setdefault("material_search", "")
        st.session_state.setdefault("material_direction_filter", "전체")
        st.session_state.setdefault("material_mode_filter", "전체")
        keyword = st.session_state.get("material_search", "")
        direction_filter = st.session_state.get("material_direction_filter", "전체")
        mode_filter = st.session_state.get("material_mode_filter", "전체")
        filtered = [m for m in materials if (not keyword or keyword.lower() in m["title"].lower() or keyword.lower() in str(m.get("content_html", "")).lower()) and (direction_filter == "전체" or m.get("language_direction", "한일") == direction_filter) and (mode_filter == "전체" or m.get("interpretation_mode", "동시") == mode_filter)]
        if filtered:
            header = st.columns([1,6,2,2,2])
            for col, label in zip(header, ["번호","제목","언어 방향","통역 방식","작성일"]): col.caption(label)
            for material in filtered:
                cols = st.columns([1,6,2,2,2])
                cols[0].write(material["id"])
                if cols[1].button(material["title"], key=f"material_open_{material['id']}", type="tertiary"):
                    st.session_state["material_selected_id"] = material["id"]; st.session_state["material_page"] = "view"; st.rerun()
                cols[2].write(material.get("language_direction", "한일")); cols[3].write(material.get("interpretation_mode", "동시")); cols[4].write(str(material.get("created_at", ""))[:10])
        else: st.info("조건에 맞는 게시글이 없습니다.")
        st.divider()
        bottom = st.columns([3,1.2,1.2,2,1])
        bottom[0].text_input("검색", placeholder="제목·본문 검색", key="material_search", label_visibility="collapsed")
        bottom[1].selectbox("언어 방향", ["전체","한일","일한"], key="material_direction_filter", label_visibility="collapsed")
        bottom[2].selectbox("통역 방식", ["전체","순차","동시"], key="material_mode_filter", label_visibility="collapsed")
        bottom[3].empty()
        if bottom[4].button("게시글 작성", type="primary", key="material_write", use_container_width=True): st.session_state["material_page"] = "new"; st.rerun()
        return

    if page == "new":
        if st.button("← 목록으로", key="material_new_back"): st.session_state["material_page"] = "list"; st.rerun()
        st.subheader("게시글 작성")
        title = st.text_input("제목 *", key="material_new_title")
        c1, c2 = st.columns(2)
        language_direction = c1.segmented_control("언어 방향", ["한일","일한"], default="한일")
        interpretation_mode = c2.segmented_control("통역 방식", ["순차","동시"], default="동시")
        revision = st.session_state.get("material_editor_revision", 0)
        content = study_material_editor_component(value="", key=f"material_new_editor_{revision}", default="")
        if st.button("게시글 저장", type="primary", use_container_width=True, key="material_create"):
            if not title.strip() or not str(content or "").strip(): st.error("제목과 내용을 입력해주세요.")
            else:
                new_id = db.add_study_material(title.strip(), str(content), language_direction, interpretation_mode)
                st.session_state["material_editor_revision"] = revision + 1; st.session_state["material_selected_id"] = new_id; st.session_state["material_page"] = "view"; st.rerun()
        return

    item = next((m for m in materials if m["id"] == selected_id), None)
    if not item: st.session_state["material_page"] = "list"; st.rerun()
    if st.button("← 목록으로", key="material_view_back"): st.session_state["material_page"] = "list"; st.rerun()
    if page == "view":
        st.markdown(f"### {item['title']}")
        st.caption(f"{item.get('language_direction','한일')} · {item.get('interpretation_mode','동시')} · 작성일 {str(item.get('created_at',''))[:10]}")
        render_study_material(item.get("content_html", ""))
        _, edit_col = st.columns([8,1])
        if edit_col.button("수정", key=f"material_edit_open_{selected_id}", use_container_width=True): st.session_state["material_page"] = "edit"; st.rerun()
        return
    st.subheader("게시글 수정")
    edit_title = st.text_input("제목", value=item["title"], key=f"material_title_{selected_id}")
    c1, c2 = st.columns(2)
    edit_direction = c1.segmented_control("언어 방향", ["한일","일한"], default=item.get("language_direction", "한일"), key=f"material_direction_{selected_id}")
    edit_mode = c2.segmented_control("통역 방식", ["순차","동시"], default=item.get("interpretation_mode", "동시"), key=f"material_mode_{selected_id}")
    edit_content = study_material_editor_component(value=item.get("content_html", ""), key=f"material_editor_{selected_id}", default=item.get("content_html", ""))
    save, cancel = st.columns(2)
    if save.button("수정 저장", type="primary", use_container_width=True, key=f"material_save_{selected_id}"):
        if not edit_title.strip() or not str(edit_content or "").strip(): st.error("제목과 내용을 입력해주세요.")
        else:
            db.update_record("study_materials", selected_id, {"title":edit_title.strip(), "content_html":str(edit_content), "language_direction":edit_direction, "interpretation_mode":edit_mode})
            st.session_state["material_page"] = "view"; st.rerun()
    if cancel.button("취소", use_container_width=True, key=f"material_cancel_{selected_id}"): st.session_state["material_page"] = "view"; st.rerun()


def statistics():
    hero("통계", "연습량과 반복되는 약점을 한눈에 확인하세요.")
    practices = pd.DataFrame(db.all_practices())
    pairs = pd.DataFrame(db.all_pairs())
    if practices.empty and pairs.empty: st.info("기록이 쌓이면 통계가 표시됩니다."); return
    if not practices.empty:
        directional = practices[practices["activity_type"] != "shadowing"]
        totals = directional.groupby("direction")["minutes"].sum().reindex(["KO→JA","JA→KO"], fill_value=0)
        a,b = st.columns(2); a.metric("KO→JA 누적", f"{totals['KO→JA']}분"); b.metric("JA→KO 누적", f"{totals['JA→KO']}분")
        st.subheader("방향별 누적 연습시간"); st.bar_chart(totals, horizontal=True)
        activity_totals = practices.groupby("activity_type")["minutes"].sum().rename(index=ACTIVITY_LABELS)
        st.subheader("연습 유형별 누적시간"); st.bar_chart(activity_totals, horizontal=True)
        error_totals = practices[list(ERROR_LABELS)].sum().rename(index=ERROR_LABELS)
        st.subheader("오류 유형 누적"); st.bar_chart(error_totals.sort_values(ascending=False), horizontal=True)
        practices["practice_date"] = pd.to_datetime(practices["practice_date"])
        weekly = directional.set_index("practice_date").groupby("direction")["minutes"].resample("W-MON").sum().unstack(0).fillna(0)
        st.subheader("주간 연습시간 추이"); st.line_chart(weekly)
    if not pairs.empty:
        pairs["created_at"] = pd.to_datetime(pairs["created_at"])
        daily = pairs.set_index("created_at").resample("D").size().cumsum()
        st.subheader("신규 언어쌍 누적"); st.line_chart(daily)


def records_manager():
    hero("기록 수정", "저장한 데이터를 표에서 고친 뒤 변경사항을 저장하세요.")
    specs = [
        ("연습", "practices", "id", {"practice_date":"날짜","activity_type":"유형","direction":"방향","title":"자료 제목","topic":"주제","source_url":"URL","video_speed":"속도","minutes":"분","difficulty":"난이도","omission":"내용 누락","number_omission":"숫자 누락","logic_error":"논리 오류","expression_block":"표현 막힘","unnatural_expression":"부자연스러운 표현","other_notes":"메모"}),
        ("언어쌍", "language_pairs", "id", {"korean":"한국어","japanese":"일본어","pair_type":"유형","source":"출처","notes":"메모","mastery":"숙지도"}),
        ("공부 메모", "study_notes", "id", {"note_date":"날짜","title":"제목","content":"내용","tags":"태그"}),
        ("스크립트 피드백", "script_feedbacks", "id", {"feedback_date":"날짜","interpretation_type":"통역 유형","direction":"방향","title":"제목","source_script":"대상 스크립트","interpreted_script":"실제 통역 스크립트","feedback":"피드백"}),
        ("목표 설정", "settings", "key", {"value":"설정값"}),
    ]
    tabs = st.tabs([x[0] for x in specs])
    for tab, (label, table, id_column, mapping) in zip(tabs, specs):
        with tab:
            rows = db.table_rows(table)
            if not rows:
                st.info("수정할 기록이 없습니다."); continue
            visible = [{id_column:r[id_column], **{kr:r.get(en, "") for en,kr in mapping.items()}} for r in rows]
            frame = pd.DataFrame(visible)
            config = {id_column: (st.column_config.TextColumn("설정", disabled=True) if table == "settings" else st.column_config.NumberColumn("ID", disabled=True))}
            if table == "practices":
                config.update({"유형":st.column_config.SelectboxColumn("유형", options=list(ACTIVITY_LABELS.values()), required=True), "방향":st.column_config.SelectboxColumn("방향", options=["KO→JA","JA→KO"], required=True), "속도":st.column_config.NumberColumn("속도", min_value=.7, max_value=1.0, step=.05)})
                frame["유형"] = frame["유형"].map(lambda x: ACTIVITY_LABELS.get(x,x))
            elif table == "language_pairs":
                config.update({"유형":st.column_config.SelectboxColumn("유형", options=list(TYPE_LABELS.values()), required=True), "숙지도":st.column_config.NumberColumn("숙지도", min_value=1, max_value=5, step=1)})
                frame["유형"] = frame["유형"].map(lambda x: TYPE_LABELS.get(x,x))
            elif table == "script_feedbacks":
                config.update({"통역 유형":st.column_config.SelectboxColumn("통역 유형", options=["동시통역","순차통역"]), "방향":st.column_config.SelectboxColumn("방향", options=["KO→JA","JA→KO"])})
            edited = st.data_editor(frame, use_container_width=True, hide_index=True, num_rows="fixed", column_config=config, key=f"editor_{table}")
            if st.button(f"{label} 변경사항 저장", type="primary", key=f"save_{table}"):
                reverse = {kr:en for en,kr in mapping.items()}
                for record in edited.to_dict("records"):
                    values = {reverse[k]: v for k,v in record.items() if k in reverse}
                    if table == "practices": values["activity_type"] = next((k for k,v in ACTIVITY_LABELS.items() if v==values["activity_type"]), values["activity_type"])
                    if table == "language_pairs": values["pair_type"] = next((k for k,v in TYPE_LABELS.items() if v==values["pair_type"]), values["pair_type"])
                    db.update_record(table, record[id_column], values)
                st.success(f"{label} 기록을 수정했습니다.")
                st.rerun()


pages = {"대시보드": dashboard, "통역 연습": practice, "언어쌍": language_pairs, "리뷰": review, "스크립트 피드백": script_feedback, "고유명사·전문용어 추출": terminology_extraction, "TTS": tts_page, "스크립트 복습": script_review, "공부 자료": study_materials, "공부 메모": study_notes, "통계": statistics}
st.sidebar.title("🎧 통역 플래너")
st.sidebar.caption(f"저장소 · {db.backend_name()}")
selection = st.sidebar.radio("메뉴", list(pages), label_visibility="collapsed")
st.sidebar.caption("기본 루틴 · 방향별 동시통역·순차통역과 방향 없는 섀도잉 각 10분")
pages[selection]()
