import streamlit as st
import pandas as pd
import requests
import urllib.parse
from datetime import datetime
import time
import shutil
import tempfile
import os
import base64
import json
from pathlib import Path
import anthropic
import ast 
from fpdf import FPDF 

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# Add library for readability analysis (Cognitive Accessibility)
try:
    import textstat
except ImportError:
    textstat = None

# --- CONFIGURATION ---
st.set_page_config(page_title="Lyreco Accessibility Monitor", layout="wide")

# Custom CSS for Lyreco Branding
st.markdown("""
    <style>
    div.stButton > button:first-child {
        background-color: #2D2E87;
        color: white;
        border-radius: 5px;
        border: none;
    }
    div.stButton > button:hover {
        background-color: #1a1b5e;
        color: white;
    }
    </style>
""", unsafe_allow_html=True)

# Load secrets
try:
    GOOGLE_KEY = st.secrets["GOOGLE_KEY"]
    WAVE_KEY = st.secrets["WAVE_KEY"]
    CLAUDE_KEY = st.secrets["CLAUDE_KEY"]
except KeyError:
    st.error("⚠️ Missing API keys. Please add GOOGLE_KEY, WAVE_KEY, and CLAUDE_KEY to Streamlit Secrets.")
    st.stop()

client = anthropic.Anthropic(api_key=CLAUDE_KEY)

# --- DATA & MAPPING ---
AXE_TO_WCAG = {
    "color-contrast": {"name": "SC 1.4.3 (Contrast Minimum)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html"},
    "image-alt": {"name": "SC 1.1.1 (Non-text Content)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/non-text-content.html"},
    "label": {"name": "SC 3.3.2 (Labels or Instructions)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/labels-or-instructions.html"},
    "button-name": {"name": "SC 4.1.2 (Name, Role, Value)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html"},
    "link-name": {"name": "SC 2.4.4 (Link Purpose)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/link-purpose-in-context.html"},
    "html-has-lang": {"name": "SC 3.1.1 (Language of Page)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/language-of-page.html"},
    "document-title": {"name": "SC 2.4.2 (Page Titled)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/page-titled.html"},
    "frame-title": {"name": "SC 2.4.1 (Bypass Blocks)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/bypass-blocks.html"},
    "list": {"name": "SC 1.3.1 (Info and Relationships)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/info-and-relationships.html"},
    "aria-allowed-attr": {"name": "SC 4.1.2 (Name, Role, Value)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/name-role-value.html"},
    "accesskeys": {"name": "SC 2.1.1 (Keyboard)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html"},
    "target-size": {"name": "SC 2.5.8 (Target Size Minimum)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html"},
    "focus-appearance": {"name": "SC 2.4.13 (Focus Appearance)", "url": "https://www.w3.org/WAI/WCAG22/Understanding/focus-appearance.html"}
}

COUNTRIES = {
    "France": {
        "home": "https://shop.lyreco.fr/fr",
        "category": "https://shop.lyreco.fr/fr/list/001001/papier-et-enveloppes/papier-blanc",
        "product": "https://shop.lyreco.fr/fr/product/157.796/papier-blanc-a4-lyreco-multi-purpose-80-g-ramette-500-feuilles",
    },
    "UK": {
        "home": "https://shop.lyreco.co.uk/",
        "category": "https://shop.lyreco.co.uk/en/list/001001/paper-envelopes/white-office-paper",
        "product": "https://shop.lyreco.co.uk/en/product/159.543/lyreco-white-a4-80gsm-copier-paper-box-of-5-reams-5x500-sheets-of-paper",
    },
    "Ireland": {
        "home": "https://www.lyreco.ie/en",
        "category": "https://www.lyreco.ie/en/list/001001001/paper-envelopes/white-office-paper/paper-a4-size",
        "product": "https://www.lyreco.ie/en/product/159.543/lyreco-white-a4-80gsm-copier-paper-box-of-5-reams-5x500-sheets-of-paper",
    },
    "Poland": {
        "home": "https://shop.lyreco.pl/pl",
        "category": "https://shop.lyreco.pl/pl/list/001001/papier-i-koperty/papiery-biale-uniwersalne",
        "product": "https://shop.lyreco.pl/pl/product/159.543/papier-do-drukarki-lyreco-copy-a4-80-g-m-5-ryz-po-500-arkuszy",
    }
}
SSO_LOGIN = "https://welcome.lyreco.com/lyreco-customers/login"

# --- IMAGE ENCODING ---
def encode_image(image_path):
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")

# --- PDF GENERATOR ---
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, 'Lyreco Accessibility Audit', 0, 1, 'R')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, label):
        self.set_font('Arial', 'B', 16)
        self.set_text_color(45, 46, 135) # Lyreco Blue
        self.cell(0, 10, label, 0, 1, 'L')
        self.ln(4)

    def chapter_body(self, text):
        self.set_font('Arial', '', 11)
        self.set_text_color(0)
        self.multi_cell(0, 6, text)
        self.ln()

def generate_w3c_pdf(df):
    pdf = PDFReport()
    pdf.add_page()
    
    logo_path = "lyreco_logo.png"
    try:
        if not os.path.exists(logo_path):
            img_data = requests.get("https://cdn-s1.lyreco.com/staticswebshop/pictures/looknfeel/FRFR/logo.png").content
            with open(logo_path, 'wb') as handler:
                handler.write(img_data)
        pdf.image(logo_path, x=10, y=8, w=40)
    except Exception:
        pass # Ignore logo loading failure silently
    
    pdf.ln(20)
    pdf.set_font('Arial', 'B', 24)
    pdf.cell(0, 15, "Accessibility Evaluation Report", 0, 1, 'L')
    
    pdf.set_font('Arial', '', 12)
    pdf.cell(0, 8, f"Date: {datetime.now().strftime('%B %d, %Y')}", 0, 1, 'L')
    pdf.cell(0, 8, f"Auditor: Lyreco Automated Agent", 0, 1, 'L')
    pdf.ln(10)

    pdf.chapter_title("1. Executive Summary")
    avg_score = df['Score'].mean()
    verdict = "Non-Compliant"
    if avg_score >= 90: verdict = "Excellent Compliance"
    elif avg_score >= 80: verdict = "Good Compliance"
    elif avg_score >= 60: verdict = "Partial Compliance"
    
    tab_sum = int(df.get('Tab_Issues_Count', pd.Series([0]*len(df))).sum())
    adv_sum = int(df.get('Advanced_Issues_Count', pd.Series([0]*len(df))).sum())
    
    summary_text = (
        f"This report presents the results of an automated accessibility evaluation of the Lyreco e-commerce platform. "
        f"The overall score is {avg_score:.1f}/100 ('{verdict}'). "
        f"Found {int(df['Critical'].sum())} critical blockers, {tab_sum} keyboard navigation barriers, and {adv_sum} advanced technology compliance issues."
    )
    pdf.chapter_body(summary_text)

    pdf.chapter_title("2. Scope of Evaluation")
    pdf.set_font('Arial', 'B', 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(30, 10, "Market", 1, 0, 'C', 1)
    pdf.cell(30, 10, "Page Type", 1, 0, 'C', 1)
    pdf.cell(30, 10, "Viewport", 1, 0, 'C', 1)
    pdf.cell(100, 10, "URL (Truncated)", 1, 1, 'C', 1)
    
    pdf.set_font('Arial', '', 9)
    for _, row in df.iterrows():
        pdf.cell(30, 8, row['Country'], 1)
        pdf.cell(30, 8, row['Type'].capitalize(), 1)
        pdf.cell(30, 8, str(row.get('Viewport', 'desktop')).capitalize(), 1)
        short_url = (row['URL'][:50] + '...') if len(row['URL']) > 50 else row['URL']
        pdf.cell(100, 8, short_url, 1, 1)
    pdf.ln(10)

    pdf.chapter_title("3. Detailed Findings")
    for _, row in df.iterrows():
        violations = row["Violations"]
        if isinstance(violations, str):
            try: violations = ast.literal_eval(violations)
            except: violations = []
            
        tab_issues = row.get("Tab_Issues_Details", "[]")
        if isinstance(tab_issues, str):
            try: tab_issues = ast.literal_eval(tab_issues)
            except: tab_issues = []

        adv_issues = row.get("Advanced_Issues_Details", "[]")
        if isinstance(adv_issues, str):
            try: adv_issues = ast.literal_eval(adv_issues)
            except: adv_issues = []
        
        serious_violations = [v for v in violations if v.get('impact') in ['critical', 'serious']]
        
        if serious_violations or tab_issues or adv_issues:
            pdf.set_font('Arial', 'B', 11)
            pdf.set_text_color(45, 46, 135)
            pdf.cell(0, 10, f"{row['Country']} - {row['Type'].capitalize()} [{row.get('Viewport', 'desktop')}] (Score: {row['Score']})", 0, 1)
            
            pdf.set_font('Arial', 'B', 9)
            pdf.set_text_color(0)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(25, 8, "Impact", 1, 0, 'C', 1)
            pdf.cell(50, 8, "Issue ID / Type", 1, 0, 'C', 1)
            pdf.cell(115, 8, "Description", 1, 1, 'C', 1)
            
            pdf.set_font('Arial', '', 8)
            
            # Tab / Keyboard Navigation issues
            for t_issue in tab_issues:
                pdf.set_text_color(200, 0, 0)
                pdf.cell(25, 8, "CRITICAL", 1, 0, 'C')
                pdf.set_text_color(0)
                pdf.cell(50, 8, "keyboard-nav-trap", 1, 0)
                desc = (t_issue.get("desc", str(t_issue))[:65] + '..') if len(t_issue.get("desc", str(t_issue))) > 65 else t_issue.get("desc", str(t_issue))
                pdf.cell(115, 8, desc, 1, 1)
            
            # Advanced Tech Issues (Target Size, Dragon, Zoomtext)
            for a_issue in adv_issues:
                pdf.set_text_color(200, 0, 0)
                pdf.cell(25, 8, "CRITICAL", 1, 0, 'C')
                pdf.set_text_color(0)
                pdf.cell(50, 8, a_issue.get("type", "advanced"), 1, 0)
                desc = (a_issue.get("desc", "")[:65] + '..') if len(a_issue.get("desc", "")) > 65 else a_issue.get("desc", "")
                pdf.cell(115, 8, desc, 1, 1)

            # Axe Core issues
            for v in serious_violations:
                impact = v.get('impact', 'minor').upper()
                if impact == 'CRITICAL':
                    pdf.set_text_color(200, 0, 0)
                else:
                    pdf.set_text_color(0)
                pdf.cell(25, 8, impact, 1, 0, 'C')
                pdf.set_text_color(0)
                pdf.cell(50, 8, v['id'], 1, 0)
                desc = (v['help'][:65] + '..') if len(v['help']) > 65 else v['help']
                pdf.cell(115, 8, desc, 1, 1)
            pdf.ln(5)
            
    return pdf.output(dest='S').encode('latin-1', 'replace')

def generate_accessibility_statement_pdf(df):
    pdf = PDFReport()
    pdf.add_page()
    
    pdf.ln(10)
    pdf.set_font('Arial', 'B', 24)
    pdf.cell(0, 15, "Accessibility Statement", 0, 1, 'L')
    pdf.ln(5)

    pdf.set_font('Arial', '', 11)
    pdf.multi_cell(0, 6, "Lyreco is committed to ensuring digital accessibility for people with disabilities. We are continually improving the user experience for everyone, and applying the relevant accessibility standards.")
    pdf.ln(5)

    pdf.chapter_title("Conformance Status")
    pdf.chapter_body("The Web Content Accessibility Guidelines (WCAG) defines requirements for designers and developers to improve accessibility for people with disabilities. Based on automated audits, the platform is Partially Conformant with WCAG 2.2 level AA.")
    
    pdf.chapter_title("Assessment Approach")
    pdf.chapter_body("Lyreco assessed the accessibility by the following approaches:")
    pdf.cell(0, 6, "- Automated evaluation (Axe, WAVE, Lighthouse, W3C Nu).", 0, 1)
    pdf.cell(0, 6, "- AI Vision-Language Model heuristic analysis.", 0, 1)
    pdf.cell(0, 6, "- Automated Keyboard Navigation simulation.", 0, 1)
    pdf.cell(0, 6, "- Advanced Technology Emulation (Dragon, JAWS, ZoomText).", 0, 1)
    pdf.ln(5)

    pdf.chapter_title("Identified Limitations")
    total_critical = int(df['Critical'].sum())
    total_serious = int(df['Serious'].sum())
    total_tab = int(df.get('Tab_Issues_Count', pd.Series([0]*len(df))).sum())
    total_adv = int(df.get('Advanced_Issues_Count', pd.Series([0]*len(df))).sum())
    
    pdf.set_font('Arial', 'B', 11)
    pdf.cell(0, 6, f"Metrics (Date: {datetime.now().strftime('%Y-%m-%d')}):", 0, 1)
    pdf.set_font('Arial', '', 11)
    pdf.cell(0, 6, f"- Critical Access Blockers: {total_critical}", 0, 1)
    pdf.cell(0, 6, f"- Serious Accessibility Issues: {total_serious}", 0, 1)
    pdf.cell(0, 6, f"- Keyboard Navigation Barriers: {total_tab}", 0, 1)
    pdf.cell(0, 6, f"- Screen Reader / Voice / Magnification Issues: {total_adv}", 0, 1)

    return pdf.output(dest='S').encode('latin-1', 'replace')

# --- AUTHENTICATION ---
def check_password():
    if "logged_in" not in st.session_state:
        st.session_state["logged_in"] = False

    if not st.session_state["logged_in"]:
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.image("https://cdn-s1.lyreco.com/staticswebshop/pictures/looknfeel/FRFR/logo.svg", width=150)
            st.subheader("Lyreco WCAG Agent Login")
            user = st.text_input("User")
            pwd = st.text_input("Password", type="password")
            if st.button("Log in"):
                if user == "admin" and pwd == "admin2026":
                    st.session_state["logged_in"] = True
                    st.session_state["role"] = "admin"
                    st.rerun()
                elif user == "france" and pwd == "fr2026":
                    st.session_state["logged_in"] = True
                    st.session_state["role"] = "france"
                    st.rerun()
                else:
                    st.error("Invalid credentials")
        return False
    return True

# --- AI FUNCTIONS ---
def get_ai_recommendation(violation_data, page_context, screenshot_path=None):
    system_prompt = """
    You are a Senior Accessibility Specialist with IAAP certification.
    If an image is provided, use it to understand the visual context of the element in question.
    """
    html_context = violation_data.get('html_context', 'No DOM snippet available.')
    issue_desc = violation_data.get('desc', violation_data.get('help', 'Unknown issue'))
    
    prompt_text = f"""
    Analyze this WCAG violation found on the Lyreco {page_context} page.
    Issue: {issue_desc}
    
    DOM:
    ```html
    {html_context}
    ```
    
    Provide remediation plan strictly using Markdown:
    ### 👥 Affected User Groups
    ### 🚀 Quick Wins (< 1 day)
    ### 🔧 Needs Development (1-5 days)
    ### ⚙️ Needs Manual Testing
    """
    
    message_content = [{"type": "text", "text": prompt_text}]
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            message_content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": encode_image(screenshot_path)}})
        except Exception: pass

    try:
        msg = client.messages.create(
            model="claude-sonnet-4-6", 
            max_tokens=800,
            system="You are an expert in web accessibility and WCAG compliance. Always respond in English, regardless of the language of the input.",
            messages=[{"role": "user", "content": message_content}],
            temperature=0.1,
        )
        return msg.content[0].text
    except Exception as e: 
        return f"AI Advisor error: {str(e)}"

def run_guided_heuristics(screenshot_path, page_type):
    system_prompt = """
    You are an expert WCAG 2.2 Auditor performing a visual heuristic evaluation of a webpage screenshot.
    You must evaluate visible elements (images, contrast, layout logic).
    
    CRITICAL INSTRUCTION:
    You are confident, but you MUST NOT auto-resolve everything. You MUST explicitly flag exactly 1 or 2 items as "NEEDS_HUMAN". 
    Choose ambiguous items for manual review.
    
    Return ONLY a valid JSON array of objects with this structure (no markdown blocks, just raw JSON):
    [
      {
        "element": "Describe the element",
        "issue_type": "Image Alt / Contrast / Logical Layout",
        "ai_judgment": "PASS" | "FAIL" | "NEEDS_HUMAN",
        "reasoning": "Brief explanation."
      }
    ]
    """
    
    try:
        base64_image = encode_image(screenshot_path)
        message_content = [
            {"type": "text", "text": f"Perform heuristic visual analysis for this {page_type} page."},
            {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": base64_image}}
        ]
        
        msg = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": message_content}]
        )
        
        response_text = msg.content[0].text.strip()
        if response_text.startswith("```json"):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith("```"):
            response_text = response_text[3:-3].strip()
            
        return json.loads(response_text)
    except Exception as e:
        return [{"element": "System API", "issue_type": "Error", "ai_judgment": "FAIL", "reasoning": str(e)}]

# --- SELENIUM & AUDIT FUNCTIONS ---
def build_driver(viewport="desktop"):
    opts = Options()
    opts.add_argument("--headless")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    
    if viewport == "mobile":
        opts.add_argument("--window-size=375,812")
        opts.add_argument("--user-agent=Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1")
    elif viewport == "tablet":
        opts.add_argument("--window-size=768,1024")
    else:
        opts.add_argument("--window-size=1280,1024")
        
    return webdriver.Chrome(service=Service(shutil.which("chromedriver") or "/usr/bin/chromedriver"), options=opts)

@st.cache_data(ttl=3600)
def fetch_axe():
    return requests.get("https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.2/axe.min.js").text

def perform_full_audit(url, page_type, country, bypass_cookies=False, viewport="desktop"):
    lh, w_err, w_con, w3c_errors = 0, 0, 0, 0
    
    # Lighthouse
    try:
        r = requests.get(f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={urllib.parse.quote(url)}&category=accessibility&key={GOOGLE_KEY}").json()
        lh = r["lighthouseResult"]["categories"]["accessibility"]["score"] * 100
    except: pass
    
    # WAVE
    try:
        r = requests.get(f"https://wave.webaim.org/api/request?key={WAVE_KEY}&url={url}").json()
        w_err = r["categories"]["error"]["count"]
        w_con = r["categories"]["contrast"]["count"]
    except: pass

    # W3C Nu API
    try:
        w3_req = requests.get(f"https://validator.w3.org/nu/?doc={urllib.parse.quote(url)}&out=json")
        w3c_errors = sum(1 for m in w3_req.json().get("messages", []) if m.get("type") == "error")
    except: pass

    axe_data = {"violations": [], "counts": {"critical": 0, "serious": 0}}
    tab_issues = []
    advanced_issues = []
    shot = ""
    protanopia_shot = ""
    
    driver = build_driver(viewport)
    try:
        driver.get(url)
        time.sleep(5)
        
        if bypass_cookies:
            driver.execute_script("""
                let uc = document.getElementById('usercentrics-root');
                if (uc) { uc.remove(); }
                document.body.style.overflow = 'auto';
                document.body.style.position = 'static';
            """)
            time.sleep(2)
        
        # Optional: Cognitive accessibility (if textstat installed)
        if textstat:
            try:
                page_text = driver.execute_script("return document.body.innerText;")
                flesch_score = textstat.flesch_reading_ease(page_text)
                if flesch_score < 40:
                    advanced_issues.append({
                        "type": "cognitive_readability", 
                        "desc": f"Low cognitive accessibility. Text is difficult to read (Flesch score: {flesch_score}). Easier level required."
                    })
            except: pass

        # Axe-core
        driver.execute_script(fetch_axe())
        res = driver.execute_async_script("const cb = arguments[arguments.length - 1]; axe.run().then(r => cb(r));")
        violations = res.get("violations", [])
        axe_data = {
            "violations": violations, 
            "counts": {"critical": sum(1 for v in violations if v.get("impact") == "critical"), 
                       "serious": sum(1 for v in violations if v.get("impact") == "serious")}
        }
        
        # JAWS/Dragon support (ARIA vs Visible text conflicts)
        dragon_issues = driver.execute_script("""
            let issues = [];
            document.querySelectorAll('button, a, [role="button"]').forEach(el => {
                let visibleText = el.innerText.trim().toLowerCase();
                let ariaLabel = (el.getAttribute('aria-label') || '').toLowerCase();
                if (visibleText && ariaLabel && !ariaLabel.includes(visibleText)) {
                    issues.push({
                        type: "voice_control_blocker",
                        desc: `Dragon/JAWS Conflict: Visible text is "${visibleText}", but aria-label is "${ariaLabel}".`,
                        html_context: el.outerHTML.substring(0, 150)
                    });
                }
            });
            return issues.slice(0, 3); // Limit to first 3 for readability
        """)
        advanced_issues.extend(dragon_issues)

        # WCAG 2.2 Target Size
        target_issues = driver.execute_script("""
            let tinyElements = [];
            document.querySelectorAll('button, a, input, [tabindex="0"]').forEach(el => {
                let rect = el.getBoundingClientRect();
                if (rect.width > 0 && rect.height > 0) {
                    if (rect.width < 24 || rect.height < 24) {
                        tinyElements.push({
                            type: "wcag_22_target_size",
                            desc: `Element too small for touch interaction: ${Math.round(rect.width)}x${Math.round(rect.height)}px. Minimum is 24x24px.`,
                            html_context: el.outerHTML.substring(0, 150)
                        });
                    }
                }
            });
            return tinyElements.slice(0, 3);
        """)
        advanced_issues.extend(target_issues)
        
        # ZoomText Simulation (Reflow to 400%)
        zoom_issues = driver.execute_script("""
            document.body.style.zoom = "400%";
            let hasHorizontalScroll = document.documentElement.scrollWidth > window.innerWidth;
            let issues = [];
            if (hasHorizontalScroll) {
                issues.push({
                    type: "zoomtext_reflow_failure",
                    desc: "CRITICAL (ZoomText): Horizontal scrollbar appears when zoomed to 400%. Users with low vision may lose orientation."
                });
            }
            document.body.style.zoom = "100%";
            return issues;
        """)
        advanced_issues.extend(zoom_issues)

        # Keyboard Navigation (Tab)
        actions = ActionChains(driver)
        focused_elements = []
        
        for _ in range(30):
            actions.send_keys(Keys.TAB).perform()
            elem_data = driver.execute_script("""
                let el = document.activeElement;
                if (!el || el === document.body) return null;
                let rect = el.getBoundingClientRect();
                return {
                    tag: el.tagName.toLowerCase(),
                    html: el.outerHTML.substring(0, 300),
                    text: (el.innerText || el.getAttribute('aria-label') || '').substring(0, 40).trim(),
                    visible: (rect.width > 0 && rect.height > 0 && window.getComputedStyle(el).visibility !== 'hidden')
                };
            """)
            
            if elem_data:
                focused_elements.append(elem_data)
                if not elem_data['visible']:
                    issue = {"type": "hidden_focus", "desc": f"Hidden element received focus: <{elem_data['tag']}> {elem_data['text']}", "html_context": elem_data['html']}
                    if issue not in tab_issues: tab_issues.append(issue)

        # Keyboard trap detection
        if len(focused_elements) > 5:
            last_five = [e['tag'] + e['text'] for e in focused_elements[-5:]]
            if len(set(last_five)) == 1:
                trap = {"type": "keyboard_trap", "desc": f"Keyboard Trap detected in component: <{focused_elements[-1]['tag']}> {focused_elements[-1]['text']}", "html_context": focused_elements[-1]['html']}
                if trap not in tab_issues: tab_issues.append(trap)

        # Standard screenshot on errors
        if axe_data["counts"]["critical"] > 0 or len(tab_issues) > 0 or len(advanced_issues) > 0:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                driver.save_screenshot(tmp.name)
                shot = tmp.name
                
            # Use CDP for color blindness simulation (desktop only for clarity)
            if viewport == "desktop":
                driver.execute_cdp_cmd('Emulation.setEmulatedVisionDeficiency', {'type': 'protanopia'})
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_cb:
                    driver.save_screenshot(tmp_cb.name)
                    protanopia_shot = tmp_cb.name
                driver.execute_cdp_cmd('Emulation.setEmulatedVisionDeficiency', {'type': 'none'}) # Disable filter
                
    finally: driver.quit()

    wave_s = max(0, 100 - (w_err * 2 + w_con * 0.5))
    axe_s = max(0, 100 - (axe_data["counts"]["critical"] * 5 + axe_data["counts"]["serious"] * 2))
    
    # Penalties for advanced issues
    tab_penalty = len(tab_issues) * 5
    adv_penalty = len(advanced_issues) * 3
    w3c_penalty = w3c_errors * 0.5
    
    final = max(0, round((lh * 0.4) + (wave_s * 0.3) + (axe_s * 0.3) - tab_penalty - adv_penalty - w3c_penalty, 1))

    return {
        "Country": country, "Type": page_type, "Viewport": viewport, "Score": final, 
        "Critical": axe_data["counts"]["critical"], "Serious": axe_data["counts"]["serious"], "W3C_Errors": w3c_errors,
        "Tab_Issues_Count": len(tab_issues), "Tab_Issues_Details": str(tab_issues), 
        "Advanced_Issues_Count": len(advanced_issues), "Advanced_Issues_Details": str(advanced_issues),
        "URL": url, "Screenshot": shot, "Protanopia_Shot": protanopia_shot, "Violations": violations
    }

def run_widget_crash_test(url):
    driver = build_driver()
    report = {"url": url, "detected": False, "esc_works": False, "ghost_elements": False, "issues": []}

    try:
        driver.get(url)
        driver.delete_all_cookies()
        driver.refresh()
        time.sleep(4)
        
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(2)
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(2)
        try: ActionChains(driver).move_by_offset(1, 1).perform() 
        except: pass
        time.sleep(3)
        
        detected = driver.execute_script("""
            let scripts = Array.from(document.scripts).some(s => s.src.includes('getsitecontrol') || s.src.includes('usercentrics'));
            let containers = document.querySelectorAll('[id^="gsc-"], [class*="gsc-"], #usercentrics-root, [role="dialog"]');
            let anyOverlay = Array.from(document.body.children).some(el => {
                let style = window.getComputedStyle(el);
                return parseInt(style.zIndex) > 100 && style.display !== 'none' && style.visibility !== 'hidden';
            });
            return scripts || containers.length > 0 || anyOverlay;
        """)
        
        if not detected: return report
        report["detected"] = True
        
        ActionChains(driver).send_keys(Keys.ESCAPE).perform()
        time.sleep(2) 
        
        test_results = driver.execute_script("""
            let issues = []; let esc_worked = true; let ghosts = false;
            let widgets = document.querySelectorAll('[id^="gsc-"], [class*="gsc-"], #usercentrics-root, [role="dialog"]');
            
            widgets.forEach(w => {
                let rect = w.getBoundingClientRect();
                let isVisible = (rect.width > 0 && rect.height > 0 && window.getComputedStyle(w).visibility !== 'hidden' && window.getComputedStyle(w).opacity > '0');
                
                if (isVisible) {
                    esc_worked = false;
                    issues.push("CRITICAL: Widget ignores the 'Escape' key (Focus Trap).");
                } else {
                    let style = window.getComputedStyle(w);
                    if ((w.tabIndex >= 0 || w.tagName === 'DIV') && w.getAttribute('aria-hidden') !== 'true' && style.display !== 'none') {
                        let focusables = w.querySelectorAll('a, button, input, [tabindex="0"]');
                        if (focusables.length > 0 || w.tabIndex >= 0) {
                            ghosts = true; issues.push("CRITICAL: Widget creates an invisible 'Ghost' trapping focus.");
                        }
                    }
                }
            });
            if (window.getComputedStyle(document.body).overflow === 'hidden') issues.push("CRITICAL: Widget locked page scroll.");
            return {esc: esc_worked, ghosts: ghosts, issues: issues};
        """)
        
        report["esc_works"] = test_results["esc"]
        report["ghost_elements"] = test_results["ghosts"]
        report["issues"] = test_results["issues"]
    except Exception as e: report["issues"].append(f"System error: {str(e)}")
    finally: driver.quit()
    return report

# --- DASHBOARD UI ---
def display_results(df):
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Avg Score", f"{df['Score'].mean():.1f}")
    m2.metric("Critical", int(df["Critical"].sum()))
    m3.metric("Tab / Nav Errors", int(df.get("Tab_Issues_Count", pd.Series([0]*len(df))).sum()))
    m4.metric("Advanced / UX Issues", int(df.get("Advanced_Issues_Count", pd.Series([0]*len(df))).sum()))
    m5.metric("W3C HTML Errors", int(df.get("W3C_Errors", pd.Series([0]*len(df))).sum()))

    st.subheader("Market Compliance Heatmap")
    st.dataframe(df.pivot_table(index="Country", columns="Type", values="Score").style.background_gradient(cmap="RdYlGn", vmin=0, vmax=100), use_container_width=True)

    st.subheader("❌ Detailed Violations")
    v_rows = []
    for _, row in df.iterrows():
        violations = row["Violations"]
        if isinstance(violations, str):
            try: violations = ast.literal_eval(violations)
            except: violations = []
        for v in violations:
            v_rows.append({"Country": row["Country"], "Page": row["Type"].capitalize(), "Viewport": row.get("Viewport", "desktop"), "Impact": v.get("impact", "minor").capitalize(), "Description": v["help"]})
            
        tab_issues = row.get("Tab_Issues_Details", "[]")
        if isinstance(tab_issues, str):
            try: tab_issues = ast.literal_eval(tab_issues)
            except: tab_issues = []
        for t_issue in tab_issues:
            v_rows.append({"Country": row["Country"], "Page": row["Type"].capitalize(), "Viewport": row.get("Viewport", "desktop"), "Impact": "Critical", "Description": t_issue.get("desc", str(t_issue))})
            
        adv_issues = row.get("Advanced_Issues_Details", "[]")
        if isinstance(adv_issues, str):
            try: adv_issues = ast.literal_eval(adv_issues)
            except: adv_issues = []
        for a_issue in adv_issues:
            v_rows.append({"Country": row["Country"], "Page": row["Type"].capitalize(), "Viewport": row.get("Viewport", "desktop"), "Impact": "Critical", "Description": a_issue.get("desc", str(a_issue))})

    if v_rows:
        v_df = pd.DataFrame(v_rows)
        v_df["sort_idx"] = v_df["Impact"].map({"Critical": 0, "Serious": 1, "Moderate": 2, "Minor": 3}).fillna(4)
        st.dataframe(v_df.sort_values(by=["sort_idx", "Country"]).drop(columns=["sort_idx"]), use_container_width=True, hide_index=True)

    st.subheader("🧠 AI Accessibility Advisor (Claude 3.5 Sonnet)")
    for _, row in df.iterrows():
        violations = ast.literal_eval(row["Violations"]) if isinstance(row["Violations"], str) else row["Violations"]
        tab_issues = ast.literal_eval(row.get("Tab_Issues_Details", "[]")) if isinstance(row.get("Tab_Issues_Details"), str) else row.get("Tab_Issues_Details", [])
        adv_issues = ast.literal_eval(row.get("Advanced_Issues_Details", "[]")) if isinstance(row.get("Advanced_Issues_Details"), str) else row.get("Advanced_Issues_Details", [])

        if violations or tab_issues or adv_issues:
            with st.expander(f"Strategy: {row['Country']} - {row['Type'].capitalize()} ({row.get('Viewport', 'desktop')})"):
                shot = row.get("Screenshot") if row.get("Screenshot") != "" else None
                protanopia_shot = row.get("Protanopia_Shot") if row.get("Protanopia_Shot") != "" else None
                
                # Visual presentation with visual impairment simulation
                if shot or protanopia_shot:
                    img_cols = st.columns(2)
                    if shot and os.path.exists(shot): img_cols[0].image(shot, caption="Standard view screenshot")
                    if protanopia_shot and os.path.exists(protanopia_shot): img_cols[1].image(protanopia_shot, caption="Color blindness simulation (Protanopia)")
                
                # Prioritize displaying the issue for AI
                target_issue = None
                if tab_issues: target_issue = {"id": "keyboard-trap", "impact": "critical", "help": tab_issues[0].get('desc'), "html_context": tab_issues[0].get('html_context')}
                elif adv_issues: target_issue = {"id": "advanced-tech", "impact": "critical", "help": adv_issues[0].get('desc'), "html_context": adv_issues[0].get('html_context')}
                else: 
                    top_v = sorted(violations, key=lambda x: {"critical": 0, "serious": 1}.get(x.get("impact"), 4))[0] 
                    target_issue = {"id": top_v["id"], "impact": top_v.get("impact"), "help": top_v["help"], "html_context": top_v.get("nodes", [{}])[0].get("html", "")}

                st.write(f"**Issue:** {target_issue['help']}")
                st.code(target_issue.get("html_context", ""), language="html")
                
                if st.button("Get remediation recommendations from Claude", key=f"ai_btn_{row['Country']}_{row['Type']}_{row.get('Viewport', 'desktop')}"):
                    with st.spinner("Claude is analyzing the DOM and screenshots..."):
                        st.markdown(get_ai_recommendation(target_issue, row['Type'], shot))

# --- MAIN ---
if check_password():
    with st.sidebar:
        st.image("https://cdn-s1.lyreco.com/staticswebshop/pictures/looknfeel/FRFR/logo.svg", width=180)
        st.write(f"Role: **{st.session_state['role'].upper()}**")
        
        if "last_res" in st.session_state:
            st.divider()
            st.download_button("📥 CSV", data=st.session_state["last_res"].to_csv(index=False).encode('utf-8'), file_name="audit.csv", use_container_width=True)
            
            try:
                pdf_bytes = generate_w3c_pdf(st.session_state["last_res"])
                if pdf_bytes:
                    st.download_button("📄 PDF Report", data=pdf_bytes, file_name="Report.pdf", use_container_width=True)
            except Exception as e:
                st.error(f"Failed to generate PDF Report: {e}")
                
            try:
                stmt_bytes = generate_accessibility_statement_pdf(st.session_state["last_res"])
                if stmt_bytes:
                    st.download_button("📜 Statement", data=stmt_bytes, file_name="Statement.pdf", use_container_width=True)
            except Exception as e:
                st.error(f"Failed to generate Statement: {e}")
            
        if st.button("Logout", use_container_width=True):
            st.session_state["logged_in"] = False
            st.rerun()
      
    tab1, tab2, tab3, tab4 = st.tabs(["🚀 New Audit", "📂 History", "🎯 Widget Crash-Tester", "🧑‍💻 Guided Testing"])
    
    with tab1:
        c1, c2, c3 = st.columns(3)
        opts = list(COUNTRIES.keys()) if st.session_state["role"] == "admin" else ["France"]
        sel_c = c1.multiselect("Markets", opts, default=opts)
        sel_t = c2.multiselect("Pages", ["home", "category", "product"], default=["home"])
        sel_v = c3.selectbox("Device Resolution (Viewport)", ["desktop", "tablet", "mobile"])

        bypass = st.checkbox("🪄 Bypass Cookie Banner", value=True)

        # PROGRESS BAR WITH VISUALIZATION:
        if st.button("Run Audit", type="primary"):
            total_tasks = len(sel_c) * len(sel_t)
            
            if total_tasks == 0:
                st.warning("⚠️ Please select at least one market and page!")
            else:
                progress_bar = st.progress(0)
                status_text = st.empty()
                res = []
                
                current_task = 0
                for c in sel_c:
                    for t in sel_t:
                        status_text.info(f"🔍 Scanning device **{sel_v}**: market {c} - page {t.capitalize()}... (Analyzing Selenium, WAVE, axe, TargetSize, JAWS/Dragon)")
                        url_to_test = COUNTRIES[c].get(t, SSO_LOGIN)
                        
                        audit_result = perform_full_audit(url_to_test, t, c, bypass, sel_v)
                        res.append(audit_result)
                        
                        current_task += 1
                        progress_bar.progress(current_task / total_tasks)
                
                status_text.success("✅ Audit completed successfully!")
                time.sleep(1) # Leave 100% status briefly for the user
                status_text.empty()
                progress_bar.empty()
                
                st.session_state["last_res"] = pd.DataFrame(res)
                st.rerun()

        if "last_res" in st.session_state: display_results(st.session_state["last_res"])

    with tab2:
        up = st.file_uploader("Upload CSV")
        if up: 
            df = pd.read_csv(up)
            st.session_state["last_res"] = df
            display_results(df)

    with tab3:
        st.header("🎯 Widget Crash-Tester")
        t_url = st.text_input("URL to test:", "https://shop.lyreco.fr/fr")
        if st.button("🔍 Run Widget Test", type="primary"):
            with st.spinner("Provoking widgets..."):
                res = run_widget_crash_test(t_url)
                if not res["detected"]: st.warning("📭 No active widgets detected.")
                else:
                    st.success("🎯 Widgets detected!")
                    c1, c2 = st.columns(2)
                    if res["esc_works"]: c1.success("✅ Closes on ESC")
                    else: c1.error("❌ Fails ESC test")
                    if not res["ghost_elements"]: c2.success("✅ Clean DOM")
                    else: c2.error("❌ Leaves Ghosts")
                    for i in res["issues"]: st.error(i)

    with tab4:
        st.header("🧑‍💻 AI + Human Guided Testing")
        st.write("Artificial Intelligence (Claude) evaluates visual aspects of the page. Where context is ambiguous, it asks for your final auditor verdict.")
        
        gt_url = st.text_input("URL for manual verification:", "https://shop.lyreco.fr/fr", key="gt_url")
        
        if st.button("Run hybrid analysis", type="primary", key="btn_gt"):
            with st.spinner("Capturing screenshot and analyzing visually (Model: claude-3-5-sonnet)..."):
                driver = build_driver()
                gt_shot = ""
                try:
                    driver.get(gt_url)
                    time.sleep(5)
                    driver.execute_script("let uc = document.getElementById('usercentrics-root'); if(uc) uc.remove();")
                    time.sleep(1)
                    
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp:
                        driver.save_screenshot(tmp.name)
                        gt_shot = tmp.name
                finally:
                    driver.quit()
                
                st.image(gt_shot, caption="Analyzed view (Bypass Cookies enabled)", use_container_width=True)
                
                evaluations = run_guided_heuristics(gt_shot, "ecommerce")
                
                st.subheader("📋 Verification Card")
                
                if isinstance(evaluations, list):
                    for i, item in enumerate(evaluations):
                        with st.container():
                            st.markdown(f"**Element:** {item.get('element')} | **Type:** {item.get('issue_type')}")
                            judgment = item.get('ai_judgment')
                            
                            if judgment == "PASS":
                                st.success(f"🤖 AI: APPROVED - {item.get('reasoning')}")
                            elif judgment == "FAIL":
                                st.error(f"🤖 AI: REJECTED (Error) - {item.get('reasoning')}")
                            elif judgment == "NEEDS_HUMAN":
                                st.warning(f"🤔 AI is uncertain: {item.get('reasoning')}")
                                st.radio(
                                    "Your auditor decision for this element:", 
                                    ["Pass (Compliant)", "Fail (Non-compliant)"], 
                                    key=f"human_eval_{i}"
                                )
                            st.divider()
                    
                    st.button("💾 Save final verdict to report")
                else:
                    st.error("Error parsing JSON from the model. Please try again.")
