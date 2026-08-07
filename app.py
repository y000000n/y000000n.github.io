from __future__ import annotations

from datetime import date, datetime, timedelta
import re
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import db

st.set_page_config(page_title="통역 졸업시험 플래너", page_icon="🎧", layout="wide")
db.init_db()
_component_dir = Path(__file__).with_name("script_highlighter")
script_highlighter_component = (
    components.declare_component("script_highlighter_inline_v3", path=str(_component_dir))
    if _component_dir.is_dir() else None
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


def dashboard():
    settings = db.get_settings()
    exam = datetime.strptime(settings["exam_date"], "%Y-%m-%d").date()
    dday = (exam - date.today()).days
    hero("오늘도 한 문장씩, 더 정확하게", f"졸업시험까지 D-{dday}" if dday >= 0 else f"시험일로부터 {abs(dday)}일")
    today = date.today().isoformat()
    week = db.week_start()
    week_practices = db.practices_between(week)
    mins = {direction: sum(r["minutes"] for r in week_practices if r["direction"] == direction) for direction in ("KO→JA", "JA→KO")}
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
    today_rows = [{"activity_type": a, "direction": d, "minutes": sum(r["minutes"] for r in today_raw if r["activity_type"] == a and r["direction"] == d)} for a in ACTIVITY_LABELS for d in ("KO→JA", "JA→KO")]
    def routine_minutes(rows, activity, direction):
        return sum(r["minutes"] for r in rows if r["activity_type"] == activity and (direction is None or r["direction"] == direction))
    cols = st.columns(5)
    for col, (activity, direction, label) in zip(cols, routines):
        current = routine_minutes(today_rows, activity, direction)
        col.markdown(f"### {'✅' if current >= 10 else '⬜'} {label}")
        col.caption(f"오늘 {current}분 / 기본 10분")
        col.progress(min(current / 10, 1.0))
    st.subheader("이번 주 루틴 실천표")
    week_days = [date.fromisoformat(week) + timedelta(days=i) for i in range(7)]
    weekly_raw = db.practices_between(week_days[0].isoformat(), week_days[-1].isoformat())
    weekly_rows = [{"practice_date": day.isoformat(), "activity_type": a, "direction": d, "minutes": sum(r["minutes"] for r in weekly_raw if str(r["practice_date"])[:10] == day.isoformat() and r["activity_type"] == a and r["direction"] == d)} for day in week_days for a in ACTIVITY_LABELS for d in ("KO→JA", "JA→KO")]
    table = []
    for activity, direction, label in routines:
        row = {"기본 루틴": label}
        for day in week_days:
            day_rows = [r for r in weekly_rows if r["practice_date"] == day.isoformat()]
            amount = routine_minutes(day_rows, activity, direction)
            row[f"{day.strftime('%m/%d')}\n{'월화수목금토일'[day.weekday()]}"] = "✅" if amount >= 10 else (f"{amount}분" if amount else "—")
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
    hero("연습", "동시통역·순차통역·시역·섀도잉 연습과 셀프피드백을 기록하세요.")
    with st.form("practice", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        day = c1.date_input("날짜", date.today())
        activity_label = c2.selectbox("연습 유형", list(ACTIVITY_LABELS.values()))
        activity_type = next(k for k, v in ACTIVITY_LABELS.items() if v == activity_label)
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
    rows = [{"날짜":r["practice_date"], "연습유형":ACTIVITY_LABELS.get(r["activity_type"], r["activity_type"]), "방향":r["direction"], "자료":r["title"], "주제":r["topic"], "URL":r.get("source_url", ""), "속도":f"×{r.get('video_speed',1.0):.2f}" if r["activity_type"]=="simultaneous" else "—", "분":r["minutes"], "난이도":r["difficulty"]} for r in db.recent_practices(20)]
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.info("아직 연습 기록이 없습니다.")
    if rows:
        st.markdown("#### 기록별 수정")
        raw_rows = db.recent_practices(20)
        fields = [(x,y) for x,y in [("practice_date","날짜"),("activity_type","연습 유형"),("direction","방향"),("title","자료 제목"),("topic","주제"),("source_url","URL"),("video_speed","속도"),("minutes","분"),("difficulty","난이도"),("omission","내용 누락"),("number_omission","숫자 누락"),("logic_error","논리 오류"),("expression_block","표현 막힘"),("unnatural_expression","부자연스러운 표현"),("other_notes","메모")]]
        for r in raw_rows: edit_button("practices", r, fields, f"{r['practice_date']} · {ACTIVITY_LABELS.get(r['activity_type'])} {r['direction']} · {r['title']}", f"practice_{r['id']}")


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
        st.markdown("#### 기록별 수정")
        fields = [("korean","한국어"),("japanese","일본어"),("pair_type","유형"),("source","출처"),("notes","메모"),("mastery","숙지도")]
        for r in rows: edit_button("language_pairs", r, fields, f"{r['korean']} → {r['japanese']}", f"pair_{r['id']}")
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
            edit_button("study_notes", note, [("note_date","날짜"),("title","제목"),("content","내용"),("tags","태그")], f"{note['note_date']} · {note['title']}", f"note_{note['id']}")
            with st.expander(f"{note['note_date']} · {note['title']}"):
                st.write(note["content"])
                if note["tags"]: st.caption(f"태그: {note['tags']}")
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


def script_feedback():
    hero("스크립트 피드백", "원문과 실제 통역문을 비교해 기본 셀프피드백을 만들고 저장하세요.")
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
                result = analyze_scripts(source_script, interpreted_script)
                db.add_script_feedback({"feedback_date":feedback_date.isoformat(), "interpretation_type":interpretation_type, "direction":direction, "title":title.strip(), "source_script":source_script.strip(), "interpreted_script":interpreted_script.strip(), "feedback":result})
                st.session_state["latest_script_feedback"] = result
                st.success("분석 결과를 저장했습니다.")
    if st.session_state.get("latest_script_feedback"):
        st.subheader("이번 분석 결과"); st.text(st.session_state["latest_script_feedback"])
    st.subheader("저장된 피드백")
    for item in db.all_script_feedbacks()[:20]:
        edit_button("script_feedbacks", item, [("feedback_date","날짜"),("interpretation_type","통역 유형"),("direction","방향"),("title","제목"),("source_script","대상 스크립트"),("interpreted_script","실제 통역 스크립트"),("feedback","피드백")], f"{item['feedback_date']} · {item['interpretation_type']} {item['direction']} · {item['title']}", f"feedback_{item['id']}")
        with st.expander(f"{item['feedback_date']} · {item['interpretation_type']} {item['direction']} · {item['title']}"):
            st.text(item["feedback"])


def script_review():
    hero("스크립트 복습", "본문을 드래그해 하이라이트하고 선택한 부분 아래에 메모를 남기세요.")
    if script_highlighter_component is None:
        st.error("하이라이터 파일이 없습니다. GitHub에서 app.py와 같은 위치에 script_highlighter/index.html을 업로드해주세요.")
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


def statistics():
    hero("통계", "연습량과 반복되는 약점을 한눈에 확인하세요.")
    practices = pd.DataFrame(db.all_practices())
    pairs = pd.DataFrame(db.all_pairs())
    if practices.empty and pairs.empty: st.info("기록이 쌓이면 통계가 표시됩니다."); return
    if not practices.empty:
        totals = practices.groupby("direction")["minutes"].sum().reindex(["KO→JA","JA→KO"], fill_value=0)
        a,b = st.columns(2); a.metric("KO→JA 누적", f"{totals['KO→JA']}분"); b.metric("JA→KO 누적", f"{totals['JA→KO']}분")
        st.subheader("방향별 누적 연습시간"); st.bar_chart(totals, horizontal=True)
        activity_totals = practices.groupby("activity_type")["minutes"].sum().rename(index=ACTIVITY_LABELS)
        st.subheader("연습 유형별 누적시간"); st.bar_chart(activity_totals, horizontal=True)
        error_totals = practices[list(ERROR_LABELS)].sum().rename(index=ERROR_LABELS)
        st.subheader("오류 유형 누적"); st.bar_chart(error_totals.sort_values(ascending=False), horizontal=True)
        practices["practice_date"] = pd.to_datetime(practices["practice_date"])
        weekly = practices.set_index("practice_date").groupby("direction")["minutes"].resample("W-MON").sum().unstack(0).fillna(0)
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


pages = {"대시보드": dashboard, "연습": practice, "언어쌍": language_pairs, "리뷰": review, "스크립트 피드백": script_feedback, "스크립트 복습": script_review, "공부 메모": study_notes, "통계": statistics}
st.sidebar.title("🎧 통역 플래너")
st.sidebar.caption(f"저장소 · {db.backend_name()}")
selection = st.sidebar.radio("메뉴", list(pages), label_visibility="collapsed")
st.sidebar.caption("기본 루틴 · 방향별 동시통역·순차통역, 섀도잉 각 10분")
pages[selection]()
