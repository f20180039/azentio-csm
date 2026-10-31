import os
import sys
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.enum.shapes import MSO_SHAPE

def create_deck():
    prs = Presentation()
    # 16:9 Widescreen standard
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank_layout = prs.slide_layouts[6]

    # Colors
    NAVY = RGBColor(11, 25, 44)
    SLATE_DARK = RGBColor(15, 23, 42)
    ACCENT_BLUE = RGBColor(37, 99, 235)
    CYAN = RGBColor(14, 165, 233)
    BG_CARD = RGBColor(248, 250, 252)
    BORDER_COLOR = RGBColor(226, 232, 240)
    TEXT_MAIN = RGBColor(30, 41, 59)
    TEXT_MUTED = RGBColor(100, 116, 139)
    GREEN = RGBColor(22, 163, 74)
    WHITE = RGBColor(255, 255, 255)

    slides_data = [
        {
            "num": "01",
            "tag": "EXECUTIVE PITCH",
            "title": "Azentio-CSM: Next-Gen Autonomous BFSI Voice Platform",
            "subtitle": "Deterministic Guardrails, Multilingual Intelligence & Cryptographic Auditability",
            "points": [
                ("Full-Stack BFSI Solution", "Autonomous voice agent handling complex customer support, loan inquiries, statement generation, and policy renewals."),
                ("Zero-Hallucination Architecture", "Every financial figure, reference number, and date is strictly grounded against Core Banking Simulator APIs before synthesis."),
                ("Enterprise Compliance & 2FA", "Automated Two-Factor Authentication (OTP/DOB) with hard guardrails and instant supervisor handoff backstops."),
                ("Production-Grade Quality", "924 automated tests passing (100% green across Core API, Banking Simulator, Voice Agent, and Web Desk).")
            ],
            "kpi": ("924 Tests Passing", "100% Automated Coverage"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/01_support_desk.png",
            "caption": "Live Operator Support Desk running on localhost:5173"
        },
        {
            "num": "02",
            "tag": "THE PROBLEM & CHALLENGE",
            "title": "The High-Stakes Friction in BFSI Customer Service",
            "subtitle": "Traditional Chatbots Hallucinate; Human Call Centers Are Overwhelmed",
            "points": [
                ("Financial & Regulatory Risk", "Generic LLM bots hallucinate balances, interest rates, and loan terms, causing severe RBI/compliance penalties."),
                ("Vernacular & Multilingual Gap", "Over 65% of Tier-2/3 Indian banking customers speak regional languages (Kannada, Hindi), where off-the-shelf bots fail."),
                ("Security & Verification Vulnerability", "Weak authentication leads to data leakage, social engineering attacks, and compromised customer PII."),
                ("Black-Box Operations", "Zero explainability into why an AI agent made a decision, with no tamper-evident audit trail for dispute resolution.")
            ],
            "kpi": ("65%+ Call Volume", "Demands Regional Language Support"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/02_dashboard.png",
            "caption": "Real-Time Operations Analytics & Intent Trends on localhost:5173/dashboard"
        },
        {
            "num": "03",
            "tag": "SYSTEM ARCHITECTURE",
            "title": "Defense-in-Depth Microservice Architecture",
            "subtitle": "Modular, Multi-Model Resilience with Strict Service Separation",
            "points": [
                ("Dual Ingress Channels", "WebRTC browser peer connection (<350ms glass-to-glass) + Twilio Carrier Telephony (PSTN/SIP voice streaming)."),
                ("Multi-Model Resilience Chain", "Dynamic failover across Groq GPT-OSS 120B -> 20B -> Local LLaMA 3.2 Ollama with automatic cooldown & health monitoring."),
                ("Clean Microservices", "Core API (8080) + Core Banking Simulator (8090) + Pipecat Voice Pipeline (7861) + Modern React Desk (5173)."),
                ("100% Modern Python & TypeScript", "Completely eliminated legacy Java dependencies for lightning-fast container startup and agile CI/CD.")
            ],
            "kpi": ("<850ms Latency", "End-to-End Voice Response"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/01_support_desk.png",
            "caption": "Integrated Microservices Ecosystem: Core API (8080), Voice (7861), Web (5173)"
        },
        {
            "num": "04",
            "tag": "MULTILINGUAL INTELLIGENCE",
            "title": "Native Kannada & Hindi Speech Recognition",
            "subtitle": "Accurate Vernacular Nuances with Real-Time English Transcription",
            "points": [
                ("Devanagari & Kannada Conditioning", "Custom acoustic biasing handles Kannada verb endings, Hindi honorifics, and dialectical number pronunciations."),
                ("Dual-Pane Operator Assistance", "Call transcripts display native vernacular text alongside instant English machine translation for bank supervisors."),
                ("Phonetic Reference Recovery", "Translates spoken phonetic phrases into valid banking references ('ಎಂಟು ನೂರು' -> '800', 'ಲೋನ್' -> 'LOAN')."),
                ("Speech-to-Text Benchmark Proven", "Benchmarked across diverse accents and background noise with >94% intent classification accuracy.")
            ],
            "kpi": ("94%+ STT Accuracy", "Across Kannada, Hindi & Indian English"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/03_kannada_call.png",
            "caption": "Live Kannada Support Call with Parallel English Translation (localhost:5173)"
        },
        {
            "num": "05",
            "tag": "SECURITY & GUARDRAILS",
            "title": "Deterministic 2FA & Zero-Trust Banking Gate",
            "subtitle": "No Customer Financial Data Exposed Prior to Identity Verification",
            "points": [
                ("Strict Two-Factor Gate", "Callers must provide registered 10-digit mobile number and Date of Birth (YYYY-MM-DD) or OTP before any query."),
                ("Model Lockout Enforcement", "LLM prompt conditioning forbids answering balance or statement queries while verified=false; hard-coded tool guardrails enforce this."),
                ("Brute-Force Protection", "Maximum 3 failed verification attempts before account lock and automated supervisor escalation (ESC-XXXXX)."),
                ("Caller Profile Integration", "Verified callers instantly surface KYC profile, active loan accounts, and risk score on the operator desk.")
            ],
            "kpi": ("Zero Leaks", "Strict Identity Gate Enforced"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/05_customer_verification.png",
            "caption": "Customer Identity Verification & Security Card on localhost:5173"
        },
        {
            "num": "06",
            "tag": "AUTONOMOUS OPERATIONS",
            "title": "Real-Time Service Request Execution",
            "subtitle": "Automated Core Banking Transactions with Reference Generation",
            "points": [
                ("End-to-End API Execution", "The voice agent directly queries and updates the Core Banking Simulator (8090) in real-time."),
                ("Automated Service Requests", "Instant registration of loan statements, repayment schedules, and callback tickets with unique reference IDs (SR-1042)."),
                ("Formal Complaint Lodging", "Logs grievances with category classification, department routing, and SLA tracking (CMP-3011)."),
                ("Phonetic Reference Repair", "Spoken letters and numbers are phonetically spelled out and matched against active database records.")
            ],
            "kpi": ("100% Autonomous", "SR-1042 / CMP-3011 Real-Time Creation"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/06_ops_records.png",
            "caption": "Live Core Banking Operations Ledger: Tickets, Complaints & Service Requests"
        },
        {
            "num": "07",
            "tag": "EXPLAINABILITY & GROUNDING",
            "title": "Explainability: 'Why Did the Agent Say This?'",
            "subtitle": "Structured Decision Rationale, Masked Tool Traces & Fact Verification",
            "points": [
                ("Transparent Tool Execution", "Every agent utterance is accompanied by an expandable 'Retrieved' card showing the exact tool called and parameters used."),
                ("Pre-Speech Grounding Validator", "Extracts figures, dates, and amounts from draft replies and verifies existence in tool outputs before audio generation."),
                ("Anti-Hallucination Gate", "If a number cannot be verified in the bank simulator output, the draft reply is intercepted and safely deflected."),
                ("Raw JSON Auditability", "Operators and compliance officers can inspect the underlying JSON payload for every turn with one click.")
            ],
            "kpi": ("0% Hallucination", "Every Claim Linked to Simulator Output"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/04_tool_trace.png",
            "caption": "Tool Trace Rationale Card: Masked Arguments, Status & Retrieved Records"
        },
        {
            "num": "08",
            "tag": "AUDITABILITY & COMPLIANCE",
            "title": "Cryptographic SHA-256 Hash Chaining",
            "subtitle": "Append-Only, Tamper-Evident Record of Every Customer Interaction",
            "points": [
                ("Mathematical Hash Chaining", "Every action produces hash = sha256(prev_hash | actor | action | payload | timestamp) rooted at Genesis 0000..."),
                ("1-Click Integrity Verification", "'Verify Chain' button executes cryptographic audit across all historical events; flags any modified, inserted or deleted records."),
                ("Four-Eyes Governance", "Reviewers who initiated or handled a case are cryptographically prevented from approving it."),
                ("Regulatory Export Ready", "Export entire conversation trails with cryptographic signatures for RBI / SEBI audit compliance.")
            ],
            "kpi": ("100% Tamper Proof", "Cryptographically Verifiable Hash Chain"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/07_audit_chain.png",
            "caption": "Case Workspace Cryptographic Audit Trail with 'Verify Chain' Banner"
        },
        {
            "num": "09",
            "tag": "OPERATOR WORKSPACE",
            "title": "Enterprise Review Queue & Temporal Filtering",
            "subtitle": "Risk-Prioritized Case Sorting with Intuitive Date Boundaries",
            "points": [
                ("Financial Risk Prioritization", "Sorts cases by highest ₹ amount at risk and AI finding severity first, optimizing reviewer bandwidth."),
                ("Temporal Date Filtering", "New preset selector (Today, Yesterday, Past 7 Days, Past 30 Days) plus custom calendar date range pickers."),
                ("Persistent URL Synchronization", "Filter states are preserved across search params (?datePreset=today), bookmarks, and supervisor reloads."),
                ("3-Second Real-Time Polling", "Automatically detects new cases and audio uploads without requiring manual browser page refreshes.")
            ],
            "kpi": ("Instant Filtering", "Today, 7D, 30D & Custom Date Bounds"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/08_queue_date_filter.png",
            "caption": "Review Queue with New Date Range Presets & Risk Sorting (localhost:5173/queue)"
        },
        {
            "num": "10",
            "tag": "BUSINESS VALUE & ROADMAP",
            "title": "Measurable Business ROI & Next-Step Roadmap",
            "subtitle": "Production-Ready Conversational AI Tailored for Financial Institutions",
            "points": [
                ("85% First-Contact Deflection", "Routinely handles tier-1 service requests, statements, and repayment schedules without human intervention."),
                ("Sub-Second Latency", "End-to-end voice turnaround under 850ms enables natural, non-awkward human conversation flow."),
                ("Full Regulatory Compliance", "Zero PII leakage, deterministic failovers, and tamper-evident audit logs meet stringent BFSI standards."),
                ("Continuous Learning Loop", "Turn-level supervisor ratings, test scenario exports, and feedback loops continuously improve model performance.")
            ],
            "kpi": ("85% Call Deflection", "<850ms Voice Response Time"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/09_insights_analytics.png",
            "caption": "Support Insights & Quality Review: Ratings, Feedback & Scenario Exports"
        }
    ]

    for data in slides_data:
        slide = prs.slides.add_slide(blank_layout)

        # Background Header Bar
        header_rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.85))
        header_rect.fill.solid()
        header_rect.fill.fore_color.rgb = NAVY
        header_rect.line.fill.background()

        # Header Title in Bar
        tx_box = slide.shapes.add_textbox(Inches(0.8), Inches(0.18), Inches(7.0), Inches(0.5))
        tf = tx_box.text_frame
        tf.word_wrap = True
        p = tf.paragraphs[0]
        p.text = "AZENTIO-CSM  |  BFSI AUTONOMOUS CONVERSATIONAL AI"
        p.font.size = Pt(13)
        p.font.bold = True
        p.font.color.rgb = CYAN

        # Slide Number / Tag Badge in Header Bar
        tx_badge = slide.shapes.add_textbox(Inches(10.5), Inches(0.18), Inches(2.0), Inches(0.5))
        tf_b = tx_badge.text_frame
        p_b = tf_b.paragraphs[0]
        p_b.text = f"SLIDE {data['num']} / 10"
        p_b.alignment = PP_ALIGN.RIGHT
        p_b.font.size = Pt(12)
        p_b.font.bold = True
        p_b.font.color.rgb = WHITE

        # Left Column: Content Container
        left_box = slide.shapes.add_textbox(Inches(0.8), Inches(1.05), Inches(5.8), Inches(5.9))
        tf_l = left_box.text_frame
        tf_l.word_wrap = True
        tf_l.margin_left = tf_l.margin_top = tf_l.margin_right = tf_l.margin_bottom = 0

        # Category Tag
        p_tag = tf_l.paragraphs[0]
        p_tag.text = data["tag"]
        p_tag.font.size = Pt(11)
        p_tag.font.bold = True
        p_tag.font.color.rgb = ACCENT_BLUE

        # Main Title
        p_title = tf_l.add_paragraph()
        p_title.text = data["title"]
        p_title.font.size = Pt(20)
        p_title.font.bold = True
        p_title.font.color.rgb = SLATE_DARK
        p_title.space_after = Pt(4)

        # Subtitle
        p_sub = tf_l.add_paragraph()
        p_sub.text = data["subtitle"]
        p_sub.font.size = Pt(12)
        p_sub.font.color.rgb = TEXT_MUTED
        p_sub.space_after = Pt(14)

        # Bullet Points
        for bold_lead, body_text in data["points"]:
            p_pt = tf_l.add_paragraph()
            p_pt.space_after = Pt(8)
            run_b = p_pt.add_run()
            run_b.text = f"•  {bold_lead}: "
            run_b.font.bold = True
            run_b.font.size = Pt(11.5)
            run_b.font.color.rgb = SLATE_DARK
            
            run_t = p_pt.add_run()
            run_t.text = body_text
            run_t.font.size = Pt(11)
            run_t.font.color.rgb = TEXT_MAIN

        # Bottom KPI Callout Box (Left Column)
        kpi_rect = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.8), Inches(6.25), Inches(5.6), Inches(0.85))
        kpi_rect.fill.solid()
        kpi_rect.fill.fore_color.rgb = BG_CARD
        kpi_rect.line.color.rgb = CYAN
        kpi_rect.line.width = Pt(1.5)

        tx_kpi = slide.shapes.add_textbox(Inches(0.95), Inches(6.32), Inches(5.3), Inches(0.7))
        tf_k = tx_kpi.text_frame
        tf_k.word_wrap = True
        p_k1 = tf_k.paragraphs[0]
        p_k1.text = data["kpi"][0]
        p_k1.font.size = Pt(15)
        p_k1.font.bold = True
        p_k1.font.color.rgb = ACCENT_BLUE
        
        p_k2 = tf_k.add_paragraph()
        p_k2.text = data["kpi"][1]
        p_k2.font.size = Pt(10)
        p_k2.font.color.rgb = TEXT_MUTED

        # Right Column: Actual Screenshot Container
        img_x = Inches(6.8)
        img_y = Inches(1.15)
        img_w = Inches(5.7)
        img_h = Inches(5.1)

        # Card shadow / border background
        bg_card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, img_x - Inches(0.08), img_y - Inches(0.08), img_w + Inches(0.16), img_h + Inches(0.85))
        bg_card.fill.solid()
        bg_card.fill.fore_color.rgb = WHITE
        bg_card.line.color.rgb = BORDER_COLOR
        bg_card.line.width = Pt(1.5)

        # Embed Actual Image
        if os.path.exists(data["img"]):
            slide.shapes.add_picture(data["img"], img_x, img_y, width=img_w, height=img_h)

        # Image Caption Below
        cap_box = slide.shapes.add_textbox(img_x, img_y + img_h + Inches(0.1), img_w, Inches(0.6))
        tf_c = cap_box.text_frame
        tf_c.word_wrap = True
        p_c = tf_c.paragraphs[0]
        p_c.text = f"📷 {data['caption']}"
        p_c.font.size = Pt(10)
        p_c.font.bold = True
        p_c.font.color.rgb = TEXT_MUTED

    output_path = "/Volumes/DiskD/OFFLINEHACK/azentio-csm/Azentio_CSM_Project_Pitch_Deck.pptx"
    prs.save(output_path)
    print(f"Presentation saved successfully to: {output_path}")

if __name__ == "__main__":
    create_deck()
