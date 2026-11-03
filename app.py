import base64
import datetime
import io
import json
import os
import re
import time
import warnings

# Suppress deprecation warnings on console
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*st.components.v1.html.*")

from dotenv import load_dotenv
from groq import Groq
from gtts import gTTS
from pypdf import PdfReader
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
import streamlit as st
import streamlit.components.v1 as components

# ==============================================================================
# CONFIGURATION SETTINGS
# (Customizable in code: change interview, aptitude, and coding parameters here)
# ==============================================================================
TOTAL_INTERVIEW_QUESTIONS = 3  # Customizable in code
APTITUDE_QUESTIONS_PER_ROUND = 3  # Questions per round (3 x 4 rounds = 12 total questions)
CODING_PROBLEMS_COUNT = 2  # Total coding problems in technical coding round
APTITUDE_SEC_PER_QUESTION = 90  # Recommended seconds per aptitude question (1.5 mins)

# Page configuration
st.set_page_config(
    page_title="AI Career Suite: Full Hiring Drive & Modular Rounds",
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load environment variables
load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

if not GROQ_API_KEY:
    st.error("⚠️ GROQ_API_KEY is missing. Please add it to your .env file or environment variables.")
    st.stop()

groq_client = Groq(api_key=GROQ_API_KEY)


# ==============================================================================
# SESSION STATE INITIALIZATION
# ==============================================================================
if "resume_text" not in st.session_state:
    st.session_state.resume_text = ""
if "resume_filename" not in st.session_state:
    st.session_state.resume_filename = None
if "candidate_track" not in st.session_state:
    st.session_state.candidate_track = "Experienced"
if "target_role" not in st.session_state:
    st.session_state.target_role = "Software Engineer"

# Global Dashboard Navigation & Mode
if "app_mode" not in st.session_state:
    st.session_state.app_mode = "dashboard"  # 'dashboard', 'full_drive', 'individual'
if "drive_stage" not in st.session_state:
    st.session_state.drive_stage = "aptitude"  # 'aptitude', 'coding', 'interview', 'master_summary'
if "individual_active_round" not in st.session_state:
    st.session_state.individual_active_round = "aptitude"  # 'aptitude', 'coding', 'interview', 'ats'

# Voice Interview states
if "interview_status" not in st.session_state:
    st.session_state.interview_status = "idle"  # 'idle', 'in_progress', 'completed'
if "current_question_index" not in st.session_state:
    st.session_state.current_question_index = 0
if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []
if "evaluations" not in st.session_state:
    st.session_state.evaluations = []
if "final_report" not in st.session_state:
    st.session_state.final_report = None
if "current_question" not in st.session_state:
    st.session_state.current_question = ""
if "current_audio" not in st.session_state:
    st.session_state.current_audio = None
if "autoplay_voice" not in st.session_state:
    st.session_state.autoplay_voice = True

# Aptitude Assessment states
if "aptitude_status" not in st.session_state:
    st.session_state.aptitude_status = "idle"  # 'idle', 'in_progress', 'completed'
if "aptitude_current_round" not in st.session_state:
    st.session_state.aptitude_current_round = 1  # 1 to 4
if "aptitude_rounds_data" not in st.session_state:
    st.session_state.aptitude_rounds_data = None
if "aptitude_user_answers" not in st.session_state:
    st.session_state.aptitude_user_answers = {}  # {q_id: selected_option}
if "aptitude_final_report" not in st.session_state:
    st.session_state.aptitude_final_report = None
if "aptitude_round_start_time" not in st.session_state:
    st.session_state.aptitude_round_start_time = None

# Coding Round states
if "coding_status" not in st.session_state:
    st.session_state.coding_status = "idle"  # 'idle', 'in_progress', 'completed'
if "coding_problems" not in st.session_state:
    st.session_state.coding_problems = None
if "coding_language" not in st.session_state:
    st.session_state.coding_language = "C"  # C programming available by default
if "coding_submissions" not in st.session_state:
    st.session_state.coding_submissions = {"p1": "", "p2": ""}
if "coding_final_report" not in st.session_state:
    st.session_state.coding_final_report = None

# ATS Scanner states
if "ats_result" not in st.session_state:
    st.session_state.ats_result = None
if "ats_jd_text" not in st.session_state:
    st.session_state.ats_jd_text = ""


# ==============================================================================
# HELPER FUNCTIONS: TEXT, SPEECH & SANITIZERS
# ==============================================================================
def extract_text_from_pdf(pdf_file):
    """Extracts text from the uploaded PDF resume."""
    try:
        pdf_reader = PdfReader(pdf_file)
        pages_text = []
        for page in pdf_reader.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
        return "\n".join(pages_text).strip(), len(pdf_reader.pages)
    except Exception as e:
        st.error(f"Error reading PDF: {e}")
        return "", 0


def clean_markdown_for_speech(text):
    """Strips markdown formatting, bullet markers, and brackets for natural TTS output."""
    text = re.sub(r"```[\s\S]*?```", "", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\*\*|\*|__|_", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\d+\.\s+", "", text, flags=re.MULTILINE)
    return text.strip()


def text_to_speech(text):
    """Converts clean text to MP3 audio bytes using gTTS."""
    try:
        clean_text = clean_markdown_for_speech(text)
        if not clean_text:
            return None
        tts = gTTS(text=clean_text, lang="en", slow=False)
        fp = io.BytesIO()
        tts.write_to_fp(fp)
        fp.seek(0)
        return fp
    except Exception as e:
        st.warning(f"Voice generation note: {e}")
        return None


def transcribe_audio(audio_file, client):
    """Transcribes user voice recording via Groq's Whisper model."""
    try:
        audio_bytes = audio_file.read()
        response = client.audio.transcriptions.create(
            file=("audio.wav", audio_bytes),
            model="whisper-large-v3",
            response_format="text",
        )
        if isinstance(response, str):
            return response.strip()
        elif hasattr(response, "text"):
            return response.text.strip()
        return str(response).strip()
    except Exception as e:
        st.error(f"Audio transcription error: {e}")
        return None


def sanitize_question_dict(q, fallback_id="q"):
    """
    Guarantees that:
    1. The question statement contains ONLY the problem statement (no options, no leaked answers or explanations).
    2. The options are a clean list of 4 choices.
    3. The correct_answer is extracted and normalized to match one of the options.
    4. The explanation is separated so it only shows AFTER test submission.
    """
    raw_q = str(q.get("question", "")).strip()

    # Detect if answer or explanation was accidentally concatenated into the question text
    m_ans = re.search(r"(?i)\b(?:correct[_\s]*answer|answer|key)\s*[:：\n\s]+([A-D](?:\s*\)|[.\s][^\n]*)?)", raw_q)
    leaked_ans = m_ans.group(1).strip() if m_ans else None

    m_exp = re.search(r"(?i)\bexplanation\s*[:：\n\s]+([\s\S]+)", raw_q)
    leaked_exp = m_exp.group(1).strip() if m_exp else None

    # Cut off any leaked options (A), B), C), D)) or leaked answers/explanations from the question text
    cleaned_q = re.split(r"(?im)^\s*(?:[A-D]\s*[\).]|correct[_\s]*answer|answer|explanation)\s*[:：\n\s]?", raw_q)[0].strip()
    if not cleaned_q:
        cleaned_q = raw_q.split("\n")[0].strip()

    # Extract and clean options
    raw_opts = q.get("options", [])
    cleaned_opts = []
    if isinstance(raw_opts, list):
        for opt in raw_opts:
            if isinstance(opt, str):
                clean_opt = re.split(r"(?i)\s*(?:correct[_\s]*answer|explanation)\s*[:：]", opt)[0].strip()
                if clean_opt:
                    cleaned_opts.append(clean_opt)
            elif isinstance(opt, dict):
                opt_text = opt.get("text", "") or opt.get("val", "")
                opt_key = opt.get("option", "") or opt.get("key", "")
                cleaned_opts.append(f"{opt_key}) {opt_text}".strip())

    if len(cleaned_opts) < 2:
        found_opts = re.findall(r"(?m)^\s*([A-D]\s*[\).][^\n]+)", raw_q)
        if found_opts:
            cleaned_opts = [re.split(r"(?i)\s*(?:correct[_\s]*answer|explanation)\s*[:：]", o)[0].strip() for o in found_opts]

    if len(cleaned_opts) < 4:
        cleaned_opts = ["A) Option A", "B) Option B", "C) Option C", "D) Option D"]

    # Extract correct_answer across all possible dictionary keys or leaked text
    correct_ans = ""
    for k in ["correct_answer", "correctAnswer", "correct_option", "correctOption", "answer", "correct", "key"]:
        if k in q and q[k]:
            correct_ans = str(q[k]).strip()
            break

    if not correct_ans and leaked_ans:
        correct_ans = leaked_ans

    if not correct_ans:
        correct_ans = cleaned_opts[0]

    # Normalize correct_ans to match the option string if it was just "A", "B", "C", "D"
    clean_c = correct_ans.strip().upper()
    if len(clean_c) >= 1 and clean_c[0] in "ABCD":
        char = clean_c[0]
        for opt in cleaned_opts:
            if opt.strip().upper().startswith(char):
                correct_ans = opt
                break

    explanation = q.get("explanation") or leaked_exp or "Standard solution guidelines."

    return {
        "id": q.get("id", fallback_id),
        "question": cleaned_q,
        "options": cleaned_opts,
        "correct_answer": correct_ans,
        "explanation": str(explanation).strip(),
    }


def is_answer_correct(user_ans, correct_ans):
    """Compares user's selected choice with the correct answer key safely."""
    if not user_ans or user_ans == "Not Answered":
        return False
    u = str(user_ans).strip()
    c = str(correct_ans).strip()
    if u.lower() == c.lower():
        return True
    u_char = u[0].upper() if len(u) > 0 and u[0].upper() in "ABCD" else None
    c_char = c[0].upper() if len(c) > 0 and c[0].upper() in "ABCD" else None
    if u_char and c_char and u_char == c_char:
        return True
    return False


def render_countdown_timer(total_seconds, label="Round Countdown Timer"):
    """
    Renders a real-time, client-side ticking countdown timer badge.
    Uses modern st.iframe / base64 iframe to eliminate st.components.v1.html deprecation notices.
    """
    timer_html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;overflow:hidden;background:transparent;">
  <div style="background: linear-gradient(135deg, #1E3A8A, #2563EB); color: white; padding: 10px 18px; border-radius: 8px; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
    <div>
      <span style="font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; opacity: 0.85;">⏳ {label}</span><br>
      <span style="font-size: 22px; font-weight: 700; letter-spacing: 1px;" id="live-timer-display">--:--</span>
    </div>
    <div style="text-align: right;">
      <span style="font-size: 11px; opacity: 0.85;">⏱️ Recommended per Question: ~{APTITUDE_SEC_PER_QUESTION}s</span><br>
      <span style="font-size: 12px; font-weight: 600; color: #93C5FD;" id="timer-status">● Live Session</span>
    </div>
  </div>
  <script>
    (function() {{
      let timeLeft = {total_seconds};
      let display = document.getElementById("live-timer-display");
      let status = document.getElementById("timer-status");
      function updateClock() {{
        let m = Math.floor(timeLeft / 60);
        let s = timeLeft % 60;
        m = m < 10 ? "0" + m : m;
        s = s < 10 ? "0" + s : s;
        display.textContent = m + ":" + s;
        if (timeLeft <= 30 && timeLeft > 0) {{
          display.style.color = "#FEF08A";
          status.textContent = "⚠️ Ending Soon";
          status.style.color = "#FEF08A";
        }}
        if (timeLeft <= 0) {{
          clearInterval(timerInterval);
          display.textContent = "00:00 (Time Up!)";
          display.style.color = "#FCA5A5";
          status.textContent = "⛔ Time Expired";
          status.style.color = "#FCA5A5";
        }}
        timeLeft--;
      }}
      updateClock();
      let timerInterval = setInterval(updateClock, 1000);
    }})();
  </script>
</body>
</html>"""

    # 1. Try modern st.iframe if available in recent Streamlit versions
    if hasattr(st, "iframe"):
        try:
            st.iframe(srcdoc=timer_html, height=75)
            return
        except Exception:
            pass

    # 2. Try components.iframe with standard base64 data URI (avoids deprecation warnings)
    if hasattr(components, "iframe"):
        try:
            b64_html = base64.b64encode(timer_html.encode("utf-8")).decode("utf-8")
            components.iframe(src=f"data:text/html;base64,{b64_html}", height=75)
            return
        except Exception:
            pass

    # 3. Fallback: components.html with warnings suppressed
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            components.html(timer_html, height=75)
    except Exception:
        st.info(f"⏳ **{label}**: Allocated Time: {total_seconds // 60}m {total_seconds % 60}s")


# ==============================================================================
# REPORTLAB PDF GENERATION FUNCTIONS
# ==============================================================================
def get_pdf_base_elements(title, subtitle_meta):
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=18,
        leading=22,
        textColor=colors.HexColor("#1E3A8A"),
        spaceAfter=4,
    )
    meta_style = ParagraphStyle(
        "DocMeta",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor("#4B5563"),
    )
    story = [
        Paragraph(title, title_style),
        Paragraph(subtitle_meta, meta_style),
        Spacer(1, 6),
        HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#1E3A8A"), spaceAfter=8),
    ]
    return story, styles


def generate_interview_scorecard_pdf(evaluations, report, resume_name, track, role):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    meta = f"<b>Candidate:</b> {resume_name or 'Uploaded Document'} &nbsp;|&nbsp; <b>Track:</b> {track} &nbsp;|&nbsp; <b>Role:</b> {role} &nbsp;|&nbsp; <b>Date:</b> {date_str}"
    story, styles = get_pdf_base_elements("AI Mock Interview — Official Performance Scorecard", meta)

    cell_style = ParagraphStyle("TC", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#1F2937"))
    cell_bold = ParagraphStyle("TCB", parent=styles["Normal"], fontSize=8, leading=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1E3A8A"))
    sub_title = ParagraphStyle("ST", parent=styles["Heading2"], fontSize=12, leading=16, textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle("DB", parent=styles["Normal"], fontSize=9, leading=13, textColor=colors.HexColor("#1F2937"))

    overall_score = report.get("overall_score", 0)
    rating = report.get("performance_rating", "Evaluated")
    cat = report.get("category_scores", {})

    score_data = [
        [
            Paragraph("<b>Overall Score</b>", cell_bold),
            Paragraph("<b>Verdict</b>", cell_bold),
            Paragraph("<b>Technical Depth</b>", cell_bold),
            Paragraph("<b>Resume Alignment</b>", cell_bold),
            Paragraph("<b>Problem Solving</b>", cell_bold),
            Paragraph("<b>STAR Delivery</b>", cell_bold),
        ],
        [
            Paragraph(f"<font size=12><b>{overall_score}/100</b></font>", cell_style),
            Paragraph(f"<b>{rating}</b>", cell_style),
            Paragraph(f"{cat.get('technical_depth', 0)}/25", cell_style),
            Paragraph(f"{cat.get('experience_alignment', 0)}/25", cell_style),
            Paragraph(f"{cat.get('problem_solving', 0)}/25", cell_style),
            Paragraph(f"{cat.get('communication_and_structure', 0)}/25", cell_style),
        ],
    ]
    t = Table(score_data, colWidths=[90, 95, 90, 90, 85, 90])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F9FAFB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Executive Appraisal", sub_title))
    story.append(Paragraph(report.get("executive_summary", "Evaluation complete."), body_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Detailed Question-by-Question Transcript & Evaluation", sub_title))
    q_data = [[Paragraph("<b>#</b>", cell_bold), Paragraph("<b>Question & Spoken Answer</b>", cell_bold), Paragraph("<b>Score</b>", cell_bold), Paragraph("<b>Evaluator Feedback</b>", cell_bold)]]
    for item in evaluations:
        q_text = f"<b>Q{item['q_num']}:</b> {item['question']}<br/><br/><i>Candidate Answer:</i> \"{item['answer']}\""
        q_data.append([Paragraph(f"Q{item['q_num']}", cell_bold), Paragraph(q_text, cell_style), Paragraph(f"<b>{item['score']}/10</b>", cell_bold), Paragraph(item["feedback"], cell_style)])
    q_table = Table(q_data, colWidths=[28, 262, 50, 200])
    q_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(q_table)
    doc.build(story)
    return buffer.getvalue()


def generate_aptitude_scorecard_pdf(apt_data, candidate_name, role, track):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    meta = f"<b>Candidate:</b> {candidate_name or 'Candidate'} &nbsp;|&nbsp; <b>Target Role:</b> {role} &nbsp;|&nbsp; <b>Level:</b> {track} &nbsp;|&nbsp; <b>Date:</b> {date_str}"
    story, styles = get_pdf_base_elements("Aptitude & Technical Assessment — 4-Round Official Scorecard", meta)

    cell_style = ParagraphStyle("TC", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#1F2937"))
    cell_bold = ParagraphStyle("TCB", parent=styles["Normal"], fontSize=8, leading=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1E3A8A"))
    sub_title = ParagraphStyle("ST", parent=styles["Heading2"], fontSize=12, leading=16, textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=4)

    overall_pct = apt_data.get("overall_percentage", 0)
    verdict = apt_data.get("verdict", "Evaluated")
    rounds_summary = apt_data.get("rounds_summary", [])

    score_data = [
        [
            Paragraph("<b>Overall Aptitude Score</b>", cell_bold),
            Paragraph("<b>Hiring Cutoff Verdict</b>", cell_bold),
            Paragraph("<b>Total Questions</b>", cell_bold),
            Paragraph("<b>Correct Answers</b>", cell_bold),
            Paragraph("<b>Accuracy</b>", cell_bold),
        ],
        [
            Paragraph(f"<font size=12><b>{overall_pct}%</b></font>", cell_style),
            Paragraph(f"<b>{verdict}</b>", cell_style),
            Paragraph(f"{apt_data.get('total_questions', 0)}", cell_style),
            Paragraph(f"{apt_data.get('total_correct', 0)}", cell_style),
            Paragraph(f"{overall_pct}%", cell_style),
        ],
    ]
    t = Table(score_data, colWidths=[110, 140, 95, 95, 100])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F9FAFB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Round-by-Round Breakdown", sub_title))
    r_data = [[Paragraph("<b>Round</b>", cell_bold), Paragraph("<b>Assessment Competency</b>", cell_bold), Paragraph("<b>Score</b>", cell_bold), Paragraph("<b>Accuracy</b>", cell_bold), Paragraph("<b>Status</b>", cell_bold)]]
    for r in rounds_summary:
        r_data.append([
            Paragraph(f"Round {r.get('round_num')}", cell_bold),
            Paragraph(r.get("title", ""), cell_style),
            Paragraph(f"{r.get('score')} / {r.get('total')}", cell_style),
            Paragraph(f"{r.get('pct')}%", cell_style),
            Paragraph(f"<b>{r.get('status', 'Completed')}</b>", cell_style),
        ])
    r_table = Table(r_data, colWidths=[65, 230, 75, 75, 95])
    r_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F4F6")),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E5E7EB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(r_table)
    doc.build(story)
    return buffer.getvalue()


def generate_coding_scorecard_pdf(coding_report, candidate_name, role, track, language):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    meta = f"<b>Candidate:</b> {candidate_name or 'Candidate'} &nbsp;|&nbsp; <b>Role:</b> {role} ({track}) &nbsp;|&nbsp; <b>Language:</b> {language} &nbsp;|&nbsp; <b>Date:</b> {date_str}"
    story, styles = get_pdf_base_elements("Technical Coding Assessment — Official Scorecard", meta)

    cell_style = ParagraphStyle("TC", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#1F2937"))
    cell_bold = ParagraphStyle("TCB", parent=styles["Normal"], fontSize=8, leading=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1E3A8A"))
    sub_title = ParagraphStyle("ST", parent=styles["Heading2"], fontSize=12, leading=16, textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle("DB", parent=styles["Normal"], fontSize=9, leading=13, textColor=colors.HexColor("#1F2937"))

    overall_score = coding_report.get("overall_coding_score", 0)
    verdict = coding_report.get("verdict", "Evaluated")
    p1 = coding_report.get("problem_1", {})
    p2 = coding_report.get("problem_2", {})

    score_data = [
        [
            Paragraph("<b>Overall Coding Score</b>", cell_bold),
            Paragraph("<b>Verdict</b>", cell_bold),
            Paragraph("<b>Problem 1 Score</b>", cell_bold),
            Paragraph("<b>Problem 2 Score</b>", cell_bold),
            Paragraph("<b>Programming Language</b>", cell_bold),
        ],
        [
            Paragraph(f"<font size=12><b>{overall_score} / 100</b></font>", cell_style),
            Paragraph(f"<b>{verdict}</b>", cell_style),
            Paragraph(f"{p1.get('score', 0)} / 50", cell_style),
            Paragraph(f"{p2.get('score', 0)} / 50", cell_style),
            Paragraph(f"<b>{language}</b>", cell_style),
        ],
    ]
    t = Table(score_data, colWidths=[110, 130, 100, 100, 100])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F9FAFB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Executive Code Evaluation", sub_title))
    story.append(Paragraph(coding_report.get("executive_summary", "Evaluation complete."), body_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Problem 1 Technical Breakdown", sub_title))
    story.append(Paragraph(f"• <b>Title:</b> {p1.get('title', 'Problem 1')}", body_style))
    story.append(Paragraph(f"• <b>Correctness & Testcases:</b> {p1.get('correctness', 'Analyzed')}", body_style))
    story.append(Paragraph(f"• <b>Time & Space Complexity:</b> Time {p1.get('time_complexity', 'O(N)')} | Space {p1.get('space_complexity', 'O(1)')}", body_style))
    story.append(Paragraph(f"• <b>Review & Code Quality:</b> {p1.get('code_quality', '')}", body_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Problem 2 Technical Breakdown", sub_title))
    story.append(Paragraph(f"• <b>Title:</b> {p2.get('title', 'Problem 2')}", body_style))
    story.append(Paragraph(f"• <b>Correctness & Testcases:</b> {p2.get('correctness', 'Analyzed')}", body_style))
    story.append(Paragraph(f"• <b>Time & Space Complexity:</b> Time {p2.get('time_complexity', 'O(N)')} | Space {p2.get('space_complexity', 'O(1)')}", body_style))
    story.append(Paragraph(f"• <b>Review & Code Quality:</b> {p2.get('code_quality', '')}", body_style))

    doc.build(story)
    return buffer.getvalue()


def generate_ats_scorecard_pdf(ats_data, resume_name, role_name):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    meta = f"<b>Resume:</b> {resume_name or 'Uploaded Document'} &nbsp;|&nbsp; <b>Target Role:</b> {role_name} &nbsp;|&nbsp; <b>Date:</b> {date_str}"
    story, styles = get_pdf_base_elements("Applicant Tracking System (ATS) Compatibility Audit", meta)

    cell_style = ParagraphStyle("TC", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#1F2937"))
    cell_bold = ParagraphStyle("TCB", parent=styles["Normal"], fontSize=8, leading=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1E3A8A"))
    sub_title = ParagraphStyle("ST", parent=styles["Heading2"], fontSize=12, leading=16, textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle("DB", parent=styles["Normal"], fontSize=9, leading=13, textColor=colors.HexColor("#1F2937"))

    overall_score = ats_data.get("overall_ats_score", 0)
    match_level = ats_data.get("match_level", "Evaluated")
    cats = ats_data.get("category_breakdown", {})

    score_data = [
        [
            Paragraph("<b>Overall ATS Match</b>", cell_bold),
            Paragraph("<b>Match Verdict</b>", cell_bold),
            Paragraph("<b>Hard Skills Match</b>", cell_bold),
            Paragraph("<b>Experience Match</b>", cell_bold),
            Paragraph("<b>Education Match</b>", cell_bold),
            Paragraph("<b>ATS Parseability</b>", cell_bold),
        ],
        [
            Paragraph(f"<font size=12><b>{overall_score} %</b></font>", cell_style),
            Paragraph(f"<b>{match_level}</b>", cell_style),
            Paragraph(f"{cats.get('hard_skills_match', {}).get('score', 0)} / 30", cell_style),
            Paragraph(f"{cats.get('experience_relevance', {}).get('score', 0)} / 30", cell_style),
            Paragraph(f"{cats.get('education_and_certifications', {}).get('score', 0)} / 20", cell_style),
            Paragraph(f"{cats.get('ats_parseability_and_impact', {}).get('score', 0)} / 20", cell_style),
        ],
    ]
    t = Table(score_data, colWidths=[90, 95, 90, 90, 85, 90])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F9FAFB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    missing = ats_data.get("critical_missing_keywords", [])
    story.append(Paragraph("Critical Missing Keywords", sub_title))
    story.append(Paragraph(", ".join(missing) if missing else "None! Excellent coverage.", body_style))
    doc.build(story)
    return buffer.getvalue()


def generate_master_scorecard_pdf(candidate_name, role, track, apt_data, coding_data, interview_data):
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    date_str = datetime.datetime.now().strftime("%B %d, %Y")
    meta = f"<b>Candidate:</b> {candidate_name or 'Candidate'} &nbsp;|&nbsp; <b>Target Role:</b> {role} &nbsp;|&nbsp; <b>Level:</b> {track} &nbsp;|&nbsp; <b>Date:</b> {date_str}"
    story, styles = get_pdf_base_elements("End-to-End Recruitment Drive — Unified Master Scorecard", meta)

    cell_style = ParagraphStyle("TC", parent=styles["Normal"], fontSize=8, leading=11, textColor=colors.HexColor("#1F2937"))
    cell_bold = ParagraphStyle("TCB", parent=styles["Normal"], fontSize=8, leading=11, fontName="Helvetica-Bold", textColor=colors.HexColor("#1E3A8A"))
    sub_title = ParagraphStyle("ST", parent=styles["Heading2"], fontSize=12, leading=16, textColor=colors.HexColor("#1F2937"), spaceBefore=10, spaceAfter=4)
    body_style = ParagraphStyle("DB", parent=styles["Normal"], fontSize=9, leading=13, textColor=colors.HexColor("#1F2937"))

    apt_score = apt_data.get("overall_percentage", 0) if apt_data else 0
    coding_score = coding_data.get("overall_coding_score", 0) if coding_data else 0
    interview_score = interview_data.get("overall_score", 0) if interview_data else 0

    composite = int(round((apt_score * 0.25) + (coding_score * 0.35) + (interview_score * 0.40)))
    verdict = "RECOMMENDED FOR HIRE (Top Tier Candidate)" if composite >= 75 else ("PASSED HIRING THRESHOLD" if composite >= 60 else "NEEDS ADDITIONAL DEVELOPMENT")

    summary_table = [
        [
            Paragraph("<b>Stage 1: Aptitude (25%)</b>", cell_bold),
            Paragraph("<b>Stage 2: Coding (35%)</b>", cell_bold),
            Paragraph("<b>Stage 3: Voice Interview (40%)</b>", cell_bold),
            Paragraph("<b>Composite Master Score</b>", cell_bold),
        ],
        [
            Paragraph(f"<font size=11><b>{apt_score}%</b></font>", cell_style),
            Paragraph(f"<font size=11><b>{coding_score} / 100</b></font>", cell_style),
            Paragraph(f"<font size=11><b>{interview_score} / 100</b></font>", cell_style),
            Paragraph(f"<font size=12 color='#1E3A8A'><b>{composite} / 100</b></font>", cell_style),
        ],
    ]
    t = Table(summary_table, colWidths=[130, 130, 135, 145])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#F9FAFB")),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#BFDBFE")),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    story.append(Spacer(1, 10))

    story.append(Paragraph("Final Hiring Committee Verdict", sub_title))
    story.append(Paragraph(f"<b>Overall Recommendation:</b> {verdict}", body_style))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Stage Breakdown Summaries", sub_title))
    if apt_data:
        story.append(Paragraph(f"• <b>Round 1 Aptitude:</b> {apt_data.get('total_correct')}/{apt_data.get('total_questions')} correct ({apt_score}%). Status: {apt_data.get('verdict')}", body_style))
    if coding_data:
        story.append(Paragraph(f"• <b>Round 2 Coding:</b> {coding_score}/100. P1 ({coding_data.get('problem_1',{}).get('score')}/50), P2 ({coding_data.get('problem_2',{}).get('score')}/50). Status: {coding_data.get('verdict')}", body_style))
    if interview_data:
        story.append(Paragraph(f"• <b>Round 3 AI Voice Interview:</b> {interview_score}/100. Rating: {interview_data.get('performance_rating')}. Summary: {interview_data.get('executive_summary')}", body_style))

    doc.build(story)
    return buffer.getvalue()


# ==============================================================================
# LLM FUNCTIONS: INTERVIEW, APTITUDE, CODING & ATS
# ==============================================================================
def get_track_guidelines(track, role):
    if track == "Fresher":
        return f"Focus on fundamental concepts, algorithmic thinking, and academic projects for {role}."
    return f"Focus on production system architecture, high-availability, scalability, and impact for {role}."


def generate_first_question(resume_text, track, role, client, model_name):
    track_prompt = get_track_guidelines(track, role)
    system_prompt = f"""
You are an experienced hiring manager conducting a {TOTAL_INTERVIEW_QUESTIONS}-question job interview for {role} ({track} level).
{track_prompt}
Output JSON: {{"greeting": "1 sentence warm greeting", "question": "Question 1 of {TOTAL_INTERVIEW_QUESTIONS}"}}
"""
    user_prompt = f"Resume:\n{resume_text}\nStart interview. Output JSON."
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        data = json.loads(response.choices[0].message.content)
        return f"{data.get('greeting', 'Welcome to the interview!')} {data.get('question', 'Could you please introduce yourself and walk me through your background?')}"
    except Exception:
        return f"Welcome! Thank you for speaking with me today for the {role} position. To start, could you please introduce yourself and walk me through your background?"


def evaluate_and_ask_next(resume_text, question_num, current_q, candidate_answer, prev_questions, track, role, client, model_name):
    next_q_num = question_num + 1
    is_final = question_num >= TOTAL_INTERVIEW_QUESTIONS
    track_prompt = get_track_guidelines(track, role)

    if is_final:
        trans_inst = f"- Since this was Question {TOTAL_INTERVIEW_QUESTIONS}, provide closing remarks thanking the candidate."
        json_spec = '  "score": <1-10>,\n  "feedback": "<critique>",\n  "verbal_reaction": "<1 sentence reaction>",\n  "closing_statement": "<closing remarks>"'
    else:
        trans_inst = f"- Seamlessly transition to Question {next_q_num} of {TOTAL_INTERVIEW_QUESTIONS}."
        json_spec = f'  "score": <1-10>,\n  "feedback": "<critique>",\n  "verbal_reaction": "<1 sentence reaction>",\n  "next_question": "<Question {next_q_num}>"'

    system_prompt = f"""
Expert lead interviewer for {role} ({track}). Total Questions: {TOTAL_INTERVIEW_QUESTIONS}. Current: {question_num}.
{track_prompt}
1. Score answer 1-10 with constructive feedback.
2. Formulate verbal reaction and {trans_inst}
Return JSON:
{{
{json_spec}
}}
"""
    prev_str = "\n".join(f"- Q{i+1}: {q}" for i, q in enumerate(prev_questions))
    user_prompt = f"Resume:\n{resume_text}\nPrevious Qs:\n{prev_str}\nAnswered Q{question_num}: {current_q}\nSpoken Answer: {candidate_answer}"

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_object"},
        temperature=0.6,
    )
    data = json.loads(response.choices[0].message.content)
    score = int(data.get("score", 7))
    feedback = data.get("feedback", "Good communication with relevant points.")
    reaction = data.get("verbal_reaction", "Thank you for sharing those insights.")

    if not is_final:
        next_q = data.get("next_question", "Could you tell me more about your technical accomplishments?")
        full_spoken = f"{reaction} {next_q}"
    else:
        closing = data.get("closing_statement", f"That concludes our {TOTAL_INTERVIEW_QUESTIONS} questions. Thank you for your thoughtful responses!")
        full_spoken = f"{reaction} {closing}"

    return score, feedback, full_spoken


def generate_final_summary_report(resume_text, evaluations, track, role, client, model_name):
    system_prompt = f"""
Talent assessment lead evaluating {role} ({track}).
Output JSON:
{{
  "overall_score": <integer 0-100>,
  "performance_rating": "<Needs Improvement | Fair | Good | Strong | Exceptional>",
  "category_scores": {{ "technical_depth": <0-25>, "experience_alignment": <0-25>, "problem_solving": <0-25>, "communication_and_structure": <0-25> }},
  "key_strengths": ["<s1>", "<s2>", "<s3>"],
  "areas_for_improvement": ["<a1>", "<a2>", "<a3>"],
  "executive_summary": "<3-4 sentence appraisal>"
}}
"""
    transcript = "\n".join(f"Q{e['q_num']}: {e['question']}\nAns: {e['answer']}\nScore: {e['score']}/10\nFeedback: {e['feedback']}\n---" for e in evaluations)
    user_prompt = f"Resume:\n{resume_text}\nTranscript:\n{transcript}"

    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_object"},
        temperature=0.5,
    )
    return json.loads(response.choices[0].message.content)


def generate_aptitude_rounds_data(role, track, client, model_name):
    """
    Generates 4 distinct rounds with strict formatting rules to prevent answers
    or explanations from leaking into the question text.
    """
    system_prompt = f"""
You are an expert psychometric and technical assessment test designer.
Design a 4-round aptitude test for {role} ({track} level).
Round 1: Quantitative Aptitude & Numerical Ability
Round 2: Logical Reasoning & Critical Thinking
Round 3: Verbal Ability & Professional Communication
Round 4: Domain Knowledge & Coding / Technical Concepts for {role}

STRICT FORMATTING RULES:
1. Exactly {APTITUDE_QUESTIONS_PER_ROUND} questions per round.
2. The "question" string must contain ONLY the question statement. NEVER include the options (A, B, C, D), correct_answer, or explanation inside the "question" string.
3. The "options" list must be an array of exactly 4 strings: ["A) ...", "B) ...", "C) ...", "D) ..."].
4. The "correct_answer" field MUST be provided as a separate JSON key matching one of the options (e.g. "C) ..." or "C"). DO NOT OMIT THIS KEY.
5. The "explanation" field MUST be provided as a separate JSON key explaining the solution.

Output strictly valid JSON with this exact schema:
{{
  "round_1": {{ "round_num": 1, "title": "Quantitative Aptitude", "description": "Numerical reasoning", "questions": [ {{ "id": "r1_q1", "question": "Clean question statement only", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "correct_answer": "B) ...", "explanation": "Detailed explanation..." }} ] }},
  "round_2": {{ "round_num": 2, "title": "Logical Reasoning", "description": "Deductive logic", "questions": [ ... ] }},
  "round_3": {{ "round_num": 3, "title": "Verbal Ability", "description": "Communication precision", "questions": [ ... ] }},
  "round_4": {{ "round_num": 4, "title": "Domain & Coding Skills", "description": "Technical problem solving", "questions": [ ... ] }}
}}
"""
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": "Generate 4 rounds JSON strictly following formatting rules"}],
            response_format={"type": "json_object"},
            temperature=0.5,
        )
        raw_data = json.loads(response.choices[0].message.content)

        # Sanitize every single question to eliminate any leaked answers or explanations
        sanitized_rounds = {}
        for r_key in ["round_1", "round_2", "round_3", "round_4"]:
            r_data = raw_data.get(r_key, {})
            q_list = r_data.get("questions", [])
            sanitized_q_list = []
            for idx, q in enumerate(q_list, start=1):
                sq = sanitize_question_dict(q, fallback_id=f"{r_key}_q{idx}")
                sanitized_q_list.append(sq)
            r_data["questions"] = sanitized_q_list
            sanitized_rounds[r_key] = r_data

        return sanitized_rounds

    except Exception:
        # Fallback preset
        raw_preset = {
            "round_1": {"round_num": 1, "title": "Quantitative Aptitude", "description": "Numerical reasoning", "questions": [
                {"id": "r1_q1", "question": "A train 180m long crosses a 220m platform in 20s. What is its speed in km/h?", "options": ["A) 64 km/h", "B) 72 km/h", "C) 80 km/h", "D) 90 km/h"], "correct_answer": "B) 72 km/h", "explanation": "Total distance = 400m. Speed = 400m / 20s = 20 m/s = 72 km/h."},
                {"id": "r1_q2", "question": "If the price of a commodity rises by 25%, by what percentage must consumption be reduced to keep total expenditure unchanged?", "options": ["A) 15%", "B) 20%", "C) 25%", "D) 30%"], "correct_answer": "B) 20%", "explanation": "Reduction = (25 / 125) * 100 = 20%."},
                {"id": "r1_q3", "question": "What is the probability of drawing 2 red balls from a bag with 5 red, 4 green, and 3 blue balls without replacement?", "options": ["A) 5/33", "B) 5/22", "C) 1/6", "D) 5/66"], "correct_answer": "A) 5/33", "explanation": "P = (5/12) * (4/11) = 20/132 = 5/33."}
            ]},
            "round_2": {"round_num": 2, "title": "Logical Reasoning", "description": "Deductive logic", "questions": [
                {"id": "r2_q1", "question": "Find the next number in the prime square series: 4, 9, 25, 49, 121, ?", "options": ["A) 144", "B) 169", "C) 196", "D) 225"], "correct_answer": "B) 169", "explanation": "Consecutive prime squares: 13^2 = 169."},
                {"id": "r2_q2", "question": "Statements: (1) All developers write code. (2) Some code writers are architects. Conclusion: Do some developers definitely architect systems?", "options": ["A) Definitely follows", "B) Does not necessarily follow", "C) Irrelevant", "D) False premise"], "correct_answer": "B) Does not necessarily follow", "explanation": "No necessary subset overlap is guaranteed."},
                {"id": "r2_q3", "question": "Rohit says: 'She is the mother of my father's only son's wife.' How is the woman related to Rohit's wife?", "options": ["A) Sister", "B) Mother", "C) Aunt", "D) Cousin"], "correct_answer": "B) Mother", "explanation": "Father's only son is Rohit. Her mother."}
            ]},
            "round_3": {"round_num": 3, "title": "Verbal Ability", "description": "Communication precision", "questions": [
                {"id": "r3_q1", "question": "Select the grammatically correct sentence:", "options": ["A) Each of the microservices were deployed independently.", "B) Each of the microservices was deployed independently.", "C) Each of the microservices have been deployed independently.", "D) Each of the microservices are deployed independently."], "correct_answer": "B) Each of the microservices was deployed independently.", "explanation": "'Each' takes the singular verb 'was'."},
                {"id": "r3_q2", "question": "Select the word most nearly opposite in meaning to 'EPHEMERAL':", "options": ["A) Transient", "B) Perpetual", "C) Fragile", "D) Vague"], "correct_answer": "B) Perpetual", "explanation": "Perpetual means everlasting."},
                {"id": "r3_q3", "question": "Identify the idiom meaning 'to face a difficult situation with courage':", "options": ["A) Burn bridges", "B) Bite the bullet", "C) Cut corners", "D) Call it a day"], "correct_answer": "B) Bite the bullet", "explanation": "'Bite the bullet' means enduring a painful or difficult situation with resilience."}
            ]},
            "round_4": {"round_num": 4, "title": "Domain & Coding Skills", "description": "Technical logic", "questions": [
                {"id": "r4_q1", "question": "What is the worst-case time complexity of QuickSort?", "options": ["A) O(n log n)", "B) O(n^2)", "C) O(n)", "D) O(1)"], "correct_answer": "B) O(n^2)", "explanation": "Degrades to O(n^2) when poor pivots are chosen repeatedly."},
                {"id": "r4_q2", "question": "In database normalization, which normal form strictly eliminates transitive functional dependencies?", "options": ["A) First Normal Form (1NF)", "B) Second Normal Form (2NF)", "C) Third Normal Form (3NF)", "D) Boyce-Codd Normal Form (BCNF)"], "correct_answer": "C) Third Normal Form (3NF)", "explanation": "3NF removes transitive dependencies where non-prime attributes depend on non-prime attributes."},
                {"id": "r4_q3", "question": "Which data structure is optimal for implementing an LRU Cache with O(1) get and put operations?", "options": ["A) Balanced Binary Search Tree", "B) Hash Map + Doubly Linked List", "C) Stack + Priority Queue", "D) Dynamic Array"], "correct_answer": "B) Hash Map + Doubly Linked List", "explanation": "Hash Map allows O(1) key access; Doubly Linked List allows O(1) removal and node repositioning."}
            ]}
        }
        sanitized_preset = {}
        for r_key, r_val in raw_preset.items():
            r_val["questions"] = [sanitize_question_dict(q, f"{r_key}_{i}") for i, q in enumerate(r_val["questions"], 1)]
            sanitized_preset[r_key] = r_val
        return sanitized_preset


def compute_aptitude_score(rounds_data, user_answers):
    """Safely calculates scores without any possibility of KeyError on 'correct_answer'."""
    total_q = 0
    total_correct = 0
    rounds_summary = []
    all_questions_detail = []
    q_counter = 1

    if not rounds_data or not isinstance(rounds_data, dict):
        return {
            "overall_percentage": 0,
            "verdict": "Incomplete Assessment",
            "total_questions": 0,
            "total_correct": 0,
            "rounds_summary": [],
            "strengths": ["Completed assessment session."],
            "areas_for_improvement": ["Review fundamentals."],
            "all_questions_detail": [],
        }

    for r_key in ["round_1", "round_2", "round_3", "round_4"]:
        r_info = rounds_data.get(r_key, {})
        r_title = r_info.get("title", f"Round {r_key}")
        r_num = r_info.get("round_num", 1)
        r_questions = r_info.get("questions", [])

        r_correct = 0
        r_total = len(r_questions)
        for q in r_questions:
            # Safe access: Never use raw q["correct_answer"]
            q_id = q.get("id", f"{r_key}_{q_counter}")
            u_ans = user_answers.get(q_id, "Not Answered")
            c_ans = q.get("correct_answer", "")
            is_corr = is_answer_correct(u_ans, c_ans)

            if is_corr:
                r_correct += 1
                total_correct += 1
            total_q += 1

            all_questions_detail.append({
                "q_idx": q_counter,
                "round_num": r_num,
                "round_title": r_title,
                "question": q.get("question", ""),
                "options": q.get("options", []),
                "user_answer": u_ans,
                "correct_answer": c_ans,
                "is_correct": is_corr,
                "explanation": q.get("explanation", ""),
            })
            q_counter += 1

        r_pct = int(round((r_correct / r_total) * 100)) if r_total > 0 else 0
        status_label = "Strong" if r_pct >= 75 else ("Good" if r_pct >= 50 else "Needs Practice")
        rounds_summary.append({"round_num": r_num, "title": r_title, "score": r_correct, "total": r_total, "pct": r_pct, "status": status_label})

    overall_pct = int(round((total_correct / total_q) * 100)) if total_q > 0 else 0
    verdict = "Shortlist Qualified (Passed Cutoff)" if overall_pct >= 60 else "Below Recommended Cutoff"
    strengths = [f"Strong proficiency in {r['title']} ({r['pct']}% accuracy)" for r in rounds_summary if r["pct"] >= 75]
    improvements = [f"Practice speed & fundamentals in {r['title']} ({r['pct']}%)" for r in rounds_summary if r["pct"] < 60]

    return {
        "overall_percentage": overall_pct,
        "verdict": verdict,
        "total_questions": total_q,
        "total_correct": total_correct,
        "rounds_summary": rounds_summary,
        "strengths": strengths or ["Completed all four rounds."],
        "areas_for_improvement": improvements or ["Maintain high test consistency."],
        "all_questions_detail": all_questions_detail,
    }


def generate_coding_problems(role, track, client, model_name):
    """Generates 2 role-calibrated coding problems with starter templates including C, C++, Python, Java, JS, and Go."""
    system_prompt = f"""
Technical Interviewer creating 2 coding problems for {role} ({track} level).
Problem 1: Core algorithmic/data structure problem (Array/String/Hash Map).
Problem 2: Applied technical/system problem (Sliding Window/Tree/DP/Concurrency/Optimization).

Support C, C++, Python, JavaScript, Java, and Go starter codes.
Return JSON format:
{{
  "problem_1": {{
    "title": "<Title>",
    "difficulty": "Easy-Medium",
    "description": "<Clear statement>",
    "constraints": "<Constraints>",
    "example_1": {{"input": "...", "output": "...", "explanation": "..."}},
    "example_2": {{"input": "...", "output": "...", "explanation": "..."}},
    "starter_code": {{
      "C": "#include <stdio.h>\\n#include <stdlib.h>\\n\\n// Complete the function\\nint* solve(int* nums, int numsSize, int target, int* returnSize) {{\\n    *returnSize = 0;\\n    return NULL;\\n}}",
      "C++": "#include <vector>\\nusing namespace std;\\n\\nclass Solution {{\\npublic:\\n    vector<int> solve(vector<int>& nums, int target) {{\\n        return {{}};\\n    }}\\n}};",
      "Python": "def solve(nums, target):\\n    # Write your solution here\\n    pass",
      "JavaScript": "function solve(nums, target) {{\\n    // Write your solution here\\n}}",
      "Java": "public class Solution {{\\n    public int[] solve(int[] nums, int target) {{\\n        // Write code\\n        return new int[]{{}};\\n    }}\\n}}",
      "Go": "package main\\n\\nfunc solve(nums []int, target int) []int {{\\n    // Write code\\n    return nil\\n}}"
    }}
  }},
  "problem_2": {{
    "title": "<Title>",
    "difficulty": "Medium",
    "description": "<Clear statement>",
    "constraints": "<Constraints>",
    "example_1": {{"input": "...", "output": "...", "explanation": "..."}},
    "example_2": {{"input": "...", "output": "...", "explanation": "..."}},
    "starter_code": {{
      "C": "#include <stdio.h>\\n#include <string.h>\\n\\nint solveAdvanced(char* data) {{\\n    // Write your solution here\\n    return 0;\\n}}",
      "C++": "#include <string>\\nusing namespace std;\\n\\nclass Solution {{\\npublic:\\n    int solveAdvanced(string data) {{\\n        return 0;\\n    }}\\n}};",
      "Python": "def solve_advanced(data):\\n    # Write your solution here\\n    pass",
      "JavaScript": "function solveAdvanced(data) {{\\n    // Write your solution here\\n}}",
      "Java": "public class Solution {{\\n    public int solveAdvanced(String data) {{\\n        return 0;\\n    }}\\n}}",
      "Go": "package main\\n\\nfunc solveAdvanced(data string) int {{\\n    return 0\\n}}"
    }}
  }}
}}
"""
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": "Generate 2 coding problems JSON supporting C and other languages"}],
            response_format={"type": "json_object"},
            temperature=0.6,
        )
        return json.loads(response.choices[0].message.content)
    except Exception:
        return {
            "problem_1": {
                "title": "Two Sum with Target Difference",
                "difficulty": "Easy-Medium",
                "description": "Given an array of integers `nums` and an integer `k`, return indices of two numbers such that their absolute difference equals `k`.",
                "constraints": "2 <= nums.length <= 10^5, -10^9 <= nums[i] <= 10^9, 0 <= k <= 10^9",
                "example_1": {"input": "nums = [1, 5, 3, 4, 2], k = 2", "output": "[0, 2]", "explanation": "|1 - 3| = 2"},
                "example_2": {"input": "nums = [8, 12, 16], k = 4", "output": "[0, 1]", "explanation": "|8 - 12| = 4"},
                "starter_code": {
                    "C": "#include <stdio.h>\n#include <stdlib.h>\n\n/**\n * Note: The returned array must be malloced, assume caller calls free().\n */\nint* twoSumDiff(int* nums, int numsSize, int k, int* returnSize) {\n    *returnSize = 0;\n    // Write your C solution here\n    return NULL;\n}",
                    "C++": "#include <vector>\nusing namespace std;\n\nclass Solution {\npublic:\n    vector<int> twoSumDiff(vector<int>& nums, int k) {\n        return {};\n    }\n};",
                    "Python": "def two_sum_diff(nums, k):\n    # Write your solution here\n    pass",
                    "JavaScript": "function twoSumDiff(nums, k) {\n    // Write your solution here\n}",
                    "Java": "public class Solution {\n    public int[] twoSumDiff(int[] nums, int k) {\n        return new int[]{};\n    }\n}",
                    "Go": "package main\n\nfunc twoSumDiff(nums []int, k int) []int {\n    return nil\n}"
                }
            },
            "problem_2": {
                "title": "Longest Substring Without Repeating Characters",
                "difficulty": "Medium",
                "description": "Given a string `s`, find the length of the longest substring without duplicate characters.",
                "constraints": "0 <= s.length <= 5 * 10^4, `s` consists of standard ASCII characters.",
                "example_1": {"input": "s = \"abcabcbb\"", "output": "3", "explanation": "The answer is \"abc\", length 3."},
                "example_2": {"input": "s = \"pwwkew\"", "output": "3", "explanation": "The answer is \"wke\", length 3."},
                "starter_code": {
                    "C": "#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n\nint lengthOfLongestSubstring(char* s) {\n    // Write your C solution here\n    return 0;\n}",
                    "C++": "#include <string>\nusing namespace std;\n\nclass Solution {\npublic:\n    int lengthOfLongestSubstring(string s) {\n        return 0;\n    }\n};",
                    "Python": "def length_of_longest_substring(s):\n    # Write your solution here\n    pass",
                    "JavaScript": "function lengthOfLongestSubstring(s) {\n    // Write your solution here\n}",
                    "Java": "public class Solution {\n    public int lengthOfLongestSubstring(String s) {\n        return 0;\n    }\n}",
                    "Go": "package main\n\nfunc lengthOfLongestSubstring(s string) int {\n    return 0\n}"
                }
            }
        }


def evaluate_coding_solutions(problems, submissions, language, client, model_name):
    """Evaluates code for correctness, complexity, testcases, and gives scores."""
    system_prompt = f"""
You are a senior algorithmic engineering lead and technical coding interviewer.
Evaluate the candidate's code for Problem 1 and Problem 2 written in {language}.
If written in C, verify proper pointer arithmetic, memory management (malloc/free), array bounds, and syntax correctness.

For each problem:
- Score (0 to 50)
- Functional correctness & test cases passed (e.g. "Passed 10/10 test cases" or specific failure)
- Time complexity (Big-O)
- Space complexity (Big-O)
- Code quality & readability review
- Strengths and improvement advice
- Optimal reference code

Overall Coding Score = Problem 1 score + Problem 2 score (0 to 100).
Return JSON schema:
{{
  "overall_coding_score": <0-100>,
  "verdict": "<Strong Problem Solver | Proficient | Needs Optimization | Incomplete>",
  "executive_summary": "<summary>",
  "problem_1": {{
    "title": "<title>",
    "score": <0-50>,
    "correctness": "...",
    "time_complexity": "...",
    "space_complexity": "...",
    "code_quality": "...",
    "strengths": ["..."],
    "improvements": ["..."]
  }},
  "problem_2": {{
    "title": "<title>",
    "score": <0-50>,
    "correctness": "...",
    "time_complexity": "...",
    "space_complexity": "...",
    "code_quality": "...",
    "strengths": ["..."],
    "improvements": ["..."]
  }}
}}
"""
    p1 = problems.get("problem_1", {})
    p2 = problems.get("problem_2", {})
    sub1 = submissions.get("p1", "")
    sub2 = submissions.get("p2", "")

    user_prompt = f"""
Language: {language}

--- PROBLEM 1 ---
Title: {p1.get('title')}
Description: {p1.get('description')}
Candidate Code:
```
{sub1}
```

--- PROBLEM 2 ---
Title: {p2.get('title')}
Description: {p2.get('description')}
Candidate Code:
```
{sub2}
```

Evaluate both and return JSON.
"""
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_object"},
        temperature=0.3,
    )
    return json.loads(response.choices[0].message.content)


def analyze_resume_with_ats(resume_text, job_description, role_name, client, model_name):
    system_prompt = f"""
Enterprise ATS parser screening for {role_name}. Return JSON:
{{
  "overall_ats_score": <0-100>,
  "match_level": "<Needs Major Optimization (<60%) | Moderate Match (60-79%) | Strong Match (80-89%) | Fast-Track Shortlist (90-100%)>",
  "category_breakdown": {{
    "hard_skills_match": {{ "score": <0-30>, "matched_skills": ["..."], "missing_skills": ["..."] }},
    "experience_relevance": {{ "score": <0-30>, "feedback": "..." }},
    "education_and_certifications": {{ "score": <0-20>, "feedback": "..." }},
    "ats_parseability_and_impact": {{ "score": <0-20>, "feedback": "..." }}
  }},
  "critical_missing_keywords": ["..."],
  "ats_formatting_analysis": {{ "standard_sections_present": true, "contact_info_detected": true, "quantifiable_metrics_rating": "Strong" }},
  "actionable_resume_improvements": [ {{ "section": "...", "issue": "...", "recommendation": "..." }} ],
  "sample_optimized_bullets": ["..."]
}}
"""
    user_prompt = f"Resume:\n{resume_text}\nJD:\n{job_description}"
    response = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
        response_format={"type": "json_object"},
        temperature=0.4,
    )
    return json.loads(response.choices[0].message.content)


# ==============================================================================
# SIDEBAR: Resume & Profile Controls
# ==============================================================================
with st.sidebar:
    st.header("🏢 Candidate Profile")
    uploaded_file = st.file_uploader("Upload Resume (PDF)", type=["pdf"], help="Shared across all assessment rounds.")

    if uploaded_file is not None:
        if st.session_state.resume_filename != uploaded_file.name:
            st.session_state.resume_filename = uploaded_file.name
            with st.spinner("Extracting resume content..."):
                extracted_text, num_pages = extract_text_from_pdf(uploaded_file)
                if extracted_text.strip():
                    st.session_state.resume_text = extracted_text
                    st.success(f"Loaded: {uploaded_file.name} ({num_pages} pages)")
                else:
                    st.error("No readable text found in PDF.")

    st.markdown("### 🎯 Role & Track")
    common_roles = [
        "Software Engineer",
        "Full Stack Developer",
        "Backend Engineer",
        "Frontend Engineer",
        "Data Scientist / ML Engineer",
        "DevOps / Cloud Engineer",
        "Product Manager",
        "Custom Role...",
    ]
    sel_role = st.selectbox("Target Role:", common_roles, index=0)
    if sel_role == "Custom Role...":
        st.session_state.target_role = st.text_input("Enter custom job title:", value="Software Engineer")
    else:
        st.session_state.target_role = sel_role

    st.session_state.candidate_track = st.radio(
        "Candidate Experience Level:",
        ["Fresher", "Experienced"],
        format_func=lambda x: "🎓 Fresher (0-2 yrs)" if x == "Fresher" else "💼 Experienced (3+ yrs)",
    )

    st.divider()
    st.markdown("### ⚙️ System Settings")
    st.write(f"• **Interview Qs:** {TOTAL_INTERVIEW_QUESTIONS} *(In Code)*")
    st.write(f"• **Aptitude Qs:** 4 Rounds ({APTITUDE_QUESTIONS_PER_ROUND} Qs/round)")
    st.write(f"• **Coding Problems:** {CODING_PROBLEMS_COUNT} problems (C, C++, Python, Java...)")

    st.session_state.autoplay_voice = st.checkbox("🔊 Autoplay Voice", value=st.session_state.autoplay_voice)

    st.divider()
    if st.button("🏠 Return to Main Dashboard", use_container_width=True):
        st.session_state.app_mode = "dashboard"
        st.rerun()


# ==============================================================================
# VIEW 1: MAIN DASHBOARD PANEL (TWO OPTIONS)
# ==============================================================================
if st.session_state.app_mode == "dashboard":
    st.title("🏢 Enterprise Candidate Assessment Suite")
    st.caption("Comprehensive technical recruitment platform powered by AI.")

    st.markdown(
        """
        Welcome to the candidate evaluation dashboard. You can either undertake the **complete 3-stage recruitment drive**
        in a guided sequence, or practice and take **any individual round separately**.
        """
    )
    st.divider()

    col_opt1, col_opt2 = st.columns(2)

    # --- OPTION 1: COMPLETE END-TO-END HIRING DRIVE ---
    with col_opt1:
        st.markdown(
            """
            <div style="background: #F0FDF4; border: 2px solid #86EFAC; border-radius: 12px; padding: 22px; height: 100%;">
                <h3 style="color: #166534; margin-top: 0;">🚀 Option 1: Start Full Hiring Drive</h3>
                <p style="color: #15803D; font-size: 14px;"><b>Complete all 3 stages in sequence like an authentic company hiring process:</b></p>
                <ol style="color: #166534; font-size: 14px; line-height: 1.8;">
                    <li><b>Round 1:</b> 4-Round Aptitude Assessment (with live timer)</li>
                    <li><b>Round 2:</b> Technical Coding Assessment (C, C++, Python, Java, JS, Go)</li>
                    <li><b>Round 3:</b> AI Voice Interview (Resume & role deep dive)</li>
                </ol>
                <p style="color: #166534; font-size: 13px;">Generates a <b>Unified Master Scorecard (PDF)</b> with an overall hiring recommendation.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")
        if st.button("🚀 Start Full 3-Round Hiring Assessment", type="primary", use_container_width=True):
            st.session_state.app_mode = "full_drive"
            st.session_state.drive_stage = "aptitude"
            st.session_state.aptitude_status = "idle"
            st.session_state.coding_status = "idle"
            st.session_state.interview_status = "idle"
            st.rerun()

    # --- OPTION 2: TAKE INDIVIDUAL ROUND SEPARATELY ---
    with col_opt2:
        st.markdown(
            """
            <div style="background: #EFF6FF; border: 2px solid #93FD93; border-radius: 12px; padding: 22px; height: 100%;">
                <h3 style="color: #1E40AF; margin-top: 0;">🎯 Option 2: Take Individual Round Separately</h3>
                <p style="color: #1D4ED8; font-size: 14px;"><b>Select and complete any single assessment module in isolation:</b></p>
                <ul style="color: #1E40AF; font-size: 14px; line-height: 1.8;">
                    <li><b>🧠 Aptitude Round:</b> 4 rounds with per-question & total timers</li>
                    <li><b>💻 Technical Coding Round:</b> 2 coding challenges in C, C++, Python, etc.</li>
                    <li><b>🎙️ AI Voice Interview:</b> Spoken technical interview based on resume</li>
                    <li><b>🎯 Real-Time ATS Scanner:</b> Resume & job description compatibility</li>
                </ul>
                <p style="color: #1E40AF; font-size: 13px;">Generates an <b>Individual Official Scorecard (PDF)</b> for that specific round.</p>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.write("")
        chosen_module = st.selectbox(
            "Select the round you want to attempt:",
            ["🧠 4-Round Aptitude Assessment", "💻 Technical Coding Round", "🎙️ AI Voice Interviewer", "🎯 Real-Time ATS Scanner"],
            key="dash_select_module",
        )
        if st.button("➡️ Launch Selected Round", use_container_width=True):
            st.session_state.app_mode = "individual"
            if "Aptitude" in chosen_module:
                st.session_state.individual_active_round = "aptitude"
            elif "Coding" in chosen_module:
                st.session_state.individual_active_round = "coding"
            elif "Interview" in chosen_module:
                st.session_state.individual_active_round = "interview"
            else:
                st.session_state.individual_active_round = "ats"
            st.rerun()


# ==============================================================================
# VIEW 2 & 3: RENDERING ASSESSMENT MODULES
# ==============================================================================
else:
    # Top banner indicator when in Full Drive mode
    if st.session_state.app_mode == "full_drive":
        stage_names = {"aptitude": "1. Aptitude Round", "coding": "2. Coding Round", "interview": "3. Voice Interview", "master_summary": "4. Master Scorecard"}
        st.info(f"🏆 **Full Hiring Drive Active** — Currently at: **{stage_names.get(st.session_state.drive_stage, '')}** | Target: **{st.session_state.target_role}** ({st.session_state.candidate_track})")

    # In Individual mode, show modular sub-tabs
    if st.session_state.app_mode == "individual":
        col_nav1, col_nav2 = st.columns([3, 1])
        with col_nav1:
            mod_choice = st.radio(
                "Active Assessment Module:",
                ["🧠 Aptitude Round", "💻 Coding Round", "🎙️ Voice Interview", "🎯 ATS Resume Scanner"],
                horizontal=True,
                index=["aptitude", "coding", "interview", "ats"].index(st.session_state.individual_active_round),
            )
            key_map = {"🧠 Aptitude Round": "aptitude", "💻 Coding Round": "coding", "🎙️ Voice Interview": "interview", "🎯 ATS Resume Scanner": "ats"}
            st.session_state.individual_active_round = key_map[mod_choice]
        with col_nav2:
            if st.button("🏠 Dashboard", use_container_width=True):
                st.session_state.app_mode = "dashboard"
                st.rerun()

    # Determine what module to render
    show_aptitude = (st.session_state.app_mode == "full_drive" and st.session_state.drive_stage == "aptitude") or (st.session_state.app_mode == "individual" and st.session_state.individual_active_round == "aptitude")
    show_coding = (st.session_state.app_mode == "full_drive" and st.session_state.drive_stage == "coding") or (st.session_state.app_mode == "individual" and st.session_state.individual_active_round == "coding")
    show_interview = (st.session_state.app_mode == "full_drive" and st.session_state.drive_stage == "interview") or (st.session_state.app_mode == "individual" and st.session_state.individual_active_round == "interview")
    show_ats = (st.session_state.app_mode == "individual" and st.session_state.individual_active_round == "ats")
    show_master = (st.session_state.app_mode == "full_drive" and st.session_state.drive_stage == "master_summary")


    # --------------------------------------------------------------------------
    # MODULE: 🧠 APTITUDE ASSESSMENT (WITH TIMER & STRICT CLEAN QUESTIONS)
    # --------------------------------------------------------------------------
    if show_aptitude:
        st.title("🧠 4-Round Aptitude Assessment")
        st.caption("Standard pre-interview screening: Quantitative Ability, Logical Reasoning, Verbal Communication, and Domain/Coding Skills.")

        if st.session_state.aptitude_status == "idle":
            st.markdown(
                f"""
                #### Assessment Structure:
                - **Total Rounds:** 4 progressive rounds ({APTITUDE_QUESTIONS_PER_ROUND} questions per round, total {APTITUDE_QUESTIONS_PER_ROUND * 4} questions).
                - **Exam Timer:** Per-question recommended time (~{APTITUDE_SEC_PER_QUESTION}s) and live countdown timer per round.
                - **Rounds Covered:**
                  1. Quantitative Aptitude & Numerical Ability
                  2. Logical Reasoning & Critical Thinking
                  3. Verbal Ability & Workplace Communication
                  4. Role-Specific Technical & Coding Concepts for **{st.session_state.target_role}**
                """
            )
            if st.button("🚀 Start Aptitude Test", type="primary", use_container_width=True):
                with st.spinner("Generating role-specific questions across all 4 rounds via Groq AI..."):
                    st.session_state.aptitude_rounds_data = generate_aptitude_rounds_data(
                        role=st.session_state.target_role,
                        track=st.session_state.candidate_track,
                        client=groq_client,
                        model_name=GROQ_MODEL,
                    )
                    st.session_state.aptitude_status = "in_progress"
                    st.session_state.aptitude_current_round = 1
                    st.session_state.aptitude_user_answers = {}
                    st.session_state.aptitude_final_report = None
                    st.session_state.aptitude_round_start_time = time.time()
                st.rerun()

        elif st.session_state.aptitude_status == "in_progress":
            curr_r = st.session_state.aptitude_current_round
            r_key = f"round_{curr_r}"
            r_info = st.session_state.aptitude_rounds_data.get(r_key, {})
            r_title = r_info.get("title", f"Round {curr_r}")
            r_desc = r_info.get("description", "")
            r_questions = r_info.get("questions", [])

            # Dynamic timer calculation based on number of questions in round
            round_allocated_sec = len(r_questions) * APTITUDE_SEC_PER_QUESTION

            col_prog, col_meta = st.columns([3, 1])
            with col_prog:
                st.progress((curr_r - 1) / 4, text=f"Round {curr_r} of 4: {r_title}")
            with col_meta:
                st.write(f"⏱️ Total Round Time: **{round_allocated_sec // 60}m {round_allocated_sec % 60}s**")

            # Render Live Countdown Timer safely without deprecation warnings
            render_countdown_timer(total_seconds=round_allocated_sec, label=f"Round {curr_r} Countdown ({r_title})")

            st.subheader(f"Round {curr_r}: {r_title}")
            st.caption(r_desc)
            st.divider()

            with st.form(key=f"apt_round_{curr_r}_form"):
                for idx, q in enumerate(r_questions, start=1):
                    q_id = q.get("id", f"{r_key}_q{idx}")
                    q_text = q.get("question", f"Question {idx}")
                    opts = q.get("options", ["A) Option A", "B) Option B", "C) Option C", "D) Option D"])

                    # Display clean question ONLY - no leaked answer or explanation
                    st.markdown(f"#### Q{idx}. {q_text}")

                    curr_saved = st.session_state.aptitude_user_answers.get(q_id, None)
                    def_idx = opts.index(curr_saved) if curr_saved in opts else None

                    selected = st.radio(
                        f"Select your answer for Question {idx}:",
                        options=opts,
                        index=def_idx,
                        key=f"radio_{q_id}",
                        label_visibility="collapsed",
                    )
                    st.session_state.aptitude_user_answers[q_id] = selected
                    st.markdown("---")

                btn_label = f"Submit Round {curr_r} & Proceed to Round {curr_r + 1} ➡️" if curr_r < 4 else "🏁 Submit Final Round & Complete Aptitude"
                submitted = st.form_submit_button(btn_label, type="primary", use_container_width=True)

                if submitted:
                    if curr_r < 4:
                        st.session_state.aptitude_current_round += 1
                        st.session_state.aptitude_round_start_time = time.time()
                    else:
                        st.session_state.aptitude_status = "completed"
                    st.rerun()

        elif st.session_state.aptitude_status == "completed":
            st.balloons()
            st.success("🎉 You have completed all 4 rounds of the Aptitude Assessment!")

            if st.session_state.aptitude_final_report is None:
                report = compute_aptitude_score(st.session_state.aptitude_rounds_data, st.session_state.aptitude_user_answers)
                st.session_state.aptitude_final_report = report

            apt_rep = st.session_state.aptitude_final_report

            col_s1, col_s2, col_s3, col_s4 = st.columns(4)
            with col_s1:
                st.metric("Overall Score", f"{apt_rep['overall_percentage']}%")
            with col_s2:
                st.metric("Questions Correct", f"{apt_rep['total_correct']} / {apt_rep['total_questions']}")
            with col_s3:
                st.metric("Cutoff Verdict", apt_rep["verdict"])
            with col_s4:
                st.metric("Level", st.session_state.candidate_track)

            st.progress(apt_rep["overall_percentage"] / 100)
            st.divider()

            st.subheader("📈 Round-by-Round Breakdown")
            r_cols = st.columns(4)
            for i, r in enumerate(apt_rep["rounds_summary"]):
                with r_cols[i]:
                    st.markdown(f"**Round {r['round_num']}**")
                    st.caption(r["title"])
                    st.metric(f"Score ({r['status']})", f"{r['score']} / {r['total']}", f"{r['pct']}%")

            st.divider()
            col_str, col_imp = st.columns(2)
            with col_str:
                st.markdown("### 🌟 Strengths")
                for s in apt_rep["strengths"]:
                    st.markdown(f"- ✅ **{s}**")
            with col_imp:
                st.markdown("### 🎯 Areas to Improve")
                for imp in apt_rep["areas_for_improvement"]:
                    st.markdown(f"- 💡 **{imp}**")

            st.divider()
            st.subheader("📝 Complete Question Solution Key & Explanations")
            st.caption("Review the correct answers and detailed explanations after submitting your assessment.")
            for q_item in apt_rep.get("all_questions_detail", []):
                status_icon = "✅" if q_item["is_correct"] else "❌"
                header_text = f"{status_icon} Q{q_item['q_idx']} [{q_item['round_title']}]: {q_item['question'][:80]}..."
                with st.expander(header_text):
                    st.markdown(f"**Question:** {q_item['question']}")
                    for opt in q_item.get("options", []):
                        if opt == q_item["correct_answer"]:
                            st.markdown(f"- **{opt}** *(Correct Key)*")
                        elif opt == q_item["user_answer"] and not q_item["is_correct"]:
                            st.markdown(f"- *{opt}* ❌ *(Your Choice)*")
                        else:
                            st.markdown(f"- {opt}")

                    st.markdown(f"**Your Answer:** `{q_item['user_answer']}`")
                    st.markdown(f"**Correct Answer:** `{q_item['correct_answer']}`")
                    st.info(f"**Explanation:** {q_item.get('explanation', '')}")

            st.divider()
            st.subheader("📥 Export Aptitude Scorecard (PDF)")
            apt_pdf = generate_aptitude_scorecard_pdf(
                apt_data=apt_rep,
                candidate_name=st.session_state.resume_filename or "Candidate",
                role=st.session_state.target_role,
                track=st.session_state.candidate_track,
            )
            st.download_button(
                label="📥 Download Aptitude Scorecard (PDF)",
                data=apt_pdf,
                file_name=f"Aptitude_Scorecard_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
            )

            # If in Full Drive mode, give button to proceed to Coding Round
            if st.session_state.app_mode == "full_drive":
                st.divider()
                if st.button("🚀 Proceed to Round 2: Technical Coding Round ➡️", type="primary", use_container_width=True):
                    st.session_state.drive_stage = "coding"
                    st.session_state.coding_status = "idle"
                    st.rerun()


    # --------------------------------------------------------------------------
    # MODULE: 💻 TECHNICAL CODING ROUND (2 PROBLEMS WITH C, C++, PYTHON, ETC.)
    # --------------------------------------------------------------------------
    elif show_coding:
        st.title("💻 Technical Coding Assessment")
        st.caption(f"Write, test, and submit solutions for {CODING_PROBLEMS_COUNT} technical coding challenges.")

        if st.session_state.coding_status == "idle":
            st.markdown(
                f"""
                #### Coding Round Overview:
                - **Number of Problems:** {CODING_PROBLEMS_COUNT} problems calibrated for a **{st.session_state.candidate_track} {st.session_state.target_role}**.
                - **Supported Languages:** Select your preferred language: **C**, **C++**, **Python**, **Java**, **JavaScript**, **Go**.
                - **Automated Judge:** Evaluates functional correctness, test cases, time complexity (Big-O), space complexity, memory management, and clean code standards.
                """
            )
            if st.button("🚀 Start Coding Round", type="primary", use_container_width=True):
                with st.spinner("Generating technical coding problems and starter templates via Groq AI..."):
                    st.session_state.coding_problems = generate_coding_problems(
                        role=st.session_state.target_role,
                        track=st.session_state.candidate_track,
                        client=groq_client,
                        model_name=GROQ_MODEL,
                    )
                    st.session_state.coding_status = "in_progress"
                    st.session_state.coding_final_report = None
                st.rerun()

        elif st.session_state.coding_status == "in_progress":
            problems = st.session_state.coding_problems
            p1 = problems.get("problem_1", {})
            p2 = problems.get("problem_2", {})

            col_lang, col_reset, col_time = st.columns([2, 1, 1])
            with col_lang:
                avail_languages = ["C", "C++", "Python", "Java", "JavaScript", "Go"]
                curr_lang = st.session_state.coding_language if st.session_state.coding_language in avail_languages else "C"
                selected_lang = st.selectbox(
                    "Choose Programming Language:",
                    avail_languages,
                    index=avail_languages.index(curr_lang),
                    key="coding_lang_select_box",
                )
                if selected_lang != st.session_state.coding_language:
                    st.session_state.coding_language = selected_lang
                    # Update starter templates for selected language if submissions are empty or matched template
                    st.session_state.coding_submissions["p1"] = p1.get("starter_code", {}).get(selected_lang, "// Write solution here\n")
                    st.session_state.coding_submissions["p2"] = p2.get("starter_code", {}).get(selected_lang, "// Write solution here\n")
                    st.rerun()

            lang = st.session_state.coding_language

            with col_reset:
                if st.button(f"🔄 Reset to {lang} Boilerplate", use_container_width=True):
                    st.session_state.coding_submissions["p1"] = p1.get("starter_code", {}).get(lang, f"// Write {lang} solution here\n")
                    st.session_state.coding_submissions["p2"] = p2.get("starter_code", {}).get(lang, f"// Write {lang} solution here\n")
                    st.rerun()

            with col_time:
                st.info(f"Active: **{lang}**")

            tab_p1, tab_p2 = st.tabs(["📝 Problem 1", "📝 Problem 2"])

            # --- PROBLEM 1 TAB ---
            with tab_p1:
                st.subheader(f"Problem 1: {p1.get('title', 'Algorithmic Problem')}")
                st.caption(f"Difficulty: {p1.get('difficulty', 'Medium')}")
                st.markdown(p1.get("description", ""))
                st.markdown(f"**Constraints:** `{p1.get('constraints', '')}`")

                ex1 = p1.get("example_1", {})
                ex2 = p1.get("example_2", {})
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    st.markdown("**Example 1:**")
                    st.code(f"Input: {ex1.get('input')}\nOutput: {ex1.get('output')}\nExplanation: {ex1.get('explanation')}", language="text")
                with col_e2:
                    st.markdown("**Example 2:**")
                    st.code(f"Input: {ex2.get('input')}\nOutput: {ex2.get('output')}\nExplanation: {ex2.get('explanation')}", language="text")

                starter1 = p1.get("starter_code", {}).get(lang, "// Write code here\n")
                if not st.session_state.coding_submissions.get("p1"):
                    st.session_state.coding_submissions["p1"] = starter1

                st.session_state.coding_submissions["p1"] = st.text_area(
                    f"Write your solution for Problem 1 ({lang}):",
                    value=st.session_state.coding_submissions["p1"],
                    height=280,
                    key=f"code_editor_p1_{lang}",
                )

            # --- PROBLEM 2 TAB ---
            with tab_p2:
                st.subheader(f"Problem 2: {p2.get('title', 'Applied Technical Challenge')}")
                st.caption(f"Difficulty: {p2.get('difficulty', 'Medium-Hard')}")
                st.markdown(p2.get("description", ""))
                st.markdown(f"**Constraints:** `{p2.get('constraints', '')}`")

                ex1 = p2.get("example_1", {})
                ex2 = p2.get("example_2", {})
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    st.markdown("**Example 1:**")
                    st.code(f"Input: {ex1.get('input')}\nOutput: {ex1.get('output')}\nExplanation: {ex1.get('explanation')}", language="text")
                with col_e2:
                    st.markdown("**Example 2:**")
                    st.code(f"Input: {ex2.get('input')}\nOutput: {ex2.get('output')}\nExplanation: {ex2.get('explanation')}", language="text")

                starter2 = p2.get("starter_code", {}).get(lang, "// Write code here\n")
                if not st.session_state.coding_submissions.get("p2"):
                    st.session_state.coding_submissions["p2"] = starter2

                st.session_state.coding_submissions["p2"] = st.text_area(
                    f"Write your solution for Problem 2 ({lang}):",
                    value=st.session_state.coding_submissions["p2"],
                    height=280,
                    key=f"code_editor_p2_{lang}",
                )

            st.divider()
            if st.button("🚀 Submit Solutions for Automated Code Review & Scoring", type="primary", use_container_width=True):
                with st.spinner(f"Automated judge is compiling and evaluating {lang} solutions, test cases, and time/space complexity..."):
                    eval_res = evaluate_coding_solutions(
                        problems=st.session_state.coding_problems,
                        submissions=st.session_state.coding_submissions,
                        language=st.session_state.coding_language,
                        client=groq_client,
                        model_name=GROQ_MODEL,
                    )
                    st.session_state.coding_final_report = eval_res
                    st.session_state.coding_status = "completed"
                st.rerun()

        elif st.session_state.coding_status == "completed":
            st.balloons()
            st.success("🎉 Technical Coding Assessment Submitted & Evaluated!")

            rep = st.session_state.coding_final_report
            score = rep.get("overall_coding_score", 0)
            verdict = rep.get("verdict", "Evaluated")
            p1_res = rep.get("problem_1", {})
            p2_res = rep.get("problem_2", {})

            col_c1, col_c2, col_c3 = st.columns([1, 1, 2])
            with col_c1:
                st.metric("Total Coding Score", f"{score} / 100")
            with col_c2:
                st.metric("Verdict", verdict)
            with col_c3:
                st.info(f"**Executive Review:** {rep.get('executive_summary', '')}")

            st.progress(score / 100)
            st.divider()

            col_p1_card, col_p2_card = st.columns(2)
            with col_p1_card:
                st.subheader(f"Problem 1: {p1_res.get('title', 'Problem 1')}")
                st.metric("Score", f"{p1_res.get('score', 0)} / 50")
                st.markdown(f"**Test Cases:** {p1_res.get('correctness')}")
                st.markdown(f"**Time Complexity:** `{p1_res.get('time_complexity')}`")
                st.markdown(f"**Space Complexity:** `{p1_res.get('space_complexity')}`")
                st.markdown(f"**Quality Review:** {p1_res.get('code_quality')}")

            with col_p2_card:
                st.subheader(f"Problem 2: {p2_res.get('title', 'Problem 2')}")
                st.metric("Score", f"{p2_res.get('score', 0)} / 50")
                st.markdown(f"**Test Cases:** {p2_res.get('correctness')}")
                st.markdown(f"**Time Complexity:** `{p2_res.get('time_complexity')}`")
                st.markdown(f"**Space Complexity:** `{p2_res.get('space_complexity')}`")
                st.markdown(f"**Quality Review:** {p2_res.get('code_quality')}")

            st.divider()
            st.subheader("📥 Export Coding Scorecard (PDF)")
            coding_pdf = generate_coding_scorecard_pdf(
                coding_report=rep,
                candidate_name=st.session_state.resume_filename or "Candidate",
                role=st.session_state.target_role,
                track=st.session_state.candidate_track,
                language=st.session_state.coding_language,
            )
            st.download_button(
                label="📥 Download Coding Scorecard (PDF)",
                data=coding_pdf,
                file_name=f"Coding_Scorecard_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
            )

            # If in Full Drive mode, give button to proceed to Interview Round
            if st.session_state.app_mode == "full_drive":
                st.divider()
                if st.button("🚀 Proceed to Round 3: AI Voice Interview ➡️", type="primary", use_container_width=True):
                    st.session_state.drive_stage = "interview"
                    st.session_state.interview_status = "idle"
                    st.rerun()


    # --------------------------------------------------------------------------
    # MODULE: 🎙️ AI VOICE INTERVIEWER
    # --------------------------------------------------------------------------
    elif show_interview:
        st.title("🎙️ AI Voice Interviewer")
        st.caption(f"Authentic, voice-first mock interview powered by your resume and Groq AI ({TOTAL_INTERVIEW_QUESTIONS} questions).")

        if st.session_state.interview_status == "idle":
            if not st.session_state.resume_text:
                st.info("👈 Please upload your resume (PDF) in the sidebar to begin your interview.")
            else:
                st.success(f"Resume ready: **{st.session_state.resume_filename}**")
                st.write(f"Conducting a {TOTAL_INTERVIEW_QUESTIONS}-question voice interview for **{st.session_state.target_role}** ({st.session_state.candidate_track} track).")
                if st.button("🚀 Start Voice Interview", type="primary", use_container_width=True):
                    with st.spinner("The interviewer is preparing Question 1..."):
                        first_q = generate_first_question(st.session_state.resume_text, st.session_state.candidate_track, st.session_state.target_role, groq_client, GROQ_MODEL)
                        first_audio = text_to_speech(first_q)
                        st.session_state.interview_status = "in_progress"
                        st.session_state.current_question_index = 1
                        st.session_state.current_question = first_q
                        st.session_state.current_audio = first_audio
                        st.session_state.conversation_history.append({"role": "interviewer", "text": first_q, "audio": first_audio})
                    st.rerun()

        elif st.session_state.interview_status == "in_progress":
            q_idx = st.session_state.current_question_index
            st.progress(q_idx / TOTAL_INTERVIEW_QUESTIONS, text=f"Question {q_idx} of {TOTAL_INTERVIEW_QUESTIONS}")

            for i, msg in enumerate(st.session_state.conversation_history):
                is_latest = i == len(st.session_state.conversation_history) - 1
                if msg["role"] == "interviewer":
                    with st.chat_message("assistant", avatar="🧑‍💼"):
                        st.markdown(msg["text"])
                        if msg.get("audio"):
                            should_autoplay = is_latest and st.session_state.autoplay_voice
                            st.audio(msg["audio"], format="audio/mp3", autoplay=should_autoplay)
                else:
                    with st.chat_message("user", avatar="🎙️"):
                        st.markdown(f"**Your Answer:** {msg['text']}")

            st.divider()
            st.subheader(f"🎙️ Speak Your Answer for Question {q_idx}")
            user_audio = st.audio_input(f"Record answer for Question {q_idx}", key=f"audio_q_{q_idx}")

            if user_audio is not None:
                with st.spinner("Transcribing spoken response via Whisper..."):
                    transcribed = transcribe_audio(user_audio, groq_client)

                if not transcribed or len(transcribed.strip()) < 3:
                    st.warning("⚠️ Could not clearly hear your answer. Please record again.")
                else:
                    st.session_state.conversation_history.append({"role": "candidate", "text": transcribed})
                    with st.spinner("Interviewer is evaluating your response..."):
                        prev_qs = [item["question"] for item in st.session_state.evaluations]
                        score, feedback, next_spoken = evaluate_and_ask_next(
                            resume_text=st.session_state.resume_text,
                            question_num=q_idx,
                            current_q=st.session_state.current_question,
                            candidate_answer=transcribed,
                            prev_questions=prev_qs,
                            track=st.session_state.candidate_track,
                            role=st.session_state.target_role,
                            client=groq_client,
                            model_name=GROQ_MODEL,
                        )
                        st.session_state.evaluations.append({"q_num": q_idx, "question": st.session_state.current_question, "answer": transcribed, "score": score, "feedback": feedback})
                        next_audio = text_to_speech(next_spoken)
                        st.session_state.conversation_history.append({"role": "interviewer", "text": next_spoken, "audio": next_audio})

                        if q_idx < TOTAL_INTERVIEW_QUESTIONS:
                            st.session_state.current_question_index += 1
                            st.session_state.current_question = next_spoken
                            st.session_state.current_audio = next_audio
                        else:
                            st.session_state.interview_status = "completed"
                    st.rerun()

        elif st.session_state.interview_status == "completed":
            st.balloons()
            st.success(f"🎉 Completed all {TOTAL_INTERVIEW_QUESTIONS} interview questions!")

            if st.session_state.final_report is None:
                with st.spinner("Generating performance scorecard..."):
                    st.session_state.final_report = generate_final_summary_report(
                        st.session_state.resume_text, st.session_state.evaluations, st.session_state.candidate_track, st.session_state.target_role, groq_client, GROQ_MODEL
                    )

            rep = st.session_state.final_report
            score = rep.get("overall_score", 0)

            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                st.metric("Interview Score", f"{score} / 100")
            with col2:
                st.metric("Rating", rep.get("performance_rating", "Evaluated"))
            with col3:
                st.info(f"**Appraisal:** {rep.get('executive_summary', '')}")

            st.divider()
            st.subheader("📥 Export Interview Scorecard (PDF)")
            iv_pdf = generate_interview_scorecard_pdf(
                evaluations=st.session_state.evaluations,
                report=rep,
                resume_name=st.session_state.resume_filename,
                track=st.session_state.candidate_track,
                role=st.session_state.target_role,
            )
            st.download_button(
                label="📥 Download Scorecard (PDF)",
                data=iv_pdf,
                file_name=f"Interview_Scorecard_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
                mime="application/pdf",
                type="primary",
            )

            # If in Full Drive mode, give button to see the Master Final Result
            if st.session_state.app_mode == "full_drive":
                st.divider()
                if st.button("🏆 View Unified Master Hiring Report ➡️", type="primary", use_container_width=True):
                    st.session_state.drive_stage = "master_summary"
                    st.rerun()


    # --------------------------------------------------------------------------
    # MODULE: 🎯 REAL-TIME ATS SCANNER
    # --------------------------------------------------------------------------
    elif show_ats:
        st.title("🎯 Real-Time ATS Resume Scanner")
        st.caption("How actual corporate Applicant Tracking Systems (Workday, Taleo, Greenhouse) screen your resume.")

        ats_res_text = st.session_state.resume_text
        if not ats_res_text:
            st.warning("Please upload a resume in the sidebar to scan against a Job Description.")
        else:
            st.success(f"Resume: **{st.session_state.resume_filename}**")
            jd_input = st.text_area("Paste Job Description:", height=200)

            if st.button("🔍 Run Real-Time ATS Compatibility Scan", type="primary", disabled=not jd_input.strip()):
                with st.spinner("Analyzing keyword density, requirements, and ATS parseability..."):
                    st.session_state.ats_result = analyze_resume_with_ats(ats_res_text, jd_input, st.session_state.target_role, groq_client, GROQ_MODEL)
                st.rerun()

            if st.session_state.ats_result:
                ats_d = st.session_state.ats_result
                st.divider()
                st.metric("ATS Match Score", f"{ats_d.get('overall_ats_score', 0)}%")
                st.progress(ats_d.get("overall_ats_score", 0) / 100)

                col_k1, col_k2 = st.columns(2)
                with col_k1:
                    st.markdown("### ✅ Matched Skills")
                    for m in ats_d.get("category_breakdown", {}).get("hard_skills_match", {}).get("matched_skills", []):
                        st.markdown(f"- 🟢 {m}")
                with col_k2:
                    st.markdown("### ⚠️ Missing Keywords")
                    for miss in ats_d.get("critical_missing_keywords", []):
                        st.markdown(f"- 🔴 {miss}")

                st.divider()
                ats_pdf = generate_ats_scorecard_pdf(ats_d, st.session_state.resume_filename, st.session_state.target_role)
                st.download_button("📥 Download ATS Report (PDF)", data=ats_pdf, file_name="ATS_Report.pdf", mime="application/pdf", type="primary")


    # --------------------------------------------------------------------------
    # FULL DRIVE STAGE 4: UNIFIED MASTER SCORECARD
    # --------------------------------------------------------------------------
    elif show_master:
        st.balloons()
        st.title("🏆 Complete Recruitment Drive — Final Hiring Scorecard")
        st.caption(f"Comprehensive multi-stage evaluation for **{st.session_state.target_role}** ({st.session_state.candidate_track}).")

        apt_data = st.session_state.aptitude_final_report or {}
        coding_data = st.session_state.coding_final_report or {}
        interview_data = st.session_state.final_report or {}

        apt_pct = apt_data.get("overall_percentage", 0)
        cod_pct = coding_data.get("overall_coding_score", 0)
        int_pct = interview_data.get("overall_score", 0)

        composite_score = int(round((apt_pct * 0.25) + (cod_pct * 0.35) + (int_pct * 0.40)))
        hiring_verdict = "RECOMMENDED FOR HIRE (Strong Candidate)" if composite_score >= 75 else ("PASSED HIRING CUTOFF" if composite_score >= 60 else "NEEDS ADDITIONAL DEVELOPMENT")

        col_m1, col_m2, col_m3, col_m4 = st.columns(4)
        with col_m1:
            st.metric("Round 1: Aptitude (25%)", f"{apt_pct}%")
        with col_m2:
            st.metric("Round 2: Coding (35%)", f"{cod_pct} / 100")
        with col_m3:
            st.metric("Round 3: Interview (40%)", f"{int_pct} / 100")
        with col_m4:
            st.metric("Composite Hiring Score", f"{composite_score} / 100")

        st.progress(composite_score / 100)
        st.success(f"**Final Recruitment Verdict:** {hiring_verdict}")

        st.divider()
        st.subheader("📥 Download Official Unified Master Scorecard (PDF)")
        st.caption("Official report consolidating Aptitude, Technical Coding, and Voice Interview results.")

        master_pdf = generate_master_scorecard_pdf(
            candidate_name=st.session_state.resume_filename or "Candidate",
            role=st.session_state.target_role,
            track=st.session_state.candidate_track,
            apt_data=apt_data,
            coding_data=coding_data,
            interview_data=interview_data,
        )

        st.download_button(
            label="📥 Download Master Scorecard (PDF)",
            data=master_pdf,
            file_name=f"Master_Recruitment_Report_{datetime.datetime.now().strftime('%Y%m%d')}.pdf",
            mime="application/pdf",
            type="primary",
        )

        st.divider()
        if st.button("🔄 Start Another Assessment", use_container_width=True):
            st.session_state.app_mode = "dashboard"
            st.rerun()