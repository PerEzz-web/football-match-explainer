import json
from datetime import datetime

import openpyxl
import streamlit as st
from openai import OpenAI

DEFAULT_ALLOWED_DOMAINS = [
    "fotmob.com",
    "sofascore.com",
    "flashscore.com",
    "whoscored.com",
    "soccerway.com",
    "fbref.com",
    "theanalyst.com",
    "transfermarkt.com",
    "espn.com",
    "onefootball.com",
]

DEFAULT_SYSTEM_PROMPT = """You are a football match prediction analyst and editorial writer.

Your job is NOT to invent probabilities. Your job is to EXPLAIN and JUSTIFY the probabilities supplied by the user's forecast file using recent, relevant football information found on the web.

Important rules:
1. The forecast values from the Excel file are the source of truth.
2. Use web research only to explain and support those values.
3. Stay aligned with the supplied forecast.
4. Never invent facts.
5. If a detail cannot be verified, say so briefly and continue with the strongest verified evidence.
6. Search only within the allowed domains provided by the app.
7. Use no more than the allowed number of tool calls.
8. Return JSON only.

Write in clear, website-ready English.

Return these sections:
- general_match_description
- match_outcome_probability
- correct_score_probability
- both_teams_to_score
- match_goals_probability

Each section must contain:
- title
- text

The correct score section must also contain:
- most_likely_score

The BTTS section must also contain:
- most_likely_outcome

The match outcome section must also contain:
- favored_outcome
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "general_match_description": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["title", "text"],
            "additionalProperties": False,
        },
        "match_outcome_probability": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "favored_outcome": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["title", "favored_outcome", "text"],
            "additionalProperties": False,
        },
        "correct_score_probability": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "most_likely_score": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["title", "most_likely_score", "text"],
            "additionalProperties": False,
        },
        "both_teams_to_score": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "most_likely_outcome": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["title", "most_likely_outcome", "text"],
            "additionalProperties": False,
        },
        "match_goals_probability": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "text": {"type": "string"},
            },
            "required": ["title", "text"],
            "additionalProperties": False,
        },
    },
    "required": [
        "general_match_description",
        "match_outcome_probability",
        "correct_score_probability",
        "both_teams_to_score",
        "match_goals_probability",
    ],
    "additionalProperties": False,
}


def clean_text(value):
    if value is None:
        return None
    return str(value).replace("\xa0", " ").strip()


def parse_percent(value):
    text = clean_text(value)
    if not text:
        return None
    text = text.replace("%", "").strip()
    try:
        return float(text) / 100
    except ValueError:
        return None


def parse_match_datetime(value):
    text = clean_text(value)
    if not text:
        return None, None, None

    dt = None
    for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"):
        try:
            dt = datetime.strptime(text, fmt)
            break
        except ValueError:
            pass

    if dt is None:
        return text, None, None

    return text, dt.strftime("%Y-%m-%d"), dt.strftime("%d %b %Y %H:%M")


@st.cache_data
def load_matches_from_excel(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active

    matches = []
    row = 2

    while row <= ws.max_row:
        top_left = clean_text(ws.cell(row, 1).value)
        bottom_left = clean_text(ws.cell(row + 1, 1).value) if row + 1 <= ws.max_row else None

        # Your file stores each match across 2 rows
        if top_left and ":" in top_left and bottom_left and " - " in bottom_left:
            raw_datetime, match_date_iso, match_date_display = parse_match_datetime(top_left)
            home_team, away_team = [part.strip() for part in bottom_left.split(" - ", 1)]

            home_win = parse_percent(ws.cell(row, 2).value)
            draw = parse_percent(ws.cell(row, 3).value)
            away_win = parse_percent(ws.cell(row, 4).value)

            correct_scores = [
                {
                    "score": clean_text(ws.cell(row, 5).value),
                    "probability": parse_percent(ws.cell(row + 1, 5).value),
                },
                {
                    "score": clean_text(ws.cell(row, 6).value),
                    "probability": parse_percent(ws.cell(row + 1, 6).value),
                },
                {
                    "score": clean_text(ws.cell(row, 7).value),
                    "probability": parse_percent(ws.cell(row + 1, 7).value),
                },
            ]

            btts_yes = parse_percent(ws.cell(row, 8).value)
            btts_no = parse_percent(ws.cell(row + 1, 8).value)

            totals = {
                "over_1_5": parse_percent(ws.cell(row, 9).value),
                "over_2_5": parse_percent(ws.cell(row, 10).value),
                "over_3_5": parse_percent(ws.cell(row, 11).value),
                "under_1_5": parse_percent(ws.cell(row, 12).value),
                "under_2_5": parse_percent(ws.cell(row, 13).value),
                "under_3_5": parse_percent(ws.cell(row, 14).value),
            }

            handicaps = {
                "home_handicap_0_5": parse_percent(ws.cell(row, 15).value),
                "home_handicap_1_5": parse_percent(ws.cell(row, 16).value),
                "home_handicap_2_5": parse_percent(ws.cell(row, 17).value),
                "away_handicap_0_5": parse_percent(ws.cell(row, 18).value),
                "away_handicap_1_5": parse_percent(ws.cell(row, 19).value),
                "away_handicap_2_5": parse_percent(ws.cell(row, 20).value),
                "home_handicap_minus_0_5": parse_percent(ws.cell(row, 21).value),
                "home_handicap_minus_1_5": parse_percent(ws.cell(row, 22).value),
                "home_handicap_minus_2_5": parse_percent(ws.cell(row, 23).value),
                "away_handicap_minus_0_5": parse_percent(ws.cell(row, 24).value),
                "away_handicap_minus_1_5": parse_percent(ws.cell(row, 25).value),
                "away_handicap_minus_2_5": parse_percent(ws.cell(row, 26).value),
            }

            favored_outcome = max(
                [
                    ("Home win", home_win),
                    ("Draw", draw),
                    ("Away win", away_win),
                ],
                key=lambda item: item[1] if item[1] is not None else -1,
            )[0]

            most_likely_score = max(
                correct_scores,
                key=lambda item: item["probability"] if item["probability"] is not None else -1,
            )["score"]

            most_likely_btts = "Yes" if (btts_yes or 0) >= (btts_no or 0) else "No"

            matches.append(
                {
                    "label": f"{home_team} vs {away_team} — {match_date_display or raw_datetime}",
                    "home_team": home_team,
                    "away_team": away_team,
                    "match_date": match_date_iso or raw_datetime,
                    "match_date_display": match_date_display or raw_datetime,
                    "engine_forecast": {
                        "match_outcome_probability": {
                            "home_win": home_win,
                            "draw": draw,
                            "away_win": away_win,
                            "favored_outcome": favored_outcome,
                        },
                        "correct_score_probability": {
                            "top_outcomes": correct_scores,
                            "most_likely_score": most_likely_score,
                        },
                        "both_teams_to_score": {
                            "yes": btts_yes,
                            "no": btts_no,
                            "most_likely_outcome": most_likely_btts,
                        },
                        "match_goals_probability": totals,
                        "handicaps": handicaps,
                    },
                }
            )

            row += 2
        else:
            row += 1

    return matches


def build_user_payload(match):
    return {
        "match": {
            "home_team": match["home_team"],
            "away_team": match["away_team"],
            "match_date": match["match_date"],
            "output_language": "en",
        },
        "engine_forecast": match["engine_forecast"],
    }


def generate_explanation(match, model_name, system_prompt, allowed_domains, max_tool_calls):
    client = OpenAI(api_key=st.secrets["OPENAI_API_KEY"])

    response = client.responses.create(
        model=model_name,
        instructions=system_prompt,
        input=json.dumps(build_user_payload(match), ensure_ascii=False),
        tools=[
            {
                "type": "web_search",
                "filters": {"allowed_domains": allowed_domains},
            }
        ],
        include=["web_search_call.action.sources"],
        max_tool_calls=max_tool_calls,
        text={
            "format": {
                "type": "json_schema",
                "name": "match_explanation",
                "strict": True,
                "schema": OUTPUT_SCHEMA,
            }
        },
    )

    return json.loads(response.output_text)


st.set_page_config(page_title="Football Match Explainer", layout="wide")
st.title("Football Match Explainer")

with st.sidebar:
    st.header("Settings")

    model_name = st.selectbox(
        "GPT model",
        ["gpt-4o", "gpt-4o-mini", "gpt-5"],
        index=0,
    )

    max_tool_calls = st.slider("Max web search calls", 1, 10, 4)

    domains_text = st.text_area(
        "Allowed websites (one per line)",
        value="\n".join(DEFAULT_ALLOWED_DOMAINS),
        height=180,
    )
    allowed_domains = [line.strip() for line in domains_text.splitlines() if line.strip()]

    system_prompt = st.text_area(
        "System prompt",
        value=DEFAULT_SYSTEM_PROMPT,
        height=320,
    )

matches = load_matches_from_excel("Forecasts.xlsx")

if not matches:
    st.error("No matches were found in Forecasts.xlsx")
    st.stop()

selected_label = st.selectbox("Select a match", [m["label"] for m in matches])
selected_match = next(m for m in matches if m["label"] == selected_label)

st.subheader("Selected match data from the Excel file")
st.json(selected_match)

if st.button("Generate explanation"):
    with st.spinner("Generating explanation..."):
        try:
            result = generate_explanation(
                match=selected_match,
                model_name=model_name,
                system_prompt=system_prompt,
                allowed_domains=allowed_domains,
                max_tool_calls=max_tool_calls,
            )
        except Exception as e:
            st.error(f"Error: {e}")
        else:
            st.success("Done")

            st.subheader(result["general_match_description"]["title"])
            st.write(result["general_match_description"]["text"])

            st.subheader(result["match_outcome_probability"]["title"])
            st.write(f"Favored outcome: {result['match_outcome_probability']['favored_outcome']}")
            st.write(result["match_outcome_probability"]["text"])

            st.subheader(result["correct_score_probability"]["title"])
            st.write(f"Most likely score: {result['correct_score_probability']['most_likely_score']}")
            st.write(result["correct_score_probability"]["text"])

            st.subheader(result["both_teams_to_score"]["title"])
            st.write(f"Most likely BTTS outcome: {result['both_teams_to_score']['most_likely_outcome']}")
            st.write(result["both_teams_to_score"]["text"])

            st.subheader(result["match_goals_probability"]["title"])
            st.write(result["match_goals_probability"]["text"])
