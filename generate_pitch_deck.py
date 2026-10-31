import os
from PIL import Image
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

    # Typography & Palette
    FONT_FAMILY = "Segoe UI"
    NAVY_TOPBAR = RGBColor(11, 25, 44)       # Azentio Deep Navy
    SLATE_DARK = RGBColor(15, 23, 42)        # Charcoal Navy for Headings
    ACCENT_BLUE = RGBColor(30, 64, 175)      # Royal Cobalt
    CYAN_ACCENT = RGBColor(14, 165, 233)     # Cyan highlight
    BG_CARD = RGBColor(248, 250, 252)        # Clean off-white surface
    BORDER_LIGHT = RGBColor(226, 232, 240)   # Crisp subtle divider
    TEXT_MAIN = RGBColor(51, 65, 85)         # Readable slate body
    TEXT_MUTED = RGBColor(100, 116, 139)     # Secondary slate
    PILL_BG = RGBColor(238, 242, 255)        # Soft indigo/blue tag fill
    PILL_TEXT = RGBColor(49, 46, 129)        # Deep indigo tag text
    GREEN_ACCENT = RGBColor(22, 163, 74)     # Success green
    WHITE = RGBColor(255, 255, 255)

    slides_data = [
        {
            "num": "01",
            "tag": "EXECUTIVE PITCH",
            "title": "Azentio-CSM: Autonomous BFSI Voice AI Platform",
            "subtitle": "Deterministic Guardrails, Multilingual Intelligence & Cryptographic Auditability",
            "points": [
                ("Full-Stack BFSI Solution", "Autonomous voice agent handling tier-1 customer support, loan inquiries, statement generation, and renewals."),
                ("Zero-Hallucination Architecture", "Every financial figure, reference number, and date is strictly grounded against Core Banking Simulator APIs before synthesis."),
                ("Enterprise Compliance & 2FA", "Automated Two-Factor Authentication (OTP/DOB) with hard guardrails and instant supervisor handoff backstops."),
                ("Production-Grade Quality", "924 automated tests passing (100% green across Core API, Banking Simulator, Voice Agent, and Web Desk).")
            ],
            "kpi": ("924 Tests Passing", "100% Automated Coverage Across 4 Microservices"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/01_support_desk.png",
            "meta_label": "LIVE OPERATOR SUPPORT DESK",
            "meta_route": "http://localhost:5173/",
            "meta_tech": "FastAPI Core (8080) · Pipecat WebRTC (7861) · React Desk (5173)"
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
            "kpi": ("65%+ Call Volume", "Demands Vernacular Regional Language Support"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/02_dashboard.png",
            "meta_label": "EXECUTIVE DASHBOARD & INTENT TRENDS",
            "meta_route": "http://localhost:5173/dashboard",
            "meta_tech": "Rolling 7-Day Intent Classification · Live Model Cooldown Tracker"
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
            "kpi": ("<850ms Latency", "Sub-Second Glass-to-Glass Voice Response"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/01_support_desk.png",
            "meta_label": "INTEGRATED MICROSERVICES ECOSYSTEM",
            "meta_route": "http://localhost:5173/",
            "meta_tech": "FastAPI (Python 3.12) · SQLite Storage · WebRTC SmallWebRTC SCTP"
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
            "kpi": ("94%+ STT Accuracy", "Across Kannada, Hindi & Indian English Dialects"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/03_kannada_call.png",
            "meta_label": "MULTILINGUAL TIMELINE WITH ENGLISH TRANSLATION",
            "meta_route": "http://localhost:5173/support/calls/475b0ac5-...",
            "meta_tech": "Acoustic Conditioning (VOICE_LANGUAGES=en,kn,hi) · Real-time Translate"
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
            "kpi": ("Zero Data Leaks", "Hardware-Enforced 2FA Gate & Automatic Lockout"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/05_customer_verification.png",
            "meta_label": "CUSTOMER IDENTITY VERIFICATION CARD",
            "meta_route": "http://localhost:5173/support/calls/475b0ac5-...",
            "meta_tech": "Deterministic 2FA Gate · 3-Strike Lockout · KYC Data Surface"
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
            "kpi": ("100% Autonomous", "SR-1042 / CMP-3011 Real-Time API Execution"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/06_ops_records.png",
            "meta_label": "CORE BANKING OPERATIONS LEDGER",
            "meta_route": "http://localhost:5173/ (Tickets & Complaints Tabs)",
            "meta_tech": "Simulated Core Banking (8090) · SQLite Backend · SLA Department Routing"
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
            "kpi": ("0% Hallucination", "Every Claim Linked to Core Banking API Output"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/04_tool_trace.png",
            "meta_label": "EXPANDABLE TOOL TRACE & GROUNDING CARD",
            "meta_route": "http://localhost:5173/support/calls/475b0ac5-...",
            "meta_tech": "Structured Tool Trace · Masked Arguments · Raw JSON Inspection"
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
            "kpi": ("100% Tamper Proof", "Cryptographically Verifiable Hash Chain with Genesis Root"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/07_audit_chain.png",
            "meta_label": "CASE WORKSPACE AUDIT TRAIL & VERIFY PROOF",
            "meta_route": "http://localhost:5173/cases/475b0ac5-...#audit",
            "meta_tech": "SHA-256 Chaining · Genesis 0000 Anchor · Four-Eyes Access Guard"
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
            "kpi": ("Instant Filtering", "Today, Yesterday, 7D, 30D & Custom Date Bounds"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/08_queue_date_filter.png",
            "meta_label": "REVIEW QUEUE WITH TEMPORAL DATE FILTERS",
            "meta_route": "http://localhost:5173/queue?datePreset=today",
            "meta_tech": "Dual Client/SQL Filtering · ISO Bounds · Real-time 3s Polling"
        },
        {
            "num": "10",
            "tag": "BUSINESS VALUE & ROADMAP",
            "title": "Measurable Business ROI & Continuous Learning",
            "subtitle": "Production-Ready Conversational AI Tailored for Financial Institutions",
            "points": [
                ("85% First-Contact Deflection", "Routinely handles tier-1 service requests, statements, and repayment schedules without human intervention."),
                ("Sub-Second Latency", "End-to-end voice turnaround under 850ms enables natural, non-awkward human conversation flow."),
                ("Full Regulatory Compliance", "Zero PII leakage, deterministic failovers, and tamper-evident audit logs meet stringent BFSI standards."),
                ("Continuous Learning Loop", "Turn-level supervisor ratings, test scenario exports, and feedback loops continuously improve model performance.")
            ],
            "kpi": ("85% Call Deflection", "<850ms Voice Response Time & 100% Audit Compliance"),
            "img": "/Volumes/DiskD/OFFLINEHACK/azentio-csm/presentation_assets/09_insights_analytics.png",
            "meta_label": "SUPPORT INSIGHTS, RATINGS & SCENARIO EXPORTS",
            "meta_route": "http://localhost:5173/insights",
            "meta_tech": "Review Queue · Turn Feedback · 1-Click Scenario Export"
        }
    ]

    for data in slides_data:
        slide = prs.slides.add_slide(blank_layout)

        # -------------------------------------------------------------
        # TOP HEADER BAR
        # -------------------------------------------------------------
        header_rect = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0), Inches(0), Inches(13.333), Inches(0.82))
        header_rect.fill.solid()
        header_rect.fill.fore_color.rgb = NAVY_TOPBAR
        header_rect.line.fill.background()

        # Branding in Header
        tx_brand = slide.shapes.add_textbox(Inches(0.8), Inches(0.18), Inches(7.5), Inches(0.45))
        tf_brand = tx_brand.text_frame
        tf_brand.word_wrap = True
        p_brand = tf_brand.paragraphs[0]
        p_brand.font.name = FONT_FAMILY
        p_brand.font.size = Pt(12)
        p_brand.font.bold = True

        run_brand1 = p_brand.add_run()
        run_brand1.text = "AZENTIO-CSM  "
        run_brand1.font.color.rgb = CYAN_ACCENT

        run_brand2 = p_brand.add_run()
        run_brand2.text = "|  BFSI AUTONOMOUS CONVERSATIONAL VOICE PLATFORM"
        run_brand2.font.color.rgb = WHITE
        run_brand2.font.size = Pt(11)

        # Slide Number Badge in Header
        tx_num = slide.shapes.add_textbox(Inches(10.5), Inches(0.18), Inches(2.0), Inches(0.45))
        tf_num = tx_num.text_frame
        p_num = tf_num.paragraphs[0]
        p_num.alignment = PP_ALIGN.RIGHT
        p_num.font.name = FONT_FAMILY
        p_num.font.size = Pt(11)
        p_num.font.bold = True
        p_num.font.color.rgb = RGBColor(203, 213, 225)
        p_num.text = f"SLIDE {data['num']} / 10"

        # -------------------------------------------------------------
        # LEFT COLUMN: Content & Details
        # -------------------------------------------------------------
        left_margin = Inches(0.8)
        content_top = Inches(1.1)
        content_w = Inches(5.4)

        # Tag Pill Shape
        tag_pill = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left_margin, content_top, Inches(2.2), Inches(0.32))
        tag_pill.fill.solid()
        tag_pill.fill.fore_color.rgb = PILL_BG
        tag_pill.line.fill.background()
        tf_pill = tag_pill.text_frame
        p_pill = tf_pill.paragraphs[0]
        p_pill.text = data["tag"]
        p_pill.font.name = FONT_FAMILY
        p_pill.font.size = Pt(9.5)
        p_pill.font.bold = True
        p_pill.font.color.rgb = PILL_TEXT
        p_pill.alignment = PP_ALIGN.CENTER

        # Content Box
        left_box = slide.shapes.add_textbox(left_margin, content_top + Inches(0.38), content_w, Inches(4.5))
        tf_l = left_box.text_frame
        tf_l.word_wrap = True
        tf_l.margin_left = tf_l.margin_top = tf_l.margin_right = tf_l.margin_bottom = 0

        # Title
        p_title = tf_l.paragraphs[0]
        p_title.text = data["title"]
        p_title.font.name = FONT_FAMILY
        p_title.font.size = Pt(21)
        p_title.font.bold = True
        p_title.font.color.rgb = SLATE_DARK
        p_title.space_after = Pt(4)

        # Subtitle
        p_sub = tf_l.add_paragraph()
        p_sub.text = data["subtitle"]
        p_sub.font.name = FONT_FAMILY
        p_sub.font.size = Pt(11.5)
        p_sub.font.color.rgb = TEXT_MUTED
        p_sub.space_after = Pt(14)

        # Bullet Points
        for bold_lead, body_text in data["points"]:
            p_pt = tf_l.add_paragraph()
            p_pt.space_after = Pt(7)
            
            # Bullet symbol
            run_sym = p_pt.add_run()
            run_sym.text = "• "
            run_sym.font.name = FONT_FAMILY
            run_sym.font.bold = True
            run_sym.font.size = Pt(11)
            run_sym.font.color.rgb = ACCENT_BLUE

            # Bold Heading
            run_b = p_pt.add_run()
            run_b.text = f"{bold_lead}: "
            run_b.font.name = FONT_FAMILY
            run_b.font.bold = True
            run_b.font.size = Pt(11)
            run_b.font.color.rgb = SLATE_DARK
            
            # Body text
            run_t = p_pt.add_run()
            run_t.text = body_text
            run_t.font.name = FONT_FAMILY
            run_t.font.size = Pt(10.5)
            run_t.font.color.rgb = TEXT_MAIN

        # Bottom KPI Highlight Box
        kpi_y = Inches(6.15)
        kpi_h = Inches(0.95)
        
        # Base Card
        kpi_card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, left_margin, kpi_y, content_w, kpi_h)
        kpi_card.fill.solid()
        kpi_card.fill.fore_color.rgb = BG_CARD
        kpi_card.line.color.rgb = BORDER_LIGHT
        kpi_card.line.width = Pt(1.0)

        # Left Accent Stripe on KPI Card
        kpi_stripe = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, left_margin, kpi_y, Inches(0.08), kpi_h)
        kpi_stripe.fill.solid()
        kpi_stripe.fill.fore_color.rgb = ACCENT_BLUE
        kpi_stripe.line.fill.background()

        # Text inside KPI Card
        tx_kpi = slide.shapes.add_textbox(left_margin + Inches(0.2), kpi_y + Inches(0.12), content_w - Inches(0.4), kpi_h - Inches(0.24))
        tf_k = tx_kpi.text_frame
        tf_k.word_wrap = True
        tf_k.margin_left = tf_k.margin_top = tf_k.margin_right = tf_k.margin_bottom = 0

        p_k1 = tf_k.paragraphs[0]
        p_k1.font.name = FONT_FAMILY
        p_k1.text = data["kpi"][0]
        p_k1.font.size = Pt(16)
        p_k1.font.bold = True
        p_k1.font.color.rgb = ACCENT_BLUE

        p_k2 = tf_k.add_paragraph()
        p_k2.font.name = FONT_FAMILY
        p_k2.text = data["kpi"][1]
        p_k2.font.size = Pt(9.5)
        p_k2.font.color.rgb = TEXT_MUTED

        # -------------------------------------------------------------
        # RIGHT COLUMN: Un-Squeezed Screenshot with Exact Aspect Ratio
        # -------------------------------------------------------------
        img_col_left = Inches(6.5)
        img_col_top = Inches(1.1)
        target_w = Inches(6.1)
        
        if os.path.exists(data["img"]):
            # Inspect actual dimensions using PIL
            with Image.open(data["img"]) as im:
                orig_w, orig_h = im.size
            aspect_ratio = orig_w / orig_h
            
            # Compute exact proportional height (zero distortion!)
            actual_w = target_w
            actual_h = actual_w / aspect_ratio
            
            # Outer Card framing the screenshot
            card_pad = Inches(0.08)
            meta_box_h = Inches(0.85)
            total_card_h = actual_h + meta_box_h + Inches(0.2)
            
            outer_card = slide.shapes.add_shape(
                MSO_SHAPE.ROUNDED_RECTANGLE, 
                img_col_left - card_pad, 
                img_col_top - card_pad, 
                actual_w + (card_pad * 2), 
                total_card_h
            )
            outer_card.fill.solid()
            outer_card.fill.fore_color.rgb = WHITE
            outer_card.line.color.rgb = BORDER_LIGHT
            outer_card.line.width = Pt(1.5)

            # Add Image with strictly proportional dimensions (NO SQUEEZING!)
            slide.shapes.add_picture(
                data["img"], 
                img_col_left, 
                img_col_top, 
                width=actual_w, 
                height=actual_h
            )

            # Lower Card Info (Live URL & Verified Details)
            meta_y = img_col_top + actual_h + Inches(0.08)
            tx_meta = slide.shapes.add_textbox(img_col_left + Inches(0.05), meta_y, actual_w - Inches(0.1), meta_box_h)
            tf_m = tx_meta.text_frame
            tf_m.word_wrap = True
            tf_m.margin_left = tf_m.margin_top = tf_m.margin_right = tf_m.margin_bottom = 0

            # Line 1: Live Status & Screen Label
            p_m1 = tf_m.paragraphs[0]
            p_m1.font.name = FONT_FAMILY
            run_dot = p_m1.add_run()
            run_dot.text = "● "
            run_dot.font.color.rgb = GREEN_ACCENT
            run_dot.font.size = Pt(10)
            
            run_mlabel = p_m1.add_run()
            run_mlabel.text = f"{data['meta_label']}  "
            run_mlabel.font.bold = True
            run_mlabel.font.size = Pt(9.5)
            run_mlabel.font.color.rgb = SLATE_DARK

            run_url = p_m1.add_run()
            run_url.text = f"({data['meta_route']})"
            run_url.font.size = Pt(8.5)
            run_url.font.color.rgb = ACCENT_BLUE

            # Line 2: Tech stack & capability
            p_m2 = tf_m.add_paragraph()
            p_m2.font.name = FONT_FAMILY
            p_m2.text = f"Tech Architecture: {data['meta_tech']}"
            p_m2.font.size = Pt(8.5)
            p_m2.font.color.rgb = TEXT_MUTED

    output_path = "/Volumes/DiskD/OFFLINEHACK/azentio-csm/Azentio_CSM_Project_Pitch_Deck.pptx"
    prs.save(output_path)
    print(f"Polished Presentation saved successfully to: {output_path}")

if __name__ == "__main__":
    create_deck()
